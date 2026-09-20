"""`harness.convention` — resolving a hostname to a GitHub document with NO registry row.

Owner decision D38: a document is reachable the moment its html file exists in a repository.
Nothing publishes it, nothing registers it, and nothing has to be run first.
"""
import pytest

from harness.convention import split_label


REPOS = ["rawgentic", "herdr-dashboard", "claude-skills", "3dstories-fleet", "herdr"]


class TestSplitLabel:
    """A hostname carries three parts and TWO of them may contain hyphens, so the repository
    list is what makes the split decidable. Without it `herdr-dashboard-107-usage` could be the
    repo `herdr` and the document `dashboard-107-usage`, and both readings are grammatical."""

    def test_the_owners_worked_example(self):
        assert split_label("2026-08-19-rawgentic-unified-roadmap", REPOS) == (
            "2026-08-19", "rawgentic", "unified-roadmap")

    def test_a_repository_name_containing_hyphens(self):
        assert split_label("2026-08-04-herdr-dashboard-107-usage-strip-redesign", REPOS) == (
            "2026-08-04", "herdr-dashboard", "107-usage-strip-redesign")

    def test_the_longest_matching_repository_wins(self):
        # `herdr` and `herdr-dashboard` both prefix this label. The longer one is the only
        # reading that does not silently serve one repository's document under another's name.
        date, repo, rest = split_label("2026-08-04-herdr-dashboard-x", REPOS)
        assert repo == "herdr-dashboard"
        assert rest == "x"

    def test_a_label_with_no_date_prefix(self):
        assert split_label("rawgentic-campaign-log", REPOS) == (
            None, "rawgentic", "campaign-log")

    def test_a_repository_that_is_not_in_the_list_is_unresolvable(self):
        # Refusing is the point: guessing a repository would let any hostname trigger a GitHub
        # request for a repository name an outsider chose.
        assert split_label("2026-08-19-notarepo-doc", REPOS) is None

    def test_a_label_that_is_only_a_repository_name_is_unresolvable(self):
        # There is no document part, so there is nothing to serve.
        assert split_label("rawgentic", REPOS) is None

    def test_a_date_shaped_prefix_that_is_not_a_date_is_treated_as_part_of_the_name(self):
        assert split_label("9999-99-99-rawgentic-x", REPOS) is None


from harness.convention import DocumentAmbiguous, find_document
from harness.github import TreeEntry


def entry(path, mode="100644"):
    return TreeEntry(path=path, type="blob", mode=mode, blob_id="b" * 40, size=10)


class TestFindDocument:
    """The tree is searched for the document's FILE. The dated filename is tried first, because
    most documents carry their date in the name; the undated one is the fallback for a file
    whose date came from its last-modified time instead."""

    def test_the_dated_filename_is_found(self):
        got = find_document([entry("docs/planning/2026-08-19-unified-roadmap.html")],
                            "2026-08-19", "unified-roadmap")
        assert got.path == "docs/planning/2026-08-19-unified-roadmap.html"

    def test_the_undated_filename_is_the_fallback(self):
        # `blarg.html` landing today is served at `2026-08-24-rawgentic-blarg`, so the date in
        # the hostname is not in the filename and must not be required to be.
        got = find_document([entry("docs/blarg.html")], "2026-08-24", "blarg")
        assert got.path == "docs/blarg.html"

    def test_the_dated_filename_wins_when_both_exist(self):
        got = find_document([entry("docs/blarg.html"),
                             entry("docs/2026-08-24-blarg.html")], "2026-08-24", "blarg")
        assert got.path == "docs/2026-08-24-blarg.html"

    def test_a_label_with_no_date_finds_the_undated_file(self):
        got = find_document([entry("docs/campaign-log.html")], None, "campaign-log")
        assert got.path == "docs/campaign-log.html"

    def test_a_document_that_is_not_there_is_None(self):
        assert find_document([entry("docs/other.html")], "2026-08-19", "unified-roadmap") is None

    def test_two_files_of_the_same_name_in_different_directories_are_REFUSED(self):
        # Serving either one would be a coin toss the reader cannot see. Refusing is the same
        # rule the backfill uses for an ambiguous mapping.
        with pytest.raises(DocumentAmbiguous):
            find_document([entry("docs/a/x.html"), entry("docs/b/x.html")], None, "x")

    def test_a_symlink_is_never_served(self):
        # A symlink's target is decided by the repository, not by this service, so following one
        # would let a document point anywhere the harness can read.
        assert find_document([entry("docs/x.html", mode="120000")], None, "x") is None

    def test_a_tree_entry_that_is_not_a_blob_is_ignored(self):
        directory = TreeEntry(path="docs/x.html", type="tree", mode="040000",
                              blob_id="c" * 40, size=None)
        assert find_document([directory], None, "x") is None


import hashlib

from harness.convention import ConventionResolver
from harness.github import Budget, FakeGitHub

PAGE = b"<!doctype html><title>blarg</title>"
BLOB = "a" * 40
COMMIT = "c" * 40


def budget():
    return Budget(60.0, 20, lambda: 0.0)


def source(tree_paths=("docs/planning/2026-08-19-unified-roadmap.html",), repos=("rawgentic",)):
    return FakeGitHub(
        trees={("3D-Stories/rawgentic", COMMIT): [
            {"path": p, "type": "blob", "mode": "100644", "sha": BLOB, "size": len(PAGE)}
            for p in tree_paths]},
        blobs={("3D-Stories/rawgentic", BLOB): PAGE},
        commits={("3D-Stories/rawgentic", "HEAD"): COMMIT},
        repos=list(repos))


class TestConventionResolver:
    def test_a_hostname_resolves_to_a_servable_deployment(self):
        got = ConventionResolver("3D-Stories", source()).resolve(
            "2026-08-19-rawgentic-unified-roadmap", budget())
        assert got is not None
        assert got.repo == "3D-Stories/rawgentic"
        assert got.commit_sha == COMMIT
        assert got.name == "2026-08-19-rawgentic-unified-roadmap"
        assert got.entry_path == "/index.html"
        asset = got.assets["/index.html"]
        assert asset.repo_path == "docs/planning/2026-08-19-unified-roadmap.html"
        assert asset.sha256 == hashlib.sha256(PAGE).hexdigest()
        assert asset.content_type.startswith("text/html")

    def test_an_undated_file_resolves_under_a_dated_hostname(self):
        # `blarg.html` landing today is reachable at `2026-08-24-rawgentic-blarg`.
        got = ConventionResolver("3D-Stories", source(("docs/blarg.html",))).resolve(
            "2026-08-24-rawgentic-blarg", budget())
        assert got is not None
        assert got.assets["/index.html"].repo_path == "docs/blarg.html"

    def test_an_unknown_repository_never_reaches_github(self):
        # The repository list is checked FIRST, so a hostname an outsider picked cannot make
        # this service fetch a repository name of their choosing.
        src = source()
        assert ConventionResolver("3D-Stories", src).resolve(
            "2026-08-19-somebody-elses-repo-x", budget()) is None
        assert src.tree_calls == 0
        assert src.commit_calls == 0

    def test_a_document_that_does_not_exist_is_None(self):
        got = ConventionResolver("3D-Stories", source()).resolve(
            "2026-08-19-rawgentic-nothing-here", budget())
        assert got is None

    def test_the_repository_list_is_fetched_once_and_reused(self):
        src = source()
        resolver = ConventionResolver("3D-Stories", src)
        resolver.resolve("2026-08-19-rawgentic-unified-roadmap", budget())
        resolver.resolve("2026-08-19-rawgentic-unified-roadmap", budget())
        assert src.repos_calls == 1

    def test_a_truncated_tree_is_refused_rather_than_read_as_absent(self):
        # A truncated tree cannot prove a document is missing, and reporting 404 from one would
        # tell a reader their document does not exist when it does.
        src = source()
        src._truncated.add(("3D-Stories/rawgentic", COMMIT))
        with pytest.raises(Exception):
            ConventionResolver("3D-Stories", src).resolve(
                "2026-08-19-rawgentic-unified-roadmap", budget())


