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


def _tracked_files() -> list[Path]:
    """Every file git tracks — which is exactly what an install would copy."""
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

    def test_no_file_still_points_at_the_old_symlink_install(self):
        """The whole point of the change. A survivor here resolves to nothing once
        installed, and it fails at the moment somebody else first tries the tool."""
        offenders = []
        for path in _text_files():
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if path.name == "third-party-notices.md":
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if LEGACY_INSTALL_RE.search(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{number}")
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

    def test_no_dangling_reference_to_the_removed_set(self):
        """Deleting files is half the job. A comment or fixture still naming them is a
        pointer to nothing, which reads as an answer and delivers none."""
        offenders = []
        for path in _text_files():
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            # The notices file deliberately keeps the record of what was removed and why.
            if path.name == "third-party-notices.md":
                continue
            if "docs/planning/" in path.as_posix():
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if "nsmith-html" in line:
                    offenders.append(f"{path.relative_to(ROOT)}:{number}")
        assert not offenders, (
            "these still name the removed vendored set: " + ", ".join(offenders))

    def test_no_account_specific_document_ships(self):
        """docs/vercel-account.md named one Vercel team and recorded that its deployment
        protection was deliberately off. That is a posture disclosure, and an install would
        hand it to everybody."""
        assert not (ROOT / "docs" / "vercel-account.md").exists(), (
            "docs/vercel-account.md documents one account, not the tool, and every install "
            "would copy it")


@pytest.mark.parametrize("relative", ["scripts/publish_doc.py", "scripts/render-doc",
                                      "docs/design-language.md", "index/build_index.py"])
def test_the_files_the_skill_promises_are_where_it_says(relative):
    """SKILL.md addresses these as ${CLAUDE_PLUGIN_ROOT}/<relative>. The install root is
    whatever directory holds them, so the check that means anything is that the layout the
    skill describes is the layout the repo has."""
    assert (ROOT / relative).exists(), f"{relative} is not where SKILL.md says it is"
