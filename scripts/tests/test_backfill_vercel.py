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


class FakeCli:
    """The SUBPROCESS seam. Hands back canned pages in order, and records every argv."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        if not self.pages:
            raise AssertionError("the fake CLI was called more times than the test allowed")
        return self.pages.pop(0)


def page(names, nxt=None):
    return 0, json.dumps({
        "projects": [{"id": f"prj_{n}", "name": n, "latestProductionUrl": f"https://{n}.vercel.app/",
                      "nodeVersion": "22.x", "deprecated": False, "updatedAt": 1}
                     for n in names],
        "pagination": {"next": nxt},
        "contextName": "test",
    }), ""


class InventoryTests(unittest.TestCase):
    """T2 — bounded walks, honest cutoffs, and a listing failure that stops the campaign."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.run = bf.RunDir(pathlib.Path(self._tmp.name) / "run")
        self.addCleanup(self._tmp.cleanup)

    def test_pagination_follows_next_until_absent(self):
        cli = FakeCli([page(["a", "b"], nxt="123"), page(["c"]), page(["a", "b"], nxt="123"),
                       page(["c"])])
        snap = bf.inventory(self.run, runner=cli, max_walks=3)
        self.assertEqual(["a", "b", "c"], [r["name"] for r in snap["rows"]])
        self.assertTrue(snap["converged"])
        self.assertFalse(snap["cutoff"])
        # The second page must carry --next; the first must not.
        self.assertNotIn("--next", cli.calls[0])
        self.assertIn("--next", cli.calls[1])
        self.assertIn("123", cli.calls[1])

    def test_two_agreeing_walks_converge(self):
        cli = FakeCli([page(["a"]), page(["a"])])
        snap = bf.inventory(self.run, runner=cli, max_walks=3)
        self.assertTrue(snap["converged"])
        self.assertEqual(2, snap["walks"])

    def test_walks_that_never_agree_record_a_non_atomic_cutoff(self):
        cli = FakeCli([page(["a"]), page(["a", "b"]), page(["a", "b", "c"])])
        snap = bf.inventory(self.run, runner=cli, max_walks=3)
        self.assertFalse(snap["converged"])
        self.assertTrue(snap["cutoff"])
        self.assertEqual(3, snap["walks"])
        # The LAST fully completed walk is what is frozen, and it is bounded by two instants.
        self.assertEqual(["a", "b", "c"], [r["name"] for r in snap["rows"]])
        self.assertLessEqual(snap["started_at"], snap["completed_at"])

    def test_max_walks_is_honoured(self):
        cli = FakeCli([page(["a"]), page(["a", "b"]), page(["a", "b", "c"]), page(["d"])])
        snap = bf.inventory(self.run, runner=cli, max_walks=2)
        self.assertEqual(2, snap["walks"])
        self.assertTrue(snap["cutoff"])

    def test_non_zero_cli_exit_is_inventory_failed_not_an_empty_inventory(self):
        cli = FakeCli([(1, "", "Error: not authenticated")])
        with self.assertRaises(bf.CampaignFailed) as caught:
            bf.inventory(self.run, runner=cli, max_walks=3)
        self.assertEqual(bf.INVENTORY_FAILED, caught.exception.outcome)
        self.assertIn("not authenticated", str(caught.exception))

    def test_a_listing_missing_its_projects_array_is_inventory_failed(self):
        cli = FakeCli([(0, json.dumps({"pagination": {"next": None}}), "")])
        with self.assertRaises(bf.CampaignFailed) as caught:
            bf.inventory(self.run, runner=cli, max_walks=3)
        self.assertEqual(bf.INVENTORY_FAILED, caught.exception.outcome)

    def test_unparseable_json_is_inventory_failed(self):
        cli = FakeCli([(0, "not json at all", "")])
        with self.assertRaises(bf.CampaignFailed):
            bf.inventory(self.run, runner=cli, max_walks=3)

    def test_the_snapshot_is_persisted_and_digested(self):
        cli = FakeCli([page(["a"]), page(["a"])])
        snap = bf.inventory(self.run, runner=cli, max_walks=3)
        stored = self.run.read_json("inventory.json")
        self.assertEqual(snap["rows"], stored["rows"])
        self.assertEqual(bf.digest(stored["rows"]), stored["digest"])


