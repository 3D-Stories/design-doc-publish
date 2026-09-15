"""Resolve a hostname to a GitHub document by CONVENTION, with no registry row.

Owner decision D38. A document is reachable the moment its html file exists in a repository:
`2026-08-19-rawgentic-unified-roadmap` means the repository `rawgentic`, dated `2026-08-19`,
document `unified-roadmap`. Nothing publishes it, nothing registers it, and nothing has to be
run first. That is the whole point of the harness, and the registry path could not provide it.

The date is part of the NAME and never a lookup key that is recomputed per request. A hostname
whose date came from a file's last-modified time would otherwise move every time the file was
edited, and a link shared yesterday would stop working today.
"""
from __future__ import annotations

import concurrent.futures
import dataclasses
import datetime
import hashlib
import math
import re
import threading
import time

from .github import (BudgetExhausted, DeadlineExceeded, GitHubError, RateLimited,
                     Unavailable)
from .manifest import Asset, content_type_for
from .registry import ActiveDeployment

# A date-SHAPED prefix is only treated as a date when it is a real one. `9999-99-99-x` is a
# document called `9999-99-99-x`, not a document dated in the year 9999.
_DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)$")


def split_label(label: object, repos) -> tuple[str | None, str, str] | None:
    """`(date | None, repository, document)` for `label`, or `None` when it names nothing.

    `repos` is what makes the split decidable. Two of the three parts may contain hyphens, so
    `herdr-dashboard-107-usage` is grammatical both as the repository `herdr-dashboard` and as
    the repository `herdr`. Without the real list there is no way to choose, and guessing would
    let any hostname trigger a GitHub request for a repository name an outsider picked.
    """
    if not isinstance(label, str) or not label:
        return None
    date, remainder = None, label
    match = _DATE_PREFIX.match(label)
    if match:
        try:
            datetime.date.fromisoformat(match.group(1))
        except ValueError:
            pass                       # shaped like a date, is not one: it stays part of the name
        else:
            date, remainder = match.group(1), match.group(2)
    # The LONGEST matching repository wins. A shorter one that also prefixes the remainder is a
    # real reading, and taking it would serve one repository's document under another's name.
    best = None
    for repo in repos:
        if remainder.startswith(repo + "-") and (best is None or len(repo) > len(best)):
            best = repo
    if best is None:
        return None
    document = remainder[len(best) + 1:]
    return (date, best, document) if document else None


class DocumentAmbiguous(Exception):
    """Two files in one repository answer to the same hostname."""


# Git records a symlink as mode 120000 and a submodule as 160000. Neither is a file this service
# may serve: their target is decided by the repository, so following one would let a document
# point at anything the harness can read.
_REGULAR_FILE_MODES = ("100644", "100755")


def find_document(entries, date: str | None, document: str):
    """The `TreeEntry` for `document`, or `None`. Raises `DocumentAmbiguous` on a tie.

    The DATED filename is tried first, because most documents carry their date in the name. The
    undated one is the fallback, for a file whose hostname date came from its last-modified time
    rather than from the filename.
    """
    wanted = ([] if date is None else ["%s-%s.html" % (date, document)]) + ["%s.html" % document]
    for basename in wanted:
        matches = [e for e in entries
                   if e.type == "blob" and e.mode in _REGULAR_FILE_MODES
                   and e.path.rsplit("/", 1)[-1] == basename]
        if len(matches) > 1:
            # Serving either one would be a coin toss the reader cannot see. Same rule the
            # backfill uses for an ambiguous mapping: refuse, and make a human choose.
            raise DocumentAmbiguous(
                "%d files in this repository are named %s: %s"
                % (len(matches), basename, ", ".join(sorted(m.path for m in matches))))
        if matches:
            return matches[0]
    return None


class TreeTruncated(Exception):
    """GitHub truncated the tree, so absence cannot be proven."""


