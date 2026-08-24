#!/usr/bin/env python3
"""One command from a committed markdown doc to a verified-live page (#12, wave 5).

Design: `docs/planning/2026-08-01-12-publish-pipeline.md` (revision 2, after a Step 4
gate returned FAIL with six High findings).

Every step here already existed as prose in `SKILL.md`, and the prose had a measured
failure rate: 37 Vercel projects, junk names like `deploy-713`, three duplicate deploys
of one page, no index. Prose is re-performed by a model on every publish; a command is
not. So the exit code is the verdict.

    python3 publish_doc.py --md docs/planning/x.md --project herdr-dashboard \\
                           --type design --ref 81 --title "#81 The Design"

Seven stages, each able to refuse (exit ``EXIT_BASE + stage``):

    1 render  2 name  3 LINT  4 reuse-or-create  5 deploy  6 verify  7 index

**The gate runs BEFORE the deploy, and that is a correction to the issue's own order.**
The issue lists deploy → lint → verify, but AC4 requires a lint failure to leave
"nothing deployed". Those cannot both hold: linting after the deploy means a page with
an external request or a sub-AA token pair is already public by the time it is caught.

Three things this file is careful about, each because the first draft got it wrong:

* **A name is validated by COMPONENT, never by shape.** `--project deploy --type design
  --ref 713` yields `deploy-design-713`, which matches the convention's pattern
  perfectly and is exactly the junk the convention exists to stop.
* **The deploy is bound to the rendered file**, not to ambient link state — a temp dir
  holding it as `index.html`, linked in that directory. `vercel deploy --prod` from the
  wrong directory deploys the repository.
* **The verifier is written here, not borrowed.** `page_meta()` in `build_index.py`
  sends no cache-buster, exposes no status code, and collapses every failure into
  `(name, None)` — so a dead page and a live one are indistinguishable.

Version control and PR sequencing stay OUT of this script (AC6): committing and opening
a pull request remain the workflows' business, and a test greps this file to keep it so.
"""
from __future__ import annotations

import argparse
import html
import importlib.util
import json
import os
import random
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
INDEX_SCRIPT = HERE.parent / "index" / "build_index.py"


