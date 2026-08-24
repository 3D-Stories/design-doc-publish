"""Parse and validate a publisher's deployment payload. Pure: no I/O, no network, no database.

Everything decidable from the request bytes plus the config is decided HERE, before the control
handler opens a socket to GitHub or a transaction against the registry. That ordering is the
point: a manifest that is going to be refused should cost one parse, not two hundred blob
fetches.

Two rules are worth reading twice.

**The content type is derived, never accepted.** The confirmed spec's manifest contract is
exactly `{url_path, repo_path, blob_id, size, sha256}`. Taking a content type from the publisher
would widen the contract that #36 has to satisfy, and #36 is not written yet, so the widening
would surface there instead of here (design finding S7). The allowlist below is deliberately
short, and anything off it serves as `application/octet-stream` behind `nosniff`.

**`entry_path` must name a declared asset.** Design finding B7: without that check a manifest
passes every per-asset test and activates a deployment whose front page is a 404.
"""
from __future__ import annotations

import dataclasses
import re

from .config import HarnessConfig
from .routing import PathError, canonical_path

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPO = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")

_CONTENT_TYPES = {
    "html": "text/html; charset=utf-8",
    "css": "text/css; charset=utf-8",
    "js": "text/javascript; charset=utf-8",
    "svg": "image/svg+xml",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "woff2": "font/woff2",
    "json": "application/json",
    "txt": "text/plain; charset=utf-8",
}
_DEFAULT_CONTENT_TYPE = "application/octet-stream"


class ManifestError(Exception):
    """The payload is not a valid deployment. Always names the offending field or path."""


@dataclasses.dataclass(frozen=True)
class Asset:
    url_path: str
    repo_path: str
    blob_id: str
    size: int
    sha256: str
    content_type: str


@dataclasses.dataclass(frozen=True)
class Manifest:
    name: str
    repo: str
    commit_sha: str
    entry_path: str
    assets: tuple[Asset, ...]
    title: str | None
    project: str | None
    purpose: str | None
    published_at: str | None
    expected_active: int | None
    total_bytes: int


def content_type_for(url_path: str) -> str:
    _, _, ext = url_path.rpartition(".")
    if "/" in ext or not ext:
        return _DEFAULT_CONTENT_TYPE
    return _CONTENT_TYPES.get(ext.lower(), _DEFAULT_CONTENT_TYPE)


def _require(obj: dict, field: str):
    if field not in obj:
        raise ManifestError(f"{field} is required and is absent")
    return obj[field]


def _text(obj: dict, field: str) -> str:
    value = _require(obj, field)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{field} must be a non-empty string, got {value!r}")
    return value


def _optional_text(obj: dict, field: str) -> str | None:
    value = obj.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ManifestError(f"{field} must be a string or null, got {value!r}")
    return value


def _asset(raw, cfg: HarnessConfig, index: int) -> Asset:
    if not isinstance(raw, dict):
        raise ManifestError(f"assets[{index}] must be an object, got {type(raw).__name__}")
    url_path = _text(raw, "url_path")
    try:
        url_path = canonical_path(url_path)
    except PathError as exc:
        raise ManifestError(f"assets[{index}].url_path is not canonical: {exc}") from None
    if url_path == "/":
        raise ManifestError(f"assets[{index}].url_path must name a file, not '/'")

    repo_path = _text(raw, "repo_path")
    if repo_path.startswith("/") or ".." in repo_path.split("/"):
        raise ManifestError(f"assets[{index}].repo_path must be a relative path with no '..'")

    blob_id = _text(raw, "blob_id").lower()
    if not _HEX40.match(blob_id):
        raise ManifestError(f"assets[{index}].blob_id must be 40 hex characters, got {blob_id!r}")
    sha256 = _text(raw, "sha256").lower()
    if not _HEX64.match(sha256):
        raise ManifestError(f"assets[{index}].sha256 must be 64 hex characters")

    size = _require(raw, "size")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ManifestError(f"assets[{index}].size must be a non-negative integer, got {size!r}")
    if size > cfg.max_blob_bytes:
        raise ManifestError(
            f"assets[{index}] declares {size} bytes, over DOC_HARNESS_MAX_BLOB_BYTES "
            f"({cfg.max_blob_bytes})")

    # content_type is DERIVED. Anything the publisher sent under that key is ignored on purpose.
    return Asset(url_path=url_path, repo_path=repo_path, blob_id=blob_id, size=size,
                 sha256=sha256, content_type=content_type_for(url_path))


def parse_manifest(body, cfg: HarnessConfig) -> Manifest:
    """Validate a decoded JSON body into a `Manifest`, or raise `ManifestError`."""
    if not isinstance(body, dict):
        raise ManifestError(f"the request body must be a JSON object, got {type(body).__name__}")

    name = _text(body, "name")
    repo = _text(body, "repo")
    if not _REPO.match(repo):
        raise ManifestError(f"repo must be 'owner/name', got {repo!r}")
    commit_sha = _text(body, "commit_sha").lower()
    if not _HEX40.match(commit_sha):
        raise ManifestError("commit_sha must be a full 40-hex commit id, not a ref")

    raw_assets = _require(body, "assets")
    if not isinstance(raw_assets, list) or not raw_assets:
        raise ManifestError("assets must be a non-empty list")
    if len(raw_assets) > cfg.max_assets:
        raise ManifestError(
            f"{len(raw_assets)} assets declared, over DOC_HARNESS_MAX_ASSETS ({cfg.max_assets})")

    assets = tuple(_asset(raw, cfg, i) for i, raw in enumerate(raw_assets))
    seen: set[str] = set()
    for a in assets:
        if a.url_path in seen:
            raise ManifestError(f"duplicate url_path {a.url_path!r}")
        seen.add(a.url_path)

    total = sum(a.size for a in assets)
    if total > cfg.max_publish_bytes:
        raise ManifestError(
            f"the manifest declares {total} bytes in total, over DOC_HARNESS_MAX_PUBLISH_BYTES "
            f"({cfg.max_publish_bytes})")

    entry_path = _text(body, "entry_path")
    try:
        entry_path = canonical_path(entry_path)
    except PathError as exc:
        raise ManifestError(f"entry_path is not canonical: {exc}") from None
    if entry_path not in seen:
        raise ManifestError(
            f"entry_path {entry_path!r} names no declared asset, so '/' would 404 on a "
            f"deployment that otherwise activated cleanly")

    if "expected_active" not in body:
        raise ManifestError(
            "expected_active is required. Send null for a first publish — omitting the field is "
            "not the same as declaring there is no active deployment, and the difference is the "
            "whole point of the compare-and-swap.")
    expected_active = body["expected_active"]
    if expected_active is not None:
        if isinstance(expected_active, bool) or not isinstance(expected_active, int):
            raise ManifestError(
                f"expected_active must be an integer deployment id or null, got "
                f"{expected_active!r}")

    return Manifest(name=name, repo=repo, commit_sha=commit_sha, entry_path=entry_path,
                    assets=assets, title=_optional_text(body, "title"),
                    project=_optional_text(body, "project"),
                    purpose=_optional_text(body, "purpose"),
                    published_at=_optional_text(body, "published_at"),
                    expected_active=expected_active, total_bytes=total)
