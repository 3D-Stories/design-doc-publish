"""Guards for the plugin packaging shape (#2).

This package used to install by one hand-made symlink at
`~/.claude/skills/design-doc-publish`. It now ships as a Claude Code plugin, and that
changes two things a reader would not guess:

1. **A plugin skill gets no entry under `~/.claude/skills/` at all.** Verified live against
   `frontend-design`, which is installed as a plugin and has no such directory. So every
   `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/design-doc-publish/...` path that used to be
   correct is now categorically wrong, and `${CLAUDE_PLUGIN_ROOT}` replaces it.

2. **An install copies the whole `source` subtree, and nothing filters it.** A `.skillignore`
   file was probed and excludes nothing from the installed bundle. Only the marketplace
   entry's `source` bounds what ships. That is why the tests below assert about *absence* —
   anything left in this tree is handed to every stranger who installs the plugin.

The unlicensed vendored set is the sharp case. `references/nsmith-html/` had no upstream
grant, so shipping it inside a distributed plugin would have been redistribution nobody
authorised. It is deleted, and `test_no_unlicensed_vendored_set_ships` is what stops it
coming back by an innocent-looking refresh.

Stdlib only, by the same rule as the rest of this package.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
PLUGIN_MANIFEST = ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
SKILL_MD = ROOT / "skills" / "design-doc-publish" / "SKILL.md"
THIS_FILE = Path(__file__).resolve().relative_to(ROOT).as_posix()

# The eight keys AC1 names, modelled on projects/rawgentic/.claude-plugin/plugin.json,
# which was read and carries exactly these.
REQUIRED_MANIFEST_KEYS = {
    "name",
    "version",
    "description",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
}

# The old install root, in both the bare and the shell-defaulted form.
LEGACY_INSTALL_RE = re.compile(r"(CLAUDE_CONFIG_DIR|\.claude/skills/design-doc-publish)")


def _in_a_git_repo() -> bool:
    """These tests SHIP inside the plugin, and an installed copy has no `.git` — measured:
    an install copies working-tree files and leaves `.git` behind. So anything that shells
    out to git must ask first, or a stranger running the suite from their install gets
    failures that say nothing about their install.

    Two traps here, both raised by the Step-8a review and both real:

    - `rev-parse --git-dir` WALKS UP. If the install sits anywhere beneath an unrelated
      repository it answers yes, and the source-only guards then scan that foreign repo,
      find nothing, and pass vacuously — a silent false green, which is worse than the
      failure it replaced. So resolve the top level and require it to be exactly ROOT.
    - If `git` is not installed at all, `subprocess.run` raises `FileNotFoundError`. This
      runs at import, so that would abort COLLECTION rather than produce the promised
      skips. Catch it.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True,
        )
    except (FileNotFoundError, OSError):
        return False
    if result.returncode != 0:
        return False
    try:
        return Path(result.stdout.strip()).resolve() == ROOT.resolve()
    except OSError:
        return False


HAS_GIT = _in_a_git_repo()

needs_the_source_repo = pytest.mark.skipif(
    not HAS_GIT,
    reason="this guard asks about the SOURCE repository's shape, and there is no repository "
           "here. The suite ships inside the plugin, so it also runs from an installed copy, "
           "where git is absent by design — an install copies working-tree files and leaves "
           "`.git` behind. Skipping is the honest answer, not a failure.",
)


def _tracked_files() -> list[Path]:
    """Every file git tracks — which is what a clone, and therefore a real install, carries."""
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [ROOT / line for line in out.splitlines() if line]


def _text_files() -> list[Path]:
    skip_suffixes = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".pdf"}
    return [p for p in _tracked_files() if p.suffix.lower() not in skip_suffixes]


