"""The WSGI application. A plain callable, PEP 3333, with no non-stdlib import anywhere.

That is the whole reason the core is shaped this way. Every test invokes this callable
directly — no socket, no thread, no waitress — so the dependency the container needs never
reaches the test gate.

This module only DISPATCHES. The security decisions live where they can be tested in
isolation: the zone allowlist in `routing`, the bearer in `control`, the failure split in
`serving`. Wiring is the one thing here, so wiring is the only thing that can go wrong here.
"""
from __future__ import annotations

import threading
import traceback

from .cache import BlobCache
from .config import HarnessConfig
from .control import handle_control
from .indexpage import render_index
from .registry import Registry
from .routing import CONTROL_LABEL, INDEX_LABEL, RouteError, resolve_host
from .serving import Response, serve
from .github import Budget


def _plain(status: int, message: str, extra: dict | None = None) -> Response:
    """A plain-text response whose Content-Length cannot drift from its body."""
    body = (message.rstrip("\n") + "\n").encode("utf-8")
    headers = {"Content-Type": "text/plain; charset=utf-8", "Content-Length": str(len(body))}
    headers.update(extra or {})
    return Response(status, headers, body)


def _not_found() -> Response:
    return _plain(404, "not found")


def make_app(*, cfg: HarnessConfig, registry: Registry, cache: BlobCache, source,
             log=None):
    """Build the WSGI callable over already-constructed collaborators."""
    publish_slots = threading.BoundedSemaphore(cfg.max_concurrent_publishes)

    def _log(message: str) -> None:
        if log is not None:
            log(message)

    def _dispatch(environ) -> Response:
        try:
            label = resolve_host(environ.get("HTTP_HOST"), cfg.zone)
        except RouteError:
            return _not_found()

        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = _decoded_path(environ)

        if label == CONTROL_LABEL:
            body = None
            raw_length = environ.get("CONTENT_LENGTH")
            if method == "POST":
                if raw_length in (None, ""):
                    # waitress answers a MALFORMED length with 400 before we are entered;
                    # an ABSENT one reaches here, so the 411 is ours. Measured, not assumed.
                    return _plain(411, "Content-Length is required on a publish")
                body = environ["wsgi.input"].read(int(raw_length))
                if not publish_slots.acquire(blocking=False):
                    # Finding B3: publishing must never be able to occupy every worker.
                    return _plain(429, "too many publishes in flight; retry shortly",
                                  {"Retry-After": "30"})
                try:
                    return handle_control(method, path, headers=_headers(environ), body=body,
                                          registry=registry, cache=cache, source=source, cfg=cfg)
                finally:
                    publish_slots.release()
            return handle_control(method, path, headers=_headers(environ), body=body,
                                  registry=registry, cache=cache, source=source, cfg=cfg)

        if label == INDEX_LABEL:
            return render_index(registry, zone=cfg.zone,
                                if_none_match=environ.get("HTTP_IF_NONE_MATCH"))

        # Control routes exist ONLY on the control host. Reaching them from a serving host
        # is a 404, not a 401, so their existence is not confirmed to a caller who cannot
        # use them.
        if path.startswith("/v1/"):
            return _not_found()

        active = registry.active(label)
        if active is None:
            return _not_found()
        return serve(active, path, method=method, headers=_headers(environ),
                     query=environ.get("QUERY_STRING", ""), cache=cache, source=source,
                     cfg=cfg, budget=Budget(cfg.http_timeout * 2, cfg.max_github_calls))

    def app(environ, start_response):
        try:
            response = _dispatch(environ)
        except Exception:
            # The body never carries the reason. A traceback in a response is an information
            # leak, and this page is served to whoever got past Access.
            _log("unhandled error:\n" + traceback.format_exc())
            body = b"internal error\n"
            start_response("500 Internal Server Error",
                           [("Content-Type", "text/plain; charset=utf-8"),
                            ("Content-Length", str(len(body)))])
            return [body]
        if response.alert:
            _log(response.alert)
        headers = dict(response.headers)
        headers.setdefault("Content-Length", str(len(response.body)))
        start_response(f"{response.status} {_reason(response.status)}",
                       list(headers.items()))
        return [response.body]

    return app


def _decoded_path(environ) -> str:
    """`PATH_INFO`, with the UTF-8 that WSGI flattened into latin-1 put back.

    PEP 3333 requires a server to hand the application a `str` whose code points are the raw
    request BYTES, so a UTF-8 asset name arrives as mojibake. Step 11 finding F3 is about this
    boundary: without the round trip below, a document called `café.html` publishes and then
    cannot be requested. A value that is not latin-1-encodable, or not UTF-8 once encoded, is
    returned untouched — it is already the best string available, and guessing further would
    invent a second spelling of one resource.
    """
    raw = environ.get("PATH_INFO", "/") or "/"
    try:
        return raw.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return raw


def _headers(environ) -> dict:
    out = {}
    for key, value in environ.items():
        if key.startswith("HTTP_"):
            out[key[5:].replace("_", "-").title()] = value
    return out


_REASONS = {200: "OK", 201: "Created", 304: "Not Modified", 400: "Bad Request",
            401: "Unauthorized", 404: "Not Found", 405: "Method Not Allowed",
            409: "Conflict", 411: "Length Required", 413: "Payload Too Large",
            422: "Unprocessable Entity", 429: "Too Many Requests",
            500: "Internal Server Error", 502: "Bad Gateway",
            503: "Service Unavailable", 504: "Gateway Timeout"}


def _reason(status: int) -> str:
    return _REASONS.get(status, "Status")
