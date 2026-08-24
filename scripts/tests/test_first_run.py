"""AC6: a stranger's path, proven rather than assumed (#9).

Design: `docs/planning/2026-08-10-9-first-run-setup-flow.md` (revision 3).

The acceptance criterion is "proven, not assumed", on a development machine that is the
opposite of a stranger's: it has the author's workspace file, an authenticated Vercel CLI,
and a config directory. A test that merely hides `~/rawgentic/.rawgentic_workspace.json`
while keeping the real XDG config, the real environment variables and the real `vercel`
binary is not a first-run test — it is the same machine with one file moved.

So these run in a SUBPROCESS against a constructed machine state:

* `HOME` and `XDG_CONFIG_HOME` under `tmp_path`;
* every `DESIGN_DOC_PUBLISH_*` and `VERCEL_*` variable removed from the child environment;
* a fake `vercel` first on `PATH`, driven by a state file, logging every argv it receives.

The fake covers only the probes SETUP itself makes. It is deliberately not a Vercel
emulator: making it carry a full publish through stages 4-7 would need `pagination.next`, a
deploy log and a live URL for the stage-6 verifier, and the test would then pass because the
emulator agrees with the code rather than because the code is right. The `--scope` invariant
is asserted in `test_scope_threading.py` instead, in-process, the way this suite already
asserts it.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parent
ROOT = SCRIPTS.parent
SETUP = SCRIPTS / "setup.py"
PUBLISH = SCRIPTS / "publish_doc.py"

SCOPE = "example-team"

FAKE_VERCEL = '''#!/usr/bin/env python3
"""A stand-in for the Vercel CLI, covering only the probes setup makes."""
import json
import os
import sys

log = os.environ["FAKE_VERCEL_LOG"]
state = os.environ["FAKE_VERCEL_STATE"]
context = os.environ.get("FAKE_VERCEL_CONTEXT", "%s")
mode = os.environ.get("FAKE_VERCEL_MODE", "ok")

with open(log, "a") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")

argv = sys.argv[1:]

if argv[:1] == ["whoami"]:
    if os.path.exists(state):
        sys.stdout.write("a-person\\n")
        raise SystemExit(0)
    sys.stderr.write("Error: no existing credentials found\\n")
    raise SystemExit(1)

if argv[:3] == ["project", "ls", "--format"]:
    if mode == "notjson":
        sys.stdout.write("Vercel CLI 56.5.0\\nnot json at all\\n")
        raise SystemExit(0)
    if mode == "denied":
        sys.stderr.write("Error: You are not authorized\\n")
        raise SystemExit(1)
    sys.stdout.write(json.dumps({
        "projects": [], "pagination": {"next": None}, "contextName": context}))
    raise SystemExit(0)

raise SystemExit(0)
''' % SCOPE


@pytest.fixture
def stranger(tmp_path):
    """A machine that has never run setup, and a CLI we control."""
    home = tmp_path / "home"
    (home / ".config").mkdir(parents=True)
    bindir = tmp_path / "bin"
    bindir.mkdir()

    fake = bindir / "vercel"
    fake.write_text(FAKE_VERCEL, encoding="utf-8")
    fake.chmod(0o755)

    log = tmp_path / "argv.log"
    state = tmp_path / "logged-in"

    env = {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "PATH": f"{bindir}:/usr/bin:/bin",
        "FAKE_VERCEL_LOG": str(log),
        "FAKE_VERCEL_STATE": str(state),
        "LC_ALL": "C.UTF-8",
    }
    # Nothing of this machine's own configuration may leak in. Removing only the workspace
    # file would leave the real XDG config, the real variables and the real binary in place,
    # which is not a first run.
    for name in os.environ:
        assert not name.startswith("DESIGN_DOC_PUBLISH_") or name not in env

    class Stranger:
        def __init__(self):
            self.home, self.env, self.log, self.state = home, env, log, state
            self.tmp = tmp_path

        def run(self, script, *args, **overrides):
            env = dict(self.env)
            env.update(overrides)
            return subprocess.run([sys.executable, str(script), *args],
                                  capture_output=True, text=True, cwd=str(self.tmp),
                                  env=env, check=False)

        def log_in(self):
            self.state.write_text("yes", encoding="utf-8")

        def argv(self):
            if not self.log.exists():
                return []
            return [json.loads(line) for line in
                    self.log.read_text(encoding="utf-8").splitlines() if line]

    return Stranger()


class TestSetupOnAMachineWithNothing:
    def test_it_reports_a_first_run_honestly_and_writes_nothing(self, stranger):
        proc = stranger.run(SETUP, "--json")
        assert proc.returncode == 0, proc.stderr
        state = json.loads(proc.stdout)
        assert state["first_run"] is True
        assert state["authenticated"] is False
        assert state["can_proceed"] is False
        assert state["status"] == "needs_login"
        assert not (stranger.home / ".config" / "design-doc-publish").exists(), (
            "reporting must not create anything")

    def test_the_config_it_names_is_outside_the_plugin_tree(self, stranger):
        """A plugin is installed into a versioned cache directory that is replaced on
        upgrade, so configuration written there is lost on the next release."""
        state = json.loads(stranger.run(SETUP, "--json").stdout)
        config = Path(state["config_file"])
        assert ROOT not in config.parents, f"{config} is inside the installed tree"
        assert str(config).startswith(str(stranger.home))

    def test_with_no_vercel_at_all_it_says_so(self, stranger):
        proc = stranger.run(SETUP, "--json", PATH="/usr/bin:/bin")
        state = json.loads(proc.stdout)
        assert state["status"] == "needs_vercel_cli"
        assert state["vercel_cli"] is False

    def test_check_exits_non_zero_with_one_line(self, stranger):
        proc = stranger.run(SETUP, "--check")
        assert proc.returncode == 3, proc.stderr
        assert proc.stderr.count("\n") == 1
        assert proc.stdout == ""

    def test_it_walks_an_unauthenticated_user_through_login_without_running_it(self,
                                                                              stranger):
        proc = stranger.run(SETUP)
        assert "vercel login" in proc.stdout
        assert ["login"] not in stranger.argv(), "login must never be run for the user"

    def test_the_whole_flow_ends_ready(self, stranger):
        stranger.log_in()
        assert stranger.run(SETUP, "--set-scope", SCOPE).returncode == 0
        assert stranger.run(SETUP, "--init-workspace").returncode == 0
        assert stranger.run(SETUP, "--add-project", "payments-api").returncode == 0

        state = json.loads(stranger.run(SETUP, "--json").stdout)
        assert state["status"] == "ready"
        assert state["can_proceed"] is True
        assert state["project_count"] == 1
        assert state["first_run"] is False
        assert stranger.run(SETUP, "--check").returncode == 0

    def test_a_team_that_answers_for_someone_else_is_refused(self, stranger):
        stranger.log_in()
        proc = stranger.run(SETUP, "--set-scope", SCOPE, FAKE_VERCEL_CONTEXT="another-team")
        assert proc.returncode != 0
        assert "another-team" in proc.stderr
        config = stranger.home / ".config" / "design-doc-publish" / "config.json"
        assert not config.exists(), "nothing may be recorded when the team is not proved"

    def test_a_probe_that_cannot_be_parsed_is_not_reported_as_a_denial(self, stranger):
        stranger.log_in()
        proc = stranger.run(SETUP, "--set-scope", SCOPE, FAKE_VERCEL_MODE="notjson")
        assert proc.returncode != 0
        assert "JSON" in proc.stderr or "json" in proc.stderr
        assert "not authorized" not in proc.stderr.lower()

    def test_no_credential_is_ever_written(self, stranger):
        stranger.log_in()
        stranger.run(SETUP, "--set-scope", SCOPE)
        stranger.run(SETUP, "--init-workspace")
        config = stranger.home / ".config" / "design-doc-publish" / "config.json"
        stored = json.loads(config.read_text(encoding="utf-8"))
        assert set(stored) <= {"version", "vercel_scope", "workspace_file",
                               "owned_workspace_file"}


class TestPublishingBeforeSetup:
    """AC5, by the path a stranger takes: stage 2 precedes every network call, so this is
    fully hermetic and needs no `vercel` at all."""

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
        assert stranger.argv() == [], "nothing may reach an account before stage 2 passes"

    def test_rendering_still_works_with_nothing_configured(self, stranger):
        """The shape that must not break: the README's first command needs no workspace, no
        team and no network."""
        doc = stranger.tmp / "hello.md"
        doc.write_text("# Hello\n\nA first page.\n\n## A section\n\nSome prose.\n",
                       encoding="utf-8")
        out = stranger.tmp / "hello.html"
        proc = stranger.run(SCRIPTS / "render-doc", "--md", str(doc), "--out", str(out),
                            "--title", "Hello")
        assert proc.returncode == 0, proc.stderr
        assert out.is_file() and "<html" in out.read_text(encoding="utf-8")
        assert stranger.argv() == []

    def test_after_setup_the_same_command_gets_past_stage_two(self, stranger):
        """The other half of the criterion: the refusal is not permanent, and following its
        instruction is what clears it."""
        stranger.log_in()
        stranger.run(SETUP, "--set-scope", SCOPE)
        stranger.run(SETUP, "--init-workspace")
        stranger.run(SETUP, "--add-project", "payments-api")

        doc = self._doc(stranger)
        proc = stranger.run(PUBLISH, "--md", str(doc), "--out", str(stranger.tmp / "o.html"),
                            "--project", "payments-api", "--type", "design", "--ref", "1",
                            "--title", "Payments rollout design", "--dry-run")
        assert proc.returncode == 0, proc.stderr
        assert "2/6 name payments-api-design-1" in proc.stdout