class TestTheManifest:
    def test_it_exists_and_parses(self):
        assert PLUGIN_MANIFEST.is_file(), (
            f"{PLUGIN_MANIFEST} is missing — without it `claude plugin install` has "
            "nothing to install")
        json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))

    def test_it_carries_every_required_field(self):
        data = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
        missing = REQUIRED_MANIFEST_KEYS - set(data)
        assert not missing, f"plugin.json is missing required keys: {sorted(missing)}"

    def test_every_required_field_holds_a_usable_VALUE(self):
        """Step-8a review: checking key PRESENCE lets `author: null`, an empty repository or a
        string-valued `keywords` through, while the guard claims to pin the manifest. Presence
        is not the property anyone cares about — a usable value is."""
        data = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
        for field in ("name", "version", "description", "homepage", "repository", "license"):
            value = data[field]
            assert isinstance(value, str) and value.strip(), (
                f"{field} must be a non-empty string, got {value!r}")
        author = data["author"]
        assert isinstance(author, dict), f"author must be an object, got {type(author).__name__}"
        assert isinstance(author.get("name"), str) and author["name"].strip(), (
            "author.name must be a non-empty string")
        keywords = data["keywords"]
        assert isinstance(keywords, list) and keywords, "keywords must be a non-empty list"
        assert all(isinstance(k, str) and k.strip() for k in keywords), (
            "every keyword must be a non-empty string")

    def test_the_description_does_not_promise_what_it_cannot_do(self):
        """Step-8a review, and the finding was right. The description is the FIRST thing a
        stranger reads, before any README. It promised a command that deploys and verifies,
        while publishing actually stops at stage 2 of 7 for anyone but the author — measured:
        `--project '<name>' is not a rawgentic project in ~/rawgentic/.rawgentic_workspace.json`.
        A README caveat does not correct a marketplace-facing claim."""
        for manifest, path in ((json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8")),
                                "plugin.json"),
                               (json.loads(MARKETPLACE.read_text(encoding="utf-8"))["plugins"][0],
                                "marketplace.json")):
            description = manifest["description"].lower()
            if "deploy" in description or "publish" in description:
                assert "not yet available" in description or "requires" in description, (
                    f"{path}'s description mentions deploying or publishing without saying it "
                    "is unavailable to other users until #9 lands")

    def test_the_name_matches_the_skill_directory(self):
        data = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
        assert data["name"] == SKILL_MD.parent.name, (
            "the plugin name and the skill directory name must agree, or the marketplace "
            "entry points at a directory that is not there")

    def test_the_description_is_a_sentence_not_a_file_list(self):
        """AC2: a stranger must be able to act on it."""
        desc = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))["description"]
        assert len(desc) >= 60, "a one-clause description tells a stranger nothing"
        assert ".py" not in desc, (
            "AC2 asks for what the plugin DOES, not a list of internal file names")

    def test_a_version_is_stated(self):
        """AC5's first half. The tag is a release step, not something a test can see."""
        version = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))["version"]
        assert re.fullmatch(r"\d+\.\d+\.\d+", version), (
            f"version {version!r} is not a three-part version")


class TestTheMarketplace:
    def test_it_exists_and_lists_this_skill(self):
        assert MARKETPLACE.is_file(), (
            "without .claude-plugin/marketplace.json this repo cannot be added with "
            "`claude plugin marketplace add`, and the install command cannot resolve")
        data = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
        entries = data["plugins"]
        assert len(entries) == 1, "one plugin per repo here — more needs a deliberate design"
        skills = entries[0]["skills"]
        assert "./skills/design-doc-publish" in skills, (
            f"marketplace does not list the skill directory: {skills}")

    def test_the_source_is_the_repo_root(self):
        """If this ever changes, the shipped-file guards below stop describing reality."""
        data = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
        assert data["plugins"][0]["source"] == "./"


