"""The first-run setup entry point (#9), rebuilt around the harness (5.0.0).

Setup's whole job is to be honest on a machine that has nothing. So the tests that matter
here are the refusals and the state reporting, not the happy path:

* **`status` and `can_proceed` are different questions.** A configured user with an empty
  project list can still publish to the literal `workspace` bucket, so `can_proceed` is true
  while `status` still names something missing. A first run lacking only an optional thing is
  not reported as broken.
* **A probe that could not run is not a denial.** Reporting a network blip as `harness_denied`
  sends the user to rotate a credential they already hold.
* **The probe is read-only.** It uses the control API's read-back route, which proves the URL
  and the bearer together while publishing nothing.
* **`--add-project` never writes to a file this package did not create.** The resolved
  workspace may be someone else's, read by other tools.
* **No credential is ever stored.** The harness tokens live in the environment, and the config
  file holds only the workspace pointer.
"""
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import setup as setup_mod  # noqa: E402
import user_config  # noqa: E402

# Imported HERE, at module scope, and never lazily inside a test.
#
# Since #54 `setup.probe_harness` imports `publish_doc` on demand to reuse its destination
# allowlist, and `FakeHarness` below patches `urllib.request.build_opener`. `publish_doc` builds
# its `NO_REDIRECTS` opener AT IMPORT TIME with that same function — so if its first import ever
# landed inside a patched window, `publish_doc.NO_REDIRECTS` would become a dead test double for
# the rest of the session, silently disabling the redirect refusal that keeps the publish bearer
# away from the Cloudflare Access login host. Measured: it does exactly that. Importing before
# any fixture runs closes the window, and `test_the_real_opener_survived_the_fakes` pins it.
import publish_doc  # noqa: E402,F401

ENV_VARS = ("DESIGN_DOC_PUBLISH_CONFIG", "DESIGN_DOC_PUBLISH_WORKSPACE_FILE",
            "XDG_CONFIG_HOME", "DOC_HARNESS_CONTROL_URL", "DOC_HARNESS_PUBLISH_TOKEN",
            "DOC_HARNESS_PUBLIC_BASE", "CF_ACCESS_CLIENT_ID", "CF_ACCESS_CLIENT_SECRET")

CONTROL = "http://127.0.0.1:18081"
TOKEN = "test-bearer"

#: What the read-back route answers for an ABSENT name (contract C9): 200 with a null id.
CONTRACT_BODY = json.dumps({"name": "setup-readiness-probe", "active_deployment_id": None,
                            "commit_sha": None, "published_at": None}).encode("utf-8")


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


class _Resp:
    def __init__(self, body):
        self._body = io.BytesIO(body)

    def read(self, n=None):
        return self._body.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeOpener:
    """What a patched `build_opener` returns: something with `.open`, which is the fake."""

    def __init__(self, fake):
        self.open = fake


class FakeHarness:
    """Stands in for the control API. Records every URL so the tests can assert what was
    asked, and — the property that matters — that the probe only ever GETs."""

    def __init__(self, *, body=CONTRACT_BODY, status=None, raises=None):
        self.body = body
        self.status = status          # an HTTP error code, or None for 200
        self.raises = raises
        self.calls = []
        self.handlers = ()

    def install(self, monkeypatch):
        monkeypatch.setattr(urllib.request, "urlopen", self)
        # Since #54 the probe goes through an opener with the redirect handler neutered, so
        # patching `urlopen` alone would stop intercepting and every status test would attempt a
        # real network call. `build_opener` hands back this same fake, and records the handlers
        # it was given so a test can assert the redirect refusal directly.
        monkeypatch.setattr(urllib.request, "build_opener", self._build_opener)
        return self

    def _build_opener(self, *handlers):
        self.handlers = handlers
        return _FakeOpener(self)

    def __call__(self, req, timeout=None):
        self.calls.append((req.get_method(), req.full_url, dict(req.headers)))
        if self.raises:
            raise self.raises
        if self.status:
            raise urllib.error.HTTPError(req.full_url, self.status, "refused", {}, None)
        return _Resp(self.body)


def _env(**extra):
    base = {"DOC_HARNESS_CONTROL_URL": CONTROL, "DOC_HARNESS_PUBLISH_TOKEN": TOKEN}
    base.update(extra)
    return {k: v for k, v in base.items() if v is not None}


def _status(monkeypatch, fake, cfg, env=None, **kw):
    fake.install(monkeypatch)
    return setup_mod.status(config_path=cfg, env=env if env is not None else _env(), **kw)


def _ready_files(cfg, tmp_path, projects=({"name": "widget"},)):
    ws = _write(tmp_path / "ws.json", {"version": 1, "projects": list(projects)})
    _write(cfg, {"version": 1, "workspace_file": str(ws)})
    return ws


# --------------------------------------------------------------------- the state table

