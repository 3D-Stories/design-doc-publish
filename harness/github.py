"""The credentialed GitHub client, the tree walk, and the budget that bounds a publish.

**The budget is the point of this module, not a detail.** Design finding B3 showed that
per-call limits do not bound an operation: 200 assets at a 20-second per-call timeout is roughly
4,000 seconds of one worker, with every individual limit honored. Finding C2 then showed that
checking a deadline only BEFORE each call still does not bound it, because one call started just
under the wire gets a whole fresh timeout, and a response that trickles bytes holds the worker
for as long as it keeps trickling. So `Budget` does three things: it caps total calls, it derives
every socket timeout from the REMAINING deadline, and it is re-checked on every streamed chunk.

**The tree walk is non-recursive on purpose.** `?recursive=1` truncates past GitHub's response
limit and returns a partial tree, which a naive reader treats as "path absent". Measured on
2026-08-24 the two real doc repos do not truncate, so that is a latent failure rather than a
present one — but the stronger reason is that walking components yields each entry's `mode`,
which is how a symlink or a submodule gets refused by name instead of being followed.

**The token never reaches an exception.** Every error raised here is constructed from the status
and the repository, never from the request or its headers.
"""
from __future__ import annotations

import dataclasses
import json
import time
import urllib.error
import urllib.request
from typing import Callable, Iterable, Protocol

_CHUNK = 65536


class GitHubError(Exception):
    """Any refusal from this module. Never carries credentials."""


class NotFound(GitHubError):
    """The object is genuinely absent — a dead SHA, or a path that is not in the tree."""


class Unavailable(GitHubError):
    """An outage, a timeout, or a response this client will not guess at."""


class Unauthorized(GitHubError):
    """The credential was refused, or the rate limit is exhausted."""


class DeadlineExceeded(GitHubError):
    """The end-to-end publish deadline passed."""


class BudgetExhausted(GitHubError):
    """The publish made more GitHub calls than it is allowed."""