class ConventionResolver:
    """Turns a hostname into a servable deployment, reading GitHub and nothing else.

    Three calls on a cold hostname and one cached list: the repository names, the ref pinned to
    a commit, that commit's whole tree, and the blob. The ref is pinned FIRST so the search and
    the fetch see one snapshot even if somebody pushes between them.
    """

    def __init__(self, owner: str, source, *, repos_ttl: float = 300.0, now=time.time):
        self._owner = owner
        self._source = source
        self._ttl = repos_ttl
        self._now = now
        self._repos: list[str] | None = None
        self._repos_at = 0.0

    def repositories(self, budget) -> list[str]:
        """The owner's repository names, cached for `repos_ttl` seconds.

        Cached because every single request needs it and it changes rarely. Not cached forever,
        because a repository created today must become reachable without a restart — which is
        the whole promise of resolving by convention.
        """
        if self._repos is None or (self._now() - self._repos_at) > self._ttl:
            self._repos = self._source.repos(self._owner, budget)
            self._repos_at = self._now()
        return self._repos

    def resolve(self, label: str, budget, *, http_timeout: float = 20.0,
                max_blob_bytes: int | None = None):
        """An `ActiveDeployment` for `label`, or `None` when nothing answers to that name."""
        split = split_label(label, self.repositories(budget))
        if split is None:
            # Checked BEFORE any repository call. A hostname is attacker-chosen, so resolving an
            # unknown one would let an outsider decide which repository this service requests.
            return None
        date, repo, document = split
        full_repo = "%s/%s" % (self._owner, repo)
        commit = self._source.commit(full_repo, "HEAD", budget, http_timeout)
        entries, truncated = self._source.tree(full_repo, commit, budget, http_timeout,
                                               recursive=True)
        if truncated:
            # A truncated tree cannot prove a document is absent. Answering 404 from one would
            # tell a reader their document does not exist when it does.
            raise TreeTruncated(
                "GitHub truncated the tree for %s, so this document cannot be located" % full_repo)
        found = find_document(entries, date, document)
        if found is None:
            return None
        data = self._source.blob(full_repo, found.blob_id, budget, http_timeout, max_blob_bytes)
        asset = Asset(url_path="/index.html", repo_path=found.path, blob_id=found.blob_id,
                      size=len(data), sha256=hashlib.sha256(data).hexdigest(),
                      content_type=content_type_for("/index.html"))
        # A convention-resolved document has NO deployment id, because nothing deployed it. Zero
        # is the reserved value the serving path compares against for the `__deployment` pin, and
        # a pinned request for a real id will simply not match it.
        return ActiveDeployment(
            deployment_id=0, name=label, repo=full_repo, commit_sha=commit,
            entry_path="/index.html", title=document, project=repo,
            purpose=None, published_at="", assets={"/index.html": asset})


_MAX_DNS_LABEL = 63


def label_for(repo: str, repo_path: str, *, fallback_date: str | None = None) -> str:
    """The hostname label a document is served at. The INVERSE of `split_label`.

    The index generates its links with this, so the two must agree: a link the index prints and
    `split_label` cannot read is a link that resolves to nothing. A round-trip test pins that.

    Owner rule: `{date}-{repo}-{html name}`, the date taken from the FILENAME when it carries
    one and omitted when it does not. An omitted date still resolves, because `find_document`
    tries the undated filename as its fallback.
    """
    stem = re.sub(r"\.html?$", "", str(repo_path).rsplit("/", 1)[-1], flags=re.IGNORECASE)
    match = _DATE_PREFIX.match(stem)
    if match:
        try:
            datetime.date.fromisoformat(match.group(1))
        except ValueError:
            match = None
    if match:
        parts = [match.group(1), repo, match.group(2)]
    else:
        # Owner request: every URL carries a date. With none in the filename, the date GitHub
        # reports for the file's LAST CHANGE is used instead. Only the day is taken, and only
        # when it parses — the value arrives from an API response, so a junk one must never
        # become part of a hostname.
        day = ""
        if isinstance(fallback_date, str) and len(fallback_date) >= 10:
            try:
                day = datetime.date.fromisoformat(fallback_date[:10]).isoformat()
            except ValueError:
                day = ""
        parts = ([day] if day else []) + [repo, stem]
    label = "-".join(p for p in parts if p).lower()
    # One DNS label is 63 characters. The TAIL is cut, never the date and never the repository,
    # and the cut must not leave a trailing hyphen, which is not a legal label.
    if len(label) > _MAX_DNS_LABEL:
        label = label[:_MAX_DNS_LABEL].rstrip("-")
    return label


