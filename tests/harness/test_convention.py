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
