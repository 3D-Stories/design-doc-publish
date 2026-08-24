"""The content-addressed blob cache: bytes on the disposable volume, LRU index beside them.

**The index lives on the cache volume, not in the registry.** Losing the volume must lose the
index and the bytes together; putting them on different volumes is how they drift apart.

**Every crash window is named and has a defined recovery** (design finding A3 — co-location
makes whole-volume loss consistent, but it does not make a filesystem write and a SQLite write
atomic). Insert order is rename-then-row, evict order is row-then-unlink, so a crash between the
two always leaves an orphan FILE and never a row pointing at nothing. `reconcile` deletes orphan
files, rows with no file, leftovers under `tmp/`, and abandoned staging directories, then
recomputes the total. **A missing file is always a recoverable MISS**, which is the invariant
that makes every window above harmless.

**Eviction never races a reader.** A reader `open()`s the file and holds the descriptor for the
whole response; eviction only unlinks. On POSIX the directory entry goes and the inode survives
while any descriptor is open, so the reader streams to completion from a file with no name.
Probed on 2026-08-24 inside a container on a real Docker named volume, not assumed.

**Staging is outside LRU accounting** (finding B5). A publish's verified bytes sit under
`staging/<publish id>/` until its compare-and-swap commits. Admitting earlier would let a LOSING
publisher evict the active deployment's warm blobs on its way to a 409.

**A hit must match the requesting asset, not merely the key** (finding B6). The key is a Git
SHA-1; the caller declares its own `sha256` and `size`. A disagreement purges and misses.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import threading
import time

_SCHEMA = """
CREATE TABLE IF NOT EXISTS blob (
  blob_id     TEXT PRIMARY KEY,
  sha256      TEXT NOT NULL,
  size        INTEGER NOT NULL,
  last_access INTEGER NOT NULL
);
"""


class _Flight:
    """One in-flight fetch, and the single place its outcome is published.

    Waiters hold a reference to this object, so the leader cannot remove the result out from
    under them. `data` and `error` are written exactly once, before `event` is set.
    """

    __slots__ = ("event", "data", "error")

    def __init__(self):
        self.event = threading.Event()
        self.data = None
        self.error = None


class CacheError(Exception):
    """The cache refused an operation."""


class CacheConflict(CacheError):
    """Bytes did not hash to what the caller declared."""


class BlobCache:
    def __init__(self, root: str, max_bytes: int, *, now=time.time):
        self.root = root
        self.max_bytes = max_bytes
        self._now = now
        self._local = threading.local()
        self._lock = threading.RLock()
        # LRU order is a strictly increasing TICK, not a wall-clock stamp. Millisecond
        # timestamps collide when several accesses land in the same millisecond, and then
        # `ORDER BY last_access` returns an arbitrary order — which showed up immediately as
        # an eviction test that removed the wrong entry. A counter cannot tie.
        self._tick = 0
        self._inflight: dict[str, "_Flight"] = {}
        #: Blobs that verified but could not be stored. Serving continues from the in-hand
        #: bytes; this list is what makes that visible rather than silent.
        self._admission_failures: list[str] = []
        self.blob_dir = os.path.join(root, "blobs")
        self.tmp_dir = os.path.join(root, "tmp")
        self.staging_root = os.path.join(root, "staging")
        self._db = os.path.join(root, "cache-index.db")

    # ---- lifecycle -------------------------------------------------------------------

    def initialize(self) -> None:
        for d in (self.blob_dir, self.tmp_dir, self.staging_root):
            os.makedirs(d, exist_ok=True)
        self._conn().executescript(_SCHEMA)
        row = self._conn().execute("SELECT COALESCE(MAX(last_access),0) AS t FROM blob").fetchone()
        self._tick = int(row["t"])
        self.reconcile()

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db, isolation_level=None, timeout=5.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return conn

    # ---- paths -----------------------------------------------------------------------

    def path_for(self, blob_id: str) -> str:
        return os.path.join(self.blob_dir, blob_id[:2], blob_id)

    def staging_dir(self, publish_id: str, *, create: bool = True) -> str:
        d = os.path.join(self.staging_root, publish_id)
        if create:
            os.makedirs(d, exist_ok=True)
        return d

    # ---- reconciliation --------------------------------------------------------------

    def reconcile(self) -> None:
        """Repair every crash window, then evict down to the bound. Runs before serving."""
        conn = self._conn()
        for name in os.listdir(self.tmp_dir):
            self._remove_strict(os.path.join(self.tmp_dir, name))
        # Finding C1: staged bytes are outside LRU accounting, so an abandoned publish is
        # invisible to the bound and accumulates until the volume fills.
        for name in os.listdir(self.staging_root):
            self._remove_strict(os.path.join(self.staging_root, name))

        on_disk: dict[str, int] = {}
        for shard in os.listdir(self.blob_dir):
            shard_path = os.path.join(self.blob_dir, shard)
            if not os.path.isdir(shard_path):
                self._remove_strict(shard_path)
                continue
            for name in os.listdir(shard_path):
                on_disk[name] = os.path.getsize(os.path.join(shard_path, name))

        known = {r["blob_id"]: int(r["size"]) for r in conn.execute("SELECT blob_id,size FROM blob")}
        for blob_id in set(known) - set(on_disk):
            conn.execute("DELETE FROM blob WHERE blob_id=?", (blob_id,))
        for blob_id in set(on_disk) - set(known):
            self._remove_strict(self.path_for(blob_id))
        for blob_id, size in on_disk.items():
            if blob_id in known and known[blob_id] != size:
                conn.execute("UPDATE blob SET size=? WHERE blob_id=?", (size, blob_id))
        self._evict_to_bound()

    @staticmethod
    def _remove(path: str) -> None:
        """Best-effort removal, for eviction, purging and discarding a publish's staging.

        Every caller of this one is on a path where a leftover file is harmless: reconcile
        deletes it at the next start, and the accounting is rebuilt from disk there.
        """
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

    @staticmethod
    def _remove_strict(path: str) -> None:
        """Removal that REFUSES to be ignored, for reconciliation only.

        Step 11 finding F6: reconcile used the best-effort remover, so a removal it could not
        perform passed silently. Reconciliation is the one place where that is not harmless —
        its whole job is to make the accounting match the volume, and a file it failed to
        delete is a byte the bound will never see again. A start-up that cannot reconcile
        refuses instead of serving with accounting it knows is wrong.
        """
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.unlink(path)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise CacheError(
                f"could not remove {path} while reconciling the cache volume: {exc}. Refusing "
                f"to serve: the LRU bound cannot be enforced over bytes this process failed to "
                f"account for.") from None

    def _next_tick(self) -> int:
        with self._lock:
            self._tick += 1
            return self._tick

    # ---- accounting ------------------------------------------------------------------

    def total_bytes(self) -> int:
        row = self._conn().execute("SELECT COALESCE(SUM(size),0) AS s FROM blob").fetchone()
        return int(row["s"])

    def _evict_for(self, incoming: int) -> None:
        """Make room for `incoming` bytes BEFORE they are written (Step 11 finding F2)."""
        self._evict_to_bound(headroom=incoming)

    def _evict_to_bound(self, *, headroom: int = 0) -> None:
        conn = self._conn()
        budget = self.max_bytes - headroom
        total = self.total_bytes()
        if total <= budget:
            return
        # The rows are materialized by the sort before any DELETE runs, so mutating the table
        # while iterating is safe here. Fetching the list explicitly says so rather than
        # relying on it: an index on `last_access` would turn this into a live index scan.
        for row in conn.execute(
                "SELECT blob_id,size FROM blob ORDER BY last_access ASC").fetchall():
            if total <= budget:
                break
            # Row first, then the file. A crash between them leaves an orphan file, which
            # reconcile deletes — never a row pointing at nothing.
            conn.execute("DELETE FROM blob WHERE blob_id=?", (row["blob_id"],))
            self._remove(self.path_for(row["blob_id"]))
            total -= int(row["size"])

    # ---- write -----------------------------------------------------------------------

    def _write_bytes(self, target: str, data: bytes) -> None:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        tmp = os.path.join(self.tmp_dir, f"{os.path.basename(target)}.{os.getpid()}."
                                         f"{threading.get_ident()}")
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, target)

    def put(self, blob_id: str, data: bytes, sha256: str) -> None:
        """Verify, then store. A blob larger than the whole bound is dropped, never cached."""
        actual = hashlib.sha256(data).hexdigest()
        if actual != sha256:
            raise CacheConflict(
                f"blob {blob_id} hashed to {actual[:12]}… but {sha256[:12]}… was declared; "
                f"refusing to cache or serve it")
        if len(data) > self.max_bytes:
            # Evicting the entire cache to store something that still will not fit is worse
            # than serving this one straight through.
            return
        with self._lock:
            # Step 11 finding F2: this used to write first and evict afterwards, so the bytes on
            # the volume passed the configured bound for the length of the write. On a volume
            # that was already near full, the write itself then failed with ENOSPC while the
            # entries that would have made room were still sitting there, evictable.
            self._evict_for(len(data))
            self._write_bytes(self.path_for(blob_id), data)
            self._conn().execute(
                "INSERT OR REPLACE INTO blob(blob_id,sha256,size,last_access) VALUES(?,?,?,?)",
                (blob_id, sha256, len(data), self._next_tick()))

    # ---- read ------------------------------------------------------------------------

    def open(self, blob_id: str, sha256: str, size: int):
        """An open file object for a verified hit, or None for a miss.

        The caller holds the descriptor for the whole response — that IS the lease.
        """
        with self._lock:
            row = self._conn().execute(
                "SELECT sha256,size FROM blob WHERE blob_id=?", (blob_id,)).fetchone()
            if row is None:
                return None
            if row["sha256"] != sha256 or int(row["size"]) != size:
                # Finding B6: the key matched but the bytes are not this asset's bytes.
                self._purge(blob_id)
                return None
            try:
                fh = open(self.path_for(blob_id), "rb")
            except FileNotFoundError:
                # A missing file is a MISS, never an error. This is the invariant that makes
                # every crash window recoverable.
                self._purge(blob_id)
                return None
            self._conn().execute("UPDATE blob SET last_access=? WHERE blob_id=?",
                                 (self._next_tick(), blob_id))
            return fh

    def _purge(self, blob_id: str) -> None:
        self._conn().execute("DELETE FROM blob WHERE blob_id=?", (blob_id,))
        self._remove(self.path_for(blob_id))

    def get_or_fetch(self, blob_id: str, sha256: str, size: int, fetch) -> bytes:
        """Read a hit, or fetch EXACTLY ONCE across concurrent callers, then store and return.

        The outcome — bytes or exception — is carried on a `_Flight` object that every waiter
        already holds a reference to, so there is no window in which a waiter can wake and
        find the result gone.

        This replaces two earlier attempts, and the history is worth keeping because each one
        was wrong in an instructive way. The first published the result into a shared dict and
        popped it AFTER setting the event, so a waiter raced the pop (Step 8a inline finding
        I2). The second had the losing waiter fetch again, which fixed the raise but defeated
        the whole point of the coalescer — Step 8a finding R5 wanted exactly one upstream
        call, and that version made two. Handing every waiter a reference to the same outcome
        object satisfies both: nobody raises spuriously, and nobody fetches twice.

        An exception from `fetch` propagates to every waiter unchanged, so each one keeps its
        correctly typed failure instead of a shared generic one.
        """
        fh = self.open(blob_id, sha256, size)
        if fh is not None:
            with fh:
                return fh.read()
        with self._lock:
            # Step 11 finding F15: the check above is OUTSIDE the lock, so a leader could
            # complete its whole fetch — store the blob AND drop its in-flight entry — in the
            # window between that miss and this line. The next caller then found no flight,
            # elected ITSELF leader, and fetched a blob that was already on disk. The exact
            # single-upstream-call guarantee this method exists for was therefore only
            # probabilistic, which showed up as a test that failed roughly three runs in eight.
            #
            # Re-checking here closes it deterministically, because `put` and the in-flight pop
            # both happen under this same lock and in that order: any caller that gets the lock
            # after the pop necessarily sees the stored row. The lock is an RLock, so `open`
            # taking it again on this thread is fine.
            fh = self.open(blob_id, sha256, size)
            if fh is not None:
                with fh:
                    return fh.read()
            flight = self._inflight.get(blob_id)
            leader = flight is None
            if leader:
                flight = _Flight()
                self._inflight[blob_id] = flight
        if not leader:
            flight.event.wait()
            if flight.error is not None:
                raise flight.error
            if flight.data is not None:
                return flight.data
            # The leader finished but left neither outcome, which should be unreachable.
            # Retry as a fresh caller rather than inventing an answer.
            return self.get_or_fetch(blob_id, sha256, size, fetch)
        try:
            data, declared_sha = fetch()
            try:
                self.put(blob_id, data, declared_sha)
            except OSError as exc:
                # Step 11 finding F2. The bytes are already verified — `put` hashes before it
                # writes anything — so a full or read-only volume is a warming problem, not a
                # serving one. Propagating it turned a recoverable cold cache into a 500 for a
                # page whose content was in hand. A CacheConflict is NOT caught here: that one
                # means the bytes are wrong, and wrong bytes must never be served.
                self._admission_failures.append(f"{blob_id}: {exc}")
            flight.data = data
        except BaseException as exc:
            flight.error = exc
            raise
        finally:
            with self._lock:
                self._inflight.pop(blob_id, None)
            flight.event.set()
        return data

    # ---- staging ---------------------------------------------------------------------

    def stage(self, publish_id: str, blob_id: str, data: bytes, sha256: str) -> str:
        """Write verified bytes OUTSIDE the LRU, for a publish that has not committed yet."""
        actual = hashlib.sha256(data).hexdigest()
        if actual != sha256:
            raise CacheConflict(f"staged blob {blob_id} does not match its declared sha256")
        target = os.path.join(self.staging_dir(publish_id), blob_id)
        with open(target + ".part", "wb") as fh:
            fh.write(data)
        os.replace(target + ".part", target)
        return target

    def discard_staging(self, publish_id: str) -> None:
        self._remove(self.staging_dir(publish_id, create=False))

    def commit_staging(self, publish_id: str, entries) -> None:
        """Admit a committed publish's staged blobs to the cache, then drop the directory."""
        d = self.staging_dir(publish_id, create=False)
        with self._lock:
            for blob_id, sha256, size in entries:
                src = os.path.join(d, blob_id)
                if not os.path.exists(src):
                    continue
                target = self.path_for(blob_id)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.replace(src, target)
                self._conn().execute(
                    "INSERT OR REPLACE INTO blob(blob_id,sha256,size,last_access) "
                    "VALUES(?,?,?,?)", (blob_id, sha256, size, self._next_tick()))
            self._evict_to_bound()
        self.discard_staging(publish_id)
