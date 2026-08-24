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

    def test_the_history_walk_runs_once_per_repository_not_once_per_ref(self):
        """Ten rows across thirty repositories would otherwise be three hundred history walks."""
        repo = self.tmp / "repo"
        make_repo(repo, {"docs/planning/7-x.html": "B"})
        bf._HTML_PATHS_CACHE.clear()
        calls = []

        def counting(argv):
            calls.append(argv)
            return bf._default_cli(argv)

        bf.candidate_paths(repo, "7", runner=counting)
        bf.candidate_paths(repo, "8", runner=counting)
        bf.candidate_paths(repo, "9", runner=counting)
        walks = [c for c in calls if "log" in c and "--name-only" in c]
        self.assertEqual(1, len(walks))

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

    def test_the_workspace_file_is_found_by_walking_up_not_by_counting_parents(self):
        nested = self.tmp / "ws" / "projects" / "proj" / "scripts"
        nested.mkdir(parents=True)
        (self.tmp / "ws" / ".rawgentic_workspace.json").write_text('{"projects": []}')
        found = bf.find_workspace_file(nested / "backfill_vercel.py")
        self.assertEqual(str(self.tmp / "ws" / ".rawgentic_workspace.json"), found)

    def test_a_missing_workspace_file_refuses_rather_than_guessing(self):
        with self.assertRaises(bf.Refused):
            bf.find_workspace_file(pathlib.Path("/nonexistent-a/nonexistent-b/x.py"))

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

    def test_blob_present_finds_a_blob_that_is_there_and_misses_one_that_is_not(self):
        """The MECHANISM, tested directly.

        The collision test below asserted only the ambiguous outcome, and a completely broken
        `blob_present` produced that same outcome by failing every repository. So the mechanism
        gets its own test: a broken one must not be able to pass this.
        """
        repo = self.tmp / "direct"
        make_repo(repo, {"docs/x.html": "EXACT BYTES"})
        import hashlib as _h
        self.assertTrue(bf.blob_present(repo, sha256_hex=_h.sha256(b"EXACT BYTES").hexdigest(),
                                        size=len(b"EXACT BYTES")))
        self.assertFalse(bf.blob_present(repo, sha256_hex=_h.sha256(b"OTHER").hexdigest(),
                                         size=len(b"OTHER")))

    def test_a_plain_directory_is_not_treated_as_an_unsearchable_repository(self):
        """It cannot hold a committed blob, so it says NOTHING about uniqueness."""
        good = self.tmp / "proj"
        make_repo(good, {"docs/planning/7-x.html": "B", "docs/planning/7-x.md": "# b"})
        plain = self.tmp / "just-a-folder"
        plain.mkdir()
        http = FakeHttp({"https://proj-plan-7.vercel.app/": (200, {}, b"B")})
        rows = bf.map_rows(
            self._snapshot([{"id": "prj_1", "name": "proj-plan-7",
                             "latestProductionUrl": "https://proj-plan-7.vercel.app/",
                             "updatedAt": 1}]),
            workspace_file=self._workspace({"proj": good, "folder": plain}), opener=http,
            run=self.run, fetch_remote=False)
        self.assertIsNone(rows[0]["reason"], rows[0])
        self.assertIn("folder", rows[0]["not_repositories"])

    def test_identical_bytes_at_a_DIFFERENTLY_NAMED_path_elsewhere_are_still_ambiguous(self):
        """The collision check must not depend on the ref narrowing, or a non-unique match reads
        as unique. It runs over every blob in every repository, by size then hash."""
        one, two = self.tmp / "proj", self.tmp / "other"
        make_repo(one, {"docs/planning/7-x.html": "SAME BYTES", "docs/planning/7-x.md": "# s"})
        # A path carrying NO trace of the ref, so the narrowed search cannot see it.
        make_repo(two, {"docs/archive/unrelated-name.html": "SAME BYTES"})
        http = FakeHttp({"https://proj-plan-7.vercel.app/": (200, {}, b"SAME BYTES")})
        rows = bf.map_rows(
            self._snapshot([{"id": "prj_1", "name": "proj-plan-7",
                             "latestProductionUrl": "https://proj-plan-7.vercel.app/",
                             "updatedAt": 1}]),
            workspace_file=self._workspace({"proj": one, "other": two}), opener=http,
            run=self.run, fetch_remote=False)
        self.assertEqual("mapping_ambiguous", rows[0]["reason"])
        # The DETAIL must name the collision, not merely say "unproven" — otherwise a broken
        # collision check passes this test by failing every repository instead.
        self.assertIn("also committed in", rows[0]["detail"])
        self.assertIn("other", rows[0]["detail"])

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

    def test_limit_is_the_sample_selection_rule_and_takes_the_recorded_order(self):
        repo = self.tmp / "proj"
        make_repo(repo, {"docs/planning/7-x.html": "B", "docs/planning/7-x.md": "# b"})
        http = FakeHttp({"https://proj-plan-7.vercel.app/": (200, {}, b"B")})
        rows = bf.map_rows(
            self._snapshot([
                {"id": "prj_1", "name": "proj-plan-7",
                 "latestProductionUrl": "https://proj-plan-7.vercel.app/", "updatedAt": 1},
                {"id": "prj_2", "name": "proj-plan-8",
                 "latestProductionUrl": "https://proj-plan-8.vercel.app/", "updatedAt": 1}]),
            workspace_file=self._workspace({"proj": repo}), opener=http, run=self.run,
            fetch_remote=False, limit=1)
        self.assertEqual(1, len(rows))
        self.assertEqual("proj-plan-7", rows[0]["inventory"]["name"])

    def test_a_workspace_entry_that_is_not_a_git_repository_does_not_poison_every_row(self):
        """Found by the live sample run: one non-git path flagged all ten rows.

        A directory that cannot be searched is a property of the WORKSPACE, not of the document
        being mapped, so it is skipped and RECORDED rather than charged to the row.
        """
        good = self.tmp / "proj"
        make_repo(good, {"docs/planning/7-x.html": "B", "docs/planning/7-x.md": "# b"})
        broken = self.tmp / "not-a-repo"
        broken.mkdir()
        http = FakeHttp({"https://proj-plan-7.vercel.app/": (200, {}, b"B")})
        rows = bf.map_rows(
            self._snapshot([{"id": "prj_1", "name": "proj-plan-7",
                             "latestProductionUrl": "https://proj-plan-7.vercel.app/",
                             "updatedAt": 1}]),
            workspace_file=self._workspace({"proj": good, "junk": broken}), opener=http,
            run=self.run, fetch_remote=False)
        # It is NOT charged to the row as a reachability problem — that was the bug. `broken` here
        # is a plain directory, which cannot hold a committed blob, so it is excluded from the
        # uniqueness universe and recorded rather than blocking the row.
        self.assertIsNone(rows[0]["reason"], rows[0])
        self.assertIn("junk", rows[0]["not_repositories"])

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


