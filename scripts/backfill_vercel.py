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
    rows, nxt = [], None
    while True:
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


def candidate_paths(repo, ref: str, *, runner=None) -> list:
    """Paths ever present in history whose name carries the ref. A NARROWING, nothing more.

    `--all` and `--name-only` over history, because most of these pages were published from a
    commit that is now old and a search of `HEAD` would miss them entirely.
    """
    out = _git_out(repo, ["log", "--all", "--pretty=format:", "--name-only"], runner=runner)
    seen, paths = set(), []
    needle = str(ref).lower()
    for line in out.splitlines():
        line = line.strip()
        if not line or line in seen or not line.endswith(".html"):
            continue
        seen.add(line)
        parts = line.lower().split("/")
        if needle in parts[-1] or any(needle in part for part in parts[:-1]):
            paths.append(line)
    return paths


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
        tip = _git_out(repo, ["rev-parse", "origin/HEAD"], runner=runner).strip()
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
             fetch_remote: bool = True) -> list:
    """One mapping row per inventory row. Provenance from the bytes; target from the tip.

    Every row carries its IMMUTABLE inventory binding — the project id, the name and the
    snapshotted URL — because a later phase re-reads this file after a human has edited it, and
    without that binding an edit could keep a perfectly valid blob while pointing it at a different
    source or a different trusted name.
    """
    projects = load_projects(workspace_file)
    rows = []
    for entry in snapshot.get("rows") or []:
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
            candidates, capped = [], False
            for project in dict.fromkeys(list(projects)):
                repo = projects[project]
                for ref in dict.fromkeys(refs):
                    found, hit = history_candidates(repo, ref=ref, target=live,
                                                    cap=history_cap, report_cap=True)
                    capped = capped or hit
                    for item in found:
                        candidates.append(dict(item, project=project))
            row["history_capped"] = capped
            # Dedup by (project, path, blob): the same blob reached through two refs is one answer.
            unique = {(c["project"], c["repo_path"], c["blob_id"]): c for c in candidates}
            candidates = list(unique.values())
            if not candidates:
                raise RowError("mapping_not_found",
                               "no committed blob in the workspace hashes to the live bytes"
                               + (" (the history search hit its cap, so this is not exhaustive)"
                                  if capped else ""))
            if len({(c["project"], c["repo_path"]) for c in candidates}) > 1:
                row["candidates"] = candidates
                raise RowError("mapping_ambiguous",
                               f"{len(candidates)} committed blobs hash to the live bytes")
            match = candidates[0]
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
    mapping = {"rows": rows, "inventory_digest": snapshot.get("digest")}
    mapping["digest"] = digest(rows)
    run.write_json("mapping.json", mapping)
    return rows


def _cmd_map(args, run) -> int:
    snapshot = run.read_json("inventory.json")
    workspace = args.workspace_file or str(
        pathlib.Path(__file__).resolve().parents[2] / ".rawgentic_workspace.json")
    rows = map_rows(snapshot, workspace_file=workspace, opener=_http, run=run,
                    history_cap=args.history_cap)
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
    opener = urllib.request.build_opener(_NoRedirect)
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
            # The body is SUMMARIZED, never echoed: a server can reflect Authorization into it.
            text = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else str(payload)
            raise ControlError(status, text.strip()[:200])
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


def _revalidate(row: dict, *, repos: dict) -> None:
    """The mapping is UNTRUSTED on every re-read, and bound to its inventory row.

    Recomputing the blob is not enough on its own: an edit could keep a perfectly valid, reachable
    blob while pointing the row at a different source URL or a different trusted harness name. So
    the binding is checked first.
    """
    inventory = row.get("inventory") or {}
    if row.get("harness_name") != inventory.get("name"):
        raise RowError("mapping_invalid",
                       f"the row's harness name {row.get('harness_name')!r} is not its inventory "
                       f"row's name {inventory.get('name')!r}")
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