class FakeHttp:
    """The HTTP seam. Maps a URL to (status, headers, body) and records what was asked for."""

    def __init__(self, responses):
        self.responses = dict(responses)
        self.asked = []

    def __call__(self, url, *, headers=None, method="GET", body=None, timeout=None):
        self.asked.append({"url": url, "headers": dict(headers or {}), "method": method})
        if url not in self.responses:
            raise AssertionError(f"the fake HTTP seam was asked for an unexpected url: {url}")
        item = self.responses[url]
        if isinstance(item, Exception):
            raise item
        return item


class NameSplitTests(unittest.TestCase):
    """T3 — the name NARROWS the search. It never decides the answer."""

    def test_the_purposes_copy_has_not_drifted(self):
        """The copy's own comment promises this test. An unbacked promise is worse than none."""
        spec = importlib.util.spec_from_file_location(
            "publish_doc_for_drift", ROOT / "scripts" / "publish_doc.py")
        pd = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pd)
        self.assertEqual(tuple(pd.PURPOSES), tuple(bf.PURPOSES))

    def test_every_viable_split_is_returned_not_the_first(self):
        """`a-plan-design-x` splits at BOTH purpose tokens when both projects exist."""
        splits = bf.viable_splits("a-plan-design-x", {"a", "a-plan"})
        self.assertIn(("a", "plan", "design-x"), splits)
        self.assertIn(("a-plan", "design", "x"), splits)

    def test_a_project_name_containing_a_purpose_word_does_not_hide_the_real_split(self):
        splits = bf.viable_splits("design-doc-publish-plan-campaign", {"design-doc-publish"})
        self.assertEqual([("design-doc-publish", "plan", "campaign")], splits)

    def test_a_ref_that_is_itself_a_purpose_token_still_splits(self):
        splits = bf.viable_splits("proj-plan-design", {"proj"})
        self.assertIn(("proj", "plan", "design"), splits)

    def test_a_name_with_no_purpose_token_yields_no_split(self):
        self.assertEqual([], bf.viable_splits("docs-index", {"docs"}))

    def test_a_split_whose_project_is_unknown_is_not_viable(self):
        self.assertEqual([], bf.viable_splits("ghost-plan-x", {"real"}))


class LiveFetchTests(unittest.TestCase):
    """T3 — the response is CHECKED, because a request header is only a preference."""

    def test_identity_is_requested(self):
        http = FakeHttp({"https://x/": (200, {"Content-Type": "text/html"}, b"<html>")})
        body = bf.fetch_live("https://x/", opener=http)
        self.assertEqual(b"<html>", body)
        self.assertEqual("identity", http.asked[0]["headers"]["Accept-Encoding"])

    def test_a_gzip_response_is_refused_even_though_identity_was_requested(self):
        http = FakeHttp({"https://x/": (200, {"Content-Encoding": "gzip"}, b"\x1f\x8b")})
        with self.assertRaises(bf.RowError) as caught:
            bf.fetch_live("https://x/", opener=http)
        self.assertEqual("source_unavailable", caught.exception.reason)
        self.assertIn("gzip", str(caught.exception))

    def test_identity_content_encoding_is_accepted(self):
        http = FakeHttp({"https://x/": (200, {"Content-Encoding": "identity"}, b"ok")})
        self.assertEqual(b"ok", bf.fetch_live("https://x/", opener=http))

    def test_a_non_200_is_source_unavailable_and_keeps_the_status(self):
        http = FakeHttp({"https://x/": (429, {}, b"slow down")})
        with self.assertRaises(bf.RowError) as caught:
            bf.fetch_live("https://x/", opener=http)
        self.assertEqual("source_unavailable", caught.exception.reason)
        self.assertIn("429", str(caught.exception))

    def test_a_transport_exception_is_source_unavailable_not_a_crash(self):
        http = FakeHttp({"https://x/": OSError("connection reset")})
        with self.assertRaises(bf.RowError) as caught:
            bf.fetch_live("https://x/", opener=http)
        self.assertEqual("source_unavailable", caught.exception.reason)