class DestinationGuardTests(unittest.TestCase):
    """T4 — where the bearer may go, checked BEFORE it is attached."""

    def test_an_http_loopback_ip_literal_is_allowed(self):
        bf.assert_control_destination("http://127.0.0.1:18081", env={})

    def test_a_dns_name_is_refused_even_when_it_resolves_to_loopback(self):
        with self.assertRaises(bf.Refused) as caught:
            bf.assert_control_destination("http://docs-control.localhost:18081", env={})
        self.assertIn("IP literal", str(caught.exception))

    def test_a_non_loopback_ip_needs_an_explicit_grant_naming_host_and_port(self):
        with self.assertRaises(bf.Refused):
            bf.assert_control_destination("http://172.18.0.2:8080", env={})
        with self.assertRaises(bf.Refused):
            bf.assert_control_destination(
                "http://172.18.0.2:8080", env={"BACKFILL_ALLOW_PLAINTEXT": "true"})
        bf.assert_control_destination(
            "http://172.18.0.2:8080", env={"BACKFILL_ALLOW_PLAINTEXT": "172.18.0.2:8080"})

    def test_a_non_http_scheme_is_refused(self):
        with self.assertRaises(bf.Refused):
            bf.assert_control_destination("ftp://127.0.0.1:18081", env={})