def _load(path: Path, private_name: str):
    """Load a module from an exact path, under a private name, without consulting
    ``sys.path``.

    The same guard `render-doc` documents at length: a foreign package named `render`
    sitting earlier on the path would otherwise be selected AND have its top-level code
    executed before any check could reject it. Resolving the file we intend to run and
    loading that file directly removes the choice entirely.
    """
    spec = importlib.util.spec_from_file_location(private_name, path)
    if spec is None or spec.loader is None:
        sys.exit(f"publish_doc: refusing to run: could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[private_name] = module
    spec.loader.exec_module(module)
    return module


RENDER = _load(HERE / "render" / "__init__.py", "_publish_doc_render")
_LINT = _load(HERE / "render" / "lint.py", "_publish_doc_lint")
SOURCE_LINT = _load(HERE / "render" / "source_lint.py", "_publish_doc_source_lint")
LINT = _LINT.lint
# Not part of `lint()` on purpose — see the note above `check_blocks` in lint.py.
CHECK_BLOCKS = _LINT.check_blocks
# #130, the strict sibling: `check_blocks` is a floor that one component of any kind clears;
# this one requires the devices the page's own style opens with. Disjoint by construction —
# exactly one of the two ever fires.
CHECK_STYLE_DEVICES = _LINT.check_style_devices
# The one part of the component policy `--skip-component-checks` does NOT reach — see `gate()`.
CHECK_TEMPLATE_CLASSIFICATION = _LINT.check_template_classification
INDEX = _load(INDEX_SCRIPT, "_publish_doc_index")
VDL = _load(HERE / "vdl_packs.py", "_publish_doc_vdl")
CONFIG = _load(HERE / "user_config.py", "_publish_doc_user_config")

# Offset past argparse's own exit code 2, so a usage error is never mistaken for a
# stage failure — stage 2 (naming) would otherwise share it.
EXIT_BASE = 10

# The publication purposes of the {project}-{purpose}-{ref} convention. This is what
# `--type` names, and it is NOT the template vocabulary — see PURPOSE_STYLE.
PURPOSES = ("design", "plan", "uat", "audit", "report", "runbook", "analysis", "spec",
            # #42: the page that documents a project's own design language.
            "tokens", "map", "deck")

# The only bridge between the two vocabularies (§2b). A purpose says WHY the page
# exists; a style says how it looks. `plan`/`audit`/`runbook` are not styles, and
# `roadmap`/`dashboard`/`workflow` are not purposes — a test pins that every value here
# is a real entry in the renderer's registry, so a renamed template fails loudly.
PURPOSE_STYLE = {
    "design": "design",
    "plan": "roadmap",
    "uat": "uat",
    "audit": "review",
    "report": "report",
    "runbook": "workflow",
    "analysis": "analysis",
    "spec": "spec",
    "tokens": "design-system",
    "map": "module-map",
    "deck": "slide-deck",
}

# Every Vercel call is still pinned to a team — that has not changed and must not. Ambient
# scope is whatever the last `vercel switch` left behind, so an unpinned deploy can land in a
# personal account. Raised by the security lane on #12 and again on #19.
#
# What #9 changed is WHERE the team comes from. It used to be the string "3d-stories" written
# here, which meant this tool worked for exactly one account. It is now resolved from the
# user's own configuration, ONCE in `main`, and threaded through every stage — including the
# index-refresh CHILD PROCESS, which would otherwise be free to resolve a different account
# halfway through a single publish. There is deliberately no fallback: `require_vercel_scope`
# raises rather than returning anything a caller could pass to `--scope`.

WORKSPACE_BUCKET = "workspace"     # the one literal that is not a rawgentic project
INDEX_PROJECT = "docs-index"
MAX_NAME = 100

# Vercel cuts the auto-assigned `<name>.vercel.app` label at 35 characters and strips a
# trailing hyphen left by the cut (#23; measured 2026-08-13 across the 20 live projects:
# longest intact label 33, every truncated label 34-35, shortest truncated name 36 — and
# confirmed on the 2026-08-12 deploy where a 41-char name aliased to a 35-char label).
# An over-cap name deploys FINE and then 404s at its conventional URL forever, so stage 2
# refuses it: refusing before the deploy is cheaper than stage 6 discovering it after.
MAX_ALIAS_LABEL = 35

# Local plumbing, so a hung git cannot hang a publish. Generous: a first fetch on a big
# repository is genuinely slow.
_GIT_TIMEOUT = 120


class StageError(Exception):
    """A stage refused. The process exits ``EXIT_BASE + stage``."""

    def __init__(self, stage: int, message: str):
        super().__init__(message)
        self.stage = stage
        self.message = message


# --- #36: the declared states, and why they sit ABOVE the stage block ------------------
#
# `EXIT_BASE + stage` owns 11 through 17. A code inside that range cannot be told apart
# from a stage FAILURE, and these two are not failures — they are states the operator
# declared by leaving a variable unset. Putting them at 25 and 26 is what lets a caller
# distinguish "you did not configure an endpoint" from "stage 5 tried and could not".

EXIT_CONTROL_URL_UNSET = 25
EXIT_EDGE_SKIPPED = 26


class DeclaredStateError(Exception):
    """Not a stage failure: a state the operator declared by leaving a variable unset.

    Carries its own exit code rather than deriving one from a stage, because the whole
    point is that no stage was reached.
    """

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _normalized_origin(raw: str, *, stage: int, varname: str) -> str:
    """`scheme://host[:port]`, or raise.

    Step-4 finding N4: the previous rule was syntactic — https, or a host with no dot —
    which still let the publish bearer reach ANY https host. Transport syntax does not
    establish server identity. This function does the half that IS mechanical: it refuses
    anything that is not exactly scheme, host and port, so a base URL can never smuggle
    userinfo (which is a credential), a path, a query or a fragment past the allowlist
    check that follows it.
    """
    parsed = urllib.parse.urlsplit(raw.strip())
    if parsed.scheme not in ("http", "https"):
        raise StageError(stage, f"{varname} must be an http or https URL, not {raw.strip()!r}")
    if not parsed.hostname:
        raise StageError(stage, f"{varname} carries no host: {raw.strip()!r}")
    if parsed.username or parsed.password:
        raise StageError(
            stage, f"{varname} carries userinfo, which is a credential in a URL. "
                   "Give scheme, host and port only.")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise StageError(
            stage, f"{varname} must be scheme, host and port only — no path, query or "
                   f"fragment. Got {raw.strip()!r}")
    return f"{parsed.scheme}://{parsed.netloc}"


def control_base(env) -> str:
    """The control API base, or raise. **There is no default** (owner decision D21).

    Revision 2 of the #36 design defaulted this to the compose-network address
    ``http://harness:8080`` and called it reachable today. Measured on the harness host
    2026-08-24: the host reaches a container's BRIDGE IP with no published port, and never
    resolves a compose SERVICE name. `compose.yaml` states the harness publishes no host
    port and never will. So there is no value that is right by default, and guessing one
    is how a publish fails with a connection error instead of a sentence.
    """
    raw = (env.get("DOC_HARNESS_CONTROL_URL") or "").strip()
    if not raw:
        raise DeclaredStateError(
            EXIT_CONTROL_URL_UNSET,
            "DOC_HARNESS_CONTROL_URL is not set, and it has no default. Point it at the "
            "harness control API. From the harness host that is the container's bridge "
            "address: DOC_HARNESS_CONTROL_URL=http://$(docker compose ps -q harness | "
            "xargs docker inspect -f "
            "'{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'):8080")
    return _normalized_origin(raw, stage=5, varname="DOC_HARNESS_CONTROL_URL")


def public_base(env) -> str | None:
    """The public host pattern for stage 6's edge half, or ``None`` meaning SKIP.

    Unset is a legitimate declared state, not an error: no harness hostname resolves yet.
    The skip is visible and exits ``EXIT_EDGE_SKIPPED``; it never exits 0, because every
    caller and script reads 0 as a pass.
    """
    raw = (env.get("DOC_HARNESS_PUBLIC_BASE") or "").strip()
    if not raw:
        return None
    base = _normalized_origin(raw, stage=6, varname="DOC_HARNESS_PUBLIC_BASE")
    if not base.startswith("https://"):
        raise StageError(
            6, "DOC_HARNESS_PUBLIC_BASE must be https: the Cloudflare Access service "
               f"tokens are sent to this host, and plaintext would expose them. Got {base!r}")
    return base


# --- #36 stage 4a: provenance, failing LOCALLY -----------------------------------------
#
# The harness does not accept rendered bytes. It takes a manifest naming a repo, a full
# commit sha and, per asset, a repo path and a blob id, then fetches every blob FROM
# GITHUB and refuses on any mismatch. So the page must be committed and pushed BEFORE the
# publish, and the publish pins that commit.
#
# Each check below is a refusal the harness would eventually make anyway. Making it here
# turns a 422 about a blob id into one clear local sentence.

_GITHUB_SLUG = re.compile(
    r"^(?:git@github\.com:|ssh://git@github\.com/|https?://(?:[^@/]+@)?github\.com/)"
    r"(?P<slug>[^/\s]+/[^/\s]+?)(?:\.git)?/?$")


def _git(argv: list[str], cwd: Path | None = None, *, runner=None):
    """One git call. `runner` exists so the suite can script git without a real repository.

    Looked up on the module at call time (never bound at import) so the existing
    `monkeypatch.setattr(subprocess, "run", ...)` fixture keeps working unchanged.
    """
    run = runner if runner is not None else subprocess.run
    full = ["git", *(["-C", str(cwd)] if cwd is not None else []), *argv]
    return run(full, capture_output=True, text=True, check=False, timeout=_GIT_TIMEOUT)


def github_slug(url: str) -> str | None:
    """`owner/name` for a GitHub remote URL, else None. Normalizing here is what lets the
    manifest's `repo` be DERIVED from the selected remote rather than configured beside it,
    so the two can never disagree."""
    m = _GITHUB_SLUG.match((url or "").strip())
    return m.group("slug") if m else None


def repo_root(path: Path, *, runner=None) -> str | None:
    r = _git(["rev-parse", "--show-toplevel"], path, runner=runner)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def assert_one_repository(md: Path, out: Path, *, runner=None) -> str:
    """Finding S1. `--md` and `--out` are arbitrary paths and this tool runs across a whole
    workspace, so the document routinely lives in a different repository from the process's
    cwd. Resolving via cwd pins the WRONG repo. The benign failure is a 422; the dangerous
    one is that the path exists in the wrong repo and the harness serves a **different file
    under the right name**, with every downstream check still passing."""
    a = repo_root(md.resolve().parent, runner=runner)
    b = repo_root(out.resolve().parent, runner=runner)
    if a is None or b is None:
        raise StageError(4, f"--md and --out must live inside a git repository; "
                            f"{'--md' if a is None else '--out'} does not.")
    if a != b:
        raise StageError(
            4, f"--md and --out resolve into different repositories ({a} and {b}). "
               "The harness would serve a different file under the right name, and every "
               "later check would still pass. Refusing.")
    return a


def assert_blob_committed(root: Path, repo_path: str, blob_id: str, *, runner=None) -> None:
    """Finding A2. Compare against the COMMITTED blob, never against the file's own bytes.

    `git hash-object <file>` hashes the working tree, so comparing it to itself proves
    nothing about the commit being pinned. The real question is whether `HEAD:<repo_path>`
    is that same blob.
    """
    r = _git(["rev-parse", f"HEAD:{repo_path}"], root, runner=runner)
    if r.returncode != 0:
        raise StageError(
            4, f"{repo_path} is not committed at HEAD, so the harness cannot fetch it. "
               "Commit and push the rendered page and its assets before publishing.")
    committed = r.stdout.strip()
    if committed != blob_id:
        raise StageError(
            4, f"{repo_path} in the working tree is not what HEAD holds "
               f"(working tree {blob_id}, HEAD {committed}). The publish would pin a commit "
               "that does not contain these bytes. Commit the change first.")


def select_remote(root: Path, override: str | None, *, runner=None) -> tuple[str, str]:
    """The remote to pin, and the `owner/name` derived FROM it. Findings M5 and N9.

    Ordered, stopping at the first that resolves. The order matters: the first attempt at
    this refused whenever two GitHub remotes existed, which is every ordinary
    fork-plus-upstream checkout — it would have refused far more often than it caught
    anything.
    """
    names = [n for n in _git(["remote"], root, runner=runner).stdout.split() if n]

    def slug_of(name):
        return github_slug(_git(["remote", "get-url", name], root, runner=runner).stdout)

    # a. an explicit override always wins.
    if override:
        if override not in names:
            raise StageError(4, f"--publish-remote {override!r} is not a remote here. "
                                f"Remotes: {', '.join(names) or 'none'}")
        slug = slug_of(override)
        if slug is None:
            raise StageError(4, f"--publish-remote {override!r} is not a GitHub remote. "
                                "The harness fetches blobs from GitHub.")
        return override, slug

    # b. the branch's own upstream, when it is a GitHub remote.
    up = _git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
              root, runner=runner)
    if up.returncode == 0 and "/" in up.stdout.strip():
        name = up.stdout.strip().split("/", 1)[0]
        slug = slug_of(name)
        if slug is not None:
            return name, slug

    # c. exactly one GitHub remote needs no upstream at all.
    github = [(n, slug_of(n)) for n in names]
    github = [(n, sl) for n, sl in github if sl is not None]
    if len(github) == 1:
        return github[0]
    if not github:
        raise StageError(
            4, f"no GitHub remote here, and the harness fetches blobs from GitHub. "
               f"Remotes: {', '.join(names) or 'none'}")
    raise StageError(
        4, "cannot tell which remote to pin: this branch has no upstream and there are "
           f"several GitHub remotes ({', '.join(n for n, _ in github)}). "
           "Pass --publish-remote <name>.")