from harness.convention import label_for


class TestLabelFor:
    """The INVERSE of `split_label`. The index generates links with it, so if the two ever
    disagreed the index would publish links that resolve to nothing."""

    def test_the_owners_worked_example(self):
        assert label_for("rawgentic", "docs/planning/2026-08-19-unified-roadmap.html") == \
            "2026-08-19-rawgentic-unified-roadmap"

    def test_a_file_with_no_date_omits_the_date(self):
        assert label_for("rawgentic", "docs/campaign-log.html") == "rawgentic-campaign-log"

    def test_it_is_lowercased(self):
        assert label_for("MyRepo", "d/2026-08-19-My-Doc.HTML") == "2026-08-19-myrepo-my-doc"

    def test_an_over_long_label_is_trimmed_to_the_dns_limit(self):
        got = label_for("thewanderinginn",
                        "docs/2026-08-17-166-manifest-overwrite-discards-spans.html")
        assert len(got) == 63
        assert not got.endswith("-")

    @pytest.mark.parametrize("repo,path", [
        ("rawgentic", "docs/planning/2026-08-19-unified-roadmap.html"),
        ("rawgentic", "docs/campaign-log.html"),
        ("herdr-dashboard", "docs/2026-08-04-107-usage-strip-redesign.html"),
    ])
    def test_every_generated_label_splits_back_to_its_repository(self, repo, path):
        # The round trip is the whole point: a link the index prints must resolve.
        label = label_for(repo, path)
        split = split_label(label, ["rawgentic", "herdr-dashboard", "herdr", "thewanderinginn"])
        assert split is not None, label
        assert split[1] == repo


from harness.convention import ConventionIndex


def index_source(**per_repo):
    """A fake whose repositories each carry the html paths given."""
    trees, commits, repos = {}, {}, []
    for repo, paths in per_repo.items():
        repo = repo.replace("_", "-")
        full = "3D-Stories/%s" % repo
        sha = (repo[:1] * 40)[:40]
        repos.append(repo)
        commits[(full, "HEAD")] = sha
        trees[(full, sha)] = [
            {"path": p, "type": "blob", "mode": "100644", "sha": BLOB, "size": 10}
            for p in paths]
    return FakeGitHub(trees=trees, commits=commits, repos=repos)


class TestConventionIndex:
    """The index is built by WALKING the repositories, because convention-resolved documents
    have no registry rows to read."""

    def test_it_lists_a_document_from_every_repository(self):
        src = index_source(rawgentic=["docs/planning/2026-08-19-unified-roadmap.html"],
                           saystory=["docs/design-log.html"])
        snap = ConventionIndex("3D-Stories", src).snapshot(budget())
        names = sorted(r["name"] for r in snap["rows"])
        assert names == ["2026-08-19-rawgentic-unified-roadmap", "saystory-design-log"]
        assert sorted(snap["projects"]) == ["rawgentic", "saystory"]

    def test_files_outside_the_documents_directory_are_not_listed(self):
        # A repository's application assets and test fixtures are not design documents. They
        # remain SERVABLE by hostname; they are simply not advertised.
        src = index_source(rawgentic=["docs/a.html", "src/templates/widget.html",
                                      "archive/old.html"])
        snap = ConventionIndex("3D-Stories", src).snapshot(budget())
        assert [r["name"] for r in snap["rows"]] == ["rawgentic-a"]

    def test_a_name_that_appears_twice_in_one_repository_is_not_listed(self):
        # It cannot be served — `find_document` refuses it — so advertising it would print a
        # link that answers 409.
        src = index_source(rawgentic=["docs/a/x.html", "docs/b/x.html", "docs/ok.html"])
        snap = ConventionIndex("3D-Stories", src).snapshot(budget())
        assert [r["name"] for r in snap["rows"]] == ["rawgentic-ok"]

    def test_a_repository_that_cannot_be_read_does_not_empty_the_index(self):
        # One unreadable repository must not turn the whole index into a confident blank page.
        from harness.github import Unauthorized
        src = index_source(rawgentic=["docs/a.html"], secret=["docs/b.html"])
        src._errors[("3D-Stories/secret", "HEAD")] = Unauthorized("nope")
        snap = ConventionIndex("3D-Stories", src).snapshot(budget())
        assert [r["name"] for r in snap["rows"]] == ["rawgentic-a"]
        assert snap["unreadable"] == ["secret"]

    def test_the_walk_is_cached_and_reused(self):
        src = index_source(rawgentic=["docs/a.html"])
        idx = ConventionIndex("3D-Stories", src)
        idx.snapshot(budget()); idx.snapshot(budget())
        assert src.tree_calls == 1

    def test_the_generation_changes_when_the_documents_change(self):
        one = ConventionIndex("3D-Stories", index_source(rawgentic=["docs/a.html"])
                              ).snapshot(budget())
        two = ConventionIndex("3D-Stories", index_source(rawgentic=["docs/a.html",
                                                                    "docs/b.html"])
                              ).snapshot(budget())
        assert one["generation"] != two["generation"]

    def test_every_listed_name_resolves_back_to_its_repository(self):
        # The index must never print a link that cannot be read back.
        src = index_source(rawgentic=["docs/planning/2026-08-19-unified-roadmap.html"],
                           herdr_dashboard=["docs/2026-08-04-107-usage.html"])
        idx = ConventionIndex("3D-Stories", src)
        snap = idx.snapshot(budget())
        repos = src.repos("3D-Stories", budget())
        for row in snap["rows"]:
            split = split_label(row["name"], repos)
            assert split is not None, row["name"]
            assert split[1] == row["project"]


