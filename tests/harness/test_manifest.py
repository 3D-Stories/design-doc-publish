"""`harness.manifest` — the publisher's payload is untrusted input, parsed before anything else.

Pure: no I/O, no network, no database. Everything here is decided from the bytes of the request
plus the config, which is what makes the whole publish-refusal surface cheap to test.
"""
import pytest

from harness.routing import RESERVED_LABELS

from harness.config import load_config
from harness.manifest import ManifestError, parse_manifest

CFG = load_config({"DOC_HARNESS_GITHUB_TOKEN": "g", "DOC_HARNESS_PUBLISH_TOKEN": "p"})


def asset(url_path="/index.html", **kw):
    base = {"url_path": url_path, "repo_path": "docs/out/index.html",
            "blob_id": "a" * 40, "size": 10, "sha256": "b" * 64}
    base.update(kw)
    return base


def payload(**kw):
    base = {"name": "proj-design-12", "repo": "owner/repo", "commit_sha": "c" * 40,
            "entry_path": "/index.html", "assets": [asset()],
            "title": "A design", "project": "proj", "purpose": "design",
            "published_at": "2026-08-24T00:00:00Z", "expected_active": None}
    base.update(kw)
    return base


class TestRequiredFields:
    @pytest.mark.parametrize("field", ["name", "repo", "commit_sha", "entry_path", "assets"])
    def test_a_missing_required_field_names_itself(self, field):
        body = payload()
        del body[field]
        with pytest.raises(ManifestError) as exc:
            parse_manifest(body, CFG)
        assert field in str(exc.value)

    @pytest.mark.parametrize("field", ["url_path", "repo_path", "blob_id", "size", "sha256"])
    def test_a_missing_asset_field_names_itself(self, field):
        a = asset()
        del a[field]
        with pytest.raises(ManifestError) as exc:
            parse_manifest(payload(assets=[a], entry_path="/index.html"), CFG)
        assert field in str(exc.value)

    def test_a_body_that_is_not_an_object_is_refused(self):
        with pytest.raises(ManifestError):
            parse_manifest([1, 2, 3], CFG)

    def test_expected_active_absent_is_not_the_same_as_null(self):
        body = payload()
        del body["expected_active"]
        with pytest.raises(ManifestError) as exc:
            parse_manifest(body, CFG)
        assert "expected_active" in str(exc.value)


class TestHashAndShapeChecks:
    def test_a_blob_id_that_is_not_40_hex_is_refused(self):
        with pytest.raises(ManifestError):
            parse_manifest(payload(assets=[asset(blob_id="nope")]), CFG)

    def test_a_sha256_that_is_not_64_hex_is_refused(self):
        with pytest.raises(ManifestError):
            parse_manifest(payload(assets=[asset(sha256="nope")]), CFG)

    def test_a_commit_sha_that_is_not_40_hex_is_refused(self):
        with pytest.raises(ManifestError):
            parse_manifest(payload(commit_sha="HEAD"), CFG)

    def test_a_repo_that_is_not_owner_slash_name_is_refused(self):
        for bad in ["repo", "owner/repo/extra", "owner/", "/repo", "own er/repo"]:
            with pytest.raises(ManifestError):
                parse_manifest(payload(repo=bad), CFG)

    def test_a_negative_or_non_integer_size_is_refused(self):
        for bad in [-1, "10", 1.5, None]:
            with pytest.raises(ManifestError):
                parse_manifest(payload(assets=[asset(size=bad)]), CFG)


class TestBounds:
    def test_more_assets_than_the_cap_is_refused(self):
        many = [asset(url_path=f"/a{i}.css") for i in range(CFG.max_assets + 1)]
        many.append(asset())
        with pytest.raises(ManifestError) as exc:
            parse_manifest(payload(assets=many), CFG)
        assert "DOC_HARNESS_MAX_ASSETS" in str(exc.value)

    def test_a_declared_size_over_the_blob_cap_is_refused(self):
        with pytest.raises(ManifestError) as exc:
            parse_manifest(payload(assets=[asset(size=CFG.max_blob_bytes + 1)]), CFG)
        assert "DOC_HARNESS_MAX_BLOB_BYTES" in str(exc.value)

    def test_a_declared_total_over_the_publish_cap_is_refused(self):
        # Each asset must stay UNDER the per-blob cap, or that check fires first and this
        # test would pass while proving nothing about the total. 100 MiB blob cap,
        # 256 MiB publish cap, so three at the blob cap sum past it.
        each = CFG.max_blob_bytes
        assert each * 3 > CFG.max_publish_bytes, "the two caps no longer make this test meaningful"
        assets = [asset(url_path="/index.html", size=each),
                  asset(url_path="/b.css", size=each),
                  asset(url_path="/c.css", size=each)]
        with pytest.raises(ManifestError) as exc:
            parse_manifest(payload(assets=assets), CFG)
        assert "DOC_HARNESS_MAX_PUBLISH_BYTES" in str(exc.value)


