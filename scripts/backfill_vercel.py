#!/usr/bin/env python3
"""Backfill the existing Vercel-hosted doc pages into the doc-harness registry (#37).

Five subcommands over one append-only run directory:

    inventory   walk the Vercel listing, bounded, until two walks agree or the bound is hit
    map         identify each document by hashing its LIVE bytes against git history, then
                record the publish TARGET at the remote tip
    stage       compare the target bytes to Vercel, then publish under a staging label and
                verify what the harness serves
    activate    re-validate, then CAS-publish the production name and verify it
    report      assert every row ended live or flagged, then write the report

Design: `docs/planning/2026-08-24-37-vercel-backfill.md`.

**Provenance and target are DIFFERENT questions, and conflating them defeats the feature.** The
hash match against history answers "which document is this page" — it necessarily matches the live
Vercel bytes, so comparing that same blob back against Vercel is a tautology and would migrate the
stale version of every drifted document. The publish TARGET is the document's current committed
page at the remote tip, and the compare is target-versus-Vercel, which is a real question.

**`--execute` gates REGISTRY mutations, and only those.** Every command writes local artifacts
under its own run directory — that is what a resumable campaign is made of, and `inventory` could
not otherwise start, since it is the command that produces the first digest. No `POST` reaches the
control API without an explicit `--execute` carrying the digest of the exact plan being executed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time

# The publication purposes of the `{project}-{purpose}-{ref}` convention, which is what the old
# Vercel project names carry. Copied deliberately rather than imported: `publish_doc.py` is out of
# scope for this child, and a drift here is caught by a test that compares the two lists.
PURPOSES = ("design", "plan", "uat", "audit", "report", "runbook", "analysis", "spec",
            "tokens", "map", "deck")

# Row outcomes. Exactly two, because the acceptance criterion says "activated or flagged" — a
# third bucket for drift would satisfy neither.
LIVE = "live"
FLAGGED = "flagged"

# Every flag reason. A closed vocabulary, so a report cannot invent a state, and a transport
# failure can never be recorded as a content verdict.
REASONS = (
    "mapping_not_found",
    "mapping_ambiguous",
    "mapping_invalid",
    "uncommitted_or_unreachable",
    "source_unavailable",
    "vercel_changed",
    "byte_mismatch",
    "target_name_collision",
    "stage_publish_failed",
    "target_occupied",
    "cas_conflict",
    "final_verification_failed",
    "plan_expired",
    "harness_fetch_denied",
    "skipped_by_reviewer",
)

# NOT a flag reason: a row the run never attempted has no outcome at all. Forcing a sampled-out
# row into a reason that does not describe it would be a lie in the report, so the report counts
# these separately and the completeness assertion is scoped to what was PROCESSED.
NOT_ATTEMPTED = "not_attempted"

# Campaign-level, NOT a row outcome: a truncated or invalid listing is not a property of any one
# project, and reporting a partial walk as a complete campaign would be a lie.
INVENTORY_FAILED = "inventory_failed"

# One walk of a hundred-per-page listing over ~181 projects is two pages. A hundred is four
# hundred times that, so hitting it means the cursor is broken, not that the account is large.
MAX_PAGES_PER_WALK = 100


class Refused(Exception):
    """A gate refused. Never a bug — the refusal IS the feature."""


class CampaignFailed(Exception):
    """The whole campaign stops. NOT a row outcome.

    A truncated or invalid listing is not a property of any one project, so recording it against a
    row — or worse, continuing with a partial walk — would report an incomplete campaign as a
    complete one.
    """

    def __init__(self, outcome: str, detail: str = ""):
        super().__init__(f"{outcome}: {detail}" if detail else outcome)
        self.outcome = outcome
        self.detail = detail


class RowError(Exception):
    """One row failed. Carries its reason so the journal records a vocabulary term, not prose."""

    def __init__(self, reason: str, detail: str = ""):
        if reason not in REASONS:
            raise AssertionError(f"{reason!r} is not one of the closed flag reasons")
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def digest(obj) -> str:
    """sha256 over canonical JSON: key order cannot change it, value order can.

    The plan digests are what stop a stale human review being replayed against a file that has
    since changed, so this must be stable for the same content and different for different
    content — including a reordered list, which IS different content.
    """
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def require_execute(*, execute: str | None, expected: str, what: str) -> None:
    """Refuse unless the caller passed `--execute <the exact digest>`.

    Two separate refusals on purpose. A missing flag means "you did not ask to write"; a wrong
    digest means "what you reviewed is not what is on disk", and telling those apart is the
    difference between a typo and a stale plan.
    """
    if not execute:
        raise Refused(
            f"refusing to write: {what} would be executed, so pass --execute {expected} "
            f"(read-only is the default, and no registry is touched without it)")
    if execute != expected:
        raise Refused(
            f"refusing to write: --execute {execute} does not match the current {what} digest "
            f"{expected}. Something changed since it was reviewed — re-read it, do not re-run.")


class RunDir:
    """One run's directory: an append-only journal, plus whatever the phases persist.

    An existing directory is REUSED, never clobbered. A resumable campaign whose ledger a re-run
    silently truncated would be worse than one that never resumed.
    """

    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.journal_path = self.path / "journal.jsonl"

    def journal(self, row: str, record: dict) -> None:
        """Append one entry. Never rewrites, never seeks — evidence only accumulates."""
        entry = {"row": row, "at": int(time.time()), "record": record}
        with open(self.journal_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")

    def journal_entries(self) -> list:
        if not self.journal_path.exists():
            return []
        out = []
        for line in self.journal_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def write_json(self, name: str, obj) -> pathlib.Path:
        target = self.path / name
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                       encoding="utf-8")
        os.replace(tmp, target)
        return target

    def read_json(self, name: str):
        target = self.path / name
        if not target.exists():
            raise Refused(f"{target} does not exist — run the earlier phase first")
        return json.loads(target.read_text(encoding="utf-8"))


def _default_cli(argv):
    """The real subprocess seam. Returns (returncode, stdout, stderr) and never raises for a
    non-zero exit — the caller decides what a failure means."""
    proc = subprocess.run(argv, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def _one_walk(runner) -> list:
    """One complete walk of the Vercel listing, following `pagination.next` to exhaustion.

    Every failure here is `inventory_failed`, never an empty list. A partial walk that read as
    "there are no projects" would activate nothing and report success, which is the worst possible
    way for this to break.
    """
    rows, nxt, pages, seen_cursors = [], None, 0, set()
    while True:
        pages += 1
        if pages > MAX_PAGES_PER_WALK:
            raise CampaignFailed(INVENTORY_FAILED,
                                 f"the listing returned more than {MAX_PAGES_PER_WALK} pages; the "
                                 "walk bound applies to COMPLETE walks, so a cursor that never "
                                 "ends would otherwise spin here for ever and neither --max-walks "
                                 "nor an elapsed-time cutoff could fire")
        argv = ["vercel", "project", "list", "-F", "json", "--limit", "100"]
        if nxt:
            argv += ["--next", str(nxt)]
        code, out, err = runner(argv)
        if code != 0:
            raise CampaignFailed(INVENTORY_FAILED,
                                 f"`vercel project list` exited {code}: {(err or '').strip()}")
        try:
            payload = json.loads(out)
        except (ValueError, TypeError) as exc:
            raise CampaignFailed(INVENTORY_FAILED,
                                 f"the listing was not JSON: {exc}") from None
        projects = payload.get("projects") if isinstance(payload, dict) else None
        if not isinstance(projects, list):
            raise CampaignFailed(INVENTORY_FAILED,
                                 "the listing carries no `projects` array, so it cannot be read "
                                 "as an inventory")
        for item in projects:
            rows.append({"id": item.get("id"), "name": item.get("name"),
                         "latestProductionUrl": item.get("latestProductionUrl"),
                         "updatedAt": item.get("updatedAt")})
        nxt = (payload.get("pagination") or {}).get("next")
        if not nxt:
            break
        if nxt in seen_cursors:
            raise CampaignFailed(INVENTORY_FAILED,
                                 f"the listing repeated the cursor {str(nxt)[:24]!r}, so it is "
                                 "cycling rather than paginating")
        seen_cursors.add(nxt)
    # Sorted, because the listing's own order may vary between walks and convergence has to mean
    # "the same set", not "the same order the server happened to answer in".
    return sorted(rows, key=lambda r: (str(r.get("name")), str(r.get("id"))))


def inventory(run: RunDir, *, runner=None, max_walks: int = 3) -> dict:
    """Walk the listing until two consecutive walks agree, or the bound is hit.

    A paginated walk cannot establish an atomic set at an instant, so a converged snapshot is the
    strongest claim available and a non-converged one is recorded as a CUTOFF bounded by two
    instants — never as a moment. Sessions in this workspace publish continuously, so this is the
    normal case, not a corner.
    """
    runner = runner or _default_cli
    started = int(time.time())
    previous, walks = None, 0
    while walks < max(1, int(max_walks)):
        rows = _one_walk(runner)
        walks += 1
        if previous is not None and digest(previous) == digest(rows):
            snapshot = {"rows": rows, "walks": walks, "converged": True, "cutoff": False,
                        "started_at": started, "completed_at": int(time.time())}
            snapshot["digest"] = digest(rows)
            run.write_json("inventory.json", snapshot)
            run.journal("_campaign", {"phase": "inventory", "converged": True,
                                      "rows": len(rows), "walks": walks})
            return snapshot
        previous = rows
    snapshot = {"rows": previous or [], "walks": walks, "converged": False, "cutoff": True,
                "started_at": started, "completed_at": int(time.time())}
    snapshot["digest"] = digest(snapshot["rows"])
    run.write_json("inventory.json", snapshot)
    run.journal("_campaign", {"phase": "inventory", "converged": False, "cutoff": True,
                              "rows": len(snapshot["rows"]), "walks": walks})
    return snapshot


def _cmd_inventory(args, run) -> int:
    snapshot = inventory(run, max_walks=args.max_walks)
    kind = "converged" if snapshot["converged"] else "CUTOFF (walks never agreed)"
    print(f"inventory: {len(snapshot['rows'])} rows, {snapshot['walks']} walk(s), {kind}")
    print(f"inventory digest: {snapshot['digest']}")
    return 0


# --------------------------------------------------------------------------------------------
# T3 — provenance. The name NARROWS; the bytes DECIDE.
# --------------------------------------------------------------------------------------------


def viable_splits(name: str, known_projects) -> list:
    """EVERY `{project}-{purpose}-{ref}` split whose project exists. Not the first one.

    Taking the first purpose-looking token was a confirmed review finding: a project name can
    contain a purpose word (`rawgentic-plan-roadmap-v2`) and a ref can BE a purpose token, so the
    first plausible split can name a real but WRONG project and exclude the true source from the
    search entirely. Returning all of them, and searching their union, is what makes the hash the
    evidence rather than the name.
    """
    if not isinstance(name, str) or not name:
        return []
    known = set(known_projects or ())
    tokens = name.split("-")
    out = []
    for index, token in enumerate(tokens):
        if token not in PURPOSES or index == 0 or index == len(tokens) - 1:
            continue
        project = "-".join(tokens[:index])
        ref = "-".join(tokens[index + 1:])
        if project in known and ref:
            out.append((project, token, ref))
    return out


def _header(headers, name: str):
    """Case-insensitive header lookup. HTTP/2 lowercases names, which already bit #36 once."""
    for key, value in (headers or {}).items():
        if str(key).lower() == name.lower():
            return value
    return None