class TestIndexOrdering:
    """Owner request 2026-08-24: the index is ordered by LAST UPDATED. The renderer already
    sorts newest-first; it had no dates to sort by, because every row carried an empty one."""

    def test_a_row_carries_the_files_last_commit_date(self):
        src = index_source(rawgentic=["docs/a.html"])
        src._dates[("3D-Stories/rawgentic", "docs/a.html")] = "2026-08-19T10:11:12Z"
        snap = ConventionIndex("3D-Stories", src).snapshot(budget())
        assert snap["rows"][0]["published_at"] == "2026-08-19T10:11:12Z"

    def test_a_date_is_cached_by_blob_so_an_unchanged_file_is_asked_once(self):
        # 460 documents is 460 extra calls on a cold walk. Keying the cache on the BLOB means a
        # refresh only pays for the files that actually changed.
        src = index_source(rawgentic=["docs/a.html"])
        src._dates[("3D-Stories/rawgentic", "docs/a.html")] = "2026-08-19T10:11:12Z"
        idx = ConventionIndex("3D-Stories", src, ttl=0.0)
        idx.snapshot(budget())
        idx.snapshot(budget())
        assert src.date_calls == 1

    def test_a_file_whose_date_cannot_be_read_is_still_listed(self):
        # Dropping it would hide a real document because of an API hiccup. The renderer already
        # sinks a row with no time to the bottom.
        from harness.github import Unavailable
        src = index_source(rawgentic=["docs/a.html"])

        def boom(*a, **k):
            raise Unavailable("no")
        src.last_commit_date = boom
        snap = ConventionIndex("3D-Stories", src).snapshot(budget())
        assert [r["name"] for r in snap["rows"]] == ["rawgentic-a"]
        assert snap["rows"][0]["published_at"] == ""


class TestLabelDateFallback:
    """Owner request 2026-08-24: every document URL carries a date. The filename's own date is
    used when it has one; otherwise the date GitHub reports for the file's last change.

    97 of 428 listed documents had no date in the name, so their URLs had none either."""

    def test_the_filename_date_still_wins(self):
        assert label_for("rawgentic", "docs/2026-08-19-unified-roadmap.html",
                         fallback_date="2020-01-01T00:00:00Z") == \
            "2026-08-19-rawgentic-unified-roadmap"

    def test_a_dateless_filename_takes_the_github_date(self):
        assert label_for("rawgentic", "docs/campaign-log.html",
                         fallback_date="2026-08-24T09:10:11Z") == \
            "2026-08-24-rawgentic-campaign-log"

    def test_no_fallback_still_gives_a_dateless_label(self):
        assert label_for("rawgentic", "docs/campaign-log.html") == "rawgentic-campaign-log"

    def test_a_fallback_that_is_not_a_date_is_ignored_rather_than_pasted_in(self):
        # The value comes from an API response, so a junk one must not become a hostname.
        assert label_for("rawgentic", "docs/x.html", fallback_date="not-a-date") == "rawgentic-x"

    def test_a_label_built_from_the_fallback_still_resolves(self):
        # The URL says 2026-08-24 and the FILE is `campaign-log.html`. `find_document` tries the
        # dated filename first and the undated one second, which is what makes this work.
        label = label_for("rawgentic", "docs/campaign-log.html",
                          fallback_date="2026-08-24T09:10:11Z")
        date, repo, doc = split_label(label, ["rawgentic"])
        assert (date, repo, doc) == ("2026-08-24", "rawgentic", "campaign-log")
        assert find_document([entry("docs/campaign-log.html")], date, doc) is not None


def test_every_index_row_url_carries_a_date_when_github_supplies_one():
    src = index_source(rawgentic=["docs/campaign-log.html"])
    src._dates[("3D-Stories/rawgentic", "docs/campaign-log.html")] = "2026-08-24T09:10:11Z"
    snap = ConventionIndex("3D-Stories", src).snapshot(budget())
    assert snap["rows"][0]["name"] == "2026-08-24-rawgentic-campaign-log"


def test_the_url_uses_when_the_file_was_added_and_the_order_uses_when_it_changed():
    """Owner decision 2026-08-24. A URL dated by LAST change moves every time somebody edits
    the file, so a link shared yesterday 404s. Dating it by when the file was ADDED keeps the
    link stable forever, and the index still sorts on the last change."""
    src = index_source(rawgentic=["docs/campaign-log.html"])
    src._dates[("3D-Stories/rawgentic", "docs/campaign-log.html")] = (
        "2026-03-01T09:00:00Z", "2026-08-24T09:10:11Z")
    row = ConventionIndex("3D-Stories", src).snapshot(budget())["rows"][0]
    assert row["name"] == "2026-03-01-rawgentic-campaign-log"
    assert row["published_at"] == "2026-08-24T09:10:11Z"


# ---------------------------------------------------------------------------------------
# #65: the index stops rebuilding on the reader's request.
#
# Every no-block assertion below is CAUSAL, never a stopwatch. The fake source blocks on an
# Event the test controls, so "it returned without walking" is proved by the walk being
# provably impossible until the test says so. A wall-clock threshold would pass on a fast
# machine and flake on a slow one, and would prove nothing either way.
# ---------------------------------------------------------------------------------------

import threading

from harness.convention import IndexBuilding, IndexCoolingDown, IndexTooStale
from harness.github import Budget, BudgetExhausted, GitHubError, Unauthorized, Unavailable


def wide_budget():
    """The shared `budget()` caps at 20 calls; a multi-repository walk needs more."""
    return Budget(60.0, 500, lambda: 0.0)


