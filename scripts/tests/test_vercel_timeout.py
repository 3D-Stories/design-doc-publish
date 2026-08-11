"""No call to the Vercel CLI may hang forever.

Both modules shell out to `vercel` through exactly one helper each, so the timeout belongs
there and nowhere else. Without it a non-responsive CLI stalls a publish stage or a setup
check indefinitely, and the caller cannot tell a slow network from a dead one.

The second half matters more than the first. A timeout must be reported as **could not
check**, never as **not signed in** or **refused**. `setup.py` already argues this for the
scope probe — "Telling someone their access was refused when the network blipped sends them
to fix a permission they already hold" — and a timeout on `whoami` is the same mistake with
a different label: it would send someone to run `vercel login` while they are already
logged in.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import setup as SETUP  # noqa: E402
import publish_doc as PUB  # noqa: E402


class TestBothHelpersPassATimeout:
    def test_setup_run_passes_one(self, monkeypatch):
        seen = {}

        def fake(*args, **kwargs):
            seen.update(kwargs)
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(SETUP.subprocess, "run", fake)
        SETUP._run(["whoami"])
        assert seen.get("timeout"), (
            "setup.py._run must pass a timeout; without it a dead CLI hangs the check")
        assert isinstance(seen["timeout"], (int, float)) and seen["timeout"] > 0

    def test_publish_doc_vercel_passes_one(self, monkeypatch):
        seen = {}

        def fake(*args, **kwargs):
            seen.update(kwargs)
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(PUB.subprocess, "run", fake)
        PUB._vercel(["ls"], ROOT, "some-team")
        assert seen.get("timeout"), (
            "publish_doc.py._vercel must pass a timeout; without it a dead CLI hangs a stage")
        assert isinstance(seen["timeout"], (int, float)) and seen["timeout"] > 0


class TestATimeoutIsNotADiagnosis:
    """The whole point: a timeout says NOTHING about credentials or permissions."""

    def _timeout(self, *args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["vercel"], timeout=1)

    def test_a_whoami_timeout_is_not_reported_as_needs_login(self, monkeypatch, tmp_path):
        monkeypatch.setattr(SETUP, "_vercel_installed", lambda: True)
        monkeypatch.setattr(SETUP.subprocess, "run", self._timeout)
        state = SETUP.status(config_path=tmp_path / "config.json")
        assert state["status"] != "needs_login", (
            "a timeout was reported as not-signed-in; that sends someone to run `vercel "
            "login` while they are already logged in")
        assert state["status"] == "vercel_probe_failed", state["status"]
        assert state["can_proceed"] is False

    def test_a_scope_probe_timeout_is_failed_not_denied(self, monkeypatch):
        monkeypatch.setattr(SETUP.subprocess, "run", self._timeout)
        outcome, detail = SETUP.probe_scope("some-team")
        assert outcome == "failed", (
            f"a timeout must be a FAILED probe, not a denial; got {outcome!r}")
        assert detail and "answer" in detail.lower() or "timed out" in (detail or "").lower()

    def test_a_publish_call_that_times_out_fails_the_stage(self, monkeypatch):
        """It must return a non-zero result, not raise into the caller's face and not hang."""
        monkeypatch.setattr(PUB.subprocess, "run", self._timeout)
        proc = PUB._vercel(["ls"], ROOT, "some-team")
        assert proc.returncode != 0, "a timed-out call must fail the stage"
        assert proc.stderr and proc.stderr.strip(), (
            "a timed-out call must say why, or the stage failure is unexplainable")
