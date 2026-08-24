"""#36 — publishing through the doc-harness control API instead of Vercel.

New surfaces live here rather than in `test_publish_doc.py`, which task T7 rewrites: keeping
the new contract in its own file means the retirement churn and the new coverage cannot
obscure each other in review.

Design: docs/planning/2026-08-24-36-publish-to-harness.md (revision 4).

## Two whole files retired into this one

A deleted test must say where its risk went.

* **`test_scope_threading.py`** (410 lines) existed to prove `--vercel-scope` was threaded
  into every account-targeting call, so an unpinned deploy could not land in whichever
  account `vercel switch` last selected. **That risk left with Vercel**: there is no
  account to target and no scope to thread. The adjacent risk that survives — a credential
  reaching a destination nobody validated — is covered here by
  `TestACredentialNeverReachesAnUnvalidatedDestination`, and it is a stronger check than
  the one it replaces, because it bounds the DESTINATION rather than a CLI flag.

* **`test_vercel_timeout.py`** (82 lines) proved both Vercel helpers passed a timeout and
  that a timeout failed the stage rather than being diagnosed as something else. **That
  risk did NOT leave** — an unbounded call still hangs the CLI — so it is replaced here by
  `TestTheBoundedCalls`, plus the no-auto-retry assertion in `TestThePublishCall`, which
  the old file had no equivalent of.
"""
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))
# The repository root, so `harness.*` imports here work when this FILE is run alone.
# Several tests below compare the publisher against the harness's own functions, and they
# used to pass only because the harness's own test directory had already put the root on
# the path — order-dependent, and invisible in a full run. Running just this file failed
# with ModuleNotFoundError, which is exactly what a developer does.
sys.path.insert(0, str(ROOT))

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
        ("https://docs-control.docs.3dstories.ca", "https://docs-control.docs.3dstories.ca"),
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
            {"DOC_HARNESS_PUBLIC_BASE": "https://<name>.docs.3dstories.ca/"}
        ) == "https://<name>.docs.3dstories.ca"

    def test_the_public_base_must_be_https(self):
        """Finding N4. The Access service tokens ride on this host, so plaintext is
        refused rather than downgraded."""
        with pytest.raises(publish_doc.StageError):
            publish_doc.public_base({"DOC_HARNESS_PUBLIC_BASE": "http://<name>.docs.3dstories.ca"})

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
        assert git.ran("fetch", "--prune", "origin")

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
        git = FakeGit({}, fail={("fetch", "--prune", "origin")})
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
# Finding S3: a bridge address needs the explicit opt-in, so the tests that use one say so.
BRIDGE_OK = {"DOC_HARNESS_ALLOW_BRIDGE_PLAINTEXT": "172.25.0.2:8080"}
TOKEN_ENV = {"DOC_HARNESS_CONTROL_URL": BASE, "DOC_HARNESS_PUBLISH_TOKEN": "s3cret"}


class TestTheReadBackIsParsedBeforeAnythingIsPublished:

    def test_a_first_publish_reads_null_and_passes_it_through(self):
        http = FakeHTTP({("GET", "/v1/deployments/example-design-12"):
                         (200, {"name": "example-design-12", "active_deployment_id": None})})
        assert publish_doc.read_active(BASE, "example-design-12", "s3cret",
                                       opener=http, env=BRIDGE_OK) is None

    def test_an_existing_deployment_reads_its_integer_id(self):
        """Finding M12. Every other listed case passes with a client that always sends
        null, so the republish path is the one that actually needs proving."""
        http = FakeHTTP({("GET", "/v1/deployments/example-design-12"):
                         (200, {"active_deployment_id": 41})})
        assert publish_doc.read_active(BASE, "example-design-12", "s3cret", opener=http, env=BRIDGE_OK) == 41

    @pytest.mark.parametrize("bad", ["41", 41.5, True, [], {}])
    def test_a_non_integer_active_id_refuses_before_the_post(self, bad):
        http = FakeHTTP({("GET", "/v1/deployments/example-design-12"):
                         (200, {"active_deployment_id": bad})})
        with pytest.raises(publish_doc.StageError):
            publish_doc.read_active(BASE, "example-design-12", "s3cret", opener=http, env=BRIDGE_OK)
        assert len(http.calls) == 1, "nothing may be published after an unparseable read-back"

    def test_the_read_back_carries_the_bearer(self):
        http = FakeHTTP({("GET", "/v1/deployments/example-design-12"):
                         (200, {"active_deployment_id": None})})
        publish_doc.read_active(BASE, "example-design-12", "s3cret", opener=http, env=BRIDGE_OK)
        assert http.header(0, "Authorization") == "Bearer s3cret"

    def test_the_path_carries_the_v1_prefix(self):
        """Finding M1. Revision 2 wrote /deployments, which is a 404 at
        harness/control.py:83 — every publish would have failed at the first call."""
        http = FakeHTTP({("GET", "/v1/deployments/example-design-12"):
                         (200, {"active_deployment_id": None})})
        publish_doc.read_active(BASE, "example-design-12", "s3cret", opener=http, env=BRIDGE_OK)
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
        assert publish_doc.publish(BASE, self.MANIFEST, None, "s3cret", opener=http, env=BRIDGE_OK) == 42

    def test_expected_active_is_sent_explicitly_as_null_on_a_first_publish(self):
        import json as _json
        http = FakeHTTP({("POST", "/v1/deployments"): (201, {"deployment_id": 42})})
        publish_doc.publish(BASE, self.MANIFEST, None, "s3cret", opener=http, env=BRIDGE_OK)
        sent = _json.loads(http.calls[0][3])
        assert "expected_active" in sent and sent["expected_active"] is None

    def test_a_republish_sends_the_exact_integer_it_read_back(self):
        import json as _json
        http = FakeHTTP({("POST", "/v1/deployments"): (201, {"deployment_id": 43})})
        publish_doc.publish(BASE, self.MANIFEST, 41, "s3cret", opener=http, env=BRIDGE_OK)
        assert _json.loads(http.calls[0][3])["expected_active"] == 41

    def test_content_type_is_never_sent_in_the_manifest(self):
        """The #34 boundary: the harness derives it, and sending one is a 422."""
        import json as _json
        http = FakeHTTP({("POST", "/v1/deployments"): (201, {"deployment_id": 42})})
        publish_doc.publish(BASE, self.MANIFEST, None, "s3cret", opener=http, env=BRIDGE_OK)
        sent = _json.loads(http.calls[0][3])
        assert all("content_type" not in a for a in sent["assets"])

    def test_a_201_without_an_integer_deployment_id_is_a_failure_not_a_pass(self):
        http = FakeHTTP({("POST", "/v1/deployments"): (201, {"name": "x"})})
        with pytest.raises(publish_doc.StageError):
            publish_doc.publish(BASE, self.MANIFEST, None, "s3cret", opener=http, env=BRIDGE_OK)

    def test_a_409_is_reported_as_a_race_not_a_generic_failure(self):
        http = FakeHTTP({("POST", "/v1/deployments"):
                         (409, {"active_deployment_id": 44})})
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.publish(BASE, self.MANIFEST, 41, "s3cret", opener=http, env=BRIDGE_OK)
        assert "race" in e.value.message.lower() or "another publisher" in e.value.message.lower()
        assert "44" in e.value.message

    def test_a_502_names_the_github_grant_not_the_transport(self):
        """Findings A5 and S4. Stage 4a exercises the PUBLISHER's git credentials; the
        harness fetches blobs with a DIFFERENT identity. Every local check can pass while
        the harness cannot read a single blob."""
        http = FakeHTTP({("POST", "/v1/deployments"): (502, {"error": "upstream"})})
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.publish(BASE, self.MANIFEST, None, "s3cret", opener=http, env=BRIDGE_OK)
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
            publish_doc.publish(BASE, self.MANIFEST, None, "s3cret", opener=http, env=BRIDGE_OK)
        assert len(http.calls) == 1
        assert "not retried" in e.value.message.lower() or "retry" in e.value.message.lower()