class GateSource(FakeGitHub):
    """A source whose repository walk cannot finish until the test releases it."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.entered = threading.Event()      # set the moment the walk touches the source
        self.release = threading.Event()      # the walk waits here
        self.release.set()                    # open by default
        self.fail_with = None

    def commit(self, repo, ref, budget, http_timeout: float = 20.0):
        self.entered.set()
        self.release.wait(5)
        if self.fail_with is not None:
            raise self.fail_with
        return super().commit(repo, ref, budget, http_timeout)


def gate_source(**per_repo):
    trees, commits, repos = {}, {}, []
    for repo, paths in per_repo.items():
        repo = repo.replace("_", "-")
        full = "3D-Stories/%s" % repo
        sha = (repo[:1] * 40)[:40]
        repos.append(repo)
        commits[(full, "HEAD")] = sha
        trees[(full, sha)] = [
            {"path": p, "type": "blob", "mode": "100644", "sha": BLOB, "size": 10} for p in paths]
    return GateSource(trees=trees, commits=commits, repos=repos)


def swr_index(src, **kw):
    """An index wired the way `app.py` wires it: with a refresh budget, so SWR is live."""
    kw.setdefault("ttl", 900.0)
    kw.setdefault("refresh_budget", budget)
    return ConventionIndex("3D-Stories", src, **kw)


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class TestStaleWhileRevalidate:
    def test_a_stale_reader_is_served_without_the_walk_being_entered(self):
        """AC1. The assertion is causal: the source is gated shut, so a snapshot that came
        back at all cannot have come from a fresh walk."""
        src = gate_source(rawgentic=["docs/a.html"])
        clock = FakeClock()
        idx = swr_index(src, monotonic=clock)
        first = idx.snapshot(budget())
        assert src.tree_calls == 1

        src.release.clear()                   # the walk can no longer finish
        src.entered.clear()
        clock.t += 901.0                      # past the TTL

        served = idx.snapshot(budget())
        assert served is first                # the SAME object, not a rebuilt one
        src.release.set()

    def test_the_refreshed_snapshot_replaces_the_stale_one(self):
        """AC2."""
        src = gate_source(rawgentic=["docs/a.html"])
        clock = FakeClock()
        idx = swr_index(src, monotonic=clock)
        first = idx.snapshot(budget())

        src._trees[("3D-Stories/rawgentic", "r" * 40)].append(
            _entry_for("docs/b.html"))
        clock.t += 901.0
        assert idx.snapshot(budget()) is first          # stale, served at once

        # Settle on the snapshot being INSTALLED, not on the call having been made. The build
        # makes its tree call before it publishes, so counting calls races the install.
        assert _settle(lambda: idx.snapshot(budget()) is not first), "refresh never landed"
        later = idx.snapshot(budget())
        assert later is not first
        assert [r["name"] for r in later["rows"]] == ["rawgentic-a", "rawgentic-b"]

    def test_two_concurrent_stale_readers_trigger_exactly_one_walk(self):
        """AC3."""
        src = gate_source(rawgentic=["docs/a.html"])
        clock = FakeClock()
        idx = swr_index(src, monotonic=clock)
        idx.snapshot(budget())
        assert src.tree_calls == 1

        src.release.clear()
        clock.t += 901.0
        start = threading.Barrier(4)

        def reader():
            start.wait()
            idx.snapshot(budget())

        ts = [threading.Thread(target=reader) for _ in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(5)
        src.release.set()
        _settle(lambda: src.tree_calls == 2)
        assert src.tree_calls == 2            # one original + exactly one refresh

    def test_a_failed_refresh_leaves_the_previous_snapshot_and_never_reaches_the_reader(self):
        """AC6, warm half."""
        src = gate_source(rawgentic=["docs/a.html"])
        clock = FakeClock()
        idx = swr_index(src, monotonic=clock)
        first = idx.snapshot(budget())

        src.fail_with = Unavailable("github is down")
        clock.t += 901.0
        assert idx.snapshot(budget()) is first          # no exception reaches here

        # The settle predicate must NOT be "the snapshot is still `first`" — that is true from
        # the moment the refresh is kicked, so the test would finish before the injected
        # failure happened and pass without checking anything (review finding, 2026-09-15).
        # Wait for the build to actually END, then assert what survived it.
        assert _settle(lambda: idx._building is False), "the refresh never finished"
        assert idx.snapshot(budget()) is first
        assert idx._cooldown_until > clock.t, "a failed build must start the cool-off"

    def test_without_a_refresh_budget_a_stale_read_rebuilds_inline_exactly_as_before(self):
        """The opt-in seam. Every pre-#65 caller keeps its old semantics."""
        src = index_source(rawgentic=["docs/a.html"])
        idx = ConventionIndex("3D-Stories", src, ttl=0.0)     # no refresh_budget
        idx.snapshot(budget())
        idx.snapshot(budget())
        assert src.tree_calls == 2                            # rebuilt on the reader's thread


class TestColdBuild:
    def test_a_cold_failure_still_reaches_the_reader(self):
        """AC6, cold half — `app.py` turns this into the existing 503."""
        src = gate_source(rawgentic=["docs/a.html"])
        src.fail_with = Unavailable("github is down")
        idx = swr_index(src)
        with pytest.raises(Unavailable):
            idx.snapshot(budget())

    def test_a_second_cold_caller_is_refused_at_once_rather_than_blocking(self):
        """Only the leader may block. Enough blocked readers would occupy every waitress
        worker, and document requests — which never touch the index — would stop being served.
        Same rule as `publish_slots` in app.py."""
        src = gate_source(rawgentic=["docs/a.html"])
        src.release.clear()
        idx = swr_index(src)
        leader_done = []

        def leader():
            leader_done.append(idx.snapshot(budget()))

        t = threading.Thread(target=leader)
        t.start()
        assert src.entered.wait(5)            # the leader is inside the walk

        with pytest.raises(IndexBuilding):
            idx.snapshot(budget())            # returns immediately, does not join the wait

        src.release.set()
        t.join(5)
        assert leader_done and leader_done[0]["rows"]

    def test_a_cold_caller_inside_the_cool_off_is_told_when_to_come_back(self):
        src = gate_source(rawgentic=["docs/a.html"])
        src.fail_with = Unavailable("github is down")
        clock = FakeClock()
        idx = swr_index(src, monotonic=clock)
        with pytest.raises(Unavailable):
            idx.snapshot(budget())

        clock.t += 10.0
        with pytest.raises(IndexCoolingDown) as caught:
            idx.snapshot(budget())
        assert caught.value.retry_after == 50          # 60s cool-off, 10 elapsed

        clock.t += 51.0
        src.fail_with = None
        assert idx.snapshot(budget())["rows"]          # the cool-off expired, a build ran


class TestFailureCoolOff:
    def test_a_failed_refresh_does_not_start_another_on_the_next_request(self):
        """Without this, a GitHub outage turns every cached read into a fresh 61-repository
        walk attempt — a request storm caused by the caching feature."""
        src = gate_source(rawgentic=["docs/a.html"])
        clock = FakeClock()
        idx = swr_index(src, monotonic=clock)
        idx.snapshot(budget())
        src.fail_with = Unavailable("down")
        clock.t += 901.0
        idx.snapshot(budget())
        _settle(lambda: src.commit_calls >= 2)
        after_first_failure = src.commit_calls

        for _ in range(5):
            clock.t += 1.0
            idx.snapshot(budget())
        assert src.commit_calls == after_first_failure

        clock.t += 61.0
        src.fail_with = None
        idx.snapshot(budget())
        _settle(lambda: src.commit_calls > after_first_failure)
        assert src.commit_calls > after_first_failure


class TestThreadStartFailure:
    def test_a_thread_that_cannot_start_does_not_freeze_the_index_for_ever(self):
        """If `_building` were set before a `start()` that raises, the target never runs its
        `finally`, and every later request suppresses the refresh until the process restarts —
        the exact invariant the `finally` exists to protect."""
        src = gate_source(rawgentic=["docs/a.html"])
        clock = FakeClock()
        calls = {"n": 0}

        class Refusing:
            def __init__(self, **kw):
                self._kw = kw

            def start(self):
                calls["n"] += 1
                raise RuntimeError("can't start new thread")

        idx = swr_index(src, monotonic=clock, thread_factory=Refusing)
        first = idx.snapshot(budget())
        clock.t += 901.0
        assert idx.snapshot(budget()) is first         # stale served, no crash
        assert calls["n"] == 1

        clock.t += 61.0                                # past the cool-off
        idx.snapshot(budget())
        assert calls["n"] == 2                         # it tried again: not frozen


