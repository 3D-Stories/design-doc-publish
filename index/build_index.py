#!/usr/bin/env python3
"""Derive the docs-index page from Vercel, instead of hand-editing it.

Why derived rather than edited (owner decision 2026-08-01): the index is already a pure
function of the Vercel project list — verified live, 37 projects vs 36 rows, the set
difference being exactly {docs-index} one way and empty the other. Hand-editing carried a
real lost-row race: two concurrent publishes both fetch version N, each appends its own row,
and the second deploy silently overwrites the first with no conflict and no error. This
workspace runs concurrent sessions and hit that race class on another file the same week.
Deriving removes the shared mutable file entirely, so there is nothing to race on.

The generated page is NOT committed: it is a build artifact, gitignored, rebuilt on demand.

Usage:
    python3 build_index.py --out /tmp/index/index.html
    python3 build_index.py --out - --no-titles      # fast, for diffing the row set

Every count on the page is computed here. None may be hand-edited.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# The index groups by rawgentic project. `workspace-` is the cross-project bucket.
WORKSPACE_GROUP = "workspace"
SELF_PROJECT = "docs-index"  # the index never lists itself

# #9: `VERCEL_SCOPE` used to live here as a hardcoded team name, which meant this builder
# only ever worked for one account. The scope is now resolved from the user's own
# configuration and THREADED through — `main()` resolves it once and passes it down, so a
# child process cannot re-resolve to a different account halfway through a publish. Every
# call that targets an account still carries `--scope`; the pin was never the problem.

# Runaway backstop for the #171 pagination loop, not a capacity limit: at the default
# `--limit 100` this allows 2,500 projects, far past any real account here. It exists so a
# cursor that never clears fails loudly instead of spawning subprocesses forever.
_MAX_PAGES = 25

# Purpose vocabulary from the {project}-{purpose}-{ref} naming convention. "review" is
# included because it is part of the same established template vocabulary
# (rawgentic render_artifact styles: plain|roadmap|report|design|dashboard|review|spec).
# Names that predate the convention carry no purpose token and honestly render as "doc"
# rather than being guessed at — renaming them to the convention is the real fix.
PURPOSES = ("design", "plan", "uat", "audit", "report", "runbook", "analysis", "spec", "review")
DEFAULT_PURPOSE = "doc"

# #14: group colours are NOT defined here any more. A project's colour is resolved by
# `scripts/vdl_packs.py`, which the renderer also calls — that shared answer is the only
# thing making the index swatches and the pages agree (AC6). Re-adding a literal table
# here would restore exactly the drift this deleted, and a test now fails if one appears.
def _vdl_packs():
    import importlib.util
    root = Path(__file__).resolve().parent.parent / "scripts"
    path = root / "vdl_packs.py"
    # Containment, duplicated deliberately at each of the three load sites. A shared
    # helper would itself have to be loaded the same way, so the guard cannot live behind
    # the thing it guards. `render-doc` documents the full reasoning: a symlinked target
    # is EXECUTED before any check can reject it, so the check must precede the load.
    real = path.resolve()
    if not real.is_file() or not real.is_relative_to(root):
        raise RuntimeError(f"refusing to load {path}: resolves to {real}, outside {root}")
    spec = importlib.util.spec_from_file_location("_index_vdl_packs", real)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _user_config():
    """`scripts/user_config.py`, loaded the same guarded way as `vdl_packs` (#9).

    Containment duplicated here on purpose, exactly as the comment above says: a shared
    helper would itself have to be loaded this way, so the guard cannot live behind the
    thing it guards. This module decides which Vercel account a public page reaches, which
    makes a `sys.path` hijack of it worse than most.
    """
    import importlib.util
    root = Path(__file__).resolve().parent.parent / "scripts"
    path = root / "user_config.py"
    real = path.resolve()
    if not real.is_file() or not real.is_relative_to(root):
        raise RuntimeError(f"refusing to load {path}: resolves to {real}, outside {root}")
    spec = importlib.util.spec_from_file_location("_index_user_config", real)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def group_colors(group: str, workspace_file: Path | None = None) -> tuple[str, str]:
    """(dark, light) for a line — the same pack the rendered pages wear.

    `None` is a real state since #9, not a stand-in for a default that no longer exists:
    a machine that has never run setup has no workspace file, and `pack_for` degrades to
    the seed table and then the name hash rather than raising.
    """
    pack = _vdl_packs().pack_for(group, workspace_file)
    return pack["accent"]["dark"], pack["accent"]["light"]


# Every refusal in the JSON read points here, because a CLI upgrade is the only thing that
# changes this shape: `--format json` is UNDOCUMENTED for `project ls` (it is documented on
# `integration`, `skills` and `deploy-hooks ls`), so an upgrade is free to drop or rename it.
# Exiting loudly is the whole point — guessing is what shipped #125.
_UPGRADE_HINT = (
    "`vercel project ls --format json` did not return the payload this expects. That flag is "
    "undocumented for this subcommand, so a CLI upgrade may have dropped or renamed it — check "
    "`vercel --version` against the release notes. Refusing to guess at project names: a wrong "
    "name makes publish stage 4 disown a live project and offer --new-project, which changes "
    "the doc's URL (#125)."
)


def _refuse(detail: str, blob: str = "") -> None:
    """Exit with a diagnostic that names both the specific defect and its likely cause."""
    sys.exit(f"build_index: {detail}\n{_UPGRADE_HINT}" + (f"\n{blob[:500]}" if blob else ""))


def _clean_name(value: object) -> bool:
    r"""A project name is a non-empty, fully printable string with no surrounding whitespace.

    The printability clause is not paranoia. `\x1b[1mthewanderinginn-design-11\x1b[22m` is what
    #125 actually fed into the membership test, and escape bytes inside a JSON *string* keep the
    document perfectly valid — so `json.loads` alone would hand that back as a name and
    reproduce the same silent false absence in JSON clothing.

    `str.isprintable()` rather than a hand-rolled codepoint range, because the hand-rolled
    version covered only C0 and DEL: it accepted the single-character C1 CSI (U+009B), accepted
    zero-width format characters, and accepted a name that was nothing but spaces. Space itself
    IS printable, so the strip comparison is what rejects padded and blank names.

    (This docstring is raw for the same reason it exists: unescaped, `\x1b` would put a real
    escape byte into the module's own help text.)
    """
    return (isinstance(value, str) and bool(value)
            and value.isprintable() and value == value.strip())


# The shape of a reported production URL (#23): https, a single vercel.app host, nothing
# after it. Anchored at BOTH ends — `https://x.vercel.app.evil.com` carries the suffix
# mid-host and must not read as a Vercel domain (the same lookahead lesson publish_doc's
# `_URL_HOST` documents). The index emits this value verbatim as an href, so the check is
# also what keeps a hostile payload from injecting a foreign link target.
_PROD_URL = re.compile(r"^https://[a-z0-9][a-z0-9-]*\.vercel\.app$")


# Vercel reports `updatedAt` in epoch MILLISECONDS. The magnitude window rejects a value in the
# wrong unit rather than believing it: epoch SECONDS would divide down to a 1970 date and then be
# displayed AND hashed into the change signature as though it were real, which is exactly the
# silently-wrong value this whole change exists to stop. 10**11 ms is 1973; 10**14 is the year 5138.
_MS_MIN, _MS_MAX = 10**11, 10**14


def _instant(value: object) -> datetime | None:
    """Vercel's `updatedAt` (epoch milliseconds) as an absolute instant, or None.

    Never raises: the age is the ONE field allowed to go missing (see `_parse_projects_json`).
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not _MS_MIN <= value < _MS_MAX:   # also False for NaN, which fails every comparison
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=_TZ)
    except (OverflowError, OSError, ValueError):
        return None


def _parse_projects_json(blob: str, scope: str) -> tuple[list[dict], object]:
    """One `--format json` payload in; validated rows plus the next cursor out — or a loud exit.

    Returns the cursor VALUE rather than a more-pages flag (#171). A boolean could only answer
    "is there more", which was enough to refuse and is not enough to fetch. The value is what
    `--next` needs.

    Strictness is asymmetric on purpose, and the asymmetry is the design:

    * a wrong **name** is refused, because that is the #125 failure — stage 4 stops
      recognising a live project and offers `--new-project`, which mints a second project and
      changes a published doc's URL;
    * an unusable **age** degrades to None. Its cost is not only the one em dash the index
      renders: `signature()` then hashes a constant for that row, so if the row also carries no
      page-declared stamp, a later deploy of it does not move the change signature. That is a
      real (and pre-existing) blind spot, accepted because the alternative — refusing to publish
      because a TIMESTAMP is unreadable — is an availability regression with no safety gain. The
      table parser kept its age group optional for the same reason.

    Rows are returned in CLI order, `docs-index` included — the caller filters and counts.
    """
    try:
        doc = json.loads(blob)
    except json.JSONDecodeError as e:
        _refuse(f"stdout is not JSON ({e})", blob)
    if not isinstance(doc, dict):
        _refuse(f"stdout parsed as {type(doc).__name__}, not an object", blob)
    # The payload names the tenant it answered FOR. Passing --scope only ASKS for an account;
    # this is what verifies we were given it. The hazard is already documented in this file
    # (#19 Step 11: an unpinned listing can enumerate a personal account) — a listing silently
    # answered for the wrong account is that same hazard, and it would present every genuinely
    # live project as absent, which is #125's failure by another route.
    context = doc.get("contextName")
    if context != scope:
        _refuse(f"the listing answered for context {context!r}, not {scope!r}")
    pagination = doc.get("pagination")
    if not isinstance(pagination, dict) or "next" not in pagination:
        _refuse("the payload carries no `pagination.next`, so completeness cannot be judged")
    projects = doc.get("projects")
    if not isinstance(projects, list):
        _refuse("the payload carries no `projects` array", blob)
    rows = []
    for i, p in enumerate(projects):
        if not isinstance(p, dict):
            _refuse(f"projects[{i}] is {type(p).__name__}, not an object", blob)
        name = p.get("name")
        if not _clean_name(name):
            _refuse(f"projects[{i}] has no usable `name` ({name!r})", blob)
        # #23: the href is the domain Vercel REPORTS, never one constructed from the name
        # — five live projects have a truncated domain, and a constructed link to them is
        # permanently dead. Fail closed like `name`: a row without its real domain can
        # only be indexed as a guess, which is the defect this field replaces.
        url = p.get("latestProductionUrl")
        if not _clean_name(url) or not _PROD_URL.match(url):
            _refuse(f"projects[{i}] ({name}) has no usable `latestProductionUrl` "
                    f"({url!r}) — the index emits the reported domain, never a "
                    f"constructed one (#23)", blob)
        rows.append({"name": name, "url": url,
                     "deployed": _instant(p.get("updatedAt"))})
    return rows, pagination["next"]


def vercel_projects(limit: int = 100, *, scope: str) -> list[dict]:
    """Project name + last-deploy instant from the Vercel CLI, read as JSON.

    `--format json` puts a machine surface on **stdout** and leaves only the banner on stderr —
    the exact inverse of the human table, which writes everything to stderr with stdout empty.
    So this reads stdout ALONE, and parses it strictly. There is deliberately **no fallback to
    the table**: a fallback would duplicate the fragile parsing this replaced and would mask the
    one event that should stop a publish outright — an upgrade that moved the machine surface.

    The CLI still paginates at 20 without --limit, so --limit is still passed. Verified live
    against Vercel CLI 56.5.0 (2026-08-04): `--limit 3` returns exactly three rows and sets
    `pagination.next`; the full listing returns 0 escape bytes.

    `limit` is now the PAGE SIZE, not a ceiling on the account (#171). Every page is followed
    to exhaustion, so the returned list is the whole account regardless of how many pages that
    takes.
    """
    # --scope pins the team: ambient scope is whatever the last `vercel switch` left,
    # so an unpinned listing can enumerate a personal account instead (#19 Step 11).
    #
    # The colour controls below are defence in depth, NOT the guarantee — the strict parse is.
    # They keep the human-readable stderr a diagnostic quotes clean, and FORCE_COLOR in the
    # environment is one of the two ways #125 was reproducible. Everything else in the
    # environment is preserved: strip PATH and the CLI loses both its binary and its credentials.
    env = {k: v for k, v in os.environ.items() if k != "FORCE_COLOR"}
    env["NO_COLOR"] = "1"

    # #171: FOLLOW the cursor instead of refusing at it.
    #
    # The account crossed 100 projects on 2026-08-10 and stage 7 of EVERY publish started
    # failing — the index could not be rebuilt at all, in any project. The old code refused
    # whenever `pagination.next` was set and told the operator to "re-run with a higher
    # --limit", which is advice a hardcoded `limit=100` default made impossible to take.
    #
    # Refusing was the right call when there was no loop: a partial listing makes live projects
    # look absent, which is #125's failure, and stage 4 answers that by minting a duplicate
    # project under a new URL. This keeps that guarantee and drops the false refusal, because a
    # cursor that is followed to exhaustion is a COMPLETE listing, not a truncated one.
    rows: list[dict] = []
    seen: set = set()
    cursor = None
    for _page in range(_MAX_PAGES):
        cmd = ["vercel", "project", "ls", "--format", "json",
               "--limit", str(limit), "--scope", scope, "--no-color"]
        if cursor is not None:
            cmd += ["--next", str(cursor)]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
        if proc.returncode != 0:
            sys.exit(f"build_index: `vercel project ls` failed (rc={proc.returncode}):\n"
                     + (proc.stdout or "") + (proc.stderr or ""))
        page_rows, cursor = _parse_projects_json(proc.stdout or "", scope)
        # Deduplicated by name, because a page boundary that moves while paging can repeat a
        # row. A duplicate is not corruption, but it would double-count in the index, and the
        # first sighting carries the newer timestamp — pages come newest-first.
        for r in page_rows:
            if r["name"] not in seen:
                seen.add(r["name"])
                rows.append(r)
        if cursor is None:
            break
    else:
        # A cursor that never clears. Not reachable through the CLI as it behaves today, which
        # is exactly why it needs a backstop: the failure it prevents is an infinite loop
        # spawning subprocesses, and that is worse than a refusal.
        sys.exit(f"build_index: still paginating after {_MAX_PAGES} pages of {limit}; refusing "
                 f"to keep going. Either the account is larger than this tool expects, or the "
                 f"cursor is not advancing.")

    # The empty-list refusal that used to live HERE has moved to `main()`, where its own
    # stated purpose already put it (#9). It said "refusing to render an empty index" while
    # sitting in the function that does not render anything — and the docstring of
    # `TestTheBootstrapAccountStillPublishes` had already drawn the distinction in so many
    # words: "the refusal that DOES exist is about rendering an index from nothing, which is a
    # different question from what this function returns."
    #
    # A brand-new Vercel account has ZERO projects, not even `docs-index`, and `resolve_project`
    # must be able to see "no such project yet" so `--new-project` can mint the very first doc.
    # Exiting here made a first publish fail at stage 4 while setup reported the account ready.
    #
    # Nothing is weakened. `_parse_projects_json` has already refused a listing whose
    # `contextName` is wrong or whose `pagination.next` is missing, and the cursor is followed
    # to exhaustion — so an empty list that survives all of that is an empty ACCOUNT, not a
    # truncated listing. That is the same reasoning the note below applies to the row count.
    # The length heuristic that lived here is GONE, and its removal is the point rather than a
    # casualty. It refused whenever a page came back full, because a full page used to be the
    # only evidence of truncation available. Under the loop a full page is the ordinary case —
    # it means "fetch the next one" — so keeping the check would refuse every account over 100
    # projects, which is the bug being fixed. The guarantee it approximated is now held exactly
    # by the cursor, which this file already called authoritative "where a row count is only a
    # heuristic". Completeness is proven by exhausting the cursor, not by counting rows.
    # The FILTERED result may legitimately be empty, and the empty-index refusal above is
    # deliberately NOT moved down here. An account holding only `docs-index` is the bootstrap
    # state: `resolve_project` must be able to see "no such project yet" and let `--new-project`
    # mint the first doc. Refusing on an empty FILTERED list reads as tidier and breaks exactly
    # that first publish — verified, and pinned by
    # test_build_index.py::TestTheBootstrapAccountStillPublishes.
    return [r for r in rows if r["name"] != SELF_PROJECT]


def known_projects(workspace_file: Path | None) -> list[str]:
    """rawgentic project names, longest first so prefix matching prefers the specific one
    (a longer name must win over any shorter sibling).

    `None` since #9: the index groups by project as a nicety, so a machine with no
    configured workspace still builds a usable page — every row simply falls into the
    cross-project bucket. That is a degradation the index can afford. `publish_doc` cannot,
    which is why IT calls `require_workspace_file` and refuses instead.
    """
    if workspace_file is None:
        return []
    try:
        data = json.loads(workspace_file.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    return sorted((p["name"].lower() for p in data.get("projects", [])), key=len, reverse=True)


def classify(name: str, projects: list[str]) -> tuple[str, str]:
    """(group, chip) for a Vercel project name."""
    if name.startswith(WORKSPACE_GROUP + "-"):
        group, rest = WORKSPACE_GROUP, name[len(WORKSPACE_GROUP) + 1:]
    else:
        group = next((p for p in projects if name == p or name.startswith(p + "-")), "other")
        rest = name[len(group) + 1:] if group != "other" else name
    chip = next((tok for tok in rest.split("-") if tok in PURPOSES), DEFAULT_PURPOSE)
    return group, chip


# The Edmonton stamp every new/updated page must carry (owner rule, 2026-07-31). Preferred
# over the deploy age because it is what the DOCUMENT says about itself: a re-deploy with no
# content change moves the deploy age but not this.
_STAMP_NEAR = re.compile(
    r"(?:updated|generated|drawn|stamped|revised|as of)\b[^0-9<]{0,24}"
    r"(\d{4}-\d{2}-\d{2})(?:[ T]+(\d{2}:\d{2}))?", re.I)
_STAMP_ANY = re.compile(r"(\d{4}-\d{2}-\d{2})[ T]+(\d{2}:\d{2})")
_TZ = ZoneInfo("America/Edmonton")


def _parse_stamp(body: str) -> datetime | None:
    """The page's own declared last-updated instant, or None.

    Anchored forms ("updated 2026-08-01 00:12") are tried first; only then a bare
    datetime. Both are read from the page's own text, so a document that mentions dates in
    its CONTENT can still mislead this — which is why the row marks where the time came
    from rather than presenting all times as equally solid.
    """
    for pat in (_STAMP_NEAR, _STAMP_ANY):
        m = pat.search(body)
        if not m:
            continue
        date, clock = m.group(1), (m.group(2) if m.lastindex and m.lastindex >= 2 else None)
        try:
            dt = datetime.strptime(f"{date} {clock or '00:00'}", "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        return dt.replace(tzinfo=_TZ)
    return None


def page_meta(name: str, url: str, timeout: float = 15.0) -> tuple[str, datetime | None]:
    """(title, self-declared updated-at) for one page. Falls back to the project name and
    None — a fetch failure must not silently drop a row.

    `url` is the row's REPORTED domain (#23): fetching a constructed
    `https://{name}.vercel.app/` 404s for every truncated-domain project, so their titles
    silently degraded to the bare project name."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "docs-index-builder"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            body = resp.read(60000).decode("utf-8", "replace")
        m = re.search(r"<title>(.*?)</title>", body, re.S | re.I)
        title = html.unescape(m.group(1)).strip() if m else name
        return title, _parse_stamp(body)
    except Exception:  # noqa: BLE001 - any failure degrades to the name, never a dropped row
        return name, None


def build_rows(entries: list[dict], projects: list[str], fetch_titles: bool) -> list[dict]:
    names = [e["name"] for e in entries]
    meta: dict[str, tuple[str, datetime | None]] = {}
    if fetch_titles:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            meta = dict(zip(names, pool.map(
                lambda e: page_meta(e["name"], e["url"] + "/"), entries)))
    rows = []
    for e in entries:
        n = e["name"]
        group, chip = classify(n, projects)
        title, declared = meta.get(n, (n, None))
        # Declared beats deployed. Same rule the VDL packs use: what the artifact says
        # about itself wins over what the platform infers about it.
        updated, source = (declared, "page") if declared else (e["deployed"], "deploy")
        rows.append({"name": n, "url": e["url"],
                     "title": title, "group": group, "chip": chip,
                     "updated": updated, "updated_src": source if updated else "none"})
    return rows


def _ago(then: datetime, now: datetime) -> str:
    """Compact relative age: 40m, 6h, 3d, 2w."""
    secs = max(0, int((now - then).total_seconds()))
    for cutoff, div, unit in ((3600, 60, "m"), (86400, 3600, "h"),
                              (604800, 86400, "d"), (10**12, 604800, "w")):
        if secs < cutoff:
            return f"{max(1, secs // div)}{unit}"
    return "?"


def signature(rows: list[dict]) -> str:
    """A hash of the row set that is stable while nothing real changes.

    Every clock-dependent value is excluded, so an idle account hashes identically on every
    build. BOTH time sources are absolute instants now — a page's own declared stamp, and the
    project's `updatedAt` from the CLI — so both are hashed directly. The old carve-out (deploy
    rows contributed the coarse age TOKEN "6h" instead of a timestamp) existed because the age
    was derived as `now` minus a relative token and therefore drifted on every single build,
    which is the false-positive that makes a change-detector useless. `--format json` reports
    the instant itself, so there is nothing left to drift (#125). `updated_src` stays in the
    canon line below, so a row that switches from a deploy-inferred time to a page-declared one
    still counts as changed.
    """
    def mark(r: dict) -> str:
        return r["updated"].isoformat() if r["updated"] else "-"
    canon = "\n".join(sorted(
        f"{r['name']}\t{r['title']}\t{mark(r)}\t{r['updated_src']}" for r in rows))
    return hashlib.sha256(canon.encode()).hexdigest()


def _sort_key(r: dict) -> tuple:
    """Newest first; rows with no known time sink to the bottom, then alphabetical so the
    order is stable across builds rather than dependent on CLI ordering."""
    return (0, -r["updated"].timestamp(), r["name"]) if r["updated"] else (1, 0, r["name"])


def _color_for(group: str, seen: dict[str, tuple[str, str]],
               workspace_file: Path) -> tuple[str, str]:
    """No positional cycling: the old fallback was `PALETTE[len(seen) % len(PALETTE)]`, so
    a project's colour depended on how many groups sorted before it and adding one project
    silently recoloured others. `pack_for` hashes the name instead."""
    if group not in seen:
        seen[group] = group_colors(group, workspace_file)
    return seen[group]


# Owner request 2026-08-05: index links open a new tab by default.
#
# Applied to the DOCUMENT links only. The group nav emits `href="#slug"`, an in-page jump to a
# section of this same page — sending that to a new tab would break the index's own navigation
# and open a duplicate of the index instead of moving within it. So this is deliberately NOT a
# blanket rule over every anchor, and a test pins the distinction in both directions.
#
# `rel="noopener"` rides along because `target="_blank"` without it is the tabnabbing shape:
# the opened page gets a `window.opener` handle back. Current browsers imply it for
# `target="_blank"`, older ones do not, and saying it costs nothing.
NEW_TAB = ' target="_blank" rel="noopener"'


def render(rows: list[dict], stamp: str, now: datetime, sig: str,
           workspace_file: Path | None = None, scope: str | None = None) -> str:
    # #9: the team name is user-supplied now, so the two places it reaches the page are an
    # injection surface that did not exist while it was a constant. Both are escaped, and
    # `user_config.validate_scope` has already refused anything that is not a slug — belt
    # and braces, because this page is deployed PUBLICLY.
    tenant = html.escape(scope) if scope else ""
    title_prefix = f"{tenant} · " if tenant else ""
    eyebrow = f"{tenant} · vercel · living documentation" if tenant else (
        "vercel · living documentation")
    groups: dict[str, list[dict]] = {}
    for r in sorted(rows, key=_sort_key):
        groups.setdefault(r["group"], []).append(r)

    def freshest(g: str) -> float:
        times = [r["updated"].timestamp() for r in groups[g] if r["updated"]]
        return max(times) if times else 0.0

    # Most-recently-touched line first (owner request 2026-08-01). Was biggest-group-first;
    # size is a poor proxy for "what am I working on", and every line is one click away in
    # the nav regardless.
    order = sorted(groups, key=lambda g: (-freshest(g), g))

    colors: dict[str, tuple[str, str]] = {}
    for g in order:
        _color_for(g, colors, workspace_file)

    # --- every count below is COMPUTED; none may be hand-edited ---
    total_pages = len(rows)
    total_lines = len(order)

    def slug(g: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", g.lower()).strip("-")

    tokens = "\n".join(
        f"  --l-{slug(g)}:{colors[g][0]};" for g in order)
    tokens_light = "\n".join(
        f"    --l-{slug(g)}:{colors[g][1]};" for g in order)
    group_css = "\n".join(
        f".c-{slug(g)}{{color:var(--l-{slug(g)})}} .b-{slug(g)}{{background:var(--l-{slug(g)})}}"
        for g in order)

    nav = "\n".join(
        f'  <a href="#{slug(g)}"><span class="dot b-{slug(g)}"></span>{html.escape(g)}'
        f'<span class="n">{len(groups[g])}</span></a>' for g in order)

    def when(r: dict) -> str:
        """The row's last-updated cell. `~` marks a time inferred from the DEPLOY age
        rather than declared by the page itself, so the two are never confused."""
        if not r["updated"]:
            return '<span class="when none" title="no timestamp found">—</span>'
        tilde = "~" if r["updated_src"] == "deploy" else ""
        exact = r["updated"].strftime("%Y-%m-%d %H:%M")
        src = ("declared by the page" if r["updated_src"] == "page"
               else "inferred from the Vercel deploy age (coarse)")
        return (f'<span class="when" title="{exact} America/Edmonton — {src}">'
                f'{tilde}{_ago(r["updated"], now)}</span>')

    def row_li(r: dict) -> str:
        return (f'    <li><a href="{html.escape(r["url"])}"{NEW_TAB}>'
                f'<span class="t">{html.escape(r["title"])}</span>'
                f'<span class="rt">{when(r)}'
                f'<span class="chip">{html.escape(r["chip"])}</span></span>'
                f'<span class="u">{html.escape(r["url"].removeprefix("https://"))}</span></a></li>')

    # "Newest documents on top" (owner request 2026-08-01), read literally: the most recent
    # pages across ALL lines, before any grouping.
    recent = [r for r in sorted(rows, key=_sort_key) if r["updated"]][:8]
    recent_html = "\n".join(
        f'    <li><a href="{html.escape(r["url"])}"{NEW_TAB}>'
        f'<span class="dot b-{slug(r["group"])}"></span>'
        f'<span class="t">{html.escape(r["title"])}</span>'
        f'<span class="rt">{when(r)}<span class="chip">{html.escape(r["group"])}</span></span>'
        f'</a></li>' for r in recent)

    sections = []
    for g in order:
        items = "\n".join(row_li(r) for r in groups[g])
        n = len(groups[g])
        sections.append(
            f'<section class="line c-{slug(g)}" id="{slug(g)}">\n'
            f'  <div class="lhead"><span class="badge b-{slug(g)}">{html.escape(g)}</span>'
            f'<span class="cnt">{n} page{"s" if n != 1 else ""}</span></div>\n'
            f'  <ul class="stations">\n{items}\n  </ul>\n</section>')

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title_prefix}docs index</title>
<meta name="index-signature" content="{sig}">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Crect width='16' height='16' rx='3' fill='%23131720'/%3E%3Ccircle cx='5' cy='8' r='2.2' fill='%235ec8f2'/%3E%3Ccircle cx='11' cy='8' r='2.2' fill='%23f2a65e'/%3E%3C/svg%3E">
<style>
:root{{
  --bg:#131720; --panel:#1a1f2b; --panel2:#20263380; --ink:#e9e7de; --dim:#9aa3b5;
  --hair:#2c3345; --focus:#ffd166;
{tokens}
}}
@media (prefers-color-scheme: light){{
  :root{{ --bg:#f3f1ea; --panel:#ffffff; --panel2:#e9e5da80; --ink:#20242e; --dim:#5c6474;
    --hair:#d8d2c4; --focus:#8a5a00;
{tokens_light}
  }}
}}
*{{box-sizing:border-box;margin:0;padding:0}}
html{{scroll-behavior:smooth}}
@media (prefers-reduced-motion: reduce){{ html{{scroll-behavior:auto}} *{{transition:none!important;animation:none!important}} }}
body{{background:var(--bg);color:var(--ink);font:15px/1.5 ui-sans-serif,system-ui,"Segoe UI",Roboto,sans-serif;min-height:100vh}}
a{{color:inherit;text-decoration:none}}
a:focus-visible,input:focus-visible,button:focus-visible{{outline:2px solid var(--focus);outline-offset:2px;border-radius:4px}}
header{{padding:34px clamp(18px,5vw,54px) 22px;border-bottom:1px solid var(--hair)}}
.eyebrow{{font:600 11px/1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.22em;text-transform:uppercase;color:var(--dim)}}
h1{{font-size:clamp(30px,5.5vw,52px);font-weight:800;letter-spacing:-.03em;line-height:1.05;margin:10px 0 6px}}
h1 .tick{{display:inline-block;width:.45em;height:.45em;border-radius:50%;background:var(--l-{slug(order[0])});margin:0 .12em 0 .06em}}
.sub{{color:var(--dim);max-width:60ch}}
.hud{{display:flex;flex-wrap:wrap;gap:18px;align-items:center;margin-top:18px}}
.stat{{font:700 13px/1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.06em;color:var(--dim)}}
.stat b{{color:var(--ink);font-size:17px}}
#q{{flex:1 1 260px;max-width:430px;background:var(--panel);color:var(--ink);border:1px solid var(--hair);
   border-radius:9px;padding:10px 14px;font:inherit}}
#q::placeholder{{color:var(--dim)}}
.kbd{{font:600 10.5px/1 ui-monospace,monospace;color:var(--dim);border:1px solid var(--hair);border-radius:4px;padding:2px 5px}}
.wrap{{display:grid;grid-template-columns:230px 1fr;gap:0;align-items:start}}
@media (max-width:820px){{ .wrap{{grid-template-columns:1fr}} nav.lines{{position:static;display:flex;flex-wrap:wrap;gap:6px;border-right:none;border-bottom:1px solid var(--hair)}} nav.lines a{{border-left:none!important;border-radius:99px;border:1px solid var(--hair)}} }}
nav.lines{{position:sticky;top:0;padding:22px 10px 22px clamp(18px,5vw,54px);display:flex;flex-direction:column;gap:2px;border-right:1px solid var(--hair);min-height:50vh}}
nav.lines a{{display:flex;align-items:center;gap:9px;padding:7px 10px;color:var(--dim);font:600 13px/1.2 ui-sans-serif,system-ui,sans-serif;border-left:3px solid transparent}}
nav.lines a:hover{{color:var(--ink);background:var(--panel2)}}
nav.lines a .dot{{width:10px;height:10px;border-radius:50%;flex:none}}
nav.lines a .n{{margin-left:auto;font:600 11px/1 ui-monospace,monospace;color:var(--dim)}}
main{{padding:26px clamp(18px,4vw,50px) 60px}}
section.line{{margin-bottom:34px}}
.lhead{{display:flex;align-items:baseline;gap:12px;margin-bottom:4px}}
.lhead .badge{{font:700 10.5px/1 ui-monospace,monospace;letter-spacing:.14em;text-transform:uppercase;
  padding:4px 9px;border-radius:99px;color:var(--bg)}}
.lhead .cnt{{color:var(--dim);font:600 12px/1 ui-monospace,monospace}}
ul.stations{{list-style:none;border-left:3px solid currentColor;margin-left:6px;padding:6px 0 2px}}
ul.stations li{{position:relative}}
ul.stations li a{{display:grid;grid-template-columns:1fr auto;gap:4px 16px;align-items:baseline;
  padding:9px 12px 9px 24px;border-radius:0 9px 9px 0}}
ul.stations li a::before{{content:"";position:absolute;left:-7.5px;top:50%;transform:translateY(-50%);
  width:9px;height:9px;border-radius:50%;background:var(--bg);border:2.5px solid var(--hair)}}
ul.stations li a:hover{{background:var(--panel2)}}
ul.stations li a:hover::before{{border-color:currentColor}}
.t{{font-weight:650}}
.u{{grid-column:1 / -1;font:12px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--dim);word-break:break-all}}
.rt{{display:flex;align-items:baseline;gap:9px;justify-self:end}}
.chip{{font:700 10px/1 ui-monospace,monospace;letter-spacing:.12em;text-transform:uppercase;color:var(--dim);
  border:1px solid var(--hair);border-radius:4px;padding:3px 6px}}
.when{{font:600 11.5px/1 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--dim);
  min-width:3.2em;text-align:right;cursor:help}}
.when.none{{opacity:.55;cursor:default}}
/* Recently updated — the literal "newest on top" strip, above every grouped line. */
section.recent{{margin:0 0 34px;padding:14px 16px 8px;background:var(--panel);
  border:1px solid var(--hair);border-radius:12px}}
section.recent .rhead{{display:flex;align-items:baseline;gap:12px;margin-bottom:2px}}
section.recent .rhead .badge{{font:700 10.5px/1 ui-monospace,monospace;letter-spacing:.14em;
  text-transform:uppercase;color:var(--dim)}}
section.recent ul{{list-style:none}}
section.recent li a{{display:grid;grid-template-columns:auto 1fr auto;gap:10px;align-items:baseline;
  padding:7px 6px;border-radius:7px}}
section.recent li a:hover{{background:var(--panel2)}}
section.recent .dot{{width:8px;height:8px;border-radius:50%;flex:none;align-self:center}}
li.hide,section.hide{{display:none}}
#recent.hide{{display:none}}
#fresh{{position:fixed;left:50%;transform:translateX(-50%);bottom:20px;z-index:20;display:flex;
  align-items:center;gap:12px;background:var(--panel);color:var(--ink);border:1px solid var(--hair);
  border-radius:999px;padding:9px 10px 9px 18px;box-shadow:0 6px 24px rgba(0,0,0,.28);
  font:600 13px/1 ui-sans-serif,system-ui,sans-serif}}
#fresh[hidden]{{display:none}}
#fresh button{{font:700 12px/1 ui-monospace,monospace;letter-spacing:.06em;text-transform:uppercase;
  background:var(--ink);color:var(--bg);border:0;border-radius:999px;padding:7px 13px;cursor:pointer}}
#none{{display:none;color:var(--dim);padding:30px 0;font-style:italic}}
#none.show{{display:block}}
footer{{border-top:1px solid var(--hair);color:var(--dim);font:12px/1.6 ui-monospace,monospace;
  padding:20px clamp(18px,5vw,54px) 40px}}
{group_css}
</style>
</head>
<body>
<header>
  <div class="eyebrow">{eyebrow}</div>
  <h1>Docs index<span class="tick"></span></h1>
  <p class="sub">Every deployed page, newest first, grouped by the rawgentic project it belongs to. Type to filter; click a line to jump.</p>
  <div class="hud">
    <span class="stat"><b>{total_pages}</b> pages</span>
    <span class="stat"><b>{total_lines}</b> lines</span>
    <input id="q" type="search" placeholder="Filter by name, title, or purpose…" aria-label="Filter pages">
    <span class="kbd">/</span>
    <span class="stat">updated <b>{html.escape(stamp)}</b></span>
  </div>
</header>

<div id="fresh" role="status" hidden><span>New pages published</span><button type="button" id="freshgo">Reload</button></div>

<div class="wrap">
<nav class="lines" aria-label="Project lines">
{nav}
</nav>

<main>
<section class="recent" id="recent">
  <div class="rhead"><span class="badge">recently updated</span></div>
  <ul>
{recent_html}
  </ul>
</section>

{chr(10).join(sections)}

<p id="none">No page matches that filter.</p>
</main>
</div>

<footer>
  naming: {{project}}-{{purpose}}-{{ref}} · derived from `vercel project ls` by
  build_index.py — never hand-edited · {total_pages} pages across {total_lines} lines ·
  generated {html.escape(stamp)} (America/Edmonton)
</footer>

<script>
(function(){{
  var q = document.getElementById('q');
  var none = document.getElementById('none');
  var sections = Array.prototype.slice.call(document.querySelectorAll('section.line'));
  var recent = document.getElementById('recent');
  document.addEventListener('keydown', function(e){{
    if (e.key === '/' && document.activeElement !== q){{ e.preventDefault(); q.focus(); }}
    if (e.key === 'Escape' && document.activeElement === q){{ q.value=''; apply(); q.blur(); }}
  }});
  function apply(){{
    var needle = q.value.trim().toLowerCase();
    var any = false;
    // The recency strip is a shortcut, not a search result — hide it while filtering so
    // a hit inside it cannot be mistaken for a second copy of a grouped row.
    if (recent) recent.classList.toggle('hide', needle !== '');
    sections.forEach(function(sec){{
      var kept = 0;
      Array.prototype.slice.call(sec.querySelectorAll('li')).forEach(function(li){{
        var hit = !needle || li.textContent.toLowerCase().indexOf(needle) !== -1
                  || sec.id.toLowerCase().indexOf(needle) !== -1;
        li.classList.toggle('hide', !hit);
        if (hit) kept++;
      }});
      sec.classList.toggle('hide', kept === 0);
      if (kept > 0) any = true;
    }});
    none.classList.toggle('show', !any);
  }}
  q.addEventListener('input', apply);

  // ---- auto-refresh when new content is published -------------------------------------
  // The page is static, so there is nothing to push an update. It polls its own URL and
  // compares the build signature in <meta name="index-signature">, which changes only when
  // a page was added, removed, retitled or restamped — never merely because the clock moved.
  var meta = document.querySelector('meta[name="index-signature"]');
  var mine = meta && meta.getAttribute('content');
  var banner = document.getElementById('fresh');
  var go = document.getElementById('freshgo');
  if (mine && banner && go && window.fetch) {{
    go.addEventListener('click', function(){{ location.reload(); }});
    var stop = false;
    function busy(){{
      // Reloading out from under someone mid-filter loses their query and their scroll
      // position. In that case offer the banner and let them choose the moment.
      return document.activeElement === q || q.value.trim() !== '';
    }}
    function check(){{
      if (stop || document.hidden) return;
      fetch(location.pathname + '?cb=' + Date.now(), {{cache: 'no-store'}})
        .then(function(r){{ return r.ok ? r.text() : null; }})
        .then(function(t){{
          if (!t) return;
          var m = t.match(/name="index-signature" content="([a-f0-9]{{64}})"/);
          if (!m || m[1] === mine) return;
          stop = true;                       // one decision per change, not one per tick
          if (busy()) banner.hidden = false; else location.reload();
        }})
        .catch(function(){{ /* offline or a blip: try again next tick, never disturb the page */ }});
    }}
    setInterval(check, 90000);
    // A tab left open overnight should be current the moment it is looked at again.
    document.addEventListener('visibilitychange', function(){{ if (!document.hidden) check(); }});
  }}
}})();
</script>
</body>
</html>
"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", help="output path, or - for stdout. Required unless --signature.")
    ap.add_argument("--workspace-file", default=None,
                    help="workspace file used to group pages by project. Resolved from your "
                         "configuration when omitted; grouping is skipped when nothing is "
                         "configured, which is a degradation rather than a failure.")
    ap.add_argument("--vercel-scope", default=None,
                    help="the Vercel team to list. Resolved from your configuration when "
                         "omitted; there is no built-in default, because deploying to the "
                         "wrong account is worse than refusing.")
    ap.add_argument("--config", default=None,
                    help="read configuration from this file instead of the default location")
    ap.add_argument("--no-titles", action="store_true",
                    help="skip <title> fetches (fast; rows are labelled by project name)")
    ap.add_argument("--limit", type=int, default=100,
                    help="vercel project ls page size (it paginates at 20 by default)")
    ap.add_argument("--signature", action="store_true",
                    help="print a hash of the row set and exit; no page is rendered. Changes "
                         "only when a page is added, removed, retitled or restamped — NOT "
                         "when the clock moves. refresh_index.sh diffs this to decide whether "
                         "a redeploy is warranted.")
    args = ap.parse_args(argv)
    if not args.out and not args.signature:
        ap.error("--out is required unless --signature is given")

    # Resolved ONCE, here, and threaded down. Re-resolving inside a helper would let one run
    # answer for two different accounts — the exact hazard that makes `publish_doc` pass these
    # values to this script explicitly rather than letting it look them up again (#9).
    cfg = _user_config()
    try:
        config_path = cfg.config_file(cli_value=args.config)
        scope = cfg.require_vercel_scope(cli_value=args.vercel_scope, config_path=config_path)
        workspace = cfg.workspace_file(cli_value=args.workspace_file, config_path=config_path)
    except cfg.ConfigError as e:
        sys.exit(f"build_index: {e}")

    now = datetime.now(ZoneInfo("America/Edmonton"))
    entries = vercel_projects(args.limit, scope=scope)
    # Rendering an index from nothing is what the refusal was always about, so it lives here
    # now rather than inside the listing function every consumer shares (#9). It also checks
    # the FILTERED list, which the old placement could not: an account holding only
    # `docs-index` used to reach `render` with zero rows and raise `IndexError` from the
    # `order[0]` its own accent CSS reads.
    if not entries:
        sys.exit("build_index: no pages to index — the account holds no published documents "
                 "yet. Refusing to render an empty index. Publish something first.")
    projects = known_projects(workspace)
    rows = build_rows(entries, projects, fetch_titles=not args.no_titles)

    sig = signature(rows)
    if args.signature:
        print(sig)
        return 0

    stamp = now.strftime("%Y-%m-%d %H:%M %Z")
    page = render(rows, stamp, now, sig, workspace, scope)

    if args.out == "-":
        sys.stdout.write(page)
    else:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(page, encoding="utf-8")
        print(f"build_index: wrote {args.out} — {len(rows)} pages, "
              f"{len({r['group'] for r in rows})} lines, stamped {stamp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