class TestTheSkillIsPluginRooted:
    def test_the_skill_lives_where_a_plugin_skill_lives(self):
        assert SKILL_MD.is_file(), (
            f"{SKILL_MD} is missing — a plugin's skills live at skills/<name>/SKILL.md")

    def test_it_addresses_its_own_files_through_the_plugin_root(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        assert "${CLAUDE_PLUGIN_ROOT}" in text, (
            "SKILL.md must reach its bundled scripts through ${CLAUDE_PLUGIN_ROOT}, which "
            "the harness expands when it loads skill content")

    @needs_the_source_repo
    def test_no_file_still_points_at_the_old_symlink_install(self):
        """The whole point of the change. A survivor here resolves to nothing once
        installed, and it fails at the moment somebody else first tries the tool."""
        offenders = []
        for path in _text_files():
            relative = path.relative_to(ROOT).as_posix()
            # Exempt the files whose job is to RECORD the old shape: the planning documents
            # that explain what changed, and this guard, which must name the pattern it hunts.
            if relative.startswith("docs/planning/") or relative == THIS_FILE:
                continue
            if path.name == "third-party-notices.md":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if LEGACY_INSTALL_RE.search(line):
                    offenders.append(f"{relative}:{number}")
        assert not offenders, (
            "these still address the retired ~/.claude/skills install root: "
            + ", ".join(offenders))


class TestWhatShipsToAStranger:
    """An install copies every tracked file. These assert what must not be among them."""

    def test_no_unlicensed_vendored_set_ships(self):
        gone = ROOT / "references" / "nsmith-html"
        assert not gone.exists(), (
            "references/nsmith-html/ has no upstream licence grant, so shipping it inside a "
            "distributed plugin is redistribution nobody authorised. See "
            "docs/third-party-notices.md")

    def test_the_licensed_vendored_set_still_ships_with_its_notice(self):
        """The counterpart guard: artifact-organizer IS granted, and dropping it would be
        an over-correction. Its notice must travel with it."""
        kept = ROOT / "references" / "artifact-organizer"
        assert kept.is_dir(), "artifact-organizer is MIT and granted — it should still be here"
        assert (kept / "LICENSE-upstream.txt").is_file(), (
            "the upstream notice must travel with the material it covers")

    @needs_the_source_repo
    def test_no_dangling_reference_to_the_removed_set(self):
        """Deleting files is half the job. A comment or fixture still naming them is a
        pointer to nothing, which reads as an answer and delivers none.

        Four files are exempt because naming the removed set is their JOB — they are the
        record of what went and why, and losing that record is how a future refresh
        re-vendors unlicensed material without noticing. Everything else must be clean.
        """
        keeps_the_record = {
            "docs/third-party-notices.md",       # the licence position itself
            "references/README.md",              # provenance, including what was removed
            "references/manifest.json",          # the removal record and its pinned commit
            "tests/test_vendored_references.py",  # asserts the removal stays done
            "scripts/tests/test_plugin_packaging.py",  # this file
        }
        offenders = []
        for path in _text_files():
            relative = path.relative_to(ROOT).as_posix()
            if relative in keeps_the_record or relative.startswith("docs/planning/"):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if "nsmith-html" in line:
                    offenders.append(f"{relative}:{number}")
        assert not offenders, (
            "these still name the removed vendored set: " + ", ".join(offenders))

    @needs_the_source_repo
    def test_private_working_state_can_never_reach_the_distribution_source(self):
        """Measured during #2's live verification, and it was a surprise worth pinning.

        `claude plugin install` from a LOCAL PATH copies the working DIRECTORY, not the git
        tree. The real install shipped 221 files where git tracked 120: `claude_docs/` went
        along, carrying campaign driver state, supervision claims and a loop-back token.
        `.git` did NOT ship, so a GitHub-sourced install (the real distribution path, which
        clones) carries committed files only.

        So the load-bearing property is that this material is gitignored — that is what keeps
        it out of every clone, and therefore out of every install a stranger performs. It also
        means you must not test-install from a working tree holding private state and then
        conclude the bundle is clean. It is clean only from a clean clone.
        """
        for private in ("claude_docs/", ".rawgentic-*", "index/index.html"):
            result = subprocess.run(
                ["git", "-C", str(ROOT), "check-ignore", "-q", private.rstrip("*")],
                capture_output=True,
            )
            assert result.returncode == 0, (
                f"{private} is not gitignored, so it would reach the distribution source and "
                "every install made from it")

    def test_no_account_specific_document_ships(self):
        """docs/vercel-account.md named one Vercel team and recorded that its deployment
        protection was deliberately off. That is a posture disclosure, and an install would
        hand it to everybody."""
        assert not (ROOT / "docs" / "vercel-account.md").exists(), (
            "docs/vercel-account.md documents one account, not the tool, and every install "
            "would copy it")

    @needs_the_source_repo
    def test_no_account_identifier_ships_under_ANY_filename(self):
        """Cross-model review, #2: the check above uses one FILENAME as the boundary, so the
        same disclosure under any other name ships silently. That is a real gap — the review
        was right — and a filename is the wrong boundary for a content property.

        So this scans CONTENT instead. It is deliberately narrow: it hunts the account
        identifiers this project actually has, rather than pretending to be a general secret
        scanner. Step 11.5 runs real scanners. This stops the specific regression that removing
        docs/vercel-account.md was meant to fix.

        **What this does NOT do, said plainly rather than left to be discovered.** The reviewer's
        stronger proposal was an allowlist of shipped paths, enforced by packaging from a
        generated clean subtree. That is the `dist/` design, and the owner declined it as ~115
        duplicated files in a repo whose own .gitignore argues against committed derived
        artifacts. So the residual stands: a NEW kind of account-specific content, under a new
        name and using none of these words, would still ship. This narrows the hole the removed
        document opened. It does not close the class.
        """
        # Deliberately NOT the string "3d-stories". That is also the public GitHub org, so it
        # appears legitimately in the manifest, the repository URLs and the README. Using it
        # would make this guard cry wolf on correct content, and a guard nobody believes gets
        # deleted. What made the removed document a disclosure was its POSTURE claim.
        #
        # Known and deliberately out of scope for #2, reported rather than silently passed:
        #   - scripts/tests/fixtures/vercel_project_ls.* carry real project names from the
        #     account. That is the sanitisation sweep, issue #4 (its AC6 names exactly this).
        #   - VERCEL_SCOPE is hardcoded at scripts/publish_doc.py:129 and
        #     index/build_index.py:39, so the tool targets one team. That is issue #9.
        # Also NOT "invalid_sso_protection" on its own: that is a public Vercel API error
        # code, used legitimately as test data in test_deploy_check.py. The marker has to be
        # the SENTENCE that disclosed the posture, not a vocabulary word that appears near it.
        # A guard that fires on correct content teaches people to ignore it.
        markers = ("Advanced Deployment Protection is not enabled",)
        # `docs/planning/` is NOT exempt any more. The Step-8a review caught this document
        # set reproducing the exact posture sentence that deleting docs/vercel-account.md was
        # meant to remove — and planning documents ship too, so the exemption made the guard
        # complicit in the leak it existed to stop. Only this file is exempt, because it must
        # name the string it hunts.
        allowed = {"scripts/tests/test_plugin_packaging.py"}
        offenders = []
        for path in _text_files():
            relative = path.relative_to(ROOT).as_posix()
            if relative in allowed or any(relative.startswith(a) for a in allowed):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            lowered = text.lower()
            for marker in markers:
                if marker.lower() in lowered:
                    offenders.append(f"{relative} names {marker!r}")
        assert not offenders, (
            "an install copies every one of these to every stranger: " + "; ".join(offenders))


@pytest.mark.parametrize("relative", ["scripts/publish_doc.py", "scripts/render-doc",
                                      "docs/design-language.md", "index/build_index.py"])
def test_the_files_the_skill_promises_are_where_it_says(relative):
    """SKILL.md addresses these as ${CLAUDE_PLUGIN_ROOT}/<relative>. The install root is
    whatever directory holds them, so the check that means anything is that the layout the
    skill describes is the layout the repo has."""
    assert (ROOT / relative).exists(), f"{relative} is not where SKILL.md says it is"
