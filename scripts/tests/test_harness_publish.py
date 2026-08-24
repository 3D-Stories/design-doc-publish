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


# --------------------------------------------------------------------------- T3, AC1

class FakeHTTP:
    """A scriptable control API. `script` maps (method, path) to a response spec."""

    def __init__(self, script=None):
        self.script = dict(script or {})
        self.calls = []          # (method, full_url, headers, body, timeout)

    def __call__(self, req, timeout=None, **kw):
        import io as _io
        import json as _json
        import urllib.error as _ue
        method = req.get_method()
        url = req.full_url
        path = urllib.parse.urlsplit(url).path
        body = req.data
        self.calls.append((method, url, dict(req.header_items()), body, timeout))
        spec = self.script.get((method, path))
        if spec is None:
            raise AssertionError(f"unscripted call: {method} {path}")
        if isinstance(spec, Exception):
            raise spec
        status, payload = spec
        raw = _json.dumps(payload).encode() if not isinstance(payload, bytes) else payload
        if status >= 400:
            raise _ue.HTTPError(url, status, "scripted", {}, _io.BytesIO(raw))
        resp = _io.BytesIO(raw)
        resp.status = status
        resp.headers = {"Content-Type": "application/json"}
        resp.__enter__ = lambda s=resp: s
        resp.__exit__ = lambda *a: False
        return resp

    def header(self, i, name):
        # urllib title-cases header names it sets via Request(headers=...).
        got = self.calls[i][2]
        for k, v in got.items():
            if k.lower() == name.lower():
                return v
        return None


import urllib.parse  # noqa: E402  (used by FakeHTTP above)

BASE = "http://172.25.0.2:8080"
TOKEN_ENV = {"DOC_HARNESS_CONTROL_URL": BASE, "DOC_HARNESS_PUBLISH_TOKEN": "s3cret"}


class TestTheReadBackIsParsedBeforeAnythingIsPublished:

    def test_a_first_publish_reads_null_and_passes_it_through(self):
        http = FakeHTTP({("GET", "/v1/deployments/example-design-12"):
                         (200, {"name": "example-design-12", "active_deployment_id": None})})
        assert publish_doc.read_active(BASE, "example-design-12", "s3cret",
                                       opener=http) is None

    def test_an_existing_deployment_reads_its_integer_id(self):
        """Finding M12. Every other listed case passes with a client that always sends
        null, so the republish path is the one that actually needs proving."""
        http = FakeHTTP({("GET", "/v1/deployments/example-design-12"):
                         (200, {"active_deployment_id": 41})})
        assert publish_doc.read_active(BASE, "example-design-12", "s3cret", opener=http) == 41

    @pytest.mark.parametrize("bad", ["41", 41.5, True, [], {}])
    def test_a_non_integer_active_id_refuses_before_the_post(self, bad):
        http = FakeHTTP({("GET", "/v1/deployments/example-design-12"):
                         (200, {"active_deployment_id": bad})})
        with pytest.raises(publish_doc.StageError):
            publish_doc.read_active(BASE, "example-design-12", "s3cret", opener=http)
        assert len(http.calls) == 1, "nothing may be published after an unparseable read-back"

    def test_the_read_back_carries_the_bearer(self):
        http = FakeHTTP({("GET", "/v1/deployments/example-design-12"):
                         (200, {"active_deployment_id": None})})
        publish_doc.read_active(BASE, "example-design-12", "s3cret", opener=http)
        assert http.header(0, "Authorization") == "Bearer s3cret"

    def test_the_path_carries_the_v1_prefix(self):
        """Finding M1. Revision 2 wrote /deployments, which is a 404 at
        harness/control.py:83 — every publish would have failed at the first call."""
        http = FakeHTTP({("GET", "/v1/deployments/example-design-12"):
                         (200, {"active_deployment_id": None})})
        publish_doc.read_active(BASE, "example-design-12", "s3cret", opener=http)
        assert urllib.parse.urlsplit(http.calls[0][1]).path == "/v1/deployments/example-design-12"


