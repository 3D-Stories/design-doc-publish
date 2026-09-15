"""The document-date cache, on disk, so a restart does not re-ask GitHub for all of them.

`ConventionIndex` already memoizes `(repo, path, blob_id) -> (added, updated)` in memory, keyed
on the BLOB rather than the path, so a refresh only pays for files whose content changed. That
memo dies with the process. Measured 2026-09-15 against the real account: a cold walk with an
empty memo spends 618 date calls, 41.36s of a 52.66s total. With those dates already on disk a
restart pays only the repository walk — 11.30s.

**Where it lives is the contract.** `compose.yaml` mounts `blobcache:/var/cache/doc-harness` and
calls it "disposable: rebuilds from GitHub by design". Losing this file must therefore cost one
slow boot and nothing else. The durable `registry` volume is for data that cannot be recomputed;
a date cache is not that.

**Nothing here may ever raise at a caller.** Every operation catches `sqlite3.Error` AND
`OSError`, logs once, and goes inert. Both families are required, and that was probed inside the
serving container rather than assumed: an unwritable path raises `sqlite3.OperationalError`,
which is **not** an `OSError`, while `os.makedirs` on an unwritable parent raises
`PermissionError`, which is. Catching one family would turn an unwritable volume into a failed
boot, which is exactly the outcome #65 forbids.

Connection discipline is `BlobCache._conn`'s, deliberately: one connection per thread, WAL,
a bounded busy timeout. The index walks with a pool of eight.
"""
from __future__ import annotations

import os
import sqlite3
import threading

_SCHEMA = """
CREATE TABLE IF NOT EXISTS file_date (
  repo    TEXT NOT NULL,
  path    TEXT NOT NULL,
  blob_id TEXT NOT NULL,
  added   TEXT NOT NULL,
  updated TEXT NOT NULL,
  PRIMARY KEY (repo, path, blob_id)
) WITHOUT ROWID;
"""

# Every access is a lookup on the whole composite primary key, and nothing wants an integer row
# id, so the table IS the index rather than carrying a second one beside it.


class DateStore:
    """`(repo, path, blob_id) -> (added, updated)`, persisted on the disposable cache volume.

    `available` is the whole state machine. It starts False, `initialize()` may set it True, and
    any failure afterwards sets it back to False for good. An unavailable store answers every
    read with a miss and drops every write, which is precisely the behavior the service had
    before this module existed.
    """

    def __init__(self, path: str, *, log=None):
        self.path = path
        self.available = False
        self._log = log
        self._local = threading.local()
        self._lock = threading.Lock()
        self._reported = False

    # ---- lifecycle -------------------------------------------------------------------

    def initialize(self) -> None:
        """Open the file and create the table. Never raises."""
        try:
            parent = os.path.dirname(self.path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            self._conn().executescript(_SCHEMA)
        except (sqlite3.Error, OSError) as exc:
            self._degrade("initialize", exc)
            return
        self.available = True

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass
            self._local.conn = None

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, isolation_level=None, timeout=5.0)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return conn

    def _degrade(self, operation: str, exc: BaseException) -> None:
        """Go inert, and say so EXACTLY once.

        Once per process, not once per row: the walk touches 618 documents, so a full disk
        would otherwise write 618 identical lines into the container log and bury whatever
        else was happening.
        """
        self.available = False
        with self._lock:
            if self._reported:
                return
            self._reported = True
        if self._log is None:
            return
        try:
            self._log(
                f"index date store unavailable after {operation} on {self.path}: {exc!r}. "
                f"Falling back to in-memory dates; the listing is unaffected and a restart "
                f"will re-ask GitHub for them.")
        except Exception:                              # noqa: BLE001 - see below
            # The whole contract of this class is that it never raises at a caller. A logging
            # callback that throws while REPORTING a storage failure would break exactly that,
            # and during `initialize` it would abort the boot — the one outcome #65 forbids.
            # There is nowhere left to report this, so it is dropped rather than re-raised.
            pass

    # ---- reads and writes ------------------------------------------------------------

    def get(self, key) -> tuple | None:
        if not self.available:
            return None
        repo, path, blob_id = key
        try:
            row = self._conn().execute(
                "SELECT added, updated FROM file_date "
                "WHERE repo=? AND path=? AND blob_id=?", (repo, path, blob_id)).fetchone()
        except (sqlite3.Error, OSError) as exc:
            self._degrade("get", exc)
            return None
        return None if row is None else (row[0], row[1])

    def put(self, key, value) -> None:
        """Best effort. A value that cannot be stored is simply re-fetched next restart."""
        if not self.available:
            return
        repo, path, blob_id = key
        added, updated = value
        try:
            self._conn().execute(
                "INSERT OR REPLACE INTO file_date(repo, path, blob_id, added, updated) "
                "VALUES(?,?,?,?,?)", (repo, path, blob_id, added, updated))
        except (sqlite3.Error, OSError) as exc:
            self._degrade("put", exc)

    def prune(self, live_keys, walked_repos) -> None:
        """Drop rows for documents that no longer exist, in the repositories actually walked.

        Every edit to a document leaves its predecessor's row behind for ever, because the key
        carries the blob id. Sweeping is therefore necessary, and scoping it to `walked_repos`
        is what makes it safe: a repository the credential could not read this time tells us
        nothing about which of its rows are live, so deleting them on that non-evidence would
        throw away a working cache because of one API hiccup.
        """
        if not self.available:
            return
        walked = sorted(set(walked_repos))
        if not walked:
            return
        try:
            conn = self._conn()
            conn.execute("CREATE TEMP TABLE IF NOT EXISTS live"
                         "(repo TEXT, path TEXT, blob_id TEXT)")
            conn.execute("CREATE TEMP TABLE IF NOT EXISTS walked(repo TEXT)")
            conn.execute("DELETE FROM live")
            conn.execute("DELETE FROM walked")
            conn.executemany("INSERT INTO live VALUES(?,?,?)",
                             [tuple(k) for k in live_keys])
            conn.executemany("INSERT INTO walked VALUES(?)", [(r,) for r in walked])
            # A temp table rather than a 1,800-parameter `NOT IN`: 618 documents is already
            # past the comfortable size for an inline list, and it grows with the site.
            conn.execute(
                "DELETE FROM file_date "
                "WHERE repo IN (SELECT repo FROM walked) "
                "  AND NOT EXISTS (SELECT 1 FROM live l "
                "                  WHERE l.repo = file_date.repo "
                "                    AND l.path = file_date.path "
                "                    AND l.blob_id = file_date.blob_id)")
        except (sqlite3.Error, OSError) as exc:
            self._degrade("prune", exc)
