"""`harness.control` — the one mutating route, its bearer, its bounds, and the read-back.

The read-back contract has one assertion per row of the design's table. Issue #36 has to write
a parser against it, and finding B1 (High) was that an under-specified endpoint forces exactly
the control-API reopening the endpoint was added to avoid.
"""
import hashlib
import json

import pytest

from harness.cache import BlobCache
from harness.config import load_config
from harness.control import handle_control
from harness.github import FakeGitHub, Unavailable
from harness.registry import Registry

CFG = load_config({"DOC_HARNESS_GITHUB_TOKEN": "g", "DOC_HARNESS_PUBLISH_TOKEN": "s3cr3t"})
PAGE = b"<!doctype html><title>hi</title>"
PAGE_SHA = hashlib.sha256(PAGE).hexdigest()
REPO, COMMIT = "owner/repo", "c" * 40


def git_blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


BLOB = git_blob_id(PAGE)


def source(page=PAGE, mode="100644"):
    return FakeGitHub(
        trees={(REPO, COMMIT): [{"path": "docs", "type": "tree", "mode": "040000", "sha": "t1"}],
               (REPO, "t1"): [{"path": "i.html", "type": "blob", "mode": mode,
                               "sha": git_blob_id(page), "size": len(page)}]},
        blobs={(REPO, git_blob_id(page)): page})


def body(**kw):
    base = {"name": "proj-design-1", "repo": REPO, "commit_sha": COMMIT,
            "entry_path": "/index.html",
            "assets": [{"url_path": "/index.html", "repo_path": "docs/i.html",
                        "blob_id": BLOB, "size": len(PAGE), "sha256": PAGE_SHA}],
            "title": "T", "project": "proj", "purpose": "design",
            "published_at": "2026-08-24T00:00:00Z", "expected_active": None}
    base.update(kw)
    return base


@pytest.fixture()
def env(tmp_path):
    reg = Registry(str(tmp_path / "r.db")); reg.initialize()
    cache = BlobCache(str(tmp_path / "c"), max_bytes=100000); cache.initialize()
    yield reg, cache
    reg.close(); cache.close()


def post(env, payload, *, bearer="s3cr3t", src=None, headers=None, cfg=CFG):
    reg, cache = env
    h = {"Authorization": f"Bearer {bearer}"} if bearer is not None else {}
    h.update(headers or {})
    raw = json.dumps(payload).encode() if not isinstance(payload, bytes) else payload
    return handle_control("POST", "/v1/deployments", headers=h, body=raw,
                          registry=reg, cache=cache, source=src or source(), cfg=cfg)


def get(env, path, *, bearer="s3cr3t"):
    reg, cache = env
    h = {"Authorization": f"Bearer {bearer}"} if bearer is not None else {}
    return handle_control("GET", path, headers=h, body=b"", registry=reg, cache=cache,
                          source=source(), cfg=CFG)


class TestBearer:
    def test_no_bearer_is_401(self, env):
        assert post(env, body(), bearer=None).status == 401

    def test_a_wrong_bearer_is_401(self, env):
        assert post(env, body(), bearer="nope").status == 401

    def test_the_correct_bearer_publishes(self, env):
        assert post(env, body()).status == 201

    def test_the_bearer_is_never_echoed(self, env):
        r = post(env, body(), bearer="nope")
        assert "nope" not in r.body.decode() and "s3cr3t" not in r.body.decode()