class TestTheStateTable:
    def test_nothing_configured(self, monkeypatch, cfg):
        s = _status(monkeypatch, FakeHarness(), cfg)
        assert s["status"] == "needs_config"
        assert s["can_proceed"] is False
        assert s["project_count"] is None
        assert setup_mod.exit_code(s) == 4

    def test_a_workspace_but_no_harness_env(self, monkeypatch, cfg, tmp_path):
        _ready_files(cfg, tmp_path)
        s = _status(monkeypatch, FakeHarness(), cfg, env={})
        assert s["status"] == "needs_harness_env"
        assert s["can_proceed"] is False
        assert setup_mod.exit_code(s) == 2

    def test_a_public_base_without_the_access_pair(self, monkeypatch, cfg, tmp_path):
        _ready_files(cfg, tmp_path)
        s = _status(monkeypatch, FakeHarness(), cfg,
                    env=_env(DOC_HARNESS_PUBLIC_BASE="https://x.example"))
        assert s["status"] == "edge_env_incomplete"
        assert setup_mod.exit_code(s) == 2

    def test_a_public_base_with_the_whole_pair_is_fine(self, monkeypatch, cfg, tmp_path):
        _ready_files(cfg, tmp_path)
        s = _status(monkeypatch, FakeHarness(), cfg,
                    env=_env(DOC_HARNESS_PUBLIC_BASE="https://x.example",
                             CF_ACCESS_CLIENT_ID="i", CF_ACCESS_CLIENT_SECRET="s"))
        assert s["status"] == "ready"

    def test_a_probe_that_could_not_run_is_not_a_denial(self, monkeypatch, cfg, tmp_path):
        """The distinction that keeps a network blip from telling someone to rotate a
        credential they already hold."""
        _ready_files(cfg, tmp_path)
        s = _status(monkeypatch, FakeHarness(raises=OSError("refused")), cfg)
        assert s["status"] == "harness_unreachable"
        assert s["harness_reachable"] is False
        assert setup_mod.exit_code(s) == 5

    def test_garbage_from_the_endpoint_is_unreachable_not_denied(self, monkeypatch, cfg,
                                                                 tmp_path):
        """A non-JSON answer means this is not the control API, which says nothing about
        the credential."""
        _ready_files(cfg, tmp_path)
        s = _status(monkeypatch, FakeHarness(body=b"<html>a login page</html>"), cfg)
        assert s["status"] == "harness_unreachable"
        assert setup_mod.exit_code(s) == 5

    def test_a_contract_without_its_fields_is_unreachable_too(self, monkeypatch, cfg,
                                                              tmp_path):
        """JSON alone is not the contract: an answer missing `active_deployment_id` is some
        other service, and treating it as ready would fail at stage 5 instead."""
        _ready_files(cfg, tmp_path)
        s = _status(monkeypatch, FakeHarness(body=b'{"ok": true}'), cfg)
        assert s["status"] == "harness_unreachable"

    def test_a_401_is_a_denial(self, monkeypatch, cfg, tmp_path):
        _ready_files(cfg, tmp_path)
        s = _status(monkeypatch, FakeHarness(status=401), cfg)
        assert s["status"] == "harness_denied"
        assert s["harness_reachable"] is False
        assert setup_mod.exit_code(s) == 3

    def test_a_configured_workspace_that_is_gone(self, monkeypatch, cfg, tmp_path):
        _write(cfg, {"version": 1, "workspace_file": str(tmp_path / "gone.json")})
        s = _status(monkeypatch, FakeHarness(), cfg)
        assert s["status"] == "workspace_missing"
        assert s["project_count"] is None
        assert setup_mod.exit_code(s) == 4

    def test_a_zero_byte_workspace_is_malformed_not_empty(self, monkeypatch, cfg, tmp_path):
        """Zero bytes is not valid JSON, so it is a malformed file rather than an empty
        project list — the two get different answers on purpose."""
        ws = tmp_path / "ws.json"
        ws.write_text("", encoding="utf-8")
        _write(cfg, {"version": 1, "workspace_file": str(ws)})
        s = _status(monkeypatch, FakeHarness(), cfg)
        assert s["status"] == "workspace_malformed"
        assert setup_mod.exit_code(s) == 4

    def test_an_empty_project_list_can_still_proceed(self, monkeypatch, cfg, tmp_path):
        """The row that proves `status` and `can_proceed` are different questions: the
        literal `workspace` bucket publishes without any registered project."""
        _ready_files(cfg, tmp_path, projects=())
        s = _status(monkeypatch, FakeHarness(), cfg)
        assert s["status"] == "ready_no_projects"
        assert s["can_proceed"] is True
        assert s["project_count"] == 0
        assert setup_mod.exit_code(s) == 0

    def test_fully_configured(self, monkeypatch, cfg, tmp_path):
        _ready_files(cfg, tmp_path, projects=({"name": "widget"}, {"name": "gadget"}))
        s = _status(monkeypatch, FakeHarness(), cfg)
        assert s["status"] == "ready"
        assert s["can_proceed"] is True
        assert s["project_count"] == 2
        assert s["harness_reachable"] is True
        assert setup_mod.exit_code(s) == 0

    def test_an_unknown_config_version_is_reported_not_raised(self, monkeypatch, cfg):
        _write(cfg, {"version": 99})
        s = _status(monkeypatch, FakeHarness(), cfg)
        assert s["status"] == "config_version_unsupported"
        assert setup_mod.exit_code(s) == 4

    def test_first_run_is_about_the_config_file_alone(self, monkeypatch, cfg):
        assert _status(monkeypatch, FakeHarness(), cfg)["first_run"] is True
        _write(cfg, {"version": 1})
        assert _status(monkeypatch, FakeHarness(), cfg)["first_run"] is False


class TestTheProbeItself:
    def test_it_only_ever_GETs(self, monkeypatch, cfg, tmp_path):
        """READ-ONLY is the probe's contract: it must prove the URL and the bearer without
        being able to publish anything, ever."""
        _ready_files(cfg, tmp_path)
        fake = FakeHarness()
        _status(monkeypatch, fake, cfg)
        assert fake.calls, "the probe never ran"
        for method, url, headers in fake.calls:
            assert method == "GET"

    def test_it_asks_the_read_back_route_with_the_bearer(self, monkeypatch, cfg, tmp_path):
        _ready_files(cfg, tmp_path)
        fake = FakeHarness()
        _status(monkeypatch, fake, cfg)
        method, url, headers = fake.calls[0]
        assert url.startswith(CONTROL + "/v1/deployments/")
        assert headers.get("Authorization") == "Bearer " + TOKEN

    def test_a_loopback_probe_names_the_control_host(self, monkeypatch, cfg, tmp_path):
        """The harness routes on the HOST header, so `Host: 127.0.0.1` is refused by the
        zone check and a working harness would read as unreachable."""
        _ready_files(cfg, tmp_path)
        fake = FakeHarness()
        _status(monkeypatch, fake, cfg)
        _, _, headers = fake.calls[0]
        assert headers.get("Host") == "docs-control.3dstories.ca"

    def test_no_env_means_no_call_at_all(self, monkeypatch, cfg, tmp_path):
        _ready_files(cfg, tmp_path)
        fake = FakeHarness()
        _status(monkeypatch, fake, cfg, env={})
        assert fake.calls == []


# ------------------------------------------------------------------------ the surfaces

