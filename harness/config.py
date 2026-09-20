"""Environment parsing, and the refusals that belong at start-up rather than at request time.

Everything the service can be tuned with lives in one frozen object built in one place, so a
setting cannot be read from `os.environ` halfway down a call stack and disagree with the value
the rest of the process is using.

The refusals here are deliberate. A missing GitHub token would not fail until the first cache
miss, and it would fail as a 503 that looks exactly like an upstream outage — so the operator
gets paged toward GitHub instead of toward their own compose file. Failing at start-up, naming
the variable, costs one line and removes that whole class of confusion.
"""
from __future__ import annotations

import dataclasses
from typing import Mapping


class ConfigError(Exception):
    """A setting is missing or unusable. Always names the variable it is about."""


_REQUIRED = ("DOC_HARNESS_GITHUB_TOKEN", "DOC_HARNESS_PUBLISH_TOKEN")


@dataclasses.dataclass(frozen=True)
class HarnessConfig:
    github_token: str = dataclasses.field(repr=False)
    publish_token: str = dataclasses.field(repr=False)
    zone: str
    registry_path: str
    cache_dir: str
    cache_max_bytes: int
    max_body_bytes: int
    max_blob_bytes: int
    max_assets: int
    max_publish_bytes: int
    http_timeout: float
    publish_deadline: float
    max_github_calls: int
    max_concurrent_publishes: int
    index_workers: int
    index_max_stale_age: int
    threads: int
    channel_timeout: int
    connection_limit: int
    bind: str
    github_api: str
    github_owner: str


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "")
    if not value.strip():
        raise ConfigError(
            f"{name} is required and is missing or blank. The service refuses to start without "
            f"it: booting anyway would turn a configuration mistake into a 503 that looks like "
            f"an upstream outage.")
    return value


def _number(env: Mapping[str, str], name: str, default, cast):
    raw = env.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = cast(str(raw).strip())
    except (TypeError, ValueError):
        raise ConfigError(f"{name} must be a number, got {raw!r}") from None
    if value <= 0:
        raise ConfigError(f"{name} must be greater than zero, got {value!r}")
    return value


#: The index snapshot's TTL, in `ConventionIndex`. Named here because a staleness bound at or
#: below it makes the stale window exactly zero, which would leave the index rebuilding on the
#: reader's request while LOOKING configured — the whole defect #65 exists to remove.
_INDEX_TTL_SECONDS = 900

#: GitHub's secondary rate limits punish burst concurrency, and 8 is a measured starting point
#: rather than an optimum, so the knob has a ceiling. One mistyped digit should not be able to
#: open a 500-way burst at the API.
_MAX_INDEX_WORKERS = 32


def _index_workers(env: Mapping[str, str]) -> int:
    """1..32, REJECTED rather than clamped outside it.

    A mistyped 64 that quietly became 32 is a setting the operator cannot see is wrong, and
    every other refusal in this file names its variable and stops.
    """
    value = _number(env, "DOC_HARNESS_INDEX_WORKERS", 8, int)
    if not 1 <= value <= _MAX_INDEX_WORKERS:
        raise ConfigError(
            f"DOC_HARNESS_INDEX_WORKERS must be between 1 and {_MAX_INDEX_WORKERS}, got "
            f"{value}. GitHub's secondary rate limits punish burst concurrency, so the pool "
            f"is bounded rather than trusted.")
    return value


def _index_max_stale_age(env: Mapping[str, str]) -> int:
    """How old a listing may be before it is refused. `0` means no bound.

    `_number` refuses anything `<= 0`, and `0` is a meaningful value here, so this parses its
    own. A POSITIVE value at or below the TTL is refused: the snapshot only becomes stale at
    the TTL, so such a bound leaves no window in which a stale listing is ever served, and
    stale-while-revalidate would silently do nothing.
    """
    raw = env.get("DOC_HARNESS_INDEX_MAX_STALE_AGE")
    if raw is None or not str(raw).strip():
        return 21600                      # six hours; see docs/planning/2026-09-15-65-*.md
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ConfigError(
            f"DOC_HARNESS_INDEX_MAX_STALE_AGE must be a whole number of seconds, got "
            f"{raw!r}") from None
    if value == 0:
        return 0
    if value < 0:
        raise ConfigError(
            f"DOC_HARNESS_INDEX_MAX_STALE_AGE must not be negative, got {value}. Use 0 to "
            f"serve a stale listing for as long as an outage lasts.")
    if value <= _INDEX_TTL_SECONDS:
        raise ConfigError(
            f"DOC_HARNESS_INDEX_MAX_STALE_AGE ({value}) must be greater than the index TTL of "
            f"{_INDEX_TTL_SECONDS} seconds. A listing only becomes stale at the TTL, so a "
            f"bound at or below it leaves no window in which a stale listing is served and "
            f"the index would go back to rebuilding on the reader's request.")
    return value


