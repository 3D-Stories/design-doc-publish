"""`harness.routing` — the access-control boundary, and the path canonicalizer.

Design finding A1 (High, confidence 0.98) is the reason this module exists as its own unit.
An earlier revision took the deployment name from the leftmost label of the Host header with
no zone check at all, so `docs-control.evil.example` reached the control router. The zone is
an allowlist and it is checked BEFORE anything else looks at the request.
"""
import pytest

from harness.routing import (CONTROL_LABEL, INDEX_LABEL, PathError, RouteError,
                             canonical_url_path, resolve_host)

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
        assert canonical_url_path("/assets/app.css") == "/assets/app.css"

    def test_root_is_preserved_for_the_caller_to_map_to_entry_path(self):
        assert canonical_url_path("/") == "/"

    def test_percent_encoding_is_decoded_once(self):
        assert canonical_url_path("/a%20b.html") == "/a b.html"

    @pytest.mark.parametrize("path", [
        "/a/../b", "/a/./b", "/../etc/passwd", "/a//b", "a/b", "",
        "/a\\b", "/a\x00b", "/a/..%2fb", "/%2e%2e/b", "/a/", "/.",
    ])
    def test_a_non_canonical_or_traversing_path_is_refused(self, path):
        with pytest.raises(PathError):
            canonical_url_path(path)

    def test_a_doubly_encoded_sequence_decodes_to_a_literal_segment(self):
        """This test's ASSERTION was inverted during the Step 8a review. Read the reason.

        It used to demand that `/%252e%252e/b` be refused, on the premise that decoding once
        must not produce something that would traverse "if decoded again". That premise was
        checked and is false for this codebase: nothing decodes a second time. `grep` over
        `harness/` finds `unquote` in exactly one place, this module, and the decoded path
        goes straight to an exact-match lookup against declared asset paths — which were
        themselves canonicalized by this same function at publish time.

        So `/%252e%252e/b` names a literal segment `%2e%2e`, which is an ordinary filename.
        Accepting it is correct AND it is the only spelling of that resource, which is the
        invariant this function actually enforces. The rule that replaced the old one is
        strictly stronger where it matters: `%2f` and a singly-encoded `%2e` used to be
        ACCEPTED and are now refused.
        """
        assert canonical_url_path("/%252e%252e/b") == "/%2e%2e/b"


class TestEncodedSeparatorsAndDuplicateSpellings:
    """Step 8a inline review, finding I1.

    The design's stated rule is that `canonical_url_path` REFUSES a non-canonical path rather
    than normalizing it, because two spellings of one resource are two ETags for the same
    bytes. `%2f` broke that rule: `/a%2fb` was accepted and decoded to `/a/b`, so the same
    asset had two accepted spellings. Not a traversal — the manifest is an exact-match
    allowlist — but exactly the invariant the rule exists to hold.
    """

    @pytest.mark.parametrize("path", [
        "/a%2fb",        # encoded separator
        "/a%2Fb",
        "/a%2e%2e/b",    # encoded dots that decode to a literal `a..` segment
        "/a%2eb",        # encoded dot inside a name
        "/a%zz.html",    # malformed encoding, passed through unchanged by unquote
        "/a%2",          # truncated encoding
    ])
    def test_a_redundantly_encoded_path_is_refused(self, path):
        with pytest.raises(PathError):
            canonical_url_path(path)

    def test_encoding_that_is_genuinely_required_still_works(self):
        # A space MUST be encoded in a URL, so this spelling is the canonical one.
        assert canonical_url_path("/a%20b.html") == "/a b.html"

    def test_a_non_ascii_name_survives_its_required_encoding(self):
        assert canonical_url_path("/caf%C3%A9.html") == "/café.html"

    def test_the_plain_spelling_is_unaffected(self):
        assert canonical_url_path("/a/b.html") == "/a/b.html"

class TestStep11PathBoundary:
    """Step 11 F3: a manifest url_path and a WSGI PATH_INFO are not the same string.

    WSGI hands the application an ALREADY percent-decoded `PATH_INFO`. Applying the raw-URL
    round-trip rule to it rejected every asset whose canonical name needs encoding — a space, a
    parenthesis, a plus — so a deployment activated cleanly and then 404ed for ever. The manifest
    side keeps the round-trip rule, because there the value really is a URL path and one resource
    must still get exactly one spelling; the request side validates the decoded segments instead,
    and the decoded form is the single lookup key both sides agree on.
    """

    def test_a_decoded_space_is_accepted_on_the_request_side(self):
        from harness.routing import canonical_request_path
        assert canonical_request_path("/a b.html") == "/a b.html"

    def test_decoded_punctuation_browsers_send_literally_is_accepted(self):
        from harness.routing import canonical_request_path
        for path in ("/a+b.png", "/Screenshot (1).png", "/a,b.html", "/a&b.html", "/a'b.html"):
            assert canonical_request_path(path) == path

    def test_a_decoded_non_ascii_name_is_accepted(self):
        from harness.routing import canonical_request_path
        assert canonical_request_path("/café.html") == "/café.html"

    def test_the_request_side_still_refuses_dot_and_empty_segments(self):
        from harness.routing import canonical_request_path
        for path in ("/a/../b", "/a//b", "/./a", "/a/"):
            with pytest.raises(PathError):
                canonical_request_path(path)

    def test_the_request_side_still_refuses_a_backslash_or_a_nul(self):
        from harness.routing import canonical_request_path
        with pytest.raises(PathError):
            canonical_request_path("/a\\b")
        with pytest.raises(PathError):
            canonical_request_path("/a\x00b")

    def test_the_request_side_still_requires_a_leading_slash(self):
        from harness.routing import canonical_request_path
        with pytest.raises(PathError):
            canonical_request_path("a.html")

    def test_the_manifest_side_keeps_the_round_trip_rule(self):
        from harness.routing import canonical_url_path
        with pytest.raises(PathError):
            canonical_url_path("/a%2fb.html")
        assert canonical_url_path("/a%20b.html") == "/a b.html"
        assert canonical_url_path("/plain.html") == "/plain.html"

    def test_both_spellings_of_one_resource_collapse_to_one_key(self):
        from harness.routing import canonical_request_path, canonical_url_path
        assert canonical_url_path("/a%20b.html") == canonical_request_path("/a b.html")