class TestTheBoundedCalls:
    """Finding N8. The client is urllib.request.urlopen, which takes ONE per-socket
    deadline — not separate connect and read deadlines. The contract is what it can
    actually enforce, and the tests pin the values that reach it."""

    def test_the_read_back_and_the_publish_carry_different_deadlines(self):
        http = FakeHTTP({("GET", "/v1/deployments/n"): (200, {"active_deployment_id": None}),
                         ("POST", "/v1/deployments"): (201, {"deployment_id": 1})})
        publish_doc.read_active(BASE, "n", "s3cret", opener=http, env=BRIDGE_OK)
        publish_doc.publish(BASE, TestThePublishCall.MANIFEST, None, "s3cret", opener=http, env=BRIDGE_OK)
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
                                "s3cret", opener=http, env=BRIDGE_OK)
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
        "http://127.0.0.1:8080", "http://localhost:8080",
        "https://docs-control.docs.3dstories.ca",
    ])
    def test_a_permitted_origin_passes(self, ok):
        """A bridge address is no longer here: finding S3 made it require an explicit
        opt-in, and that contract is asserted by
        `TestPlaintextToANonLoopbackHostIsOptedIntoExplicitly` below."""
        publish_doc.assert_bearer_destination(ok, env={})

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
            "https://example-design-12.docs.3dstories.ca/p.html", "example-design-12")

    @pytest.mark.parametrize("url", [
        "https://example-design-12.evil.com/p.html",
        "https://other-name.docs.3dstories.ca/p.html",
        "http://example-design-12.docs.3dstories.ca/p.html",
    ])
    def test_a_wrong_host_or_scheme_refuses_the_access_headers(self, url):
        with pytest.raises(publish_doc.StageError):
            publish_doc.assert_access_destination(url, "example-design-12")

    def test_the_zone_is_pinned_in_source_not_read_from_the_environment(self):
        """Finding N11. Revision 3 validated against DOC_HARNESS_ZONE, which is supplied by
        the same mutable environment as the destination — so an attacker who can set the
        destination can set the anchor to match it."""
        assert publish_doc.PINNED_ZONE == "docs.3dstories.ca"
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
            BASE, "/p.html", 42, name="example-design-12", access=None, env=BRIDGE_OK)
        assert req.get_header("Host") == "example-design-12.docs.3dstories.ca"
        assert req.full_url == f"{BASE}/p.html?__deployment=42"

    def test_the_edge_half_carries_access_headers_and_no_host_override(self):
        req = publish_doc.build_verify_request(
            "https://example-design-12.docs.3dstories.ca", "/p.html", 42,
            name="example-design-12", access=("i", "s"))
        assert req.get_header("Cf-access-client-id") == "i"
        assert req.get_header("Cf-access-client-secret") == "s"
        assert req.full_url.startswith("https://example-design-12.docs.3dstories.ca/p.html")

    def test_the_deployment_query_pins_the_new_id_not_the_previous_one(self):
        req = publish_doc.build_verify_request(
            BASE, "/p.html", 42, name="n", access=None, env=BRIDGE_OK)
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

    def test_no_second_extension_mapping_exists_here(self):
        """The intent, stated directly. It used to be an identity check against the harness
        function, which broke the moment that import became lazy — and lazy is right, since
        a module-scope import of `harness` would make the whole script unimportable. What
        must not exist is a SECOND copy of the mapping, so that is what is asserted, and the
        parity test above proves the two agree on every kind."""
        src = (SCRIPTS / "publish_doc.py").read_text(encoding="utf-8")
        for ext in ("text/css", "image/png", "font/woff2", "application/octet-stream"):
            assert ext not in src, f"{ext!r} is hard-coded here; import the harness mapping"

    def test_it_delegates_to_the_harness_rather_than_answering_itself(self):
        """Monkeypatching the harness function must change this one's answer. A copy would
        keep returning the old value, which is exactly the drift finding N7 named."""
        import harness.manifest as hm
        original = hm.content_type_for
        try:
            hm.content_type_for = lambda p: "sentinel/value"
            assert publish_doc.content_type_for("/a.css") == "sentinel/value"
        finally:
            hm.content_type_for = original