def fetch_live(url: str, *, opener, timeout: int = 30) -> bytes:
    """The live page's bytes, or `source_unavailable`.

    Requesting `Accept-Encoding: identity` is a PREFERENCE; an origin or an intermediary may ignore
    it. So the response is checked too — hashing a gzip stream would produce a confident, wrong
    mapping and a confident, wrong drift verdict. Every transport failure lands on
    `source_unavailable` and never on a content verdict: "I could not read it" is not "it differs".
    """
    try:
        status, headers, body = opener(
            url, headers={"Accept-Encoding": "identity", "User-Agent": "backfill-vercel/1"},
            method="GET", timeout=timeout)
    except Exception as exc:                                   # noqa: BLE001 - see docstring
        raise RowError("source_unavailable",
                       f"{type(exc).__name__} fetching {url}: {exc}") from None
    if status != 200:
        raise RowError("source_unavailable", f"HTTP {status} fetching {url}")
    encoding = (_header(headers, "Content-Encoding") or "").strip().lower()
    if encoding not in ("", "identity"):
        raise RowError("source_unavailable",
                       f"{url} answered with Content-Encoding {encoding!r} despite an identity "
                       "request, so these bytes are not the page's bytes and hashing them would "
                       "produce a confident wrong answer")
    return body


def _git_out(repo, argv, *, runner=None):
    runner = runner or _default_cli
    code, out, err = runner(["git", "-C", str(repo), *argv])
    if code != 0:
        raise RowError("uncommitted_or_unreachable",
                       f"git {' '.join(argv)} failed in {repo}: {(err or '').strip()}")
    return out


def _git_bytes(repo, argv):
    proc = subprocess.run(["git", "-C", str(repo), *argv], capture_output=True)
    if proc.returncode != 0:
        raise RowError("uncommitted_or_unreachable",
                       f"git {' '.join(argv)} failed in {repo}: "
                       f"{proc.stderr.decode('utf-8', 'replace').strip()}")
    return proc.stdout


# One full-history walk per REPOSITORY, not per (repository, ref). Process-scoped and never
# invalidated, which is correct for a one-shot CLI run and would be wrong for a long-lived process:
# a commit landing mid-run would not be seen. Stated because the next reader will wonder. Measured need: a sample of ten
# rows across thirty repositories would otherwise run three hundred whole-history walks, and this
# repository's own history is not small. The cache is per process and keyed by the resolved path.
_HTML_PATHS_CACHE: dict = {}


def all_html_paths(repo, *, runner=None) -> list:
    """Every `.html` path ever present in this repository's history, cached.

    `--all` and `--name-only` over history, because most of these pages were published from a
    commit that is now old and a search of `HEAD` alone would miss them entirely.
    """
    key = str(pathlib.Path(repo).resolve())
    if key in _HTML_PATHS_CACHE:
        return _HTML_PATHS_CACHE[key]
    out = _git_out(repo, ["log", "--all", "--pretty=format:", "--name-only"], runner=runner)
    seen, paths = set(), []
    for line in out.splitlines():
        line = line.strip()
        if not line or line in seen or not line.endswith(".html"):
            continue
        seen.add(line)
        paths.append(line)
    _HTML_PATHS_CACHE[key] = paths
    return paths


def candidate_paths(repo, ref: str, *, runner=None) -> list:
    """The cached path list, filtered by the ref. A NARROWING, nothing more."""
    needle = str(ref).lower()
    out = []
    for line in all_html_paths(repo, runner=runner):
        parts = line.lower().split("/")
        if needle in parts[-1] or any(needle in part for part in parts[:-1]):
            out.append(line)
    return out


def is_git_repository(path) -> bool:
    """Is this a git repository at all?

    A plain directory cannot hold a committed blob, so failing to search it says nothing about
    uniqueness. Conflating "not a repository" with "a repository I could not search" made one stray
    directory in the workspace block every row — measured on the live run.
    """
    proc = subprocess.run(["git", "-C", str(path), "rev-parse", "--git-dir"],
                          capture_output=True, text=True)
    return proc.returncode == 0


def blob_present(repo, *, sha256_hex: str, size: int) -> bool:
    """Is a blob with these exact bytes anywhere in this repository's object store?

    `--batch-all-objects --batch-check` lists every object with its size, so filtering by size and
    hashing only the survivors is exact and cheap — and it does NOT depend on the path narrowing.
    That matters: the collision check used to search only ref-bearing paths, so identical bytes at a
    differently named path in another repository were invisible and a non-unique match was reported
    as unique. A Critical-adjacent High, and it was right.
    """
    # `--batch-check=<format>` with the EQUALS SIGN. Passing the format as a separate argument
    # fails with "batch modes take no arguments" in every repository, which is exactly what
    # happened on the live run: essentially every workspace entry came back unsearchable and every
    # row became `mapping_ambiguous` for a reason that was entirely my own bug. The unit test did
    # not catch it because it asserted the ambiguous OUTCOME, which the failure also produced.
    proc = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "--batch-all-objects",
         "--batch-check=%(objectname) %(objecttype) %(objectsize)"],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise RowError("uncommitted_or_unreachable",
                       f"git cat-file --batch-all-objects failed in {repo}: "
                       f"{proc.stderr.strip()[:200]}")
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) != 3 or parts[1] != "blob":
            continue
        try:
            if int(parts[2]) != int(size):
                continue
        except ValueError:
            continue
        body = _git_bytes(repo, ["cat-file", "blob", parts[0]])
        if hashlib.sha256(body).hexdigest() == sha256_hex:
            return True
    return False


def history_candidates(repo, *, ref: str, target: bytes, cap: int = 2000,
                       report_cap: bool = False, runner=None):
    """Every committed blob under a ref-bearing path whose bytes hash to the target.

    Bounded by `cap` commits per path, and whether the cap was HIT is returned rather than
    swallowed: a capped search reported as exhaustive is how a `mapping_not_found` becomes a lie.
    """
    want = hashlib.sha256(target).hexdigest()
    found, capped = [], False
    seen_blobs = set()
    for path in candidate_paths(repo, ref, runner=runner):
        commits = _git_out(repo, ["log", "--all", "--format=%H", "--", path],
                           runner=runner).split()
        if len(commits) > cap:
            capped = True
            commits = commits[:cap]
        for commit in commits:
            try:
                blob_id = _git_out(repo, ["rev-parse", f"{commit}:{path}"], runner=runner).strip()
            except RowError:
                continue                      # the path did not exist at that commit
            if not blob_id or blob_id in seen_blobs:
                continue
            seen_blobs.add(blob_id)
            body = _git_bytes(repo, ["cat-file", "blob", blob_id])
            if hashlib.sha256(body).hexdigest() == want:
                found.append({"commit": commit, "repo_path": path, "blob_id": blob_id,
                              "sha256": want, "size": len(body)})
    return (found, capped) if report_cap else found


