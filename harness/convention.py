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

import datetime
import hashlib
import re
import time

from .github import GitHubError
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


class ConventionIndex:
    """The index, built by WALKING the repositories rather than reading the registry.

    Convention-resolved documents have no registry rows, so the registry-derived index went
    blank when resolution replaced publishing. This produces the SAME snapshot shape the
    registry produced, so the renderer is unchanged.

    Only `docs/` is listed. A repository's application assets and test fixtures are not design
    documents; they stay servable by hostname and are simply not advertised.
    """

    DOC_PREFIX = "docs/"

    def __init__(self, owner: str, source, *, ttl: float = 900.0, now=time.time):
        self._owner = owner
        self._source = source
        self._ttl = ttl
        self._now = now
        self._snapshot = None
        self._at = 0.0
        # Dates are keyed on the BLOB, not the path. 460 documents is 460 extra calls on a cold
        # walk; keying on content means a refresh only pays for the files that actually changed.
        self._dates: dict[tuple, str] = {}

    def _dates_for(self, full_repo: str, entry, budget, http_timeout: float) -> tuple:
        """`(added, updated)` for this file, each "" when GitHub would not say.

        ADDED dates the URL, so a link never moves when somebody edits the file. UPDATED orders
        the page, so the newest work is on top. Owner decision 2026-08-24.

        A file whose dates cannot be read is still LISTED. Dropping it would hide a real
        document because of one API hiccup, and the renderer already sinks a row with no time
        to the bottom of the page.
        """
        key = (full_repo, entry.path, entry.blob_id)
        if key not in self._dates:
            try:
                added, updated = self._source.file_dates(
                    full_repo, entry.path, budget, http_timeout)
            except GitHubError:
                return ("", "")
            self._dates[key] = (added or "", updated or "")
        return self._dates[key]

    def snapshot(self, budget, *, http_timeout: float = 20.0) -> dict:
        if self._snapshot is not None and (self._now() - self._at) <= self._ttl:
            return self._snapshot
        rows, projects, unreadable = [], [], []
        for repo in sorted(self._source.repos(self._owner, budget)):
            full = "%s/%s" % (self._owner, repo)
            try:
                commit = self._source.commit(full, "HEAD", budget, http_timeout)
                entries, truncated = self._source.tree(full, commit, budget, http_timeout,
                                                       recursive=True)
            except GitHubError:
                # ONE unreadable repository must not turn the whole index into a confident
                # blank page. It is recorded and named, not swallowed.
                unreadable.append(repo)
                continue
            if truncated:
                unreadable.append(repo)
                continue
            found = [e for e in entries
                     if e.type == "blob" and e.mode in _REGULAR_FILE_MODES
                     and e.path.startswith(self.DOC_PREFIX)
                     and e.path.lower().endswith((".html", ".htm"))]
            # A basename appearing twice cannot be SERVED — `find_document` refuses it — so
            # advertising it would print a link that answers 409.
            seen = {}
            for entry in found:
                seen.setdefault(entry.path.rsplit("/", 1)[-1], []).append(entry)
            listed = False
            for basename, group in sorted(seen.items()):
                if len(group) > 1:
                    continue
                entry = group[0]
                added, updated = self._dates_for(full, entry, budget, http_timeout)
                rows.append({
                    "name": label_for(repo, entry.path, fallback_date=added),
                    "title": re.sub(r"\.html?$", "", basename, flags=re.IGNORECASE),
                    "project": repo,
                    # The walk knows the repository, so the page does not have to guess it from
                    # a hostname that now begins with a date.
                    "group": repo,
                    "purpose": None,
                    "commit_sha": commit,
                    "published_at": updated,
                })
                listed = True
            if listed:
                projects.append(repo)
        rows.sort(key=lambda r: r["name"])
        # The generation is derived from the ROWS, so the ETag changes exactly when the listing
        # does and a reader's cached copy is never stale in a way they cannot see.
        digest = hashlib.sha256(
            "\n".join("%s\t%s" % (r["name"], r["commit_sha"]) for r in rows).encode()
        ).hexdigest()[:16]
        self._snapshot = {"generation": digest, "generated_at": self._now(),
                          "rows": rows, "projects": sorted(projects, key=len, reverse=True),
                          "unreadable": sorted(unreadable)}
        self._at = self._now()
        return self._snapshot