#: The two `GitHubError` subclasses that are never ONE repository's problem: the build ran out
#: of wall-clock, or out of calls. Both were caught by the base-class handlers in the repository
#: walk AND in `_dates_for`, so an exhausted budget quietly became "unreadable" repositories and
#: blank dates, and the walk carried on publishing a degraded listing as though it had succeeded.
#:
#: `RateLimited` is here and its parent `Unauthorized` is NOT, and the split is the point.
#: GitHub answers 403 both for "this credential may not read this repository" and for "you have
#: made too many requests". The first is ONE repository's problem, and treating it as fatal
#: would let a single unreadable repository kill the whole index — exactly what
#: `test_a_repository_that_cannot_be_read_does_not_empty_the_index` forbids. The second is every
#: repository's, and treating it as local records sixty readable repositories as unreadable and
#: publishes that as a success. `HttpGitHub._classify` tells them apart by
#: `x-ratelimit-remaining`, so this module does not have to guess.
#:
#: A genuinely dead credential still needs no special case: every repository fails, the build
#: reads nothing, and guard 1 refuses to publish it.
_WALK_FATAL = (DeadlineExceeded, BudgetExhausted, RateLimited)


@dataclasses.dataclass(frozen=True)
class _RepoWalk:
    """One repository's phase-1 result. Immutable, so a worker cannot mutate shared state."""

    repo: str
    commit: str | None
    docs: tuple
    unreadable: bool


class IndexBuilding(GitHubError):
    """A cold build is already running; this caller is not the leader.

    A subclass of `GitHubError` on purpose: if the specific handler in `app.py` is ever
    removed, the fallback is the existing 503 rather than a 500.
    """


class IndexCoolingDown(GitHubError):
    """A build failed recently, so another has not been started yet."""

    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after


class IndexTooStale(GitHubError):
    """The snapshot is older than the operator allows a listing to be served."""