class TestMaxStaleAge:
    def test_a_snapshot_past_the_bound_is_refused_rather_than_served(self):
        src = gate_source(rawgentic=["docs/a.html"])
        clock = FakeClock()
        idx = swr_index(src, monotonic=clock, max_stale_age=3600.0)
        idx.snapshot(budget())
        src.fail_with = Unavailable("down")

        clock.t += 901.0
        assert idx.snapshot(budget())["rows"]          # stale but inside the bound
        # The bound now fires on EVIDENCE that refreshing fails, never on the listing's age
        # alone, so the failed refresh that read started has to have landed before it can
        # refuse. Age alone could not tell a real outage from a night with no visitor.
        assert _settle(lambda: idx._refresh_failing), "the failed refresh never landed"
        clock.t += 3601.0
        with pytest.raises(IndexTooStale):
            idx.snapshot(budget())

    def test_zero_means_no_bound(self):
        src = gate_source(rawgentic=["docs/a.html"])
        clock = FakeClock()
        idx = swr_index(src, monotonic=clock, max_stale_age=0.0)
        idx.snapshot(budget())
        src.fail_with = Unavailable("down")
        clock.t += 999999.0
        assert idx.snapshot(budget())["rows"]

    def test_a_quiet_period_is_not_an_outage(self):
        """The falsifying case the rest of this class cannot reach.

        Every other test here breaks the source BEFORE advancing the clock, so each one can
        only confirm that the bound fires when GitHub really is down. None of them asks what
        happens when GitHub is perfectly healthy and the listing simply went unread. That is
        the ordinary night of a personal index: a refresh only runs when a reader arrives, so
        an unvisited listing ages past the bound with no failure anywhere, and the next reader
        was refused under a message blaming GitHub for a walk nobody had attempted.
        """
        src = gate_source(rawgentic=["docs/a.html"])
        clock = FakeClock()
        idx = swr_index(src, monotonic=clock, max_stale_age=3600.0)
        first = idx.snapshot(budget())

        # The source is never broken. `fail_with` is left alone deliberately.
        clock.t += 7201.0                              # twice the bound, entirely unread

        assert idx.snapshot(budget())["rows"] == first["rows"]

    def test_a_recovered_refresh_disarms_the_bound(self):
        """The other half of the same flag, and the one that would fail silently.

        If a success never cleared it, a single failed refresh would arm the bound for the
        life of the process, and a service whose GitHub came back would go on refusing every
        listing it was asked for until somebody restarted it.
        """
        src = gate_source(rawgentic=["docs/a.html"])
        clock = FakeClock()
        idx = swr_index(src, monotonic=clock, max_stale_age=3600.0)
        first = idx.snapshot(budget())

        src.fail_with = Unavailable("down")
        clock.t += 901.0
        idx.snapshot(budget())
        assert _settle(lambda: idx._refresh_failing), "the failed refresh never landed"

        src.fail_with = None                           # GitHub comes back
        clock.t += 901.0
        idx.snapshot(budget())
        assert _settle(lambda: idx._refresh_failing is False), "the refresh never recovered"

        clock.t += 7201.0                              # a long quiet gap AFTER recovery
        assert idx.snapshot(budget())["rows"] == first["rows"]

    def test_the_bound_is_honoured_when_a_refresh_thread_cannot_start(self):
        """The one path that returns the stale snapshot from outside the normal branch."""
        class Refusing:
            def __init__(self, **kw):
                pass

            def start(self):
                raise RuntimeError("can't start new thread")

        src = gate_source(rawgentic=["docs/a.html"])
        clock = FakeClock()
        idx = swr_index(src, monotonic=clock, max_stale_age=3600.0,
                        thread_factory=Refusing)
        idx.snapshot(budget())
        clock.t += 3601.0
        with pytest.raises(IndexTooStale):
            idx.snapshot(budget())


class TestFreshnessClock:
    def test_freshness_uses_the_monotonic_clock_not_the_wall_clock(self):
        """A wall-clock step — an NTP correction, a container clock jump — must not un-expire
        a snapshot, nor expire a fresh one."""
        src = gate_source(rawgentic=["docs/a.html"])
        wall = FakeClock(5000.0)
        mono = FakeClock(1000.0)
        idx = swr_index(src, now=wall, monotonic=mono)
        first = idx.snapshot(budget())
        assert first["generated_at"] == 5000.0

        wall.t -= 4000.0                       # the wall clock jumps BACKWARDS
        assert idx.snapshot(budget()) is first  # still fresh: monotonic did not move
        assert src.tree_calls == 1


def _entry_for(path):
    # FakeGitHub converts its constructor input to TreeEntry, so anything appended later must
    # already be one — a raw dict would blow up on `.type` inside the walk.
    from harness.github import TreeEntry
    return TreeEntry(path=path, type="blob", mode="100644", blob_id=BLOB, size=10)


def _settle(predicate, timeout=5.0):
    """Wait for a background build to land. A deadlock guard, never the proof of anything."""
    import time as _time
    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        if predicate():
            return True
        _time.sleep(0.01)
    return predicate()


class BarrierSource(FakeGitHub):
    """Blocks every `commit` on a barrier, so the walk only completes if N run at once.

    This is how bounded concurrency is PROVED rather than timed: on the serial walk the
    barrier is never reached by a second caller and the test deadlocks out.
    """

    def __init__(self, *a, parties=8, **kw):
        super().__init__(*a, **kw)
        self.barrier = threading.Barrier(parties, timeout=5)
        self.peak = 0
        self._inflight = 0
        self._mu = threading.Lock()

    def _enter(self):
        with self._mu:
            self._inflight += 1
            self.peak = max(self.peak, self._inflight)

    def _leave(self):
        with self._mu:
            self._inflight -= 1

    def commit(self, repo, ref, budget, http_timeout: float = 20.0):
        self._enter()
        try:
            self.barrier.wait()
            return super().commit(repo, ref, budget, http_timeout)
        finally:
            self._leave()


class DateBarrierSource(FakeGitHub):
    """Blocks every `file_dates` on a barrier — phase 2's concurrency, inside ONE repository."""

    def __init__(self, *a, parties=8, **kw):
        super().__init__(*a, **kw)
        self.barrier = threading.Barrier(parties, timeout=5)

    def file_dates(self, repo, path, budget, http_timeout: float = 20.0):
        self.barrier.wait()
        return super().file_dates(repo, path, budget, http_timeout)


def _barrier_source(cls, parties, **per_repo):
    trees, commits, repos = {}, {}, []
    for repo, paths in per_repo.items():
        repo = repo.replace("_", "-")
        full = "3D-Stories/%s" % repo
        sha = (repo[:1] * 40)[:40]
        repos.append(repo)
        commits[(full, "HEAD")] = sha
        trees[(full, sha)] = [
            {"path": p, "type": "blob", "mode": "100644", "sha": BLOB, "size": 10} for p in paths]
    return cls(trees=trees, commits=commits, repos=repos, parties=parties)