def assert_head_reachable(root: Path, remote: str, branch: str, *, fetch: bool,
                          runner=None) -> None:
    """Finding A6. "Is HEAD pushed" is NOT `ls-remote` succeeding, and it is NOT ref-tip
    equality — a pushed commit that is no longer a tip is still perfectly reachable, and
    tip-matching would falsely reject it. The rule is that nothing on HEAD is missing from
    the remote-tracking ref.

    `fetch` is False under `--dry-run` (finding N10, AC5): the fetch is new network access
    and it mutates remote-tracking refs, so a flag whose whole point is touching nothing
    must not perform it.
    """
    if fetch:
        f = _git(["fetch", remote], root, runner=runner)
        if f.returncode != 0:
            raise StageError(4, f"git fetch {remote} failed, so reachability cannot be "
                                f"established: {(f.stderr or f.stdout).strip()}")
    ref = f"{remote}/{branch}"
    r = _git(["rev-list", "--count", f"{ref}..HEAD"], root, runner=runner)
    if r.returncode != 0:
        raise StageError(4, f"cannot compare HEAD against {ref}: "
                            f"{(r.stderr or r.stdout).strip()}")
    if r.stdout.strip() != "0":
        listing = _git(["rev-list", "--oneline", f"{ref}..HEAD"], root, runner=runner)
        raise StageError(
            4, f"HEAD is not reachable from {ref}: {r.stdout.strip()} commit(s) are not "
               f"pushed. The harness fetches from GitHub and would not find them.\n"
               + listing.stdout.rstrip())


# --- stage 1: render -----------------------------------------------------------------

MAX_FETCH = 8_000_000


def _check_paths(md_path: Path, out_path: Path) -> None:
    """Refuse the two path shapes that lose data or leak it.

    A symlinked `--md` is followed like any other file, and the renderer supplies the
    title and stamp and escapes the body — so a link pointing at a readable secret
    renders into a page that passes the mechanical gate and is then deployed PUBLICLY.
    A `--out` equal to `--md` reads the source and overwrites it with HTML, destroying
    the document and the `.md`/`.html` pair the convention requires.
    """
    if md_path.is_symlink():
        raise StageError(1, f"--md {md_path} is a symlink. These pages are public and "
                            f"this script follows what it is given, so the source must "
                            f"be a real file in the repo.")
    if not md_path.is_file():
        raise StageError(1, f"--md {md_path} is not a regular file")
    if out_path.suffix.lower() != ".html":
        raise StageError(1, f"--out {out_path} must end in .html — it is the committed "
                            f"half of the pair")
    if out_path.is_symlink():
        raise StageError(1, f"--out {out_path} is a symlink; refusing to write through it")
    try:
        same = out_path.resolve() == md_path.resolve()
    except OSError as e:
        raise StageError(1, f"could not resolve {out_path}: {e}") from e
    if same:
        raise StageError(1, f"--out resolves to the same file as --md ({md_path}); that "
                            f"would overwrite the source with its own rendering")


def load_telemetry(path: Path | None) -> dict | None:
    """#152. The run-telemetry block, read from a JSON file.

    `render_artifact` has always accepted a `telemetry` mapping and rendered a **Run telemetry**
    section from it; the WF2 design-artifact step passes one. This script never could, so a page
    created by that step and later re-published HERE silently lost the whole section — measured
    on `docs/planning/campaign-log.html` during #130, where the only copy of that content lived
    in the generated file and the records behind it sit in an UNTRACKED store.

    Fails LOUD on anything it cannot use, because a silently dropped section is the entire defect
    class this closes. Absent stays the default and renders exactly as before.
    """
    if path is None:
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise StageError(1, f"could not read --telemetry {path}: {e}") from e
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as e:
        raise StageError(1, f"--telemetry {path} is not valid JSON: {e}") from e
    if not isinstance(value, dict):
        raise StageError(1, f"--telemetry {path} must hold a JSON object, not "
                            f"{type(value).__name__} — the renderer reads it as a run-record "
                            f"mapping (see hooks/work_summary.py for the shape)")
    # An EMPTY object is deliberately allowed through, and this is worth stating because the
    # obvious validation is wrong. `render_artifact` branches on `telemetry is not None`, and
    # `_telemetry_html` renders an explicit `{}` as a visible "telemetry unavailable" placeholder
    # — "a record present but empty", which its own comment distinguishes from `None` ("no
    # telemetry"). Rejecting `{}` here would delete that distinction and make this flag unable to
    # express a state the renderer supports on purpose. Same for a well-formed object with no
    # recognised run-record fields: the renderer surfaces a placeholder rather than pretending,
    # which is louder than anything this function could add.
    return value


def render(md_path: Path, out_path: Path, *, title: str, subtitle: str,
           style: str, doc_id: str | None, vdl: dict | None = None,
           telemetry: dict | None = None, section_chips: bool = True) -> str:
    """Render to the committed `.html` and return the same string the gate will read."""
    _check_paths(md_path, out_path)
    try:
        markdown = md_path.read_text(encoding="utf-8")
    except OSError as e:
        raise StageError(1, f"could not read {md_path}: {e}") from e
    page = RENDER.render_artifact(markdown, title=title, subtitle=subtitle,
                                  style=style, doc_id=doc_id, vdl=vdl,
                                  telemetry=telemetry, section_chips=section_chips)
    # Cross-model review, and it caught my own claim being overstated: `load_telemetry` validated
    # only JSON shape, so a typoed record like `{"tsets": {...}}` published happily and rendered
    # "telemetry unavailable" — a successful exit whose figures were discarded, from a function
    # whose docstring promised to fail loud on anything it could not use.
    #
    # Validated by ASKING THE RENDERER rather than by re-implementing its field predicate here:
    # `_telemetry_html` already decides what a run-record is, and a second copy of that judgement
    # is exactly the drift this codebase keeps paying for. A truthy record that renders the
    # placeholder is a wrong or mistyped file.
    #
    # `{}` is exempt on purpose — falsy, and the renderer's own comment calls it "record present
    # but empty", a state it distinguishes from absent and renders the placeholder for
    # deliberately.
    if telemetry and "telemetry unavailable" in page:
        raise StageError(1, "the --telemetry file parsed as JSON but the renderer recognised no "
                            "run-record fields in it, so the page would publish with a "
                            "'telemetry unavailable' placeholder instead of your figures. Check "
                            "the keys against hooks/work_summary.py's run-record shape (a typo "
                            "like 'tsets' for 'tests' does this), or omit the flag.")
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(page, encoding="utf-8")
    except OSError as e:
        raise StageError(1, f"could not write {out_path}: {e}") from e
    return page


# --- stage 2: the name ---------------------------------------------------------------

_REF_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_REF_ISSUE = re.compile(r"^[1-9][0-9]*$")   # canonical: `1` is valid, `01` is not
_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


