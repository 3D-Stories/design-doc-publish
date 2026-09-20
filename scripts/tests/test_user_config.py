"""Where a user's configuration lives, and how the two settings resolve (#9).

Design: `docs/planning/2026-08-10-9-first-run-setup-flow.md` (revision 3, after a Step-4
gate that ran three cross-model passes and closed budget-exhausted).

This module decided which account a PUBLIC page reached (retired) and still owns the workspace pointer, so the tests here
are about precedence and refusal rather than convenience. Three properties earned their
own tests the hard way, each from a review finding:

* **Resolution happens at call time, never at import.** A module-level `Path.home()` would
  make every test depend on the developer's real home directory and would defeat the
  subprocess isolation the first-run test needs.
* **`UNSET` is not `None` and neither is `""`.** An absent flag falls through to the next
  rung. An explicitly empty one is an error, because the user tried to set something and
  silently resolving a different value is how you deploy to the wrong account.
* **The parent directory is created before the temp file.** On a genuine first run
  `~/.config/design-doc-publish/` does not exist, so asking for a same-directory temporary
  file inside it raises before anything is written — a first-run crash inside the code
  written to fix first-run crashes.

Hermetic: every test scrubs `HOME`, `XDG_CONFIG_HOME` and every `DESIGN_DOC_PUBLISH_*`
variable, so nothing here can read or write the real machine.
"""
import json
import os
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import user_config  # noqa: E402

ENV_VARS = (
    "DESIGN_DOC_PUBLISH_CONFIG",
    "DESIGN_DOC_PUBLISH_WORKSPACE_FILE",
    "XDG_CONFIG_HOME",
)


@pytest.fixture(autouse=True)
def scrubbed(tmp_path, monkeypatch):
    """A machine with nothing configured. Every test starts here."""
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    return home


