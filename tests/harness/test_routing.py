"""`harness.routing` — the access-control boundary, and the path canonicalizer.

Design finding A1 (High, confidence 0.98) is the reason this module exists as its own unit.
An earlier revision took the deployment name from the leftmost label of the Host header with
no zone check at all, so `docs-control.evil.example` reached the control router. The zone is
an allowlist and it is checked BEFORE anything else looks at the request.
"""
import pytest

from harness.routing import (CONTROL_LABEL, INDEX_LABEL, PathError, RouteError,
                             canonical_path, resolve_host)

ZONE = "3dstories.ca"


class TestHostAllowlist:
    def test_a_plain_deployment_host_resolves_to_its_label(self):
        assert resolve_host("known-doc.3dstories.ca", ZONE) == "known-doc"

    def test_the_host_is_lowercased_and_the_port_is_stripped(self):
        assert resolve_host("KNOWN-DOC.3DStories.CA:8080", ZONE) == "known-doc"

    def test_a_trailing_dot_is_tolerated(self):
        # A fully-qualified name with the root dot is the same name.
        assert resolve_host("known-doc.3dstories.ca.", ZONE) == "known-doc"

    def test_the_control_and_index_labels_resolve_to_themselves(self):
        assert resolve_host(f"{CONTROL_LABEL}.3dstories.ca", ZONE) == CONTROL_LABEL
        assert resolve_host(f"{INDEX_LABEL}.3dstories.ca", ZONE) == INDEX_LABEL

    @pytest.mark.parametrize("host", [
        "docs-control.evil.example",     # finding A1, the exact attack
        "docs-control.3dstories.ca.evil.example",
        "evil-3dstories.ca",             # suffix confusion: no dot before the zone
        "x3dstories.ca",
        "a.b.3dstories.ca",              # more than one label
        "3dstories.ca",                  # the bare zone, no label
        ".3dstories.ca",                 # empty label
        "",
        "   ",
        "known-doc.3dstories.ca.attacker.test",
    ])
    def test_a_host_outside_the_zone_is_refused(self, host):
        with pytest.raises(RouteError):
            resolve_host(host, ZONE)

    def test_a_label_that_is_not_a_dns_label_is_refused(self):
        for bad in ["-leading", "trailing-", "under_score", "a" * 64, "up.per"]:
            with pytest.raises(RouteError):
                resolve_host(f"{bad}.3dstories.ca", ZONE)

    def test_a_missing_host_is_refused_rather_than_defaulted(self):
        with pytest.raises(RouteError):
            resolve_host(None, ZONE)


class TestPathCanonicalization:
    def test_a_simple_path_passes_through(self):
        assert canonical_path("/assets/app.css") == "/assets/app.css"

    def test_root_is_preserved_for_the_caller_to_map_to_entry_path(self):
        assert canonical_path("/") == "/"

    def test_percent_encoding_is_decoded_once(self):
        assert canonical_path("/a%20b.html") == "/a b.html"

    @pytest.mark.parametrize("path", [
        "/a/../b", "/a/./b", "/../etc/passwd", "/a//b", "a/b", "",
        "/a\\b", "/a\x00b", "/a/..%2fb", "/%2e%2e/b", "/a/", "/.",
    ])
    def test_a_non_canonical_or_traversing_path_is_refused(self, path):
        with pytest.raises(PathError):
            canonical_path(path)

    def test_a_doubly_encoded_traversal_is_refused(self):
        # Decoding once must not produce something that would traverse if decoded again.
        with pytest.raises(PathError):
            canonical_path("/%252e%252e/b")