class TestPublishRefusals:
    def test_a_malformed_json_body_is_400(self, env):
        assert post(env, b"{not json").status == 400

    def test_an_absent_content_length_is_411(self, env):
        reg, cache = env
        r = handle_control("POST", "/v1/deployments",
                           headers={"Authorization": "Bearer s3cr3t", "_no_length": "1"},
                           body=None, registry=reg, cache=cache, source=source(), cfg=CFG)
        assert r.status == 411

    def test_an_invalid_manifest_is_422_naming_the_field(self, env):
        r = post(env, body(entry_path="/missing.html"))
        assert r.status == 422 and "entry_path" in r.body.decode()

    def test_a_blob_absent_from_the_tree_is_422_naming_the_path(self, env):
        r = post(env, body(assets=[{"url_path": "/index.html", "repo_path": "docs/gone.html",
                                    "blob_id": BLOB, "size": len(PAGE), "sha256": PAGE_SHA}]))
        assert r.status == 422 and "docs/gone.html" in r.body.decode()

    def test_a_declared_blob_id_that_disagrees_with_the_tree_is_422(self, env):
        r = post(env, body(assets=[{"url_path": "/index.html", "repo_path": "docs/i.html",
                                    "blob_id": "d" * 40, "size": len(PAGE),
                                    "sha256": PAGE_SHA}]))
        assert r.status == 422

    def test_a_sha256_mismatch_is_422(self, env):
        r = post(env, body(assets=[{"url_path": "/index.html", "repo_path": "docs/i.html",
                                    "blob_id": BLOB, "size": len(PAGE),
                                    "sha256": "e" * 64}]))
        assert r.status == 422

    def test_a_symlink_is_refused(self, env):
        r = post(env, body(), src=source(mode="120000"))
        assert r.status == 422 and "symlink" in r.body.decode()

    def test_an_upstream_failure_is_502_not_422(self, env):
        # Blaming the publisher for an upstream failure sends the wrong person to debug it.
        bad = FakeGitHub(errors={(REPO, COMMIT): Unavailable("github down")})
        r = post(env, body(), src=bad)
        assert r.status == 502

    def test_nothing_is_written_when_verification_fails(self, env):
        reg, _ = env
        post(env, body(entry_path="/missing.html"))
        assert reg._conn().execute("SELECT COUNT(*) FROM deployment").fetchone()[0] == 0


class TestCompareAndSwapOverHttp:
    def test_a_stale_publisher_is_409_carrying_the_current_active_id(self, env):
        first = post(env, body())
        assert first.status == 201
        dep = json.loads(first.body)["deployment_id"]
        second = post(env, body())
        assert second.status == 409
        assert json.loads(second.body)["active_deployment_id"] == dep

    def test_the_correct_expected_active_succeeds(self, env):
        dep = json.loads(post(env, body()).body)["deployment_id"]
        assert post(env, body(expected_active=dep)).status == 201


class TestCacheInteraction:
    def test_a_committed_publish_warms_the_cache(self, env):
        _, cache = env
        post(env, body())
        assert cache.total_bytes() == len(PAGE)

    def test_a_refused_publish_leaves_nothing_staged_or_cached(self, env):
        # Finding B5: a losing publisher must not evict the active deployment's warm blobs.
        import os
        _, cache = env
        post(env, body())
        before = cache.total_bytes()
        post(env, body())                      # stale, refused with 409
        assert cache.total_bytes() == before
        assert os.listdir(cache.staging_root) == []


class TestReadBackContract:
    """One assertion per row of the design's read-back table (finding B1)."""

    def test_no_bearer_is_401(self, env):
        assert get(env, "/v1/deployments/proj-design-1", bearer=None).status == 401

    def test_a_malformed_name_is_400_not_404(self, env):
        r = get(env, "/v1/deployments/Not_A_Label")
        assert r.status == 400

    def test_an_absent_deployment_is_200_with_a_null_id(self, env):
        # Finding C9: 404 forces the special case the contract promised to avoid, because
        # many clients raise on 4xx or skip body parsing entirely.
        r = get(env, "/v1/deployments/never-published-1")
        assert r.status == 200
        payload = json.loads(r.body)
        assert payload == {"name": "never-published-1", "active_deployment_id": None,
                           "commit_sha": None, "published_at": None}

    def test_a_published_deployment_returns_the_exact_shape(self, env):
        dep = json.loads(post(env, body()).body)["deployment_id"]
        r = get(env, "/v1/deployments/proj-design-1")
        assert r.status == 200
        assert r.headers["Content-Type"] == "application/json"
        assert json.loads(r.body) == {"name": "proj-design-1", "active_deployment_id": dep,
                                      "commit_sha": COMMIT,
                                      "published_at": "2026-08-24T00:00:00Z"}

    def test_an_unknown_route_is_404(self, env):
        assert get(env, "/v1/nonsense").status == 404
