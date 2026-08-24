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
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Iterable, Protocol

_CHUNK = 65536

# A tree listing is JSON metadata, never file content. GitHub truncates its own tree
# responses well below this, so a body past it means something is wrong upstream.
MAX_TREE_BYTES = 16 * 1024 * 1024


class GitHubError(Exception):
    """Any refusal from this module. Never carries credentials."""


class NotFound(GitHubError):
    """The object is genuinely absent — a dead SHA, or a path that is not in the tree."""


class Unavailable(GitHubError):
    """An outage, a timeout, or a response this client will not guess at."""


class Unauthorized(GitHubError):
    """The credential was refused, or the rate limit is exhausted."""


class ResponseTooLarge(GitHubError):
    """The upstream response passed its byte bound and was cut off mid-stream."""


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


_SHA = re.compile(r"^[0-9a-f]{40}$")


def url_for_commit(api: str, repo: str, ref: str) -> str:
    return f"{api}/repos/{repo}/commits/{ref}"


@dataclasses.dataclass(frozen=True)
class TreeEntry:
    path: str
    type: str
    mode: str
    blob_id: str
    size: int | None


def _commit_date(entry) -> str | None:
    """The committer date of one commit object, or `None`. Author date is the fallback."""
    if not isinstance(entry, dict):
        return None
    commit = entry.get("commit")
    if not isinstance(commit, dict):
        return None
    for who in ("committer", "author"):
        block = commit.get(who)
        if isinstance(block, dict) and isinstance(block.get("date"), str) and block["date"]:
            return block["date"]
    return None


def _validated_tree(payload) -> tuple[list[TreeEntry], bool]:
    """A tree response, or `Unavailable`. Absence upstream is never a publisher's fault.

    Step 11 finding F5: `payload.get("tree") or []` turned a response with no `tree` key into a
    perfectly valid EMPTY tree, and `bool(payload.get("truncated"))` turned a missing truncation
    flag into a confident "not truncated". The caller then reported the publisher's path as
    absent — a 422 blaming the publisher for an upstream response this client could not read.
    """
    if not isinstance(payload, dict):
        raise Unavailable(
            f"GitHub returned a tree body that is not an object, got {type(payload).__name__}")
    raw = payload.get("tree")
    if not isinstance(raw, list):
        raise Unavailable("GitHub returned a tree body with no list-valued 'tree'; an absent "
                          "tree is not an empty one, and refusing beats reporting the "
                          "publisher's path as missing")
    truncated = payload.get("truncated")
    if not isinstance(truncated, bool):
        raise Unavailable("GitHub returned a tree body whose 'truncated' flag is absent or not a "
                          "boolean; without it a partial tree cannot be told from a whole one")
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise Unavailable(f"tree entry {index} is not an object")
        for field in ("path", "type", "sha"):
            value = entry.get(field)
            if not isinstance(value, str) or not value:
                raise Unavailable(
                    f"tree entry {index} carries no usable {field!r}; the entry cannot be "
                    f"matched against a declared asset")
        if entry.get("mode") is None:
            raise Unavailable(
                f"tree entry {index} carries no 'mode'; a symlink or a submodule is refused BY "
                f"its mode, so an absent mode would silently disable that refusal")
    return _entries(raw), truncated


