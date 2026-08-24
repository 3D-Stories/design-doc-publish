"""The read path: manifest lookup, response headers, and the failure classification.

**The failure split is on what an attempted FETCH returned.** An earlier revision's table
promised an alert on a warm hit after a dead SHA, and the peer consult correctly pointed out
that this is unreachable: an immutable, TTL-free cache does not contact GitHub on a hit, so the
service cannot know the SHA died. A warm hit is simply a hit. The rows below classify what came
back when the service actually asked.

**Upstream detail never reaches the response body.** A 503 says a plain sentence; the reason
goes to the alert line, which is a log. The one exception is the dead-SHA case, where naming the
blob is the whole diagnostic value — and a blob id is public information in a repository the
caller can already read.

**No filesystem path is derived from request input.** The asset table is the allowlist and the
cache is addressed by blob id, so 404 for an undeclared path is a dictionary miss, not a probe.

**The request path goes through `canonical_request_path`, never the manifest validator.** Step 11
finding F3: WSGI hands this layer an already-decoded path, and validating it as though it were a
raw URL made every asset needing encoding unreachable.
"""
from __future__ import annotations

import dataclasses
import hashlib
from urllib.parse import parse_qs

from .cache import BlobCache, CacheConflict
from .config import HarnessConfig
from .github import (Budget, GitHubError, NotFound, Unauthorized, Unavailable)
from .manifest import Asset
from .registry import ActiveDeployment
from .routing import PathError, canonical_request_path

_SAFE_METHODS = ("GET", "HEAD")


@dataclasses.dataclass
class Response:
    status: int
    headers: dict
    body: bytes
    alert: str | None = None


def _text(status: int, message: str, alert: str | None = None) -> Response:
    body = (message.rstrip("\n") + "\n").encode("utf-8")
    return Response(status, {"Content-Type": "text/plain; charset=utf-8",
                             "Content-Length": str(len(body))}, body, alert)


def _headers_for(asset: Asset, deployment_id: int, origin: str, length: int) -> dict:
    return {
        "Content-Type": asset.content_type,
        "Content-Length": str(length),
        "ETag": f'"{asset.sha256}"',
        "X-Doc-Deployment": str(deployment_id),
        "X-Doc-Origin": origin,
        "X-Content-Type-Options": "nosniff",
    }


def serve(deployment: ActiveDeployment, path: str, *, method: str, headers: dict,
          query: str, cache: BlobCache, source, cfg: HarnessConfig,
          budget: Budget) -> Response:
    if method not in _SAFE_METHODS:
        r = _text(405, f"{method} is not allowed here")
        r.headers["Allow"] = "GET, HEAD"
        return r

    if query:
        wanted = (parse_qs(query).get("__deployment") or [None])[0]
        if wanted is not None and wanted != str(deployment.deployment_id):
            return _text(409, f"this name now serves deployment "
                              f"{deployment.deployment_id}, not {wanted}")

    try:
        clean = canonical_request_path(path)
    except PathError:
        return _text(404, "not found")
    if clean == "/":
        clean = deployment.entry_path

    asset = deployment.assets.get(clean)
    if asset is None:
        return _text(404, "not found")

    if headers.get("If-None-Match") == f'"{asset.sha256}"':
        return Response(304, {"ETag": f'"{asset.sha256}"'}, b"")

    fh = cache.open(asset.blob_id, asset.sha256, asset.size)
    if fh is not None:
        with fh:
            data = fh.read()
        body = b"" if method == "HEAD" else data
        return Response(200, _headers_for(asset, deployment.deployment_id, "cache", len(data)),
                        body)

    # Step 8a finding R5. This used to call `source.blob` DIRECTLY, which left
    # `BlobCache.get_or_fetch` — the single-flight coalescer, written and tested in its own
    # module — reachable from nothing but its own tests. A grep proved it. The cost was real:
    # a cold burst on one page made one upstream call PER REQUEST, which is how a recoverable
    # cold start turns into a rate-limit 503 for everybody.
    #
    # The fetch closure raises the SAME typed errors as before, and `get_or_fetch` does not
    # catch them, so each waiter still receives its own correctly classified failure rather
    # than a shared generic one.
    def _fetch() -> tuple[bytes, str]:
        fetched = source.blob(deployment.repo, asset.blob_id, budget, cfg.http_timeout,
                              max_bytes=cfg.max_blob_bytes)
        # The DECLARED hash, never the fetched one. Handing `put` the hash of whatever
        # arrived would make its integrity check compare a value to itself, and bytes that
        # failed the manifest's check would be cached anyway — caught by a test that asserts
        # the cache stays empty after a mismatch.
        return fetched, asset.sha256

    try:
        data = cache.get_or_fetch(asset.blob_id, asset.sha256, asset.size, _fetch)
    except CacheConflict as exc:
        return _text(
            502, "this page failed its integrity check and was not served",
            alert=f"integrity failure: blob {asset.blob_id} for {deployment.name}{clean}: "
                  f"{exc}; nothing was cached or served")
    except NotFound:
        return _text(
            503,
            f"this page's content is no longer reachable: git blob {asset.blob_id} is gone",
            alert=f"dead SHA: blob {asset.blob_id} for {deployment.name}{clean} returned 404 "
                  f"from {deployment.repo}; the deployment is active but its bytes are not "
                  f"reachable")
    except Unauthorized as exc:
        return _text(
            503, "this page is temporarily unavailable",
            alert=f"credential or rate limit problem reading {deployment.repo}: {exc}")
    except (Unavailable, GitHubError) as exc:
        return _text(503, "this page is temporarily unavailable",
                     alert=f"upstream failure reading {deployment.repo}: {exc}")

    # `get_or_fetch` already verified and stored the bytes: `BlobCache.put` refuses anything
    # whose SHA-256 disagrees with what was declared, and that refusal arrives here as the
    # CacheConflict handled above. This check is the belt to that braces, and it also covers
    # the path where a waiter received bytes from a leader's in-memory result.
    actual = hashlib.sha256(data).hexdigest()
    if actual != asset.sha256:
        return _text(
            502, "this page failed its integrity check and was not served",
            alert=f"integrity failure: blob {asset.blob_id} for {deployment.name}{clean} "
                  f"hashed to {actual[:12]}… but the manifest declares {asset.sha256[:12]}…; "
                  f"nothing was cached or served")

    body = b"" if method == "HEAD" else data
    return Response(200, _headers_for(asset, deployment.deployment_id, "fetch", len(data)), body)