def find_workspace_file(start=None):
    """Walk UP for `.rawgentic_workspace.json`, rather than counting `parents[]` positions.

    Counting was wrong by one on the first try — `parents[2]` is the projects directory, not the
    workspace root — and a hard-coded index is wrong again the moment the layout moves. Walking up
    is the same amount of code and cannot be off by one.
    """
    here = pathlib.Path(start or __file__).resolve()
    for candidate in [here, *here.parents]:
        target = candidate / ".rawgentic_workspace.json"
        if target.is_file():
            return str(target)
    raise Refused("no .rawgentic_workspace.json found above "
                  f"{here} — pass --workspace-file explicitly")


def load_projects(workspace_file) -> dict:
    """`{name: absolute path}` from the rawgentic workspace file.

    Relative paths resolve against the workspace file's own directory, which is what the workspace
    format means by them — resolving against the cwd would silently point at nothing.
    """
    path = pathlib.Path(workspace_file).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for entry in data.get("projects") or []:
        name, where = entry.get("name"), entry.get("path")
        if not name or not where:
            continue
        target = pathlib.Path(where)
        out[name] = str(target if target.is_absolute() else (path.parent / target).resolve())
    return out


def _target_at_tip(repo, repo_path: str, *, fetch_remote: bool, runner=None) -> dict:
    """The document's CURRENT committed page, which is what a migration should serve.

    A local remote-tracking ref is not evidence about the remote, so the default fetches first.
    Passing `fetch_remote=False` is for tests over a repository with no remote at all — never a
    way to skip the freshness proof on a real run.
    """
    if fetch_remote:
        _git_out(repo, ["fetch", "--quiet", "origin"], runner=runner)
        tip = ""
        for ref in ("origin/HEAD", "origin/main", "origin/master"):
            try:
                tip = _git_out(repo, ["rev-parse", ref], runner=runner).strip()
                break
            except RowError:
                continue
        if not tip:
            raise RowError("uncommitted_or_unreachable",
                           "no origin/HEAD, origin/main or origin/master in this repository, so "
                           "there is no remote tip to pin — and a local ref is not evidence about "
                           "the remote")
    else:
        tip = _git_out(repo, ["rev-parse", "HEAD"], runner=runner).strip()
    blob_id = _git_out(repo, ["rev-parse", f"{tip}:{repo_path}"], runner=runner).strip()
    body = _git_bytes(repo, ["cat-file", "blob", blob_id])
    md_path = repo_path[: -len(".html")] + ".md"
    try:
        md_blob = _git_out(repo, ["rev-parse", f"{tip}:{md_path}"], runner=runner).strip()
    except RowError:
        raise RowError("uncommitted_or_unreachable",
                       f"{md_path} is not committed at {tip[:7]}; every surface in this project "
                       "says the .md and the .html ship together") from None
    return {"commit": tip, "repo_path": repo_path, "blob_id": blob_id,
            "sha256": hashlib.sha256(body).hexdigest(), "size": len(body),
            "md_path": md_path, "md_blob_id": md_blob,
            "preview": body.decode("utf-8", "replace")[:64]}


def enforce_name_uniqueness(rows: list) -> list:
    """Two rows resolving to ONE harness name are BOTH flagged, before anything is staged.

    Not "the second one loses": whichever went second would replace the first under a name people
    trust, and the API cannot deactivate, so there would be no way back. Refusing both makes a
    human choose.
    """
    counts = {}
    for row in rows:
        name = row.get("harness_name")
        if name:
            counts[name] = counts.get(name, 0) + 1
    for row in rows:
        if row.get("reason"):
            continue
        if counts.get(row.get("harness_name"), 0) > 1:
            row["reason"] = "target_name_collision"
            row["detail"] = (f"{counts[row['harness_name']]} rows resolve to the harness name "
                             f"{row['harness_name']!r}; neither is staged until a human picks one")
    return rows


def map_rows(snapshot: dict, *, workspace_file, opener, run: RunDir, history_cap: int = 2000,
             fetch_remote: bool = True, limit=None) -> list:
    """One mapping row per inventory row. Provenance from the bytes; target from the tip.

    Every row carries its IMMUTABLE inventory binding — the project id, the name and the
    snapshotted URL — because a later phase re-reads this file after a human has edited it, and
    without that binding an edit could keep a perfectly valid blob while pointing it at a different
    source or a different trusted name.
    """
    projects = load_projects(workspace_file)
    rows = []
    # `--limit` IS the sample selection rule: the first N of the snapshot in its recorded order, so
    # which rows ran is reproducible from the artifacts rather than remembered.
    entries = snapshot.get("rows") or []
    if limit is not None:
        entries = entries[:int(limit)]
    for entry in entries:
        row = {"inventory": {"id": entry.get("id"), "name": entry.get("name"),
                             "url": entry.get("latestProductionUrl")},
               "harness_name": entry.get("name"),
               "splits": [list(s) for s in viable_splits(entry.get("name"), projects)],
               "reason": None, "detail": ""}
        try:
            url = entry.get("latestProductionUrl")
            if not url:
                raise RowError("source_unavailable",
                               "the listing carries no latestProductionUrl for this project, so "
                               "there is nothing to compare against")
            live = fetch_live(url, opener=opener)
            # EVERY project is searched, always. The name only narrows which PATHS are worth
            # looking at inside each repository (the ref), because the workspace-wide collision
            # check is what makes a unique match trustworthy — searching only the narrowed project
            # would let the same bytes sit unnoticed in another repository and report a confident
            # unique answer. That was a confirmed review finding, not a hypothetical.
            refs = [r for _, _, r in row["splits"]] or [str(entry.get("name") or "")]
            candidates, capped, unsearchable, not_repos = [], False, [], []
            row["unsearchable"], row["not_repositories"] = unsearchable, not_repos
            for project in dict.fromkeys(list(projects)):
                repo = projects[project]
                if not is_git_repository(repo):
                    not_repos.append(project)
                    continue
                try:
                    for ref in dict.fromkeys(refs):
                        found, hit = history_candidates(repo, ref=ref, target=live,
                                                        cap=history_cap, report_cap=True)
                        capped = capped or hit
                        for item in found:
                            candidates.append(dict(item, project=project))
                except RowError as exc:
                    # A directory that cannot be searched is a property of the WORKSPACE, not of
                    # the document being mapped. Found by the live sample run: one workspace entry
                    # was not a git repository at all, and charging it to the row flagged all ten
                    # rows `uncommitted_or_unreachable` with nothing wrong with any of them.
                    unsearchable.append(project)
                    continue
            row["history_capped"] = capped
            # Dedup by (project, path, blob): the same blob reached through two refs is one answer.
            unique = {(c["project"], c["repo_path"], c["blob_id"]): c for c in candidates}
            candidates = list(unique.values())
            if not candidates:
                raise RowError(
                    "mapping_not_found",
                    "no committed blob in the workspace hashes to the live bytes"
                    + (" (the history search hit its cap, so this is not exhaustive)"
                       if capped else "")
                    + (f" — and {len(unsearchable)} workspace entries could not be searched at all: "
                       + ", ".join(sorted(unsearchable)) if unsearchable else ""))
            if len({(c["project"], c["repo_path"]) for c in candidates}) > 1:
                row["candidates"] = candidates
                raise RowError("mapping_ambiguous",
                               f"{len(candidates)} committed blobs hash to the live bytes")
            # F4: uniqueness is proven against every blob in every repository, not against the
            # ref-narrowed paths the search used. F5: a repository that could not be searched means
            # uniqueness is UNPROVEN, and unproven is ambiguous, not unique.
            match = candidates[0]
            elsewhere = []
            for project in dict.fromkeys(list(projects)):
                if project == match["project"]:
                    continue
                if not is_git_repository(projects[project]):
                    # Same rule as the search loop above: a plain directory holds no blobs, so its
                    # unsearchability is not evidence about uniqueness.
                    if project not in not_repos:
                        not_repos.append(project)
                    continue
                try:
                    if blob_present(projects[project], sha256_hex=match["sha256"],
                                    size=len(live)):
                        elsewhere.append(project)
                except RowError:
                    if project not in unsearchable:
                        unsearchable.append(project)
            if elsewhere:
                row["candidates"] = candidates + [{"project": p, "note": "same bytes present"}
                                                  for p in elsewhere]
                raise RowError("mapping_ambiguous",
                               "the same bytes are also committed in " + ", ".join(elsewhere))
            if unsearchable:
                row["candidates"] = candidates
                raise RowError("mapping_ambiguous",
                               "uniqueness is UNPROVEN: these workspace entries could not be "
                               "searched at all — " + ", ".join(sorted(unsearchable))
                               + " — so the same bytes may sit in one of them")
            row["unsearchable"] = unsearchable
            row["not_repositories"] = not_repos
            row["provenance"] = {k: match[k] for k in
                                 ("project", "commit", "repo_path", "blob_id", "sha256")}
            row["target"] = _target_at_tip(projects[match["project"]], match["repo_path"],
                                           fetch_remote=fetch_remote)
            row["target"]["project"] = match["project"]
        except RowError as exc:
            row["reason"] = exc.reason
            row["detail"] = exc.detail
        rows.append(row)
        run.journal(str(row["inventory"]["name"]),
                    {"phase": "map", "reason": row["reason"], "detail": row["detail"][:400]})
    rows = enforce_name_uniqueness(rows)
    mapping = {"rows": rows, "inventory_digest": snapshot.get("digest"),
               # The selection is RECORDED, so the report can tell "sampled out" from "a row went
               # missing". Without it every absent row read as a deliberate sample, which would let
               # a truncated or corrupt mapping satisfy the completeness assertion silently.
               "selection": {"limit": (int(limit) if limit is not None else None),
                             "rule": "the first N of the snapshot in its recorded order",
                             "snapshot_rows": len(snapshot.get("rows") or [])}}
    mapping["digest"] = digest(rows)
    run.write_json("mapping.json", mapping)
    return rows