class TestConcurrentWalk:
    def test_repositories_are_walked_concurrently_up_to_the_pool_size(self):
        """AC4. Eight repositories must be in flight together or the barrier never trips.

        Measured live before this was written: 16 repositories at pool 8 took 3.05s against
        1.40s each serially, with peak in-flight exactly 8.
        """
        src = _barrier_source(BarrierSource, 8,
                              **{"r%d" % i: ["docs/a.html"] for i in range(8)})
        snap = ConventionIndex("3D-Stories", src, workers=8).snapshot(wide_budget())
        assert len(snap["rows"]) == 8
        assert src.peak == 8

    def test_documents_inside_ONE_repository_are_dated_concurrently(self):
        """The 170.87s lesson. One task per repository parallelizes across repositories but
        serializes a repository's own date calls, so the largest repository becomes the whole
        critical path. Flattening phase 2 cut the real cold walk to 52.66s.
        """
        src = _barrier_source(DateBarrierSource, 8,
                              rawgentic=["docs/d%d.html" % i for i in range(8)])
        snap = ConventionIndex("3D-Stories", src, workers=8).snapshot(wide_budget())
        assert len(snap["rows"]) == 8

    def test_the_concurrent_snapshot_is_identical_to_a_serial_one(self):
        """Completion order must not reach the output — rows, projects or the digest."""
        spec = {"r%d" % i: ["docs/a.html", "docs/b.html"] for i in range(6)}
        one = ConventionIndex("3D-Stories", index_source(**spec), workers=1).snapshot(wide_budget())
        many = ConventionIndex("3D-Stories", index_source(**spec), workers=8).snapshot(wide_budget())
        # `generated_at` is a wall-clock stamp and legitimately differs between two builds.
        one.pop("generated_at"), many.pop("generated_at")
        assert one == many


class TestSharedFailuresAreNotLocalOnes:
    """`DeadlineExceeded`, `BudgetExhausted` and `Unauthorized` all subclass `GitHubError`, and
    BOTH handlers caught the base class. So an expired token made all 61 repositories
    `unreadable`, `snapshot()` returned SUCCESSFULLY with no rows, and the page rendered as a
    confident empty index instead of the 503 it would have rendered had the call raised.
    """

    def test_a_credential_that_reads_NOTHING_fails_the_build(self):
        """`Unauthorized` is deliberately not a fatal type — GitHub answers 403 for a single
        repository a token cannot read, and killing the index over one of those is what
        `test_a_repository_that_cannot_be_read_does_not_empty_the_index` forbids. A genuinely
        dead credential needs no special case: every repository fails, so no rows are produced
        and the zero-rows guard refuses to publish the result."""
        src = index_source(a=["docs/a.html"], b=["docs/b.html"])
        src._errors[("3D-Stories/a", "HEAD")] = Unauthorized("credential refused")
        src._errors[("3D-Stories/b", "HEAD")] = Unauthorized("credential refused")
        with pytest.raises(GitHubError):
            ConventionIndex("3D-Stories", src).snapshot(budget())

    def test_budget_exhaustion_INSIDE_file_dates_fails_the_build(self):
        """The exact hole the reviewer found. `_dates_for` has its own `except GitHubError`,
        so it swallowed budget exhaustion before any per-repository re-raise could see it, and
        the walk carried on publishing blank dates."""
        src = index_source(rawgentic=["docs/a.html"])

        def boom(*_a, **_k):
            raise BudgetExhausted("out of calls")

        src.file_dates = boom
        with pytest.raises(BudgetExhausted):
            ConventionIndex("3D-Stories", src).snapshot(budget())

    def test_an_ordinary_single_repository_failure_is_still_only_unreadable(self):
        # The pre-existing behaviour this must not regress.
        src = index_source(rawgentic=["docs/a.html"], secret=["docs/b.html"])
        src._errors[("3D-Stories/secret", "HEAD")] = Unavailable("hiccup")
        snap = ConventionIndex("3D-Stories", src).snapshot(budget())
        assert [r["name"] for r in snap["rows"]] == ["rawgentic-a"]
        assert snap["unreadable"] == ["secret"]


class TestPublicationGuards:
    def test_a_build_with_no_rows_and_an_unreadable_repository_is_a_failure(self):
        """Cold. Otherwise a total outage renders a confident empty page."""
        src = index_source(a=["docs/a.html"])
        src._errors[("3D-Stories/a", "HEAD")] = Unavailable("hiccup")
        with pytest.raises(GitHubError):
            ConventionIndex("3D-Stories", src).snapshot(budget())

    def test_an_org_with_genuinely_no_documents_still_publishes_an_empty_listing(self):
        # Nothing FAILED here, so an empty listing is the truth and must be served.
        src = index_source(a=["src/not-a-doc.html"])
        snap = ConventionIndex("3D-Stories", src).snapshot(budget())
        assert snap["rows"] == []
        assert snap["unreadable"] == []

    def test_a_build_where_every_date_lookup_failed_is_a_failure(self):
        """A blank date changes a dateless document's hostname, so a systemic date outage
        would silently break every shared link at once."""
        src = index_source(rawgentic=["docs/a.html", "docs/b.html"])

        def boom(*_a, **_k):
            raise Unavailable("commits api is down")

        src.file_dates = boom
        with pytest.raises(GitHubError):
            ConventionIndex("3D-Stories", src).snapshot(budget())

    def test_ONE_failed_date_lookup_still_lists_its_document(self):
        """`convention.py` has always listed a document whose dates could not be read, and
        that is deliberate: dropping it would hide a real document over one API hiccup."""
        src = index_source(rawgentic=["docs/a.html", "docs/b.html"])
        real = src.file_dates

        def flaky(repo, path, budget_, http_timeout=20.0):
            if path.endswith("a.html"):
                raise Unavailable("hiccup")
            return real(repo, path, budget_, http_timeout)

        src.file_dates = flaky
        snap = ConventionIndex("3D-Stories", src).snapshot(budget())
        assert sorted(r["name"] for r in snap["rows"]) == ["rawgentic-a", "rawgentic-b"]


