"""#36 — publishing through the doc-harness control API instead of Vercel.

New surfaces live here rather than in `test_publish_doc.py`, which task T7 rewrites: keeping
the new contract in its own file means the retirement churn and the new coverage cannot
obscure each other in review.

Design: docs/planning/2026-08-24-36-publish-to-harness.md (revision 4).
"""
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import publish_doc  # noqa: E402


# --------------------------------------------------------------------------- T1, AC1

class TestTheControlEndpointIsRequiredRatherThanDefaulted:
    """Owner decision D21. Revision 2 defaulted this to the compose-network address and
    called it reachable. Measured on the harness host: the host reaches a container's
    bridge IP with no published port, but never resolves a compose SERVICE name. So a
    default cannot be right, and an unset variable is a declared state with its own exit
    code rather than a guess."""

    def test_the_two_declared_state_exit_codes_sit_outside_the_stage_block(self):
        """`EXIT_BASE + stage` owns 11 through 17. A skip code inside that range is
        indistinguishable from a stage failure, which is the whole misreport the exit
        contract exists to prevent."""
        assert publish_doc.EXIT_CONTROL_URL_UNSET == 25
        assert publish_doc.EXIT_EDGE_SKIPPED == 26
        taken = {publish_doc.EXIT_BASE + s for s in range(1, 8)}
        assert publish_doc.EXIT_CONTROL_URL_UNSET not in taken
        assert publish_doc.EXIT_EDGE_SKIPPED not in taken

    def test_an_unset_control_url_refuses_and_names_the_variable(self):
        with pytest.raises(publish_doc.DeclaredStateError) as e:
            publish_doc.control_base({})
        assert e.value.code == publish_doc.EXIT_CONTROL_URL_UNSET
        assert "DOC_HARNESS_CONTROL_URL" in e.value.message

    def test_an_empty_control_url_is_unset_not_a_value(self):
        """An exported-but-blank variable is the same declared state, never a base URL
        of the empty string."""
        for blank in ("", "   ", "\t"):
            with pytest.raises(publish_doc.DeclaredStateError):
                publish_doc.control_base({"DOC_HARNESS_CONTROL_URL": blank})

    def test_there_is_no_default_anywhere(self):
        """The regression guard for D21. A default reintroduced here is the exact defect
        revision 2 shipped."""
        with pytest.raises(publish_doc.DeclaredStateError):
            publish_doc.control_base({"SOMETHING_ELSE": "x"})

    @pytest.mark.parametrize("raw,want", [
        ("http://172.25.0.2:8080", "http://172.25.0.2:8080"),
        ("http://172.25.0.2:8080/", "http://172.25.0.2:8080"),
        ("https://docs-control.3dstories.ca", "https://docs-control.3dstories.ca"),
        ("  http://127.0.0.1:8080  ", "http://127.0.0.1:8080"),
    ])
    def test_a_usable_base_is_normalized_to_scheme_host_port(self, raw, want):
        assert publish_doc.control_base({"DOC_HARNESS_CONTROL_URL": raw}) == want

    @pytest.mark.parametrize("bad", [
        "http://user:pw@10.0.0.1:8080",          # userinfo
        "http://10.0.0.1:8080/v1",               # path
        "http://10.0.0.1:8080/?a=b",             # query
        "http://10.0.0.1:8080/#frag",            # fragment
        "10.0.0.1:8080",                         # no scheme
        "ftp://10.0.0.1:8080",                   # wrong scheme
    ])
    def test_anything_but_scheme_host_port_is_refused(self, bad):
        """Finding N4. A control base carrying userinfo, a path, a query or a fragment is
        refused BEFORE any bearer is attached, not sanitized into one."""
        with pytest.raises(publish_doc.StageError):
            publish_doc.control_base({"DOC_HARNESS_CONTROL_URL": bad})


class TestTheEdgeHalfSkipsVisiblyRatherThanSilently:
    """AC2's edge half needs a public hostname. None resolves, so the skip is a declared
    state with its own exit code — never a silent 0, which every caller reads as a pass."""

    def test_an_unset_public_base_is_a_skip_not_an_error(self):
        assert publish_doc.public_base({}) is None

    def test_an_empty_public_base_is_also_a_skip(self):
        for blank in ("", "   "):
            assert publish_doc.public_base({"DOC_HARNESS_PUBLIC_BASE": blank}) is None

    def test_a_set_public_base_is_normalized(self):
        assert publish_doc.public_base(
            {"DOC_HARNESS_PUBLIC_BASE": "https://<name>.3dstories.ca/"}
        ) == "https://<name>.3dstories.ca"

    def test_the_public_base_must_be_https(self):
        """Finding N4. The Access service tokens ride on this host, so plaintext is
        refused rather than downgraded."""
        with pytest.raises(publish_doc.StageError):
            publish_doc.public_base({"DOC_HARNESS_PUBLIC_BASE": "http://<name>.3dstories.ca"})

    def test_the_flag_that_converted_the_skip_to_zero_does_not_exist(self):
        """Finding N3. `--allow-unverified-edge` turned exit 26 into 0, which contradicts
        the declared meaning of 0 and let a status-only caller record an AC2 pass that
        never happened."""
        flags = {o for a in publish_doc.build_parser()._actions for o in a.option_strings}
        assert "--allow-unverified-edge" not in flags