def _bind(env: Mapping[str, str]) -> str:
    """`host:port`, validated here so the refusal names its variable (Step 11 finding F12).

    `__main__` split this with `rpartition(":")` and called `int()` on the tail, OUTSIDE the
    try that turns a `ConfigError` into the "refusing to start" line. A bind with no port
    therefore exited with a raw traceback — the one setting in this file whose mistake was not
    reported the way every other one is.
    """
    raw = env.get("DOC_HARNESS_BIND", "0.0.0.0:8080").strip()
    host, sep, port = raw.rpartition(":")
    if not sep or not port:
        raise ConfigError(
            f"DOC_HARNESS_BIND must be 'host:port', got {raw!r}. Without a port there is "
            f"nothing to listen on.")
    try:
        number = int(port)
    except ValueError:
        raise ConfigError(f"DOC_HARNESS_BIND port must be a number, got {port!r}") from None
    if not 1 <= number <= 65535:
        raise ConfigError(f"DOC_HARNESS_BIND port {number} is outside 1-65535")
    return f"{host}:{number}" if host else f"0.0.0.0:{number}"


def load_config(env: Mapping[str, str]) -> HarnessConfig:
    """Build the config from an environment mapping, or raise `ConfigError` naming the variable."""
    zone = env.get("DOC_HARNESS_ZONE", "3dstories.ca").strip().strip(".").lower()
    if not zone:
        raise ConfigError("DOC_HARNESS_ZONE must not be empty")

    threads = _number(env, "DOC_HARNESS_THREADS", 8, int)
    max_concurrent_publishes = _number(env, "DOC_HARNESS_MAX_CONCURRENT_PUBLISHES", 2, int)
    # Finding B3: per-call bounds do not bound the operation. If publishes may occupy every
    # worker, a burst of them takes serving down while every individual limit is honored.
    if max_concurrent_publishes > threads - 2:
        raise ConfigError(
            f"DOC_HARNESS_MAX_CONCURRENT_PUBLISHES ({max_concurrent_publishes}) must be at least "
            f"2 below DOC_HARNESS_THREADS ({threads}), so publishing can never occupy every "
            f"worker and leave serving with none.")

    return HarnessConfig(
        github_token=_required(env, "DOC_HARNESS_GITHUB_TOKEN"),
        github_owner=env.get("DOC_HARNESS_GITHUB_OWNER", "3D-Stories").strip(),
        publish_token=_required(env, "DOC_HARNESS_PUBLISH_TOKEN"),
        zone=zone,
        registry_path=env.get("DOC_HARNESS_REGISTRY_PATH", "/var/lib/doc-harness/registry.db"),
        cache_dir=env.get("DOC_HARNESS_CACHE_DIR", "/var/cache/doc-harness"),
        cache_max_bytes=_number(env, "DOC_HARNESS_CACHE_MAX_BYTES", 2147483648, int),
        max_body_bytes=_number(env, "DOC_HARNESS_MAX_BODY_BYTES", 1048576, int),
        max_blob_bytes=_number(env, "DOC_HARNESS_MAX_BLOB_BYTES", 104857600, int),
        max_assets=_number(env, "DOC_HARNESS_MAX_ASSETS", 200, int),
        max_publish_bytes=_number(env, "DOC_HARNESS_MAX_PUBLISH_BYTES", 268435456, int),
        http_timeout=_number(env, "DOC_HARNESS_HTTP_TIMEOUT", 20.0, float),
        publish_deadline=_number(env, "DOC_HARNESS_PUBLISH_DEADLINE", 120.0, float),
        max_github_calls=_number(env, "DOC_HARNESS_MAX_GITHUB_CALLS", 300, int),
        max_concurrent_publishes=max_concurrent_publishes,
        index_workers=_index_workers(env),
        index_max_stale_age=_index_max_stale_age(env),
        threads=threads,
        channel_timeout=_number(env, "DOC_HARNESS_CHANNEL_TIMEOUT", 60, int),
        connection_limit=_number(env, "DOC_HARNESS_CONNECTION_LIMIT", 100, int),
        bind=_bind(env),
        github_api=env.get("DOC_HARNESS_GITHUB_API", "https://api.github.com").rstrip("/"),
    )