class ConventionIndex:
    """The index, built by WALKING the repositories rather than reading the registry.

    Convention-resolved documents have no registry rows, so the registry-derived index went
    blank when resolution replaced publishing. This produces the SAME snapshot shape the
    registry produced, so the renderer is unchanged.

    Only `docs/` is listed. A repository's application assets and test fixtures are not design
    documents; they stay servable by hostname and are simply not advertised.

    **Since #65 a reader never waits for a rebuild.** Measured at the origin: a first load after
    the 900-second cache expired took 93.697s, and the next took 0.071s — the same 301,664-byte
    page. Past the TTL the snapshot already in hand is returned immediately and a build runs on
    a daemon thread. Only the very first caller of a cold process blocks; a second one is
    refused with `IndexBuilding` rather than joining the wait, because enough blocked index
    readers would occupy every waitress worker and stop DOCUMENT requests being served. That is
    the same rule `publish_slots` encodes in `app.py`.

    **Freshness is measured on a MONOTONIC clock**, separately from `now`. A wall-clock
    correction must not un-expire a snapshot; `generated_at` keeps the wall clock because a
    human reads it.

    **`refresh_budget` is the opt-in seam.** A `Budget` carries a deadline set at construction
    and belongs to the operation that made it, so a background build needs its own. Without the
    callable this class behaves exactly as it did before #65: a stale read rebuilds inline.
    """

    DOC_PREFIX = "docs/"

    #: How long after a failed build before another may start. Fixed rather than exponential:
    #: the TTL is already 900s, so a schedule would need its own state and its own test to
    #: earn itself. Without any cool-off, a GitHub outage turns every cached read into a fresh
    #: 61-repository walk attempt — a request storm caused by the caching feature.
    REFRESH_COOLDOWN = 60.0

    def __init__(self, owner: str, source, *, ttl: float = 900.0, now=time.time,
                 monotonic=time.monotonic, refresh_budget=None, store=None,
                 workers: int = 8, max_stale_age: float = 0.0, log=None,
                 thread_factory=threading.Thread):
        self._owner = owner
        self._source = source
        self._ttl = ttl
        self._now = now
        self._monotonic = monotonic
        self._refresh_budget = refresh_budget
        self._store = store
        self._workers = max(1, int(workers))
        self._max_stale_age = float(max_stale_age or 0.0)
        self._log = log
        self._thread_factory = thread_factory
        self._snapshot = None
        self._at = 0.0
        self._lock = threading.RLock()
        self._building = False
        self._cooldown_until = 0.0
        # Dates are keyed on the BLOB, not the path. 618 documents is 618 extra calls on a cold
        # walk; keying on content means a refresh only pays for the files that actually changed.
        # Guarded by its OWN lock, which is never held across a GitHub or a SQLite call.
        self._dates: dict[tuple, tuple] = {}
        self._dates_lock = threading.Lock()
        # When each repository was last READ successfully, on the monotonic clock. Carry-forward
        # is bounded by this: without it, a repository whose access is revoked keeps its rows in
        # every later snapshot while the snapshot's own age keeps resetting, so `max_stale_age`
        # never fires for it and the disclosure bound this class advertises silently stops
        # existing for exactly the repository it most needed to cover.
        self._repo_verified: dict = {}

    def _dates_for(self, full_repo: str, entry, budget, http_timeout: float) -> tuple:
        """`(added, updated, failed)` for this file.

        ADDED dates the URL, so a link never moves when somebody edits the file. UPDATED orders
        the page, so the newest work is on top. Owner decision 2026-08-24.

        Lookup order is memory, store, GitHub. **No lock is held across the store or the
        network**, because holding one across a 1.4-second round trip would serialize the very
        pool it protects. Two workers can therefore both miss the same key — but within one
        build each `(repo, path, blob_id)` is visited exactly once by exactly one worker, and
        only one build runs at a time, so the duplicate is unreachable rather than tolerated.

        A failure is NEVER memoized and never persisted. Writing a blank would poison every
        future restart with a permanent wrong date for a document that has one. The caller
        decides what a failure means: one is a hiccup and the document is still listed, all of
        them is an outage and the build is abandoned.
        """
        key = (full_repo, entry.path, entry.blob_id)
        with self._dates_lock:
            hit = self._dates.get(key)
        if hit is not None:
            return (hit[0], hit[1], False)
        if self._store is not None:
            stored = self._store.get(key)
            if stored is not None:
                with self._dates_lock:
                    self._dates[key] = stored
                return (stored[0], stored[1], False)
        try:
            added, updated = self._source.file_dates(
                full_repo, entry.path, budget, http_timeout)
        except _WALK_FATAL:
            # These are NOT this document's problem — they are the whole build's. The
            # base-class handler below used to swallow them here, so an exhausted budget
            # became blank dates and the walk carried on publishing a degraded listing.
            raise
        except GitHubError:
            return ("", "", True)
        value = (added or "", updated or "")
        with self._dates_lock:
            self._dates[key] = value
        if self._store is not None:
            self._store.put(key, value)
        return (value[0], value[1], False)

    # ---- the two-phase walk ----------------------------------------------------------

    def _run_phase(self, items, work, stop):
        """Run `work` over `items` through one bounded pool, in submission order out.

        Results come back indexed, so completion order never reaches the caller. On the first
        walk-fatal error every pending future is cancelled and the error is re-raised: without
        that, an expired credential still fires the remaining sixty repositories at an API
        that is already refusing them.
        """
        if not items:
            return []
        done, fatal = {}, None
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=self._workers, thread_name_prefix="index-walk") as pool:
            futures = {pool.submit(work, item): i for i, item in enumerate(items)}
            for future in concurrent.futures.as_completed(futures):
                try:
                    done[futures[future]] = future.result()
                except _WALK_FATAL as exc:
                    if fatal is None:
                        fatal = exc
                        stop.set()
                        for pending in futures:
                            pending.cancel()
                except concurrent.futures.CancelledError:
                    continue
        if fatal is not None:
            raise fatal
        return [done[i] for i in range(len(items)) if i in done]

    def _walk_repo(self, repo: str, budget, http_timeout: float, stop):
        """Phase 1: one repository's commit and tree, reduced to its listable documents."""
        full = "%s/%s" % (self._owner, repo)
        if stop.is_set():
            return _RepoWalk(repo, None, (), True)
        try:
            commit = self._source.commit(full, "HEAD", budget, http_timeout)
            entries, truncated = self._source.tree(full, commit, budget, http_timeout,
                                                   recursive=True)
        except _WALK_FATAL:
            raise
        except GitHubError:
            # ONE unreadable repository must not turn the whole index into a confident blank
            # page. It is recorded and named, not swallowed.
            return _RepoWalk(repo, None, (), True)
        if truncated:
            return _RepoWalk(repo, None, (), True)
        found = [e for e in entries
                 if e.type == "blob" and e.mode in _REGULAR_FILE_MODES
                 and e.path.startswith(self.DOC_PREFIX)
                 and e.path.lower().endswith((".html", ".htm"))]
        # A basename appearing twice cannot be SERVED — `find_document` refuses it — so
        # advertising it would print a link that answers 409.
        seen = {}
        for entry in found:
            seen.setdefault(entry.path.rsplit("/", 1)[-1], []).append(entry)
        docs = tuple(group[0] for _, group in sorted(seen.items()) if len(group) == 1)
        return _RepoWalk(repo, commit, docs, False)

    def _date_job(self, job, budget, http_timeout: float, stop):
        """Phase 2: one document's dates. Flattened across repositories on purpose.

        One task per REPOSITORY looked obvious and was measured 3.2x slower — 170.87s against
        52.66s on the real account — because a repository's date calls then serialize inside
        its own task and the largest repository becomes the entire critical path.
        """
        repo, entry = job
        if stop.is_set():
            return (repo, entry, "", "", True)
        full = "%s/%s" % (self._owner, repo)
        added, updated, failed = self._dates_for(full, entry, budget, http_timeout)
        return (repo, entry, added, updated, failed)

    def _build(self, budget, http_timeout: float = 20.0) -> dict:
        with self._lock:
            previous = self._snapshot
        # Rows of the last good listing, by repository and by document, so a transient failure
        # cannot make a document vanish or silently change its hostname.
        prev_by_repo: dict = {}
        prev_by_doc: dict = {}
        if previous is not None:
            for row in previous["rows"]:
                prev_by_repo.setdefault(row["project"], []).append(row)
                prev_by_doc[(row["project"], row["title"])] = row

        # One stop flag per BUILD, passed down rather than stored on the object: two builds
        # cannot overlap today, and an attribute reassigned per build is a clobber waiting for
        # the day that stops being true.
        stop = threading.Event()
        repos = sorted(self._source.repos(self._owner, budget))
        walks = self._run_phase(
            repos, lambda repo: self._walk_repo(repo, budget, http_timeout, stop), stop)

        jobs = [(walk.repo, entry) for walk in walks for entry in walk.docs]
        dated = self._run_phase(
            jobs, lambda job: self._date_job(job, budget, http_timeout, stop), stop)
        by_entry = {(repo, entry.path): (added, updated, failed)
                    for repo, entry, added, updated, failed in dated}

        rows, projects, unreadable, carried, dropped = [], [], [], [], []
        now = self._monotonic()
        # Rows this build actually READ, as opposed to rows it carried forward. The difference
        # is what tells a real refresh from a refresh that read nothing at all.
        fresh_rows = 0
        # Failed date lookups with NO previous row to fall back on. These are the ones that
        # actually change a hostname, so they are what the systemic-outage guard counts.
        uncovered = 0
        attempts = len(dated)
        for walk in walks:
            if walk.unreadable:
                unreadable.append(walk.repo)
                # Carry the last good rows for this repository. Without this, one hiccup drops
                # every document it holds from the listing until the next successful build.
                #
                # BOUNDED by when it was last actually read. A repository whose access is
                # revoked would otherwise be carried forward for ever while each successful
                # build reset the snapshot's age, so `max_stale_age` would never fire for it.
                # The bound the operator set has to mean something per repository, not only
                # for the snapshot as a whole.
                kept = prev_by_repo.get(walk.repo, [])
                if kept and not self._carry_expired(walk.repo, now):
                    rows.extend(kept)
                    projects.append(walk.repo)
                    carried.append(walk.repo)
                elif kept:
                    dropped.append(walk.repo)
                continue
            listed = False
            for entry in walk.docs:
                basename = entry.path.rsplit("/", 1)[-1]
                title = re.sub(r"\.html?$", "", basename, flags=re.IGNORECASE)
                added, updated, failed = by_entry.get((walk.repo, entry.path), ("", "", True))
                previous_row = prev_by_doc.get((walk.repo, title))
                if failed and previous_row is None:
                    uncovered += 1
                if failed and previous_row is not None:
                    # A blank date CHANGES a dateless document's hostname, so one 500 from the
                    # commits API would break a link somebody already shared.
                    name = previous_row["name"]
                    published = previous_row["published_at"]
                else:
                    name = label_for(walk.repo, entry.path, fallback_date=added)
                    published = updated
                rows.append({
                    "name": name,
                    "title": title,
                    "project": walk.repo,
                    # The walk knows the repository, so the page does not have to guess it from
                    # a hostname that now begins with a date.
                    "group": walk.repo,
                    "purpose": None,
                    "commit_sha": walk.commit,
                    "published_at": published,
                })
                listed = True
                fresh_rows += 1
            if listed:
                projects.append(walk.repo)
            self._repo_verified[walk.repo] = now

        # Publication guard 1: a build that read NOTHING is a failed build, however many rows
        # it carried forward.
        #
        # Two things are wrong with letting it succeed, and the second is the dangerous one.
        # An empty listing produced by failure is indistinguishable from an empty listing
        # produced by an empty org, and only one of those is true. Worse: with carry-forward
        # in place, a build during a total outage would publish the previous rows and reset the
        # snapshot's age, so the listing would look permanently fresh, `max_stale_age` would
        # never fire, and the staleness bound would quietly stop existing. Found by
        # `test_a_failed_refresh_does_not_start_another_on_the_next_request`, which expected a
        # cool-off and got a successful build.
        if not fresh_rows and unreadable:
            raise Unavailable(
                "every repository failed while building the document listing, so the result "
                "would be a confident page that read nothing")
        # Publication guard 2: one failed date is a hiccup; all of them, with nothing to fall
        # back on, is an outage that blanks the date on every dateless document's hostname at
        # once — and a blank date CHANGES the hostname, so links people already shared break.
        #
        # It counts UNCOVERED failures, not failures. A warm build whose every lookup failed is
        # fine, because carry-forward gives each row the date it already had and the listing
        # comes out byte-identical. Only a build with no previous row for a failed document can
        # actually move a URL.
        if attempts and uncovered == attempts:
            raise Unavailable(
                "every document date lookup failed while building the listing and none could "
                "be carried forward, so every generated hostname would lose its date")

        if self._store is not None:
            # Scoped to the repositories actually READ, which is what the store's own contract
            # asks for. Requiring a wholly clean walk instead was wrong in practice: the live
            # cold-walk measurement saw three transient failures in one pass of 61
            # repositories, so pruning would almost never have run and the store would grow
            # for ever. A repository that could not be read is simply left alone — it says
            # nothing about which of its rows are dead.
            read = [walk for walk in walks if not walk.unreadable]
            if read:
                live = [(("%s/%s" % (self._owner, walk.repo)), entry.path, entry.blob_id)
                        for walk in read for entry in walk.docs]
                self._store.prune(live, {"%s/%s" % (self._owner, w.repo) for w in read})

        if carried:
            self._log_line("index build carried forward the previous rows for: "
                           + ", ".join(sorted(carried)))
        if dropped:
            # Loud, because a document disappearing from the listing is exactly the kind of
            # change nobody notices until somebody asks where their page went.
            self._log_line(
                "index build DROPPED repositories whose last successful read is older than "
                "the configured maximum listing age: " + ", ".join(sorted(dropped)))

        rows.sort(key=lambda r: r["name"])
        # The generation is derived from the ROWS, so the ETag changes exactly when the listing
        # does and a reader's cached copy is never stale in a way they cannot see.
        digest = hashlib.sha256(
            "\n".join("%s\t%s" % (r["name"], r["commit_sha"]) for r in rows).encode()
        ).hexdigest()[:16]
        # Returned, never installed here. `_run_build` owns installation, so a build that fails
        # partway cannot leave a half-written snapshot where a reader can see it.
        return {"generation": digest, "generated_at": self._now(),
                "rows": rows, "projects": sorted(set(projects), key=len, reverse=True),
                "unreadable": sorted(unreadable)}

    # ---- the reader's path -----------------------------------------------------------

    def snapshot(self, budget, *, http_timeout: float = 20.0) -> dict:
        """The listing. Never blocks once a snapshot exists.

        Five outcomes, and the branch each takes is decided under one lock so two readers
        cannot both elect themselves the builder.
        """
        with self._lock:
            snap, at = self._snapshot, self._at
            now = self._monotonic()
            if snap is not None and (now - at) <= self._ttl:
                return snap

            if snap is None:
                if self._building:
                    raise IndexBuilding(
                        "the document listing is still being built; retry shortly")
                cooling = self._cooling_for(now)
                if cooling > 0:
                    raise IndexCoolingDown(
                        "the document listing could not be built and is cooling down; "
                        "retry shortly", cooling)
                self._building = True
                lead = True
            else:
                # Stale. Without a refresh budget there is nowhere to run a background build,
                # so this caller rebuilds inline exactly as every pre-#65 caller did.
                lead = False
                if self._refresh_budget is None:
                    if not self._building:
                        self._building = True
                        lead = True
                elif not self._building and self._cooling_for(now) <= 0:
                    self._spawn(http_timeout)

        if lead:
            return self._run_build(budget, http_timeout)

        # Serve what is already in hand, subject to the operator's staleness bound.
        with self._lock:
            snap, at = self._snapshot, self._at
            if snap is None:
                # Only reachable if a concurrent build failed between the two locked sections.
                raise IndexBuilding(
                    "the document listing is still being built; retry shortly")
            if self._max_stale_age and (self._monotonic() - at) > self._max_stale_age:
                raise IndexTooStale(
                    "the document listing is older than this service is allowed to serve; "
                    "GitHub has not been reachable for a while")
            return snap

    def _cooling_for(self, now: float) -> int:
        """Whole seconds left on the failure cool-off, 0 when it is not running.

        Rounded UP, so a `Retry-After` never tells a reader to come back before the cool-off
        has actually expired.
        """
        left = self._cooldown_until - now
        return math.ceil(left) if left > 0 else 0

    def _spawn(self, http_timeout: float) -> None:
        """Start a background build. The caller holds `self._lock`.

        `start()` can raise `RuntimeError` when the process cannot make another thread. If
        `_building` were left set by that, the target never runs its `finally` and every later
        request suppresses the refresh until the process restarts — the exact invariant the
        `finally` protects. So the failure is handled here, not hoped away.
        """
        self._building = True
        try:
            thread = self._thread_factory(
                target=self._background, args=(http_timeout,),
                name="index-refresh", daemon=True)
            thread.start()
        except BaseException as exc:                   # noqa: BLE001 - a refusal to start
            self._building = False
            self._cooldown_until = self._monotonic() + self.REFRESH_COOLDOWN
            self._log_line(f"index refresh could not start a thread: {exc!r}; "
                           f"continuing to serve the previous listing")

    def _background(self, http_timeout: float) -> None:
        """Rebuild off the reader's thread. A failure here must never reach a reader.

        `_building` is cleared HERE as well as in `_run_build`, because the budget factory is
        evaluated before `_run_build` is entered: a factory that raises would otherwise never
        reach that `finally`, and the flag would stay set for the life of the process. Every
        later stale reader would then trigger no walk at all and the index would freeze on its
        last snapshot — the same freeze the `thread.start()` guard exists to prevent, one level
        further down. Clearing twice is harmless; clearing never is not.
        """
        try:
            budget = self._refresh_budget()
        except BaseException as exc:                   # noqa: BLE001 - never kill the thread
            with self._lock:
                self._building = False
                self._cooldown_until = self._monotonic() + self.REFRESH_COOLDOWN
            self._log_line(f"index refresh could not build a budget: {exc!r}; "
                           f"continuing to serve the previous listing")
            return
        try:
            self._run_build(budget, http_timeout)
        except BaseException as exc:                   # noqa: BLE001 - never kill the thread
            self._log_line(f"index refresh failed, keeping the previous listing: {exc!r}")

    def _run_build(self, budget, http_timeout: float):
        """Build, then install atomically. Clears `_building` on every path."""
        built = None
        try:
            built = self._build(budget, http_timeout)
        finally:
            with self._lock:
                self._building = False
                if built is None:
                    self._cooldown_until = self._monotonic() + self.REFRESH_COOLDOWN
        with self._lock:
            self._snapshot = built
            self._at = self._monotonic()
            self._cooldown_until = 0.0
        return built

    def _carry_expired(self, repo: str, now: float) -> bool:
        """Has this repository gone unread for longer than a listing may be stale?

        `max_stale_age` of 0 means the operator asked for no bound at all, so carry-forward is
        unbounded too — the two settings have to agree, or the knob would mean one thing for
        the snapshot and another for a repository inside it.
        """
        if not self._max_stale_age:
            return False
        seen = self._repo_verified.get(repo)
        if seen is None:
            # Never read successfully by THIS process. There is nothing to date the carry
            # against, so it is not carried.
            return True
        return (now - seen) > self._max_stale_age

    def _log_line(self, message: str) -> None:
        if self._log is not None:
            self._log(message)