class TestTheJsonMode:
    def test_it_emits_the_names_the_criterion_asks_for(self, monkeypatch, cfg, capsys):
        FakeHarness().install(monkeypatch)
        rc = setup_mod.main(["--json", "--config", str(cfg)])
        assert rc == 0, "--json always exits 0; it reports rather than gates"
        payload = json.loads(capsys.readouterr().out)
        for key in ("status", "can_proceed", "first_run"):
            assert key in payload
        for key in ("config_file", "workspace_file", "project_count",
                    "harness_control_url", "publish_token_set", "public_base_set",
                    "edge_credentials_set", "harness_reachable"):
            assert key in payload

    def test_it_never_prints_the_token_value(self, monkeypatch, cfg, capsys, tmp_path):
        """The report says `set`, never the value: a status object is something people
        paste."""
        _ready_files(cfg, tmp_path)
        monkeypatch.setenv("DOC_HARNESS_CONTROL_URL", CONTROL)
        monkeypatch.setenv("DOC_HARNESS_PUBLISH_TOKEN", "tok_abc123_secret")
        FakeHarness().install(monkeypatch)
        setup_mod.main(["--json", "--config", str(cfg)])
        assert "tok_abc123_secret" not in capsys.readouterr().out
        setup_mod.main(["--config", str(cfg)])
        assert "tok_abc123_secret" not in capsys.readouterr().out


class TestTheCheckMode:
    def test_it_is_silent_when_everything_is_ready(self, monkeypatch, cfg, capsys, tmp_path):
        _ready_files(cfg, tmp_path)
        monkeypatch.setenv("DOC_HARNESS_CONTROL_URL", CONTROL)
        monkeypatch.setenv("DOC_HARNESS_PUBLISH_TOKEN", TOKEN)
        FakeHarness().install(monkeypatch)
        rc = setup_mod.main(["--check", "--config", str(cfg)])
        captured = capsys.readouterr()
        assert rc == 0
        assert captured.out == "" and captured.err == ""

    def test_it_prints_one_actionable_line_otherwise(self, monkeypatch, cfg, capsys):
        FakeHarness().install(monkeypatch)
        rc = setup_mod.main(["--check", "--config", str(cfg)])
        err = capsys.readouterr().err
        assert rc == 4
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
    def test_it_creates_one_and_records_that_we_own_it(self, cfg, tmp_path):
        target = tmp_path / "mine.json"
        rc = setup_mod.main(["--init-workspace", str(target), "--config", str(cfg)])
        assert rc == 0
        assert json.loads(target.read_text(encoding="utf-8")) == {"version": 1, "projects": []}
        stored = json.loads(cfg.read_text(encoding="utf-8"))
        assert stored["workspace_file"] == str(target)
        assert stored["owned_workspace_file"] == str(target)

    def test_it_refuses_to_overwrite_an_existing_file(self, cfg, tmp_path):
        target = _write(tmp_path / "already.json", {"version": 1, "projects": [{"name": "x"}]})
        rc = setup_mod.main(["--init-workspace", str(target), "--config", str(cfg)])
        assert rc != 0
        assert json.loads(target.read_text(encoding="utf-8"))["projects"] == [{"name": "x"}]

    def test_without_a_path_it_lands_beside_the_config(self, cfg, tmp_path):
        setup_mod.main(["--init-workspace", "--config", str(cfg)])
        stored = json.loads(cfg.read_text(encoding="utf-8"))
        assert Path(stored["workspace_file"]).parent == cfg.parent


class TestSetWorkspace:
    def test_it_stores_an_absolute_normalized_path(self, cfg, tmp_path):
        """Storing what the user typed would make resolution depend on whichever directory a
        later publish ran from, turning a configured workspace into a missing one."""
        _write(tmp_path / "ws.json", {"version": 1, "projects": []})
        rc = setup_mod.main(["--set-workspace", "ws.json", "--config", str(cfg)])
        assert rc == 0
        stored = json.loads(cfg.read_text(encoding="utf-8"))["workspace_file"]
        assert Path(stored).is_absolute()
        assert Path(stored) == tmp_path / "ws.json"

    def test_adopting_does_not_claim_ownership(self, cfg, tmp_path):
        ws = _write(tmp_path / "theirs.json", {"version": 1, "projects": []})
        setup_mod.main(["--set-workspace", str(ws), "--config", str(cfg)])
        assert "owned_workspace_file" not in json.loads(cfg.read_text(encoding="utf-8"))

    def test_it_refuses_a_path_that_is_not_there(self, cfg, tmp_path):
        rc = setup_mod.main(["--set-workspace", str(tmp_path / "nope.json"),
                             "--config", str(cfg)])
        assert rc != 0


class TestAddProject:
    def _owned(self, cfg, tmp_path):
        setup_mod.main(["--init-workspace", str(tmp_path / "mine.json"),
                        "--config", str(cfg)])
        return tmp_path / "mine.json"

    def test_it_adds_a_name(self, cfg, tmp_path):
        ws = self._owned(cfg, tmp_path)
        assert setup_mod.main(["--add-project", "payments-api", "--config", str(cfg)]) == 0
        assert json.loads(ws.read_text(encoding="utf-8"))["projects"] == [
            {"name": "payments-api"}]

    def test_adding_the_same_name_twice_is_idempotent(self, cfg, tmp_path):
        ws = self._owned(cfg, tmp_path)
        setup_mod.main(["--add-project", "payments-api", "--config", str(cfg)])
        assert setup_mod.main(["--add-project", "payments-api", "--config", str(cfg)]) == 0
        assert json.loads(ws.read_text(encoding="utf-8"))["projects"] == [
            {"name": "payments-api"}]

    def test_it_preserves_unknown_fields_and_existing_entries(self, cfg, tmp_path):
        ws = self._owned(cfg, tmp_path)
        data = json.loads(ws.read_text(encoding="utf-8"))
        data["projects"] = [{"name": "old", "path": "./old", "extra": 1}]
        data["somethingElse"] = {"keep": True}
        ws.write_text(json.dumps(data), encoding="utf-8")
        setup_mod.main(["--add-project", "new", "--config", str(cfg)])
        after = json.loads(ws.read_text(encoding="utf-8"))
        assert after["somethingElse"] == {"keep": True}
        assert {"name": "old", "path": "./old", "extra": 1} in after["projects"]
        assert {"name": "new"} in after["projects"]

    def test_it_REFUSES_a_workspace_this_package_did_not_create(self, cfg, tmp_path, capsys):
        """The important one. The resolved workspace can be another tool's file, read by
        every concurrent session on the machine — writing there is out of the question."""
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
        ws = self._owned(cfg, tmp_path)
        elsewhere = _write(tmp_path / "elsewhere.json", {"version": 1, "projects": []})
        before = elsewhere.read_text(encoding="utf-8")
        monkeypatch.setenv("DESIGN_DOC_PUBLISH_WORKSPACE_FILE", str(elsewhere))
        rc = setup_mod.main(["--add-project", "widget", "--config", str(cfg)])
        assert rc != 0, "an override moved resolution off the owned file; it must refuse"
        assert elsewhere.read_text(encoding="utf-8") == before
        assert json.loads(ws.read_text(encoding="utf-8"))["projects"] == []

    def test_it_refuses_a_name_that_is_not_a_slug(self, cfg, tmp_path):
        self._owned(cfg, tmp_path)
        assert setup_mod.main(["--add-project", "Not A Slug", "--config", str(cfg)]) != 0

    def test_an_option_like_value_cannot_become_a_name(self, cfg, tmp_path):
        self._owned(cfg, tmp_path)
        assert setup_mod.main(["--add-project=--sneaky", "--config", str(cfg)]) != 0

    def test_the_write_is_serialized(self):
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
    ])
    def test_an_unknown_config_version_is_a_sentence(self, cfg, tmp_path, capsys, args):
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
    def test_the_config_it_writes_holds_no_credential(self, cfg, tmp_path):
        setup_mod.main(["--init-workspace", str(tmp_path / "m.json"), "--config", str(cfg)])
        stored = json.loads(cfg.read_text(encoding="utf-8"))
        assert set(stored) <= {"version", "workspace_file", "owned_workspace_file"}

    def test_nothing_here_shells_out_at_all(self):
        """The old setup drove a vendor CLI. The new one has nothing to drive: its one
        network touch is the read-only urllib probe, so any subprocess use is a regression."""
        import inspect
        source = inspect.getsource(setup_mod)
        assert "subprocess" not in source


