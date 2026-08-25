#!/usr/bin/env python3
"""One command from a committed markdown doc to a verified-live page (#12, wave 5).

Design: `docs/planning/2026-08-01-12-publish-pipeline.md`, and for the harness migration
`docs/planning/2026-08-24-36-publish-to-harness.md` (revision 4).

Every step here already existed as prose in `SKILL.md`, and the prose had a measured
failure rate: junk names like `deploy-713`, three duplicate deploys of one page, no index.
Prose is re-performed by a model on every publish; a command is not. So the exit code is
the verdict.

    python3 publish_doc.py --md docs/planning/x.md --project herdr-dashboard \\
                           --type design --ref 81 --title "#81 The Design"

**PUBLISH-BEFORE-MERGE is the thing to understand first (#36).** The doc harness never
receives rendered bytes. It takes a manifest naming a repo, a full 40-hex commit and, per
asset, a repo path and a blob id — then fetches every blob FROM GITHUB itself. So the page
must be committed and pushed BEFORE it is published, and the publish pins that commit. The
working order is: render with ``--dry-run``, commit the ``.md`` and the ``.html`` together,
push, then publish.

One consequence is a gift: because the harness serves the COMMITTED bytes, stage 6's byte
equality also proves the render matches the commit. "Rendered but forgot to commit" becomes
a caught failure rather than a stale page nobody notices.

Six stages, each able to refuse (exit ``EXIT_BASE + stage``):

    1 render   2 name   3 LINT   4 provenance   5 publish   6 verify

Two exits are NOT stage failures, and they sit above the 11-17 block so a caller can tell
them apart: **25** means ``DOC_HARNESS_CONTROL_URL`` is unset and nothing was published,
**26** means the page published and origin-verified while the edge half SKIPPED. 26 is not
a pass.

**The gate runs BEFORE the publish, and that is a correction to the issue's own order.**
The issue lists deploy -> lint -> verify, but AC4 requires a lint failure to leave
"nothing deployed". Those cannot both hold: linting afterwards means a page with an
external request or a sub-AA token pair is already public by the time it is caught.

Four things this file is careful about, each because a draft got it wrong:

* **A name is validated by COMPONENT, never by shape.** `--project deploy --type design
  --ref 713` yields `deploy-design-713`, which matches the convention's pattern
  perfectly and is exactly the junk the convention exists to stop.
* **Provenance is bound to the repository the MANIFEST names**, never to the process's
  cwd. `--md` and `--out` are arbitrary paths used across a whole workspace, so resolving
  from cwd pins the wrong repo — and the dangerous failure is not a 422, it is the path
  existing in the wrong repo, where the harness serves a DIFFERENT file under the right
  name with every later check still passing.
* **No credential reaches a destination that was not validated first**, and no credential
  is ever rendered into an error message, a log line, or a redirect that gets followed.
  Redaction alone protects only the log; the destination check is what protects the wire.
* **The verifier is written here, not borrowed.** `page_meta()` in `build_index.py`
  sends no cache-buster, exposes no status code, and collapses every failure into
  `(name, None)` — so a dead page and a live one are indistinguishable.

Version control stays OUT of this script in the sense that matters (AC6): it READS git —
the repository, the committed blob ids, whether HEAD is pushed — because the harness
fetches from GitHub and none of that is answerable otherwise. It never COMMITS, stages,
pushes, branches or opens a pull request, and a test enforces exactly that split.
"""
from __future__ import annotations

import argparse
import hashlib
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

# Finding N7. The manifest carries no content_type — the harness DERIVES it — so a second
# copy of the extension mapping here would drift, and drift produces both false failures
# and false passes. This is the harness's own function, not a reimplementation.
#
# LAZY, per the Step 8a inline pass. At module scope a missing `harness/` would make the
# whole script unimportable, so the process would die before it could print a sentence —
# and RENDERING, the one thing that needs no harness at all, would die with it. Deferring
# the import to the point of use means the coupling fails loudly where it matters and
# nowhere else.


def content_type_for(url_path: str) -> str:
    """The harness's own derivation, resolved on first use."""
    if str(HERE.parent) not in sys.path:
        sys.path.insert(0, str(HERE.parent))
    try:
        from harness.manifest import content_type_for as _impl
    except ImportError as e:                                  # pragma: no cover - see below
        raise StageError(
            6, "cannot import the harness's content-type derivation "
               f"(harness/manifest.py): {e}. Verification compares each asset against the "
               "type the HARNESS derives, so a second copy here would drift silently.") from e
    return _impl(url_path)
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

WORKSPACE_BUCKET = "workspace"     # the one literal that is not a rawgentic project
INDEX_PROJECT = "docs-index"
MAX_NAME = 100

