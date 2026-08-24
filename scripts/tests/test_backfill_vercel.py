"""Tests for scripts/backfill_vercel.py — the #37 Vercel-to-harness backfill.

Offline by construction. Two injected seams, because the inventory is a SUBPROCESS
(`vercel project list`) while the page fetch and the harness calls are HTTP; one seam would
have been a fake of itself. Temporary git repositories give real blob ids and real history,
because the whole provenance step is "which commit holds these exact bytes" and a mock of git
cannot answer that.
"""

import importlib.util
import json
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "backfill_vercel", ROOT / "scripts" / "backfill_vercel.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bf = _load()


def git(repo, *argv):
    """Run git in `repo` and return stdout, raising with stderr on failure."""
    proc = subprocess.run(["git", "-C", str(repo), *argv],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(argv)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def make_repo(path, files, message="initial"):
    """A real git repository with real blobs. Returns the commit sha."""
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "test@example.invalid")
    git(path, "config", "user.name", "Test")
    for rel, body in files.items():
        target = path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body if isinstance(body, bytes) else body.encode())
        git(path, "add", "--", rel)
    git(path, "commit", "-q", "-m", message)
    return git(path, "rev-parse", "HEAD")


class RunDirectoryTests(unittest.TestCase):
    """T1 — the run directory, the append-only journal, and the digest helpers."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_journal_is_append_only(self):
        """A second write for one row APPENDS. The journal is evidence, not state."""
        run = bf.RunDir(self.tmp / "run")
        run.journal("row-1", {"outcome": "pending"})
        run.journal("row-1", {"outcome": "live"})
        rows = run.journal_entries()
        self.assertEqual(2, len(rows))
        self.assertEqual(["pending", "live"], [r["record"]["outcome"] for r in rows])

    def test_existing_run_directory_is_reused_not_clobbered(self):
        run = bf.RunDir(self.tmp / "run")
        run.journal("row-1", {"outcome": "pending"})
        again = bf.RunDir(self.tmp / "run")
        self.assertEqual(1, len(again.journal_entries()))

    def test_digest_is_stable_across_key_order(self):
        a = bf.digest({"b": 1, "a": [1, 2]})
        b = bf.digest({"a": [1, 2], "b": 1})
        self.assertEqual(a, b)
        self.assertNotEqual(a, bf.digest({"a": [2, 1], "b": 1}))


class ReadOnlyByDefaultTests(unittest.TestCase):
    """T1 — no command may write to a registry without an explicit flag AND the right digest."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_execute_without_a_digest_refuses(self):
        with self.assertRaises(bf.Refused) as caught:
            bf.require_execute(execute=None, expected="abc123", what="mapping")
        self.assertIn("--execute", str(caught.exception))

    def test_execute_with_the_wrong_digest_refuses_and_names_both(self):
        with self.assertRaises(bf.Refused) as caught:
            bf.require_execute(execute="deadbeef", expected="abc123", what="mapping")
        message = str(caught.exception)
        self.assertIn("deadbeef", message)
        self.assertIn("abc123", message)

    def test_execute_with_the_right_digest_passes(self):
        bf.require_execute(execute="abc123", expected="abc123", what="mapping")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(unittest.main())
