"""The control host: publish, and read back what is active.

**Two independent gates, and this file ships one of them.** Cloudflare Access sits at the edge
(#35) and the `DOC_HARNESS_PUBLISH_TOKEN` bearer sits inside the app. #34 ships the bearer, so it
has to be correct on its own: `hmac.compare_digest`, never `==`, and never echoed into a body.

**Verification happens entirely before the transaction opens.** Every declared asset is resolved
through the tree, fetched, and hash-checked while no lock is held; then one short transaction
touches only SQLite. That ordering is what keeps the write lock at milliseconds no matter how
large the manifest is.

**A publisher's mistake is 422; an upstream failure is 502.** Blaming the publisher for GitHub
being down sends the wrong person to debug it.

**Staged bytes are admitted only after the swap commits** (finding B5), so a losing publisher
cannot evict the active deployment's warm blobs on its way to a 409.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import uuid

from .cache import BlobCache
from .config import HarnessConfig
from .github import (Budget, BudgetExhausted, DeadlineExceeded, GitHubError, NotFound,
                     Unauthorized, Unavailable, resolve_path)
from .manifest import ManifestError, parse_manifest
from .registry import Registry, StalePublisher
from .serving import Response

_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_DEPLOYMENTS = "/v1/deployments"


def _json(status: int, payload: dict, headers: dict | None = None) -> Response:
    body = json.dumps(payload).encode("utf-8")
    h = {"Content-Type": "application/json", "Content-Length": str(len(body))}
    h.update(headers or {})
    return Response(status, h, body)


def _plain(status: int, message: str, alert: str | None = None) -> Response:
    body = (message.rstrip("\n") + "\n").encode("utf-8")
    return Response(status, {"Content-Type": "text/plain; charset=utf-8",
                             "Content-Length": str(len(body))}, body, alert)


def _authorized(headers: dict, cfg: HarnessConfig) -> bool:
    presented = headers.get("Authorization") or ""
    return hmac.compare_digest(presented, f"Bearer {cfg.publish_token}")


def git_blob_id(data: bytes) -> str:
    """Git's own object id for these bytes, so the LOOKUP key is verified too, not just sha256."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def handle_control(method: str, path: str, *, headers: dict, body: bytes | None,
                   registry: Registry, cache: BlobCache, source,
                   cfg: HarnessConfig) -> Response:
    if not _authorized(headers, cfg):
        return _plain(401, "a valid publish bearer is required")

    if method == "GET" and path.startswith(_DEPLOYMENTS + "/"):
        return _read_back(path[len(_DEPLOYMENTS) + 1:], registry)
    if method == "POST" and path == _DEPLOYMENTS:
        if body is None:
            return _plain(411, "Content-Length is required on a publish")
        return _publish(body, registry, cache, source, cfg)
    return _plain(404, "no such control route")


def _read_back(name: str, registry: Registry) -> Response:
    """The contract #36 parses against. Every branch here is pinned by a test."""
    if not _NAME.match(name):
        # 400, never 404: a caller must be able to tell a malformed request from an absent
        # deployment.
        return _plain(400, "that is not a valid deployment name")
    active = registry.active(name)
    if active is None:
        # Finding C9: 200 with a null id, NOT 404. A first publish reads null and passes it
        # straight back as expected_active; a 404 would force the special case this contract
        # exists to remove, because many clients raise on 4xx.
        return _json(200, {"name": name, "active_deployment_id": None,
                           "commit_sha": None, "published_at": None})
    return _json(200, {"name": name, "active_deployment_id": active.deployment_id,
                       "commit_sha": active.commit_sha, "published_at": active.published_at})


def _publish(raw: bytes, registry: Registry, cache: BlobCache, source,
             cfg: HarnessConfig) -> Response:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _plain(400, f"the body is not valid JSON: {exc}")

    try:
        manifest = parse_manifest(payload, cfg)
    except ManifestError as exc:
        return _plain(422, str(exc))

    budget = Budget(cfg.publish_deadline, cfg.max_github_calls)
    publish_id = uuid.uuid4().hex
    staged: list[tuple[str, str, int]] = []
    memo: dict = {}
    try:
        for asset in manifest.assets:
            try:
                entry = resolve_path(source, manifest.repo, manifest.commit_sha,
                                     asset.repo_path, budget, memo=memo,
                                     http_timeout=cfg.http_timeout)
            except NotFound as exc:
                return _plain(422, f"{asset.repo_path}: {exc}")
            except (Unauthorized, Unavailable) as exc:
                return _plain(502, "could not read the repository", alert=str(exc))
            except (DeadlineExceeded, BudgetExhausted) as exc:
                return _plain(504, str(exc))
            except GitHubError as exc:
                # A symlink, a submodule, or a directory where a file was declared: the
                # publisher's manifest is wrong, so this one IS 422.
                return _plain(422, f"{asset.repo_path}: {exc}")

            if entry.blob_id != asset.blob_id:
                return _plain(422, f"{asset.repo_path}: the tree holds blob {entry.blob_id}, "
                                   f"but the manifest declares {asset.blob_id}")
            if entry.size is not None and entry.size != asset.size:
                return _plain(422, f"{asset.repo_path}: the tree says {entry.size} bytes, "
                                   f"but the manifest declares {asset.size}")

            try:
                data = source.blob(manifest.repo, asset.blob_id, budget, cfg.http_timeout)
            except NotFound as exc:
                return _plain(422, f"{asset.repo_path}: {exc}")
            except (Unauthorized, Unavailable) as exc:
                return _plain(502, "could not read the repository", alert=str(exc))
            except (DeadlineExceeded, BudgetExhausted) as exc:
                return _plain(504, str(exc))

            if len(data) > cfg.max_blob_bytes:
                return _plain(413, f"{asset.repo_path} is {len(data)} bytes, over "
                                   f"DOC_HARNESS_MAX_BLOB_BYTES ({cfg.max_blob_bytes})")
            actual_sha = hashlib.sha256(data).hexdigest()
            if actual_sha != asset.sha256:
                return _plain(422, f"{asset.repo_path}: the fetched bytes hash to "
                                   f"{actual_sha[:12]}…, not the declared {asset.sha256[:12]}…")
            if git_blob_id(data) != asset.blob_id:
                return _plain(422, f"{asset.repo_path}: the fetched bytes do not reproduce "
                                   f"the declared git blob id")

            cache.stage(publish_id, asset.blob_id, data, actual_sha)
            staged.append((asset.blob_id, actual_sha, len(data)))

        try:
            deployment_id = registry.publish(manifest)
        except StalePublisher as exc:
            return _json(409, {"error": "stale publisher", "name": manifest.name,
                               "active_deployment_id": exc.current_active})

        # Only now do the bytes enter the LRU (finding B5).
        cache.commit_staging(publish_id, staged)
        return _json(201, {"deployment_id": deployment_id, "name": manifest.name,
                           "commit_sha": manifest.commit_sha,
                           "assets": len(manifest.assets)})
    finally:
        cache.discard_staging(publish_id)