class TestCarryForward:
    def test_a_repository_that_fails_on_a_REFRESH_keeps_its_rows(self):
        """One transient hiccup must not make ~200 documents vanish from the listing for
        fifteen minutes. The cold-walk spike measured 3 transient repository failures in a
        single 61-repository walk, so this is the common case, not the exotic one."""
        src = gate_source(rawgentic=["docs/a.html"], saystory=["docs/b.html"])
        clock = FakeClock()
        idx = swr_index(src, monotonic=clock)
        first = idx.snapshot(budget())
        assert sorted(r["name"] for r in first["rows"]) == ["rawgentic-a", "saystory-b"]

        src._errors[("3D-Stories/saystory", "HEAD")] = Unavailable("hiccup")
        clock.t += 901.0
        idx.snapshot(budget())
        assert _settle(lambda: idx.snapshot(budget()) is not first), "refresh never landed"

        later = idx.snapshot(budget())
        assert sorted(r["name"] for r in later["rows"]) == ["rawgentic-a", "saystory-b"]
        assert later["unreadable"] == ["saystory"]

    def test_a_document_whose_date_lookup_fails_on_a_REFRESH_keeps_its_dates(self):
        """A blank date changes the generated hostname, so one 500 would break a shared link."""
        src = gate_source(rawgentic=["docs/campaign-log.html"])
        src._dates[("3D-Stories/rawgentic", "docs/campaign-log.html")] = (
            "2026-03-01T09:00:00Z", "2026-08-24T09:10:11Z")
        clock = FakeClock()
        idx = swr_index(src, monotonic=clock)
        first = idx.snapshot(budget())
        assert first["rows"][0]["name"] == "2026-03-01-rawgentic-campaign-log"

        # A different blob id forces a fresh lookup, and that lookup fails.
        src._trees[("3D-Stories/rawgentic", "r" * 40)] = [_entry_for_blob("docs/campaign-log.html")]

        def boom(*_a, **_k):
            raise Unavailable("commits api hiccup")

        src.file_dates = boom
        clock.t += 901.0
        idx.snapshot(budget())
        assert _settle(lambda: idx.snapshot(budget()) is not first), "refresh never landed"

        later = idx.snapshot(budget())
        assert later["rows"][0]["name"] == "2026-03-01-rawgentic-campaign-log"
        assert later["rows"][0]["published_at"] == "2026-08-24T09:10:11Z"


class TestDateStoreIntegration:
    def test_a_second_index_over_the_same_store_makes_no_date_call(self, tmp_path):
        """AC5, end to end: the point of the whole persistence task."""
        from harness.datestore import DateStore

        path = str(tmp_path / "index-dates.db")
        first_store = DateStore(path)
        first_store.initialize()
        src = index_source(rawgentic=["docs/a.html"])
        src._dates[("3D-Stories/rawgentic", "docs/a.html")] = ("2026-01-01", "2026-02-02")
        ConventionIndex("3D-Stories", src, store=first_store).snapshot(budget())
        assert src.date_calls == 1
        first_store.close()

        second_store = DateStore(path)
        second_store.initialize()
        src2 = index_source(rawgentic=["docs/a.html"])
        src2._dates[("3D-Stories/rawgentic", "docs/a.html")] = ("2026-01-01", "2026-02-02")
        snap = ConventionIndex("3D-Stories", src2, store=second_store).snapshot(budget())
        assert src2.date_calls == 0
        assert snap["rows"][0]["published_at"] == "2026-02-02"

    def test_a_failed_date_lookup_is_never_written_to_the_store(self, tmp_path):
        """Persisting a blank would poison every future restart with a permanent wrong date."""
        from harness.datestore import DateStore

        store_ = DateStore(str(tmp_path / "index-dates.db"))
        store_.initialize()
        src = index_source(rawgentic=["docs/a.html", "docs/b.html"])
        real = src.file_dates

        def flaky(repo, path, budget_, http_timeout=20.0):
            if path.endswith("a.html"):
                raise Unavailable("hiccup")
            return real(repo, path, budget_, http_timeout)

        src.file_dates = flaky
        ConventionIndex("3D-Stories", src, store=store_).snapshot(budget())
        assert store_.get(("3D-Stories/rawgentic", "docs/a.html", BLOB)) is None

    def test_an_unavailable_store_changes_nothing(self, tmp_path):
        from harness.datestore import DateStore

        store_ = DateStore("/proc/not-writable/index-dates.db", log=lambda _m: None)
        store_.initialize()
        assert store_.available is False
        src = index_source(rawgentic=["docs/a.html"])
        snap = ConventionIndex("3D-Stories", src, store=store_).snapshot(budget())
        assert [r["name"] for r in snap["rows"]] == ["rawgentic-a"]


def _entry_for_blob(path, blob="z" * 40):
    from harness.github import TreeEntry
    return TreeEntry(path=path, type="blob", mode="100644", blob_id=blob, size=10)


