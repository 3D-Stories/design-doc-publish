"""Host and path admission. Nothing downstream sees a request this module has not vetted.

Two rules, and both are boundaries rather than conveniences.

**The zone is an allowlist.** The deployment name is the single label in front of
`DOC_HARNESS_ZONE`, and a host that does not end in that zone is refused before the registry is
consulted. Design finding A1: an earlier revision took the leftmost label with no zone check, so
`docs-control.evil.example` reached the control router. Requiring the zone is what makes "control
routes are bound to the control host" a fact rather than a hope about proxy configuration.

**Forwarded headers are never consulted.** `X-Forwarded-Host` and friends are client-settable,
so trusting one would hand the attacker the very field this module exists to check.

**The path is an exact key, not a filesystem path.** The caller requires an exact match against
the deployment's declared assets. No filesystem path is ever derived from request input, so there
is no traversal surface to defend — the refusals below are belt to that braces.

**A manifest url_path and a request path are DIFFERENT STRINGS, and conflating them was a bug.**
Step 11 finding F3: one function served both, and it applied the raw-URL round-trip rule to WSGI
`PATH_INFO`, which PEP 3333 hands over ALREADY percent-decoded. Every asset whose canonical name
needs encoding — a space, a parenthesis, a plus — was therefore accepted at publish and then 404ed
for ever, which is the "activates cleanly and cannot be served" failure that finding B7 exists to
prevent. So there are two functions:

- `canonical_url_path` validates a URL path a publisher wrote. The round-trip rule stays here,
  because here the string really is a URL and one resource must get exactly one spelling.
- `canonical_request_path` validates the decoded path WSGI already produced. It checks segments,
  backslashes and NULs, and it does NOT require an encoded spelling.

Both return the DECODED form, so that single decoded string is the one lookup key, one cache key
and one ETag the original rule was protecting.
"""
from __future__ import annotations

import re
from urllib.parse import quote, unquote

CONTROL_LABEL = "docs-control"
INDEX_LABEL = "docs-index"

# One DNS label: letters, digits and inner hyphens, 1..63 characters. Lowercase only, because
# `resolve_host` lowercases first and an uppercase label at this point means the caller bypassed it.
_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


RESERVED_LABELS = frozenset({CONTROL_LABEL, INDEX_LABEL})


def is_valid_label(label: object) -> bool:
    """One DNS label, lowercase, 1-63 characters. THE shared grammar.

    Step 8a finding R2: publish validated the name with nothing at all while routing
    validated it with `_LABEL`, so a publish could activate a name routing can never
    address. One function, used by both, is the only way those two stay honest.
    """
    return isinstance(label, str) and bool(_LABEL.match(label))


class RouteError(Exception):
    """The Host header is not one this service answers for."""


class PathError(Exception):
    """The request path is not a canonical, non-traversing path."""


def resolve_host(host: str | None, zone: str) -> str:
    """The deployment name for `host`, or raise `RouteError`.

    `zone` is the configured suffix. The host must be exactly one label in front of it.
    """
    if not isinstance(host, str) or not host.strip():
        raise RouteError("no Host header")
    name = host.strip().lower()
    # Strip the port. rpartition avoids mangling an IPv6 literal, which cannot be a
    # deployment host anyway and will fail the label check below.
    if ":" in name:
        name = name.rpartition(":")[0]
    name = name.rstrip(".")
    suffix = "." + zone.strip(".").lower()
    if not name.endswith(suffix):
        raise RouteError(f"host {host!r} is not inside the configured zone")
    label = name[: -len(suffix)]
    if not is_valid_label(label):
        raise RouteError(f"host {host!r} does not carry exactly one valid label before the zone")
    return label


def canonical_url_path(path: str) -> str:
    """The decoded form of a publisher-declared URL path, or raise `PathError`.

    Refusing a non-canonical path outright, rather than normalizing it, is deliberate: two
    spellings of one resource are two cache keys and two ETags for the same bytes, and the
    normalizing version is where traversal bugs live.
    """
    if not isinstance(path, str) or not path.startswith("/"):
        raise PathError(f"path {path!r} must start with '/'")
    if "\\" in path or "\x00" in path:
        raise PathError(f"path {path!r} contains a backslash or a NUL")
    decoded = unquote(path)
    # Decode once, then require the decoded form to RE-ENCODE to exactly what was sent.
    #
    # Step 8a inline review, finding I1. The earlier rule only refused DOUBLE encoding, so
    # `/a%2fb` was accepted and decoded to `/a/b` — a second accepted spelling of one asset,
    # which is precisely what this function's "refuse, do not normalize" rule exists to
    # prevent. The round-trip is the exact test: an encoding that is genuinely REQUIRED (a
    # space, a non-ASCII character) re-encodes to itself and passes, while a redundant one
    # (`%2f` for `/`, `%2e` for `.`) or a malformed one (`%zz`, a truncated `%2`) does not.
    if quote(decoded, safe="/") != path:
        raise PathError(
            f"path {path!r} is not canonically encoded; the same resource is reachable at "
            f"{quote(decoded, safe='/')!r}, and one resource gets exactly one spelling here")
    if "\\" in decoded or "\x00" in decoded:
        raise PathError(f"path {path!r} decodes to a backslash or a NUL")
    if decoded == "/":
        return "/"
    segments = decoded.split("/")[1:]
    for seg in segments:
        if seg in ("", ".", ".."):
            raise PathError(f"path {path!r} is not canonical (empty, '.' or '..' segment)")
    return decoded


def canonical_request_path(path: str) -> str:
    """The already-decoded WSGI `PATH_INFO`, or raise `PathError`.

    PEP 3333 states that a server URL-decodes `PATH_INFO` before the application sees it, so
    there is nothing left to decode and no encoded spelling to compare against. What is still
    worth refusing is a path that is not a plain sequence of non-empty, non-dot segments: those
    are the shapes that mean two keys for one resource, or an attempt at traversal.

    Returning the decoded string unchanged is what makes the asset dictionary a true allowlist:
    the key a publisher declared through `canonical_url_path` and the key a request resolves to
    here are the same decoded bytes.
    """
    if not isinstance(path, str) or not path.startswith("/"):
        raise PathError(f"path {path!r} must start with '/'")
    if "\\" in path or "\x00" in path:
        raise PathError(f"path {path!r} contains a backslash or a NUL")
    if path == "/":
        return "/"
    for seg in path.split("/")[1:]:
        if seg in ("", ".", ".."):
            raise PathError(f"path {path!r} is not canonical (empty, '.' or '..' segment)")
    return path
