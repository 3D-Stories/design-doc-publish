"""The container entry point. The ONLY module in this package that imports a server.

Everything else is stdlib, so `pytest scripts/tests/ tests/ -q` never installs or imports
waitress. Keeping the import inside `main()` rather than at module scope means even importing
this module does not require it, which is what `test_entrypoint.py` asserts.

Start-up refuses rather than degrades. A service that boots without a token, or without an
exclusive lock on its cache volume, is a service whose first symptom is a confusing 503.
"""
from __future__ import annotations

import fcntl
import os
import sys

from .app import make_app
from .cache import BlobCache
from .config import ConfigError, load_config
from .datestore import DateStore
from .github import HttpGitHub
from .registry import Registry


def take_cache_lock(cache_dir: str):
    """An exclusive lock on the cache volume, held for the process lifetime.

    The cache's in-process lock, its pin map and its single-flight table are correct only
    while ONE process owns the volume. That invariant is checked here rather than assumed:
    a second process fails loudly at start-up instead of corrupting the accounting quietly.
    Probed 2026-08-24 inside a container on a real Docker named volume.
    """
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, ".harness.lock")
    handle = open(path, "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError(
            f"another process already holds {path}. The harness supports exactly one process "
            f"per cache volume: its LRU accounting and single-flight map are process-local, so "
            f"two writers would silently disagree about what is cached.")
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def build(env=None):
    """Everything except the server, so a test can construct the real stack without one."""
    cfg = load_config(env if env is not None else os.environ)
    lock = take_cache_lock(cfg.cache_dir)
    registry = Registry(cfg.registry_path)
    registry.initialize()
    cache = BlobCache(cfg.cache_dir, max_bytes=cfg.cache_max_bytes)
    cache.initialize()
    log = lambda m: print(m, file=sys.stderr, flush=True)   # noqa: E731 - one expression
    # Beside the blob cache, on the volume compose.yaml calls "disposable: rebuilds from GitHub
    # by design" — never on the durable registry volume, which is for data that cannot be
    # recomputed. Losing this file costs one slow boot: measured 52.66s against 11.30s with it.
    #
    # `initialize()` NEVER raises. An unwritable cache volume is a warming problem, not a
    # serving one, and failing the boot over it is the outcome #65 forbids outright.
    dates = DateStore(os.path.join(cfg.cache_dir, "index-dates.db"), log=log)
    dates.initialize()
    source = HttpGitHub(cfg.github_token, cfg.github_api)
    app = make_app(cfg=cfg, registry=registry, cache=cache, source=source,
                   log=log, date_store=dates)
    return cfg, app, lock


def main(argv=None) -> int:
    try:
        cfg, app, _lock = build()
    except (ConfigError, RuntimeError) as exc:
        print(f"doc-harness: refusing to start: {exc}", file=sys.stderr)
        return 2

    import waitress  # noqa: PLC0415 - deliberately not a module-level import

    host, _, port = cfg.bind.rpartition(":")
    print(f"doc-harness: serving {cfg.zone} on {cfg.bind} with {cfg.threads} threads",
          file=sys.stderr, flush=True)
    waitress.serve(
        app,
        host=host or "0.0.0.0",
        port=int(port),
        threads=cfg.threads,
        # Every one of these is a stated decision, not an inherited default (finding S9).
        max_request_body_size=cfg.max_body_bytes,
        channel_timeout=cfg.channel_timeout,
        connection_limit=cfg.connection_limit,
        ident="doc-harness",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
