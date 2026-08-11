"""The first-run setup entry point (#9).

Design: `docs/planning/2026-08-10-9-first-run-setup-flow.md` (revision 3).

Setup's whole job is to be honest on a machine that has nothing. So the tests that matter
here are the refusals and the state reporting, not the happy path:

* **`status` and `can_proceed` are different questions.** A configured user with an empty
  project list can still publish to the literal `workspace` bucket, so `can_proceed` is true
  while `status` still names something missing. A first run lacking only an optional thing is
  not reported as broken.
* **Authentication is not authorization.** `vercel whoami` succeeding says nothing about
  whether the recorded team is usable, so setup proves the team with the same scoped listing
  the publisher itself makes and compares `contextName`.
* **A probe that could not run is not a denial.** Reporting a network blip as `scope_denied`
  sends the user to fix a permission they already hold.
* **`--add-project` never writes to a file this package did not create.** The resolved
  workspace may be someone else's, read by other tools.
* **No credential is ever stored, and `vercel login` is never run** — it is interactive and
  mutates machine-global state.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import setup as setup_mod  # noqa: E402
import user_config  # noqa: E402

SCOPE = "example-team"
ENV_VARS = ("DESIGN_DOC_PUBLISH_CONFIG", "DESIGN_DOC_PUBLISH_WORKSPACE_FILE",
            "DESIGN_DOC_PUBLISH_VERCEL_SCOPE", "XDG_CONFIG_HOME")


@pytest.fixture(autouse=True)
def scrubbed(tmp_path, monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    return home


@pytest.fixture
def cfg(tmp_path):
    return tmp_path / "config.json"


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class FakeVercel:
    """Stands in for the CLI. Records every argv so the tests can assert what was asked."""

    def __init__(self, *, installed=True, logged_in=True, listing=None, rc=0, raises=None):
        self.installed = installed
        self.logged_in = logged_in
        self.listing = listing
        self.rc = rc
        self.raises = raises
        self.calls = []

    def install(self, monkeypatch):
        monkeypatch.setattr(shutil, "which",
                            lambda name: "/usr/bin/vercel" if self.installed else None)
        monkeypatch.setattr(subprocess, "run", self)
        return self

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))
        if self.raises:
            raise self.raises
        if "whoami" in cmd:
            return subprocess.CompletedProcess(
                cmd, 0 if self.logged_in else 1,
                "someone\n" if self.logged_in else "", "" if self.logged_in else "no session")
        if "ls" in cmd:
            body = self.listing if self.listing is not None else json.dumps(
                {"projects": [], "pagination": {"next": None}, "contextName": SCOPE})
            return subprocess.CompletedProcess(cmd, self.rc, body, "")
        return subprocess.CompletedProcess(cmd, 0, "", "")


def _status(monkeypatch, fake, cfg, **kw):
    fake.install(monkeypatch)
    return setup_mod.status(config_path=cfg, **kw)


# --------------------------------------------------------------------- the state table

class TestTheStateTable:
    def test_no_cli_installed(self, monkeypatch, cfg):
        s = _status(monkeypatch, FakeVercel(installed=False), cfg)
        assert s["status"] == "needs_vercel_cli"
        assert s["can_proceed"] is False
        assert s["project_count"] is None
        assert setup_mod.exit_code(s) == 2

    def test_installed_but_not_authenticated(self, monkeypatch, cfg):
        s = _status(monkeypatch, FakeVercel(logged_in=False), cfg)
        assert s["status"] == "needs_login"
        assert s["can_proceed"] is False
        assert setup_mod.exit_code(s) == 3

    def test_authenticated_but_nothing_configured(self, monkeypatch, cfg):
        s = _status(monkeypatch, FakeVercel(), cfg)
        assert s["status"] == "needs_config"
        assert s["can_proceed"] is False
        assert setup_mod.exit_code(s) == 4

    def test_a_probe_that_could_not_run_is_not_a_denial(self, monkeypatch, cfg, tmp_path):
        """The distinction that keeps a network blip from telling someone to fix a
        permission they already hold."""
        ws = _write(tmp_path / "ws.json", {"version": 1, "projects": [{"name": "widget"}]})
        _write(cfg, {"version": 1, "vercel_scope": SCOPE, "workspace_file": str(ws)})
        s = _status(monkeypatch, FakeVercel(listing="not json at all"), cfg)
        assert s["status"] == "vercel_probe_failed"
        assert s["can_proceed"] is False
        assert setup_mod.exit_code(s) == 5

    def test_a_listing_answering_for_another_team_is_a_denial(self, monkeypatch, cfg,
                                                              tmp_path):
        ws = _write(tmp_path / "ws.json", {"version": 1, "projects": [{"name": "widget"}]})
        _write(cfg, {"version": 1, "vercel_scope": SCOPE, "workspace_file": str(ws)})
        other = json.dumps({"projects": [], "pagination": {"next": None},
                            "contextName": "someone-else"})
        s = _status(monkeypatch, FakeVercel(listing=other), cfg)
        assert s["status"] == "scope_denied"
        assert s["scope_list_accessible"] is False
        assert setup_mod.exit_code(s) == 3

    def test_a_configured_workspace_that_is_gone(self, monkeypatch, cfg, tmp_path):
        _write(cfg, {"version": 1, "vercel_scope": SCOPE,
                     "workspace_file": str(tmp_path / "gone.json")})
        s = _status(monkeypatch, FakeVercel(), cfg)
        assert s["status"] == "workspace_missing"
        assert s["project_count"] is None
        assert setup_mod.exit_code(s) == 4

    def test_a_zero_byte_workspace_is_malformed_not_empty(self, monkeypatch, cfg, tmp_path):
        """Zero bytes is not valid JSON, so it is a malformed file rather than an empty
        project list — the two get different answers on purpose."""
        ws = tmp_path / "ws.json"
        ws.write_text("", encoding="utf-8")
        _write(cfg, {"version": 1, "vercel_scope": SCOPE, "workspace_file": str(ws)})
        s = _status(monkeypatch, FakeVercel(), cfg)
        assert s["status"] == "workspace_malformed"
        assert setup_mod.exit_code(s) == 4

    def test_an_empty_project_list_can_still_proceed(self, monkeypatch, cfg, tmp_path):
        """The row that proves `status` and `can_proceed` are different questions: the
        literal `workspace` bucket publishes without any registered project."""
        ws = _write(tmp_path / "ws.json", {"version": 1, "projects": []})
        _write(cfg, {"version": 1, "vercel_scope": SCOPE, "workspace_file": str(ws)})
        s = _status(monkeypatch, FakeVercel(), cfg)
        assert s["status"] == "ready_no_projects"
        assert s["can_proceed"] is True
        assert s["project_count"] == 0
        assert setup_mod.exit_code(s) == 0

    def test_fully_configured(self, monkeypatch, cfg, tmp_path):
        ws = _write(tmp_path / "ws.json",
                    {"version": 1, "projects": [{"name": "widget"}, {"name": "gadget"}]})
        _write(cfg, {"version": 1, "vercel_scope": SCOPE, "workspace_file": str(ws)})
        s = _status(monkeypatch, FakeVercel(), cfg)
        assert s["status"] == "ready"
        assert s["can_proceed"] is True
        assert s["project_count"] == 2
        assert setup_mod.exit_code(s) == 0

    def test_an_unknown_config_version_is_reported_not_raised(self, monkeypatch, cfg):
        _write(cfg, {"version": 99})
        s = _status(monkeypatch, FakeVercel(), cfg)
        assert s["status"] == "config_version_unsupported"
        assert setup_mod.exit_code(s) == 4

    def test_first_run_is_about_the_config_file_alone(self, monkeypatch, cfg, tmp_path):
        assert _status(monkeypatch, FakeVercel(), cfg)["first_run"] is True
        _write(cfg, {"version": 1})
        assert _status(monkeypatch, FakeVercel(), cfg)["first_run"] is False


# ------------------------------------------------------------------------ the surfaces

class TestTheJsonMode:
    def test_it_emits_the_three_names_the_criterion_asks_for(self, monkeypatch, cfg, capsys):
        FakeVercel().install(monkeypatch)
        rc = setup_mod.main(["--json", "--config", str(cfg)])
        assert rc == 0, "--json always exits 0; it reports rather than gates"
        payload = json.loads(capsys.readouterr().out)
        for key in ("status", "can_proceed", "first_run"):
            assert key in payload
        for key in ("config_file", "workspace_file", "vercel_scope", "vercel_cli",
                    "authenticated", "scope_list_accessible", "project_count"):
            assert key in payload

    def test_it_never_leaks_captured_cli_output(self, monkeypatch, cfg, capsys, tmp_path):
        ws = _write(tmp_path / "ws.json", {"version": 1, "projects": []})
        _write(cfg, {"version": 1, "vercel_scope": SCOPE, "workspace_file": str(ws)})
        FakeVercel(listing=json.dumps({"projects": [], "pagination": {"next": None},
                                       "contextName": SCOPE,
                                       "secret": "tok_abc123"})).install(monkeypatch)
        setup_mod.main(["--json", "--config", str(cfg)])
        assert "tok_abc123" not in capsys.readouterr().out


class TestTheCheckMode:
    def test_it_is_silent_when_everything_is_ready(self, monkeypatch, cfg, capsys, tmp_path):
        ws = _write(tmp_path / "ws.json", {"version": 1, "projects": [{"name": "widget"}]})
        _write(cfg, {"version": 1, "vercel_scope": SCOPE, "workspace_file": str(ws)})
        FakeVercel().install(monkeypatch)
        rc = setup_mod.main(["--check", "--config", str(cfg)])
        captured = capsys.readouterr()
        assert rc == 0
        assert captured.out == "" and captured.err == ""

    def test_it_prints_one_actionable_line_otherwise(self, monkeypatch, cfg, capsys):
        FakeVercel(installed=False).install(monkeypatch)
        rc = setup_mod.main(["--check", "--config", str(cfg)])
        err = capsys.readouterr().err
        assert rc == 2
        assert err.count("\n") == 1, f"one line, not a report: {err!r}"


class TestTheVersionGuard:
    def test_it_refuses_an_older_interpreter_with_a_sentence(self, capsys):
        """Setup is the first thing a stranger runs, so a too-old interpreter must produce a
        sentence rather than a SyntaxError. Called with a faked version because no
        interpreter below the floor exists on this machine to run it under — which is stated
        in the design rather than papered over."""
        assert setup_mod.check_python_version((3, 8, 0)) is False
        out = capsys.readouterr()
        message = out.err or out.out
        assert str(setup_mod.MINIMUM_PYTHON[0]) in message
        assert "3.8" in message

    def test_it_passes_on_the_declared_floor(self):
        assert setup_mod.check_python_version(setup_mod.MINIMUM_PYTHON) is True


# ------------------------------------------------------------------------- the setters

class TestInitWorkspace:
    def test_it_creates_one_and_records_that_we_own_it(self, monkeypatch, cfg, tmp_path):
        FakeVercel().install(monkeypatch)
        target = tmp_path / "mine.json"
        rc = setup_mod.main(["--init-workspace", str(target), "--config", str(cfg)])
        assert rc == 0
        assert json.loads(target.read_text(encoding="utf-8")) == {"version": 1, "projects": []}
        stored = json.loads(cfg.read_text(encoding="utf-8"))
        assert stored["workspace_file"] == str(target)
        assert stored["owned_workspace_file"] == str(target)

    def test_it_refuses_to_overwrite_an_existing_file(self, monkeypatch, cfg, tmp_path):
        FakeVercel().install(monkeypatch)
        target = _write(tmp_path / "already.json", {"version": 1, "projects": [{"name": "x"}]})
        rc = setup_mod.main(["--init-workspace", str(target), "--config", str(cfg)])
        assert rc != 0
        assert json.loads(target.read_text(encoding="utf-8"))["projects"] == [{"name": "x"}]

    def test_without_a_path_it_lands_beside_the_config(self, monkeypatch, cfg, tmp_path):
        FakeVercel().install(monkeypatch)
        setup_mod.main(["--init-workspace", "--config", str(cfg)])
        stored = json.loads(cfg.read_text(encoding="utf-8"))
        assert Path(stored["workspace_file"]).parent == cfg.parent


class TestSetWorkspace:
    def test_it_stores_an_absolute_normalized_path(self, monkeypatch, cfg, tmp_path):
        """Storing what the user typed would make resolution depend on whichever directory a
        later publish ran from, turning a configured workspace into a missing one."""
        FakeVercel().install(monkeypatch)
        _write(tmp_path / "ws.json", {"version": 1, "projects": []})
        rc = setup_mod.main(["--set-workspace", "ws.json", "--config", str(cfg)])
        assert rc == 0
        stored = json.loads(cfg.read_text(encoding="utf-8"))["workspace_file"]
        assert Path(stored).is_absolute()
        assert Path(stored) == tmp_path / "ws.json"

    def test_adopting_does_not_claim_ownership(self, monkeypatch, cfg, tmp_path):
        FakeVercel().install(monkeypatch)
        ws = _write(tmp_path / "theirs.json", {"version": 1, "projects": []})
        setup_mod.main(["--set-workspace", str(ws), "--config", str(cfg)])
        assert "owned_workspace_file" not in json.loads(cfg.read_text(encoding="utf-8"))

    def test_it_refuses_a_path_that_is_not_there(self, monkeypatch, cfg, tmp_path):
        FakeVercel().install(monkeypatch)
        rc = setup_mod.main(["--set-workspace", str(tmp_path / "nope.json"),
                             "--config", str(cfg)])
        assert rc != 0


class TestSetScope:
    def test_it_proves_access_before_recording(self, monkeypatch, cfg):
        fake = FakeVercel().install(monkeypatch)
        rc = setup_mod.main(["--set-scope", SCOPE, "--config", str(cfg)])
        assert rc == 0
        assert json.loads(cfg.read_text(encoding="utf-8"))["vercel_scope"] == SCOPE
        listing = [c for c in fake.calls if "ls" in c]
        assert listing, "the team must be proved with a real scoped read, not assumed"
        assert listing[0][listing[0].index("--scope") + 1] == SCOPE

    def test_it_refuses_a_team_the_listing_does_not_answer_for(self, monkeypatch, cfg):
        other = json.dumps({"projects": [], "pagination": {"next": None},
                            "contextName": "someone-else"})
        FakeVercel(listing=other).install(monkeypatch)
        rc = setup_mod.main(["--set-scope", SCOPE, "--config", str(cfg)])
        assert rc != 0
        assert not cfg.exists() or "vercel_scope" not in json.loads(
            cfg.read_text(encoding="utf-8"))

    def test_it_refuses_a_value_that_is_not_a_slug(self, monkeypatch, cfg):
        FakeVercel().install(monkeypatch)
        assert setup_mod.main(["--set-scope", "Not A Slug", "--config", str(cfg)]) != 0
        assert not cfg.exists()

    def test_an_option_like_value_cannot_become_a_team(self, monkeypatch, cfg):
        """Two layers refuse this, and it is worth pinning both. argparse rejects a bare
        `--set-scope --sneaky` outright, because it reads the second token as a flag. The
        `=` form gets past argparse and is stopped by the validator, which is the layer that
        matters — a leading dash reaching an argv is the injection."""
        FakeVercel().install(monkeypatch)
        with pytest.raises(SystemExit):
            setup_mod.main(["--set-scope", "--sneaky", "--config", str(cfg)])
        assert setup_mod.main(["--set-scope=--sneaky", "--config", str(cfg)]) != 0
        assert not cfg.exists()


class TestAddProject:
    def _owned(self, monkeypatch, cfg, tmp_path):
        FakeVercel().install(monkeypatch)
        setup_mod.main(["--init-workspace", str(tmp_path / "mine.json"),
                        "--config", str(cfg)])
        return tmp_path / "mine.json"

    def test_it_adds_a_name(self, monkeypatch, cfg, tmp_path):
        ws = self._owned(monkeypatch, cfg, tmp_path)
        assert setup_mod.main(["--add-project", "payments-api", "--config", str(cfg)]) == 0
        assert json.loads(ws.read_text(encoding="utf-8"))["projects"] == [
            {"name": "payments-api"}]

    def test_adding_the_same_name_twice_is_idempotent(self, monkeypatch, cfg, tmp_path):
        ws = self._owned(monkeypatch, cfg, tmp_path)
        setup_mod.main(["--add-project", "payments-api", "--config", str(cfg)])
        assert setup_mod.main(["--add-project", "payments-api", "--config", str(cfg)]) == 0
        assert json.loads(ws.read_text(encoding="utf-8"))["projects"] == [
            {"name": "payments-api"}]

    def test_it_preserves_unknown_fields_and_existing_entries(self, monkeypatch, cfg,
                                                              tmp_path):
        ws = self._owned(monkeypatch, cfg, tmp_path)
        data = json.loads(ws.read_text(encoding="utf-8"))
        data["projects"] = [{"name": "old", "path": "./old", "extra": 1}]
        data["somethingElse"] = {"keep": True}
        ws.write_text(json.dumps(data), encoding="utf-8")
        setup_mod.main(["--add-project", "new", "--config", str(cfg)])
        after = json.loads(ws.read_text(encoding="utf-8"))
        assert after["somethingElse"] == {"keep": True}
        assert {"name": "old", "path": "./old", "extra": 1} in after["projects"]
        assert {"name": "new"} in after["projects"]

    def test_it_REFUSES_a_workspace_this_package_did_not_create(self, monkeypatch, cfg,
                                                               tmp_path, capsys):
        """The important one. The resolved workspace can be another tool's file, read by
        every concurrent session on the machine — writing there is out of the question."""
        FakeVercel().install(monkeypatch)
        theirs = _write(tmp_path / "theirs.json", {"version": 1, "projects": []})
        setup_mod.main(["--set-workspace", str(theirs), "--config", str(cfg)])
        before = theirs.read_text(encoding="utf-8")

        rc = setup_mod.main(["--add-project", "widget", "--config", str(cfg)])
        assert rc != 0
        assert theirs.read_text(encoding="utf-8") == before, "it must not have been touched"
        err = capsys.readouterr().err
        assert "theirs.json" in err and "--init-workspace" in err

    def test_ownership_is_a_stored_path_not_a_boolean(self, monkeypatch, cfg, tmp_path):
        """A boolean goes stale the moment an override selects a different file: the flag
        would still read true while resolution pointed somewhere else."""
        ws = self._owned(monkeypatch, cfg, tmp_path)
        elsewhere = _write(tmp_path / "elsewhere.json", {"version": 1, "projects": []})
        before = elsewhere.read_text(encoding="utf-8")
        monkeypatch.setenv("DESIGN_DOC_PUBLISH_WORKSPACE_FILE", str(elsewhere))
        rc = setup_mod.main(["--add-project", "widget", "--config", str(cfg)])
        assert rc != 0, "an override moved resolution off the owned file; it must refuse"
        assert elsewhere.read_text(encoding="utf-8") == before
        assert json.loads(ws.read_text(encoding="utf-8"))["projects"] == []

    def test_it_refuses_a_name_that_is_not_a_slug(self, monkeypatch, cfg, tmp_path):
        self._owned(monkeypatch, cfg, tmp_path)
        assert setup_mod.main(["--add-project", "Not A Slug", "--config", str(cfg)]) != 0

    def test_the_write_is_serialized(self, monkeypatch, cfg, tmp_path):
        """Atomic replace keeps each write whole but does NOT make read-modify-write atomic:
        two runs can both read, both add, and the later replace erases the earlier addition.
        That is data loss, so the whole operation takes a lock."""
        import inspect
        source = inspect.getsource(setup_mod)
        assert "flock" in source, "the read-modify-write must be serialized, not just atomic"


class TestNoSetterEverPrintsATraceback:
    """Found by the Step-8a inline review, and reproduced before it was fixed.

    `status()` handles an unreadable config and reports `config_version_unsupported`, but
    every SETTER reached `user_config.load` unguarded — so a user whose config names a
    version this build does not know got a raw traceback from the one command that was
    supposed to help them out of it. AC5 says a legible message, not a traceback, and it does
    not carve out the setters.
    """

    @pytest.mark.parametrize("args", [
        ["--set-workspace", "WS"],
        ["--add-project", "widget"],
        ["--init-workspace", "NEW"],
        ["--set-scope", SCOPE],
    ])
    def test_an_unknown_config_version_is_a_sentence(self, monkeypatch, cfg, tmp_path,
                                                     capsys, args):
        FakeVercel().install(monkeypatch)
        _write(cfg, {"version": 99})
        ws = _write(tmp_path / "ws.json", {"version": 1, "projects": []})
        args = [a.replace("WS", str(ws)).replace("NEW", str(tmp_path / "new.json"))
                for a in args]

        rc = setup_mod.main(args + ["--config", str(cfg)])
        assert rc != 0
        err = capsys.readouterr().err
        assert "99" in err, "the message must name the version it could not read"
        assert "Traceback" not in err


class TestItNeverTouchesCredentials:
    def test_no_code_path_runs_vercel_login(self):
        """It is interactive and mutates machine-global authentication state. Setup prints the
        command and re-checks; an unattended run must never trigger it."""
        import inspect
        source = inspect.getsource(setup_mod)
        for line in source.splitlines():
            if "login" not in line:
                continue
            assert "subprocess" not in line and "run(" not in line, (
                f"setup must never invoke login: {line.strip()!r}")

    def test_it_tells_the_user_how_to_log_in(self, monkeypatch, cfg, capsys):
        FakeVercel(logged_in=False).install(monkeypatch)
        setup_mod.main(["--config", str(cfg)])
        assert "vercel login" in capsys.readouterr().out

    def test_the_config_it_writes_holds_no_credential(self, monkeypatch, cfg):
        FakeVercel().install(monkeypatch)
        setup_mod.main(["--set-scope", SCOPE, "--config", str(cfg)])
        stored = json.loads(cfg.read_text(encoding="utf-8"))
        assert set(stored) <= {"version", "workspace_file", "owned_workspace_file",
                               "vercel_scope"}

    def test_teams_are_printed_for_the_user_to_read_not_parsed(self):
        """`build_index` establishes this package's rule: the JSON surface is read from
        stdout and there is deliberately no fallback to the human table."""
        import inspect
        source = inspect.getsource(setup_mod)
        assert "teams" in source
        for line in source.splitlines():
            if "teams" in line and ("split" in line or "regex" in line or "re." in line):
                pytest.fail(f"the teams table must not be parsed: {line.strip()!r}")


class TestTheStepEightAFindings:
    """Six findings from the Step-8a cross-model review, each reproduced before it was fixed.

    They share a shape worth naming: every one is a place where the code was LENIENT about
    input in a context that mutates something. Leniency is right for reporting and wrong for
    writing, and the split had not been drawn.
    """

    def test_a_malformed_config_is_never_overwritten_by_a_setter(self, monkeypatch, cfg,
                                                                 tmp_path, capsys):
        """`load()` reads a malformed config as absent so that STATUS can still report. A
        setter then merged into that empty mapping and atomically replaced the file, which
        destroyed whatever was recoverable in it."""
        FakeVercel().install(monkeypatch)
        cfg.parent.mkdir(parents=True, exist_ok=True)
        original = '{"version": 1, "vercel_scope": "acme"  <-- hand-edited badly'
        cfg.write_text(original, encoding="utf-8")
        ws = _write(tmp_path / "ws.json", {"version": 1, "projects": []})

        rc = setup_mod.main(["--set-workspace", str(ws), "--config", str(cfg)])
        assert rc != 0
        assert cfg.read_text(encoding="utf-8") == original, (
            "the unreadable config must survive; it is the only copy of whatever was in it")
        assert "Traceback" not in capsys.readouterr().err

    def test_a_workspace_with_no_projects_key_is_malformed_not_empty(self, monkeypatch, cfg,
                                                                     tmp_path):
        """`{}` is not an empty project list. Reading it as one made `--check` report
        can_proceed while `--project` refused every name."""
        ws = _write(tmp_path / "ws.json", {"version": 1})
        _write(cfg, {"version": 1, "vercel_scope": SCOPE, "workspace_file": str(ws)})
        s = _status(monkeypatch, FakeVercel(), cfg)
        assert s["status"] == "workspace_malformed"
        assert s["can_proceed"] is False

    def test_the_publisher_agrees_that_it_is_malformed(self, tmp_path, monkeypatch):
        """The two must not disagree: setup saying ready while publish refuses is the
        confusion this closes."""
        for name in ENV_VARS:
            monkeypatch.delenv(name, raising=False)
        ws = _write(tmp_path / "ws.json", {"version": 1})
        cfg = _write(tmp_path / "config.json", {"version": 1, "workspace_file": str(ws)})
        with pytest.raises(user_config.ConfigError) as excinfo:
            user_config.require_workspace_file(config_path=cfg)
        assert "malformed" in str(excinfo.value).lower()

    def test_a_truncated_listing_is_not_accepted_as_proof_of_access(self, monkeypatch, cfg):
        """`{"contextName": ...}` alone passed, so setup recorded the team and reported
        ready while the publisher's stricter parser would reject the same CLI surface."""
        FakeVercel(listing=json.dumps({"contextName": SCOPE})).install(monkeypatch)
        rc = setup_mod.main(["--set-scope", SCOPE, "--config", str(cfg)])
        assert rc != 0
        assert not cfg.exists()

    def test_an_empty_account_still_passes_the_probe(self, monkeypatch, cfg):
        """The counterpart, so the stricter check does not break the bootstrap case: an
        account holding no projects yet is legitimate."""
        FakeVercel(listing=json.dumps({"projects": [], "pagination": {"next": None},
                                       "contextName": SCOPE})).install(monkeypatch)
        assert setup_mod.main(["--set-scope", SCOPE, "--config", str(cfg)]) == 0

    def test_init_workspace_leaves_nothing_behind_when_it_cannot_record(self, monkeypatch,
                                                                       cfg, tmp_path):
        """A created-but-unrecorded workspace is a file the user did not ask for and this
        tool will not use."""
        FakeVercel().install(monkeypatch)
        target = tmp_path / "mine.json"

        def explode(*a, **kw):
            # `setup_mod.CONFIG.ConfigError`, NOT the `user_config.ConfigError` this file
            # imported by name. They are different class objects: setup loads the module by
            # exact path under a private name, so `except CONFIG.ConfigError` there does not
            # catch an exception raised through a second, separately-loaded copy. Raising the
            # class setup actually catches is what makes this test about the rollback.
            raise setup_mod.CONFIG.ConfigError("cannot write the config")

        monkeypatch.setattr(setup_mod, "_store", explode)
        rc = setup_mod.main(["--init-workspace", str(target), "--config", str(cfg)])
        assert rc != 0
        assert not target.exists(), "the workspace it created must be rolled back"

    def test_each_entry_point_catches_its_own_loaded_error_class(self):
        """The consequence of loading modules by path, stated so the next person does not
        lose an afternoon to it: every entry point gets its OWN copy of `user_config`, so
        `except CONFIG.ConfigError` catches only exceptions raised through that same copy.

        It holds today because each entry point raises through the copy it loaded. It would
        stop holding the moment one of them let another's ConfigError propagate, so this
        pins the property rather than trusting it.
        """
        assert setup_mod.CONFIG.ConfigError is not user_config.ConfigError
        assert setup_mod.CONFIG.ConfigError.__name__ == user_config.ConfigError.__name__
        import publish_doc
        assert publish_doc.CONFIG.ConfigError is not setup_mod.CONFIG.ConfigError


class TestTheEntryPointIsExecutable:
    def test_setup_can_be_run_the_way_the_skill_says_to_run_it(self):
        """SKILL.md names `${CLAUDE_PLUGIN_ROOT}/scripts/setup.py` as a command. The other
        two user-facing entry points in this package are 0755 for exactly that reason, and
        setup shipping 0644 would make the documented first command fail on permissions."""
        import os
        import stat
        path = SCRIPTS / "setup.py"
        mode = os.stat(path).st_mode
        assert mode & stat.S_IXUSR, f"{path} is not executable, but the skill says to run it"
        assert path.read_text(encoding="utf-8").startswith("#!"), "and it needs a shebang"