def derive_name(project: str, purpose: str, ref: str, workspace_file: Path) -> str:
    """`{project}-{purpose}-{ref}` from components each checked against a source of truth.

    Lowercased before assembly because Vercel lowercases anyway, so `Rawgentic` and
    `rawgentic` must not become two projects. There is deliberately no flag that accepts
    a name.
    """
    project = project.strip().lower()
    purpose = purpose.strip().lower()
    ref = ref.strip().lower()

    if purpose not in PURPOSES:
        raise StageError(2, f"--type {purpose!r} is not a publication purpose "
                            f"(one of: {', '.join(PURPOSES)})")

    if project != WORKSPACE_BUCKET:
        known = INDEX.known_projects(Path(workspace_file))
        if project not in known:
            raise StageError(
                2, f"--project {project!r} is not a rawgentic project in "
                   f"{workspace_file}, and is not the literal {WORKSPACE_BUCKET!r} "
                   f"bucket. This is the check that refuses 'deploy', 'site' and "
                   f"'final-final' — names that pass a shape check and mean nothing.")

    if ref in PURPOSES:
        raise StageError(2, f"--ref {ref!r} is a purpose token, not a reference — "
                            f"the name would read as two purposes and no subject")
    # An issue number has its own rule. Under the slug rule alone, issue 1 was
    # unpublishable (one character) while `01` was accepted — and `-01` and `-1` are two
    # Vercel projects for one issue, which is the duplication this whole convention exists
    # to prevent.
    if ref.isdigit():
        if not _REF_ISSUE.match(ref):
            raise StageError(2, f"--ref {ref!r} is not a canonical issue number; use "
                                f"{ref.lstrip('0') or '0'!r} — a leading zero would mint "
                                f"a second project for the same issue")
    elif not 2 <= len(ref) <= 40 or not _REF_SLUG.match(ref):
        raise StageError(2, f"--ref {ref!r} must be an issue number, or a lowercase "
                            f"slug of 2-40 chars (letters, digits, single hyphens)")

    name = f"{project}-{purpose}-{ref}"
    if len(name) > MAX_NAME or not _NAME.match(name):
        raise StageError(2, f"the derived name {name!r} is not a usable Vercel project "
                            f"name (lowercase letters, digits and hyphens, "
                            f"{MAX_NAME} chars max)")
    # The alias cap comes AFTER name validity so the two limits stay distinguishable: an
    # unusable name gets the message above; a usable one that cannot round-trip to its
    # own `.vercel.app` domain gets this one (#23).
    if len(name) > MAX_ALIAS_LABEL:
        raise StageError(2, f"the derived name {name!r} is {len(name)} characters, over "
                            f"the {MAX_ALIAS_LABEL}-char cap Vercel puts on a "
                            f".vercel.app label. A longer name deploys, but its domain "
                            f"gets TRUNCATED and the conventional URL 404s forever "
                            f"(#23, measured live). Shorten --ref by at least "
                            f"{len(name) - MAX_ALIAS_LABEL} character(s).")
    return name


# --- stage 3: the lint gate ----------------------------------------------------------

def source_gate(md_path: Path, *, allow_unsupported: bool = False,
                ack_stale: bool = False) -> list[str]:
    """Check the SOURCE, before anything deploys. Returns the notes worth printing.

    Everything else in this pipeline answers "did the bytes I linted reach the page?" —
    which was always true on the two live defects that produced this function. Neither was
    a delivery failure. Both were the markdown not saying what its author meant, and the
    only place to catch that is here, against the source.
    """
    md = md_path.read_text(encoding="utf-8")
    notes: list[str] = []

    unsupported = SOURCE_LINT.check_unsupported_syntax(md)
    if unsupported and not allow_unsupported:
        raise StageError(3, "the source uses markdown this renderer does not implement, so "
                            "those characters would reach the page literally. Nothing was "
                            "deployed:\n  - " + "\n  - ".join(unsupported)
                         + "\n\n  Fix them, or pass --allow-unsupported-markdown if you "
                           "really mean the literal characters.")
    if unsupported:
        notes.append(f"--allow-unsupported-markdown: {len(unsupported)} construct(s) WILL "
                     f"render as literal source characters")

    # The VCS read lives in `source_lint`, deliberately. AC6 keeps version control out
    # of THIS script — `TestGitStaysOut` greps it for the word — and that rule is about
    # the publisher not taking over commit and PR duties. Reading the last committed
    # text to diff against is neither, but the guard is blunt on purpose, so the read
    # sits with the other source analysis instead of arguing with it.
    drift = SOURCE_LINT.check_status_drift(
        SOURCE_LINT.previous_committed(md_path), md)
    if drift and not ack_stale:
        raise StageError(3, "this revision marks something done, but the document still "
                            "says otherwise elsewhere. A status change to a living document "
                            "is a sweep, not an edit. Nothing was deployed:\n  - "
                         + "\n  - ".join(drift)
                         + "\n\n  Update those lines too, or pass --ack-stale if they are "
                           "deliberately historical records of what was true then.")
    if drift:
        notes.append(f"--ack-stale: {len(drift)} line(s) still read as open and were "
                     f"published anyway")
    return notes


def gate(page: str, *, skip_component_checks: bool = False) -> None:
    findings = LINT(page)
    # UNCONDITIONAL, deliberately: an unknown template class or two `<body>` tags is
    # structural corruption — a renderer defect or an edited page — not a statement that the
    # document is prose. Cross-model review caught this sitting inside the flag, where
    # the flag waved through exactly the inputs the fail-closed rule exists to stop.
    findings += [f"template: {f}" for f in CHECK_TEMPLATE_CLASSIFICATION(page)]
    # Scoped to the TWO component checks and nothing else. A flag that turned the whole gate
    # off would be a worse defect than the one it exists to work around. The two are disjoint,
    # so at most one of them ever reports.
    if not skip_component_checks:
        findings += [f"blocks: {f}" for f in CHECK_BLOCKS(page)]
        findings += [f"style-devices: {f}" for f in CHECK_STYLE_DEVICES(page)]
    if findings:
        raise StageError(3, "the page did not pass the pre-publish lint gate, so "
                            "nothing was deployed:\n  - " + "\n  - ".join(findings))


# --- the Vercel CLI ------------------------------------------------------------------

#: A publish call uploads, so it gets more room than a status probe — but it still gets a
#: bound. Unbounded, a non-responsive CLI hangs the whole publish instead of failing it.
_VERCEL_TIMEOUT = 300


def _vercel(args: list[str], cwd: Path, scope: str) -> subprocess.CompletedProcess:
    """Every call is given an explicit cwd, and every path used afterwards is absolute —
    the CLI resets the shell's working directory.

    `scope` is REQUIRED and is never conditionally omitted (#9). Dropping `--scope` when no
    team is configured would silently target whichever account `vercel switch` last selected,
    which is the failure the pin exists to prevent — so the caller refuses long before here.
    """
    try:
        return subprocess.run(["vercel", *args, "--scope", scope], cwd=str(cwd),
                              capture_output=True, text=True, check=False,
                              timeout=_VERCEL_TIMEOUT)
    except subprocess.TimeoutExpired:
        # Fail the stage rather than raise. Every caller already reads `returncode` and
        # `stderr`, so a synthetic failure keeps them working and keeps the reason legible.
        # 124 is the conventional exit code for a timed-out command.
        return subprocess.CompletedProcess(
            ["vercel", *args, "--scope", scope], 124, "",
            "vercel did not answer within %d seconds, so this stage was stopped rather "
            "than left hanging. Nothing about your account or permissions is implied."
            % _VERCEL_TIMEOUT)


#: Vercel's own wording for a permission refusal, matched loosely on purpose: this only
#: chooses which of two messages a failed deploy prints, so a miss costs a less specific
#: diagnostic and never a wrong outcome. Both paths still fail the stage.
_DENIED = ("not authorized", "not a member", "forbidden", "do not have permission",
           "does not have permission", "access denied")


def _looks_like_denied(log: str) -> bool:
    lowered = log.lower()
    return any(marker in lowered for marker in _DENIED)


def _log(proc: subprocess.CompletedProcess) -> str:
    """The CLI splits output across both streams, so every consumer here reads the pair.

    `project ls` used to be the example named here. Since #125 it is requested with
    `--format json` and read from stdout ALONE, by `build_index.vercel_projects` — never through
    this helper. `link` and `deploy` still come through it, and concatenating both streams is
    what saves this file from having to know which one each of them picks.
    """
    return (proc.stdout or "") + (proc.stderr or "")


