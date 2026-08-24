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