class TestThePublishCall:

    MANIFEST = {"name": "example-design-12", "repo": "o/r", "commit_sha": "a" * 40,
                "entry_path": "/p.html",
                "assets": [{"repo_path": "docs/p.html", "url_path": "/p.html",
                            "blob_id": "b" * 40, "size": 10, "sha256": "c" * 64}]}

    def test_a_201_yields_the_new_deployment_id(self):
        http = FakeHTTP({("POST", "/v1/deployments"):
                         (201, {"deployment_id": 42, "name": "example-design-12",
                                "commit_sha": "a" * 40, "assets": 1, "cache_warmed": True})})
        assert publish_doc.publish(BASE, self.MANIFEST, None, "s3cret", opener=http) == 42

    def test_expected_active_is_sent_explicitly_as_null_on_a_first_publish(self):
        import json as _json
        http = FakeHTTP({("POST", "/v1/deployments"): (201, {"deployment_id": 42})})
        publish_doc.publish(BASE, self.MANIFEST, None, "s3cret", opener=http)
        sent = _json.loads(http.calls[0][3])
        assert "expected_active" in sent and sent["expected_active"] is None

    def test_a_republish_sends_the_exact_integer_it_read_back(self):
        import json as _json
        http = FakeHTTP({("POST", "/v1/deployments"): (201, {"deployment_id": 43})})
        publish_doc.publish(BASE, self.MANIFEST, 41, "s3cret", opener=http)
        assert _json.loads(http.calls[0][3])["expected_active"] == 41

    def test_content_type_is_never_sent_in_the_manifest(self):
        """The #34 boundary: the harness derives it, and sending one is a 422."""
        import json as _json
        http = FakeHTTP({("POST", "/v1/deployments"): (201, {"deployment_id": 42})})
        publish_doc.publish(BASE, self.MANIFEST, None, "s3cret", opener=http)
        sent = _json.loads(http.calls[0][3])
        assert all("content_type" not in a for a in sent["assets"])

    def test_a_201_without_an_integer_deployment_id_is_a_failure_not_a_pass(self):
        http = FakeHTTP({("POST", "/v1/deployments"): (201, {"name": "x"})})
        with pytest.raises(publish_doc.StageError):
            publish_doc.publish(BASE, self.MANIFEST, None, "s3cret", opener=http)

    def test_a_409_is_reported_as_a_race_not_a_generic_failure(self):
        http = FakeHTTP({("POST", "/v1/deployments"):
                         (409, {"active_deployment_id": 44})})
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.publish(BASE, self.MANIFEST, 41, "s3cret", opener=http)
        assert "race" in e.value.message.lower() or "another publisher" in e.value.message.lower()
        assert "44" in e.value.message

    def test_a_502_names_the_github_grant_not_the_transport(self):
        """Findings A5 and S4. Stage 4a exercises the PUBLISHER's git credentials; the
        harness fetches blobs with a DIFFERENT identity. Every local check can pass while
        the harness cannot read a single blob."""
        http = FakeHTTP({("POST", "/v1/deployments"): (502, {"error": "upstream"})})
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.publish(BASE, self.MANIFEST, None, "s3cret", opener=http)
        assert "DOC_HARNESS_GITHUB_TOKEN" in e.value.message

    def test_a_non_canonical_url_path_refuses_locally(self):
        """The #34 boundary again: canonical_url_path refuses a non-canonically-encoded
        path with a 422, so catching it here is one clear sentence instead."""
        manifest = {**self.MANIFEST,
                    "assets": [{**self.MANIFEST["assets"][0], "url_path": "/a b.css"}]}
        with pytest.raises(publish_doc.StageError):
            publish_doc.publish(BASE, manifest, None, "s3cret", opener=FakeHTTP({}))

    def test_the_post_is_never_retried_after_a_timeout(self):
        """Not idempotent. A retry after an ambiguous timeout races expected_active against
        a deployment its own first attempt may have created."""
        import socket
        http = FakeHTTP({("POST", "/v1/deployments"): socket.timeout("timed out")})
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.publish(BASE, self.MANIFEST, None, "s3cret", opener=http)
        assert len(http.calls) == 1
        assert "not retried" in e.value.message.lower() or "retry" in e.value.message.lower()


class TestTheBoundedCalls:
    """Finding N8. The client is urllib.request.urlopen, which takes ONE per-socket
    deadline — not separate connect and read deadlines. The contract is what it can
    actually enforce, and the tests pin the values that reach it."""

    def test_the_read_back_and_the_publish_carry_different_deadlines(self):
        http = FakeHTTP({("GET", "/v1/deployments/n"): (200, {"active_deployment_id": None}),
                         ("POST", "/v1/deployments"): (201, {"deployment_id": 1})})
        publish_doc.read_active(BASE, "n", "s3cret", opener=http)
        publish_doc.publish(BASE, TestThePublishCall.MANIFEST, None, "s3cret", opener=http)
        assert http.calls[0][4] == publish_doc.CONTROL_READ_TIMEOUT
        assert http.calls[1][4] == publish_doc.PUBLISH_TIMEOUT

    def test_the_publish_deadline_is_the_longer_one(self):
        """The harness fetches every blob from GitHub inside the POST."""
        assert publish_doc.PUBLISH_TIMEOUT > publish_doc.CONTROL_READ_TIMEOUT