def _write_config(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestWhereTheConfigLives:
    def test_the_default_is_under_the_xdg_directory(self, scrubbed):
        assert user_config.config_file() == (
            scrubbed / ".config" / "design-doc-publish" / "config.json")

    def test_xdg_config_home_moves_it(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        assert user_config.config_file() == (
            tmp_path / "xdg" / "design-doc-publish" / "config.json")

    def test_the_environment_variable_beats_the_default(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DESIGN_DOC_PUBLISH_CONFIG", str(tmp_path / "env.json"))
        assert user_config.config_file() == tmp_path / "env.json"

    def test_the_flag_beats_the_environment_variable(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DESIGN_DOC_PUBLISH_CONFIG", str(tmp_path / "env.json"))
        got = user_config.config_file(cli_value=str(tmp_path / "flag.json"))
        assert got == tmp_path / "flag.json"

    def test_a_relative_value_resolves_against_the_working_directory(self, tmp_path):
        got = user_config.config_file(cli_value="cfg.json")
        assert got == tmp_path / "cfg.json"
        assert got.is_absolute()

    def test_an_explicitly_empty_flag_is_an_error(self):
        with pytest.raises(user_config.ConfigError):
            user_config.config_file(cli_value="")

    def test_an_explicitly_empty_environment_value_is_an_error(self, monkeypatch):
        monkeypatch.setenv("DESIGN_DOC_PUBLISH_CONFIG", "")
        with pytest.raises(user_config.ConfigError):
            user_config.config_file()

    def test_nothing_is_resolved_at_import_time(self):
        """The property the whole test-isolation story rests on: no module-level statement
        may resolve a home directory or read the environment, or scrubbing the environment
        inside a test would come too late to matter.

        Parsed rather than grepped. A line scan reads this module's own prose — which
        explains the rule and therefore quotes it — as a violation, and a guard that fires
        on its own documentation is a guard people delete.
        """
        import ast

        source = (SCRIPTS / "user_config.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        offenders = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue                      # bodies run at call time, not import time
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                continue                      # the module docstring
            segment = ast.get_source_segment(source, node) or ""
            for banned in ("Path.home()", "os.environ"):
                if banned in segment:
                    offenders.append(f"line {node.lineno}: {banned}")
        assert not offenders, (
            "these run at IMPORT time and would defeat test isolation: " + ", ".join(offenders))


class TestReadingTheConfig:
    def test_an_absent_file_is_not_an_error(self, tmp_path):
        assert user_config.load(tmp_path / "nope.json") == {}

    def test_malformed_json_warns_and_reads_as_absent(self, tmp_path, capsys):
        path = tmp_path / "config.json"
        path.write_text("{not json", encoding="utf-8")
        assert user_config.load(path) == {}
        assert "config.json" in capsys.readouterr().err

    def test_a_non_object_root_warns_and_reads_as_absent(self, tmp_path, capsys):
        path = _write_config(tmp_path / "config.json", ["a", "list"])
        assert user_config.load(path) == {}
        assert capsys.readouterr().err

    def test_an_unknown_version_is_an_explicit_error(self, tmp_path):
        path = _write_config(tmp_path / "config.json", {"version": 99})
        with pytest.raises(user_config.ConfigError) as excinfo:
            user_config.load(path)
        assert "99" in str(excinfo.value)


class TestResolvingTheWorkspaceFile:
    def test_unconfigured_resolves_to_none(self):
        assert user_config.workspace_file() is None

    def test_the_old_hardcoded_path_is_NOT_an_implicit_fallback(self, scrubbed):
        """An earlier revision kept `~/rawgentic/.rawgentic_workspace.json` as a last rung
        "only when the file exists", which reads as harmless and is not. A machine that
        happens to have a file there would silently adopt it, without the setup run, and then
        validate project names and group the index against a file its owner never pointed
        this tool at. AC4 says the hardcoded default is RETIRED and the location setup
        recorded is used instead — and a conditional default is still a default.
        """
        legacy = scrubbed / "rawgentic" / ".rawgentic_workspace.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text(json.dumps({"projects": [{"name": "somebody-elses"}]}),
                          encoding="utf-8")
        assert user_config.workspace_file() is None, (
            "a file at the old path must not be adopted without being configured")

    def test_the_config_is_what_points_at_a_workspace(self, tmp_path, scrubbed):
        legacy = scrubbed / "rawgentic" / ".rawgentic_workspace.json"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("{}", encoding="utf-8")
        cfg = _write_config(tmp_path / "config.json",
                            {"version": 1, "workspace_file": str(tmp_path / "ws.json")})
        assert user_config.workspace_file(config_path=cfg) == tmp_path / "ws.json"

    def test_the_environment_beats_the_config(self, tmp_path, monkeypatch):
        cfg = _write_config(tmp_path / "config.json",
                            {"version": 1, "workspace_file": str(tmp_path / "cfg.json")})
        monkeypatch.setenv("DESIGN_DOC_PUBLISH_WORKSPACE_FILE", str(tmp_path / "env.json"))
        assert user_config.workspace_file(config_path=cfg) == tmp_path / "env.json"

    def test_the_flag_beats_everything(self, tmp_path, monkeypatch):
        cfg = _write_config(tmp_path / "config.json",
                            {"version": 1, "workspace_file": str(tmp_path / "cfg.json")})
        monkeypatch.setenv("DESIGN_DOC_PUBLISH_WORKSPACE_FILE", str(tmp_path / "env.json"))
        got = user_config.workspace_file(cli_value=str(tmp_path / "flag.json"),
                                         config_path=cfg)
        assert got == tmp_path / "flag.json"

    def test_an_explicitly_empty_flag_is_an_error(self):
        with pytest.raises(user_config.ConfigError):
            user_config.workspace_file(cli_value="")

    def test_an_argparse_none_is_treated_as_absent_not_as_empty(self, tmp_path):
        """The parsers use `default=None`, so `None` must mean "no flag given" and fall
        through — not raise the way an explicit empty string does."""
        cfg = _write_config(tmp_path / "config.json",
                            {"version": 1, "workspace_file": str(tmp_path / "cfg.json")})
        assert user_config.workspace_file(cli_value=None,
                                          config_path=cfg) == tmp_path / "cfg.json"


class TestTheNameValidator:
    @pytest.mark.parametrize("value", ["a", "acme", "acme-docs", "a1", "my-project", "x-1-y"])
    def test_it_accepts_a_real_slug(self, value):
        assert user_config.validate_name(value) == value

    @pytest.mark.parametrize("value", [
        "-leading",          # an option-like value must never reach an argv
        "trailing-",
        "Acme",              # rejected, never silently lowercased
        "has space",
        "has\ttab",
        "has\nnewline",
        "under_score",
        "dot.dot",
        "",
        "a" * 101,           # past MAX_NAME
    ])
    def test_it_refuses_everything_else(self, value):
        with pytest.raises(user_config.ConfigError):
            user_config.validate_name(value)

    def test_a_leading_dash_can_never_pass(self):
        """The property that matters: the name reaches hostnames and rendered pages, and a
        value shaped like an option must never be able to reach an argv either."""
        for value in ("-x", "--scope", "--force"):
            with pytest.raises(user_config.ConfigError):
                user_config.validate_name(value)


class TestTheRefusalsAStrangerSees:
    def test_an_unconfigured_workspace_names_the_setup_command(self):
        with pytest.raises(user_config.ConfigError) as excinfo:
            user_config.require_workspace_file()
        message = str(excinfo.value)
        assert "setup.py" in message
        assert str(SCRIPTS) in message, "the path must be real, not a ${CLAUDE_PLUGIN_ROOT} placeholder"

    def test_a_configured_but_missing_workspace_says_which(self, tmp_path):
        cfg = _write_config(tmp_path / "config.json",
                            {"version": 1, "workspace_file": str(tmp_path / "gone.json")})
        with pytest.raises(user_config.ConfigError) as excinfo:
            user_config.require_workspace_file(config_path=cfg)
        message = str(excinfo.value)
        assert "gone.json" in message, "a configured-but-missing path must be named"
        assert "setup.py" in message

    def test_a_malformed_workspace_is_a_different_fault_from_a_missing_one(self, tmp_path):
        ws = tmp_path / "ws.json"
        ws.write_text("{not json", encoding="utf-8")
        cfg = _write_config(tmp_path / "config.json",
                            {"version": 1, "workspace_file": str(ws)})
        with pytest.raises(user_config.ConfigError) as excinfo:
            user_config.require_workspace_file(config_path=cfg)
        assert "malformed" in str(excinfo.value).lower()


class TestWritingTheConfig:
    def test_it_creates_the_parent_directory_on_a_genuine_first_run(self, scrubbed):
        """The first-run crash inside the first-run fix. On a real first run the config
        directory does not exist, so a same-directory temp file raises before anything is
        written."""
        target = scrubbed / ".config" / "design-doc-publish" / "config.json"
        assert not target.parent.exists()
        user_config.write_config({"version": 1, "some_key": "acme"}, target)
        assert json.loads(target.read_text(encoding="utf-8"))["some_key"] == "acme"

    def test_it_leaves_no_temporary_file_behind(self, tmp_path):
        target = tmp_path / "cfg" / "config.json"
        user_config.write_config({"version": 1}, target)
        assert [p.name for p in target.parent.iterdir()] == ["config.json"]

    def test_it_replaces_rather_than_truncating(self, tmp_path):
        target = tmp_path / "config.json"
        user_config.write_config({"version": 1, "vercel_scope": "first"}, target)
        user_config.write_config({"version": 1, "vercel_scope": "second"}, target)
        assert json.loads(target.read_text(encoding="utf-8"))["vercel_scope"] == "second"

    def test_a_write_it_cannot_perform_names_the_path(self, tmp_path):
        blocked = tmp_path / "blocked"
        blocked.mkdir()
        blocked.chmod(0o500)
        try:
            with pytest.raises(user_config.ConfigError) as excinfo:
                user_config.write_config({"version": 1}, blocked / "sub" / "config.json")
            assert "blocked" in str(excinfo.value)
        finally:
            blocked.chmod(0o700)


class TestTheSetupCommandItPrints:
    def test_it_is_an_absolute_path_a_stranger_can_paste(self):
        """A stranger cannot expand `${CLAUDE_PLUGIN_ROOT}` in their shell — the README
        says so — so every refusal must carry the real path."""
        assert "${CLAUDE_PLUGIN_ROOT}" not in user_config.SETUP_COMMAND
        assert user_config.SETUP_COMMAND.count("setup.py") == 1
        assert str(SCRIPTS) in user_config.SETUP_COMMAND


class TestTheEnvFileTheSecretsLiveIn:
    """`.env` exists so a publish is reproducible by somebody who did not type the token.

    Before it, `DOC_HARNESS_PUBLISH_TOKEN` had to be exported by hand every time, and on the
    author's own machine the value survived nowhere but inside a running container. The
    harness already reads this file — `docker compose` does it unasked — so the publisher
    reading the same file is what makes one value serve both halves.
    """

    def _env(self, tmp_path, name, body):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def test_it_fills_a_variable_that_is_not_set(self, scrubbed, tmp_path):
        f = self._env(tmp_path, "a.env", "DOC_HARNESS_PUBLISH_TOKEN=abc123\n")
        environ = {}
        used = user_config.load_env(files=[f], environ=environ)
        assert environ["DOC_HARNESS_PUBLISH_TOKEN"] == "abc123"
        assert used == f

    def test_a_variable_already_set_wins(self, scrubbed, tmp_path):
        """An explicit `export` in the caller's shell stays the last word. Otherwise a file
        on disk could silently redirect a publish the operator thought they had aimed."""
        f = self._env(tmp_path, "a.env", "DOC_HARNESS_PUBLISH_TOKEN=from-file\n")
        environ = {"DOC_HARNESS_PUBLISH_TOKEN": "from-shell"}
        user_config.load_env(files=[f], environ=environ)
        assert environ["DOC_HARNESS_PUBLISH_TOKEN"] == "from-shell"

    def test_only_doc_harness_names_are_loaded(self, scrubbed, tmp_path):
        """A `.env` sitting beside an installed plugin must not be able to set PATH."""
        f = self._env(tmp_path, "a.env",
                      "PATH=/evil\nLD_PRELOAD=/evil.so\nDOC_HARNESS_ZONE=example.ca\n")
        environ = {}
        user_config.load_env(files=[f], environ=environ)
        assert environ == {"DOC_HARNESS_ZONE": "example.ca"}

    def test_the_first_file_that_exists_wins(self, scrubbed, tmp_path):
        first = self._env(tmp_path, "first.env", "DOC_HARNESS_ZONE=first.ca\n")
        second = self._env(tmp_path, "second.env", "DOC_HARNESS_ZONE=second.ca\n")
        environ = {}
        used = user_config.load_env(files=[first, second], environ=environ)
        assert environ["DOC_HARNESS_ZONE"] == "first.ca"
        assert used == first

    def test_no_file_at_all_is_not_an_error(self, scrubbed, tmp_path):
        """Exporting by hand stays a supported way to run. An absent file is that case."""
        environ = {}
        assert user_config.load_env(files=[tmp_path / "nope.env"], environ=environ) is None
        assert environ == {}

    def test_it_reads_the_shapes_an_operator_actually_writes(self, scrubbed, tmp_path):
        """`export` prefixes, comments, blank lines, and quotes a password manager brought
        along. A token with a stray quote fails later as a 401, which is hours from here."""
        f = self._env(tmp_path, "a.env", "\n".join([
            "# the deploy secrets",
            "",
            "export DOC_HARNESS_PUBLISH_TOKEN='quoted-value'",
            '  DOC_HARNESS_ZONE = "spaced.ca"  ',
            "DOC_HARNESS_CONTROL_URL=http://127.0.0.1:18081  # trailing words are part of a URL",
            "NOT_AN_ASSIGNMENT",
        ]) + "\n")
        environ = {}
        user_config.load_env(files=[f], environ=environ)
        assert environ["DOC_HARNESS_PUBLISH_TOKEN"] == "quoted-value"
        assert environ["DOC_HARNESS_ZONE"] == "spaced.ca"
        assert environ["DOC_HARNESS_CONTROL_URL"].startswith("http://127.0.0.1:18081")

    def test_the_working_directory_is_never_searched(self, scrubbed, tmp_path):
        """publish_doc.py runs with its cwd set to the repository BEING PUBLISHED. A `.env`
        there is a file that repository controls, and the publish token is precisely what it
        must not be able to set."""
        (tmp_path / ".env").write_text("DOC_HARNESS_PUBLISH_TOKEN=hostile\n", encoding="utf-8")
        assert Path.cwd() == tmp_path                      # the fixture put us here
        assert (tmp_path / ".env") not in user_config.env_files()

    def test_it_looks_beside_the_scripts_and_beside_the_config(self, scrubbed):
        """Two real invocations: from this checkout, and from an installed plugin."""
        found = user_config.env_files()
        assert SCRIPTS.parent / ".env" in found
        assert user_config.config_file().parent / ".env" in found

    def test_it_honours_the_config_path_this_run_already_resolved(self, scrubbed, tmp_path):
        """This module promises one run cannot read two different config files. Re-resolving
        inside `env_files` is exactly how that promise would break, so it is passed in."""
        chosen = tmp_path / "elsewhere" / "config.json"
        found = user_config.env_files(config_path=chosen)
        assert chosen.parent / ".env" in found
        assert user_config.config_file().parent / ".env" not in found