class TestTheStepEightAFindings:
    """Findings from the Step-8a cross-model review, each reproduced before it was fixed.

    They share a shape worth naming: every one is a place where the code was LENIENT about
    input in a context that mutates something. Leniency is right for reporting and wrong for
    writing, and the split had not been drawn.
    """

    def test_a_malformed_config_is_never_overwritten_by_a_setter(self, cfg, tmp_path,
                                                                 capsys):
        """`load()` reads a malformed config as absent so that STATUS can still report. A
        setter then merged into that empty mapping and atomically replaced the file, which
        destroyed whatever was recoverable in it."""
        cfg.parent.mkdir(parents=True, exist_ok=True)
        original = '{"version": 1, "workspace_file": "x"  <-- hand-edited badly'
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
        _write(cfg, {"version": 1, "workspace_file": str(ws)})
        s = _status(monkeypatch, FakeHarness(), cfg)
        assert s["status"] == "workspace_malformed"
        assert s["can_proceed"] is False

    def test_the_publisher_agrees_that_it_is_malformed(self, tmp_path):
        """The two must not disagree: setup saying ready while publish refuses is the
        confusion this closes."""
        ws = _write(tmp_path / "ws.json", {"version": 1})
        cfg = _write(tmp_path / "config.json", {"version": 1, "workspace_file": str(ws)})
        with pytest.raises(user_config.ConfigError) as excinfo:
            user_config.require_workspace_file(config_path=cfg)
        assert "malformed" in str(excinfo.value).lower()

    def test_init_workspace_leaves_nothing_behind_when_it_cannot_record(self, monkeypatch,
                                                                        cfg, tmp_path):
        """A created-but-unrecorded workspace is a file the user did not ask for and this
        tool will not use."""
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


class TestTheStateTableOrderIsTheDocumentedOne:
    """The design states an ORDER — `status` is the FIRST actionable fault — precisely so
    that coexisting problems have one defined answer. A table nobody follows is not a
    contract."""

    def test_a_missing_workspace_outranks_missing_harness_env(self, monkeypatch, cfg,
                                                              tmp_path):
        _write(cfg, {"version": 1, "workspace_file": str(tmp_path / "gone.json")})
        s = _status(monkeypatch, FakeHarness(), cfg, env={})
        assert s["status"] == "workspace_missing", (
            "the workspace rows come before the environment rows")

    def test_missing_env_outranks_an_unreachable_harness(self, monkeypatch, cfg, tmp_path):
        """With no env there is nothing to probe, so the report names the env and the probe
        never runs — proven by the fake recording zero calls."""
        _ready_files(cfg, tmp_path)
        fake = FakeHarness(raises=OSError("never called anyway"))
        s = _status(monkeypatch, fake, cfg, env={})
        assert s["status"] == "needs_harness_env"
        assert fake.calls == []

    def test_an_unknown_config_version_still_outranks_everything(self, monkeypatch, cfg):
        _write(cfg, {"version": 99})
        s = _status(monkeypatch, FakeHarness(raises=OSError("nope")), cfg, env={})
        assert s["status"] == "config_version_unsupported", "row 1 is row 1"


