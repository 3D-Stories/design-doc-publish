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
        self._inflight: dict[str, threading.Event] = {}
        self._results: dict[str, bytes] = {}
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
            self._remove(os.path.join(self.tmp_dir, name))
        # Finding C1: staged bytes are outside LRU accounting, so an abandoned publish is
        # invisible to the bound and accumulates until the volume fills.
        for name in os.listdir(self.staging_root):
            self._remove(os.path.join(self.staging_root, name))

        on_disk: dict[str, int] = {}
        for shard in os.listdir(self.blob_dir):
            shard_path = os.path.join(self.blob_dir, shard)
            if not os.path.isdir(shard_path):
                self._remove(shard_path)
                continue
            for name in os.listdir(shard_path):
                on_disk[name] = os.path.getsize(os.path.join(shard_path, name))

        known = {r["blob_id"]: int(r["size"]) for r in conn.execute("SELECT blob_id,size FROM blob")}
        for blob_id in set(known) - set(on_disk):
            conn.execute("DELETE FROM blob WHERE blob_id=?", (blob_id,))
        for blob_id in set(on_disk) - set(known):
            self._remove(self.path_for(blob_id))
        for blob_id, size in on_disk.items():
            if blob_id in known and known[blob_id] != size:
                conn.execute("UPDATE blob SET size=? WHERE blob_id=?", (size, blob_id))
        self._evict_to_bound()

    @staticmethod
    def _remove(path: str) -> None:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

    def _next_tick(self) -> int:
        with self._lock:
            self._tick += 1
            return self._tick

    # ---- accounting ------------------------------------------------------------------

    def total_bytes(self) -> int:
        row = self._conn().execute("SELECT COALESCE(SUM(size),0) AS s FROM blob").fetchone()
        return int(row["s"])

    def _evict_to_bound(self) -> None:
        conn = self._conn()
        total = self.total_bytes()
        if total <= self.max_bytes:
            return
        for row in conn.execute("SELECT blob_id,size FROM blob ORDER BY last_access ASC"):
            if total <= self.max_bytes:
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
            self._write_bytes(self.path_for(blob_id), data)
            self._conn().execute(
                "INSERT OR REPLACE INTO blob(blob_id,sha256,size,last_access) VALUES(?,?,?,?)",
                (blob_id, sha256, len(data), self._next_tick()))
            self._evict_to_bound()

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
        """Read a hit, or fetch exactly once across concurrent callers, then store and return."""
        fh = self.open(blob_id, sha256, size)
        if fh is not None:
            with fh:
                return fh.read()
        with self._lock:
            event = self._inflight.get(blob_id)
            leader = event is None
            if leader:
                event = threading.Event()
                self._inflight[blob_id] = event
        if not leader:
            event.wait()
            cached = self._results.get(blob_id)
            if cached is not None:
                return cached
            fh = self.open(blob_id, sha256, size)
            if fh is not None:
                with fh:
                    return fh.read()
            # Step 8a inline review, finding I2. `event.set()` happens before the leader pops
            # the shared result, so a waiter can wake and find nothing — and for a blob too
            # large to be cached at all, `open()` is ALWAYS a miss, so this path was reached
            # every time and raised. Raising turned a page that had just been fetched
            # successfully into a 502. Fetching again is the right trade: one duplicate
            # request in a narrow race, instead of a wrong answer.
            data, actual_sha = fetch()
            self.put(blob_id, data, actual_sha)
            return data
        try:
            data, actual_sha = fetch()
            self.put(blob_id, data, actual_sha)
            self._results[blob_id] = data
            return data
        finally:
            with self._lock:
                self._inflight.pop(blob_id, None)
            event.set()
            self._results.pop(blob_id, None)

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