class GitHubSource(Protocol):
    """The seam every caller depends on. Two methods, so both halves are fakeable."""

    def tree(self, repo: str, sha: str, budget: Budget, http_timeout: float = 20.0,
             max_bytes: int | None = None, recursive: bool = False
             ) -> tuple[list[TreeEntry], bool]:
        """Entries of one tree, plus whether GitHub truncated the response.

        `recursive` returns the whole tree, which is what a search by document NAME needs.
        """

    def commit(self, repo: str, ref: str, budget: Budget, http_timeout: float = 20.0) -> str:
        """The commit sha `ref` points at, validated as a sha."""

    def repos(self, owner: str, budget: Budget, http_timeout: float = 20.0) -> list[str]:
        """Every repository name under `owner` this credential can see."""

    def file_dates(self, repo: str, path: str, budget: Budget,
                   http_timeout: float = 20.0) -> tuple[str | None, str | None]:
        """`(added, updated)` for `path`, or `(None, None)`."""

    def last_commit_date(self, repo: str, path: str, budget: Budget,
                         http_timeout: float = 20.0) -> str | None:
        """When `path` was last changed, as GitHub reports it, or `None`."""

    def blob(self, repo: str, blob_id: str, budget: Budget, http_timeout: float = 20.0,
             max_bytes: int | None = None) -> bytes:
        """Raw bytes of one blob, refused once it exceeds `max_bytes`."""


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

    def tree(self, repo: str, sha: str, budget: Budget, http_timeout: float = 20.0,
             max_bytes: int | None = None, recursive: bool = False
             ) -> tuple[list[TreeEntry], bool]:
        url = f"{self._api}/repos/{repo}/git/trees/{sha}"
        if recursive:
            url += "?recursive=1"
        cap = MAX_TREE_BYTES if max_bytes is None else max_bytes
        with self._request(url, "application/vnd.github+json", budget, http_timeout) as resp:
            raw = self._read(resp, budget, cap)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Unavailable(f"GitHub returned a tree body this client cannot parse: {exc}") \
                from None
        return _validated_tree(payload)

    def commit(self, repo: str, ref: str, budget: Budget,
               http_timeout: float = 20.0) -> str:
        """The commit sha `ref` points at.

        Asks for the `sha` media type, so the answer is the bare sha and no JSON body has to be
        parsed or trusted. The result is interpolated into later URLs, so it is validated as a
        sha here rather than anywhere downstream: an error page reaching a URL as a ref is how a
        broken response becomes a request nobody intended.
        """
        with self._request(url_for_commit(self._api, repo, ref),
                           "application/vnd.github.sha", budget, http_timeout) as resp:
            raw = self._read(resp, budget, 128)
        text = raw.decode("ascii", "replace").strip()
        if not _SHA.match(text):
            raise Unavailable(
                "GitHub returned a commit body that is not a sha, so it cannot be used as a ref")
        return text

    def repos(self, owner: str, budget: Budget, http_timeout: float = 20.0,
              page_cap: int = 10) -> list[str]:
        """Every repository name under `owner` this credential can see.

        Convention resolution cannot split a hostname without this: two of the three parts may
        contain hyphens, so `herdr-dashboard-107` is grammatical as two different repositories.
        Paged, and BOUNDED by `page_cap` — an unbounded follow would let a hostile or looping
        listing spend the whole request budget.
        """
        names, page = [], 1
        while page <= page_cap:
            url = (f"{self._api}/orgs/{owner}/repos"
                   f"?per_page=100&page={page}&type=all")
            with self._request(url, "application/vnd.github+json", budget,
                               http_timeout) as resp:
                raw = self._read(resp, budget, MAX_TREE_BYTES)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise Unavailable(
                    f"GitHub returned a repository listing this client cannot parse: {exc}"
                ) from None
            if not isinstance(payload, list):
                raise Unavailable(
                    "GitHub returned a repository listing that is not a list; an unreadable "
                    "listing is not an empty one, and an empty one would make every hostname "
                    "unresolvable while looking like a clean answer")
            batch = [r.get("name") for r in payload if isinstance(r, dict)]
            names.extend(n for n in batch if isinstance(n, str) and n)
            if len(payload) < 100:
                return names
            page += 1
        return names

    def last_commit_date(self, repo: str, path: str, budget: Budget,
                         http_timeout: float = 20.0) -> str | None:
        """When `path` was last changed, as GitHub reports it, or `None`.

        The index sorts on this. A filename date is NOT the same thing — a document named
        2026-07-04 that was edited yesterday was updated yesterday — and 130 of the 460 listed
        documents carry no date in their name at all.

        `per_page=1` because only the newest commit matters, and the path is percent-encoded
        rather than interpolated raw: a space or an ampersand in a path would otherwise change
        the query it lands in.
        """
        url = (f"{self._api}/repos/{repo}/commits"
               f"?path={urllib.parse.quote(path)}&per_page=1")
        with self._request(url, "application/vnd.github+json", budget, http_timeout) as resp:
            raw = self._read(resp, budget, MAX_TREE_BYTES)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Unavailable(f"GitHub returned a commit listing this client cannot parse: {exc}") \
                from None
        if not isinstance(payload, list):
            # An unreadable listing is not an empty one. Reporting "no commits" from an error
            # body would date the document as unknown and sink it to the bottom of the index.
            raise Unavailable("GitHub returned a commit listing that is not a list")
        if not payload or not isinstance(payload[0], dict):
            return None
        commit = payload[0].get("commit")
        if not isinstance(commit, dict):
            return None
        for who in ("committer", "author"):
            block = commit.get(who)
            if isinstance(block, dict) and isinstance(block.get("date"), str) and block["date"]:
                return block["date"]
        return None

    def file_dates(self, repo: str, path: str, budget: Budget,
                   http_timeout: float = 20.0) -> tuple[str | None, str | None]:
        """`(added, updated)` for `path`, from ONE listing, or `(None, None)`.

        The URL uses ADDED so a shared link never moves; the index orders by UPDATED so the
        newest work is on top. Owner decision 2026-08-24, taken over dating a URL by its last
        change, which would have moved every URL each time somebody edited its file.

        `per_page=100` because GitHub returns newest first, so one page gives both ends. A file
        with more than 100 commits would page, and its `added` is then the oldest on this page
        rather than the true first — a document with 100 revisions does not exist here, and an
        approximate date is better than a second call for every file on the site.
        """
        url = (f"{self._api}/repos/{repo}/commits"
               f"?path={urllib.parse.quote(path)}&per_page=100")
        with self._request(url, "application/vnd.github+json", budget, http_timeout) as resp:
            raw = self._read(resp, budget, MAX_TREE_BYTES)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Unavailable(f"GitHub returned a commit listing this client cannot parse: {exc}") \
                from None
        if not isinstance(payload, list):
            raise Unavailable("GitHub returned a commit listing that is not a list")
        dates = [d for d in (_commit_date(c) for c in payload) if d]
        if not dates:
            return (None, None)
        return (dates[-1], dates[0])

    def blob(self, repo: str, blob_id: str, budget: Budget, http_timeout: float = 20.0,
             max_bytes: int | None = None) -> bytes:
        url = f"{self._api}/repos/{repo}/git/blobs/{blob_id}"
        with self._request(url, "application/vnd.github.raw", budget, http_timeout) as resp:
            return self._read(resp, budget, max_bytes)

    @staticmethod
    def _read(resp, budget: Budget, max_bytes: int | None) -> bytes:
        """Stream the body, bounded in BOTH time and bytes.

        The deadline (finding C2) bounds how long this can take. It does not bound how much
        memory it can take, and Step 8a finding R3 showed why that matters: an unbounded
        accumulate consumes a hostile or malformed response in full BEFORE any caller can
        check its length, which walks straight past the operator's configured blob cap.
        """
        out = bytearray()
        while True:
            budget.check()
            try:
                chunk = resp.read(_CHUNK)
            except TimeoutError:
                # Step 11 finding F7. A connection that dies mid-body raises HERE, not at
                # `urlopen`, and the taxonomy is what the caller's failure split reads. An
                # untyped escape became a 500 where the promise was a 503 plus an alert.
                raise Unavailable("the GitHub response timed out while streaming") from None
            except OSError as exc:
                raise Unavailable(f"the GitHub response failed while streaming: {exc}") from None
            if not chunk:
                return bytes(out)
            if max_bytes is not None and len(out) + len(chunk) > max_bytes:
                raise ResponseTooLarge(
                    f"the upstream response exceeded {max_bytes} bytes and was abandoned "
                    f"mid-stream")
            out.extend(chunk)


