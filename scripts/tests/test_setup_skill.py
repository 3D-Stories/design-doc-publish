"""The `setup` skill exists and is reachable as `/design-doc-publish:setup`.

`setup.py` shipped in #9 and works, but nothing exposes it as a command. A user who has
never published from a machine has to be told a raw interpreter path — and the path is not
even pasteable, because `${CLAUDE_PLUGIN_ROOT}` is substituted by Claude Code when it loads
a SKILL.md and is NOT a shell variable. So the one instruction a first-time user needs was
the one instruction they could not follow.

Claude Code exposes a plugin's skills as `/<plugin>:<skill>`, so a `skills/setup/` directory
listed in the marketplace entry IS the command. These guards pin both halves: the skill
exists with the right name, and the marketplace actually ships it. A skill on disk that the
marketplace does not list installs nothing.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SETUP_SKILL = ROOT / "skills" / "setup" / "SKILL.md"
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
PLUGIN_MANIFEST = ROOT / ".claude-plugin" / "plugin.json"


def _frontmatter(path: Path) -> dict:
    """The YAML-ish frontmatter, parsed without a YAML dependency.

    Only `key: value` at the top level is used here, which is all a SKILL.md header carries.
    """
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert match, f"{path} has no frontmatter block"
    data = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.startswith(" "):
            continue
        key, _, value = line.partition(":")
        data[key.strip()] = value.strip()
    return data


class TestTheSetupSkillExists:
    def test_the_skill_file_is_there(self):
        assert SETUP_SKILL.is_file(), (
            f"{SETUP_SKILL} is missing — without it there is no /design-doc-publish:setup "
            "command, and a first-time user must be handed a raw interpreter path")

    def test_its_name_is_bare_and_matches_the_directory(self):
        """`name: setup` yields `/design-doc-publish:setup`.

        A prefixed name would double the command to `/design-doc-publish:design-doc-publish-setup`,
        and current Claude Code rejects a colon in the field outright.
        """
        name = _frontmatter(SETUP_SKILL).get("name")
        assert name == "setup", f"name must be exactly 'setup', got {name!r}"
        assert name == SETUP_SKILL.parent.name, (
            "the frontmatter name and the directory name must agree")

    def test_it_has_a_description_that_says_when_to_use_it(self):
        description = _frontmatter(SETUP_SKILL).get("description", "")
        assert len(description) > 40, "description must say WHEN to use the skill"
        assert "setup" in description.lower() or "configur" in description.lower(), (
            "the description must name what the skill is for")


class TestTheMarketplaceShipsIt:
    def test_the_skill_directory_is_listed(self):
        """A skill the marketplace does not list is not installed, so the command never exists."""
        entry = json.loads(MARKETPLACE.read_text(encoding="utf-8"))["plugins"][0]
        assert "./skills/setup" in entry["skills"], (
            f"marketplace does not ship the setup skill: {entry['skills']}")

    def test_the_original_skill_is_still_listed(self):
        """Adding one must not displace the other — the list is a list, not a slot."""
        entry = json.loads(MARKETPLACE.read_text(encoding="utf-8"))["plugins"][0]
        assert "./skills/design-doc-publish" in entry["skills"], (
            f"the original skill was dropped: {entry['skills']}")


class TestTheSkillPointsAtTheRealTool:
    def test_it_invokes_setup_py_by_plugin_root(self):
        """`${CLAUDE_PLUGIN_ROOT}` IS substituted in a SKILL.md body, which is the whole
        reason this belongs in a skill rather than in a README the user must translate."""
        body = SETUP_SKILL.read_text(encoding="utf-8")
        assert "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" in body, (
            "the skill must invoke setup.py by CLAUDE_PLUGIN_ROOT, not by a relative path")

    def test_it_documents_the_check_flag_and_its_exit_codes(self):
        body = SETUP_SKILL.read_text(encoding="utf-8")
        assert "--check" in body, "the skill must document --check"
        assert "--json" in body, "the skill must document --json"

    def test_it_does_not_claim_to_log_in_or_store_a_credential(self):
        """setup.py signs in to nothing and stores no credential. A skill that implied
        otherwise would be asking a user to expect something the tool refuses to do."""
        body = SETUP_SKILL.read_text(encoding="utf-8").lower()
        assert "login" not in body or "never" in body, (
            "do not imply the tool logs in; it does not")


class TestTheVersionMoved:
    def test_both_manifests_agree(self):
        """The two manifests carry the version separately; a bump that misses one ships a lie."""
        plugin = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))["version"]
        market = json.loads(MARKETPLACE.read_text(encoding="utf-8"))["metadata"]["version"]
        assert plugin == market, (
            f"plugin.json says {plugin} but marketplace.json says {market}")

    def test_it_is_past_the_version_that_shipped_without_this_skill(self):
        plugin = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))["version"]
        parts = tuple(int(p) for p in plugin.split("."))
        assert parts > (1, 0, 0), (
            f"adding a command is a feature; {plugin} is not past the 1.0.0 that lacked it")