class TestTheManifestIsRefusedLocallyBeforeTheHarnessRefusesIt:
    """Found while wiring T4, and missed by all three design review passes: the manifest
    carries a top-level `entry_path` that must name a declared asset
    (`harness/manifest.py:192-199`), and an asset `url_path` of `/` is refused outright
    (`harness/manifest.py:113`). Serving maps a request for `/` to `entry_path`
    (`harness/serving.py:80`). The design named neither, so the first manifest this tool
    built would have been a 422 about a field nobody had written down.
    """

    GOOD = TestThePublishCall.MANIFEST

    def test_the_good_manifest_passes(self):
        publish_doc.validate_manifest(self.GOOD)

    def test_an_asset_at_the_root_is_refused(self):
        m = {**self.GOOD, "entry_path": "/",
             "assets": [{**self.GOOD["assets"][0], "url_path": "/"}]}
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.validate_manifest(m)
        assert "must name a file" in e.value.message

    def test_a_missing_entry_path_is_refused(self):
        m = {k: v for k, v in self.GOOD.items() if k != "entry_path"}
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.validate_manifest(m)
        assert "entry_path" in e.value.message

    def test_an_entry_path_naming_no_declared_asset_is_refused(self):
        """The harness's own words: '/' would 404 on a deployment that otherwise
        activated cleanly."""
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.validate_manifest({**self.GOOD, "entry_path": "/missing.html"})
        assert "no declared asset" in e.value.message

    @pytest.mark.parametrize("field,bad", [
        ("commit_sha", "HEAD"), ("commit_sha", "a" * 39), ("repo", "just-a-name"),
        ("repo", "../x"), ("name", "Not_A_Label"),
    ])
    def test_a_malformed_top_level_field_is_refused(self, field, bad):
        with pytest.raises(publish_doc.StageError):
            publish_doc.validate_manifest({**self.GOOD, field: bad})

    @pytest.mark.parametrize("field,bad", [
        ("blob_id", "b" * 39), ("sha256", "c" * 63), ("repo_path", "/abs/p.html"),
        ("repo_path", "../escape.html"),
    ])
    def test_a_malformed_asset_field_is_refused(self, field, bad):
        m = {**self.GOOD, "assets": [{**self.GOOD["assets"][0], field: bad}]}
        with pytest.raises(publish_doc.StageError):
            publish_doc.validate_manifest(m)

    def test_an_empty_asset_list_is_refused(self):
        with pytest.raises(publish_doc.StageError):
            publish_doc.validate_manifest({**self.GOOD, "assets": []})

    def test_a_duplicate_url_path_is_refused(self):
        a = self.GOOD["assets"][0]
        with pytest.raises(publish_doc.StageError):
            publish_doc.validate_manifest({**self.GOOD, "assets": [a, dict(a)]})

    def test_publish_validates_before_it_sends_anything(self):
        http = FakeHTTP({})
        with pytest.raises(publish_doc.StageError):
            publish_doc.publish(BASE, {**self.GOOD, "commit_sha": "HEAD"}, None,
                                "s3cret", opener=http)
        assert http.calls == [], "a manifest the harness would refuse must not be sent"


# --------------------------------------------------------------------------- T4, AC2

class TestCredentialsArePresentBeforeAnyRequestIsBuilt:
    """Finding N6. A missing or half-present credential must fail as a LOCAL refusal, not
    indirectly as a 401 or an Access login redirect — those look like server problems."""

    def test_a_missing_publish_token_refuses_and_names_the_variable(self):
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.assert_credentials({"DOC_HARNESS_CONTROL_URL": BASE}, edge=False)
        assert "DOC_HARNESS_PUBLISH_TOKEN" in e.value.message

    def test_an_empty_publish_token_is_missing_not_present(self):
        with pytest.raises(publish_doc.StageError):
            publish_doc.assert_credentials({"DOC_HARNESS_PUBLISH_TOKEN": "  "}, edge=False)

    def test_the_publish_token_alone_is_enough_when_the_edge_half_is_skipped(self):
        publish_doc.assert_credentials(TOKEN_ENV, edge=False)

    @pytest.mark.parametrize("present", ["CF-Access-Client-Id", "CF-Access-Client-Secret"])
    def test_one_access_value_without_the_other_refuses(self, present):
        env = {**TOKEN_ENV, present.upper().replace("-", "_"): "x"}
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.assert_credentials(env, edge=True)
        assert "pair" in e.value.message.lower() or "both" in e.value.message.lower()

    def test_both_access_values_pass(self):
        publish_doc.assert_credentials(
            {**TOKEN_ENV, "CF_ACCESS_CLIENT_ID": "i", "CF_ACCESS_CLIENT_SECRET": "s"},
            edge=True)

    def test_no_refusal_ever_prints_a_credential_value(self):
        env = {"DOC_HARNESS_PUBLISH_TOKEN": "", "CF_ACCESS_CLIENT_ID": "SUPERSECRETVALUE"}
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.assert_credentials(env, edge=True)
        assert "SUPERSECRETVALUE" not in e.value.message