# #36 AC3: 35 -> 63. The old 35-character cap came from the retired hosting vendor, which
# truncated over-cap names so a page deployed fine and then 404d at its conventional URL
# forever (#23). The harness truncates nothing. Its limit is the DNS label limit itself,
# enforced by `harness/routing.py:is_valid_label`.
#
# So the refusal moves out to 63, where it is still a refusal because the harness would
# refuse too, and 36-63 becomes a WARNING: publishable, just long.
MAX_ALIAS_LABEL = 63

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
    # Finding S7. `rev-parse --abbrev-ref HEAD` yields the literal string "HEAD" when
    # detached, and passing it through compares against `<remote>/HEAD` — a symbolic ref
    # that may well contain the commit, so provenance PASSED where the design says refuse.
    if not branch or branch == "HEAD":
        raise StageError(
            4, "HEAD is detached, so there is no branch to check against the remote. "
               "Check out the branch you intend to publish from.")
    if fetch:
        # Finding A7: WITHOUT --prune a tracking ref left behind by a deleted branch or a
        # changed remote URL still contains HEAD, so this passes while GitHub no longer
        # exposes that commit — and the harness then cannot fetch it.
        f = _git(["fetch", "--prune", remote], root, runner=runner)
        if f.returncode != 0:
            raise StageError(4, f"git fetch --prune {remote} failed, so reachability cannot be "
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


# --- #36 stage 5: publish through the control API ---------------------------------------
#
# Two calls, both bearing `Authorization: Bearer $DOC_HARNESS_PUBLISH_TOKEN`, both under
# `/v1` (`harness/control.py:34` — an unprefixed path is a 404 at `harness/control.py:83`,
# which is what revision 2 of the design would have shipped).

# Finding N8. `urllib.request.urlopen` takes ONE per-socket-operation deadline, not
# separate connect and read deadlines, and this repository has no `requests` dependency —
# the gate is deliberately dependency-free. So the contract is what urllib can enforce,
# stated honestly rather than tabulated as something it cannot.
# Step 8a finding R0. A per-socket deadline does not bound an unqualified `read()`: a
# server that trickles bytes keeps the call alive for ever, and a huge response exhausts
# memory. Every response this tool reads is capped.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_READ_CHUNK = 64 * 1024
# The WHOLE-read budget. Separate from the per-socket deadline, because that one is reset
# by every byte a hostile peer sends.
RESPONSE_DEADLINE = 60.0

CONTROL_READ_TIMEOUT = 20      # a registry read
PUBLISH_TIMEOUT = 120          # the harness fetches every blob from GitHub inside this call

# The characters `harness/routing.py:canonical_url_path` refuses unencoded. Catching them
# here turns a 422 about an encoding into one sentence naming the file.
_NEEDS_ENCODING = set(" +(),&'=@!$*")


_HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_REPO_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


def validate_manifest(manifest: dict) -> None:
    """Refuse locally anything `harness/manifest.py` would refuse with a 422.

    **`entry_path` is the field the design forgot.** The manifest carries a top-level
    `entry_path` that must name a declared asset (`harness/manifest.py:192-199`), an asset
    `url_path` of `/` is refused outright (`harness/manifest.py:113`), and serving maps a
    request for `/` onto `entry_path` (`harness/serving.py:80`). None of that appears in the
    #36 design, and none of the three review passes caught it — so the first manifest this
    tool built would have been a 422 about a field nobody had written down. Every rule below
    mirrors one in the harness, so the refusal arrives here as a sentence instead.
    """
    def bad(msg):
        raise StageError(5, f"manifest: {msg}")

    name = manifest.get("name")
    if not isinstance(name, str) or not re.match(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", name):
        bad(f"name must be one DNS label, lowercase, 1-63 characters. Got {name!r}")
    repo = manifest.get("repo")
    if (not isinstance(repo, str) or not _REPO_RE.match(repo)
            or any(part in (".", "..") for part in repo.split("/"))):
        bad(f"repo must be 'owner/name' with no '.' or '..' segment. Got {repo!r}")
    sha = manifest.get("commit_sha")
    if not isinstance(sha, str) or not _HEX40_RE.match(sha.lower()):
        bad(f"commit_sha must be a full 40-hex commit id, not a ref. Got {sha!r}")

    assets = manifest.get("assets")
    if not isinstance(assets, list) or not assets:
        bad("assets must be a non-empty list")

    seen = set()
    for i, a in enumerate(assets):
        if not isinstance(a, dict):
            bad(f"assets[{i}] must be an object")
        url_path = a.get("url_path")
        if not isinstance(url_path, str) or not url_path.startswith("/"):
            bad(f"assets[{i}].url_path must be an absolute path. Got {url_path!r}")
        if url_path == "/":
            bad(f"assets[{i}].url_path must name a file, not '/'. The entry page is declared "
                "by its real path and reached through entry_path.")
        if url_path in seen:
            bad(f"duplicate url_path {url_path!r}")
        seen.add(url_path)
        repo_path = a.get("repo_path")
        if (not isinstance(repo_path, str) or repo_path.startswith("/")
                or ".." in repo_path.split("/")):
            bad(f"assets[{i}].repo_path must be relative with no '..'. Got {repo_path!r}")
        if not isinstance(a.get("blob_id"), str) or not _HEX40_RE.match(a["blob_id"].lower()):
            bad(f"assets[{i}].blob_id must be 40 hex characters")
        if not isinstance(a.get("sha256"), str) or not _HEX64_RE.match(a["sha256"].lower()):
            bad(f"assets[{i}].sha256 must be 64 hex characters")
        if not isinstance(a.get("size"), int) or isinstance(a.get("size"), bool):
            bad(f"assets[{i}].size must be an integer")

    entry_path = manifest.get("entry_path")
    if not isinstance(entry_path, str) or not entry_path:
        bad("entry_path is required: it is what a request for '/' resolves to")
    if entry_path not in seen:
        bad(f"entry_path {entry_path!r} names no declared asset, so '/' would 404 on a "
            "deployment that otherwise activated cleanly")


def build_manifest(*, root: Path, page_path: Path, staged: list[str], asset_base: Path,
                   name: str, repo: str, commit_sha: str, md_path: Path | None = None,
                   rendered: str | None = None) -> dict:
    """Describe what is COMMITTED, never what is in hand.

    The harness fetches every blob from GitHub by `blob_id`, which is git's own object id
    (`harness/control.py:git_blob_id`) — a sha256 in its place would look up nothing. The
    per-asset `sha256` is a SECOND, independent check the harness makes on the bytes it
    fetched, so both are sent.

    `content_type` is deliberately absent: the harness derives it from the extension and a
    sent one is a 422.
    """
    root = root.resolve()

    def entry_for(path: Path, url_path: str) -> dict:
        # Finding S5. `stage_assets` refuses a symlink, and this REOPENS the original path
        # afterwards — so a swap in between would be followed here, publishing unrelated
        # committed bytes under an allowed asset URL. The same rule, applied at the second
        # place the path is touched.
        if path.is_symlink():
            raise StageError(
                4, f"{path} is a symlink. An asset must be a real file: this runs after "
                   "staging already checked, and following a link swapped in between is "
                   "how other committed bytes reach a public URL.")

        path = path.resolve()
        if not path.is_relative_to(root):
            raise StageError(
                4, f"{path} is outside the repository at {root}, so the harness could "
                   "never fetch it. Everything published must be committed here.")
        raw = path.read_bytes()
        blob = _git(["hash-object", str(path)], root)
        if blob.returncode != 0:
            raise StageError(4, f"git could not hash {path}: {blob.stderr.strip()}")
        blob_id = blob.stdout.strip()
        repo_path = str(path.relative_to(root))
        assert_blob_committed(root, repo_path, blob_id)
        return {"url_path": url_path, "repo_path": repo_path, "blob_id": blob_id,
                "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    # The entry page is served at a real path and REACHED through `entry_path`; an asset
    # `url_path` of `/` is refused outright (`harness/manifest.py:113`).
    # Finding R5. Every surface here says the `.md` and the `.html` ship together, and
    # nothing checked the markdown — so committing only the HTML published happily, with
    # the pinned commit carrying a source that never produced that page.
    if md_path is not None:
        md_path = md_path.resolve()
        if not md_path.is_relative_to(root):
            raise StageError(4, f"{md_path} is outside the repository at {root}.")
        blob = _git(["hash-object", str(md_path)], root)
        if blob.returncode != 0:
            raise StageError(4, f"git could not hash {md_path}: {blob.stderr.strip()}")
        assert_blob_committed(root, str(md_path.relative_to(root)), blob.stdout.strip())

    # Partial mitigation for finding R3. The full remedy is to thread captured bytes from
    # the render all the way through, which is a larger refactor than this child should
    # carry. What is closed here is the exact danger named: between the lint gate and this
    # point, the output path could be replaced by a DIFFERENT committed page, which would
    # then be hashed, published and verified against — every check passing on a file the
    # gate never saw. Comparing against the bytes the renderer returned catches that.
    if rendered is not None and page_path.read_bytes() != rendered.encode("utf-8"):
        raise StageError(
            4, f"{page_path} changed after it was rendered and linted. Refusing: the "
               "manifest would pin a page this run never checked.")

    # The url_path must be CANONICALLY PERCENT-ENCODED or the publish is a 422. This is
    # the #34 boundary learning, and it is easy to lose: `stage_assets` resolves a
    # percent-encoded reference back to the real filename, so `rel` here carries the
    # DECODED name — a literal space, or any of `+ ( ) , & ' = @ ! $ *`. Prefixing "/" and
    # sending that is exactly the 422 the learning warns about.
    #
    # `repo_path` keeps the real decoded name, because that is what git holds.
    assets = [entry_for(page_path, "/index.html")]
    assets += [entry_for(asset_base / rel, "/" + urllib.parse.quote(rel, safe="/"))
               for rel in staged]
    return {"name": name, "repo": repo, "commit_sha": commit_sha,
            "entry_path": "/index.html", "assets": assets}


def _control_request(base: str, path: str, token: str, *, method: str, body: bytes | None,
                     env=None):
    """Finding A4, and the sharpest of the Step-11 wave.

    The destination check used to live in `main()` while THIS function — the one that
    actually attaches `Authorization: Bearer` — validated nothing. Any caller that did not
    reproduce main()'s separate step could send the token anywhere, and the proof was
    already in the test suite: it called `read_active` and `publish` directly, with no
    guard, and they worked. A guard a caller must remember is not a guard.
    """
    assert_bearer_destination(base, env=env, stage=5)
    req = urllib.request.Request(f"{base}{path}", data=body, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    # The harness routes on the HOST header, so a loopback or bridge address needs the
    # control host named explicitly — `Host: 127.0.0.1:18081` is not inside the zone and
    # the harness rightly refuses it. Measured on the #36 live run, which needed a
    # hand-written client for exactly this reason. The TLS host is left alone: its URL
    # already carries the right name, and overriding would mask a mismatch.
    if urllib.parse.urlsplit(base).scheme == "http":
        req.add_header("Host", f"{CONTROL_HOST}")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    return req


def _read_bounded(resp, *, stage: int, deadline_s: float = RESPONSE_DEADLINE) -> bytes:
    """At most `MAX_RESPONSE_BYTES`, and at most `deadline_s` of wall clock.

    Findings P1 and A2, raised independently by both Step-11 passes. A size cap is NOT a
    time bound: a peer sending one byte inside each socket timeout keeps a single blocking
    `read()` alive for ever, and the earlier version did exactly one such read. The design
    promised a stage wall-clock budget; this is it, enforced between chunks.
    """
    end = time.monotonic() + deadline_s
    chunks: list[bytes] = []
    total = 0
    while True:
        if time.monotonic() > end:
            raise StageError(
                stage, f"the response did not finish within its {deadline_s:g}s budget. A "
                       "peer that trickles bytes can hold a socket timeout open for ever, "
                       "so the whole read is bounded rather than each operation.")
        chunk = resp.read(_READ_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise StageError(
                stage, f"the response exceeded {MAX_RESPONSE_BYTES} bytes and was refused "
                       "rather than truncated. A truncated body would parse as something "
                       "other than what was sent.")
        chunks.append(chunk)
    return b"".join(chunks)


def _control_call(req, timeout: int, *, opener=None):
    """Returns (status, parsed-json-or-None).

    **The default opener does NOT follow redirects** (Step 8a finding R1). Both control
    calls carry `Authorization: Bearer <publish token>`, and `urlopen` follows a 302
    silently — so a redirect from an allowlisted control origin would have handed the
    bearer to whatever host the redirect named, straight past `assert_bearer_destination`.
    `NO_REDIRECTS` already existed for exactly this reason and was not used here.
    """
    call = opener if opener is not None else NO_REDIRECTS.open
    with call(req, timeout=timeout) as resp:
        raw = _read_bounded(resp, stage=5)
    try:
        return getattr(resp, "status", 200), json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return getattr(resp, "status", 200), None


def read_active(base: str, name: str, token: str, *, opener=None, env=None) -> int | None:
    """The active deployment id, or None when nothing is published yet.

    `harness/control.py:_read_back` answers **200 with a null id**, never 404 — a first
    publish reads null and passes it straight back as `expected_active`. Pinned at
    `tests/harness/test_control.py:184`.

    A present-but-unparseable id refuses HERE, before anything is published. Finding M12:
    a client that always sent null, or that misparsed a non-null read-back, would pass
    every first-publish and race test while every republish returned 409 for ever.
    """
    req = _control_request(base, f"/v1/deployments/{name}", token, method="GET",
                           body=None, env=env)
    try:
        status, payload = _control_call(req, CONTROL_READ_TIMEOUT, opener=opener)
    except urllib.error.HTTPError as e:
        if 300 <= e.code < 400:
            raise StageError(
                5, f"the control API answered {e.code}, a redirect. It is NOT followed: "
                   "the request carries the publish bearer, and following a redirect "
                   "would send that token to a host the allowlist never approved.") from e
        raise StageError(5, f"reading back {name} failed with HTTP {e.code}. The publish "
                             "was not attempted.") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise StageError(5, f"could not reach the control API at {base}: {e}. "
                             "DOC_HARNESS_CONTROL_URL must name a reachable harness.") from e
    # Finding S2: the STATUS is part of the contract, not decoration. Accepting any 2xx
    # lets a wrong-version or no-op endpoint answer for one that does not exist.
    if status != 200:
        raise StageError(5, f"the read-back for {name} answered HTTP {status}, and the "
                            "contract is exactly 200.")
    if not isinstance(payload, dict):
        raise StageError(5, f"the read-back for {name} was not a JSON object.")
    # Finding R6: a MISSING field is indeterminate, not "nothing is published". Treating
    # the two alike let a truncated or wrong-version response publish with
    # `expected_active: null`, which is a compare-and-swap against a state never read.
    if "active_deployment_id" not in payload:
        raise StageError(
            5, f"the read-back for {name} carries no active_deployment_id field at all, so "
               "the current state is unknown. Refusing rather than publishing as if "
               "nothing were live.")
    active = payload.get("active_deployment_id")
    if active is None:
        return None
    if not isinstance(active, int) or isinstance(active, bool):
        raise StageError(
            5, f"the read-back for {name} carries a non-integer active_deployment_id "
               f"({active!r}). Refusing to publish against a value that cannot be compared "
               "and swapped.")
    return active


def publish(base: str, manifest: dict, expected_active: int | None, token: str,
            *, opener=None, env=None) -> int:
    """POST the manifest and return the NEW deployment id from the 201.

    `expected_active` is required and is sent EXPLICITLY, including as null: the parser
    refuses an omitted field with its own message that omission and null are different
    things.

    The success contract is 201 with an integer `deployment_id` (`harness/control.py:217`).
    A 201 whose body lacks one is a failure, not a pass — stage 6 would otherwise verify
    against the wrong deployment.
    """
    validate_manifest(manifest)
    for asset in manifest.get("assets", []):
        bad = _NEEDS_ENCODING & set(asset.get("url_path", ""))
        if bad:
            raise StageError(
                5, f"url_path {asset['url_path']!r} contains {''.join(sorted(bad))!r}, which "
                   "harness/routing.py:canonical_url_path refuses unencoded (422). "
                   "Percent-encode it before publishing.")
        if "content_type" in asset:
            raise StageError(5, "assets must not carry content_type: the harness derives it "
                                "from the extension, and sending one is a 422.")

    body = json.dumps({**manifest, "expected_active": expected_active}).encode("utf-8")
    req = _control_request(base, "/v1/deployments", token, method="POST", body=body,
                           env=env)
    try:
        status, payload = _control_call(req, PUBLISH_TIMEOUT, opener=opener)
    except urllib.error.HTTPError as e:
        raise _publish_http_error(e) from e
    except (TimeoutError, OSError) as e:
        # Deliberately NOT retried. The POST is not idempotent, and a retry after an
        # ambiguous timeout races `expected_active` against a deployment its own first
        # attempt may have created — which then 409s and looks like someone else won.
        raise StageError(
            5, f"the publish timed out after {PUBLISH_TIMEOUT}s ({e}). It is NOT retried "
               "automatically, because it is not idempotent and it may already have "
               f"succeeded. Read back GET {base}/v1/deployments/{manifest.get('name')} to "
               "see the real state before trying again.") from e

    # Finding S2. 201 is the sole success status (harness/control.py:217). A 200 carrying
    # an EXISTING deployment_id would otherwise read as success, and if the committed bytes
    # happened to be unchanged, verification would pass too — reporting a publish that
    # never happened.
    if status != 201:
        raise StageError(5, f"the publish answered HTTP {status}, and the success contract "
                            "is exactly 201. Refusing to treat it as published.")
    deployment_id = (payload or {}).get("deployment_id")
    if not isinstance(deployment_id, int) or isinstance(deployment_id, bool):
        raise StageError(
            5, "the harness answered 201 without an integer deployment_id, so there is "
               "nothing to verify against. Treating this as a failure, not a pass.")
    return deployment_id


def _publish_http_error(e: urllib.error.HTTPError) -> StageError:
    """Finding R4: the response body is NEVER rendered verbatim.

    A server can reflect the `Authorization` header back inside its own JSON error, and
    interpolating that into stderr writes the bearer into terminal and CI logs — which
    contradicts the guarantee this design states outright. Only fields this function
    itself selects, and only after a type check, reach a message.
    """
    try:
        raw = json.loads(e.read(MAX_RESPONSE_BYTES).decode("utf-8"))
        payload = raw if isinstance(raw, dict) else {}
    except Exception:                                    # noqa: BLE001 - body is advisory
        payload = {}
    if 300 <= e.code < 400:
        return StageError(
            5, f"the control API answered {e.code}, a redirect. It is NOT followed: the "
               "request carries the publish bearer.")
    if e.code == 409:
        # Findings P4 and A5, raised independently by both passes. The wholesale body echo
        # was fixed and THIS field was left — and `active_deployment_id` is a field a
        # hostile server fills in, so a reflected credential landed in stderr.
        current = payload.get("active_deployment_id")
        where = (f"it is now {current}" if isinstance(current, int)
                 and not isinstance(current, bool)
                 else "the server did not report a valid current id")
        return StageError(
            5, "another publisher won the race: the active deployment moved while this "
               f"publish was in flight ({where}). Nothing was published. Re-run to publish "
               "on top of the new state.")
    if e.code == 502:
        # Findings A5 and S4: this is almost never transport. Stage 4a proved the
        # PUBLISHER can see the repo; the harness fetches with DOC_HARNESS_GITHUB_TOKEN,
        # a different identity that may not cover it at all.
        return StageError(
            5, "the harness could not fetch the blobs from GitHub. This is a GRANT "
               "problem, not a network one: stage 4a proved YOUR credentials can see the "
               "repository, but the harness fetches with DOC_HARNESS_GITHUB_TOKEN, which "
               "is a different identity. Check that token's access to this repository.")
    # The status only. No body, no `reason` — both are attacker-controlled strings.
    return StageError(5, f"the publish failed with HTTP {e.code}. The response body is "
                         "deliberately not shown: it is attacker-controlled and could "
                         "carry a reflected credential.")


# --- #36 stage 6: verify, and bind every credential to its destination -----------------
#
# Findings M7 and N4, M7 found independently by both review passes. Redaction protects the
# LOG. It does nothing about the wire or about the wrong server, and transport syntax does
# not establish server identity: "https" alone permits ANY https host.

# Finding N11. The trust anchor is PINNED HERE, in committed source, and deliberately not
# read from `DOC_HARNESS_ZONE`. Validating the destination against a value drawn from the
# same mutable environment as the destination is not validation: whoever can set
# `DOC_HARNESS_PUBLIC_BASE` can set the zone to match it and pass.
PINNED_ZONE = "3dstories.ca"

# The committed allowlist for the PUBLISH BEARER. Loopback and the docker bridge ranges are
# the operations path measured on the harness host; the one public origin is the control
# hostname the tunnel will answer for. Everything else refuses.
# Step 8a finding R2: this used to admit all of 10/8 and 192.168/16 as well, which is
# every corporate LAN — an attacker-influenced control URL could send the bearer to any
# reachable service on one. Only loopback and the docker BRIDGE space (172.16/12) have any
# reason to host the harness endpoint the operations step uses, so only those remain.
_BEARER_HOSTS_PLAINTEXT = re.compile(
    r"^(?:localhost|127\.\d+\.\d+\.\d+|::1|"
    r"172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)$")
CONTROL_HOST = f"docs-control.{PINNED_ZONE}"
_BEARER_HOSTS_TLS = frozenset({CONTROL_HOST})

# `urlopen` follows a 302 silently, which would send the Access service tokens to whatever
# login host the redirect names. An opener with no redirect handler cannot.
NO_REDIRECTS = urllib.request.build_opener(_NoRedirect := type(
    "_NoRedirect", (urllib.request.HTTPRedirectHandler,),
    {"redirect_request": lambda self, *a, **kw: None})())


def assert_credentials(env, *, edge: bool) -> tuple[str, str] | None:
    """Refuse locally before a request is built. Finding N6.

    A missing or half-present credential otherwise fails indirectly as a 401 or an Access
    login redirect, both of which read as a server problem rather than a local one.
    **No message here ever renders a value**, only a variable name.
    """
    if not (env.get("DOC_HARNESS_PUBLISH_TOKEN") or "").strip():
        # Finding R7: STAGE 5, not 6. The exit code is the verdict, so reporting 16 for a
        # publish that never happened says stage 6 tried and failed. It did not run.
        raise StageError(5, "DOC_HARNESS_PUBLISH_TOKEN is not set. The control API needs a "
                            "bearer, and refusing here is clearer than a 401 later.")
    if not edge:
        return None
    cid = (env.get("CF_ACCESS_CLIENT_ID") or "").strip()
    secret = (env.get("CF_ACCESS_CLIENT_SECRET") or "").strip()
    if bool(cid) != bool(secret):
        missing = "CF_ACCESS_CLIENT_SECRET" if cid else "CF_ACCESS_CLIENT_ID"
        raise StageError(
            6, f"the Cloudflare Access service token is a PAIR and {missing} is not set. "
               "One half alone produces a login redirect that looks like a server fault.")
    if not cid:
        raise StageError(
            6, "the edge half needs CF_ACCESS_CLIENT_ID and CF_ACCESS_CLIENT_SECRET, and "
               "neither is set. Unset DOC_HARNESS_PUBLIC_BASE to skip the edge half instead.")
    return cid, secret


_LOOPBACK = re.compile(r"^(?:localhost|127\.\d+\.\d+\.\d+|::1)$")


def assert_bearer_destination(base: str, env=None, *, stage: int = 6) -> None:
    """The publish bearer goes only where the committed allowlist permits (finding N4),
    and a NON-LOOPBACK plaintext destination is a deliberate act (finding S3).

    172.16/12 is a whole range, not the one container that was inspected, so any reachable
    service in it could capture the token. Attesting the exact container would need docker
    access this publisher does not have. So the honest narrower control is consent: the
    bridge address the operations step uses requires
    `DOC_HARNESS_ALLOW_BRIDGE_PLAINTEXT`, and setting it is a decision somebody makes
    rather than a default they inherit.
    """
    env = os.environ if env is None else env
    parsed = urllib.parse.urlsplit(base)
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "https" and host in _BEARER_HOSTS_TLS:
        return
    if parsed.scheme == "http" and _LOOPBACK.match(host):
        return
    if parsed.scheme == "http" and _BEARER_HOSTS_PLAINTEXT.match(host):
        # Finding P3: a flag that authorizes a whole /12 is consent, not validation. It
        # cannot become validation without attesting the container, which needs docker
        # access this publisher does not have — but it CAN be narrowed from "any bridge
        # address" to "exactly the one you named". The variable now carries the
        # `host:port` it grants, and nothing else is covered by it.
        granted = (env.get("DOC_HARNESS_ALLOW_BRIDGE_PLAINTEXT") or "").strip()
        if granted and granted == parsed.netloc.lower():
            return
        raise StageError(
            stage, f"refusing to send the publish bearer over plaintext to {parsed.netloc}. "
                   "That is the docker bridge range, and a range is not the one container "
                   "you inspected. To allow exactly this endpoint for the operations step, "
                   f"set DOC_HARNESS_ALLOW_BRIDGE_PLAINTEXT={parsed.netloc} — a bare truthy "
                   "value grants nothing.")
    raise StageError(
        stage, f"refusing to send the publish bearer to {base!r}: it is not on the allowlist in "
           "publish_doc.py. Permitted are the loopback and private-range addresses the "
           f"operations path uses over http, and https://docs-control.{PINNED_ZONE}. "
           "An https URL is NOT sufficient on its own — that would send the token to any "
           "host the environment happens to name.")


def assert_access_destination(url: str, name: str) -> None:
    """The Access service tokens go only to this deployment's own host, over TLS."""
    parsed = urllib.parse.urlsplit(url)
    expected = f"{name}.{PINNED_ZONE}"
    if parsed.scheme != "https":
        raise StageError(6, f"refusing to send Cloudflare Access credentials over "
                            f"{parsed.scheme!r}: they would cross the network in the clear.")
    if (parsed.hostname or "").lower() != expected:
        raise StageError(
            6, f"refusing to send Cloudflare Access credentials to {parsed.hostname!r}; "
               f"this deployment's host is {expected}.")


def build_verify_request(base: str, url_path: str, deployment_id: int, *, name: str,
                         access: tuple[str, str] | None,
                         env=None) -> urllib.request.Request:
    """One verification request. Finding M3 — revision 2 defined no request at all, so
    plausible implementations verified the ACTIVE deployment rather than the pinned one,
    hit the control route, or asked for the wrong asset.

    `deployment_id` is the integer from the stage-5 **201**, never the id read back before
    it: that one is the PREVIOUS deployment.
    """
    url = f"{base}{url_path}?__deployment={deployment_id}"
    req = urllib.request.Request(url, method="GET")
    if access is None:
        # The origin half talks to a bridge address, and serving routes on the Host header
        # (`harness/app.py:49` -> `harness/routing.py:66`), so the address's own host
        # resolves to no deployment at all. The header is mandatory, not cosmetic.
        assert_bearer_destination(base, env=env)
        req.add_header("Host", f"{name}.{PINNED_ZONE}")
    else:
        assert_access_destination(url, name)
        req.add_header("CF-Access-Client-Id", access[0])
        req.add_header("CF-Access-Client-Secret", access[1])
    return req


def fetch_for_verify(req, *, opener=None):
    """Fetch with redirects REFUSED, never followed."""
    call = opener if opener is not None else NO_REDIRECTS.open
    try:
        return call(req, timeout=CONTROL_READ_TIMEOUT)
    except urllib.error.HTTPError as e:
        if 300 <= e.code < 400:
            # Finding S4. The BODY echo was fixed and this HEADER echo was left. An edge
            # server that receives the Access credentials can reflect one into `Location`,
            # which then lands in terminal and CI logs. The status only.
            raise StageError(
                6, f"{req.full_url} answered {e.code}, a redirect. That is an Access login, "
                   "not the page. It is a FAILURE and is not followed, because following it "
                   "would send the credentials to the redirect target. The Location header "
                   "is deliberately not shown: it is attacker-controlled and could carry a "
                   "reflected credential."
            ) from e
        raise StageError(6, f"{req.full_url} answered HTTP {e.code}") from e
    except (TimeoutError, OSError) as e:
        raise StageError(6, f"{req.full_url} could not be fetched: {e}") from e


def check_verify_response(resp, *, want: bytes, deployment_id: int, url_path: str) -> None:
    """Per asset: 200, the echo naming THIS deployment, that asset's own derived content
    type, and byte equality.

    Finding A3: revision 1 put `text/html` in a condition it then repeated for every asset,
    which would have rejected every valid CSS, JavaScript and image asset.
    """
    with resp as r:
        status = getattr(r, "status", 200)
        raw_headers = getattr(r, "headers", None)
        # Finding S1: the control calls were bounded and this was not — the same defect,
        # the other half. A trickling server evades a per-socket deadline for ever.
        body = _read_bounded(r, stage=6)

    def header(name: str):
        """Case-INSENSITIVELY. Step 8a, inline pass.

        `resp.headers` is an `email.message.Message`, whose `.get()` folds case. Wrapping
        it in `dict()` produces a plain dict that does not — and every local test still
        passed, because the harness sends these title-cased. **HTTP/2 lowercases all header
        names and Cloudflare speaks HTTP/2**, so the plain-dict version would have failed
        exactly the edge half nobody can exercise yet, reported as a byte mismatch rather
        than as anything mentioning headers.
        """
        if raw_headers is None:
            return None
        get = getattr(raw_headers, "get", None)
        if get is not None and not isinstance(raw_headers, dict):
            return get(name)
        for k, v in dict(raw_headers).items():
            if k.lower() == name.lower():
                return v
        return None
    if status != 200:
        raise StageError(6, f"{url_path} answered HTTP {status}")
    echo = header("X-Doc-Deployment")
    if str(echo) != str(deployment_id):
        raise StageError(
            6, f"{url_path} carries X-Doc-Deployment {echo!r}, not {deployment_id}. The "
               "page served is a different deployment from the one just published.")
    want_type = content_type_for(url_path)
    got_type = header("Content-Type")
    if got_type != want_type:
        raise StageError(6, f"{url_path} is served as {got_type!r}, not {want_type!r}")
    if body != want:
        raise StageError(
            6, f"{url_path} does not serve the bytes that were rendered "
               f"({len(body)} bytes served, {len(want)} expected).")


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

    Lowercased before assembly because a DNS label is case-insensitive, so `Rawgentic` and
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
    # page names for one issue, which is the duplication this whole convention exists
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
        raise StageError(2, f"the derived name {name!r} is not a usable page "
                            f"name (lowercase letters, digits and hyphens, "
                            f"{MAX_NAME} chars max)")
    # The alias cap comes AFTER name validity so the two limits stay distinguishable: an
    # unusable name gets the message above; a usable one that cannot round-trip to its
    # own hostname gets this one (#23).
    # Finding S6: the note was COMPUTED and thrown away, so the CLI printed nothing while
    # the acceptance mapping claimed a 40-character name warns and passes. Returned now,
    # and stage 2 prints it.
    return name, check_name_length(name)


# The length at which a name is worth mentioning. Below the hard limit, above comfortable.
_NAME_WARN_AT = 35


def check_name_length(name: str) -> list[str]:
    """Refuse past the DNS label limit; WARN between 36 and 63. #36 AC3.

    Returns the notes worth printing, so the caller prints them rather than this deciding
    what a warning looks like.
    """
    if len(name) > MAX_ALIAS_LABEL:
        raise StageError(
            2, f"the derived name {name!r} is {len(name)} characters, over the "
               f"{MAX_ALIAS_LABEL}-character DNS label limit. That is not a preference: "
               "harness/routing.py:is_valid_label refuses it, so the deployment could "
               f"never be addressed. Shorten --ref by at least "
               f"{len(name) - MAX_ALIAS_LABEL} character(s).")
    if len(name) > _NAME_WARN_AT:
        return [f"note: the derived name is {len(name)} characters. That publishes fine on "
                f"the harness, which truncates nothing — it would have been refused under "
                f"the legacy {_NAME_WARN_AT}-character cap."]
    return []


def assert_manifest_covers(staged: list[str], url_paths: list[str]) -> None:
    """Every staged resource is declared, and every declaration was staged. #36 AC3.

    `stage_assets` already refuses a reference it cannot ship. This is the other half, and
    it runs in both directions deliberately:

    * staged but undeclared -> the harness never fetches it, and the page 404s a resource
      on a deployment that otherwise activated cleanly;
    * declared but unstaged -> the harness fetches a blob the render never produced.
    """
    # Compared DECODED on both sides. The manifest carries percent-encoded url_paths
    # (the harness refuses anything else) while `staged` carries the real filenames, so a
    # raw string comparison would report every asset with a space as both missing AND
    # extra — which is how a correct manifest looked like a broken one for one commit.
    want = {urllib.parse.unquote(p).lstrip("/") for p in url_paths}
    have = {urllib.parse.unquote(s).lstrip("/") for s in staged}
    missing = sorted(have - want)
    if missing:
        raise StageError(
            3, "the page references resources that the manifest does not declare, so they "
               f"would 404 on a live deployment: {', '.join(missing)}")
    extra = sorted(want - have)
    if extra:
        raise StageError(
            3, "the manifest declares resources the render did not produce, so the harness "
               f"would fetch bytes nobody staged: {', '.join(extra)}")


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


def _title_of(body: str) -> str:
    m = _TITLE.search(body)
    return html.unescape(m.group(1)).strip() if m else ""


# The hosted-deploy path is gone. #36 replaced deploying with publishing through the
# harness control API, and the leftover CLI helpers were removed with the rest of the
# vendor era in 5.0.0; git history holds both, and the #36 PR maps where each old risk went.


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
    ap.add_argument("--publish-remote", default=None, dest="publish_remote",
                    help="the git remote whose GitHub owner/name the manifest pins. Only "
                         "needed when this branch has no upstream AND there are several "
                         "GitHub remotes; otherwise it is derived.")
    ap.add_argument("--config", default=None,
                    help="read configuration from this file instead of the default location")
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
        print(f"publish_doc: 1/6 rendered {out_path} ({style} template, "
              f"{pack['origin']} palette {pack['accent']['light']})")

        stage = 2
        # The first place a stranger is stopped, so it must say what to run. `require_*`
        # raises `ConfigError`, which the handler below turns into a one-line stage failure
        # rather than a traceback.
        workspace = CONFIG.require_workspace_file(cli_value=args.workspace_file,
                                                  config_path=config_path)
        name, name_notes = derive_name(args.project, args.purpose, args.ref, workspace)
        print(f"publish_doc: 2/6 name {name}")
        for note in name_notes:
            print(f"publish_doc: {note}")

        stage = 3
        for note in source_gate(Path(args.md),
                                allow_unsupported=args.allow_unsupported_markdown,
                                ack_stale=args.ack_stale):
            print(f"publish_doc: {note}")
        gate(page, skip_component_checks=args.skip_component_checks)
        # Said out loud, every run. A skipped check that reports nothing is how a page with
        # no components reaches a public URL looking like it passed.
        print("publish_doc: 3/6 lint gate passed"
              + (" (--skip-component-checks: BOTH component checks were SKIPPED)"
                 if args.skip_component_checks else ""))

        # Staging proves every referenced asset can ship. No network, no git.
        with tempfile.TemporaryDirectory(prefix="publish-doc-") as tmp:
            staged = stage_assets(page, Path(args.md).parent, Path(tmp))

        if args.dry_run:
            # **AC5: `--dry-run` behavior is unchanged.** Nothing below this line runs.
            #
            # An earlier revision of this rewrite ran stage 4a provenance here, on the
            # reasoning that it touches no network once the fetch is skipped. That was
            # wrong, and an existing first-run test caught it: provenance needs a git
            # REPOSITORY, so a dry run began failing on documents that render perfectly —
            # a behavior change on the one flag whose criterion says it must not change.
            #
            # Provenance is about PUBLISHING. A dry run stops before publishing, so it has
            # nothing to establish. This also settles finding N10 outright: a dry run
            # performs no git at all, so there is no fetch to skip.
            print(f"publish_doc: --dry-run, stopping before the first network call "
                  f"({len(staged)} asset(s) would ship)")
            return 0

        stage = 4
        # #36 stage 4a. The harness fetches blobs from GITHUB, so the page must already be
        # committed and pushed, and the publish pins that commit.
        root = Path(assert_one_repository(Path(args.md), out_path))
        remote, repo = select_remote(root, args.publish_remote)
        branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], root).stdout.strip()
        assert_head_reachable(root, remote, branch, fetch=True)
        commit_sha = _git(["rev-parse", "HEAD"], root).stdout.strip()
        print(f"publish_doc: 4/6 provenance {repo}@{commit_sha[:12]} via {remote}")

        stage = 5
        manifest = build_manifest(root=root, page_path=out_path, staged=staged,
                                  asset_base=Path(args.md).parent, name=name,
                                  repo=repo, commit_sha=commit_sha,
                                  md_path=Path(args.md), rendered=page)
        assert_manifest_covers(staged, [a["url_path"] for a in manifest["assets"]
                                        if a["url_path"] != "/index.html"])
        control = control_base(os.environ)
        edge = public_base(os.environ)
        access = assert_credentials(os.environ, edge=edge is not None)
        token = os.environ["DOC_HARNESS_PUBLISH_TOKEN"].strip()

        previous = read_active(control, name, token)
        deployment_id = publish(control, manifest, previous, token)
        print(f"publish_doc: 5/6 published deployment {deployment_id} "
              f"({len(manifest['assets'])} asset(s), was {previous})")

        stage = 6
        # Finding S0, raised three times across two gates and DECLINED three times as
        # scope: the POST activates before this verifies, so a failure here leaves the new
        # deployment serving. A true rollback is not available publisher-side — it would
        # need the PREVIOUS manifest, which this process never had, or a create-inactive
        # protocol, which is harness code and out of this issue's scope.
        #
        # What IS available is refusing to be quiet about it. A stage-6 failure now says
        # which deployment is live and unverified, which one it replaced, and the exact
        # call that shows the current state.
        want = {a["url_path"]: (root / a["repo_path"]).read_bytes()
                for a in manifest["assets"]}
        try:
            for url_path, body in want.items():
                req = build_verify_request(control, url_path, deployment_id,
                                           name=name, access=None)
                check_verify_response(fetch_for_verify(req), want=body,
                                      deployment_id=deployment_id, url_path=url_path)
        except StageError as e:
            raise StageError(
                6, f"{e.message}\n\nDeployment {deployment_id} IS ACTIVE AND UNVERIFIED. "
                   f"It replaced {previous}. Nothing rolled it back: this publisher cannot, "
                   f"because rollback needs the previous manifest it never held. Read the "
                   f"current state with GET {control}/v1/deployments/{name}, and publish a "
                   f"known-good commit to replace it.") from e
        print(f"publish_doc: 6/6 origin verified — {len(want)} asset(s) serve exactly "
              f"what was committed")

        if edge is None:
            print("publish_doc: edge half SKIPPED — DOC_HARNESS_PUBLIC_BASE is not set, so "
                  "nothing past the Cloudflare edge was checked. This is NOT a pass.")
            return EXIT_EDGE_SKIPPED
        edge_base = edge.replace("<name>", name)
        for url_path, body in want.items():
            req = build_verify_request(edge_base, url_path, deployment_id,
                                       name=name, access=access)
            check_verify_response(fetch_for_verify(req), want=body,
                                  deployment_id=deployment_id, url_path=url_path)
        url = f"{edge_base}/"
        print(f"publish_doc: 6/6 edge verified — {url}")
    except DeclaredStateError as e:
        # Not a stage failure: a state the operator declared by leaving a variable unset.
        # It carries its own code precisely so a caller can tell the two apart.
        print(f"publish_doc: {e.message}", file=sys.stderr)
        return e.code
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
        # A missing binary raises FileNotFoundError, not SystemExit. Without
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