def _cmd_map(args, run) -> int:
    snapshot = run.read_json("inventory.json")
    workspace = args.workspace_file or find_workspace_file()
    rows = map_rows(snapshot, workspace_file=workspace, opener=_http, run=run,
                    history_cap=args.history_cap, limit=args.limit)
    mapped = sum(1 for r in rows if not r.get("reason"))
    print(f"map: {mapped} mapped, {len(rows) - mapped} flagged, of {len(rows)} rows")
    for reason in REASONS:
        count = sum(1 for r in rows if r.get("reason") == reason)
        if count:
            print(f"  {reason}: {count}")
    print(f"mapping digest: {run.read_json('mapping.json')['digest']}")
    print("REVIEW claude_docs mapping.json by hand before staging — that is the point of it.")
    return 0


def _http(url, *, headers=None, method="GET", body=None, timeout=30):
    """The real HTTP seam. Returns (status, headers, body) and never follows a redirect.

    No redirect handler at all, deliberately: a 302 would send whatever headers this carries to
    whatever host the redirect names, and one of those headers can be a bearer token.
    """
    import urllib.error
    import urllib.request
    # ProxyHandler({}) is not decoration: build_opener installs urllib's ENVIRONMENT proxy handler
    # by default, so an http_proxy in the environment would receive this request — and one of its
    # headers can be a bearer. The destination guard claims proxies are refused; this is what
    # makes that claim true.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
    request = urllib.request.Request(url, method=method, data=body)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read()


class _NoRedirect(__import__("urllib.request", fromlist=["HTTPRedirectHandler"])
                  .HTTPRedirectHandler):
    """Refuses every redirect. `urlopen` follows a 302 silently, which is how a token leaves."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        raise RowError("source_unavailable",
                       f"refusing to follow a {code} redirect to {newurl}: a redirect can move a "
                       "request to a host this run never authorized")


# --------------------------------------------------------------------------------------------
# T4 — staging. Compare first; a failing compare must publish NOTHING.
# --------------------------------------------------------------------------------------------

_LOOPBACK_V4 = "127."


class ControlError(Exception):
    """A non-2xx from the control API. Carries the status, because the status IS the meaning."""

    def __init__(self, status: int, detail: str = ""):
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


def assert_control_destination(base: str, env=None) -> None:
    """Where the publish bearer may go. Checked BEFORE `Authorization` is attached.

    This client cannot use `publish_doc.assert_bearer_destination` — that allowlist and the
    harness's own Host routing cannot both be satisfied, which is the whole reason this script has
    its own client — so it carries an equivalent rather than dropping the guard. An IP LITERAL is
    required: a DNS name is resolved by somebody else, and "it points at loopback today" is not a
    property of the URL.
    """
    import ipaddress
    import urllib.parse
    env = os.environ if env is None else env
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme != "http":
        raise Refused(f"refusing {base!r}: the control base must be http with an IP literal "
                      "(https to a name is a different guard, and this client does not have it)")
    host = (parsed.hostname or "").strip()
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        raise Refused(
            f"refusing {base!r}: the host must be an IP literal, not the name {host!r}. A name is "
            "resolved by something this run does not control, so 'it points at loopback' is not a "
            "property of the URL — and the bearer would go wherever it resolved.") from None
    if address.is_loopback:
        return
    granted = str(env.get("BACKFILL_ALLOW_PLAINTEXT") or "").strip().lower()
    if granted and granted == (parsed.netloc or "").lower():
        return
    raise Refused(
        f"refusing to send the publish bearer to {parsed.netloc}: it is not loopback. To allow "
        f"exactly this endpoint, set BACKFILL_ALLOW_PLAINTEXT={parsed.netloc} — a bare truthy "
        "value grants nothing, because a range is not the one host you meant.")


def staging_label(run_id: str, name: str, attempt: int) -> str:
    """`bf<run>-<12 hex of sha256(name)>-<attempt>`: fixed length, and injective.

    Right-truncating the real name is NOT injective — two long names sharing a prefix produce one
    label, and the second row would fail as "already exists" although the uniqueness check passed.
    The attempt counter is what lets a renewal after an expiry take a fresh label instead of
    colliding with its own previous one.
    """
    short = hashlib.sha256(str(name).encode("utf-8")).hexdigest()[:12]
    run_part = "".join(ch for ch in str(run_id).lower() if ch.isalnum())[:12] or "r"
    label = f"bf{run_part}-{short}-{int(attempt)}"
    return label[:63].rstrip("-")


def _safe_detail(payload, token: str) -> str:
    """A response body reduced to something safe to journal.

    Truncating is NOT sanitizing — a review finding, and it was right: a server that reflects the
    `Authorization` header near the start of its body would put bearer material into the first 200
    characters, straight into the append-only journal. So the body is matched against a small set of
    KNOWN harness messages and otherwise reduced to its shape, and the token is scrubbed either way
    as a belt-and-braces pass.
    """
    text = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else str(payload or "")
    text = text.strip()

    def scrub(value: str) -> str:
        # Only a token long enough to BE a secret is scrubbed. A test caught the first version
        # replacing every letter of a one-character test token, which both inflated the string and
        # destroyed the phrases this function matches on.
        return value.replace(token, "<redacted>") if token and len(token) >= 8 else value

    known = ("does not exist", "stale publisher", "url_path", "content_type", "name is required",
             "could not read the repository", "manifest", "blob", "sha256", "size")
    lowered = text.lower()
    if any(phrase in lowered for phrase in known):
        # Keep the first line only, which is where the harness puts its own message, and only when
        # it looks like one of its messages rather than an arbitrary reflection.
        return scrub(text.splitlines()[0][:200])
    return (f"a {len(text)}-character response body that matches none of the harness's known "
            "messages; it is deliberately NOT reproduced, because a reflected request header "
            "would land in the journal")


class ControlClient:
    """The harness control API over an explicit Host header.

    The bearer is read from the environment and never stored on the instance's repr, never
    journaled and never interpolated into an error. An error BODY is not echoed verbatim either:
    a server can reflect a request header into its own JSON, which #36's review caught for real.
    """

    def __init__(self, base: str, zone: str, *, token: str, opener=None, env=None):
        assert_control_destination(base, env=env)
        self._base = base.rstrip("/")
        self._zone = zone.strip(".")
        self._token = token
        self._opener = opener or _http

    def _call(self, host, path, *, method="GET", body=None, authorized=True):
        headers = {"Host": host}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if authorized:
            headers["Authorization"] = "Bearer " + self._token
        status, resp_headers, payload = self._opener(
            self._base + path, headers=headers, method=method,
            body=json.dumps(body).encode("utf-8") if body is not None else None, timeout=60)
        return status, resp_headers, payload

    def read_active(self, name: str) -> dict:
        status, _, payload = self._call(f"docs-control.{self._zone}", f"/v1/deployments/{name}")
        if status != 200:
            raise ControlError(status, "read-back refused")
        return json.loads(payload)

    def publish(self, manifest: dict, expected_active) -> dict:
        status, _, payload = self._call(
            f"docs-control.{self._zone}", "/v1/deployments", method="POST",
            body=dict(manifest, expected_active=expected_active))
        if status not in (200, 201):
            raise ControlError(status, _safe_detail(payload, self._token))
        return json.loads(payload)

    def serve(self, name: str) -> bytes:
        return self.serve_full(name)[0]

    def serve_full(self, name: str):
        """(body, headers). `activate` checks the headers too, not only the bytes."""
        status, headers, payload = self._call(f"{name}.{self._zone}", "/", authorized=False)
        if status != 200:
            raise ControlError(status, "the harness did not serve the page")
        return payload, headers


def manifest_for_row(row: dict, *, name: str, repos: dict) -> dict:
    """The manifest for a row's TARGET commit.

    **Deviation from the design, and its reason.** The design said to reuse
    `publish_doc.build_manifest`. It cannot be reused here: that function manifests the WORKING TREE
    (it reads the file and refuses when it differs from `HEAD`), and a backfill pins a COMMIT that
    may not be checked out — the repository can sit on another branch entirely. So the entries come
    from the target commit's own blobs, which `map` already resolved and this function re-verifies,
    and `publish_doc.validate_manifest` (which is pure) still validates the result.
    """
    target = row["target"]
    repo = repos[target["project"]]
    body = _git_bytes(repo, ["cat-file", "blob", target["blob_id"]])
    if hashlib.sha256(body).hexdigest() != target["sha256"]:
        raise RowError("mapping_invalid",
                       f"the blob recorded for {target['repo_path']} no longer hashes to the "
                       "recorded sha256")
    purpose = None
    for _, found, _ in viable_splits(row["inventory"]["name"], {target["project"]}):
        purpose = found
        break
    return {
        "name": name,
        "repo": _repo_slug(repo),
        "commit_sha": target["commit"],
        "entry_path": "/index.html",
        "assets": [{"url_path": "/index.html", "repo_path": target["repo_path"],
                    "blob_id": target["blob_id"], "size": len(body),
                    "sha256": target["sha256"]}],
        "title": row["inventory"]["name"],
        "project": target["project"],
        "purpose": purpose,
    }


def _repo_slug(repo) -> str:
    """`owner/name` from the repository's own origin, or a placeholder for a test repo."""
    try:
        url = _git_out(repo, ["remote", "get-url", "origin"]).strip()
    except RowError:
        return "local/test"
    slug = url.rstrip("/")
    if slug.endswith(".git"):
        slug = slug[:-4]
    parts = slug.replace(":", "/").split("/")
    return "/".join(parts[-2:]) if len(parts) >= 2 else "local/test"


