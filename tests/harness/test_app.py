"""`harness.app` — the WSGI callable. Invoked DIRECTLY: no socket, no thread, no waitress.

That the whole service is reachable this way is the reason the core carries no framework.
"""
import hashlib
import io
import json

import pytest

from harness.app import make_app
from harness.cache import BlobCache
from harness.config import load_config
from harness.github import FakeGitHub
from harness.registry import Registry

PAGE = b"<!doctype html><title>hi</title>"
PAGE_SHA = hashlib.sha256(PAGE).hexdigest()
REPO, COMMIT = "owner/repo", "c" * 40


def git_blob_id(data): return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


BLOB = git_blob_id(PAGE)
CFG = load_config({"DOC_HARNESS_GITHUB_TOKEN": "g", "DOC_HARNESS_PUBLISH_TOKEN": "s3cr3t"})


@pytest.fixture()
def app(tmp_path):
    reg = Registry(str(tmp_path / "r.db")); reg.initialize()
    cache = BlobCache(str(tmp_path / "c"), max_bytes=100000); cache.initialize()
    src = FakeGitHub(
        trees={(REPO, COMMIT): [{"path": "i.html", "type": "blob", "mode": "100644",
                                 "sha": BLOB, "size": len(PAGE)}]},
        blobs={(REPO, BLOB): PAGE})
    yield make_app(cfg=CFG, registry=reg, cache=cache, source=src)
    reg.close(); cache.close()


def call(app, host, path="/", method="GET", headers=None, body=b"", query=""):
    env = {"HTTP_HOST": host, "REQUEST_METHOD": method, "PATH_INFO": path,
           "QUERY_STRING": query, "wsgi.input": io.BytesIO(body),
           "wsgi.errors": io.StringIO(), "CONTENT_LENGTH": str(len(body)) if body else ""}
    for k, v in (headers or {}).items():
        env["HTTP_" + k.upper().replace("-", "_")] = v
    captured = {}

    def start_response(status, response_headers, exc_info=None):
        captured["calls"] = captured.get("calls", 0) + 1
        captured["status"] = status
        captured["headers"] = dict(response_headers)
    chunks = app(env, start_response)
    return captured, b"".join(chunks)


def publish(app):
    payload = {"name": "proj-design-1", "repo": REPO, "commit_sha": COMMIT,
               "entry_path": "/index.html",
               "assets": [{"url_path": "/index.html", "repo_path": "i.html", "blob_id": BLOB,
                           "size": len(PAGE), "sha256": PAGE_SHA}],
               "title": "T", "project": "proj", "purpose": "design",
               "published_at": "2026-08-24T00:00:00Z", "expected_active": None}
    return call(app, "docs-control.3dstories.ca", "/v1/deployments", "POST",
                {"Authorization": "Bearer s3cr3t"}, json.dumps(payload).encode())


class TestDispatch:
    def test_an_unknown_host_is_404(self, app):
        cap, body = call(app, "nope.example.test")
        assert cap["status"].startswith("404")

    def test_the_a1_attack_host_never_reaches_the_control_router(self, app):
        cap, body = call(app, "docs-control.evil.example", "/v1/deployments", "POST",
                         {"Authorization": "Bearer s3cr3t"}, b"{}")
        assert cap["status"].startswith("404")

    def test_control_routes_are_404_on_a_serving_host(self, app):
        cap, _ = call(app, "proj-design-1.3dstories.ca", "/v1/deployments", "POST",
                      {"Authorization": "Bearer s3cr3t"}, b"{}")
        assert cap["status"].startswith("404")

    def test_a_publish_then_a_fetch_round_trips(self, app):
        cap, body = publish(app)
        assert cap["status"].startswith("201"), body
        cap, body = call(app, "proj-design-1.3dstories.ca", "/")
        assert cap["status"].startswith("200")
        assert body == PAGE

    def test_the_index_host_renders(self, app):
        publish(app)
        cap, body = call(app, "docs-index.3dstories.ca", "/")
        assert cap["status"].startswith("200")
        assert b"3dstories" in body

    def test_an_unpublished_name_is_404(self, app):
        cap, _ = call(app, "never-published.3dstories.ca", "/")
        assert cap["status"].startswith("404")


class TestWsgiContract:
    def test_start_response_is_called_exactly_once_per_request(self, app):
        cap, _ = call(app, "proj-design-1.3dstories.ca", "/")
        assert cap["calls"] == 1

    def test_every_response_carries_a_content_length(self, app):
        for host, path in [("nope.example.test", "/"), ("docs-index.3dstories.ca", "/")]:
            cap, body = call(app, host, path)
            assert cap["headers"]["Content-Length"] == str(len(body))

    def test_an_unhandled_error_is_500_with_no_traceback_in_the_body(self, app, monkeypatch):
        import harness.app as mod

        def boom(*a, **k):
            raise RuntimeError("a secret-looking internal detail")
        monkeypatch.setattr(mod, "render_index", boom)
        cap, body = call(app, "docs-index.3dstories.ca", "/")
        assert cap["status"].startswith("500")
        assert b"secret-looking" not in body
        assert b"Traceback" not in body

class TestStep11EncodedAssetNames:
    """Step 11 F3, end to end: an asset whose name needs encoding must actually serve."""

    def test_an_asset_with_a_space_serves_through_the_wsgi_boundary(self, app):
        body = {"name": "proj-design-2", "repo": REPO, "commit_sha": COMMIT,
                "entry_path": "/a%20b.html",
                "assets": [{"url_path": "/a%20b.html", "repo_path": "i.html", "blob_id": BLOB,
                            "size": len(PAGE), "sha256": PAGE_SHA}],
                "expected_active": None}
        raw = json.dumps(body).encode()
        cap, _ = call(app, "docs-control.3dstories.ca", "/v1/deployments", method="POST",
                      headers={"Authorization": "Bearer s3cr3t"}, body=raw)
        assert cap["status"].startswith("201"), cap["status"]

        # waitress hands the application the DECODED path.
        cap, served = call(app, "proj-design-2.3dstories.ca", "/a b.html")
        assert cap["status"].startswith("200"), cap["status"]
        assert served == PAGE

    def test_the_entry_page_still_serves_at_the_root(self, app):
        body = {"name": "proj-design-3", "repo": REPO, "commit_sha": COMMIT,
                "entry_path": "/a%20b.html",
                "assets": [{"url_path": "/a%20b.html", "repo_path": "i.html", "blob_id": BLOB,
                            "size": len(PAGE), "sha256": PAGE_SHA}],
                "expected_active": None}
        call(app, "docs-control.3dstories.ca", "/v1/deployments", method="POST",
             headers={"Authorization": "Bearer s3cr3t"}, body=json.dumps(body).encode())
        cap, served = call(app, "proj-design-3.3dstories.ca", "/")
        assert cap["status"].startswith("200"), cap["status"]
        assert served == PAGE