class HistorySearchTests(unittest.TestCase):
    """T3 — provenance comes from the BYTES, in real git history, not from HEAD."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_a_blob_in_an_OLD_commit_is_found(self):
        repo = self.tmp / "repo"
        make_repo(repo, {"docs/planning/2026-01-01-9-thing.html": "OLD BYTES"})
        # HEAD moves on, so the old bytes exist only in history.
        (repo / "docs/planning/2026-01-01-9-thing.html").write_text("NEW BYTES")
        git(repo, "add", "--", "docs/planning/2026-01-01-9-thing.html")
        git(repo, "commit", "-q", "-m", "second")
        found = bf.history_candidates(repo, ref="9", target=b"OLD BYTES", cap=100)
        self.assertEqual(1, len(found), found)
        self.assertEqual("docs/planning/2026-01-01-9-thing.html", found[0]["repo_path"])
        # And the commit it names is NOT the tip.
        self.assertNotEqual(git(repo, "rev-parse", "HEAD"), found[0]["commit"])

    def test_bytes_that_are_nowhere_return_nothing(self):
        repo = self.tmp / "repo"
        make_repo(repo, {"docs/planning/2026-01-01-9-thing.html": "OLD"})
        self.assertEqual([], bf.history_candidates(repo, ref="9", target=b"absent", cap=100))

    def test_hitting_the_cap_is_reported_rather_than_silently_truncating(self):
        repo = self.tmp / "repo"
        make_repo(repo, {"docs/planning/2026-01-01-9-thing.html": "v0"})
        for i in range(1, 4):
            (repo / "docs/planning/2026-01-01-9-thing.html").write_text(f"v{i}")
            git(repo, "add", "--", "docs/planning/2026-01-01-9-thing.html")
            git(repo, "commit", "-q", "-m", f"v{i}")
        found, capped = bf.history_candidates(repo, ref="9", target=b"v0", cap=2, report_cap=True)
        self.assertTrue(capped)
        self.assertEqual([], found)  # v0 is older than the cap allows, and that is SAID, not hidden


class MapTests(unittest.TestCase):
    """T3 — the mapping: provenance and target are SEPARATE, and every row binds to inventory."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.run = bf.RunDir(self.tmp / "run")

    def _workspace(self, projects):
        path = self.tmp / "workspace.json"
        path.write_text(json.dumps({
            "projects": [{"name": n, "path": str(p)} for n, p in projects.items()]}))
        return path

    def _snapshot(self, rows):
        return {"rows": rows, "digest": bf.digest(rows), "converged": True, "cutoff": False,
                "walks": 2, "started_at": 1, "completed_at": 2}

    def test_a_mapped_row_records_provenance_and_target_separately(self):
        """The live bytes are OLD. The target must be the tip, or the migration ships the stale page."""
        repo = self.tmp / "proj"
        make_repo(repo, {"docs/planning/2026-01-01-7-x.html": "OLD BYTES",
                         "docs/planning/2026-01-01-7-x.md": "# old"})
        old_commit = git(repo, "rev-parse", "HEAD")
        (repo / "docs/planning/2026-01-01-7-x.html").write_text("NEW BYTES")
        git(repo, "add", "--", "docs/planning/2026-01-01-7-x.html")
        git(repo, "commit", "-q", "-m", "second")
        tip = git(repo, "rev-parse", "HEAD")

        http = FakeHttp({"https://proj-plan-7.vercel.app/": (200, {}, b"OLD BYTES")})
        rows = bf.map_rows(
            self._snapshot([{"id": "prj_1", "name": "proj-plan-7",
                             "latestProductionUrl": "https://proj-plan-7.vercel.app/",
                             "updatedAt": 1}]),
            workspace_file=self._workspace({"proj": repo}), opener=http, run=self.run,
            fetch_remote=False)
        row = rows[0]
        self.assertIsNone(row.get("reason"), row)
        self.assertEqual(old_commit, row["provenance"]["commit"])
        self.assertEqual(tip, row["target"]["commit"])
        self.assertNotEqual(row["provenance"]["commit"], row["target"]["commit"])
        # And the target's bytes are the CURRENT ones, which is what a migration should serve.
        self.assertEqual("NEW BYTES", row["target"]["preview"])

    def test_the_row_is_bound_to_its_immutable_inventory_entry(self):
        repo = self.tmp / "proj"
        make_repo(repo, {"docs/planning/7-x.html": "B", "docs/planning/7-x.md": "# b"})
        http = FakeHttp({"https://proj-plan-7.vercel.app/": (200, {}, b"B")})
        rows = bf.map_rows(
            self._snapshot([{"id": "prj_1", "name": "proj-plan-7",
                             "latestProductionUrl": "https://proj-plan-7.vercel.app/",
                             "updatedAt": 1}]),
            workspace_file=self._workspace({"proj": repo}), opener=http, run=self.run,
            fetch_remote=False)
        self.assertEqual("prj_1", rows[0]["inventory"]["id"])
        self.assertEqual("proj-plan-7", rows[0]["inventory"]["name"])
        self.assertEqual("https://proj-plan-7.vercel.app/", rows[0]["inventory"]["url"])

    def test_identical_bytes_in_two_repositories_are_ambiguous_even_when_the_name_narrows(self):
        one, two = self.tmp / "proj", self.tmp / "other"
        make_repo(one, {"docs/planning/7-x.html": "SAME", "docs/planning/7-x.md": "# s"})
        make_repo(two, {"docs/planning/7-x.html": "SAME", "docs/planning/7-x.md": "# s"})
        http = FakeHttp({"https://proj-plan-7.vercel.app/": (200, {}, b"SAME")})
        rows = bf.map_rows(
            self._snapshot([{"id": "prj_1", "name": "proj-plan-7",
                             "latestProductionUrl": "https://proj-plan-7.vercel.app/",
                             "updatedAt": 1}]),
            workspace_file=self._workspace({"proj": one, "other": two}), opener=http,
            run=self.run, fetch_remote=False)
        self.assertEqual("mapping_ambiguous", rows[0]["reason"])
        self.assertEqual(2, len(rows[0]["candidates"]))

    def test_bytes_nowhere_in_the_workspace_are_mapping_not_found_with_the_naming_evidence(self):
        repo = self.tmp / "proj"
        make_repo(repo, {"docs/planning/7-x.html": "B"})
        http = FakeHttp({"https://proj-plan-7.vercel.app/": (200, {}, b"NOT IN GIT")})
        rows = bf.map_rows(
            self._snapshot([{"id": "prj_1", "name": "proj-plan-7",
                             "latestProductionUrl": "https://proj-plan-7.vercel.app/",
                             "updatedAt": 1}]),
            workspace_file=self._workspace({"proj": repo}), opener=http, run=self.run,
            fetch_remote=False)
        self.assertEqual("mapping_not_found", rows[0]["reason"])
        self.assertEqual([["proj", "plan", "7"]], rows[0]["splits"])

    def test_a_row_whose_source_cannot_be_read_is_source_unavailable(self):
        repo = self.tmp / "proj"
        make_repo(repo, {"docs/planning/7-x.html": "B"})
        http = FakeHttp({"https://proj-plan-7.vercel.app/": (503, {}, b"down")})
        rows = bf.map_rows(
            self._snapshot([{"id": "prj_1", "name": "proj-plan-7",
                             "latestProductionUrl": "https://proj-plan-7.vercel.app/",
                             "updatedAt": 1}]),
            workspace_file=self._workspace({"proj": repo}), opener=http, run=self.run,
            fetch_remote=False)
        self.assertEqual("source_unavailable", rows[0]["reason"])

    def test_a_row_with_no_production_url_is_source_unavailable_not_a_crash(self):
        rows = bf.map_rows(
            self._snapshot([{"id": "prj_1", "name": "proj-plan-7",
                             "latestProductionUrl": None, "updatedAt": 1}]),
            workspace_file=self._workspace({}), opener=FakeHttp({}), run=self.run,
            fetch_remote=False)
        self.assertEqual("source_unavailable", rows[0]["reason"])

    def test_two_rows_resolving_to_one_harness_name_are_both_flagged(self):
        repo = self.tmp / "proj"
        make_repo(repo, {"docs/planning/7-x.html": "A", "docs/planning/7-x.md": "# a"})
        rows = [
            {"inventory": {"id": "prj_1", "name": "proj-plan-7", "url": "u1"},
             "harness_name": "shared", "target": {}, "provenance": {}},
            {"inventory": {"id": "prj_2", "name": "proj-plan-8", "url": "u2"},
             "harness_name": "shared", "target": {}, "provenance": {}},
        ]
        checked = bf.enforce_name_uniqueness(rows)
        self.assertEqual(["target_name_collision", "target_name_collision"],
                         [r["reason"] for r in checked])

    def test_the_mapping_is_persisted_with_its_digest(self):
        repo = self.tmp / "proj"
        make_repo(repo, {"docs/planning/7-x.html": "B", "docs/planning/7-x.md": "# b"})
        http = FakeHttp({"https://proj-plan-7.vercel.app/": (200, {}, b"B")})
        bf.map_rows(
            self._snapshot([{"id": "prj_1", "name": "proj-plan-7",
                             "latestProductionUrl": "https://proj-plan-7.vercel.app/",
                             "updatedAt": 1}]),
            workspace_file=self._workspace({"proj": repo}), opener=http, run=self.run,
            fetch_remote=False)
        stored = self.run.read_json("mapping.json")
        self.assertEqual(bf.digest(stored["rows"]), stored["digest"])
        self.assertEqual(1, len(stored["rows"]))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(unittest.main())