class TestTheRedirectContract:
    """Finding N10. Revision 3's redirect test demanded the FIRST request carry no
    credentials, which would simply return 401 and prove nothing."""

    def test_the_initial_request_does_carry_its_credentials(self):
        req = publish_doc.build_verify_request(
            "https://n.docs.3dstories.ca", "/p.html", 42, name="n", access=("i", "s"))
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
                    "https://n.docs.3dstories.ca", "/p.html", 42, name="n", access=("i", "s")),
                opener=opener)
        assert len(calls) == 1, "no follow-up request may be made to the redirect target"
        assert "redirect" in e.value.message.lower()

    def test_the_opener_never_follows_redirects_on_its_own(self):
        """urlopen follows a 302 silently, which would send Access credentials to the
        login host. The build must install a non-following handler."""
        assert publish_doc.NO_REDIRECTS is not None


# --------------------------------------------------------------------------- T5, AC3

class TestTheNameCapIsTheHarnessLimitNotVercels:
    """AC3. The 35-character cap existed because Vercel truncates a .vercel.app label at
    35 and the conventional URL then 404s forever. The harness has no such truncation: its
    limit is the DNS label limit itself, 63 (harness/routing.py:49-56)."""

    def test_the_cap_is_now_sixty_three(self):
        assert publish_doc.MAX_ALIAS_LABEL == 63

    def test_the_cap_agrees_with_the_harness_label_grammar(self):
        """A publisher cap looser than the harness's would publish a name routing can
        never address; tighter would refuse names that work."""
        from harness.routing import is_valid_label
        assert is_valid_label("a" * publish_doc.MAX_ALIAS_LABEL)
        assert not is_valid_label("a" * (publish_doc.MAX_ALIAS_LABEL + 1))

    def test_a_forty_character_name_now_warns_instead_of_refusing(self, tmp_path):
        """It used to be a hard stage-2 refusal. Under the harness it is publishable."""
        notes = publish_doc.check_name_length("x" * 40)
        assert notes and any("40" in n for n in notes)

    def test_a_short_name_says_nothing(self):
        assert publish_doc.check_name_length("example-design-12") == []

    def test_a_name_over_the_dns_label_limit_still_refuses(self):
        """63 is the DNS limit, not a preference. The harness would refuse it, so refusing
        here turns a 422 into a sentence."""
        with pytest.raises(publish_doc.StageError):
            publish_doc.check_name_length("y" * 64)


class TestEverySameOriginResourceIsDeclared:
    """AC3. `stage_assets` already refuses a reference it cannot ship. This is the other
    half: a resource that WAS staged but never reached the manifest would 404 on a
    deployment that otherwise activated cleanly."""

    def test_a_staged_asset_missing_from_the_manifest_is_refused(self):
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.assert_manifest_covers(["style.css", "diagram.png"],
                                               ["/style.css"])
        assert "diagram.png" in e.value.message

    def test_full_coverage_passes(self):
        publish_doc.assert_manifest_covers(["style.css", "diagram.png"],
                                           ["/style.css", "/diagram.png"])

    def test_no_assets_at_all_is_fine(self):
        publish_doc.assert_manifest_covers([], [])

    def test_a_manifest_entry_with_no_staged_file_is_also_refused(self):
        """The reverse direction: declaring a blob nobody staged means the harness fetches
        something the render never produced."""
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.assert_manifest_covers(["style.css"],
                                               ["/style.css", "/ghost.css"])
        assert "ghost.css" in e.value.message


# --------------------------------------------------------------------------- T6, AC1/AC4