# --- stage 4: reuse or create --------------------------------------------------------

def _says_no_such_project(proc, name: str) -> bool:
    """True only for the CLI's authoritative "no project named THIS", on stderr.

    Absence is the reading that mints a duplicate project under a new URL, so it is the
    narrowest branch in this file, and two things narrow it:

    * **stderr only.** That is where the CLI puts its error. Accepting the phrase from stdout
      widens what can trigger absence for no gain.
    * **It must name THIS project.** A bare substring test read a not-found about a DIFFERENT
      project as absence for the one being asked about — and then `--new-project` would mint
      a duplicate of a project that already existed.

    Verified live against Vercel CLI 56.5.0: `Error: There is no project for "<name>"`.
    """
    needle = 'there is no project for "%s"' % name.lower()
    return needle in (proc.stderr or "").lower()


def resolve_project(name: str, *, new_project: bool, scope: str) -> bool:
    """True if the project already exists (and is being reused).

    **This asks about ONE project. It does not enumerate the account, and that is the point.**

    It used to list every project in the team and test membership. Two failures came out of
    that, one certain and one latent, and they pull in opposite directions:

    * A brand-new account has NO projects, and the listing refused an empty result outright —
      so a first publish died at stage 4 while setup reported the account ready (#9).
    * Reading absence out of an empty LIST is unsound anyway. A truncated or erroneous CLI
      response can carry the requested tenant, an empty `projects` array and a null cursor,
      which is indistinguishable from a genuinely empty account. Stage 4 answers absence by
      minting a duplicate project under a new URL — the #125 failure, which changes a
      published document's URL.

    Asking about the one project removes both. `vercel project inspect` gives an EXPLICIT
    not-found, so absence is something the platform states rather than something inferred from
    a listing whose completeness had to be proved. Probed live against Vercel CLI 56.5.0: exit
    0 when the project exists, exit 1 with `Error: There is no project for "<name>"` when it
    does not.

    Anything else — a network error, a rate limit, a changed CLI — is a stage-4 error. It is
    NEVER read as absence, because that is the reading that mints the duplicate.
    """
    try:
        proc = _vercel(["project", "inspect", name], cwd=Path.cwd(), scope=scope)
    except OSError as e:
        # A missing or unrunnable binary RAISES rather than returning, so the promise that
        # everything but an explicit not-found is a stage-4 error has to catch it here.
        raise StageError(4, f"could not run the `vercel` CLI to check whether {name} exists "
                            f"({e.__class__.__name__}: {e}). Install it, or check it is on "
                            f"PATH.") from e
    if proc.returncode == 0:
        exists = True
    elif _says_no_such_project(proc, name):
        exists = False
    else:
        raise StageError(4, f"could not determine whether {name} exists (rc="
                            f"{proc.returncode}). Refusing to guess: reading this as "
                            f"'absent' would mint a duplicate project under a new URL.\n"
                            f"{_log(proc)}")
    if exists and new_project:
        raise StageError(4, f"{name} already exists — drop --new-project and it is "
                            f"reused, which is what keeps its URL stable. Otherwise the "
                            f"flag becomes the thing people paste to clear the error.")
    if not exists and not new_project:
        raise StageError(4, f"no Vercel project named {name}. Reuse is the default; "
                            f"re-run with --new-project once you are sure this doc has "
                            f"never been published under another name.")
    return exists


# --- stage 5: the deploy -------------------------------------------------------------

# A line that STARTS the Aliased verdict: optional non-alphanumeric marker glyphs
# (the CLI's `▲`), then the word. `Error: … was not aliased …` starts with `Error`,
# so it can never match (#23, Step 11 finding).
_ALIASED_LINE = re.compile(r"^[^A-Za-z0-9]*aliased\b", re.I)

# A COMPLETE host token: the lookahead is what stops `https://old.vercel.app.evil/x`
# from reading as a vercel.app host, which a trailing `\S*` happily accepted.
_URL_HOST = re.compile(r"https://([a-z0-9][a-z0-9.-]*\.vercel\.app)(?=[/\s]|$)", re.I)


def deployed_hosts(log: str, name: str) -> list[str]:
    """The hosts in a deploy log that belong to THIS project.

    `vercel deploy` prints the deployment URL (`<name>-<hash>-<team>.vercel.app`) and
    usually the alias. Accepting any vercel.app URL would accept a log that only ever
    mentions somebody else's project — which is exactly what a deploy bound to ambient
    link state looks like.
    """
    out = []
    for host in _URL_HOST.findall(log):
        h = host.lower()
        if h == f"{name}.vercel.app" or h.startswith(f"{name}-"):
            out.append(h)
    return out


def aliased_host(log: str, name: str, stage: int = 6) -> str:
    """The host the deploy itself reported as THIS project's alias (#23).

    Stage 6 used to fetch a URL CONSTRUCTED from the project name, and for any name over
    `MAX_ALIAS_LABEL` that URL is permanently absent (Vercel truncates the label), so a
    perfect deploy read as `HTTP 404 — not live`. The deploy's own `Aliased` line is the
    truth, and it is already in the log stage 5 receives — zero extra CLI calls, and the
    same trust boundary `deployed_hosts` uses for the stage-5 binding check.

    Two host shapes are THIS project's alias, judged per host from the same `_URL_HOST`
    scan `deployed_hosts` uses:
    * the label equals the name — the intact alias, preferred;
    * the label is a PREFIX of the name no shorter than `MAX_ALIAS_LABEL - 1` — the
      cap-truncated alias (35, or 34 after Vercel strips a trailing hyphen the cut left).
      The floor matters: without it, a stray short host like `design.vercel.app` would
      read as "a prefix of the name" and point the verifier at somebody else's project.

    The deployment URL (`<name>-<hash>-<team>`) matches neither: its label is LONGER
    than the name, and a longer string is not a prefix. With the stage-2 cap in place the
    truncated branch is defense-in-depth — no new over-cap name can be minted — but the
    cap is a measured constant, not a contract, so the reader stays tolerant.

    Refuses rather than constructing when the log names no alias: verifying a guessed
    URL is exactly the defect this function replaces.
    """
    exact = truncated = None
    suffix = ".vercel.app"
    # Anchored to lines that START with the Aliased verdict (8a + Step 11 findings): a
    # same-name URL in an error or diagnostic line — including one that merely contains
    # the word, like `Error: project was not aliased to https://…` — is not an alias the
    # deploy granted. Both observed success forms match: `Aliased to https://…` (56.5.0
    # capture) and `▲ Aliased https://…` (live 2026-08-12); both START with the word
    # after at most a marker glyph.
    aliased_lines = "\n".join(
        ln for ln in log.splitlines() if _ALIASED_LINE.match(ln))
    # The truncation Vercel applies is DETERMINISTIC — cut at the cap, strip trailing
    # hyphens — so the acceptable truncated label is THE truncation, never any prefix
    # that merely resembles one (Step 11 finding). Empty when the name is at or under
    # the cap: those names alias intact, so only the exact label can match.
    expected_cut = name[:MAX_ALIAS_LABEL].rstrip("-") if len(name) > MAX_ALIAS_LABEL else ""
    for host in _URL_HOST.findall(aliased_lines):
        h = host.lower()
        label = h[:-len(suffix)]
        if label == name:
            exact = h
        elif expected_cut and label == expected_cut:
            truncated = h
    if exact or truncated:
        return exact or truncated
    raise StageError(stage, f"the deploy log reports no alias for {name!r} — refusing "
                            f"to fetch a URL constructed from the name: for a truncated "
                            f"domain that guess is permanently absent and a perfect "
                            f"deploy reads as not-live (#23).")


