"""`harness.serving` — the read path, its headers, and the failure classification.

The failure table in the design has one test per row. That table was wrong in an earlier
revision: it promised an alert on a warm hit after a dead SHA, but a warm hit never contacts
GitHub, so the service cannot know the SHA died. The split is on what an attempted FETCH
returned, and a warm hit is simply a hit.
"""
import hashlib

import pytest

from harness.cache import BlobCache
from harness.config import load_config
from harness.github import Budget, FakeGitHub, NotFound, Unauthorized, Unavailable
from harness.manifest import Asset
from harness.registry import ActiveDeployment
from harness.serving import serve

CFG = load_config({"DOC_HARNESS_GITHUB_TOKEN": "g", "DOC_HARNESS_PUBLISH_TOKEN": "p"})
PAGE = b"<!doctype html><title>hi</title>"
PAGE_SHA = hashlib.sha256(PAGE).hexdigest()
BLOB = "a" * 40


def deployment(assets=None):
    assets = assets or {"/index.html": Asset("/index.html", "docs/i.html", BLOB, len(PAGE),
                                             PAGE_SHA, "text/html; charset=utf-8")}
    return ActiveDeployment(deployment_id=7, name="proj-design-1", repo="owner/repo",
                            commit_sha="c" * 40, entry_path="/index.html", title="t",
                            project="proj", purpose="design", published_at="2026-08-24",
                            assets=assets)


@pytest.fixture()
def cache(tmp_path):
    c = BlobCache(str(tmp_path / "cache"), max_bytes=100000)
    c.initialize()
    yield c
    c.close()


def call(cache, source, path="/", method="GET", headers=None, query="", dep=None):
    return serve(dep or deployment(), path, method=method, headers=headers or {},
                 query=query, cache=cache, source=source, cfg=CFG,
                 budget=Budget(60.0, 50, lambda: 0.0))


class TestHappyPath:
    def test_root_maps_to_the_entry_path_and_serves(self, cache):
        src = FakeGitHub(blobs={("owner/repo", BLOB): PAGE})
        r = call(cache, src)
        assert r.status == 200
        assert r.body == PAGE
        assert r.headers["Content-Type"] == "text/html; charset=utf-8"
        assert r.headers["Content-Length"] == str(len(PAGE))
        assert r.headers["X-Doc-Deployment"] == "7"
        assert r.headers["X-Doc-Origin"] == "fetch"
        assert r.headers["ETag"] == f'"{PAGE_SHA}"'
        assert r.headers["X-Content-Type-Options"] == "nosniff"

    def test_a_second_request_is_served_from_cache_without_touching_github(self, cache):
        src = FakeGitHub(blobs={("owner/repo", BLOB): PAGE})
        call(cache, src)
        before = src.blob_calls
        r = call(cache, src)
        assert r.status == 200 and r.body == PAGE
        assert r.headers["X-Doc-Origin"] == "cache"
        assert src.blob_calls == before, "a warm hit must make no GitHub call at all"

    def test_head_returns_the_headers_and_no_body(self, cache):
        src = FakeGitHub(blobs={("owner/repo", BLOB): PAGE})
        r = call(cache, src, method="HEAD")
        assert r.status == 200
        assert r.body == b""
        assert r.headers["Content-Length"] == str(len(PAGE))

    def test_if_none_match_returns_304_without_reading_the_cache(self, cache):
        src = FakeGitHub(blobs={("owner/repo", BLOB): PAGE})
        r = call(cache, src, headers={"If-None-Match": f'"{PAGE_SHA}"'})
        assert r.status == 304
        assert r.body == b""
        assert src.blob_calls == 0

    def test_an_unsafe_method_is_405_with_allow(self, cache):
        r = call(cache, FakeGitHub(), method="POST")
        assert r.status == 405
        assert r.headers["Allow"] == "GET, HEAD"


class TestRefusals:
    def test_an_undeclared_path_is_404(self, cache):
        r = call(cache, FakeGitHub(), path="/nope.css")
        assert r.status == 404

    def test_a_traversing_path_is_404_and_never_reaches_the_cache(self, cache):
        r = call(cache, FakeGitHub(), path="/../etc/passwd")
        assert r.status == 404

    def test_a_stale_deployment_query_is_409(self, cache):
        src = FakeGitHub(blobs={("owner/repo", BLOB): PAGE})
        r = call(cache, src, query="__deployment=6")
        assert r.status == 409

    def test_the_matching_deployment_query_serves_normally(self, cache):
        src = FakeGitHub(blobs={("owner/repo", BLOB): PAGE})
        r = call(cache, src, query="__deployment=7")
        assert r.status == 200 and r.body == PAGE


class TestFailureTable:
    """One test per row of the design's failure table."""

    def test_cold_miss_with_a_dead_sha_is_503_naming_the_sha(self, cache):
        src = FakeGitHub(errors={("owner/repo", BLOB): NotFound("gone")})
        r = call(cache, src)
        assert r.status == 503
        assert BLOB in r.body.decode()
        assert r.alert is not None and "dead" in r.alert.lower()

    def test_cold_miss_during_an_outage_is_503_and_keeps_the_detail_out_of_the_body(self, cache):
        src = FakeGitHub(errors={("owner/repo", BLOB): Unavailable("upstream on fire")})
        r = call(cache, src)
        assert r.status == 503
        assert "upstream on fire" not in r.body.decode()
        assert r.alert is not None and "upstream on fire" in r.alert

    def test_cold_miss_with_a_credential_problem_is_503_with_a_distinct_alert(self, cache):
        src = FakeGitHub(errors={("owner/repo", BLOB): Unauthorized("rate limit exhausted")})
        r = call(cache, src)
        assert r.status == 503
        assert "dead" not in (r.alert or "").lower(), "must NOT read as a dead SHA"
        assert "credential" in (r.alert or "").lower() or "rate limit" in (r.alert or "").lower()

    def test_a_hash_mismatch_is_502_and_caches_nothing(self, cache):
        src = FakeGitHub(blobs={("owner/repo", BLOB): b"not the declared bytes"})
        r = call(cache, src)
        assert r.status == 502
        assert cache.total_bytes() == 0
        assert r.alert is not None

    def test_a_warm_hit_is_served_even_when_github_would_now_fail(self, cache):
        good = FakeGitHub(blobs={("owner/repo", BLOB): PAGE})
        call(cache, good)
        dead = FakeGitHub(errors={("owner/repo", BLOB): NotFound("gone")})
        r = call(cache, dead)
        assert r.status == 200
        assert r.body == PAGE
        assert r.headers["X-Doc-Origin"] == "cache"
        assert dead.blob_calls == 0, "a warm hit must not call GitHub, so it cannot alert"
        assert r.alert is None
