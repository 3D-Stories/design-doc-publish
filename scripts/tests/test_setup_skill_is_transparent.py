"""The setup skill must never install anything without asking, and must say what it changes.

**This guards a real incident.** The first version of `skills/setup/SKILL.md` carried a
remedy table whose row for a missing CLI read `Install the CLI: npm i -g vercel.` An agent
following a skill treats a line like that as an instruction, so running
`/design-doc-publish:setup` on a fresh machine performed a GLOBAL npm install with no
warning and no consent. The tool itself never did that — `setup.py` only ever printed the
command as advice. The skill turned advice into an action.

So the rule is not "document the install". The rule is that the skill must ask first, and
must state what it will change before it changes anything. These guards pin that.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SKILL = ROOT / "skills" / "setup" / "SKILL.md"


def _body() -> str:
    return SKILL.read_text(encoding="utf-8")


class TestItNeverInstallsWithoutAsking:
    def test_no_bare_install_instruction_survives(self):
        """A line that says only "install it" is an order to an agent. It must carry a
        consent word in the same sentence, or it will simply be executed."""
        # Whitespace-normalize FIRST. Splitting the raw text on newlines cuts a wrapped
        # sentence in half and then flags its own tail for lacking the consent word that
        # sits on the line above — the guard would fail on prose that is already correct.
        body = re.sub(r"\s+", " ", _body())
        for match in re.finditer(r"[^.]*npm i[ -][^.]*", body):
            sentence = match.group(0)
            lowered = sentence.lower()
            assert any(word in lowered for word in ("ask", "confirm", "permission", "agree",
                                                    "wait", "do not run", "never run",
                                                    "yourself")),\
                ("this line reads as an order and an agent will execute it, installing "
                 f"software globally without consent: {sentence.strip()!r}")

    def test_no_install_command_appears_at_all(self):
        """Since 5.0.0 nothing needs installing: the harness is probed over HTTP with the
        standard library. The strongest form of the incident guard is that no install
        command exists to be executed."""
        body = _body().lower()
        assert "npm i" not in body and "pip install" not in body

    def test_it_names_asking_before_installing_as_a_rule(self):
        body = _body().lower()
        assert "never install" in body or "do not install" in body, (
            "the skill must carry an explicit rule against installing unprompted")


class TestItSaysWhatItChanges:
    def test_it_names_both_files_it_creates(self):
        body = _body()
        for path in ("~/.config/design-doc-publish/config.json",
                     "~/.config/design-doc-publish/workspace.json"):
            assert path in body, (
                f"the skill must name {path}, so a user knows what appears on their disk")

    def test_it_states_what_is_written_versus_only_read(self):
        body = _body().lower()
        assert "reads" in body or "read-only" in body or "only reads" in body, (
            "the skill must distinguish the commands that only read from the ones that write")

    def test_it_says_no_credential_is_stored(self):
        body = _body().lower()
        assert "credential" in body, (
            "the skill must state that no credential is stored — users assume otherwise")

    def test_it_gives_the_undo(self):
        body = _body().lower()
        assert "undo" in body or "delete" in body or "remove" in body, (
            "the skill must say how to reverse what it wrote")


class TestItStillDoesItsJob:
    def test_it_still_invokes_setup_py_by_plugin_root(self):
        assert "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" in _body()

    def test_it_still_documents_check_and_json(self):
        body = _body()
        assert "--check" in body and "--json" in body

    def test_it_declares_the_probe_read_only(self):
        """The one network touch left. A skill that does not say the probe is read-only
        invites an agent to "verify" by publishing something."""
        body = _body().lower()
        assert "read-only" in body or "read only" in body
