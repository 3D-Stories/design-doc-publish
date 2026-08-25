"""AC6: a stranger's path, proven rather than assumed (#9, harness era since 5.0.0).

Design: `docs/planning/2026-08-10-9-first-run-setup-flow.md` (revision 3).

The acceptance criterion is "proven, not assumed", on a development machine that is the
opposite of a stranger's: it has the author's workspace file, a working harness environment,
and a config directory. A test that merely hides `~/rawgentic/.rawgentic_workspace.json`
while keeping the real XDG config and the real environment variables is not a first-run test —
it is the same machine with one file moved.

So these run in a SUBPROCESS against a constructed machine state:

* `HOME` and `XDG_CONFIG_HOME` under `tmp_path`;
* every `DESIGN_DOC_PUBLISH_*`, `DOC_HARNESS_*` and `CF_ACCESS_*` variable absent from the
  child environment;
* where a harness is needed, a REAL local HTTP server started by the test, answering the
  read-back contract — so the probe is proven over a real socket, not a monkeypatch.
"""
import http.server
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parent
ROOT = SCRIPTS.parent
SETUP = SCRIPTS / "setup.py"
PUBLISH = SCRIPTS / "publish_doc.py"

TOKEN = "stranger-bearer"


class _ControlStub(http.server.BaseHTTPRequestHandler):
    """The read-back route, over a real socket. 200 with the contract for the right bearer,
    401 otherwise — which is exactly the split setup's probe must tell apart."""

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer " + TOKEN:
            self.send_response(401)
            self.end_headers()
            return
        body = json.dumps({"name": "setup-readiness-probe", "active_deployment_id": None,
                           "commit_sha": None, "published_at": None}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def control_url():
    server = http.server.HTTPServer(("127.0.0.1", 0), _ControlStub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % server.server_port
    server.shutdown()


@pytest.fixture
def stranger(tmp_path):
    """A machine that has never run setup, with nothing configured at all."""
    home = tmp_path / "home"
    (home / ".config").mkdir(parents=True)

    env = {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "PATH": "/usr/bin:/bin",
        "LC_ALL": "C.UTF-8",
    }

    class Stranger:
        def __init__(self):
            self.home, self.env = home, env
            self.tmp = tmp_path

        def run(self, script, *args, **overrides):
            child = dict(self.env)
            child.update(overrides)
            return subprocess.run([sys.executable, str(script), *args],
                                  capture_output=True, text=True, cwd=str(self.tmp),
                                  env=child, check=False)

    return Stranger()


class TestSetupOnAMachineWithNothing:
    def test_it_reports_a_first_run_honestly_and_writes_nothing(self, stranger):
        proc = stranger.run(SETUP, "--json")
        assert proc.returncode == 0, proc.stderr
        state = json.loads(proc.stdout)
        assert state["first_run"] is True
        assert state["can_proceed"] is False
        assert state["status"] == "needs_config"
        assert not (stranger.home / ".config" / "design-doc-publish").exists(), (
            "reporting must not create anything")

    def test_the_config_it_names_is_outside_the_plugin_tree(self, stranger):
        """A plugin is installed into a versioned cache directory that is replaced on
        upgrade, so configuration written there is lost on the next release."""
        state = json.loads(stranger.run(SETUP, "--json").stdout)
        config = Path(state["config_file"])
        assert ROOT not in config.parents, f"{config} is inside the installed tree"
        assert str(config).startswith(str(stranger.home))

    def test_check_exits_non_zero_with_one_line(self, stranger):
        proc = stranger.run(SETUP, "--check")
        assert proc.returncode == 4, proc.stderr
        assert proc.stderr.count("\n") == 1
        assert proc.stdout == ""

    def test_a_workspace_alone_still_names_the_missing_environment(self, stranger):
        assert stranger.run(SETUP, "--init-workspace").returncode == 0
        state = json.loads(stranger.run(SETUP, "--json").stdout)
        assert state["status"] == "needs_harness_env"
        assert state["can_proceed"] is False

    def test_the_whole_flow_ends_ready(self, stranger, control_url):
        assert stranger.run(SETUP, "--init-workspace").returncode == 0
        assert stranger.run(SETUP, "--add-project", "payments-api").returncode == 0

        env = {"DOC_HARNESS_CONTROL_URL": control_url,
               "DOC_HARNESS_PUBLISH_TOKEN": TOKEN}
        state = json.loads(stranger.run(SETUP, "--json", **env).stdout)
        assert state["status"] == "ready"
        assert state["can_proceed"] is True
        assert state["project_count"] == 1
        assert state["first_run"] is False
        assert state["harness_reachable"] is True
        assert stranger.run(SETUP, "--check", **env).returncode == 0

    def test_a_wrong_bearer_is_a_denial_over_a_real_socket(self, stranger, control_url):
        stranger.run(SETUP, "--init-workspace")
        proc = stranger.run(SETUP, "--check",
                            DOC_HARNESS_CONTROL_URL=control_url,
                            DOC_HARNESS_PUBLISH_TOKEN="the-wrong-one")
        assert proc.returncode == 3, proc.stderr
        assert "bearer" in proc.stderr.lower() or "TOKEN" in proc.stderr

    def test_a_dead_endpoint_is_unreachable_not_a_denial(self, stranger):
        stranger.run(SETUP, "--init-workspace")
        proc = stranger.run(SETUP, "--check",
                            DOC_HARNESS_CONTROL_URL="http://127.0.0.1:9",  # discard port
                            DOC_HARNESS_PUBLISH_TOKEN=TOKEN)
        assert proc.returncode == 5, proc.stderr
        assert "bearer" not in proc.stderr.lower(), (
            "a connection failure must not read as a credential problem")

    def test_no_credential_is_ever_written(self, stranger, control_url):
        stranger.run(SETUP, "--init-workspace",
                     DOC_HARNESS_CONTROL_URL=control_url,
                     DOC_HARNESS_PUBLISH_TOKEN=TOKEN)
        config = stranger.home / ".config" / "design-doc-publish" / "config.json"
        stored = config.read_text(encoding="utf-8")
        assert TOKEN not in stored
        assert set(json.loads(stored)) <= {"version", "workspace_file",
                                           "owned_workspace_file"}


class TestPublishingBeforeSetup:
    """AC5, by the path a stranger takes: stage 2 precedes every network call, so this is
    fully hermetic and needs no harness at all."""

    def _doc(self, stranger):
        doc = stranger.tmp / "hello.md"
        doc.write_text(
            "## Heading\n\nSome body text.\n\n"
            "```callout\nwarn | Read this first\nOne real component.\n```\n\n"
            "```options\nDebounce | Smallest diff | Re-done per call site | chosen\n```\n",
            encoding="utf-8")
        return doc

    def test_it_refuses_legibly_and_names_what_to_run(self, stranger):
        doc = self._doc(stranger)
        proc = stranger.run(PUBLISH, "--md", str(doc), "--out", str(stranger.tmp / "o.html"),
                            "--project", "payments-api", "--type", "design", "--ref", "1",
                            "--title", "Payments rollout design")

        assert proc.returncode == 12, (
            f"stage 2 is where an unconfigured workspace stops, got {proc.returncode}\n"
            f"{proc.stderr}")
        assert "setup.py" in proc.stderr, "the refusal must name what to run"
        assert "Traceback" not in proc.stderr, "a stranger must never see a traceback"
        assert "rawgentic" not in proc.stderr.replace(str(ROOT), ""), (
            "the message must not name a path only the author has")

    def test_rendering_still_works_with_nothing_configured(self, stranger):
        """The shape that must not break: the README's first command needs no workspace, no
        harness and no network."""
        doc = stranger.tmp / "hello.md"
        doc.write_text("# Hello\n\nA first page.\n\n## A section\n\nSome prose.\n",
                       encoding="utf-8")
        out = stranger.tmp / "hello.html"
        proc = stranger.run(SCRIPTS / "render-doc", "--md", str(doc), "--out", str(out),
                            "--title", "Hello")
        assert proc.returncode == 0, proc.stderr
        assert out.is_file() and "<html" in out.read_text(encoding="utf-8")

    def test_after_setup_the_same_command_gets_past_stage_two(self, stranger):
        """The other half of the criterion: the refusal is not permanent, and following its
        instruction is what clears it."""
        stranger.run(SETUP, "--init-workspace")
        stranger.run(SETUP, "--add-project", "payments-api")

        doc = self._doc(stranger)
        proc = stranger.run(PUBLISH, "--md", str(doc), "--out", str(stranger.tmp / "o.html"),
                            "--project", "payments-api", "--type", "design", "--ref", "1",
                            "--title", "Payments rollout design", "--dry-run")
        assert proc.returncode == 0, proc.stderr
