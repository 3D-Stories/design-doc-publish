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