# --------------------------------------------------------------------------- T2, AC1

class FakeGit:
    """A scriptable `git`. Keys are the argument tuple AFTER the leading `git`, with any
    `-C <dir>` prefix stripped, so a test states what it means rather than the exact argv.
    """

    def __init__(self, answers=None, fail=(), by_cwd=None):
        self.answers = dict(answers or {})
        self.fail = set(fail)
        # `by_cwd` keys the SAME argv by the -C directory. Needed because a check like
        # "are these two paths in one repository" runs one identical command twice and
        # must be able to get two different answers.
        self.by_cwd = dict(by_cwd or {})
        self.calls = []

    def __call__(self, argv, **kw):
        import subprocess as _sp
        assert argv[0] == "git", f"FakeGit saw a non-git command: {argv!r}"
        rest = tuple(argv[1:])
        cwd = None
        if rest[:1] == ("-C",):
            cwd, rest = rest[1], rest[2:]
        self.calls.append(rest)
        if rest in self.fail:
            return _sp.CompletedProcess(argv, 1, "", "fatal: scripted failure")
        if cwd is not None and (cwd, rest) in self.by_cwd:
            return _sp.CompletedProcess(argv, 0, self.by_cwd[(cwd, rest)], "")
        return _sp.CompletedProcess(argv, 0, self.answers.get(rest, ""), "")

    def ran(self, *prefix):
        return any(c[:len(prefix)] == prefix for c in self.calls)


class TestTheRemoteIsBoundToTheManifestRepository:
    """Finding M5. A bare reachability check is satisfied by a fork, a second GitHub
    remote or a GitLab mirror, while the harness cannot fetch the commit from the repo
    the manifest declares. Finding N9 then fixed the first attempt at this, which refused
    whenever two GitHub remotes existed — that is every ordinary fork-plus-upstream
    checkout, so it would have refused far more often than it caught anything."""

    def test_an_explicit_override_always_wins(self):
        git = FakeGit({("remote",): "origin\nupstream\n",
                       ("remote", "get-url", "upstream"): "git@github.com:up/stream.git\n",
                       ("remote", "get-url", "origin"): "https://github.com/me/fork.git\n"})
        assert publish_doc.select_remote(Path("."), "upstream", runner=git) == (
            "upstream", "up/stream")

    def test_the_branch_upstream_is_preferred_over_guessing(self):
        """The fork-plus-upstream case N9 names. Two GitHub remotes is normal, not ambiguous."""
        git = FakeGit({("remote",): "origin\nupstream\n",
                       ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"):
                           "origin/main\n",
                       ("remote", "get-url", "origin"): "https://github.com/me/fork.git\n"})
        assert publish_doc.select_remote(Path("."), None, runner=git) == ("origin", "me/fork")

    def test_a_single_github_remote_needs_no_upstream(self):
        git = FakeGit({("remote",): "origin\n",
                       ("remote", "get-url", "origin"): "git@github.com:only/one.git\n"},
                      fail={("rev-parse", "--abbrev-ref", "--symbolic-full-name",
                             "@{upstream}")})
        assert publish_doc.select_remote(Path("."), None, runner=git) == ("origin", "only/one")

    def test_two_github_remotes_and_no_upstream_refuses_and_names_them(self):
        git = FakeGit({("remote",): "origin\nupstream\n",
                       ("remote", "get-url", "origin"): "https://github.com/me/fork.git\n",
                       ("remote", "get-url", "upstream"): "git@github.com:up/stream.git\n"},
                      fail={("rev-parse", "--abbrev-ref", "--symbolic-full-name",
                             "@{upstream}")})
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.select_remote(Path("."), None, runner=git)
        assert "origin" in e.value.message and "upstream" in e.value.message
        assert "--publish-remote" in e.value.message

    def test_no_github_remote_at_all_refuses(self):
        git = FakeGit({("remote",): "origin\n",
                       ("remote", "get-url", "origin"): "git@gitlab.com:me/thing.git\n"})
        with pytest.raises(publish_doc.StageError):
            publish_doc.select_remote(Path("."), None, runner=git)

    @pytest.mark.parametrize("url,want", [
        ("git@github.com:Owner/Name.git", "Owner/Name"),
        ("https://github.com/Owner/Name.git", "Owner/Name"),
        ("https://github.com/Owner/Name", "Owner/Name"),
        ("ssh://git@github.com/Owner/Name.git", "Owner/Name"),
    ])
    def test_every_github_url_shape_parses_to_owner_name(self, url, want):
        assert publish_doc.github_slug(url) == want

    @pytest.mark.parametrize("url", ["git@gitlab.com:me/thing.git",
                                     "https://example.com/me/thing.git", "", "not a url"])
    def test_a_non_github_url_parses_to_nothing(self, url):
        assert publish_doc.github_slug(url) is None


