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
# Hosts are built from the CONFIGURED zone, never from a literal: the zone moved from the apex
# to `docs.` so that every host this service answers sits inside the `*.docs` Access application.
ZONE = CFG.zone
# The one host that must stay a literal, because the point of its test is that it is now refused.
OLD_APEX_INDEX_HOST = "docs-index.3dstories.ca"


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
    return call(app, f"docs-control.{ZONE}", "/v1/deployments", "POST",
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
        cap, _ = call(app, f"proj-design-1.{ZONE}", "/v1/deployments", "POST",
                      {"Authorization": "Bearer s3cr3t"}, b"{}")
        assert cap["status"].startswith("404")

    def test_a_publish_then_a_fetch_round_trips(self, app):
        cap, body = publish(app)
        assert cap["status"].startswith("201"), body
        cap, body = call(app, f"proj-design-1.{ZONE}", "/")
        assert cap["status"].startswith("200")
        assert body == PAGE

    def test_the_index_host_renders(self, app):
        publish(app)
        cap, body = call(app, f"index.{ZONE}", "/")
        assert cap["status"].startswith("200")
        assert b"3dstories" in body

    def test_the_index_is_served_at_index_on_the_zone(self, app):
        # `resolve_host` accepts exactly ONE label before the configured zone. With the zone at
        # the apex, no `*.docs.3dstories.ca` name could ever be answered — so the Access
        # application narrowed to that wildcard protected nothing this service serves. The zone
        # moved under `docs.` and the index label became `index`, which is the one pair that
        # puts the index inside the protected wildcard.
        publish(app)
        cap, body = call(app, "index.3dstories.ca", "/")
        assert cap["status"].startswith("200")
        assert b"3dstories" in body

    def test_the_old_apex_index_host_is_no_longer_answered(self, app):
        # Publishes first so the ONLY variable is the host: an empty registry is its own error
        # path, and this test must fail on routing rather than on having nothing to render.
        # Two labels before the new zone, so routing refuses this rather than serving the index
        # on a name the Access application does not cover.
        publish(app)
        cap, _ = call(app, OLD_APEX_INDEX_HOST, "/")
        assert cap["status"].startswith("404")

    def test_an_unpublished_name_is_404(self, app):
        cap, _ = call(app, f"never-published.{ZONE}", "/")
        assert cap["status"].startswith("404")


class TestConventionResolution:
    """A document serves the moment its file exists in a repository — owner decision D38.

    Nothing publishes it and nothing registers it, so these hostnames have NO registry row.
    """

    @pytest.fixture()
    def app_with_repo(self, tmp_path):
        from harness.registry import Registry
        reg = Registry(str(tmp_path / "r2.db")); reg.initialize()
        cache = BlobCache(str(tmp_path / "c2"), max_bytes=100000); cache.initialize()
        src = FakeGitHub(
            trees={("3D-Stories/rawgentic", COMMIT): [
                {"path": "docs/planning/2026-08-19-unified-roadmap.html", "type": "blob",
                 "mode": "100644", "sha": BLOB, "size": len(PAGE)}]},
            blobs={("3D-Stories/rawgentic", BLOB): PAGE},
            commits={("3D-Stories/rawgentic", "HEAD"): COMMIT},
            repos=["rawgentic"])
        yield make_app(cfg=CFG, registry=reg, cache=cache, source=src)
        reg.close(); cache.close()

    def test_a_never_published_document_serves_from_github(self, app_with_repo):
        cap, body = call(app_with_repo,
                         f"2026-08-19-rawgentic-unified-roadmap.{ZONE}", "/")
        assert cap["status"].startswith("200"), cap["status"]
        assert body == PAGE

    def test_a_hostname_naming_no_real_repository_is_404(self, app_with_repo):
        cap, _ = call(app_with_repo, f"2026-08-19-notarepo-whatever.{ZONE}", "/")
        assert cap["status"].startswith("404")

    def test_a_hostname_naming_a_missing_document_is_404(self, app_with_repo):
        cap, _ = call(app_with_repo, f"2026-08-19-rawgentic-nothing-here.{ZONE}", "/")
        assert cap["status"].startswith("404")


class TestWsgiContract:
    def test_start_response_is_called_exactly_once_per_request(self, app):
        cap, _ = call(app, f"proj-design-1.{ZONE}", "/")
        assert cap["calls"] == 1

    def test_every_response_carries_a_content_length(self, app):
        for host, path in [("nope.example.test", "/"), (f"index.{ZONE}", "/")]:
            cap, body = call(app, host, path)
            assert cap["headers"]["Content-Length"] == str(len(body))

    def test_an_unhandled_error_is_500_with_no_traceback_in_the_body(self, app, monkeypatch):
        import harness.app as mod

        def boom(*a, **k):
            raise RuntimeError("a secret-looking internal detail")
        monkeypatch.setattr(mod, "render_index", boom)
        cap, body = call(app, f"index.{ZONE}", "/")
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
        cap, _ = call(app, f"docs-control.{ZONE}", "/v1/deployments", method="POST",
                      headers={"Authorization": "Bearer s3cr3t"}, body=raw)
        assert cap["status"].startswith("201"), cap["status"]

        # waitress hands the application the DECODED path.
        cap, served = call(app, f"proj-design-2.{ZONE}", "/a b.html")
        assert cap["status"].startswith("200"), cap["status"]
        assert served == PAGE

    def test_the_entry_page_still_serves_at_the_root(self, app):
        body = {"name": "proj-design-3", "repo": REPO, "commit_sha": COMMIT,
                "entry_path": "/a%20b.html",
                "assets": [{"url_path": "/a%20b.html", "repo_path": "i.html", "blob_id": BLOB,
                            "size": len(PAGE), "sha256": PAGE_SHA}],
                "expected_active": None}
        call(app, f"docs-control.{ZONE}", "/v1/deployments", method="POST",
             headers={"Authorization": "Bearer s3cr3t"}, body=json.dumps(body).encode())
        cap, served = call(app, f"proj-design-3.{ZONE}", "/")
        assert cap["status"].startswith("200"), cap["status"]
        assert served == PAGE