class TestPathRules:
    def test_a_duplicate_url_path_is_refused(self):
        with pytest.raises(ManifestError) as exc:
            parse_manifest(payload(assets=[asset(), asset()]), CFG)
        assert "duplicate" in str(exc.value).lower()

    def test_a_non_canonical_url_path_is_refused(self):
        with pytest.raises(ManifestError):
            parse_manifest(payload(assets=[asset(url_path="/a/../b.html")],
                                   entry_path="/a/../b.html"), CFG)

    def test_an_entry_path_matching_no_declared_asset_is_refused(self):
        # Finding B7: otherwise a manifest passes every per-asset check and activates with
        # a deployment whose front page is 404.
        with pytest.raises(ManifestError) as exc:
            parse_manifest(payload(entry_path="/missing.html"), CFG)
        assert "entry_path" in str(exc.value)

    def test_a_non_canonical_entry_path_is_refused(self):
        with pytest.raises(ManifestError) as exc:
            parse_manifest(payload(entry_path="/./index.html"), CFG)
        assert "entry_path" in str(exc.value)


class TestContentTypeDerivation:
    @pytest.mark.parametrize("path,expected", [
        ("/index.html", "text/html; charset=utf-8"),
        ("/app.css", "text/css; charset=utf-8"),
        ("/app.js", "text/javascript; charset=utf-8"),
        ("/d.svg", "image/svg+xml"),
        ("/d.png", "image/png"),
        ("/d.jpg", "image/jpeg"),
        ("/d.jpeg", "image/jpeg"),
        ("/d.webp", "image/webp"),
        ("/f.woff2", "font/woff2"),
        ("/d.json", "application/json"),
        ("/d.txt", "text/plain; charset=utf-8"),
        ("/d.wat", "application/octet-stream"),
        ("/noextension", "application/octet-stream"),
        ("/D.HTML", "text/html; charset=utf-8"),
    ])
    def test_the_type_comes_from_the_extension_not_the_publisher(self, path, expected):
        # Finding S7: the confirmed spec's manifest contract carries no content type, so
        # taking one from the publisher would silently widen the contract #36 must satisfy.
        m = parse_manifest(payload(assets=[asset(url_path=path)], entry_path=path), CFG)
        assert m.assets[0].content_type == expected

    def test_a_publisher_supplied_content_type_is_ignored(self):
        m = parse_manifest(payload(assets=[asset(content_type="text/evil")]), CFG)
        assert m.assets[0].content_type == "text/html; charset=utf-8"


def test_a_valid_manifest_round_trips_its_fields():
    m = parse_manifest(payload(), CFG)
    assert m.name == "proj-design-12"
    assert m.repo == "owner/repo"
    assert m.entry_path == "/index.html"
    assert m.expected_active is None
    assert m.total_bytes == 10
    assert [a.url_path for a in m.assets] == ["/index.html"]


class TestDeploymentNameValidation:
    """Step 8a cross-model finding R2 (High).

    The parser accepted uppercase, underscores, spaces, multi-label names, over-long labels
    and the RESERVED names. Such a publish returned 201 and became active in SQLite while
    routing could never address it — and `docs-control` would be permanently shadowed by the
    control host. An activated deployment that can never be served is worse than a refusal.
    """

    @pytest.mark.parametrize("bad", [
        "Docs-Control", "has_underscore", "has space", "two.labels", "-leading",
        "trailing-", "a" * 64, "", "   ",
    ])
    def test_a_name_that_routing_could_never_address_is_refused(self, bad):
        with pytest.raises(ManifestError) as exc:
            parse_manifest(payload(name=bad), CFG)
        assert "name" in str(exc.value)

    @pytest.mark.parametrize("reserved", sorted(RESERVED_LABELS))
    def test_a_reserved_name_is_refused(self, reserved):
        with pytest.raises(ManifestError) as exc:
            parse_manifest(payload(name=reserved), CFG)
        assert reserved in str(exc.value)

    def test_a_valid_label_still_passes(self):
        assert parse_manifest(payload(name="proj-design-12"), CFG).name == "proj-design-12"
        assert parse_manifest(payload(name="a"), CFG).name == "a"
        assert parse_manifest(payload(name="a" * 63), CFG).name == "a" * 63

class TestStep11RepoSegments:
    """Step 11 F13: a dot segment must not reach the interpolated GitHub URL."""

    def test_a_repo_of_dot_dot_segments_is_refused(self):
        for repo in ("../..", "owner/..", "../repo", "./repo", "owner/."):
            with pytest.raises(ManifestError):
                parse_manifest(payload(repo=repo), CFG)

    def test_an_ordinary_repo_with_dots_in_its_name_still_passes(self):
        m = parse_manifest(payload(repo="3D-Stories/design.doc-publish"), CFG)
        assert m.repo == "3D-Stories/design.doc-publish"
