"""Host and path admission. Nothing downstream sees a request this module has not vetted.

Two rules, and both are boundaries rather than conveniences.

**The zone is an allowlist.** The deployment name is the single label in front of
`DOC_HARNESS_ZONE`, and a host that does not end in that zone is refused before the registry is
consulted. Design finding A1: an earlier revision took the leftmost label with no zone check, so
`docs-control.evil.example` reached the control router. Requiring the zone is what makes "control
routes are bound to the control host" a fact rather than a hope about proxy configuration.

**Forwarded headers are never consulted.** `X-Forwarded-Host` and friends are client-settable,
so trusting one would hand the attacker the very field this module exists to check.

**The path is an exact key, not a filesystem path.** `canonical_path` refuses anything that is
not already in canonical form, and the caller then requires an exact match against the
deployment's declared assets. No filesystem path is ever derived from request input, so there is
no traversal surface to defend — the refusals below are belt to that braces.
"""
from __future__ import annotations

import re
from urllib.parse import quote, unquote

CONTROL_LABEL = "docs-control"
INDEX_LABEL = "docs-index"

# One DNS label: letters, digits and inner hyphens, 1..63 characters. Lowercase only, because
# `resolve_host` lowercases first and an uppercase label at this point means the caller bypassed it.
_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


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
    if not _LABEL.match(label):
        raise RouteError(f"host {host!r} does not carry exactly one valid label before the zone")
    return label


def canonical_path(path: str) -> str:
    """The decoded request path, or raise `PathError` if it is not already canonical.

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