class TestProvenanceFailsLocallyRatherThanAsAFourTwentyTwo:
    """Every one of these is a refusal the harness would eventually make. Making it here
    turns a 422 about a blob id into one clear local sentence."""

    def test_a_split_repository_is_refused(self):
        """Finding S1. `--md` and `--out` are arbitrary paths. The benign failure is a 422;
        the dangerous one is that the path exists in the WRONG repo and the harness serves
        a different file under the right name, with every downstream check passing."""
        top = ("rev-parse", "--show-toplevel")
        git = FakeGit(by_cwd={("/a", top): "/a\n", ("/b", top): "/b\n"})
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.assert_one_repository(Path("/a/doc.md"), Path("/b/doc.html"),
                                              runner=git)
        assert "different repositories" in e.value.message.lower()

    def test_a_path_outside_any_repository_is_refused_distinctly(self):
        """A different failure from the split-repository one, and it must say so: "not in a
        repository" and "in the wrong repository" have different fixes."""
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.assert_one_repository(Path("/a/doc.md"), Path("/a/doc.html"),
                                              runner=FakeGit({}))
        assert "git repository" in e.value.message

    def test_one_repository_returns_its_root(self):
        top = ("rev-parse", "--show-toplevel")
        git = FakeGit({top: "/repo\n"})
        assert publish_doc.assert_one_repository(
            Path("/repo/docs/doc.md"), Path("/repo/docs/doc.html"), runner=git) == "/repo"

    def test_a_working_tree_ahead_of_head_is_refused(self):
        """Finding A2. Hashing working-tree bytes and comparing them to themselves proves
        nothing about the commit being pinned."""
        git = FakeGit({("rev-parse", "HEAD:docs/p.html"): "aaaa\n"})
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.assert_blob_committed(Path("."), "docs/p.html", "bbbb", runner=git)
        assert "docs/p.html" in e.value.message

    def test_an_uncommitted_asset_is_refused_by_name(self):
        git = FakeGit({}, fail={("rev-parse", "HEAD:docs/new.css")})
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.assert_blob_committed(Path("."), "docs/new.css", "cccc", runner=git)
        assert "not committed" in e.value.message.lower()

    def test_a_matching_blob_passes(self):
        git = FakeGit({("rev-parse", "HEAD:docs/p.html"): "aaaa\n"})
        publish_doc.assert_blob_committed(Path("."), "docs/p.html", "aaaa", runner=git)

    def test_an_unpushed_commit_is_refused_and_the_commits_are_named(self):
        """Finding A6. Reachability is `rev-list --count <remote ref>..HEAD == 0`, never
        ref-tip equality: a pushed commit that is no longer a tip is still reachable."""
        git = FakeGit({("rev-list", "--count", "origin/main..HEAD"): "2\n",
                       ("rev-list", "--oneline", "origin/main..HEAD"): "aaa one\nbbb two\n"})
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.assert_head_reachable(Path("."), "origin", "main",
                                              fetch=True, runner=git)
        assert "aaa one" in e.value.message
        assert git.ran("fetch", "origin")

    def test_a_pushed_commit_that_is_no_longer_a_tip_still_passes(self):
        git = FakeGit({("rev-list", "--count", "origin/main..HEAD"): "0\n"})
        publish_doc.assert_head_reachable(Path("."), "origin", "main",
                                          fetch=True, runner=git)

    def test_dry_run_performs_no_fetch(self):
        """Finding N10, and acceptance criterion 5. `--dry-run` must stay offline: the
        mandatory fetch is new network access and it mutates remote-tracking refs."""
        git = FakeGit({("rev-list", "--count", "origin/main..HEAD"): "0\n"})
        publish_doc.assert_head_reachable(Path("."), "origin", "main",
                                          fetch=False, runner=git)
        assert not git.ran("fetch")

    def test_a_failed_fetch_refuses_and_quotes_git(self):
        git = FakeGit({}, fail={("fetch", "origin")})
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.assert_head_reachable(Path("."), "origin", "main",
                                              fetch=True, runner=git)
        assert "scripted failure" in e.value.message
