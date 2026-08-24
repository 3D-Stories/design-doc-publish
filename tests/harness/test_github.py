"""`harness.github` — the credentialed client, the tree walk, and the deadline.

Nothing here touches the network. The real client takes an injected opener, and the tree walk
takes an injected source, so both are exercised for real against fakes.
"""
import hashlib

import pytest

from harness.github import (Budget, BudgetExhausted, DeadlineExceeded, FakeGitHub, GitHubError,
                            HttpGitHub, NotFound, Unauthorized, Unavailable, resolve_path)

REPO = "owner/repo"
COMMIT = "c" * 40


def blob_id_for(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


@pytest.fixture()
def budget():
    # A generous budget; individual tests tighten it.
    return Budget(deadline_seconds=60.0, max_calls=100, clock=iter_clock())


def iter_clock(step=0.0):
    t = {"now": 0.0}

    def clock():
        t["now"] += step
        return t["now"]
    return clock


class TestBudget:
    def test_remaining_shrinks_as_the_clock_moves(self):
        ticks = iter([0.0, 1.0, 5.0])
        b = Budget(deadline_seconds=10.0, max_calls=5, clock=lambda: next(ticks))
        assert b.remaining() == pytest.approx(9.0)
        assert b.remaining() == pytest.approx(5.0)

    def test_it_raises_once_the_deadline_passes(self):
        ticks = iter([0.0, 11.0])
        b = Budget(deadline_seconds=10.0, max_calls=5, clock=lambda: next(ticks))
        with pytest.raises(DeadlineExceeded):
            b.check()

    def test_it_raises_once_the_call_cap_is_reached(self):
        b = Budget(deadline_seconds=100.0, max_calls=2, clock=lambda: 0.0)
        b.spend_call()
        b.spend_call()
        with pytest.raises(BudgetExhausted):
            b.spend_call()

    def test_the_socket_timeout_is_the_smaller_of_the_two(self):
        # Finding C2: a per-call timeout alone does not bound the operation. A call started
        # just under the deadline must not be allowed another full timeout.
        b = Budget(deadline_seconds=3.0, max_calls=5, clock=lambda: 0.0)
        assert b.socket_timeout(20.0) == pytest.approx(3.0)
        b2 = Budget(deadline_seconds=100.0, max_calls=5, clock=lambda: 0.0)
        assert b2.socket_timeout(20.0) == pytest.approx(20.0)


class TestTreeWalk:
    def test_it_resolves_a_nested_path_to_its_blob(self, budget):
        src = FakeGitHub(trees={
            (REPO, COMMIT): [{"path": "docs", "type": "tree", "mode": "040000", "sha": "t1"}],
            (REPO, "t1"): [{"path": "out", "type": "tree", "mode": "040000", "sha": "t2"}],
            (REPO, "t2"): [{"path": "i.html", "type": "blob", "mode": "100644",
                            "sha": "a" * 40, "size": 12}],
        })
        entry = resolve_path(src, REPO, COMMIT, "docs/out/i.html", budget)
        assert entry.blob_id == "a" * 40
        assert entry.size == 12

    def test_an_executable_blob_is_accepted(self, budget):
        src = FakeGitHub(trees={(REPO, COMMIT): [
            {"path": "x", "type": "blob", "mode": "100755", "sha": "a" * 40, "size": 1}]})
        assert resolve_path(src, REPO, COMMIT, "x", budget).blob_id == "a" * 40

    def test_a_missing_component_raises_not_found_naming_it(self, budget):
        src = FakeGitHub(trees={(REPO, COMMIT): []})
        with pytest.raises(NotFound) as exc:
            resolve_path(src, REPO, COMMIT, "docs/gone.html", budget)
        assert "docs" in str(exc.value)

    @pytest.mark.parametrize("mode,label", [("120000", "symlink"), ("160000", "submodule")])
    def test_a_symlink_or_submodule_is_refused_by_name(self, budget, mode, label):
        src = FakeGitHub(trees={(REPO, COMMIT): [
            {"path": "x", "type": "blob" if mode == "120000" else "commit",
             "mode": mode, "sha": "a" * 40, "size": 1}]})
        with pytest.raises(GitHubError) as exc:
            resolve_path(src, REPO, COMMIT, "x", budget)
        assert label in str(exc.value)

    def test_a_tree_where_a_blob_was_declared_is_refused(self, budget):
        src = FakeGitHub(trees={(REPO, COMMIT): [
            {"path": "x", "type": "tree", "mode": "040000", "sha": "t9"}]})
        with pytest.raises(GitHubError) as exc:
            resolve_path(src, REPO, COMMIT, "x", budget)
        assert "directory" in str(exc.value).lower()

    def test_a_truncated_tree_raises_rather_than_reading_as_absent(self, budget):
        src = FakeGitHub(trees={(REPO, COMMIT): []}, truncated={(REPO, COMMIT)})
        with pytest.raises(Unavailable) as exc:
            resolve_path(src, REPO, COMMIT, "x", budget)
        assert "truncated" in str(exc.value).lower()

    def test_trees_are_memoized_within_one_walk_set(self, budget):
        src = FakeGitHub(trees={
            (REPO, COMMIT): [{"path": "d", "type": "tree", "mode": "040000", "sha": "t1"}],
            (REPO, "t1"): [{"path": "a.css", "type": "blob", "mode": "100644",
                            "sha": "a" * 40, "size": 1},
                           {"path": "b.css", "type": "blob", "mode": "100644",
                            "sha": "b" * 40, "size": 1}],
        })
        memo: dict = {}
        resolve_path(src, REPO, COMMIT, "d/a.css", budget, memo=memo)
        calls_after_first = src.tree_calls
        resolve_path(src, REPO, COMMIT, "d/b.css", budget, memo=memo)
        assert src.tree_calls == calls_after_first, "the second walk must reuse both trees"

    def test_the_walk_spends_the_call_budget(self, budget):
        src = FakeGitHub(trees={(REPO, COMMIT): [
            {"path": "x", "type": "blob", "mode": "100644", "sha": "a" * 40, "size": 1}]})
        resolve_path(src, REPO, COMMIT, "x", budget)
        assert budget.calls_spent == 1


class TestHttpClientErrorMapping:
    def make(self, status=200, body=b"{}", headers=None, raises=None):
        seen = {}

        def opener(request, timeout=None):
            seen["url"] = request.full_url
            seen["timeout"] = timeout
            seen["headers"] = dict(request.headers)
            if raises is not None:
                raise raises
            return _Resp(status, body, headers or {})
        return HttpGitHub(token="ghp_supersecret", api="https://api.github.test",
                          opener=opener), seen

    def test_a_404_raises_not_found(self):
        import urllib.error
        gh, _ = self.make(raises=urllib.error.HTTPError("u", 404, "nf", {}, None))
        with pytest.raises(NotFound):
            gh.blob(REPO, "a" * 40, Budget(60.0, 10, lambda: 0.0))

    def test_a_500_raises_unavailable(self):
        import urllib.error
        gh, _ = self.make(raises=urllib.error.HTTPError("u", 500, "boom", {}, None))
        with pytest.raises(Unavailable):
            gh.blob(REPO, "a" * 40, Budget(60.0, 10, lambda: 0.0))

    def test_a_socket_error_raises_unavailable(self):
        import urllib.error
        gh, _ = self.make(raises=urllib.error.URLError("no route"))
        with pytest.raises(Unavailable):
            gh.blob(REPO, "a" * 40, Budget(60.0, 10, lambda: 0.0))

    def test_a_401_raises_unauthorized(self):
        import urllib.error
        gh, _ = self.make(raises=urllib.error.HTTPError("u", 401, "no", {}, None))
        with pytest.raises(Unauthorized):
            gh.blob(REPO, "a" * 40, Budget(60.0, 10, lambda: 0.0))

    def test_a_rate_limited_403_is_unauthorized_and_says_rate_limit(self):
        import urllib.error
        err = urllib.error.HTTPError("u", 403, "no", {"x-ratelimit-remaining": "0"}, None)
        gh, _ = self.make(raises=err)
        with pytest.raises(Unauthorized) as exc:
            gh.blob(REPO, "a" * 40, Budget(60.0, 10, lambda: 0.0))
        assert "rate limit" in str(exc.value).lower()

    def test_a_plain_403_is_unauthorized_and_does_not_claim_rate_limit(self):
        import urllib.error
        err = urllib.error.HTTPError("u", 403, "no", {"x-ratelimit-remaining": "4999"}, None)
        gh, _ = self.make(raises=err)
        with pytest.raises(Unauthorized) as exc:
            gh.blob(REPO, "a" * 40, Budget(60.0, 10, lambda: 0.0))
        assert "rate limit" not in str(exc.value).lower()

    @pytest.mark.parametrize("status", [401, 403, 404, 500])
    def test_the_token_never_appears_in_an_exception(self, status):
        import urllib.error
        gh, _ = self.make(raises=urllib.error.HTTPError("u", status, "m", {}, None))
        with pytest.raises(GitHubError) as exc:
            gh.blob(REPO, "a" * 40, Budget(60.0, 10, lambda: 0.0))
        assert "ghp_supersecret" not in str(exc.value)
        assert "ghp_supersecret" not in repr(exc.value)

    def test_the_socket_timeout_is_bounded_by_the_remaining_deadline(self):
        gh, seen = self.make(body=b"hello")
        gh.blob(REPO, "a" * 40, Budget(deadline_seconds=2.0, max_calls=10, clock=lambda: 0.0),
                http_timeout=30.0)
        assert seen["timeout"] == pytest.approx(2.0)

    def test_the_raw_media_type_is_requested_for_a_blob(self):
        gh, seen = self.make(body=b"hello")
        gh.blob(REPO, "a" * 40, Budget(60.0, 10, lambda: 0.0))
        assert seen["headers"].get("Accept") == "application/vnd.github.raw"

    def test_a_body_that_outlives_the_deadline_is_cut_off_mid_stream(self):
        # Finding C2's core: a response that trickles must not hold the worker past the
        # deadline just because each individual read returned in time.
        ticks = iter([0.0, 0.1, 0.2, 99.0, 99.0, 99.0])

        def opener(request, timeout=None):
            return _Resp(200, b"x" * (1024 * 1024), {})
        gh = HttpGitHub(token="t", api="https://api.github.test", opener=opener)
        with pytest.raises(DeadlineExceeded):
            gh.blob(REPO, "a" * 40,
                    Budget(deadline_seconds=1.0, max_calls=10, clock=lambda: next(ticks)))


class _Resp:
    def __init__(self, status, body, headers):
        self.status = status
        self._body = body
        self._pos = 0
        self.headers = headers

    def read(self, n=-1):
        if n is None or n < 0:
            chunk, self._pos = self._body[self._pos:], len(self._body)
            return chunk
        chunk = self._body[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestResponseByteBound:
    """Step 8a cross-model finding R3 (High).

    The deadline bounded TIME but not BYTES. Both tree and blob bodies were accumulated in
    memory with no limit, so a malformed or hostile upstream response consumed its full size
    before any caller could check it — bypassing the operator's configured blob cap entirely.
    """

    def test_a_blob_larger_than_its_bound_is_cut_off_mid_stream(self):
        def opener(request, timeout=None):
            return _Resp(200, b"x" * 5_000_000, {})
        gh = HttpGitHub(token="t", api="https://api.github.test", opener=opener)
        with pytest.raises(GitHubError) as exc:
            gh.blob(REPO, "a" * 40, Budget(60.0, 10, lambda: 0.0), max_bytes=1000)
        assert "1000" in str(exc.value)

    def test_a_blob_within_its_bound_still_returns(self):
        def opener(request, timeout=None):
            return _Resp(200, b"x" * 500, {})
        gh = HttpGitHub(token="t", api="https://api.github.test", opener=opener)
        assert len(gh.blob(REPO, "a" * 40, Budget(60.0, 10, lambda: 0.0), max_bytes=1000)) == 500

    def test_a_tree_response_is_bounded_too(self):
        huge = b'{"tree":[' + b'{"path":"x","type":"blob","mode":"100644","sha":"a"},' * 100000
        def opener(request, timeout=None):
            return _Resp(200, huge, {})
        gh = HttpGitHub(token="t", api="https://api.github.test", opener=opener)
        with pytest.raises(GitHubError):
            gh.tree(REPO, COMMIT, Budget(60.0, 10, lambda: 0.0), max_bytes=2000)

class TestStep11UpstreamValidation:
    """Step 11 F5 and F7: a malformed or dying upstream is an outage, never a publisher error."""

    class _Resp:
        def __init__(self, payload=None, raiser=None):
            self._payload = payload
            self._raiser = raiser
            self._done = False

        def read(self, _n=None):
            if self._raiser is not None:
                raise self._raiser
            if self._done:
                return b""
            self._done = True
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    def _client(self, resp):
        from harness.github import HttpGitHub
        return HttpGitHub("tok", "https://api.example", opener=lambda *_a, **_k: resp)

    def test_a_tree_response_with_no_tree_key_is_an_outage(self, budget):
        import json as _json
        from harness.github import Unavailable
        client = self._client(self._Resp(_json.dumps({"truncated": False}).encode()))
        with pytest.raises(Unavailable):
            client.tree(REPO, COMMIT, budget)

    def test_a_tree_response_with_a_non_list_tree_is_an_outage(self, budget):
        import json as _json
        from harness.github import Unavailable
        client = self._client(self._Resp(_json.dumps({"tree": {}, "truncated": False}).encode()))
        with pytest.raises(Unavailable):
            client.tree(REPO, COMMIT, budget)

    def test_a_tree_entry_missing_its_path_is_an_outage(self, budget):
        import json as _json
        from harness.github import Unavailable
        payload = {"tree": [{"type": "blob", "mode": "100644", "sha": "a" * 40, "size": 1}],
                   "truncated": False}
        client = self._client(self._Resp(_json.dumps(payload).encode()))
        with pytest.raises(Unavailable):
            client.tree(REPO, COMMIT, budget)

    def test_a_well_formed_tree_response_still_parses(self, budget):
        import json as _json
        payload = {"tree": [{"path": "i.html", "type": "blob", "mode": "100644",
                             "sha": "a" * 40, "size": 3}],
                   "truncated": False}
        client = self._client(self._Resp(_json.dumps(payload).encode()))
        entries, truncated = client.tree(REPO, COMMIT, budget)
        assert truncated is False
        assert [e.path for e in entries] == ["i.html"]

    def test_a_timeout_while_streaming_the_body_is_an_outage(self, budget):
        from harness.github import Unavailable
        client = self._client(self._Resp(raiser=TimeoutError("read timed out")))
        with pytest.raises(Unavailable):
            client.blob(REPO, "a" * 40, budget)

    def test_an_oserror_while_streaming_the_body_is_an_outage(self, budget):
        from harness.github import Unavailable
        client = self._client(self._Resp(raiser=OSError(104, "Connection reset by peer")))
        with pytest.raises(Unavailable):
            client.blob(REPO, "a" * 40, budget)