class TestTheStepElevenFindings:
    """Findings from the Step-11 cross-model review, each verified against the code first."""

    def test_the_lock_refuses_to_write_through_a_symlink(self, cfg, tmp_path):
        """`open(path, "w")` follows a symlink and TRUNCATES the destination before any lock
        is taken, so a pre-created `.lock` symlink in a writable directory could destroy any
        file the invoking user can write."""
        ws = tmp_path / "mine.json"
        setup_mod.main(["--init-workspace", str(ws), "--config", str(cfg)])

        victim = tmp_path / "precious.txt"
        victim.write_text("do not truncate me", encoding="utf-8")
        lock = Path(str(ws) + ".lock")
        lock.symlink_to(victim)

        rc = setup_mod.main(["--add-project", "widget", "--config", str(cfg)])
        assert rc != 0, "a symlinked lock must be refused, not followed"
        assert victim.read_text(encoding="utf-8") == "do not truncate me"

    def test_a_normal_lock_still_works(self, cfg, tmp_path):
        """The counterpart, so the hardening does not simply break locking."""
        ws = tmp_path / "mine.json"
        setup_mod.main(["--init-workspace", str(ws), "--config", str(cfg)])
        assert setup_mod.main(["--add-project", "widget", "--config", str(cfg)]) == 0
        assert Path(str(ws) + ".lock").is_file()

    def test_adopting_a_workspace_clears_a_previous_ownership_claim(self, cfg, tmp_path):
        """Leaving the old record intact is not the same as clearing it: a previously owned
        path stays authorized, so re-adopting it after it has been replaced by someone else's
        file would let --add-project write to that file."""
        mine = tmp_path / "mine.json"
        setup_mod.main(["--init-workspace", str(mine), "--config", str(cfg)])
        assert json.loads(cfg.read_text(encoding="utf-8"))["owned_workspace_file"] == str(mine)

        theirs = _write(tmp_path / "theirs.json", {"version": 1, "projects": []})
        setup_mod.main(["--set-workspace", str(theirs), "--config", str(cfg)])
        stored = json.loads(cfg.read_text(encoding="utf-8"))
        assert "owned_workspace_file" not in stored, "adoption must clear the claim"

        # And the dangerous sequence itself: the old path is no longer authorized.
        mine.write_text(json.dumps({"version": 1, "projects": []}), encoding="utf-8")
        setup_mod.main(["--set-workspace", str(mine), "--config", str(cfg)])
        assert setup_mod.main(["--add-project", "widget", "--config", str(cfg)]) != 0

    def test_the_config_write_is_serialized_too(self):
        """Two setters run one after another in the documentation. Run concurrently they
        could both read the old config and the later writer would erase the other's
        setting."""
        import inspect
        source = inspect.getsource(setup_mod._store)
        assert "_locked(" in source, "the config read-modify-write must hold the lock too"

    def test_a_none_update_removes_the_key_rather_than_storing_null(self, cfg, tmp_path):
        setup_mod.main(["--init-workspace", str(tmp_path / "m.json"), "--config", str(cfg)])
        setup_mod._store(cfg, owned_workspace_file=None)
        assert "owned_workspace_file" not in json.loads(cfg.read_text(encoding="utf-8"))

    def test_locking_is_declared_posix_only_rather_than_crashing_on_import(self):
        """`fcntl` does not exist on Windows. Imported at module level it would raise before
        argument parsing, so the one command a stranger runs first would traceback instead of
        telling them anything."""
        import inspect
        source = inspect.getsource(setup_mod)
        assert "except ImportError" in source
        assert "fcntl = None" in source

    def test_a_platformless_host_refuses_instead_of_tracebacking(self, monkeypatch, cfg,
                                                                 tmp_path, capsys):
        setup_mod.main(["--init-workspace", str(tmp_path / "m.json"), "--config", str(cfg)])
        monkeypatch.setattr(setup_mod, "fcntl", None)
        rc = setup_mod.main(["--add-project", "widget", "--config", str(cfg)])
        assert rc != 0
        err = capsys.readouterr().err
        assert "POSIX" in err
        assert "Traceback" not in err


# --------------------------------------------------------------------------------- #54

EDGE_CONTROL = "https://docs-control.3dstories.ca"


class TestTheProbeThroughTheEdge:
    """Issue #54. The readiness probe is a CONTROL CALL, so everything the publisher's control
    calls must do, it must do: carry the Cloudflare Access pair when the destination is behind
    Access, and never follow a redirect while holding the publish bearer."""

    def test_a_loopback_probe_is_unchanged(self, monkeypatch):
        """AC3. The pair is a TLS-only credential: holding it in the environment must not put it
        on a plaintext loopback request."""
        h = FakeHarness().install(monkeypatch)
        setup_mod.probe_harness(CONTROL, TOKEN, env={"CF_ACCESS_CLIENT_ID": "i",
                                                     "CF_ACCESS_CLIENT_SECRET": "s"})
        _method, _url, headers = h.calls[0]
        assert headers.get("Host") == "docs-control.3dstories.ca"
        assert "Cf-access-client-id" not in headers
        assert "Cf-access-client-secret" not in headers

    def test_an_edge_probe_carries_the_access_pair_beside_the_bearer(self, monkeypatch):
        h = FakeHarness().install(monkeypatch)
        outcome, _detail = setup_mod.probe_harness(
            EDGE_CONTROL, TOKEN,
            env={"CF_ACCESS_CLIENT_ID": "cid-value", "CF_ACCESS_CLIENT_SECRET": "secret-value"})
        assert outcome == "ok"
        _method, _url, headers = h.calls[0]
        assert headers["Cf-access-client-id"] == "cid-value"
        assert headers["Cf-access-client-secret"] == "secret-value"
        assert headers["Authorization"] == "Bearer " + TOKEN
        # Over TLS the URL already carries the right name; an override would mask a mismatch.
        assert "Host" not in headers

    def test_an_edge_probe_with_neither_half_sends_nothing_and_names_both(self, monkeypatch):
        h = FakeHarness().install(monkeypatch)
        outcome, detail = setup_mod.probe_harness(EDGE_CONTROL, TOKEN, env={})
        # `incomplete` since #54 follow-up 3 — see
        # TestALocalCredentialRefusalIsNotAnUnreachableHarness. What this test pins is unchanged:
        # nothing is sent, and both variables are named.
        assert outcome == "incomplete"
        assert h.calls == [], "a credential-incomplete probe must not reach the network"
        assert "CF_ACCESS_CLIENT_ID" in detail and "CF_ACCESS_CLIENT_SECRET" in detail

    @pytest.mark.parametrize("env,missing", [
        ({"CF_ACCESS_CLIENT_ID": "i"}, "CF_ACCESS_CLIENT_SECRET"),
        ({"CF_ACCESS_CLIENT_SECRET": "s"}, "CF_ACCESS_CLIENT_ID"),
        ({"CF_ACCESS_CLIENT_ID": "  ", "CF_ACCESS_CLIENT_SECRET": "s"}, "CF_ACCESS_CLIENT_ID"),
    ])
    def test_an_edge_probe_with_half_the_pair_names_the_MISSING_half(self, monkeypatch, env,
                                                                     missing):
        """AC2 asks for the variable to be named. Naming both when one is already set sends
        somebody to check a value they have. The publisher's reader is shared here precisely so
        this message is the same sharp one on both paths."""
        h = FakeHarness().install(monkeypatch)
        outcome, detail = setup_mod.probe_harness(EDGE_CONTROL, TOKEN, env=env)
        assert outcome == "incomplete"      # `failed` before #54 follow-up 3
        assert h.calls == [], "a credential-incomplete probe must not reach the network"
        assert missing in detail

    def test_no_probe_refusal_prints_a_credential_value(self, monkeypatch):
        FakeHarness().install(monkeypatch)
        _outcome, detail = setup_mod.probe_harness(
            EDGE_CONTROL, TOKEN, env={"CF_ACCESS_CLIENT_ID": "SUPERSECRETVALUE"})
        assert "SUPERSECRETVALUE" not in detail

    def test_the_probe_opener_refuses_redirects(self, monkeypatch):
        """Measured 2026-08-25 on CPython 3.12.3: `urllib.request.urlopen` forwards BOTH
        `Authorization` and `CF-Access-Client-Id` across a cross-host 302. Cloudflare Access
        answers exactly such a redirect, so following one hands the publish bearer to the login
        host. The handler is asserted directly rather than through an outcome, because the
        outcome is the same whether the redirect was refused or merely failed later."""
        h = FakeHarness().install(monkeypatch)
        setup_mod.probe_harness(CONTROL, TOKEN, env={})
        assert h.handlers, "the probe must build its own opener, not call urlopen"
        redirectors = [x for x in h.handlers if hasattr(x, "redirect_request")]
        assert redirectors, "no redirect handler was passed to build_opener"
        assert all(r.redirect_request(None, None, 302, "Found", {}, EDGE_CONTROL) is None
                   for r in redirectors)

    def test_a_redirect_answer_is_reported_as_a_failed_probe_not_a_denial(self, monkeypatch):
        """A 302 is the Access login. It is not a token refusal, and telling someone their
        bearer was denied sends them to rotate a credential they already hold."""
        _status_h = FakeHarness(status=302).install(monkeypatch)
        outcome, detail = setup_mod.probe_harness(CONTROL, TOKEN, env={})
        assert outcome == "failed"
        assert "302" in detail