def _revalidate(row: dict, *, repos: dict, inventory=None) -> None:
    """The mapping is UNTRUSTED on every re-read, and bound to its inventory row.

    Recomputing the blob is not enough on its own: an edit could keep a perfectly valid, reachable
    blob while pointing the row at a different source URL or a different trusted harness name. So
    the binding is checked first.
    """
    claimed = row.get("inventory") or {}
    if row.get("harness_name") != claimed.get("name"):
        raise RowError("mapping_invalid",
                       f"the row's harness name {row.get('harness_name')!r} is not its inventory "
                       f"row's name {claimed.get('name')!r}")
    # Comparing two fields of the SAME editable row proves nothing: an edit that changes both
    # survives it. The binding is only a binding when it reaches the immutable snapshot, so when
    # one is supplied the row is looked up in it by project id. A Critical review finding.
    if inventory is not None:
        by_id = {r.get("id"): r for r in inventory}
        real = by_id.get(claimed.get("id"))
        if real is None:
            raise RowError("mapping_invalid",
                           f"no inventory row has id {claimed.get('id')!r}; a mapping row that "
                           "names no real project cannot be published")
        if real.get("name") != claimed.get("name"):
            raise RowError("mapping_invalid",
                           f"inventory {claimed.get('id')!r} is {real.get('name')!r}, and this row "
                           f"claims {claimed.get('name')!r}")
        if real.get("latestProductionUrl") != claimed.get("url"):
            raise RowError("mapping_invalid",
                           f"inventory {claimed.get('id')!r} points at "
                           f"{real.get('latestProductionUrl')!r}, and this row claims "
                           f"{claimed.get('url')!r} — the comparison would be against the wrong "
                           "page")
    target = row.get("target") or {}
    for field in ("project", "commit", "repo_path", "blob_id", "sha256"):
        if not target.get(field):
            raise RowError("mapping_invalid", f"the row's target has no {field}")
    if target["project"] not in repos:
        raise RowError("mapping_invalid", f"unknown project {target['project']!r}")
    repo = repos[target["project"]]
    # The path must still hold that blob at that commit. Checking the blob alone would accept a
    # row whose PATH had been edited: the bytes would be right and the row's own account of where
    # they live would be wrong, which is exactly the kind of quiet inconsistency a hand-edited
    # mapping introduces. Found by a test that expected one row to fail and got two publishes.
    try:
        at_commit = _git_out(repo, ["rev-parse", f"{target['commit']}:{target['repo_path']}"]).strip()
    except RowError:
        raise RowError("mapping_invalid",
                       f"{target['repo_path']} does not exist at {target['commit'][:7]}") from None
    if at_commit != target["blob_id"]:
        raise RowError("mapping_invalid",
                       f"{target['repo_path']} at {target['commit'][:7]} holds {at_commit[:12]}, "
                       f"not the recorded {target['blob_id'][:12]}")
    body = _git_bytes(repo, ["cat-file", "blob", target["blob_id"]])
    if hashlib.sha256(body).hexdigest() != target["sha256"]:
        raise RowError("mapping_invalid",
                       "the recorded blob no longer hashes to the recorded sha256")


# The harness's own words when GitHub answers 404 for a named object
# (`harness/github.py:194`). It arrives as a 422, because the harness's contract blames the
# publisher for a named object that is not there — a defensible choice on its side, and an
# ambiguous signal on this one. Measured live: two sampled rows failed this way, and their
# repositories are PRIVATE, so the harness's fine-grained token simply cannot see them.
_GITHUB_MISS = "does not exist"


def _classify_control_error(exc: "ControlError"):
    """(reason, detail) for a control-API failure, distinguishing WHOSE fault it is.

    A 502 is the harness saying it could not read the repository. A 422 carrying GitHub's
    object-not-found text is the same underlying cause wearing a different status, because the
    harness blames the publisher for a named object that is absent. Calling that
    `stage_publish_failed` hid the real reason on the first live run, which is a report that tells
    an operator to look in the wrong place.
    """
    if exc.status in (502, 504):
        return "harness_fetch_denied", exc.detail
    if exc.status == 422 and _GITHUB_MISS in (exc.detail or "").lower():
        return "harness_fetch_denied", (
            f"{exc.detail} — the blob IS committed and pushed at the pinned commit, so either the "
            "harness's GitHub token cannot read that repository (check whether it is private and "
            "whether the token's grant covers it) or the commit is not on the remote this harness "
            "fetches from. Those two look identical from here, and the token grant is the one to "
            "check first.")
    if exc.status == 409:
        return "stage_publish_failed", exc.detail
    return "stage_publish_failed", exc.detail


def plan_digest(sealed: dict) -> str:
    """The digest of a sealed plan, computed from its CONTENT — never read from its own file.

    Comparing `--execute` against the digest stored inside the plan was a Critical finding: the
    plan is an editable file, so an edited manifest with the old digest string left in place passed
    the gate and could have published attacker-selected assets under a trusted production name.
    Every gate recomputes this.
    """
    return digest({"rows": sealed.get("rows"), "expires_at": sealed.get("expires_at"),
                   "run_id": sealed.get("run_id"), "attempt": sealed.get("attempt"),
                   "mapping_digest": sealed.get("mapping_digest")})


