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
from .github import Budget, GitHubError, NotFound, Unauthorized
from .convention import (ConventionIndex, ConventionResolver, DocumentAmbiguous,
                         TreeTruncated)


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
    # Owner decision D38: a document is reachable the moment its file exists in a repository.
    # The registry is still consulted FIRST, so a published deployment keeps winning and nothing
    # that works today changes.
    resolver = ConventionResolver(cfg.github_owner, source)
    # The index walks the repositories for the same reason: a convention-resolved document has
    # no registry row, so a registry-derived listing shows nothing that anybody can actually
    # reach. Cached hard, because one refresh costs two calls per repository.
    index = ConventionIndex(cfg.github_owner, source)

    def _log(message: str) -> None:
        if log is not None:
            log(message)


    def _index_budget() -> Budget:
        """The index walk is two calls per repository plus one per document whose blob it has
        not dated yet. On this account that is roughly 540 calls the first time and a few dozen
        afterwards, so it gets its own budget rather than a serving request's."""
        return Budget(cfg.http_timeout * 30, cfg.max_github_calls * 10)

    def _warm_index() -> None:
        """Build the listing once at boot, in the background.

        Without this the FIRST reader pays for the whole cold walk — measured at 60 seconds
        before dates and several minutes with them. A daemon thread means a slow start delays
        nobody: until it finishes, an index request simply builds it itself.
        """
        try:
            index.snapshot(_index_budget(), http_timeout=cfg.http_timeout)
            _log("index warmed")
        except Exception as exc:                      # noqa: BLE001 - a warm-up must never kill boot
            _log(f"index warm-up failed, will build on demand: {exc!r}")

    threading.Thread(target=_warm_index, name="index-warm", daemon=True).start()
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
            try:
                snapshot = index.snapshot(_index_budget(),
                                          http_timeout=cfg.http_timeout)
            except GitHubError:
                # The listing could not be built. A blank index would read as "no documents
                # exist", which is a lie, so this says the truth instead.
                return _plain(503, "the document listing could not be built from GitHub")
            return render_index(registry, zone=cfg.zone,
                                if_none_match=environ.get("HTTP_IF_NONE_MATCH"),
                                snapshot=snapshot)

        # Control routes exist ONLY on the control host. Reaching them from a serving host
        # is a 404, not a 401, so their existence is not confirmed to a caller who cannot
        # use them.
        if path.startswith("/v1/"):
            return _not_found()

        active = registry.active(label)
        if active is None:
            try:
                active = resolver.resolve(
                    label, Budget(cfg.http_timeout * 2, cfg.max_github_calls),
                    http_timeout=cfg.http_timeout, max_blob_bytes=cfg.max_blob_bytes)
            except DocumentAmbiguous as exc:
                # Two files answer to this hostname. Serving either would be a coin toss the
                # reader cannot see, and the message names both so a human can fix it.
                return _plain(409, str(exc))
            except TreeTruncated:
                # Absence could not be proven, so 404 would be a lie. 503 says try again.
                return _plain(503, "this repository is too large to search right now")
            except Unauthorized:
                # The harness credential cannot read that repository. Saying so is the whole
                # remedy: it is a grant problem and nothing the reader can fix by retrying.
                return _plain(502, "the harness cannot read that repository from GitHub")
            except NotFound:
                # The repository listing named it, and GitHub now says it is gone.
                return _not_found()
            except GitHubError:
                return _plain(502, "GitHub could not be reached to resolve this document")
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