class Budget:
    """The end-to-end bound on ONE publish: wall-clock and call count together."""

    def __init__(self, deadline_seconds: float, max_calls: int,
                 clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._deadline = clock() + deadline_seconds
        self._max_calls = max_calls
        self.calls_spent = 0

    def remaining(self) -> float:
        return self._deadline - self._clock()

    def check(self) -> None:
        if self.remaining() <= 0:
            raise DeadlineExceeded(
                "the publish exceeded its end-to-end deadline and was abandoned; nothing was "
                "activated")

    def spend_call(self) -> None:
        self.check()
        if self.calls_spent >= self._max_calls:
            raise BudgetExhausted(
                f"the publish reached its cap of {self._max_calls} GitHub calls and was "
                f"abandoned; nothing was activated")
        self.calls_spent += 1

    def socket_timeout(self, http_timeout: float) -> float:
        """Never let one call outlive the whole publish (finding C2)."""
        self.check()
        return max(0.001, min(http_timeout, self.remaining()))


@dataclasses.dataclass(frozen=True)
class TreeEntry:
    path: str
    type: str
    mode: str
    blob_id: str
    size: int | None


class GitHubSource(Protocol):
    """The seam every caller depends on. Two methods, so both halves are fakeable."""

    def tree(self, repo: str, sha: str, budget: Budget) -> tuple[list[TreeEntry], bool]:
        """Entries of ONE tree object, plus whether GitHub truncated the response."""

    def blob(self, repo: str, blob_id: str, budget: Budget,
             http_timeout: float = 20.0) -> bytes:
        """Raw bytes of one blob."""


def _entries(raw: Iterable[dict]) -> list[TreeEntry]:
    out = []
    for e in raw:
        out.append(TreeEntry(path=e.get("path", ""), type=e.get("type", ""),
                             mode=str(e.get("mode", "")), blob_id=e.get("sha", ""),
                             size=e.get("size")))
    return out


class HttpGitHub:
    """The real client. `opener` is injected so every error path is testable without a socket."""

    def __init__(self, token: str, api: str = "https://api.github.com", *, opener=None):
        self._token = token
        self._api = api.rstrip("/")
        self._opener = opener or urllib.request.urlopen

    def _request(self, url: str, accept: str, budget: Budget, http_timeout: float):
        budget.spend_call()
        req = urllib.request.Request(url, headers={
            "Accept": accept,
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "doc-harness",
        })
        try:
            return self._opener(req, timeout=budget.socket_timeout(http_timeout))
        except urllib.error.HTTPError as exc:
            raise self._classify(exc) from None
        except urllib.error.URLError as exc:
            raise Unavailable(f"could not reach GitHub: {exc.reason!r}") from None
        except TimeoutError:
            raise Unavailable("the GitHub request timed out") from None

    @staticmethod
    def _classify(exc: urllib.error.HTTPError) -> GitHubError:
        # Constructed from the status only. The request and its headers, which carry the
        # credential, are never interpolated into any message.
        status = exc.code
        if status == 404:
            return NotFound("GitHub reports this object does not exist")
        if status == 401:
            return Unauthorized("GitHub refused the credential (401)")
        if status == 403:
            headers = exc.headers or {}
            try:
                remaining = headers.get("x-ratelimit-remaining")
            except AttributeError:
                remaining = None
            if str(remaining) == "0":
                return Unauthorized("GitHub rate limit is exhausted (403)")
            return Unauthorized("GitHub refused the request (403)")
        return Unavailable(f"GitHub returned {status}")

    def tree(self, repo: str, sha: str, budget: Budget,
             http_timeout: float = 20.0) -> tuple[list[TreeEntry], bool]:
        url = f"{self._api}/repos/{repo}/git/trees/{sha}"
        with self._request(url, "application/vnd.github+json", budget, http_timeout) as resp:
            payload = json.loads(self._read(resp, budget).decode("utf-8"))
        return _entries(payload.get("tree") or []), bool(payload.get("truncated"))

    def blob(self, repo: str, blob_id: str, budget: Budget,
             http_timeout: float = 20.0) -> bytes:
        url = f"{self._api}/repos/{repo}/git/blobs/{blob_id}"
        with self._request(url, "application/vnd.github.raw", budget, http_timeout) as resp:
            return self._read(resp, budget)

    @staticmethod
    def _read(resp, budget: Budget) -> bytes:
        """Stream the body, re-checking the deadline on EVERY chunk (finding C2)."""
        out = bytearray()
        while True:
            budget.check()
            chunk = resp.read(_CHUNK)
            if not chunk:
                return bytes(out)
            out.extend(chunk)


class FakeGitHub:
    """An in-memory source for tests. Same Protocol, no sockets."""

    def __init__(self, trees: dict | None = None, blobs: dict | None = None,
                 truncated: set | None = None, errors: dict | None = None):
        self._trees = {k: _entries(v) for k, v in (trees or {}).items()}
        self._blobs = dict(blobs or {})
        self._truncated = set(truncated or ())
        self._errors = dict(errors or {})
        self.tree_calls = 0
        self.blob_calls = 0

    def tree(self, repo, sha, budget, http_timeout: float = 20.0):
        budget.spend_call()
        self.tree_calls += 1
        if (repo, sha) in self._errors:
            raise self._errors[(repo, sha)]
        if (repo, sha) not in self._trees:
            raise NotFound(f"no tree {sha}")
        return self._trees[(repo, sha)], (repo, sha) in self._truncated

    def blob(self, repo, blob_id, budget, http_timeout: float = 20.0):
        budget.spend_call()
        self.blob_calls += 1
        if (repo, blob_id) in self._errors:
            raise self._errors[(repo, blob_id)]
        if (repo, blob_id) not in self._blobs:
            raise NotFound(f"no blob {blob_id}")
        return self._blobs[(repo, blob_id)]


def resolve_path(source: GitHubSource, repo: str, commit_sha: str, repo_path: str,
                 budget: Budget, *, memo: dict | None = None,
                 http_timeout: float = 20.0) -> TreeEntry:
    """Walk `repo_path` component by component from `commit_sha` and return its blob entry.

    `memo` is shared across the assets of one publish, so a manifest whose files live in one
    directory pays for that directory once.
    """
    memo = memo if memo is not None else {}
    sha = commit_sha
    walked: list[str] = []
    parts = [p for p in repo_path.split("/") if p]
    for index, part in enumerate(parts):
        key = (repo, sha)
        if key not in memo:
            entries, truncated = source.tree(repo, sha, budget, http_timeout)
            if truncated:
                raise Unavailable(
                    f"the tree at {'/'.join(walked) or '<root>'} came back truncated, so an "
                    f"absent entry cannot be told from an omitted one; refusing to guess")
            memo[key] = {e.path: e for e in entries}
        entry = memo[key].get(part)
        walked.append(part)
        if entry is None:
            raise NotFound(f"{'/'.join(walked)} is not in the tree at commit {commit_sha}")
        last = index == len(parts) - 1
        if entry.mode == "120000":
            raise GitHubError(f"{'/'.join(walked)} is a symlink, which this service refuses to "
                              f"follow")
        if entry.mode == "160000" or entry.type == "commit":
            raise GitHubError(f"{'/'.join(walked)} is a submodule, which this service refuses to "
                              f"follow")
        if last:
            if entry.type != "blob":
                raise GitHubError(f"{'/'.join(walked)} is a directory, not a file")
            return entry
        if entry.type != "tree":
            raise NotFound(f"{'/'.join(walked)} is not a directory, so {repo_path} cannot exist")
        sha = entry.blob_id
    raise NotFound(f"{repo_path!r} names nothing")