class FakeGitHub:
    """An in-memory source for tests. Same Protocol, no sockets."""

    def __init__(self, trees: dict | None = None, blobs: dict | None = None,
                 truncated: set | None = None, errors: dict | None = None,
                 commits: dict | None = None, repos=None, dates: dict | None = None):
        self._trees = {k: _entries(v) for k, v in (trees or {}).items()}
        self._blobs = dict(blobs or {})
        self._truncated = set(truncated or ())
        self._errors = dict(errors or {})
        self._commits = dict(commits or {})
        self.tree_calls = 0
        self.blob_calls = 0
        self.commit_calls = 0
        self._repos = list(repos or [])
        self.repos_calls = 0
        self._dates = dict(dates or {})
        self.date_calls = 0

    def tree(self, repo, sha, budget, http_timeout: float = 20.0, max_bytes=None,
             recursive: bool = False):
        budget.spend_call()
        self.tree_calls += 1
        if (repo, sha) in self._errors:
            raise self._errors[(repo, sha)]
        if (repo, sha) not in self._trees:
            raise NotFound(f"no tree {sha}")
        return self._trees[(repo, sha)], (repo, sha) in self._truncated

    def file_dates(self, repo, path, budget, http_timeout: float = 20.0):
        budget.spend_call()
        self.date_calls += 1
        value = self._dates.get((repo, path))
        if value is None:
            return (None, None)
        return value if isinstance(value, tuple) else (value, value)

    def last_commit_date(self, repo, path, budget, http_timeout: float = 20.0):
        budget.spend_call()
        self.date_calls += 1
        value = self._dates.get((repo, path))
        return value[1] if isinstance(value, tuple) else value

    def repos(self, owner, budget, http_timeout: float = 20.0, page_cap: int = 10):
        budget.spend_call()
        self.repos_calls += 1
        return list(self._repos)

    def commit(self, repo, ref, budget, http_timeout: float = 20.0):
        budget.spend_call()
        self.commit_calls += 1
        if (repo, ref) in self._errors:
            raise self._errors[(repo, ref)]
        if (repo, ref) not in self._commits:
            raise NotFound(f"no ref {ref}")
        return self._commits[(repo, ref)]

    def blob(self, repo, blob_id, budget, http_timeout: float = 20.0, max_bytes=None):
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