class TestTheManifestIsBuiltFromCommittedBytes:
    """The inversion #36 is really about: the harness does not accept rendered bytes. It
    takes a manifest naming a repo, a commit and per-asset blob ids, then fetches every
    blob FROM GITHUB. So the manifest describes what is COMMITTED, not what is in hand."""

    def _repo(self, tmp_path):
        import subprocess
        root = tmp_path / "repo"
        (root / "docs").mkdir(parents=True)
        (root / "docs" / "d.html").write_text("<html>page</html>", encoding="utf-8")
        (root / "docs" / "s.css").write_text("a{}", encoding="utf-8")
        for argv in (["init", "-q"], ["add", "-A"],
                     ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"]):
            subprocess.run(["git", "-C", str(root), *argv], check=True,
                           capture_output=True)
        return root

    def test_every_declared_field_matches_the_committed_object(self, tmp_path):
        import hashlib
        import subprocess
        root = self._repo(tmp_path)
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
        m = publish_doc.build_manifest(
            root=root, page_path=root / "docs" / "d.html",
            staged=["s.css"], asset_base=root / "docs",
            name="example-design-12", repo="o/r", commit_sha=head)

        assert m["name"] == "example-design-12" and m["repo"] == "o/r"
        assert m["commit_sha"] == head
        assert m["entry_path"] == "/index.html"
        by_url = {a["url_path"]: a for a in m["assets"]}
        assert set(by_url) == {"/index.html", "/s.css"}

        entry = by_url["/index.html"]
        raw = (root / "docs" / "d.html").read_bytes()
        assert entry["repo_path"] == "docs/d.html"
        assert entry["size"] == len(raw)
        assert entry["sha256"] == hashlib.sha256(raw).hexdigest()
        blob = subprocess.run(["git", "-C", str(root), "hash-object", str(root / "docs" / "d.html")],
                              capture_output=True, text=True, check=True).stdout.strip()
        assert entry["blob_id"] == blob

    def test_the_blob_id_is_gits_own_object_id(self, tmp_path):
        """Probed 2026-08-24 and pinned here: the harness looks blobs up by this id, so a
        sha256 in its place would fetch nothing."""
        from harness.control import git_blob_id
        root = self._repo(tmp_path)
        m = publish_doc.build_manifest(
            root=root, page_path=root / "docs" / "d.html", staged=[],
            asset_base=root / "docs", name="n", repo="o/r", commit_sha="a" * 40)
        assert m["assets"][0]["blob_id"] == git_blob_id(
            (root / "docs" / "d.html").read_bytes())

    def test_the_built_manifest_satisfies_the_local_validator(self, tmp_path):
        root = self._repo(tmp_path)
        publish_doc.validate_manifest(publish_doc.build_manifest(
            root=root, page_path=root / "docs" / "d.html", staged=["s.css"],
            asset_base=root / "docs", name="n", repo="o/r", commit_sha="a" * 40))

    def test_no_asset_carries_a_content_type(self, tmp_path):
        """The harness derives it and a sent one is a 422. Checked against the built
        OUTPUT, not the source text: the docstring naming the field in order to explain
        its absence is exactly what should be there."""
        root = self._repo(tmp_path)
        m = publish_doc.build_manifest(
            root=root, page_path=root / "docs" / "d.html", staged=["s.css"],
            asset_base=root / "docs", name="n", repo="o/r", commit_sha="a" * 40)
        assert all("content_type" not in a for a in m["assets"])

    def test_an_asset_outside_the_repository_is_refused(self, tmp_path):
        root = self._repo(tmp_path)
        with pytest.raises(publish_doc.StageError):
            publish_doc.build_manifest(
                root=root, page_path=tmp_path / "elsewhere.html", staged=[],
                asset_base=root / "docs", name="n", repo="o/r", commit_sha="a" * 40)


class TestTheVercelPathIsGone:
    """AC1 and AC4. Each of these is a surface a caller could still reach."""

    @pytest.mark.parametrize("flag", ["--new-project", "--vercel-scope", "--limit"])
    def test_the_retired_flags_are_rejected(self, flag):
        flags = {o for a in publish_doc.build_parser()._actions for o in a.option_strings}
        assert flag not in flags

    @pytest.mark.parametrize("symbol", ["refresh_index", "resolve_project", "deploy",
                                        "deployed_hosts", "aliased_host", "_vercel"])
    def test_the_retired_symbols_are_gone(self, symbol):
        assert not hasattr(publish_doc, symbol), f"{symbol} survived"

    def test_the_script_never_shells_out_to_vercel(self):
        import ast
        tree = ast.parse((SCRIPTS / "publish_doc.py").read_text(encoding="utf-8"))
        literals = [n.value for n in ast.walk(tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        assert [s for s in literals if s.strip() == "vercel"] == []

    def test_build_index_still_imports(self):
        """Finding S5. `index/build_index.py` SURVIVES as the harness's shared renderer;
        only publish_doc's invocation of it and the index's Vercel deploy go."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_bi", SCRIPTS.parent / "index" / "build_index.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod is not None


class TestTheUrlPathIsCanonicallyEncoded:
    """The #34 boundary learning, and the easiest thing in this child to lose:
    `stage_assets` resolves a percent-encoded reference back to the REAL filename, so the
    staged name carries a literal space. Prefixing "/" and sending that is a 422."""

    def _repo(self, tmp_path):
        import subprocess
        root = tmp_path / "r"
        (root / "docs").mkdir(parents=True)
        (root / "docs" / "d.html").write_text("<html>p</html>", encoding="utf-8")
        (root / "docs" / "my diagram.png").write_bytes(b"\x89PNG")
        (root / "docs" / "a+b(c).css").write_text("a{}", encoding="utf-8")
        for argv in (["init", "-q"], ["add", "-A"],
                     ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"]):
            subprocess.run(["git", "-C", str(root), *argv], check=True, capture_output=True)
        return root

    def test_a_space_is_encoded_in_the_url_path_but_not_the_repo_path(self, tmp_path):
        root = self._repo(tmp_path)
        m = publish_doc.build_manifest(
            root=root, page_path=root / "docs" / "d.html", staged=["my diagram.png"],
            asset_base=root / "docs", name="n", repo="o/r", commit_sha="a" * 40)
        a = [x for x in m["assets"] if x["url_path"] != "/index.html"][0]
        assert a["url_path"] == "/my%20diagram.png"
        assert a["repo_path"] == "docs/my diagram.png", "git holds the real name"

    def test_every_character_the_harness_refuses_is_encoded(self, tmp_path):
        root = self._repo(tmp_path)
        m = publish_doc.build_manifest(
            root=root, page_path=root / "docs" / "d.html", staged=["a+b(c).css"],
            asset_base=root / "docs", name="n", repo="o/r", commit_sha="a" * 40)
        a = [x for x in m["assets"] if x["url_path"] != "/index.html"][0]
        assert not (publish_doc._NEEDS_ENCODING & set(a["url_path"]))

    def test_the_built_manifest_survives_its_own_publish_check(self, tmp_path):
        """The regression that matters: publish() refuses an unencoded url_path, so a
        builder that forgets to encode makes every such document unpublishable."""
        root = self._repo(tmp_path)
        m = publish_doc.build_manifest(
            root=root, page_path=root / "docs" / "d.html",
            staged=["my diagram.png", "a+b(c).css"],
            asset_base=root / "docs", name="n", repo="o/r", commit_sha="a" * 40)
        http = FakeHTTP({("POST", "/v1/deployments"): (201, {"deployment_id": 9})})
        assert publish_doc.publish(BASE, m, None, "s3cret", opener=http, env=BRIDGE_OK) == 9

    def test_the_harness_accepts_what_the_builder_produces(self, tmp_path):
        """Parity against the real validator rather than against my reading of it."""
        from harness.routing import canonical_url_path
        root = self._repo(tmp_path)
        m = publish_doc.build_manifest(
            root=root, page_path=root / "docs" / "d.html",
            staged=["my diagram.png", "a+b(c).css"],
            asset_base=root / "docs", name="n", repo="o/r", commit_sha="a" * 40)
        for a in m["assets"]:
            canonical_url_path(a["url_path"])     # raises PathError if not canonical


# --------------------------------------------------------------------------- Step 8a, inline

class TestHeadersAreReadCaseInsensitively:
    """Step 8a, inline mechanical pass. Found by reading, confirmed by measurement.

    `resp.headers` from urllib is an `email.message.Message`, which is case-INSENSITIVE.
    Converting it with `dict()` produces a plain dict, which is not. The harness itself
    sends `X-Doc-Deployment` and `Content-Type` title-cased, so every local test passed —
    but **HTTP/2 lowercases all header names**, and Cloudflare speaks HTTP/2. So this would
    have broken precisely the edge half that nobody can exercise yet, and it would have
    failed as a byte-verification error rather than as anything naming headers.
    """

    def _resp(self, headers, body=b"page"):
        import email.message
        import io as _io
        m = email.message.Message()
        for k, v in headers.items():
            m[k] = v
        r = _io.BytesIO(body)
        r.status = 200
        r.headers = m
        r.__enter__ = lambda s=r: s
        r.__exit__ = lambda *a: False
        return r

    def test_lowercase_headers_are_accepted(self):
        publish_doc.check_verify_response(
            self._resp({"x-doc-deployment": "42",
                        "content-type": "text/html; charset=utf-8"}),
            want=b"page", deployment_id=42, url_path="/index.html")

    def test_title_case_headers_are_still_accepted(self):
        publish_doc.check_verify_response(
            self._resp({"X-Doc-Deployment": "42",
                        "Content-Type": "text/html; charset=utf-8"}),
            want=b"page", deployment_id=42, url_path="/index.html")

    def test_a_wrong_echo_still_fails_whatever_the_case(self):
        with pytest.raises(publish_doc.StageError):
            publish_doc.check_verify_response(
                self._resp({"x-doc-deployment": "41",
                            "content-type": "text/html; charset=utf-8"}),
                want=b"page", deployment_id=42, url_path="/index.html")


class TestTheSharedMimeImportCannotBreakTheWholeScript:
    """Step 8a, inline. A module-level `from harness.manifest import ...` makes the entire
    script unimportable if that package is absent — the process would die before it could
    print a sentence. Finding N7 wanted the SHARED function to prevent drift, and that
    still holds; what changes is that the coupling fails loudly at the point of use."""

    def test_the_import_is_not_performed_at_module_scope(self):
        import ast
        tree = ast.parse((SCRIPTS / "publish_doc.py").read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("harness"):
                raise AssertionError(
                    "harness is imported at module scope; an install without it could not "
                    "even render, which is the one thing that needs no harness at all")

    def test_it_still_resolves_to_the_harness_function(self):
        from harness.manifest import content_type_for
        assert publish_doc.content_type_for("/a.css") == content_type_for("/a.css")


# --------------------------------------------------------------------------- Step 8a, cross-model

class TestTheBearerNeverFollowsARedirect:
    """R1, High. The worst of the wave, and self-inflicted: `NO_REDIRECTS` exists exactly
    so a credential cannot follow a 302, and the two calls that carry the bearer used the
    default opener anyway. A redirect from an allowlisted control origin would have sent
    the publish token to any host the redirect named, straight past the allowlist."""

    def _redirector(self, calls):
        import io as _io
        import urllib.error as _ue

        def opener(req, timeout=None, **kw):
            calls.append((req.full_url, dict(req.header_items())))
            raise _ue.HTTPError(req.full_url, 302, "Found",
                                {"Location": "https://evil.example/"}, _io.BytesIO(b""))
        return opener

    def test_the_read_back_treats_a_redirect_as_a_failure(self):
        calls = []
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.read_active(BASE, "n", "s3cret", opener=self._redirector(calls), env=BRIDGE_OK)
        assert len(calls) == 1, "no request may be made to the redirect target"
        assert "redirect" in e.value.message.lower()

    def test_the_publish_treats_a_redirect_as_a_failure(self):
        calls = []
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.publish(BASE, TestThePublishCall.MANIFEST, None, "s3cret",
                                opener=self._redirector(calls), env=BRIDGE_OK)
        assert len(calls) == 1
        assert "redirect" in e.value.message.lower()

    def test_the_default_opener_for_control_calls_does_not_follow_redirects(self):
        import ast
        src = (SCRIPTS / "publish_doc.py").read_text(encoding="utf-8")
        fn = next(n for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.FunctionDef) and n.name == "_control_call")
        body = ast.unparse(fn)
        assert "urllib.request.urlopen" not in body, (
            "the control calls carry the bearer; their default opener must be the "
            "non-redirecting one")


class TestAnErrorBodyIsNeverEchoedVerbatim:
    """R4, High. A server can reflect the Authorization header into its own JSON error
    body. Interpolating that body into stderr persists the bearer into terminal and CI
    logs, which contradicts the credential guarantee this design states outright."""

    def test_the_bearer_cannot_reach_the_message_through_the_error_body(self):
        import io as _io
        import json as _json
        import urllib.error as _ue
        leak = "s3cret-bearer-value"

        def opener(req, timeout=None, **kw):
            body = _json.dumps({"echo": f"Bearer {leak}"}).encode()
            raise _ue.HTTPError(req.full_url, 500, "boom", {}, _io.BytesIO(body))

        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.publish(BASE, TestThePublishCall.MANIFEST, None, leak, opener=opener, env=BRIDGE_OK)
        assert leak not in e.value.message

    def test_the_status_is_still_reported(self):
        import io as _io
        import urllib.error as _ue

        def opener(req, timeout=None, **kw):
            raise _ue.HTTPError(req.full_url, 500, "boom", {}, _io.BytesIO(b"{}"))

        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.publish(BASE, TestThePublishCall.MANIFEST, None, "t", opener=opener, env=BRIDGE_OK)
        assert "500" in e.value.message


class TestTheAllowlistIsNarrowerThanEveryPrivateNetwork:
    """R2, High. The committed allowlist admitted all of 10/8 and 192.168/16 over
    plaintext, so an attacker-influenced control URL could send the bearer to any reachable
    service on a corporate LAN. Only the docker bridge space has any reason to be here."""

    @pytest.mark.parametrize("ok", ["http://127.0.0.1:8080", "http://localhost:8080"])
    def test_loopback_still_passes_with_no_opt_in(self, ok):
        publish_doc.assert_bearer_destination(ok, env={})

    @pytest.mark.parametrize("ok", ["http://172.17.0.2:8080", "http://172.25.0.2:8080"])
    def test_the_bridge_space_passes_only_with_a_grant_naming_it(self, ok):
        host = urllib.parse.urlsplit(ok).netloc
        publish_doc.assert_bearer_destination(
            ok, env={"DOC_HARNESS_ALLOW_BRIDGE_PLAINTEXT": host})

    @pytest.mark.parametrize("bad", ["http://10.0.17.205:8080", "http://192.168.1.50:8080",
                                     "http://10.1.2.3:9000"])
    def test_the_wider_private_ranges_no_longer_pass(self, bad):
        with pytest.raises(publish_doc.StageError):
            publish_doc.assert_bearer_destination(bad)


class TestAnIndeterminateReadBackRefuses:
    """R6, Medium. A missing field and an explicit null were treated identically, so a
    truncated or wrong-version response published with `expected_active: null` instead of
    refusing a state it could not determine."""

    def test_a_missing_field_refuses_and_publishes_nothing(self):
        http = FakeHTTP({("GET", "/v1/deployments/n"): (200, {"name": "n"})})
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.read_active(BASE, "n", "s3cret", opener=http, env=BRIDGE_OK)
        assert "active_deployment_id" in e.value.message
        assert len(http.calls) == 1

    def test_an_explicit_null_is_still_a_first_publish(self):
        http = FakeHTTP({("GET", "/v1/deployments/n"): (200, {"active_deployment_id": None})})
        assert publish_doc.read_active(BASE, "n", "s3cret", opener=http, env=BRIDGE_OK) is None


class TestACredentialRefusalNamesTheRightStage:
    """R7, Medium. The exit code IS the verdict, so a publish that never happened must not
    report exit 16, which says stage 6 tried and failed."""

    def test_a_missing_publish_token_is_stage_five(self):
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.assert_credentials({}, edge=False)
        assert e.value.stage == 5

    def test_a_missing_access_pair_is_stage_six(self):
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.assert_credentials({**TOKEN_ENV, "CF_ACCESS_CLIENT_ID": "i"}, edge=True)
        assert e.value.stage == 6


class TestResponsesAreBounded:
    """R0, High. A trickling server keeps an unqualified `read()` alive indefinitely, and a
    huge response exhausts memory."""

    def test_an_oversized_control_response_refuses(self):
        import io as _io

        class Huge(_io.BytesIO):
            status = 200
            headers = {"Content-Type": "application/json"}
            def __enter__(self): return self
            def __exit__(self, *a): return False

        payload = b'{"active_deployment_id": null, "pad": "' + b"x" * (publish_doc.MAX_RESPONSE_BYTES + 10) + b'"}'
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.read_active(BASE, "n", "s3cret", env=BRIDGE_OK,
                                    opener=lambda req, timeout=None, **kw: Huge(payload))
        assert "too large" in e.value.message.lower() or "bytes" in e.value.message.lower()

    def test_the_cap_is_a_real_number(self):
        assert isinstance(publish_doc.MAX_RESPONSE_BYTES, int)
        assert publish_doc.MAX_RESPONSE_BYTES > 0


class TestTheMarkdownSourceMustBeCommittedToo:
    """R5, Medium. Every surface says the `.md` and `.html` ship together, and nothing
    checked the markdown. Committing only the HTML published successfully."""

    def test_a_dirty_markdown_source_refuses(self, tmp_path):
        import subprocess
        root = tmp_path / "r"
        (root / "docs").mkdir(parents=True)
        md = root / "docs" / "d.md"
        md.write_text("# one\n", encoding="utf-8")
        (root / "docs" / "d.html").write_text("<html>p</html>", encoding="utf-8")
        for argv in (["init", "-q"], ["add", "-A"],
                     ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"]):
            subprocess.run(["git", "-C", str(root), *argv], check=True, capture_output=True)
        md.write_text("# one, edited after the commit\n", encoding="utf-8")
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.build_manifest(
                root=root, page_path=root / "docs" / "d.html", staged=[],
                asset_base=root / "docs", name="n", repo="o/r", commit_sha="a" * 40,
                md_path=md)
        assert "d.md" in e.value.message


# --------------------------------------------------------------------------- Step 8a, wave 2

class TestTheStatusIsPartOfTheSuccessContract:
    """S2, High. `publish()` discarded the status and accepted any 2xx carrying an integer
    deployment_id, though 201 is defined as the sole success. A wrong-version or no-op
    endpoint answering 200 with an EXISTING id would pass — and if the committed bytes
    happened to be unchanged, verification would pass too and the run would report success
    without having created the deployment it asked for."""

    def test_a_two_hundred_on_the_publish_is_refused(self):
        http = FakeHTTP({("POST", "/v1/deployments"): (200, {"deployment_id": 7})})
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.publish(BASE, TestThePublishCall.MANIFEST, None, "t", opener=http, env=BRIDGE_OK)
        assert "201" in e.value.message

    def test_a_two_oh_one_still_passes(self):
        http = FakeHTTP({("POST", "/v1/deployments"): (201, {"deployment_id": 7})})
        assert publish_doc.publish(BASE, TestThePublishCall.MANIFEST, None, "t",
                                   opener=http, env=BRIDGE_OK) == 7

    def test_the_read_back_requires_exactly_two_hundred(self):
        http = FakeHTTP({("GET", "/v1/deployments/n"): (204, {"active_deployment_id": None})})
        with pytest.raises(publish_doc.StageError):
            publish_doc.read_active(BASE, "n", "t", opener=http, env=BRIDGE_OK)


class TestVerificationResponsesAreBoundedToo:
    """S1, High. The control calls were bounded and verification was not — the same defect,
    the other half. A trickling server evades a per-socket deadline indefinitely."""

    def test_an_oversized_asset_response_refuses(self):
        import io as _io

        class Huge(_io.BytesIO):
            status = 200
            headers = {"X-Doc-Deployment": "42", "Content-Type": "text/html; charset=utf-8"}
            def __enter__(self): return self
            def __exit__(self, *a): return False

        big = b"x" * (publish_doc.MAX_RESPONSE_BYTES + 10)
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.check_verify_response(Huge(big), want=b"x", deployment_id=42,
                                              url_path="/index.html")
        assert "bytes" in e.value.message.lower() or "too large" in e.value.message.lower()


class TestARedirectLocationIsNeverEchoed:
    """S4, High. The body echo was fixed and the HEADER echo was left. An edge server that
    receives the Cloudflare Access credentials can reflect one into `Location`, which then
    lands in terminal and CI logs."""

    def test_neither_access_credential_can_reach_the_message(self):
        import io as _io
        import urllib.error as _ue
        cid, secret = "cf-id-VALUE", "cf-secret-VALUE"

        def opener(req, timeout=None, **kw):
            raise _ue.HTTPError(req.full_url, 302, "Found",
                                {"Location": f"https://x/?a={cid}&b={secret}"},
                                _io.BytesIO(b""))

        req = publish_doc.build_verify_request(
            f"https://n.{publish_doc.PINNED_ZONE}", "/index.html", 42, name="n",
            access=(cid, secret))
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.fetch_for_verify(req, opener=opener)
        assert cid not in e.value.message
        assert secret not in e.value.message
        assert "302" in e.value.message


class TestPlaintextToANonLoopbackHostIsOptedIntoExplicitly:
    """S3, High. 172.16/12 is a whole range, not the one inspected container, so any
    reachable service in it could capture the bearer. Attesting the exact container needs
    docker access the publisher does not have, so the narrower honest control is to make a
    non-loopback plaintext destination a DELIBERATE act rather than a default."""

    def test_loopback_plaintext_needs_no_opt_in(self):
        publish_doc.assert_bearer_destination("http://127.0.0.1:8080", env={})

    def test_a_bridge_address_refuses_without_the_opt_in(self):
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.assert_bearer_destination("http://172.25.0.2:8080", env={})
        assert "DOC_HARNESS_ALLOW_BRIDGE_PLAINTEXT" in e.value.message

    def test_a_bridge_address_passes_with_the_opt_in(self):
        publish_doc.assert_bearer_destination(
            "http://172.25.0.2:8080", env=BRIDGE_OK)

    def test_the_opt_in_does_not_widen_beyond_the_bridge_range(self):
        for bad in ("http://10.0.17.205:8080", "http://192.168.1.5:8080",
                    "http://evil.example.com:8080"):
            with pytest.raises(publish_doc.StageError):
                publish_doc.assert_bearer_destination(
                    bad, env={"DOC_HARNESS_ALLOW_BRIDGE_PLAINTEXT": "172.25.0.2:8080"})


class TestAnAssetCannotBecomeASymlinkAfterStaging:
    """S5, High. `stage_assets` refuses a symlink, then manifest construction REOPENS the
    original path with `resolve()` — so a swap between the two follows the link and
    publishes unrelated committed bytes under an allowed asset URL."""

    def test_a_symlinked_asset_is_refused_at_manifest_time(self, tmp_path):
        import subprocess
        root = tmp_path / "r"
        (root / "docs").mkdir(parents=True)
        (root / "docs" / "d.html").write_text("<html>p</html>", encoding="utf-8")
        (root / "docs" / "other.css").write_text("secret{}", encoding="utf-8")
        (root / "docs" / "a.css").symlink_to(root / "docs" / "other.css")
        for argv in (["init", "-q"], ["add", "-A"],
                     ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"]):
            subprocess.run(["git", "-C", str(root), *argv], check=True, capture_output=True)
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.build_manifest(
                root=root, page_path=root / "docs" / "d.html", staged=["a.css"],
                asset_base=root / "docs", name="n", repo="o/r", commit_sha="a" * 40)
        assert "symlink" in e.value.message.lower()


class TestTheNameWarningActuallyReachesTheOperator:
    """S6, Medium. `check_name_length` returned the note and `derive_name` threw it away, so
    the CLI printed nothing — while the acceptance mapping claims a 40-character name warns
    and passes."""

    def test_derive_name_surfaces_the_note(self, tmp_path):
        import json as _json
        ws = tmp_path / "w.json"
        long_project = "p" * 30
        ws.write_text(_json.dumps({"projects": [{"name": long_project}]}), encoding="utf-8")
        name, notes = publish_doc.derive_name(long_project, "design", "12", ws)
        assert len(name) > 35
        assert notes and any(str(len(name)) in n for n in notes)

    def test_a_short_name_returns_no_notes(self, tmp_path):
        import json as _json
        ws = tmp_path / "w.json"
        ws.write_text(_json.dumps({"projects": [{"name": "example"}]}), encoding="utf-8")
        name, notes = publish_doc.derive_name("example", "design", "12", ws)
        assert name == "example-design-12" and notes == []


class TestADetachedHeadRefuses:
    """S7, Medium. `rev-parse --abbrev-ref HEAD` yields the literal string `HEAD` when
    detached, and passing that through compares against `<remote>/HEAD` — a symbolic ref
    that may well contain the commit, so provenance passed where the design says it must
    refuse."""

    def test_the_literal_head_is_rejected_as_a_branch(self):
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.assert_head_reachable(Path("."), "origin", "HEAD", fetch=False,
                                              runner=FakeGit({}))
        assert "detached" in e.value.message.lower()

    def test_an_empty_branch_name_is_rejected(self):
        with pytest.raises(publish_doc.StageError):
            publish_doc.assert_head_reachable(Path("."), "origin", "", fetch=False,
                                              runner=FakeGit({}))


# --------------------------------------------------------------------------- Step 11, inline

class TestTheFrontDoorDescribesTheCurrentArchitecture:
    """Step 11 inline pass, mechanical lens. The module docstring is the first thing anyone
    reads, and it had gone stale silently: it said "Six stages" and then listed SEVEN, still
    with the Vercel names (`reuse-or-create`, `deploy`, `index`), still citing the corrected
    37-project figure, and never mentioning publish-before-merge — the single fact that now
    defines the file. Nothing pinned it, so nothing caught it."""

    def _doc(self):
        return publish_doc.__doc__ or ""

    def test_the_stage_list_matches_the_stages_that_exist(self):
        doc = self._doc()
        for stage in ("1 render", "2 name", "3 LINT", "4 provenance", "5 publish", "6 verify"):
            assert stage in doc, f"the docstring does not list {stage!r}"
        assert "7 index" not in doc, "stage 7 retired with refresh_index"

    def test_the_stage_count_agrees_with_the_list(self):
        doc = self._doc()
        assert "Six stages" in doc
        import re
        listed = re.findall(r"\b(\d) (?:render|name|LINT|provenance|publish|verify|index)\b", doc)
        assert len(set(listed)) == 6, f"the docstring lists {sorted(set(listed))}, not six stages"

    @pytest.mark.parametrize("gone", ["reuse-or-create", "vercel deploy --prod",
                                      "37 Vercel projects"])
    def test_no_retired_surface_is_still_described(self, gone):
        assert gone not in self._doc()

    def test_the_publish_before_merge_inversion_is_stated(self):
        """It is the one thing a reader must know before running this, and the old docstring
        did not mention it at all."""
        doc = self._doc().lower()
        assert "publish-before-merge" in doc
        assert "committed and pushed before" in doc

    def test_the_two_declared_state_exits_are_documented(self):
        doc = self._doc()
        assert "25" in doc and "26" in doc
        assert "not\na pass" in doc or "not a pass" in doc

    def test_the_git_split_is_described_honestly(self):
        """AC6 used to be "no version control at all", and #36 made that false. The
        docstring must say what actually holds: it READS git and never MUTATES."""
        doc = self._doc()
        assert "never COMMITS" in doc or "never commits" in doc.lower()


# --------------------------------------------------------------------------- Step 11 wave

class TestTheGuardLivesWhereTheCredentialIsAttached:
    """A4, High, and the sharpest finding of the run: neither Step 8a wave caught it.

    `assert_bearer_destination` was called from `main()`, while `_control_request` — the
    function that actually attaches `Authorization: Bearer` — validated nothing. Any caller
    that did not reproduce main()'s separate step could send the token anywhere. The proof
    was already in this file: the tests below used to call `read_active` and `publish`
    directly with no guard, and they worked.
    """

    def test_the_read_back_refuses_an_unapproved_origin_itself(self):
        http = FakeHTTP({})
        with pytest.raises(publish_doc.StageError):
            publish_doc.read_active("https://evil.example", "n", "s3cret", opener=http)
        assert http.calls == [], "no request may be built for an unapproved destination"

    def test_the_publish_refuses_an_unapproved_origin_itself(self):
        http = FakeHTTP({})
        with pytest.raises(publish_doc.StageError):
            publish_doc.publish("https://evil.example", TestThePublishCall.MANIFEST, None,
                                "s3cret", opener=http)
        assert http.calls == []

    def test_an_approved_origin_still_works(self):
        http = FakeHTTP({("GET", "/v1/deployments/n"): (200, {"active_deployment_id": None})})
        assert publish_doc.read_active("http://127.0.0.1:8080", "n", "t", opener=http) is None


class TestTheDestinationRefusalNamesStageFive:
    """P5 and A6, found by BOTH passes. The helper hard-coded stage 6 while main() calls it
    at stage 5, so an unapproved control origin exited 16 — reporting a verification failure
    for a publish that was never attempted."""

    def test_a_control_origin_refusal_is_stage_five(self):
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.assert_bearer_destination("https://evil.example", env={}, stage=5)
        assert e.value.stage == 5

    def test_the_verification_path_still_reports_stage_six(self):
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.assert_bearer_destination("https://evil.example", env={}, stage=6)
        assert e.value.stage == 6


class TestNoResponseFieldIsEchoedWithoutATypeCheck:
    """P4 and A5, found by BOTH passes. My earlier fix stopped rendering the body wholesale
    and left the 409 path interpolating `active_deployment_id` — a field a hostile server
    fills in."""

    def test_a_reflected_credential_in_the_409_field_cannot_reach_the_message(self):
        import io as _io, json as _json
        import urllib.error as _ue
        leak = "s3cret-bearer"

        def opener(req, timeout=None, **kw):
            body = _json.dumps({"active_deployment_id": f"Bearer {leak}"}).encode()
            raise _ue.HTTPError(req.full_url, 409, "conflict", {}, _io.BytesIO(body))

        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.publish("http://127.0.0.1:8080", TestThePublishCall.MANIFEST, 41,
                                leak, opener=opener)
        assert leak not in e.value.message
        assert "race" in e.value.message.lower() or "another publisher" in e.value.message.lower()

    def test_a_genuine_integer_id_is_still_reported(self):
        import io as _io, json as _json
        import urllib.error as _ue

        def opener(req, timeout=None, **kw):
            raise _ue.HTTPError(req.full_url, 409, "conflict", {},
                                _io.BytesIO(_json.dumps({"active_deployment_id": 44}).encode()))

        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.publish("http://127.0.0.1:8080", TestThePublishCall.MANIFEST, 41,
                                "t", opener=opener)
        assert "44" in e.value.message


class TestASlowTrickleCannotHangThePublisher:
    """P1 and A2, found by BOTH passes. A size cap is not a time bound: a peer sending one
    byte inside each socket timeout keeps a single blocking read alive for ever. The design
    promised a wall-clock budget and the code did not implement one."""

    class Trickle:
        status = 200
        headers = {"Content-Type": "application/json"}
        def __init__(self): self.reads = 0
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n=-1):
            self.reads += 1
            return b"x"          # never EOF, never large

    def test_a_trickling_peer_is_cut_off_by_the_deadline(self):
        r = self.Trickle()
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc._read_bounded(r, stage=5, deadline_s=0.15)
        assert "budget" in e.value.message.lower() or "deadline" in e.value.message.lower()
        assert r.reads > 1, "it must actually have looped rather than read once"


class TestTheBridgeOptInNamesOneAddress:
    """P3. An environment flag that authorizes a whole /12 is consent, not validation. It
    cannot become validation without attesting the container, which needs docker access this
    publisher does not have — but it CAN be narrowed from 'any bridge address' to 'exactly
    the one you named'."""

    def test_a_bare_truthy_value_no_longer_authorizes_anything(self):
        with pytest.raises(publish_doc.StageError):
            publish_doc.assert_bearer_destination(
                "http://172.25.0.2:8080", env={"DOC_HARNESS_ALLOW_BRIDGE_PLAINTEXT": "1"},
                stage=5)

    def test_the_exact_named_host_and_port_is_authorized(self):
        publish_doc.assert_bearer_destination(
            "http://172.25.0.2:8080",
            env={"DOC_HARNESS_ALLOW_BRIDGE_PLAINTEXT": "172.25.0.2:8080"}, stage=5)

    def test_a_different_bridge_address_is_not_covered_by_that_grant(self):
        with pytest.raises(publish_doc.StageError):
            publish_doc.assert_bearer_destination(
                "http://172.25.0.9:8080",
                env={"DOC_HARNESS_ALLOW_BRIDGE_PLAINTEXT": "172.25.0.2:8080"}, stage=5)


class TestReachabilityUsesAPrunedFetch:
    """A7. The verdict rests on a local remote-tracking ref. Without pruning, a ref left
    behind by a deleted branch or a changed remote URL still contains HEAD, so the check
    passes while GitHub no longer exposes that commit — and the harness then cannot fetch
    it."""

    def test_the_fetch_prunes(self):
        git = FakeGit({("rev-list", "--count", "origin/main..HEAD"): "0\n"})
        publish_doc.assert_head_reachable(Path("."), "origin", "main", fetch=True, runner=git)
        assert any(c[:2] == ("fetch", "--prune") for c in git.calls), \
            f"expected a pruning fetch, saw {git.calls}"