def stage_rows(rows, *, run: RunDir, control, opener, repos: dict, run_id: str,
               plan_ttl_s: int = 1800, attempt: int = 1, mapping_digest: str = "",
               inventory=None) -> list:
    """Compare, then stage, then verify. Per row, isolated, journaled before every write.

    Order matters and it is not the obvious one: the compare happens BEFORE any publish, so a
    drifted row touches no registry at all. Publishing first and comparing after would leave the
    wrong page live under a name people trust, and the control API has no deactivate.
    """
    # A DEEP COPY per row, because the caller's rows are the REVIEWED mapping. Mutating them in
    # place wrote staging outcomes back into mapping.json on the first live run, so the retry the
    # attempt counter exists for found zero eligible rows — the resumability the design promises,
    # defeated by an aliasing bug.
    rows = [json.loads(json.dumps(r)) for r in rows]
    plan = []
    stage_halted = False
    for row in rows:
        if row.get("reason"):
            continue
        if stage_halted:
            row["reason"] = "final_verification_failed"
            row["detail"] = ("not attempted: an earlier row's staging publish served bytes that "
                             "did not match its target, which is a harness defect rather than "
                             "drift, so staging stopped")
            continue
        name = row["harness_name"]
        try:
            _revalidate(row, repos=repos, inventory=inventory)
            live = fetch_live(row["inventory"]["url"], opener=opener)
            target_body = _git_bytes(repos[row["target"]["project"]],
                                     ["cat-file", "blob", row["target"]["blob_id"]])
            # Decision order, explicit: "changed since map" settles it FIRST, so the two
            # predicates cannot both fire for one row.
            if hashlib.sha256(live).hexdigest() != row["provenance"].get("sha256"):
                raise RowError("vercel_changed",
                               "the live page's bytes are not the ones `map` recorded")
            if live != target_body:
                raise RowError("byte_mismatch",
                               f"the live page is {len(live)} bytes and the committed target is "
                               f"{len(target_body)}; the document changed after its last Vercel "
                               "deploy, so nothing was published")
            label = staging_label(run_id, name, attempt)
            manifest = manifest_for_row(row, name=label, repos=repos)
            _validate_manifest(manifest)
            # WRITE-AHEAD. A crash between here and the response leaves an intent on disk, which
            # is the only thing that makes the resume decidable at all.
            run.journal(name, {"phase": "stage", "state": "pending", "target": label,
                               "content_sha256": row["target"]["sha256"],
                               "expected_active": None})
            result = control.publish(manifest, None)
            run.journal(name, {"phase": "stage", "state": "published", "target": label,
                               "deployment_id": result.get("deployment_id"),
                               "cache_warmed": bool(result.get("cache_warmed"))})
            if not result.get("cache_warmed"):
                raise RowError("stage_publish_failed",
                               "the harness did not warm its cache, so it never proved it could "
                               "fetch the blobs; that is not a pass")
            served = control.serve(label)
            if served != target_body:
                raise RowError("final_verification_failed",
                               f"the harness served {len(served)} bytes for the staging label and "
                               f"the committed target is {len(target_body)}")
            row["staged"] = {"label": label, "deployment_id": result.get("deployment_id")}
            plan.append({"name": name, "manifest": manifest, "staged": row["staged"],
                         "sealed_live_sha256": hashlib.sha256(live).hexdigest()})
        except ControlError as exc:
            row["reason"], row["detail"] = _classify_control_error(exc)
        except RowError as exc:
            row["reason"], row["detail"] = exc.reason, exc.detail
            # The design says a served-bytes mismatch is worth stopping the campaign over, because
            # it means the harness did not serve what it was given — a defect in the thing every
            # later row depends on. Recording it per row and carrying on contradicted that.
            if exc.reason == "final_verification_failed":
                stage_halted = True
        finally:
            run.journal(name, {"phase": "stage", "state": "done",
                               "reason": row.get("reason"), "detail": (row.get("detail") or "")[:300]})
    sealed = {"rows": plan, "expires_at": int(time.time()) + int(plan_ttl_s),
              "run_id": run_id, "attempt": attempt, "mapping_digest": mapping_digest}
    # The digest covers the expiry and the mapping identity too, not just the rows. Covering only
    # the rows let an edited expiry or a swapped mapping ride along under a digest that still
    # matched — a Critical review finding.
    sealed["digest"] = plan_digest(sealed)
    run.write_json("activation-plan.json", sealed)
    return rows