class TestReviewFindings65:
    """Findings from the cross-model code review of this change. Each one is a real path that
    the tests written alongside the implementation did not reach."""

    def test_a_refresh_budget_factory_that_raises_does_not_freeze_the_index(self):
        """`self._refresh_budget()` is evaluated BEFORE `_run_build` is entered, so a factory
        that raises never reaches that method's `finally`. `_building` would stay set for the
        life of the process, every later stale reader would trigger no walk at all, and the
        index would freeze on its last snapshot — the same freeze the `thread.start()` guard
        prevents, one level further down."""
        src = gate_source(rawgentic=["docs/a.html"])
        clock = FakeClock()
        calls = {"n": 0}

        def broken_budget():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("no budget for you")
            return budget()

        idx = swr_index(src, monotonic=clock, refresh_budget=broken_budget)
        first = idx.snapshot(budget())
        clock.t += 901.0
        assert idx.snapshot(budget()) is first
        assert _settle(lambda: idx._building is False), "the build flag was never cleared"

        clock.t += 61.0                                  # past the cool-off the failure started
        idx.snapshot(budget())
        assert _settle(lambda: idx.snapshot(budget()) is not first), "the index froze"

    def test_a_rate_limit_is_fatal_while_a_single_repository_refusal_is_not(self):
        """GitHub answers 403 for both. One is this repository's problem; the other is every
        repository's, and swallowing it records sixty readable repositories as unreadable and
        publishes that as a success."""
        from harness.github import RateLimited

        limited = index_source(a=["docs/a.html"], b=["docs/b.html"])
        limited._errors[("3D-Stories/b", "HEAD")] = RateLimited("rate limit exhausted")
        with pytest.raises(RateLimited):
            ConventionIndex("3D-Stories", limited).snapshot(budget())

        refused = index_source(a=["docs/a.html"], b=["docs/b.html"])
        refused._errors[("3D-Stories/b", "HEAD")] = Unauthorized("cannot read that repository")
        snap = ConventionIndex("3D-Stories", refused).snapshot(budget())
        assert [r["name"] for r in snap["rows"]] == ["a-a"]
        assert snap["unreadable"] == ["b"]

    def test_the_403_that_means_rate_limited_is_classified_as_such(self):
        """Pins `HttpGitHub._classify`, because the whole split above rests on it."""
        import urllib.error

        from harness.github import HttpGitHub, RateLimited, Unauthorized as Unauth

        def err(headers):
            return urllib.error.HTTPError("u", 403, "Forbidden", headers, None)

        limited = HttpGitHub._classify(err({"x-ratelimit-remaining": "0"}))
        plain = HttpGitHub._classify(err({"x-ratelimit-remaining": "4999"}))
        assert isinstance(limited, RateLimited)
        assert isinstance(plain, Unauth) and not isinstance(plain, RateLimited)

    def test_a_repository_unread_for_longer_than_the_bound_stops_being_carried(self):
        """The Critical. Carry-forward plus a resetting snapshot age meant a repository whose
        access was revoked stayed listed for ever while `max_stale_age` never fired for it —
        the bound the operator set would have covered the snapshot and not its contents."""
        src = gate_source(rawgentic=["docs/a.html"], saystory=["docs/b.html"])
        clock = FakeClock()
        idx = swr_index(src, monotonic=clock, max_stale_age=3600.0)
        first = idx.snapshot(budget())
        assert sorted(r["name"] for r in first["rows"]) == ["rawgentic-a", "saystory-b"]

        src._errors[("3D-Stories/saystory", "HEAD")] = Unauthorized("access revoked")

        previous = first
        for _ in range(3):                                # three refreshes over four hours
            clock.t += 1801.0
            idx.snapshot(budget())
            assert _settle(lambda: idx.snapshot(budget()) is not previous), "refresh stalled"
            previous = idx.snapshot(budget())

        assert [r["name"] for r in previous["rows"]] == ["rawgentic-a"]
        assert previous["unreadable"] == ["saystory"]

    def test_a_brief_failure_inside_the_bound_still_carries(self):
        src = gate_source(rawgentic=["docs/a.html"], saystory=["docs/b.html"])
        clock = FakeClock()
        idx = swr_index(src, monotonic=clock, max_stale_age=3600.0)
        first = idx.snapshot(budget())
        src._errors[("3D-Stories/saystory", "HEAD")] = Unauthorized("hiccup")
        clock.t += 901.0
        idx.snapshot(budget())
        assert _settle(lambda: idx.snapshot(budget()) is not first), "refresh stalled"
        assert sorted(r["name"] for r in idx.snapshot(budget())["rows"]) == [
            "rawgentic-a", "saystory-b"]

    def test_pruning_runs_even_when_one_repository_could_not_be_read(self, tmp_path):
        """The live cold walk saw three transient failures in one pass of 61 repositories, so
        requiring a wholly clean walk meant the store would essentially never be pruned."""
        from harness.datestore import DateStore

        store_ = DateStore(str(tmp_path / "d.db"))
        store_.initialize()
        dead = ("3D-Stories/rawgentic", "docs/gone.html", "f" * 40)
        store_.put(dead, ("2020-01-01", "2020-01-01"))

        src = index_source(rawgentic=["docs/a.html"], secret=["docs/b.html"])
        src._errors[("3D-Stories/secret", "HEAD")] = Unavailable("hiccup")
        ConventionIndex("3D-Stories", src, store=store_).snapshot(budget())
        assert store_.get(dead) is None


class TestStep11Findings:
    def test_the_install_and_the_flag_release_are_ONE_critical_section(self):
        """Both cross-model reviewers found this independently, and it is the reason this is a
        source-shape assertion rather than a behaviour one.

        `_run_build` used to take the lock twice — once in the `finally` to clear `_building`,
        once afterwards to install the snapshot. A caller arriving between them saw no build in
        flight AND no new snapshot, elected itself, and ran a second walk that could overwrite
        the first result.

        **A behavioural test cannot reach that window**, and pretending otherwise would be
        worse than not testing it: between the two acquisitions no lock is held and no code of
        this class runs, so there is nothing to hook and nothing to synchronize against. The
        first version of this test spawned a reader from inside `_build` and passed identically
        with the defect present — a test that cannot fail. So the invariant is asserted where it
        actually lives: the method holds the lock exactly once, and the two writes cannot be
        separated by anyone.
        """
        import inspect

        source = inspect.getsource(ConventionIndex._run_build)
        body = source.split('"""')[-1]              # past the docstring
        assert body.count("with self._lock") == 1, (
            "`_run_build` must install the snapshot and clear `_building` in ONE critical "
            "section; a second acquisition reopens the duplicate-build window")

    def test_a_concurrent_reader_during_a_cold_build_gets_one_walk_and_a_503(self):
        """The behaviour that window would have broken, asserted for its own sake."""
        src = index_source(rawgentic=["docs/a.html"])
        idx = ConventionIndex("3D-Stories", src, ttl=900.0)
        seen = []
        real_build = idx._build

        def watched(*a, **k):
            def peek():
                try:
                    idx.snapshot(budget())
                    seen.append("served")
                except IndexBuilding:
                    seen.append("IndexBuilding")
            thread = threading.Thread(target=peek)
            thread.start()
            thread.join(5)
            return real_build(*a, **k)

        idx._build = watched
        idx.snapshot(budget())
        assert seen == ["IndexBuilding"], seen
        assert idx._building is False
        assert idx._snapshot is not None
        assert src.tree_calls == 1

    def test_the_stop_flag_is_checked_BETWEEN_the_two_calls_not_only_at_entry(self):
        """`_walk_repo` checked cancellation only at entry, so a worker whose `commit` was in
        flight when another worker went fatal still issued its `tree`.

        The flag is set DURING `commit`, which is the only arrangement that discriminates: at
        entry it is clear, so the entry check passes and the new check is the one under test.
        An earlier version of this test pre-set the flag, hit the entry check, and passed
        identically with the fix removed.

        Asserted at the unit, deliberately. Cancellation is best-effort by nature — a worker
        already past a check finishes the call it started — so an end-to-end assertion that NO
        call happens after a fatal error overstates the guarantee and races the scheduler.
        """
        stop = threading.Event()

        class SetsStopDuringCommit(FakeGitHub):
            def commit(self, repo, ref, budget_, http_timeout: float = 20.0):
                sha = super().commit(repo, ref, budget_, http_timeout)
                stop.set()                    # another worker just went fatal
                return sha

        src = SetsStopDuringCommit(
            trees={("3D-Stories/rawgentic", "r" * 40): [
                {"path": "docs/a.html", "type": "blob", "mode": "100644",
                 "sha": BLOB, "size": 10}]},
            commits={("3D-Stories/rawgentic", "HEAD"): "r" * 40},
            repos=["rawgentic"])
        idx = ConventionIndex("3D-Stories", src, workers=2)

        walk = idx._walk_repo("rawgentic", budget(), 20.0, stop)
        assert src.commit_calls == 1, "the entry check must NOT have fired"
        assert walk.unreadable is True
        assert src.tree_calls == 0, "a worker resumed after the stop flag and still called tree"

    def test_a_worker_that_never_sees_the_flag_walks_normally(self):
        """The control. Without it the test above passes for a version that never calls tree."""
        src = index_source(rawgentic=["docs/a.html"])
        idx = ConventionIndex("3D-Stories", src, workers=2)
        walk = idx._walk_repo("rawgentic", budget(), 20.0, threading.Event())
        assert walk.unreadable is False
        assert len(walk.docs) == 1
        assert src.tree_calls == 1