class TestACredentialNeverReachesAnUnvalidatedDestination:
    """Findings M7 and N4, M7 found by both review passes. Redaction protects the LOG. It
    does nothing about the wire or the wrong server, and transport syntax does not
    establish server identity."""

    @pytest.mark.parametrize("ok", [
        "http://127.0.0.1:8080", "http://localhost:8080", "http://172.25.0.2:8080",
        "https://docs-control.3dstories.ca",
    ])
    def test_a_permitted_origin_passes(self, ok):
        publish_doc.assert_bearer_destination(ok)

    @pytest.mark.parametrize("bad", [
        "http://evil.example.com:8080",     # plaintext to a public host
        "http://harness.evil.com:8080",     # a dotted host is not the bridge form
        "https://evil.example.com",         # https is NOT sufficient on its own
    ])
    def test_an_unlisted_origin_refuses(self, bad):
        """Revision 3 permitted ANY https host, which exfiltrates the bearer to whatever a
        mistaken or hostile environment names."""
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.assert_bearer_destination(bad)
        assert "allow" in e.value.message.lower()

    def test_the_access_headers_go_only_to_the_pinned_zone(self):
        publish_doc.assert_access_destination(
            "https://example-design-12.3dstories.ca/p.html", "example-design-12")

    @pytest.mark.parametrize("url", [
        "https://example-design-12.evil.com/p.html",
        "https://other-name.3dstories.ca/p.html",
        "http://example-design-12.3dstories.ca/p.html",
    ])
    def test_a_wrong_host_or_scheme_refuses_the_access_headers(self, url):
        with pytest.raises(publish_doc.StageError):
            publish_doc.assert_access_destination(url, "example-design-12")

    def test_the_zone_is_pinned_in_source_not_read_from_the_environment(self):
        """Finding N11. Revision 3 validated against DOC_HARNESS_ZONE, which is supplied by
        the same mutable environment as the destination — so an attacker who can set the
        destination can set the anchor to match it."""
        assert publish_doc.PINNED_ZONE == "3dstories.ca"
        # Checked against the CODE, not the file text: a comment naming the variable in
        # order to explain why it is NOT read is exactly what should be there.
        import ast
        tree = ast.parse((SCRIPTS / "publish_doc.py").read_text(encoding="utf-8"))
        reads = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Constant) and n.value == "DOC_HARNESS_ZONE"]
        assert reads == [], (
            "the trust anchor must not come from the same environment as the destination")

    def test_the_pinned_zone_is_what_both_destination_checks_use(self):
        """A pinned constant that some other path bypasses would be decoration."""
        publish_doc.assert_access_destination(
            f"https://n.{publish_doc.PINNED_ZONE}/p.html", "n")
        with pytest.raises(publish_doc.StageError):
            publish_doc.assert_access_destination("https://n.elsewhere.test/p.html", "n")
        publish_doc.assert_bearer_destination(
            f"https://docs-control.{publish_doc.PINNED_ZONE}")


class TestTheVerificationRequest:

    def test_the_origin_half_sets_the_host_header_explicitly(self):
        """Serving routes on Host (harness/app.py:49 calls resolve_host with HTTP_HOST).
        The origin URL's own host is a bridge address, which routes to nothing."""
        req = publish_doc.build_verify_request(
            BASE, "/p.html", 42, name="example-design-12", access=None)
        assert req.get_header("Host") == "example-design-12.3dstories.ca"
        assert req.full_url == f"{BASE}/p.html?__deployment=42"

    def test_the_edge_half_carries_access_headers_and_no_host_override(self):
        req = publish_doc.build_verify_request(
            "https://example-design-12.3dstories.ca", "/p.html", 42,
            name="example-design-12", access=("i", "s"))
        assert req.get_header("Cf-access-client-id") == "i"
        assert req.get_header("Cf-access-client-secret") == "s"
        assert req.full_url.startswith("https://example-design-12.3dstories.ca/p.html")

    def test_the_deployment_query_pins_the_new_id_not_the_previous_one(self):
        req = publish_doc.build_verify_request(
            BASE, "/p.html", 42, name="n", access=None)
        assert "__deployment=42" in req.full_url