# A reference is only shippable if it names one of these. Step 11 found the real hole: with
# `is_file()` as the only content gate, `![x](.env)` published the file's bytes to a public URL —
# measured, `AWS_SECRET=hunter2` and a `credentials.json` both shipped. Containment stops a
# reference LEAVING the document's directory; it says nothing about what sits inside it, and these
# docs are routinely generated rather than hand-written.
#
# An extension allowlist and not an `assets/` subtree rule, deliberately: the one real page in this
# repo that carries assets references `./shots/*.png`, so a subtree rule would refuse the very
# document this issue fixes. `.svg` is included because the engine needs it and an `<img src>` is a
# script-inert context for SVG — but note it is the one entry here that is not inert if a reader
# navigates to the file directly.
_ASSET_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".ico", ".svg",
})


def _asset_target(ref: str) -> str:
    """The file a reference names: query and fragment dropped, percent-decoding undone.

    `d.png?v=2` and `my%20diagram.png` are references to `d.png` and `my diagram.png`. A cache
    buster is not part of the filename, and the deploy directory holds real names.
    """
    return unquote(ref.split("#", 1)[0].split("?", 1)[0])


def stage_assets(page: str, base: Path, workdir: Path) -> list[str]:
    """Copy every relative file the page fetches into the deploy directory (#121).

    Before this, `deploy()` wrote the page into an empty temporary directory and shipped that, so
    `![d](diagram.png)` resolved against a host holding only `index.html` and 404d. The failure
    was SILENT: render, lint and deploy all reported success, and the author saw a working image
    locally because there the file really is beside the markdown.

    Every reference is REFUSED rather than skipped when it cannot be shipped safely, because a
    skipped reference is the original defect — a page published with a hole in it. The rules:

    * resolved against the MARKDOWN SOURCE's directory, which is the base an author writes for;
    * a reference escaping that directory is refused, even via `..` or a symlink, because these
      pages are public and the neighbour directory is somebody's repo (#121 AC3);
    * a symlink is refused outright, the same rule `_check_paths` applies to `--md` and for the
      same reason — this script follows what it is given, and a link can point at a secret;
    * a missing file is refused, since shipping the page anyway is the 404 this issue is about;
    * a root-relative `/x.png` is refused, because the deploy root is not the document's
      directory and guessing which one an author meant would publish a broken page either way;
    * a suffix outside `_ASSET_SUFFIXES` is refused — containment alone would have published
      `.env` (Step 11, measured).

    The file is opened ONCE, with `O_NOFOLLOW`, and copied from that descriptor. Checking a path
    and then reopening it by name is a race: between the two, the final component can become a
    symlink pointing anywhere, and `copyfile` would follow it into a public deploy (Step 11). What
    this does NOT close is a swap of a PARENT directory mid-publish, which would need
    descriptor-relative traversal of every component. That residue is accepted knowingly: it
    requires write access to the document's own directory while the publish runs, and anyone
    holding that can simply edit the markdown instead.
    """
    staged: list[str] = []
    base_root = base.resolve()
    for ref in _LINT.internal_references(page):
        rel = _asset_target(ref)
        if not rel:
            continue
        if rel.startswith("/"):
            raise StageError(5, f"the page references {ref!r}, a ROOT-relative path. Assets ship "
                                f"beside the document, so write it relative to "
                                f"{base.name}/ instead.")
        if Path(rel).suffix.lower() not in _ASSET_SUFFIXES:
            raise StageError(5, f"the page references {ref!r}, which is not a static asset this "
                                f"publisher will ship. Allowed: "
                                f"{', '.join(sorted(_ASSET_SUFFIXES))}. This deploy is PUBLIC, so "
                                f"only declared asset types travel.")
        src = base / rel
        if src.is_symlink():
            raise StageError(5, f"the page references {ref!r}, which is a symlink. These pages "
                                f"are public and this script follows what it is given, so an "
                                f"asset must be a real file in the repo.")
        try:
            resolved = src.resolve()
        except OSError as e:
            raise StageError(5, f"could not resolve the asset {ref!r}: {e}") from e
        if not resolved.is_relative_to(base_root):
            raise StageError(5, f"the page references {ref!r}, which resolves to {resolved} — "
                                f"outside the document's own directory ({base_root}). Refusing: "
                                f"this deploy is public.")
        dest = workdir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(src, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            raise StageError(5, f"the page references {ref!r} but {src} does not exist. It would "
                                f"404 on the published page, so nothing was deployed.") from None
        except OSError as e:
            raise StageError(5, f"could not open the asset {ref!r}: {e}") from e
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise StageError(5, f"the page references {ref!r}, which is not a regular file.")
            with open(fd, "rb", closefd=False) as fh, open(dest, "wb") as out:
                shutil.copyfileobj(fh, out)
        finally:
            os.close(fd)
        staged.append(rel)
    return staged


def deploy(name: str, page: str, workdir: Path, scope: str) -> str:
    """Deploy the LINTED page, bound to `name` (§2a).

    The bytes written here are the string the gate passed — not a re-read of `--out`.
    Re-reading reopened the gate: this workspace runs concurrent sessions, and anything
    that rewrote that file between stage 3 and stage 5 would have shipped unlinted HTML
    to a public URL.

    `vercel link` runs in this same directory, which is what binds the deploy to the
    derived project rather than to whatever was last linked.
    """
    (workdir / "index.html").write_text(page, encoding="utf-8")

    link = _vercel(["link", "--yes", "--project", name], cwd=workdir, scope=scope)
    if link.returncode != 0:
        raise StageError(5, f"`vercel link --project {name}` failed:\n{_log(link)}")

    dep = _vercel(["deploy", "--yes", "--prod"], cwd=workdir, scope=scope)
    log = _log(dep)
    if dep.returncode != 0:
        # Listing a team and DEPLOYING to it are different permissions, and setup can only
        # prove the first — the only way to prove a deploy is permitted is to deploy (#9).
        # So an authorization refusal surfaces here, named, rather than looking like a
        # configuration mistake the user already fixed.
        if _looks_like_denied(log):
            raise StageError(5, f"the Vercel team {scope!r} refused this deploy on "
                                f"permissions. Setup cannot detect this in advance: it can "
                                f"prove you may LIST the team, not that you may deploy to "
                                f"it. Ask an owner of {scope!r} for deploy access.\n{log}")
        raise StageError(5, f"`vercel deploy --prod` failed (rc={dep.returncode}):\n{log}")
    if not deployed_hosts(log, name):
        raise StageError(5, f"the deploy log names no URL belonging to {name} — the "
                            f"deploy did not go where the link said it would, and "
                            f"verifying a guessed alias would paper over it:\n{log}")
    return log


# --- stage 6: verification -----------------------------------------------------------

_TITLE = re.compile(r"<title>(.*?)</title>", re.S | re.I)


def _title_of(body: str) -> str:
    m = _TITLE.search(body)
    return html.unescape(m.group(1)).strip() if m else ""


def _verify_once(url: str, want: bytes, stage: int, timeout: float) -> None:
    """One cache-busted fetch. Raises StageError on anything short of byte identity."""

    busted = f"{url}?cb={random.randrange(10 ** 9)}"
    req = urllib.request.Request(
        busted, headers={"User-Agent": "publish-doc-verifier", "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            status = getattr(resp, "status", None) or resp.getcode()
            final = resp.geturl()
            body = resp.read(MAX_FETCH + 1)
    except urllib.error.HTTPError as e:
        raise StageError(stage, f"{busted} returned HTTP {e.code} — not live") from e
    except OSError as e:
        raise StageError(stage, f"{busted} could not be fetched: {e}") from e

    if status != 200:
        raise StageError(stage, f"{busted} returned HTTP {status} — not live")
    if final != busted:
        raise StageError(stage, f"{busted} redirected to {final}. The URL itself is not "
                                f"serving the page — a login wall answers 200 too.")
    if len(body) > MAX_FETCH:
        raise StageError(stage, f"{busted} returned more than {MAX_FETCH} bytes")
    if body != want:
        got = _title_of(body.decode("utf-8", "replace"))
        title_note = ("its <title> matches, so this is a DIFFERENT version of the same "
                      "page — most likely a stale deployment"
                      if got == _title_of(want.decode("utf-8", "replace"))
                      else f"its <title> is {got!r}")
        raise StageError(stage, f"{busted} returned 200 but not the bytes just published "
                                f"({len(body)} bytes vs {len(want)}); {title_note}")


# A fresh deploy is not instantly live at its alias. `vercel deploy` prints "Aliased" as
# its LAST line, and the pipeline's first real run fetched the URL before that alias was
# serving the new page: the deploy was perfect and stage 6 refused. Measured on that run —
# the same check passed on a manual retry moments later.
VERIFY_ATTEMPTS = 6
VERIFY_DELAY = 5.0


def verify_live(url: str, expected: str, stage: int = 6, timeout: float = 20.0) -> None:
    """The URL must serve EXACTLY the bytes just published (AC5).

    A title match is not enough, and that was the gap two reviewers found independently.
    An updated document normally keeps its title, so a stale prior deployment, or an
    alias still pointing at the old one, answers 200 with the right title and reads as a
    successful publish. `vercel project rename` not moving the `<name>.vercel.app` domain
    is exactly that shape, and it has bitten this account before.

    So the assertion is byte identity against what was deployed. A cache-buster defeats a
    CDN copy; identity defeats everything else, including a page that merely looks right.
    Redirects are refused rather than followed — `urlopen` follows them silently, and the
    documented SSO wall is a 302 to a login page that answers 200.

    The check is retried on a BOUNDED budget, because the alias swap is not instant. It
    is bounded rather than patient because an alias that never updates is precisely the
    failure this stage exists to catch — waiting forever would convert the check back
    into the reassurance it replaced.

    Raises rather than degrading to a plausible-looking value: that degradation is the
    exact behaviour that makes `page_meta()` in build_index.py unusable for this.
    """
    want = expected.encode("utf-8")
    last = None
    for attempt in range(VERIFY_ATTEMPTS):
        if attempt:
            time.sleep(VERIFY_DELAY)
        try:
            _verify_once(url, want, stage, timeout)
            return
        except StageError as e:
            last = e
    waited = int((VERIFY_ATTEMPTS - 1) * VERIFY_DELAY)
    raise StageError(stage, f"{url} still does not serve what was just published, after "
                            f"{VERIFY_ATTEMPTS} attempts over ~{waited}s. "
                            f"Last: {last.message if last else 'unknown'}")


# --- stage 7: the docs index ---------------------------------------------------------

def refresh_index(workdir: Path, workspace_file: Path, scope: str) -> None:
    """Rebuild the index from `vercel project ls`, deploy it, and prove it went live.

    The generated page is a build artifact: it is written into a temp directory and
    never into the repository, whose ignore rules exist precisely to keep the shared
    mutable file — and its lost-row race — from coming back.

    The deploy's return code is not proof. Stage 6 learned that on the document; the
    index earns the same treatment, so a publish that leaves the index stale — which is
    the failure that made the index worth deriving at all — cannot report OK.
    """
    out = workdir / "index.html"
    # Both resolved values are handed to the child EXPLICITLY (#9). Left to look them up
    # again it would re-read the environment and the config file, so a single publish could
    # render its page under one Vercel account and its index under another — with nothing in
    # either output saying so.
    build = subprocess.run(
        [sys.executable, str(INDEX_SCRIPT), "--out", str(out),
         "--workspace-file", str(workspace_file), "--vercel-scope", scope],
        capture_output=True, text=True, check=False)
    if build.returncode != 0:
        raise StageError(7, f"could not rebuild the docs index:\n{_log(build)}")
    try:
        built = out.read_text(encoding="utf-8")
    except OSError as e:
        raise StageError(7, f"the index builder reported success but wrote no page: {e}") from e

    link = _vercel(["link", "--yes", "--project", INDEX_PROJECT], cwd=workdir, scope=scope)
    if link.returncode != 0:
        raise StageError(7, f"could not link {INDEX_PROJECT}:\n{_log(link)}")
    dep = _vercel(["deploy", "--yes", "--prod"], cwd=workdir, scope=scope)
    if dep.returncode != 0:
        raise StageError(7, f"could not deploy {INDEX_PROJECT}:\n{_log(dep)}")
    if not deployed_hosts(_log(dep), INDEX_PROJECT):
        raise StageError(7, f"the index deploy log names no {INDEX_PROJECT} URL:\n{_log(dep)}")

    # Same #23 rule as stage 6: the index's own deploy just reported its alias — use it.
    verify_live(f"https://{aliased_host(_log(dep), INDEX_PROJECT, stage=7)}/",
                built, stage=7)

    # Byte identity proves the page we built is the page that is live. It does NOT prove
    # the page is CURRENT: two publishers interleaving — A builds N rows, B publishes and
    # refreshes to N+1, A deploys last — leaves A's stale N-row index passing its own
    # byte check. The original prose rule was "the page's computed count equals
    # `vercel project ls` minus one", and it is the only thing that catches that race.
    try:
        live_count = len(INDEX.vercel_projects(100, scope=scope))
    except SystemExit as e:
        raise StageError(7, f"could not re-list projects to check the index: {e}") from e
    # An empty listing HERE cannot be an empty account: a deploy just succeeded, so at least
    # that project exists. It used to pass vacuously (`shown < 0` is never true), which meant
    # the one check that catches an interleaved publisher was silently disabled by exactly the
    # untruthful-listing case that made `vercel_projects` stop refusing empties elsewhere.
    if not live_count:
        raise StageError(7, "the account lists no projects at all, moments after a deploy "
                            "succeeded — so the listing cannot be believed, and the index "
                            "cannot be checked against it. Nothing is lost; re-run.")
    shown = built.count('<li><a href="https://')
    if shown < live_count:
        raise StageError(7, f"the index went live with {shown} pages but the account now "
                            f"has {live_count} — another publish landed while this one was "
                            f"building. Re-run to pick it up; nothing is lost.")


# --- the CLI -------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="publish_doc.py",
        description="Render, lint, deploy and verify one design doc. The exit code is "
                    "the verdict; no stage is skippable.")
    ap.add_argument("--md", required=True, help="the committed markdown source")
    ap.add_argument("--project", required=True,
                    help="the rawgentic project this doc belongs to, or the literal "
                         f"{WORKSPACE_BUCKET!r} for a cross-project doc. Validated "
                         "against the workspace file, which is what makes a junk name "
                         "impossible.")
    ap.add_argument("--type", required=True, choices=PURPOSES, dest="purpose",
                    help="the publication PURPOSE. Not a template — see --style.")
    ap.add_argument("--ref", required=True,
                    help="the issue/epic number, or a short lowercase slug")
    ap.add_argument("--title", required=True,
                    help="the page title; the renderer requires one and the lint gate "
                         "refuses a placeholder")
    ap.add_argument("--out", help="rendered HTML path (default: --md with .html)")
    ap.add_argument("--style", choices=tuple(RENDER._TEMPLATES),
                    help="template override. The default comes from --type; these are a "
                         "different vocabulary from the purposes.")
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--doc-id", dest="doc_id",
                    help="stable identity for a uat page (its localStorage namespace)")
    ap.add_argument("--new-project", action="store_true",
                    help="mint a new Vercel project. Reuse is the default; passing this "
                         "when the project already exists is itself an error.")
    ap.add_argument("--dry-run", action="store_true",
                    help="render, name and lint, then stop — no network call at all")
    # #151. `--allow-prose` named ONE check honestly until #130 put a second behind it: "this
    # page carries components, but not the ones its style opens with" is not a statement about
    # prose. The old name is kept as a working ALIAS, not deprecated with a warning — it appears
    # in committed docs, in docs/planning/, and in this repo's own history, so breaking it costs
    # something and buys nothing. Note what is deliberately NOT behind either name:
    # `check_template_classification`, because structural corruption is not a prose decision.
    ap.add_argument("--allow-unsupported-markdown", action="store_true",
                    help="publish even though the source uses syntax this renderer passes "
                         "through as literal characters (strikethrough, task lists, "
                         "footnotes, autolinks...). You are asserting you meant the "
                         "literal text.")
    ap.add_argument("--ack-stale", action="store_true",
                    help="publish even though this revision marks something done while "
                         "other lines still read as open. Use when those lines are "
                         "deliberately historical records of what was true then.")
    ap.add_argument("--no-section-chips", action="store_true",
                    help="suppress the per-section status chip on sectioned styles "
                         "(roadmap/dashboard/analysis). For NARRATIVE pages whose prose "
                         "discusses completion words as subject matter — the scanner "
                         "reads 'who may declare done' as a DONE nobody wrote, and no "
                         "document-side rewording fixes that without lying. Default "
                         "behavior is unchanged.")
    ap.add_argument("--skip-component-checks", "--allow-prose", action="store_true",
                    dest="skip_component_checks",
                    help="skip BOTH component checks: publish a styled page that carries "
                         "no components at all, or that carries some but not the ones its "
                         "style opens with. Does NOT skip the template-classification check. "
                         "Reach for the components first — the refusal names the file that "
                         "lists them, by absolute path. (--allow-prose is an alias.)")
    ap.add_argument("--telemetry", default=None,
                    help="path to a JSON object rendered as the page's Run telemetry section, "
                         "the same one the WF2 design-artifact step injects (#152). Omitted by "
                         "default; malformed input is a loud stage-1 failure, never a silently "
                         "dropped section.")
    ap.add_argument("--workspace-file", default=None,
                    help="the workspace file --project is checked against. Resolved from "
                         "your configuration when omitted; run setup if nothing is "
                         "configured, because stage 2 refuses rather than guessing.")
    ap.add_argument("--vercel-scope", default=None,
                    help="the Vercel team to deploy to. Resolved from your configuration "
                         "when omitted. There is no built-in default: an unpinned deploy "
                         "lands in whichever account `vercel switch` last selected.")
    ap.add_argument("--config", default=None,
                    help="read configuration from this file instead of the default location")
    ap.add_argument("--limit", type=int, default=100,
                    help="`vercel project ls` page size (it paginates at 20 without one)")
    return ap


def default_out(args) -> Path:
    return Path(args.out) if args.out else Path(args.md).with_suffix(".html")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    out_path = default_out(args)
    style = args.style or PURPOSE_STYLE[args.purpose]
    url = ""
    stage = 1   # so an UNEXPECTED failure is still attributed to the stage it happened in

    try:
        # Resolved ONCE, before stage 1, and threaded through every stage that needs it —
        # including the stage-7 CHILD PROCESS (#9). A helper that resolved for itself could
        # answer for a different Vercel account than the page it is indexing.
        config_path = CONFIG.config_file(cli_value=args.config)
        workspace = CONFIG.workspace_file(cli_value=args.workspace_file,
                                          config_path=config_path)

        # #14: the page wears its project's colour. Resolved through the shared
        # module the index also calls, so the two cannot drift. An unconfigured workspace is
        # a real state here and degrades to the seed-or-hash colour rather than refusing:
        # rendering must keep working before anything is set up.
        pack = VDL.pack_for(args.project, workspace)
        page = render(Path(args.md), out_path, title=args.title, subtitle=args.subtitle,
                      style=style, doc_id=args.doc_id, vdl=pack,
                      telemetry=load_telemetry(Path(args.telemetry) if args.telemetry else None),
                      section_chips=not args.no_section_chips)
        print(f"publish_doc: 1/7 rendered {out_path} ({style} template, "
              f"{pack['origin']} palette {pack['accent']['light']})")

        stage = 2
        # The first place a stranger is stopped, so it must say what to run. `require_*`
        # raises `ConfigError`, which the handler below turns into a one-line stage failure
        # rather than a traceback.
        workspace = CONFIG.require_workspace_file(cli_value=args.workspace_file,
                                                  config_path=config_path)
        name = derive_name(args.project, args.purpose, args.ref, workspace)
        print(f"publish_doc: 2/7 name {name}")

        stage = 3
        for note in source_gate(Path(args.md),
                                allow_unsupported=args.allow_unsupported_markdown,
                                ack_stale=args.ack_stale):
            print(f"publish_doc: {note}")
        gate(page, skip_component_checks=args.skip_component_checks)
        # Said out loud, every run. A skipped check that reports nothing is how a page with
        # no components reaches a public URL looking like it passed.
        print("publish_doc: 3/7 lint gate passed"
              + (" (--skip-component-checks: BOTH component checks were SKIPPED)"
                 if args.skip_component_checks else ""))

        if args.dry_run:
            print("publish_doc: --dry-run, stopping before the first network call")
            return 0

        stage = 4
        # Deferred to here on purpose: rendering, naming and linting all work without a
        # Vercel account, and `--dry-run` returns above. A team is required only once a
        # network call is about to target one.
        scope = CONFIG.require_vercel_scope(cli_value=args.vercel_scope,
                                            config_path=config_path)
        reused = resolve_project(name, new_project=args.new_project, scope=scope)
        print(f"publish_doc: 4/7 {'reusing' if reused else 'creating'} {name}")

        stage = 5
        with tempfile.TemporaryDirectory(prefix="publish-doc-") as tmp:
            # #121: assets go in BEFORE the deploy, because a deploy ships the directory. Any
            # reference that cannot ship safely raises here, so nothing is published — a page
            # with a hole in it is the defect, not the fallback.
            assets = stage_assets(page, Path(args.md).parent, Path(tmp))
            if assets:
                print(f"publish_doc: 5/7 packaging {len(assets)} asset(s): "
                      f"{', '.join(assets)}")
            log = deploy(name, page, Path(tmp), scope)
        print(f"publish_doc: 5/7 deployed\n{log.strip()}")

        stage = 6
        # The domain the deploy REPORTED, never one constructed from the name (#23).
        url = f"https://{aliased_host(log, name)}/"
        verify_live(url, page)
        print(f"publish_doc: 6/7 verified live — {url} serves exactly what was linted")

        stage = 7
        with tempfile.TemporaryDirectory(prefix="publish-index-") as tmp:
            refresh_index(Path(tmp), workspace, scope)
        print(f"publish_doc: 7/7 index refreshed and verified — "
              f"https://{INDEX_PROJECT}.vercel.app")
    except CONFIG.ConfigError as e:
        # A configuration refusal is a stage failure with a legible sentence, never a
        # traceback (#9 AC5). The stage counter says WHERE it stopped, so the exit code
        # keeps meaning what it always meant.
        print(f"publish_doc: FAILED at stage {stage}: {e}", file=sys.stderr)
        return EXIT_BASE + stage
    except StageError as e:
        print(f"publish_doc: FAILED at stage {e.stage}: {e.message}", file=sys.stderr)
        return EXIT_BASE + e.stage
    except Exception:
        # A missing `vercel` binary raises FileNotFoundError, not SystemExit. Without
        # this the process exits 1 with a traceback and no stage — the one thing the
        # exit-code contract promises never to do. The traceback is still printed,
        # because an unexpected error is a bug here, not a verdict.
        traceback.print_exc()
        print(f"publish_doc: FAILED at stage {stage}: unexpected error, traceback above",
              file=sys.stderr)
        return EXIT_BASE + stage

    print(f"publish_doc: OK — {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