def _validate_manifest(manifest: dict) -> None:
    """Validate with `publish_doc.validate_manifest`, which is pure and already tested."""
    import importlib.util
    path = pathlib.Path(__file__).resolve().parent / "publish_doc.py"
    spec = importlib.util.spec_from_file_location("publish_doc_validate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.validate_manifest(manifest)


# --------------------------------------------------------------------------------------------
# T5 — activation. The only production write, and the only thing here that cannot be undone.
# --------------------------------------------------------------------------------------------


def _row_owned_deployment(run: RunDir, name: str):
    """(deployment_id, has_unproven_pending) for THIS row's production publishes.

    Row-scoped, never run-scoped: a run-wide "is it ours" would let a second row replace the first
    row's page under a shared name. And a `pending` with no recorded id is NOT ownership — the POST
    may have committed with its response lost, and another contender publishing the same bytes is
    indistinguishable from us. That case stops the row rather than guessing.
    """
    owned, unproven = None, False
    for entry in run.journal_entries():
        record = entry.get("record") or {}
        if entry.get("row") != name or record.get("phase") != "activate":
            continue
        if record.get("target") != name:
            continue
        if record.get("state") == "published" and record.get("deployment_id") is not None:
            owned = record["deployment_id"]
            unproven = False
        elif record.get("state") == "pending":
            unproven = True
    return owned, unproven


def production_manifest(staged: dict, name: str) -> dict:
    """The staged manifest with its `name` replaced — and nothing else touched.

    Re-sending the staged bytes was an impossible instruction: a manifest CONTAINS its name, so it
    would address the staging label a second time. What is invariant is the asset set, and this
    asserts that invariant rather than trusting it.
    """
    produced = dict(staged)
    produced["name"] = name
    left, right = dict(staged), dict(produced)
    left.pop("name"), right.pop("name")
    if left != right:                                    # pragma: no cover - guard, not a path
        raise AssertionError("the production manifest differs from the staged one in more than "
                             "its name")
    return produced


def activate_rows(plan: dict, *, mapping: dict, run: RunDir, control, opener, repos: dict,
                  execute, zone: str, inventory=None, limit=None) -> list:
    """Activate every sealed row, in order, stopping the campaign on an unverified publish."""
    # RECOMPUTED, never trusted from the file. And the mapping the plan was sealed against must
    # still be the mapping on disk, or a swapped mapping rides in under a matching plan digest.
    recomputed = plan_digest(plan)
    stored = plan.get("digest", "")
    if stored and stored != recomputed:
        raise Refused(
            f"the activation plan's own digest is {stored[:12]} but its content hashes to "
            f"{recomputed[:12]}: the file has been edited since it was sealed, and a stored digest "
            "is not evidence about the content beside it")
    require_execute(execute=execute, expected=recomputed, what="activation plan")
    sealed_mapping = plan.get("mapping_digest")
    # RECOMPUTED from the rows, like every other digest comparison in this file. Comparing against
    # the string stored inside the editable mapping file is the same defect a third time, and the
    # reviewer was right to keep pointing at it.
    mapping_now = digest(mapping.get("rows") or [])
    if sealed_mapping and sealed_mapping != mapping_now:
        raise Refused(
            f"the plan was sealed against mapping {str(sealed_mapping)[:12]} and the mapping on "
            f"disk hashes to {mapping_now[:12]}: re-run `stage` rather than activating against a "
            "mapping nobody compared")
    by_name = {r.get("harness_name"): r for r in (mapping.get("rows") or [])}
    expires_at = int(plan.get("expires_at", 0))
    halted = False
    out = []
    planned = plan.get("rows") or []
    if limit is not None:
        # It was advertised and ignored. On the one irreversible command in this script, an operator
        # bounding the blast radius and being given the whole plan anyway is the worst kind of
        # defect: the flag reads as a safety belt and is not attached to anything.
        planned = planned[:int(limit)]
    for sealed in planned:
        name = sealed["name"]
        result = {"name": name, "outcome": FLAGGED, "reason": None, "detail": "",
                  "reason_class": ""}
        if halted:
            result["reason"] = "final_verification_failed"
            result["reason_class"] = "campaign_halted"
            result["detail"] = ("not attempted: an earlier row published bytes the harness did not "
                                "then serve, so activation stopped")
            out.append(result)
            continue
        published_ok = False
        try:
            # Checked PER ROW. Evaluated once before the loop, a run that started just inside the
            # window could publish every later production name long after the plan expired, which
            # is exactly what a short-lived plan is supposed to prevent.
            if expires_at < int(time.time()):
                raise RowError("plan_expired",
                               "the activation plan's expiry has passed; re-run `stage` so the "
                               "comparison is re-taken against the page as it is now")
            row = by_name.get(name)
            if row is None:
                raise RowError("mapping_invalid",
                               f"{name} is in the activation plan but not in the mapping any more; "
                               "a row a human deleted after staging must not activate")
            _revalidate(row, repos=repos, inventory=inventory)
            live = fetch_live(row["inventory"]["url"], opener=opener)
            if hashlib.sha256(live).hexdigest() != sealed.get("sealed_live_sha256"):
                raise RowError("vercel_changed",
                               "the live page moved after the comparison was sealed")
            owned, unproven = _row_owned_deployment(run, name)
            state = control.read_active(name)
            active = state.get("active_deployment_id")
            if active is not None and active != owned:
                if unproven:
                    raise RowError("final_verification_failed",
                                   f"{name} is active as deployment {active} and this row has a "
                                   "pending publish whose response was lost, so nothing here "
                                   "cannot prove which publisher owns it — an operator decides")
                raise RowError("target_occupied",
                               f"{name} is already active as deployment {active}, which is not "
                               "this row's; the API cannot deactivate and metadata cannot rebuild "
                               "somebody else's manifest, so this row stops")
            manifest = production_manifest(sealed["manifest"], name)
            run.journal(name, {"phase": "activate", "state": "pending", "target": name,
                               "expected_active": active,
                               "content_sha256": manifest["assets"][0]["sha256"]})
            published = control.publish(manifest, active)
            run.journal(name, {"phase": "activate", "state": "published", "target": name,
                               "deployment_id": published.get("deployment_id"),
                               "cache_warmed": bool(published.get("cache_warmed"))})
            published_ok = True
            body, headers = control.serve_full(name)
            target_body = _git_bytes(repos[row["target"]["project"]],
                                     ["cat-file", "blob", row["target"]["blob_id"]])
            deployment = str(published.get("deployment_id"))
            served_deployment = str(_header(headers, "X-Doc-Deployment") or "")
            # The harness sets ETag to the sha256 of the bytes (measured). Accepting a missing or
            # wrong one while calling the row `live` would weaken exactly the check this step is.
            etag = (_header(headers, "Etag") or "").strip().strip('"')
            expected_etag = hashlib.sha256(target_body).hexdigest()
            if body != target_body or served_deployment != deployment or etag != expected_etag:
                halted = True
                raise RowError("final_verification_failed",
                               f"published {name} as deployment {deployment} but it serves "
                               f"{len(body)} bytes (expected {len(target_body)}), reports "
                               f"deployment {served_deployment!r} and ETag {etag[:12]!r} against "
                               f"an expected {expected_etag[:12]!r}. The production name has ALREADY "
                               "changed, so activation stops here rather than continuing with "
                               "unverified bytes live under a trusted name.")
            result["outcome"] = LIVE
            result["deployment_id"] = published.get("deployment_id")
            result["verified_at"] = int(time.time())
        except ControlError as exc:
            result["reason"] = ("cas_conflict" if exc.status == 409 else
                                "harness_fetch_denied" if exc.status in (502, 504) else
                                "final_verification_failed")
            result["detail"] = exc.detail
            # A ControlError can arrive AFTER the production POST committed — a non-200 from
            # `serve_full` is the obvious case. The write is already irreversible at that point, so
            # this path must halt exactly like the byte-mismatch path. It did not, and the loop
            # would have carried on activating further production names. Critical, and correct.
            if published_ok and result["reason"] != "cas_conflict":
                halted = True
                result["detail"] += (" — the production POST had already committed when this "
                                     "failed, so activation stops here")
        except RowError as exc:
            result["reason"] = exc.reason
            result["detail"] = exc.detail
            # Same rule as the ControlError path: once the production POST has committed, ANY later
            # failure leaves an unverified name live. `_git_bytes` raising here — a local object
            # gone missing between the publish and the compare — was recorded and stepped over.
            if published_ok:
                halted = True
                result["detail"] += (" — the production POST had already committed when this "
                                     "failed, so activation stops here")
        run.journal(name, {"phase": "activate", "state": "done", "outcome": result["outcome"],
                           "reason": result["reason"], "detail": result["detail"][:300]})
        out.append(result)
    run.write_json("outcomes.json", {"rows": out, "halted": halted})
    return out


def _control_from_args(args):
    """The control client, built from the environment only. Refuses rather than defaults."""
    token = os.environ.get("DOC_HARNESS_PUBLISH_TOKEN") or ""
    if not token:
        raise Refused("DOC_HARNESS_PUBLISH_TOKEN is not set; the bearer comes from the "
                      "environment only and is never read from a file this script wrote")
    base = args.control_base or os.environ.get("DOC_HARNESS_CONTROL_URL") or ""
    if not base:
        raise Refused("no control base: pass --control-base http://<ip>:<port>")
    return ControlClient(base, args.zone, token=token)


def _cmd_stage(args, run) -> int:
    mapping = run.read_json("mapping.json")
    # RECOMPUTED from the rows on disk, never read from the file's own digest field. Same defect
    # class as the activation plan's, in the other phase: a reviewer edits this file BY DESIGN, so
    # trusting a digest string sitting beside the rows it is meant to authenticate lets an edited
    # mapping through on an old approval.
    recomputed = digest(mapping.get("rows") or [])
    stored = mapping.get("digest", "")
    if stored and stored != recomputed:
        raise Refused(
            f"mapping.json's own digest is {stored[:12]} but its rows hash to {recomputed[:12]}: "
            "the file changed since that digest was written. Re-read it, and pass the digest "
            "`map` or this refusal printed — never the one inside the file.")
    require_execute(execute=args.execute, expected=recomputed, what="mapping")
    rows = [r for r in mapping.get("rows") or [] if not r.get("reason")]
    if args.limit is not None:
        rows = rows[:int(args.limit)]
    control = _control_from_args(args)
    staged = stage_rows(rows, run=run, control=control, opener=_http,
                        repos=load_projects(find_workspace_file()),
                        run_id=args.run_id or pathlib.Path(args.run_dir).name,
                        plan_ttl_s=args.plan_ttl, attempt=args.attempt,
                        mapping_digest=mapping.get("digest", ""),
                        inventory=(run.read_json("inventory.json").get("rows") or []))
    ok = sum(1 for r in staged if not r.get("reason"))
    print(f"stage: {ok} staged and verified, {len(staged) - ok} flagged, of {len(staged)} "
          "eligible rows")
    for row in staged:
        if row.get("reason"):
            print(f"  {row['harness_name']}: {row['reason']} — {(row.get('detail') or '')[:120]}")
    plan = run.read_json("activation-plan.json")
    print(f"activation plan digest: {plan['digest']} (expires at {plan['expires_at']})")
    # mapping.json is NOT rewritten. It is the reviewed input, and a phase that edits its own
    # input cannot be re-run — which is exactly what happened on the first live run.
    run.write_json("staged-rows.json", {"rows": staged})
    return 0


def _cmd_activate(args, run) -> int:
    plan = run.read_json("activation-plan.json")
    mapping = run.read_json("mapping.json")
    control = _control_from_args(args)
    rows = activate_rows(plan, mapping=mapping, run=run, control=control, opener=_http,
                         repos=load_projects(find_workspace_file()), execute=args.execute,
                         zone=args.zone, limit=args.limit,
                         inventory=(run.read_json("inventory.json").get("rows") or []))
    live = sum(1 for r in rows if r["outcome"] == LIVE)
    print(f"activate: {live} live, {len(rows) - live} flagged, of {len(rows)} planned rows")
    return 0


# --------------------------------------------------------------------------------------------
# T6 — the report. An assertion, not a summary.
# --------------------------------------------------------------------------------------------


def build_report(run: RunDir) -> dict:
    """The outcome report, and the completeness check that gives it teeth.

    The assertion is scoped to the PROCESSED set, and the snapshot set is reported beside it. A
    sampled run cannot honestly assert over 181 rows it never touched, and forcing the untouched
    ones into a flag reason would describe them wrongly — so `not_attempted` is counted, named, and
    given its selection rule.
    """
    snapshot = run.read_json("inventory.json")
    mapping = run.read_json("mapping.json")
    outcomes = run.read_json("outcomes.json")
    # Staging outcomes are a THIRD source, and leaving them out was a real gap the report's own
    # assertion caught on the live run: two rows flagged `harness_fetch_denied` at stage had no
    # outcome in either the mapping (they mapped cleanly) or the activation plan (they never
    # entered it), so the report refused — correctly, and for a reason that was a defect in the
    # report rather than in the data.
    try:
        staged = {r.get("harness_name"): r for r in (run.read_json("staged-rows.json")
                                                     .get("rows") or [])}
    except Refused:
        staged = {}

    snapshot_names = [r.get("name") for r in snapshot.get("rows") or []]
    mapped = {r.get("harness_name"): r for r in mapping.get("rows") or []}
    activated = {r.get("name"): r for r in outcomes.get("rows") or []}

    processed, missing, reasons, live_rows = [], [], {}, []
    for name in mapped:
        row = activated.get(name)
        staged_row = staged.get(name)
        if row is not None:
            outcome, reason, detail = row.get("outcome"), row.get("reason"), row.get("detail", "")
        elif mapped[name].get("reason"):
            outcome, reason, detail = FLAGGED, mapped[name]["reason"], mapped[name].get("detail", "")
        elif staged_row is not None and staged_row.get("reason"):
            outcome = FLAGGED
            reason, detail = staged_row["reason"], staged_row.get("detail", "")
        else:
            missing.append(name)
            continue
        if outcome == LIVE:
            live_rows.append(name)
        else:
            # An outcome that is neither `live` nor `flagged` is corrupt, and pairing it with a
            # known reason must not launder it: the assertion claims every processed row is exactly
            # one of the two, so anything else refuses.
            if outcome != FLAGGED:
                raise Refused(f"{name} carries the outcome {outcome!r}, which is neither "
                              f"{LIVE!r} nor {FLAGGED!r}; a report that renders a corrupt value as "
                              "an outcome is not evidence")
            if reason not in REASONS:
                raise Refused(f"{name} carries the reason {reason!r}, which is not in the closed "
                              "vocabulary; a report that invents a state is not evidence")
            reasons[reason] = reasons.get(reason, 0) + 1
        processed.append({"name": name, "outcome": outcome, "reason": reason,
                          "detail": (detail or "")[:200]})
    if missing:
        raise Refused(
            "the report refuses: these processed rows ended with no outcome at all — "
            + ", ".join(sorted(missing))
            + ". Every row that was attempted must end live or flagged, and this assertion is what "
              "makes the acceptance criterion checkable rather than claimed.")

    not_attempted = [n for n in snapshot_names if n not in mapped]
    # Assert the sample selection ACCOUNTS for every absent row. A row missing for any other
    # reason — a deleted mapping entry, a truncated file — must not be laundered into
    # "not attempted", which reads as deliberate.
    selection = mapping.get("selection") or {}
    limit = selection.get("limit")
    if limit is not None:
        expected_absent = [n for n in snapshot_names[int(limit):]]
        unexplained = sorted(set(not_attempted) - set(expected_absent))
        if unexplained:
            raise Refused(
                "the report refuses: these rows are inside the sampled range and yet absent from "
                "the mapping — " + ", ".join(unexplained)
                + ". `not_attempted` means SAMPLED OUT, and calling a lost row deliberate is the "
                  "one thing the completeness assertion exists to prevent.")
    elif not_attempted:
        raise Refused(
            "the report refuses: the mapping records no selection limit, so every snapshot row "
            f"should have been processed, and {len(not_attempted)} are absent. Re-run `map`, or "
            "record the selection that explains them.")
    staging = []
    for entry in run.journal_entries():
        record = entry.get("record") or {}
        if record.get("phase") == "stage" and record.get("state") == "published":
            staging.append({"label": record.get("target"),
                            "deployment_id": record.get("deployment_id"),
                            "row": entry.get("row")})
    summary = {
        "snapshot": len(snapshot_names), "processed": len(processed),
        "not_attempted": len(not_attempted), "live": len(live_rows),
        "reasons": reasons, "staging": staging, "halted": bool(outcomes.get("halted")),
        "cutoff": bool(snapshot.get("cutoff")),
        "started_at": snapshot.get("started_at"), "completed_at": snapshot.get("completed_at"),
        "rows": processed, "not_attempted_names": not_attempted,
    }
    summary["markdown"] = _render_report(summary)
    summary["markdown_redacted"] = _render_report(summary, redact=True)
    run.write_json("report.json", {k: v for k, v in summary.items()
                                   if k not in ("markdown", "markdown_redacted")})
    (run.path / "report.md").write_text(summary["markdown"] + "\n", encoding="utf-8")
    return summary


def _pseudonym(name: str) -> str:
    """A stable, name-free handle for a live Vercel project.

    This repository SHIPS AS A PLUGIN, and it carries a test asserting that no committed file names
    a live project in the account — "an install copies it to everyone". A report enumerating 171
    real project names is exactly that leak, and the guard caught it on the Step-9 gate rather than
    after release. The full named report stays in the run directory, which is git-ignored; the
    committed copy uses these handles, and the run directory is how an operator maps one back.
    """
    return "p-" + hashlib.sha256(str(name).encode("utf-8")).hexdigest()[:12]


def _render_report(summary: dict, *, redact: bool = False) -> str:
    def shown(name):
        return _pseudonym(name) if redact else name

    lines = ["# Vercel-to-harness backfill — outcome report", ""]
    if redact:
        lines += ["> **Project names are redacted to stable handles in this committed copy.** This "
                  "repository ships as a plugin, and a committed file naming live projects in the "
                  "account would be copied to every install. The full named report is in the run "
                  "directory, which is git-ignored, and a handle is "
                  "`p-` plus the first twelve hex of the sha256 of the name.", ""]
    if summary["cutoff"]:
        lines += [f"**The inventory did NOT converge.** It is a cutoff snapshot bounded by two "
                  f"instants — started {summary['started_at']}, completed "
                  f"{summary['completed_at']} — because a paginated walk cannot establish an "
                  f"atomic set at a moment. Rows created inside that window may fall on either "
                  f"side of it, and this report does not claim to know which.", ""]
    else:
        lines += [f"Inventory converged: two agreeing walks, started {summary['started_at']}, "
                  f"completed {summary['completed_at']}.", ""]
    lines += ["| Count | What |", "| --- | --- |",
              f"| {summary['snapshot']} | rows in the snapshot |",
              f"| {summary['processed']} | rows PROCESSED by this run |",
              f"| {summary['not_attempted']} | rows `not_attempted` (sampled out) |",
              f"| {summary['live']} | rows now **live** on the harness |", ""]
    if summary["halted"]:
        lines += ["> **The campaign HALTED.** A row published bytes the harness did not then "
                  "serve, so activation stopped rather than continuing with unverified bytes live "
                  "under a trusted name.", ""]
    if summary["reasons"]:
        lines += ["## Flagged, by reason", "", "| Reason | Rows |", "| --- | --- |"]
        lines += [f"| `{reason}` | {count} |" for reason, count in sorted(summary["reasons"].items())]
        lines += [""]
    lines += ["## Every processed row", "", "| Project | Outcome | Reason |", "| --- | --- | --- |"]
    for row in summary["rows"]:
        lines.append(f"| `{shown(row['name'])}` | {row['outcome']} | "
                     f"{('`' + row['reason'] + '`') if row['reason'] else '—'} |")
    lines += [""]
    if summary["not_attempted_names"]:
        lines += ["## Not attempted", "",
                  "These rows were in the snapshot and this run did not touch them. They have NO "
                  "outcome — not a flag — because no reason in the vocabulary would describe them "
                  "truthfully. The selection rule was `--limit` over the snapshot in its recorded "
                  "order.", "",
                  ", ".join(f"`{shown(n)}`" for n in summary["not_attempted_names"]), ""]
    if summary["staging"]:
        lines += ["## Staging rows left in the registry", "",
                  "Real registry rows, visible on the derived index, and the control API has no "
                  "delete. Retiring them is a deliberate task.", "",
                  "| Label | Deployment | For |", "| --- | --- | --- |"]
        lines += [f"| `{item['label']}` | {item['deployment_id']} | `{shown(item['row'])}` |"
                  for item in summary["staging"]]
        lines += [""]
    return "\n".join(lines)


def _cmd_report(args, run) -> int:
    summary = build_report(run)
    print(summary["markdown"])
    root = pathlib.Path(__file__).resolve().parents[1]
    out = root / "docs" / "measurements" / f"{args.date}-37-backfill-{pathlib.Path(args.run_dir).name}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    # The COMMITTED copy is redacted; the named one lives in the run directory beside the journal.
    out.write_text(summary["markdown_redacted"] + "\n", encoding="utf-8")
    print(f"\nwritten (redacted, committed): {out}")
    print(f"written (named, run directory): {run.path / 'report.md'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backfill_vercel.py",
        description="Backfill Vercel-hosted doc pages into the harness registry (#37). "
                    "Read-only unless --execute carries the digest of the plan.")
    parser.add_argument("--run-dir", required=True, help="the run directory (reused if present)")
    sub = parser.add_subparsers(dest="command", required=True)

    inv = sub.add_parser("inventory", help="walk the Vercel listing, bounded")
    inv.add_argument("--max-walks", type=int, default=3,
                     help="how many walks may be attempted before a cutoff is recorded")

    mp = sub.add_parser("map", help="identify each document, and record its publish target")
    mp.add_argument("--history-cap", type=int, default=2000,
                    help="commits examined per candidate path; hitting it is RECORDED on the row")
    mp.add_argument("--workspace-file", default=None, help="the rawgentic workspace file")
    mp.add_argument("--limit", type=int, default=None,
                    help="map only the first N snapshot rows, in the snapshot's recorded order — "
                         "this IS the sample selection rule, and it is reproducible")

    st = sub.add_parser("stage", help="compare, then publish under a staging label and verify")
    st.add_argument("--execute", default=None, help="the mapping digest, required to write")
    st.add_argument("--control-base", default=None, help="http://<ip>:<port> of the control API")
    st.add_argument("--zone", default="3dstories.ca")
    st.add_argument("--limit", type=int, default=None, help="bound one pass")
    st.add_argument("--run-id", default=None,
                    help="the run id baked into the staging label; defaults to the run dir's name")
    st.add_argument("--plan-ttl", type=int, default=1800,
                    help="seconds the sealed activation plan stays valid")
    st.add_argument("--attempt", type=int, default=1,
                    help="bump this to re-stage a row under a FRESH staging label after an expiry")

    act = sub.add_parser("activate", help="CAS-publish the production name and verify it")
    act.add_argument("--execute", default=None, help="the activation-plan digest")
    act.add_argument("--control-base", default=None)
    act.add_argument("--zone", default="3dstories.ca")
    act.add_argument("--limit", type=int, default=None)

    rep = sub.add_parser("report",
                         help="assert every row ended live or flagged, and write the report")
    rep.add_argument("--date", default="2026-08-24",
                     help="the date prefix for the report filename; passed rather than derived so "
                          "a re-run cannot silently produce a second file")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    run = RunDir(args.run_dir)
    try:
        handler = COMMANDS[args.command]
    except KeyError:  # pragma: no cover - argparse already constrains this
        raise AssertionError(f"no handler for {args.command!r}")
    try:
        return handler(args, run)
    except Refused as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return 2


COMMANDS = {
    "inventory": _cmd_inventory,
    "map": _cmd_map,
    "stage": _cmd_stage,
    "activate": _cmd_activate,
    "report": _cmd_report,
}


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