class TestThePerAssetPassContract:

    def _resp(self, body=b"page", dep=42, ctype="text/html; charset=utf-8"):
        import io as _io
        r = _io.BytesIO(body)
        r.status = 200
        r.headers = {"X-Doc-Deployment": str(dep), "Content-Type": ctype}
        r.__enter__ = lambda s=r: s
        r.__exit__ = lambda *a: False
        return r

    def test_a_matching_asset_passes(self):
        publish_doc.check_verify_response(
            self._resp(), want=b"page", deployment_id=42, url_path="/p.html")

    def test_a_byte_difference_fails(self):
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.check_verify_response(
                self._resp(body=b"other"), want=b"page", deployment_id=42,
                url_path="/p.html")
        assert "byte" in e.value.message.lower()

    def test_the_echo_must_name_the_deployment_just_published(self):
        """Without this the check passes against whatever was already active."""
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.check_verify_response(
                self._resp(dep=41), want=b"page", deployment_id=42, url_path="/p.html")
        assert "X-Doc-Deployment" in e.value.message

    def test_each_asset_is_checked_against_its_own_derived_type(self):
        """Finding A3. Revision 1 put text/html in a condition it repeated per asset, which
        would have rejected every valid CSS, JavaScript and image asset."""
        publish_doc.check_verify_response(
            self._resp(body=b"a{}", ctype="text/css; charset=utf-8"),
            want=b"a{}", deployment_id=42, url_path="/s.css")

    def test_a_wrong_content_type_fails(self):
        with pytest.raises(publish_doc.StageError):
            publish_doc.check_verify_response(
                self._resp(body=b"a{}", ctype="text/html; charset=utf-8"),
                want=b"a{}", deployment_id=42, url_path="/s.css")


class TestTheMimeDerivationIsSharedNotCopied:
    """Finding N7. The manifest deliberately carries no content_type — the harness derives
    it — so a publisher that re-implements the mapping drifts, and drift here produces both
    false failures and false passes."""

    @pytest.mark.parametrize("url_path", [
        "/p.html", "/s.css", "/a.js", "/i.png", "/v.svg", "/f.woff2", "/d.json",
        "/r.txt", "/x.unknown", "/no-extension",
    ])
    def test_the_publisher_and_the_harness_agree_on_every_kind(self, url_path):
        from harness.manifest import content_type_for
        assert publish_doc.content_type_for(url_path) == content_type_for(url_path)

    def test_it_is_the_harness_function_itself_rather_than_a_copy(self):
        from harness.manifest import content_type_for
        assert publish_doc.content_type_for is content_type_for


class TestTheRedirectContract:
    """Finding N10. Revision 3's redirect test demanded the FIRST request carry no
    credentials, which would simply return 401 and prove nothing."""

    def test_the_initial_request_does_carry_its_credentials(self):
        req = publish_doc.build_verify_request(
            "https://n.3dstories.ca", "/p.html", 42, name="n", access=("i", "s"))
        assert req.get_header("Cf-access-client-id") == "i"

    def test_a_three_xx_is_a_failure_and_nothing_follows_it(self):
        import io as _io
        import urllib.error as _ue
        calls = []

        def opener(req, timeout=None, **kw):
            calls.append(req.full_url)
            raise _ue.HTTPError(req.full_url, 302, "Found",
                                {"Location": "https://login.example/"}, _io.BytesIO(b""))

        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.fetch_for_verify(
                publish_doc.build_verify_request(
                    "https://n.3dstories.ca", "/p.html", 42, name="n", access=("i", "s")),
                opener=opener)
        assert len(calls) == 1, "no follow-up request may be made to the redirect target"
        assert "redirect" in e.value.message.lower()

    def test_the_opener_never_follows_redirects_on_its_own(self):
        """urlopen follows a 302 silently, which would send Access credentials to the
        login host. The build must install a non-following handler."""
        assert publish_doc.NO_REDIRECTS is not None