def stage_rows(rows, *, run: RunDir, control, opener, repos: dict, run_id: str,
               plan_ttl_s: int = 1800, attempt: int = 1) -> list:
    """Compare, then stage, then verify. Per row, isolated, journaled before every write.

    Order matters and it is not the obvious one: the compare happens BEFORE any publish, so a
    drifted row touches no registry at all. Publishing first and comparing after would leave the
    wrong page live under a name people trust, and the control API has no deactivate.
    """
    plan = []
    for row in rows:
        if row.get("reason"):
            continue
        name = row["harness_name"]
        try:
            _revalidate(row, repos=repos)
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
            reason = ("harness_fetch_denied" if exc.status in (502, 504)
                      else "stage_publish_failed")
            row["reason"], row["detail"] = reason, exc.detail
        except RowError as exc:
            row["reason"], row["detail"] = exc.reason, exc.detail
        finally:
            run.journal(name, {"phase": "stage", "state": "done",
                               "reason": row.get("reason"), "detail": (row.get("detail") or "")[:300]})
    sealed = {"rows": plan, "expires_at": int(time.time()) + int(plan_ttl_s),
              "run_id": run_id, "attempt": attempt}
    sealed["digest"] = digest(plan)
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
                  execute, zone: str) -> list:
    """Activate every sealed row, in order, stopping the campaign on an unverified publish."""
    require_execute(execute=execute, expected=plan.get("digest", ""), what="activation plan")
    by_name = {r.get("harness_name"): r for r in (mapping.get("rows") or [])}
    expired = int(plan.get("expires_at", 0)) < int(time.time())
    halted = False
    out = []
    for sealed in plan.get("rows") or []:
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
        try:
            if expired:
                raise RowError("plan_expired",
                               "the activation plan's expiry has passed; re-run `stage` so the "
                               "comparison is re-taken against the page as it is now")
            row = by_name.get(name)
            if row is None:
                raise RowError("mapping_invalid",
                               f"{name} is in the activation plan but not in the mapping any more; "
                               "a row a human deleted after staging must not activate")
            _revalidate(row, repos=repos)
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
            body, headers = control.serve_full(name)
            target_body = _git_bytes(repos[row["target"]["project"]],
                                     ["cat-file", "blob", row["target"]["blob_id"]])
            deployment = str(published.get("deployment_id"))
            served_deployment = str(_header(headers, "X-Doc-Deployment") or "")
            if body != target_body or served_deployment != deployment:
                halted = True
                raise RowError("final_verification_failed",
                               f"published {name} as deployment {deployment} but it serves "
                               f"{len(body)} bytes (expected {len(target_body)}) and reports "
                               f"deployment {served_deployment!r}. The production name has ALREADY "
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
        except RowError as exc:
            result["reason"] = exc.reason
            result["detail"] = exc.detail
        run.journal(name, {"phase": "activate", "state": "done", "outcome": result["outcome"],
                           "reason": result["reason"], "detail": result["detail"][:300]})
        out.append(result)
    run.write_json("outcomes.json", {"rows": out, "halted": halted})
    return out


def _cmd_activate(args, run) -> int:
    plan = run.read_json("activation-plan.json")
    mapping = run.read_json("mapping.json")
    token = os.environ.get("DOC_HARNESS_PUBLISH_TOKEN") or ""
    if not token:
        raise Refused("DOC_HARNESS_PUBLISH_TOKEN is not set; the bearer comes from the "
                      "environment only and is never read from a file this script wrote")
    base = args.control_base or os.environ.get("DOC_HARNESS_CONTROL_URL") or ""
    if not base:
        raise Refused("no control base: pass --control-base http://<ip>:<port>")
    workspace = str(pathlib.Path(__file__).resolve().parents[2] / ".rawgentic_workspace.json")
    control = ControlClient(base, args.zone, token=token)
    rows = activate_rows(plan, mapping=mapping, run=run, control=control, opener=_http,
                         repos=load_projects(workspace), execute=args.execute, zone=args.zone)
    live = sum(1 for r in rows if r["outcome"] == LIVE)
    print(f"activate: {live} live, {len(rows) - live} flagged, of {len(rows)} planned rows")
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

    st = sub.add_parser("stage", help="compare, then publish under a staging label and verify")
    st.add_argument("--execute", default=None, help="the mapping digest, required to write")
    st.add_argument("--control-base", default=None, help="http://<ip>:<port> of the control API")
    st.add_argument("--zone", default="3dstories.ca")
    st.add_argument("--limit", type=int, default=None, help="bound one pass")

    act = sub.add_parser("activate", help="CAS-publish the production name and verify it")
    act.add_argument("--execute", default=None, help="the activation-plan digest")
    act.add_argument("--control-base", default=None)
    act.add_argument("--zone", default="3dstories.ca")
    act.add_argument("--limit", type=int, default=None)

    sub.add_parser("report", help="assert every row ended live or flagged, and write the report")
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


def _not_yet(args, run):  # pragma: no cover - replaced per task
    raise Refused(f"{args.command} is not implemented yet")


COMMANDS = {
    "inventory": _cmd_inventory,
    "map": _cmd_map,
    "stage": _not_yet,
    "activate": _cmd_activate,
    "report": _not_yet,
}


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