class StagingLabelTests(unittest.TestCase):
    """T4 — the staging label must be injective, or two rows collide on a shared prefix."""

    def test_two_long_names_sharing_a_prefix_get_different_labels(self):
        a = "a" * 55 + "-alpha"
        b = "a" * 55 + "-beta"
        self.assertNotEqual(bf.staging_label("r1", a, 1), bf.staging_label("r1", b, 1))

    def test_the_label_is_a_valid_dns_label(self):
        label = bf.staging_label("r1", "x" * 200, 1)
        self.assertLessEqual(len(label), 63)
        self.assertRegex(label, r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")

    def test_the_attempt_counter_changes_the_label(self):
        self.assertNotEqual(bf.staging_label("r1", "x", 1), bf.staging_label("r1", "x", 2))


class FakeControl:
    """The harness seam. Records every call IN ORDER, so ordering can be asserted."""

    def __init__(self, *, active=None, publish=None, served=None, served_headers=None):
        self.active = active or {}
        self.publish_responses = list(publish or [])
        self.served = served or {}
        self.served_headers = served_headers or {}
        self.calls = []

    def read_active(self, name):
        self.calls.append(("read_active", name))
        return self.active.get(name, {"name": name, "active_deployment_id": None,
                                      "commit_sha": None, "published_at": None})

    def publish(self, manifest, expected_active):
        self.calls.append(("publish", manifest["name"], expected_active))
        if not self.publish_responses:
            raise AssertionError("the fake control API was asked to publish more times than allowed")
        item = self.publish_responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def serve(self, name):
        return self.serve_full(name)[0]

    def serve_full(self, name):
        self.calls.append(("serve", name))
        body = self.served.get(name, b"")
        headers = dict(self.served_headers.get(name, {}))
        return body, headers


class StageTests(unittest.TestCase):
    """T4 — compare first. The invariant is that a failing compare publishes NOTHING."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.run = bf.RunDir(self.tmp / "run")
        self.repo = self.tmp / "proj"
        make_repo(self.repo, {"docs/planning/7-x.html": "PAGE BYTES",
                              "docs/planning/7-x.md": "# page"})
        self.tip = git(self.repo, "rev-parse", "HEAD")
        self.blob = git(self.repo, "rev-parse", f"{self.tip}:docs/planning/7-x.html")
        import hashlib as _h
        self.row = {
            "inventory": {"id": "prj_1", "name": "proj-plan-7",
                          "url": "https://proj-plan-7.vercel.app/"},
            "harness_name": "proj-plan-7", "reason": None, "detail": "",
            "provenance": {"project": "proj", "commit": self.tip,
                           "repo_path": "docs/planning/7-x.html", "blob_id": self.blob,
                           "sha256": _h.sha256(b"PAGE BYTES").hexdigest()},
            "target": {"project": "proj", "commit": self.tip,
                       "repo_path": "docs/planning/7-x.html", "blob_id": self.blob,
                       "sha256": _h.sha256(b"PAGE BYTES").hexdigest(), "size": 10,
                       "md_path": "docs/planning/7-x.md",
                       "md_blob_id": git(self.repo, "rev-parse", f"{self.tip}:docs/planning/7-x.md"),
                       "preview": "PAGE BYTES"},
        }

    def _stage(self, *, live, control, rows=None, repo_map=None):
        http = FakeHttp({"https://proj-plan-7.vercel.app/": (200, {}, live)}
                        if not isinstance(live, tuple) else
                        {"https://proj-plan-7.vercel.app/": live})
        return bf.stage_rows(rows if rows is not None else [dict(self.row)],
                             run=self.run, control=control, opener=http,
                             repos=repo_map or {"proj": str(self.repo)}, run_id="r1")

    def test_a_failing_compare_publishes_NOTHING(self):
        """The invariant this whole design turns on: drift touches no registry at all.

        The realistic drift shape — Vercel still serves what `map` recorded, and the committed
        target has moved on since.
        """
        (self.repo / "docs/planning/7-x.html").write_text("NEW BYTES")
        git(self.repo, "add", "--", "docs/planning/7-x.html")
        git(self.repo, "commit", "-q", "-m", "the doc was edited after its last Vercel deploy")
        new_tip = git(self.repo, "rev-parse", "HEAD")
        import hashlib as _h
        row = dict(self.row)
        row["target"] = dict(row["target"], commit=new_tip,
                            blob_id=git(self.repo, "rev-parse", f"{new_tip}:docs/planning/7-x.html"),
                            sha256=_h.sha256(b"NEW BYTES").hexdigest(),
                            md_blob_id=git(self.repo, "rev-parse", f"{new_tip}:docs/planning/7-x.md"))
        control = FakeControl()
        out = self._stage(live=b"PAGE BYTES", control=control, rows=[row])
        self.assertEqual("byte_mismatch", out[0]["reason"])
        self.assertEqual([], [c for c in control.calls if c[0] == "publish"])

    def test_a_page_that_moved_since_map_is_vercel_changed_and_settles_first(self):
        """The two predicates cannot both fire: changed-since-map is tested first."""
        control = FakeControl()
        out = self._stage(live=b"SOMETHING ELSE ENTIRELY", control=control)
        self.assertEqual("vercel_changed", out[0]["reason"])
        self.assertEqual([], [c for c in control.calls if c[0] == "publish"])

    def test_a_passing_compare_stages_and_verifies(self):
        control = FakeControl(publish=[{"deployment_id": 5, "cache_warmed": True}],
                              served={bf.staging_label("r1", "proj-plan-7", 1): b"PAGE BYTES"})
        out = self._stage(live=b"PAGE BYTES", control=control)
        self.assertIsNone(out[0]["reason"], out[0])
        self.assertEqual(5, out[0]["staged"]["deployment_id"])
        kinds = [c[0] for c in control.calls]
        self.assertEqual(["publish", "serve"], kinds)

    def test_the_manifest_carries_the_metadata_and_not_content_type(self):
        control = FakeControl(publish=[{"deployment_id": 5, "cache_warmed": True}],
                              served={bf.staging_label("r1", "proj-plan-7", 1): b"PAGE BYTES"})
        self._stage(live=b"PAGE BYTES", control=control)
        manifest = [c for c in control.calls if c[0] == "publish"][0]
        stored = self.run.read_json("activation-plan.json")["rows"][0]["manifest"]
        self.assertEqual("proj", stored["project"])
        self.assertEqual("plan", stored["purpose"])
        self.assertNotIn("content_type", json.dumps(stored["assets"]))
        self.assertEqual(manifest[2], None)  # first publish sends expected_active null

    def test_cache_warmed_false_is_a_failure_not_a_pass(self):
        control = FakeControl(publish=[{"deployment_id": 5, "cache_warmed": False}])
        out = self._stage(live=b"PAGE BYTES", control=control)
        self.assertEqual("stage_publish_failed", out[0]["reason"])

    def test_a_served_mismatch_is_final_verification_failed(self):
        control = FakeControl(publish=[{"deployment_id": 5, "cache_warmed": True}],
                              served={bf.staging_label("r1", "proj-plan-7", 1): b"WRONG"})
        out = self._stage(live=b"PAGE BYTES", control=control)
        self.assertEqual("final_verification_failed", out[0]["reason"])

    def test_a_502_from_the_harness_is_harness_fetch_denied(self):
        control = FakeControl(publish=[bf.ControlError(502, "github fetch failed for 3D/x")])
        out = self._stage(live=b"PAGE BYTES", control=control)
        self.assertEqual("harness_fetch_denied", out[0]["reason"])
        self.assertIn("3D/x", out[0]["detail"])

    def test_a_422_carrying_githubs_object_miss_is_harness_fetch_denied(self):
        """Measured live: two sampled rows failed this way and their repositories are PRIVATE.

        Calling it `stage_publish_failed` pointed an operator at the manifest, which was correct.
        """
        control = FakeControl(publish=[bf.ControlError(
            422, "docs/planning/x.html: GitHub reports this object does not exist")])
        out = self._stage(live=b"PAGE BYTES", control=control)
        self.assertEqual("harness_fetch_denied", out[0]["reason"])
        self.assertIn("token's grant", out[0]["detail"])

    def test_a_422_that_is_genuinely_the_manifest_stays_stage_publish_failed(self):
        control = FakeControl(publish=[bf.ControlError(422, "url_path is not canonically encoded")])
        out = self._stage(live=b"PAGE BYTES", control=control)
        self.assertEqual("stage_publish_failed", out[0]["reason"])

    def test_a_409_on_a_staging_name_is_stage_publish_failed_never_an_overwrite(self):
        control = FakeControl(publish=[bf.ControlError(409, "stale publisher")])
        out = self._stage(live=b"PAGE BYTES", control=control)
        self.assertEqual("stage_publish_failed", out[0]["reason"])

    def test_the_write_ahead_record_exists_BEFORE_the_publish(self):
        seen = {}
        control = FakeControl(publish=[{"deployment_id": 5, "cache_warmed": True}],
                              served={bf.staging_label("r1", "proj-plan-7", 1): b"PAGE BYTES"})
        real_publish = control.publish

        def spy(manifest, expected_active):
            pendings = [e for e in self.run.journal_entries()
                        if e["record"].get("state") == "pending"]
            seen["pending_before_publish"] = len(pendings)
            return real_publish(manifest, expected_active)

        control.publish = spy
        self._stage(live=b"PAGE BYTES", control=control)
        self.assertEqual(1, seen["pending_before_publish"])

    def test_a_row_whose_recorded_hash_no_longer_matches_is_mapping_invalid(self):
        row = dict(self.row)
        row["target"] = dict(row["target"], sha256="0" * 64)
        out = self._stage(live=b"PAGE BYTES", control=FakeControl(), rows=[row])
        self.assertEqual("mapping_invalid", out[0]["reason"])

    def test_an_edit_that_changes_BOTH_row_fields_is_still_caught_by_the_snapshot(self):
        """Critical finding: comparing two fields of the same editable row proves nothing."""
        row = dict(self.row)
        row["harness_name"] = "somebody-elses-trusted-name"
        row["inventory"] = dict(row["inventory"], name="somebody-elses-trusted-name")
        snapshot = [{"id": "prj_1", "name": "proj-plan-7",
                     "latestProductionUrl": "https://proj-plan-7.vercel.app/", "updatedAt": 1}]
        out = bf.stage_rows([row], run=self.run, control=FakeControl(),
                            opener=FakeHttp({"https://proj-plan-7.vercel.app/":
                                             (200, {}, b"PAGE BYTES")}),
                            repos={"proj": str(self.repo)}, run_id="r1", inventory=snapshot)
        self.assertEqual("mapping_invalid", out[0]["reason"])
        self.assertIn("prj_1", out[0]["detail"])

    def test_an_edited_source_url_is_caught_by_the_snapshot(self):
        row = dict(self.row)
        row["inventory"] = dict(row["inventory"], url="https://attacker.example/")
        snapshot = [{"id": "prj_1", "name": "proj-plan-7",
                     "latestProductionUrl": "https://proj-plan-7.vercel.app/", "updatedAt": 1}]
        out = bf.stage_rows([row], run=self.run, control=FakeControl(),
                            opener=FakeHttp({}), repos={"proj": str(self.repo)}, run_id="r1",
                            inventory=snapshot)
        self.assertEqual("mapping_invalid", out[0]["reason"])
        self.assertIn("wrong", out[0]["detail"])

    def test_an_edited_harness_name_that_leaves_its_inventory_row_is_mapping_invalid(self):
        row = dict(self.row)
        row["harness_name"] = "somebody-elses-trusted-name"
        out = self._stage(live=b"PAGE BYTES", control=FakeControl(), rows=[row])
        self.assertEqual("mapping_invalid", out[0]["reason"])

    def test_an_already_flagged_row_is_left_alone(self):
        row = dict(self.row, reason="mapping_ambiguous")
        out = self._stage(live=b"PAGE BYTES", control=FakeControl(), rows=[row])
        self.assertEqual("mapping_ambiguous", out[0]["reason"])

    def test_one_row_raising_leaves_the_others_intact(self):
        good = dict(self.row)
        bad = dict(self.row)
        bad["target"] = dict(bad["target"], repo_path="docs/planning/absent.html")
        control = FakeControl(publish=[{"deployment_id": 5, "cache_warmed": True}],
                             served={bf.staging_label("r1", "proj-plan-7", 1): b"PAGE BYTES"})
        out = self._stage(live=b"PAGE BYTES", control=control, rows=[bad, good])
        self.assertIsNotNone(out[0]["reason"])
        self.assertIsNone(out[1]["reason"], out[1])

    def test_staging_does_not_mutate_the_reviewed_mapping_rows(self):
        """Found live: outcomes leaked into mapping.json and the retry saw zero eligible rows."""
        row = dict(self.row)
        control = FakeControl(publish=[bf.ControlError(422, "nope")])
        bf.stage_rows([row], run=self.run, control=control,
                      opener=FakeHttp({"https://proj-plan-7.vercel.app/": (200, {}, b"PAGE BYTES")}),
                      repos={"proj": str(self.repo)}, run_id="r1")
        self.assertIsNone(row.get("reason"),
                          "the caller's reviewed row must come back untouched")

    def test_the_bearer_never_reaches_the_journal(self):
        control = FakeControl(publish=[{"deployment_id": 5, "cache_warmed": True}],
                              served={bf.staging_label("r1", "proj-plan-7", 1): b"PAGE BYTES"})
        self._stage(live=b"PAGE BYTES", control=control)
        text = (self.run.path / "journal.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("Bearer", text)
        self.assertNotIn("Authorization", text)


class ActivateTests(unittest.TestCase):
    """T5 — the only command that touches a production name, and the only irreversible one."""

    def setUp(self):
        import hashlib as _h
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.run = bf.RunDir(self.tmp / "run")
        self.repo = self.tmp / "proj"
        make_repo(self.repo, {"docs/planning/7-x.html": "PAGE BYTES",
                              "docs/planning/7-x.md": "# page"})
        self.tip = git(self.repo, "rev-parse", "HEAD")
        self.blob = git(self.repo, "rev-parse", f"{self.tip}:docs/planning/7-x.html")
        self.live_sha = _h.sha256(b"PAGE BYTES").hexdigest()
        self.label = bf.staging_label("r1", "proj-plan-7", 1)
        self.manifest = {
            "name": self.label, "repo": "local/test", "commit_sha": self.tip,
            "entry_path": "/index.html",
            "assets": [{"url_path": "/index.html", "repo_path": "docs/planning/7-x.html",
                        "blob_id": self.blob, "size": 10, "sha256": self.live_sha}],
            "title": "proj-plan-7", "project": "proj", "purpose": "plan"}
        self.plan_row = {"name": "proj-plan-7", "manifest": self.manifest,
                         "staged": {"label": self.label, "deployment_id": 5},
                         "sealed_live_sha256": self.live_sha}
        self.row = {
            "inventory": {"id": "prj_1", "name": "proj-plan-7",
                          "url": "https://proj-plan-7.vercel.app/"},
            "harness_name": "proj-plan-7", "reason": None, "detail": "",
            "provenance": {"project": "proj", "commit": self.tip,
                           "repo_path": "docs/planning/7-x.html", "blob_id": self.blob,
                           "sha256": self.live_sha},
            "target": {"project": "proj", "commit": self.tip,
                       "repo_path": "docs/planning/7-x.html", "blob_id": self.blob,
                       "sha256": self.live_sha, "size": 10,
                       "md_path": "docs/planning/7-x.md",
                       "md_blob_id": git(self.repo, "rev-parse", f"{self.tip}:docs/planning/7-x.md")}}

    def _plan(self, rows=None, *, ttl=1800):
        import time as _t
        rows = self.plan_row if rows is None else rows
        rows = rows if isinstance(rows, list) else [rows]
        plan = {"rows": rows, "expires_at": int(_t.time()) + ttl, "run_id": "r1", "attempt": 1,
                "mapping_digest": self._mapping_digest()}
        plan["digest"] = bf.plan_digest(plan)
        self.run.write_json("activation-plan.json", plan)
        return plan

    def _mapping_digest(self, rows=None):
        rows = [dict(self.row)] if rows is None else rows
        return bf.digest(rows)

    def _activate(self, *, control, live=b"PAGE BYTES", rows=None, mapping_rows=None, plan=None):
        if plan is None:
            plan = self._plan(rows)
            if mapping_rows is not None:
                # The plan seals the mapping it was compared against; a test that changes the
                # mapping on purpose must re-seal, or it is testing the swap guard instead.
                plan["mapping_digest"] = bf.digest(mapping_rows)
                plan["digest"] = bf.plan_digest(plan)
                self.run.write_json("activation-plan.json", plan)
        http = FakeHttp({"https://proj-plan-7.vercel.app/": (200, {}, live)})
        mapping = {"rows": mapping_rows if mapping_rows is not None else [dict(self.row)]}
        mapping["digest"] = bf.digest(mapping["rows"])
        self.run.write_json("mapping.json", mapping)
        return bf.activate_rows(plan, mapping=mapping, run=self.run, control=control,
                                opener=http, repos={"proj": str(self.repo)},
                                execute=plan["digest"], zone="example.test")

    def test_a_clean_activation_publishes_and_verifies(self):
        control = FakeControl(publish=[{"deployment_id": 9, "cache_warmed": True}],
                              served={"proj-plan-7": b"PAGE BYTES"},
                              served_headers={"proj-plan-7": {"X-Doc-Deployment": "9",
                                                              "Etag": f'"{self.live_sha}"'}})
        out = self._activate(control=control)
        self.assertEqual("live", out[0]["outcome"])
        published = [c for c in control.calls if c[0] == "publish"][0]
        self.assertEqual("proj-plan-7", published[1])   # the PRODUCTION name, not the staging label

    def test_the_production_manifest_differs_from_the_staged_one_in_NAME_ALONE(self):
        captured = {}
        control = FakeControl(publish=[{"deployment_id": 9, "cache_warmed": True}],
                              served={"proj-plan-7": b"PAGE BYTES"},
                              served_headers={"proj-plan-7": {
                                  "X-Doc-Deployment": "9", "Etag": f'"{self.live_sha}"'}})
        real = control.publish

        def spy(manifest, expected_active):
            captured["manifest"] = json.loads(json.dumps(manifest))
            return real(manifest, expected_active)

        control.publish = spy
        self._activate(control=control)
        produced = dict(captured["manifest"])
        produced.pop("expected_active", None)
        staged = dict(self.manifest)
        self.assertEqual("proj-plan-7", produced.pop("name"))
        self.assertEqual(self.label, staged.pop("name"))
        self.assertEqual(staged, produced)

    def test_an_EDITED_plan_is_refused_even_with_its_own_stored_digest(self):
        """Critical finding: a stored digest is not evidence about the content beside it."""
        plan = self._plan()
        plan["rows"][0]["manifest"]["assets"][0]["blob_id"] = "0" * 40
        self.run.write_json("activation-plan.json", plan)
        with self.assertRaises(bf.Refused) as caught:
            self._activate(control=FakeControl(), plan=plan)
        self.assertIn("edited since it was sealed", str(caught.exception))

    def test_a_swapped_mapping_is_refused_even_with_a_matching_plan_digest(self):
        plan = self._plan()
        other = [dict(self.row, harness_name="somebody-else")]
        mapping = {"rows": other, "digest": bf.digest(other)}
        self.run.write_json("mapping.json", mapping)
        with self.assertRaises(bf.Refused) as caught:
            bf.activate_rows(plan, mapping=mapping, run=self.run, control=FakeControl(),
                             opener=FakeHttp({}), repos={"proj": str(self.repo)},
                             execute=plan["digest"], zone="example.test")
        self.assertIn("sealed against mapping", str(caught.exception))

    def test_a_wrong_execute_digest_refuses_before_anything_is_published(self):
        plan = self._plan()
        control = FakeControl()
        http = FakeHttp({})
        mapping = {"rows": [dict(self.row)]}
        mapping["digest"] = bf.digest(mapping["rows"])
        self.run.write_json("mapping.json", mapping)
        with self.assertRaises(bf.Refused):
            bf.activate_rows(plan, mapping=mapping, run=self.run, control=control, opener=http,
                             repos={"proj": str(self.repo)}, execute="deadbeef", zone="example.test")
        self.assertEqual([], control.calls)

    def test_the_plan_digest_covers_the_expiry_not_only_the_rows(self):
        plan = self._plan()
        first = bf.plan_digest(plan)
        plan["expires_at"] = int(plan["expires_at"]) + 3600
        self.assertNotEqual(first, bf.plan_digest(plan))

    def test_an_expired_plan_is_plan_expired_and_publishes_nothing(self):
        plan = self._plan(ttl=-1)
        control = FakeControl()
        out = self._activate(control=control, plan=plan)
        self.assertEqual("plan_expired", out[0]["reason"])
        self.assertEqual([], [c for c in control.calls if c[0] == "publish"])

    def test_a_row_deleted_from_the_mapping_after_stage_does_not_activate(self):
        control = FakeControl()
        out = self._activate(control=control, mapping_rows=[])
        self.assertEqual("mapping_invalid", out[0]["reason"])
        self.assertEqual([], [c for c in control.calls if c[0] == "publish"])

    def test_vercel_moving_since_the_seal_publishes_nothing(self):
        control = FakeControl()
        out = self._activate(control=control, live=b"MOVED ON")
        self.assertEqual("vercel_changed", out[0]["reason"])
        self.assertEqual([], [c for c in control.calls if c[0] == "publish"])

    def test_a_name_owned_by_somebody_else_is_target_occupied(self):
        control = FakeControl(active={"proj-plan-7": {"name": "proj-plan-7",
                                                      "active_deployment_id": 777,
                                                      "commit_sha": "x", "published_at": ""}})
        out = self._activate(control=control)
        self.assertEqual("target_occupied", out[0]["reason"])
        self.assertEqual([], [c for c in control.calls if c[0] == "publish"])

    def test_a_deployment_this_ROW_recorded_is_adoptable(self):
        control = FakeControl(active={"proj-plan-7": {"name": "proj-plan-7",
                                                      "active_deployment_id": 9,
                                                      "commit_sha": "x", "published_at": ""}},
                              publish=[{"deployment_id": 10, "cache_warmed": True}],
                              served={"proj-plan-7": b"PAGE BYTES"},
                              served_headers={"proj-plan-7": {
                                  "X-Doc-Deployment": "10",
                                  "Etag": f'"{self.live_sha}"'}})
        self.run.journal("proj-plan-7", {"phase": "activate", "state": "published",
                                         "target": "proj-plan-7", "deployment_id": 9})
        out = self._activate(control=control)
        self.assertEqual("live", out[0]["outcome"], out[0])

    def test_an_unproven_pending_deployment_is_NEVER_adopted(self):
        """A lost POST response leaves ownership unprovable, so the row stops for an operator."""
        control = FakeControl(active={"proj-plan-7": {"name": "proj-plan-7",
                                                      "active_deployment_id": 42,
                                                      "commit_sha": "x", "published_at": ""}})
        self.run.journal("proj-plan-7", {"phase": "activate", "state": "pending",
                                         "target": "proj-plan-7", "expected_active": None})
        out = self._activate(control=control)
        self.assertEqual("final_verification_failed", out[0]["reason"])
        self.assertIn("cannot prove", out[0]["detail"])
        self.assertEqual([], [c for c in control.calls if c[0] == "publish"])

    def test_a_409_is_cas_conflict(self):
        control = FakeControl(publish=[bf.ControlError(409, "stale publisher")])
        out = self._activate(control=control)
        self.assertEqual("cas_conflict", out[0]["reason"])

    def test_a_missing_or_wrong_etag_fails_the_verification(self):
        """The design advertises bytes, ETag and deployment. Accepting a wrong ETag weakens it."""
        control = FakeControl(publish=[{"deployment_id": 9, "cache_warmed": True}],
                              served={"proj-plan-7": b"PAGE BYTES"},
                              served_headers={"proj-plan-7": {"X-Doc-Deployment": "9"}})
        out = self._activate(control=control)
        self.assertEqual("final_verification_failed", out[0]["reason"])
        self.assertIn("ETag", out[0]["detail"])

    def test_a_reflected_authorization_header_never_reaches_the_journal(self):
        """Truncating a body is not sanitizing it — a review finding, and it was right."""
        detail = bf._safe_detail(b"Bearer sekrit-token-value reflected right at the front",
                                 "sekrit-token-value")
        self.assertNotIn("sekrit-token-value", detail)
        self.assertIn("deliberately NOT reproduced", detail)

    def test_a_known_harness_message_is_kept_because_it_is_the_diagnosis(self):
        detail = bf._safe_detail(b"docs/x.html: GitHub reports this object does not exist", "t")
        self.assertIn("does not exist", detail)

    def test_a_serve_failure_AFTER_the_publish_also_halts_the_campaign(self):
        """Critical finding: the ControlError path recorded the failure and carried on.

        A non-200 from the serve check arrives after the production POST has already committed, so
        it is exactly as irreversible as a byte mismatch and must stop the run too.
        """
        second = dict(self.plan_row, name="proj-plan-8")
        second["manifest"] = dict(self.manifest)
        mapping_rows = [dict(self.row), dict(self.row, harness_name="proj-plan-8",
                                             inventory=dict(self.row["inventory"],
                                                            name="proj-plan-8"))]
        control = FakeControl(publish=[{"deployment_id": 9, "cache_warmed": True}])

        def refuse(name):
            control.calls.append(("serve", name))
            raise bf.ControlError(503, "the harness did not serve the page")

        control.serve_full = refuse
        out = self._activate(control=control, rows=[self.plan_row, second],
                             mapping_rows=mapping_rows)
        self.assertEqual("final_verification_failed", out[0]["reason"])
        self.assertIn("already committed", out[0]["detail"])
        self.assertEqual("campaign_halted", out[1]["reason_class"])
        self.assertEqual(1, len([c for c in control.calls if c[0] == "publish"]))

    def test_a_cas_conflict_does_NOT_halt_because_nothing_was_written(self):
        second = dict(self.plan_row, name="proj-plan-8")
        second["manifest"] = dict(self.manifest)
        mapping_rows = [dict(self.row), dict(self.row, harness_name="proj-plan-8",
                                             inventory=dict(self.row["inventory"],
                                                            name="proj-plan-8"))]
        control = FakeControl(publish=[bf.ControlError(409, "stale publisher"),
                                       bf.ControlError(409, "stale publisher")])
        out = self._activate(control=control, rows=[self.plan_row, second],
                             mapping_rows=mapping_rows)
        self.assertEqual("cas_conflict", out[0]["reason"])
        self.assertEqual("cas_conflict", out[1]["reason"])
        self.assertNotEqual("campaign_halted", out[1]["reason_class"])

    def test_activate_honours_limit_on_the_irreversible_command(self):
        second = dict(self.plan_row, name="proj-plan-8")
        second["manifest"] = dict(self.manifest)
        mapping_rows = [dict(self.row), dict(self.row, harness_name="proj-plan-8",
                                             inventory=dict(self.row["inventory"],
                                                            name="proj-plan-8"))]
        plan = self._plan([self.plan_row, second])
        plan["mapping_digest"] = bf.digest(mapping_rows)
        plan["digest"] = bf.plan_digest(plan)
        self.run.write_json("activation-plan.json", plan)
        mapping = {"rows": mapping_rows, "digest": bf.digest(mapping_rows)}
        self.run.write_json("mapping.json", mapping)
        control = FakeControl(publish=[{"deployment_id": 9, "cache_warmed": True}],
                              served={"proj-plan-7": b"PAGE BYTES"},
                              served_headers={"proj-plan-7": {
                                  "X-Doc-Deployment": "9", "Etag": f'"{self.live_sha}"'}})
        out = bf.activate_rows(plan, mapping=mapping, run=self.run, control=control,
                               opener=FakeHttp({"https://proj-plan-7.vercel.app/":
                                                (200, {}, b"PAGE BYTES")}),
                               repos={"proj": str(self.repo)}, execute=plan["digest"],
                               zone="example.test", limit=1)
        self.assertEqual(1, len(out))
        self.assertEqual(1, len([c for c in control.calls if c[0] == "publish"]))

    def test_a_post_publish_verification_failure_HALTS_the_campaign(self):
        """Per-row isolation stops at the campaign boundary: bad bytes are live under a real name."""
        second = dict(self.plan_row, name="proj-plan-8")
        second["manifest"] = dict(self.manifest)
        control = FakeControl(publish=[{"deployment_id": 9, "cache_warmed": True}],
                              served={"proj-plan-7": b"NOT THE PAGE"},
                              served_headers={"proj-plan-7": {"X-Doc-Deployment": "9",
                                                              "Etag": '"whatever"'}})
        mapping_rows = [dict(self.row), dict(self.row, harness_name="proj-plan-8",
                                             inventory=dict(self.row["inventory"],
                                                            name="proj-plan-8"))]
        out = self._activate(control=control, rows=[self.plan_row, second],
                             mapping_rows=mapping_rows)
        self.assertEqual("final_verification_failed", out[0]["reason"])
        self.assertEqual("campaign_halted", out[1]["reason_class"])
        self.assertEqual(1, len([c for c in control.calls if c[0] == "publish"]))


class ReportTests(unittest.TestCase):
    """T6 — the report ASSERTS its own completeness, over what was PROCESSED."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.run = bf.RunDir(self.tmp / "run")

    def _write(self, *, snapshot_names, mapping_rows, outcomes):
        rows = [{"id": f"prj_{n}", "name": n, "latestProductionUrl": f"https://{n}/",
                 "updatedAt": 1} for n in snapshot_names]
        self.run.write_json("inventory.json", {
            "rows": rows, "digest": bf.digest(rows), "converged": True, "cutoff": False,
            "walks": 2, "started_at": 100, "completed_at": 200})
        self.run.write_json("mapping.json", {"rows": mapping_rows,
                                             "digest": bf.digest(mapping_rows)})
        self.run.write_json("outcomes.json", {"rows": outcomes, "halted": False})

    def test_the_processed_and_snapshot_sets_are_reported_separately(self):
        self._write(snapshot_names=["a", "b", "c"],
                    mapping_rows=[{"harness_name": "a", "reason": None},
                                  {"harness_name": "b", "reason": "byte_mismatch",
                                   "detail": "drifted"}],
                    outcomes=[{"name": "a", "outcome": "live", "reason": None, "detail": "",
                               "deployment_id": 3}])
        summary = bf.build_report(self.run)
        self.assertEqual(3, summary["snapshot"])
        self.assertEqual(2, summary["processed"])
        self.assertEqual(1, summary["not_attempted"])
        self.assertEqual(3, summary["snapshot"])
        self.assertIn("not_attempted", summary["markdown"])

    def test_a_row_flagged_at_STAGE_is_reported_rather_than_refusing(self):
        """Found by the report's own assertion on the live run: a third source was missing.

        A row can map cleanly, fail at stage, and therefore appear in neither the mapping's reasons
        nor the activation outcomes.
        """
        self._write(snapshot_names=["a", "b"],
                    mapping_rows=[{"harness_name": "a", "reason": None}],
                    outcomes=[])
        self.run.write_json("staged-rows.json", {"rows": [
            {"harness_name": "a", "reason": "harness_fetch_denied", "detail": "private repo"}]})
        summary = bf.build_report(self.run)
        self.assertEqual(1, summary["reasons"]["harness_fetch_denied"])
        self.assertEqual(1, summary["processed"])

    def test_a_corrupt_outcome_paired_with_a_known_reason_is_still_refused(self):
        self._write(snapshot_names=["a"],
                    mapping_rows=[{"harness_name": "a", "reason": None}],
                    outcomes=[{"name": "a", "outcome": None, "reason": "byte_mismatch",
                               "detail": ""}])
        with self.assertRaises(bf.Refused) as caught:
            bf.build_report(self.run)
        self.assertIn("neither", str(caught.exception))

    def test_every_processed_row_must_have_ended_live_or_flagged(self):
        self._write(snapshot_names=["a", "b"],
                    mapping_rows=[{"harness_name": "a", "reason": None},
                                  {"harness_name": "b", "reason": None}],
                    outcomes=[{"name": "a", "outcome": "live", "reason": None, "detail": ""}])
        with self.assertRaises(bf.Refused) as caught:
            bf.build_report(self.run)
        self.assertIn("b", str(caught.exception))

    def test_totals_per_reason_add_up_to_the_processed_count(self):
        self._write(snapshot_names=["a", "b", "c"],
                    mapping_rows=[{"harness_name": n, "reason": None} for n in "abc"],
                    outcomes=[{"name": "a", "outcome": "live", "reason": None, "detail": ""},
                              {"name": "b", "outcome": "flagged", "reason": "byte_mismatch",
                               "detail": "x"},
                              {"name": "c", "outcome": "flagged", "reason": "cas_conflict",
                               "detail": "y"}])
        summary = bf.build_report(self.run)
        self.assertEqual(1, summary["live"])
        self.assertEqual(summary["processed"], summary["live"] + sum(summary["reasons"].values()))

    def test_a_reason_outside_the_vocabulary_is_refused(self):
        self._write(snapshot_names=["a"],
                    mapping_rows=[{"harness_name": "a", "reason": None}],
                    outcomes=[{"name": "a", "outcome": "flagged", "reason": "vibes",
                               "detail": ""}])
        with self.assertRaises(bf.Refused):
            bf.build_report(self.run)

    def test_leftover_staging_labels_are_listed(self):
        self._write(snapshot_names=["a"],
                    mapping_rows=[{"harness_name": "a", "reason": None}],
                    outcomes=[{"name": "a", "outcome": "live", "reason": None, "detail": ""}])
        self.run.journal("a", {"phase": "stage", "state": "published", "target": "bfr1-abc-1",
                               "deployment_id": 4, "cache_warmed": True})
        summary = bf.build_report(self.run)
        self.assertIn("bfr1-abc-1", summary["markdown"])
        self.assertIn("bfr1-abc-1", [s["label"] for s in summary["staging"]])

    def test_a_cutoff_snapshot_is_reported_as_a_cutoff_with_both_instants(self):
        rows = [{"id": "prj_a", "name": "a", "latestProductionUrl": "https://a/", "updatedAt": 1}]
        self.run.write_json("inventory.json", {
            "rows": rows, "digest": bf.digest(rows), "converged": False, "cutoff": True,
            "walks": 3, "started_at": 100, "completed_at": 260})
        self.run.write_json("mapping.json", {"rows": [], "digest": bf.digest([])})
        self.run.write_json("outcomes.json", {"rows": [], "halted": False})
        summary = bf.build_report(self.run)
        self.assertTrue(summary["cutoff"])
        self.assertIn("100", summary["markdown"])
        self.assertIn("260", summary["markdown"])


if __name__ == "__main__":  # pragma: no cover
    sys.exit(unittest.main())