class TestAnEdgeControlUrlNeedsThePairToo:
    """Issue #54. Before this, an edge control URL with no Access pair reported `ready` — and
    then every publish from that machine failed on a login redirect. The readiness answer has to
    know about the same requirement the publisher enforces."""

    def test_an_edge_control_url_without_the_pair_is_incomplete(self, monkeypatch, cfg, tmp_path):
        _ready_files(cfg, tmp_path)
        s = _status(monkeypatch, FakeHarness(), cfg,
                    env=_env(DOC_HARNESS_CONTROL_URL=EDGE_CONTROL))
        assert s["status"] == "edge_env_incomplete"
        assert s["can_proceed"] is False
        assert setup_mod.exit_code(s) == 2

    @pytest.mark.parametrize("half", ["CF_ACCESS_CLIENT_ID", "CF_ACCESS_CLIENT_SECRET"])
    def test_an_edge_control_url_with_half_the_pair_is_incomplete(self, monkeypatch, cfg,
                                                                  tmp_path, half):
        _ready_files(cfg, tmp_path)
        s = _status(monkeypatch, FakeHarness(), cfg,
                    env=_env(DOC_HARNESS_CONTROL_URL=EDGE_CONTROL, **{half: "x"}))
        assert s["status"] == "edge_env_incomplete"

    def test_an_edge_control_url_with_the_whole_pair_is_ready(self, monkeypatch, cfg, tmp_path):
        _ready_files(cfg, tmp_path)
        s = _status(monkeypatch, FakeHarness(), cfg,
                    env=_env(DOC_HARNESS_CONTROL_URL=EDGE_CONTROL,
                             CF_ACCESS_CLIENT_ID="i", CF_ACCESS_CLIENT_SECRET="s"))
        assert s["status"] == "ready"

    def test_a_loopback_control_url_without_the_pair_is_still_ready(self, monkeypatch, cfg,
                                                                    tmp_path):
        """The non-regression that matters: the pair is required by the DESTINATION, not by
        publishing in general. Requiring it on loopback would break the harness host itself."""
        _ready_files(cfg, tmp_path)
        s = _status(monkeypatch, FakeHarness(), cfg, env=_env())
        assert s["status"] == "ready"

    def test_the_advice_names_both_triggers(self):
        advice = setup_mod._ADVICE["edge_env_incomplete"]
        assert "DOC_HARNESS_PUBLIC_BASE" in advice
        assert "DOC_HARNESS_CONTROL_URL" in advice
        assert "CF_ACCESS_CLIENT_ID" in advice and "CF_ACCESS_CLIENT_SECRET" in advice


class TestTheProbeNeverSendsTheBearerOffTheAllowlist:
    """Step 8a finding F1, Critical, raised by the cross-model pass.

    `probe_harness` attaches the publish bearer and validated NOTHING about where it went, so
    whatever host `DOC_HARNESS_CONTROL_URL` named received the token. `publish_doc` fixed this
    class for the publisher in finding N4; this module never got it. Criterion 3 of #54 says no
    bearer reaches a destination outside `assert_bearer_destination`'s allowlist, and the probe
    is a bearer-carrying request like any other.

    The allowlist is IMPORTED from `publish_doc`, not copied: two copies drift, and the copy
    that drifts is the one that lets a credential out."""

    @pytest.mark.parametrize("bad", [
        "https://evil.example",                       # any https host is not sufficient
        "https://docs-control.3dstories.ca.evil.com",  # the pinned host as a prefix
        "http://10.0.0.5:8080",                       # a corporate LAN; removed by finding R2
        "http://192.168.1.9:8080",                    # likewise
        "http://172.17.0.2:8080",                     # the bridge, with NO explicit grant
        "http://example.com",                         # plaintext, not loopback
    ])
    def test_an_off_allowlist_destination_sends_nothing(self, monkeypatch, bad):
        h = FakeHarness().install(monkeypatch)
        outcome, detail = setup_mod.probe_harness(bad, TOKEN, env={})
        assert outcome == "failed"
        assert h.calls == [], "the publish bearer must not reach an unvalidated destination"
        assert detail

    @pytest.mark.parametrize("smuggled", [
        "https://docs-control.3dstories.ca/evil",
        "https://docs-control.3dstories.ca/?x=1",
        "https://docs-control.3dstories.ca/#f",
        "https://user:pw@docs-control.3dstories.ca",   # userinfo IS a credential in a URL
    ])
    def test_a_base_carrying_more_than_scheme_host_and_port_sends_nothing(self, monkeypatch,
                                                                          smuggled):
        h = FakeHarness().install(monkeypatch)
        outcome, _detail = setup_mod.probe_harness(
            smuggled, TOKEN,
            env={"CF_ACCESS_CLIENT_ID": "i", "CF_ACCESS_CLIENT_SECRET": "s"})
        assert outcome == "failed"
        assert h.calls == []

    def test_loopback_is_still_allowed(self, monkeypatch):
        h = FakeHarness().install(monkeypatch)
        outcome, _detail = setup_mod.probe_harness(CONTROL, TOKEN, env={})
        assert outcome == "ok"
        assert len(h.calls) == 1

    def test_the_bridge_is_allowed_only_with_its_explicit_grant(self, monkeypatch):
        h = FakeHarness().install(monkeypatch)
        outcome, _d = setup_mod.probe_harness(
            "http://172.17.0.2:8080", TOKEN,
            env={"DOC_HARNESS_ALLOW_BRIDGE_PLAINTEXT": "172.17.0.2:8080"})
        assert outcome == "ok"
        assert len(h.calls) == 1

    def test_the_edge_control_host_is_still_allowed(self, monkeypatch):
        h = FakeHarness().install(monkeypatch)
        outcome, _d = setup_mod.probe_harness(
            EDGE_CONTROL, TOKEN,
            env={"CF_ACCESS_CLIENT_ID": "i", "CF_ACCESS_CLIENT_SECRET": "s"})
        assert outcome == "ok"
        assert len(h.calls) == 1


class TestTheRedirectRefusalIsProvenAgainstARealSocket:
    """Step 8a finding I1, High, raised by the inline pass.

    The redirect refusal is the single control between the publish bearer and the Cloudflare
    Access login host, and every test around it asserted something other than the behavior. The
    publisher's own `test_the_opener_never_follows_redirects_on_its_own` asserted
    `NO_REDIRECTS is not None`. This module's `test_the_probe_opener_refuses_redirects` patches
    `build_opener`, so it proves the handler it hands in refuses, never that a real
    `build_opener` honors the override.

    So this one uses real sockets on loopback. It is the only test here that does, and it earns
    it: what it proves is that a sentinel bearer does not arrive at a redirect target."""

    @staticmethod
    def _servers():
        """(url_of_redirector, list_that_records_what_the_target_received, stop_callable)."""
        import http.server
        import threading

        received = []

        class Target(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                received.append({k.lower(): v for k, v in self.headers.items()})
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"active_deployment_id": null}')

            def log_message(self, *a):
                pass

        target = http.server.HTTPServer(("127.0.0.1", 0), Target)
        target_port = target.server_address[1]

        class Redirector(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:%d/login" % target_port)
                self.end_headers()

            def log_message(self, *a):
                pass

        redirector = http.server.HTTPServer(("127.0.0.1", 0), Redirector)
        for srv in (target, redirector):
            threading.Thread(target=srv.serve_forever, daemon=True).start()

        def stop():
            for srv in (target, redirector):
                srv.shutdown()
                srv.server_close()

        return "http://127.0.0.1:%d" % redirector.server_address[1], received, stop

    def test_the_probe_does_not_deliver_the_bearer_to_a_redirect_target(self):
        url, received, stop = self._servers()
        try:
            outcome, detail = setup_mod.probe_harness(url, "SENTINEL-BEARER", env={})
        finally:
            stop()
        assert received == [], (
            "the redirect target received a request; the bearer followed the 302")
        assert outcome == "failed"
        assert "302" in detail

    def test_the_publisher_opener_does_not_follow_either(self):
        """The same construction, in the module that already relied on it."""
        import urllib.error
        import urllib.request

        url, received, stop = self._servers()
        req = urllib.request.Request(url + "/v1/deployments/x")
        req.add_header("Authorization", "Bearer SENTINEL-BEARER")
        try:
            with pytest.raises(urllib.error.HTTPError) as e:
                publish_doc.NO_REDIRECTS.open(req, timeout=5)
        finally:
            stop()
        assert e.value.code == 302
        assert received == [], "publish_doc.NO_REDIRECTS followed a redirect"

    def test_the_real_opener_survived_the_fakes(self):
        """A guard on the guard. If `publish_doc` is ever first imported inside a window where
        `urllib.request.build_opener` is patched, `NO_REDIRECTS` becomes a dead test double and
        every redirect test above passes vacuously. This asserts it is the real thing."""
        import urllib.request
        assert isinstance(publish_doc.NO_REDIRECTS, urllib.request.OpenerDirector), (
            "publish_doc.NO_REDIRECTS is %s, not a real opener — it was built while "
            "build_opener was patched" % type(publish_doc.NO_REDIRECTS).__name__)


class TestAMalformedControlUrlGetsASentenceNotATraceback:
    """Step 11 findings J1 (inline) and A1 (adversarial), both against code THIS change added.

    Before #54 `status` never parsed DOC_HARNESS_CONTROL_URL, so a malformed value reported an
    unreachable harness. The new edge gate parses it, and `urllib.parse.urlsplit` raises on some
    inputs — so `setup --check`, the tool people run when a machine is already broken, exited
    with a ValueError traceback. This module's docstring promises a sentence instead."""

    MALFORMED = "http://[::1"

    def test_status_returns_a_state_and_does_not_raise(self, monkeypatch, cfg, tmp_path):
        _ready_files(cfg, tmp_path)
        s = _status(monkeypatch, FakeHarness(), cfg,
                    env=_env(DOC_HARNESS_CONTROL_URL=self.MALFORMED))
        assert s["status"] in setup_mod._BY_NAME, "status must be a declared state"
        assert s["status"] == "harness_unreachable"
        assert s["detail"]

    def test_the_probe_returns_a_sentence_and_sends_nothing(self, monkeypatch):
        h = FakeHarness().install(monkeypatch)
        outcome, detail = setup_mod.probe_harness(self.MALFORMED, TOKEN, env={})
        assert outcome == "failed"
        assert h.calls == []
        assert detail and "DOC_HARNESS_CONTROL_URL" in detail

    def test_an_edge_host_carrying_a_path_is_not_reported_as_a_missing_pair(self, monkeypatch,
                                                                           cfg, tmp_path):
        """A1: the pair gate ran on the RAW url, so an invalid destination that merely LOOKED
        like the edge host was reported as `edge_env_incomplete`. Setting the pair would not have
        helped — the URL is the problem."""
        _ready_files(cfg, tmp_path)
        s = _status(monkeypatch, FakeHarness(), cfg,
                    env=_env(DOC_HARNESS_CONTROL_URL="https://docs-control.3dstories.ca/evil"))
        assert s["status"] != "edge_env_incomplete"
        assert s["status"] == "harness_unreachable"

    def test_a_well_formed_edge_url_without_the_pair_is_still_incomplete(self, monkeypatch, cfg,
                                                                        tmp_path):
        """The non-regression beside it: a VALID edge URL with no pair must still report the
        pair, not be swallowed by the new validation."""
        _ready_files(cfg, tmp_path)
        s = _status(monkeypatch, FakeHarness(), cfg,
                    env=_env(DOC_HARNESS_CONTROL_URL=EDGE_CONTROL))
        assert s["status"] == "edge_env_incomplete"


class TestADenialThroughTheEdgeNamesTheRightCredential:
    """Step 11 findings F1 and A2 — the same defect, found independently by both passes.

    Through the edge, Cloudflare Access answers 401/403 BEFORE the harness does. Reporting every
    one of those as a harness denial sends the operator to rotate the publish bearer when the
    Access pair is what was refused."""

    @pytest.mark.parametrize("code", [401, 403])
    def test_an_edge_denial_names_both_credentials(self, monkeypatch, code):
        FakeHarness(status=code).install(monkeypatch)
        outcome, detail = setup_mod.probe_harness(
            EDGE_CONTROL, TOKEN,
            env={"CF_ACCESS_CLIENT_ID": "i", "CF_ACCESS_CLIENT_SECRET": "s"})
        assert outcome == "denied"
        assert "CF_ACCESS_CLIENT_ID" in detail
        assert "DOC_HARNESS_PUBLISH_TOKEN" in detail

    @pytest.mark.parametrize("code", [401, 403])
    def test_a_loopback_denial_still_names_only_the_bearer(self, monkeypatch, code):
        """No Access layer stands in front of loopback, so there is nothing else it could be.
        Widening this message everywhere would make the accurate case vaguer."""
        FakeHarness(status=code).install(monkeypatch)
        outcome, detail = setup_mod.probe_harness(CONTROL, TOKEN, env={})
        assert outcome == "denied"
        assert "CF_ACCESS_CLIENT_ID" not in detail


class TestTheDocsDoNotSayBothOrNeither:
    """Step 11 finding F3/A3, raised by both cross-model passes.

    "Both or neither" reads as though omitting both is a valid configuration. For the public
    control host it is not: `_access_pair` refuses the neither-set case exactly as firmly as the
    half-set one. An off-host publisher following that phrasing would hit a stage-5 refusal the
    prerequisites table told them was fine.

    Pinned as a test rather than a one-time edit because the phrase reappeared in three files
    from one careless sentence, and prose has no other guard here."""

    ROOT = SCRIPTS.parent
    DOCS = ("README.md", "skills/setup/SKILL.md", "skills/design-doc-publish/SKILL.md")

    @pytest.mark.parametrize("rel", DOCS)
    def test_the_misleading_phrase_is_absent(self, rel):
        text = (self.ROOT / rel).read_text(encoding="utf-8").lower()
        assert "both or neither" not in text, (
            f"{rel} says 'both or neither', but omitting both is refused for the public "
            "control host")

    @pytest.mark.parametrize("rel", DOCS)
    def test_each_doc_still_names_both_variables(self, rel):
        text = (self.ROOT / rel).read_text(encoding="utf-8")
        assert "CF_ACCESS_CLIENT_ID" in text and "CF_ACCESS_CLIENT_SECRET" in text, (
            f"{rel} must still document both variables (AC4)")


class TestALocalCredentialRefusalIsNotAnUnreachableHarness:
    """#54 follow-up 3. `probe_harness` returned "failed" when it refused locally for an
    incomplete Access pair, and `status` maps "failed" to `harness_unreachable`, whose advice
    says the harness did not answer. Nothing was asked of it. `status` gates the pair earlier so
    only a direct caller could see this, but the outcome vocabulary was still wrong.

    A new OUTCOME rather than a new STATE, deliberately: "the pair is incomplete" is exactly
    `edge_env_incomplete`, which already exists. Adding a state would move the exit-code
    surface for a condition the table already names."""

    def test_the_probe_reports_an_incomplete_pair_as_incomplete(self, monkeypatch):
        h = FakeHarness().install(monkeypatch)
        outcome, detail = setup_mod.probe_harness(EDGE_CONTROL, TOKEN, env={})
        assert outcome == "incomplete", "a local credential refusal is not a failed probe"
        assert h.calls == []
        assert "CF_ACCESS_CLIENT_ID" in detail

    def test_status_maps_it_to_the_state_that_already_names_it(self, monkeypatch, cfg, tmp_path):
        """Reached by forcing the probe to answer `incomplete`, since `status` normally refuses
        the same condition one step earlier."""
        _ready_files(cfg, tmp_path)
        monkeypatch.setattr(setup_mod, "probe_harness",
                            lambda *a, **k: ("incomplete", "CF_ACCESS_CLIENT_SECRET is not set"))
        s = _status(monkeypatch, FakeHarness(), cfg,
                    env=_env(CF_ACCESS_CLIENT_ID="i", CF_ACCESS_CLIENT_SECRET="s"))
        assert s["status"] == "edge_env_incomplete"
        assert setup_mod.exit_code(s) == 2
        assert s["harness_reachable"] is not True

    def test_an_unreachable_harness_is_still_unreachable(self, monkeypatch, cfg, tmp_path):
        """The non-regression: a real connection failure keeps its own state and message."""
        _ready_files(cfg, tmp_path)
        s = _status(monkeypatch, FakeHarness(raises=OSError("refused")), cfg)
        assert s["status"] == "harness_unreachable"

    def test_a_refused_destination_is_still_a_failed_probe(self, monkeypatch):
        """Scope line: an off-allowlist destination genuinely is not reachable as configured, so
        it keeps `failed`. Only the CREDENTIAL refusal changed."""
        h = FakeHarness().install(monkeypatch)
        outcome, _d = setup_mod.probe_harness("https://evil.example", TOKEN, env={})
        assert outcome == "failed"
        assert h.calls == []
