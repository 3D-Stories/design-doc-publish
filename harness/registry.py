"""The durable registry: what is published, what is active, and the swap between them.

Three things here are load-bearing and each exists because of a specific defect.

**One connection per thread.** Connections live in a `threading.local` and are never shared or
passed as arguments. Design finding A5: the earlier text fixed a thread count and said nothing
about connection ownership, and sharing a SQLite connection across threads interleaves
transactions in ways that make an application-level compare-and-swap meaningless.

**`BEGIN IMMEDIATE` on every write.** The write lock is taken at statement one, which is what
makes read-then-write atomic against a concurrent publisher rather than merely unlikely to
interleave. GitHub I/O never happens inside the transaction, so the lock is held for
milliseconds regardless of manifest size.

**The seal is enforced by the database, not remembered by the application.** Triggers refuse
mutation of a sealed deployment AND of its assets, including INSERT (finding B2 — a new
`url_path` changes what a sealed deployment serves) and including a reparent into a sealed row
(finding C7 — checking only the old parent leaves that door open).
"""
from __future__ import annotations

import dataclasses
import sqlite3
import threading
import time

from .manifest import Asset, Manifest

_SCHEMA = """
CREATE TABLE IF NOT EXISTS deployment (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL,
  repo          TEXT NOT NULL,
  commit_sha    TEXT NOT NULL,
  entry_path    TEXT NOT NULL,
  title         TEXT,
  project       TEXT,
  purpose       TEXT,
  published_at  TEXT NOT NULL,
  sealed        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS deployment_by_name ON deployment(name, id DESC);

CREATE TABLE IF NOT EXISTS asset (
  deployment_id INTEGER NOT NULL REFERENCES deployment(id),
  url_path      TEXT NOT NULL,
  repo_path     TEXT NOT NULL,
  blob_id       TEXT NOT NULL,
  size          INTEGER NOT NULL,
  sha256        TEXT NOT NULL,
  content_type  TEXT NOT NULL,
  PRIMARY KEY (deployment_id, url_path)
);

CREATE TABLE IF NOT EXISTS active (
  name          TEXT PRIMARY KEY,
  deployment_id INTEGER NOT NULL REFERENCES deployment(id)
);

CREATE TABLE IF NOT EXISTS registry_meta (k TEXT PRIMARY KEY, v INTEGER NOT NULL);
INSERT OR IGNORE INTO registry_meta(k, v) VALUES ('generation', 0), ('generated_at', 0);

CREATE TRIGGER IF NOT EXISTS deployment_sealed_no_update BEFORE UPDATE ON deployment
  WHEN OLD.sealed = 1 BEGIN SELECT RAISE(ABORT, 'deployment is sealed'); END;
CREATE TRIGGER IF NOT EXISTS deployment_sealed_no_delete BEFORE DELETE ON deployment
  WHEN OLD.sealed = 1 BEGIN SELECT RAISE(ABORT, 'deployment is sealed'); END;

CREATE TRIGGER IF NOT EXISTS asset_sealed_no_insert BEFORE INSERT ON asset
  WHEN (SELECT sealed FROM deployment WHERE id = NEW.deployment_id) = 1
  BEGIN SELECT RAISE(ABORT, 'deployment is sealed'); END;
CREATE TRIGGER IF NOT EXISTS asset_sealed_no_update BEFORE UPDATE ON asset
  WHEN (SELECT sealed FROM deployment WHERE id = OLD.deployment_id) = 1
    OR (SELECT sealed FROM deployment WHERE id = NEW.deployment_id) = 1
    OR NEW.deployment_id <> OLD.deployment_id
  BEGIN SELECT RAISE(ABORT, 'deployment is sealed'); END;
CREATE TRIGGER IF NOT EXISTS asset_sealed_no_delete BEFORE DELETE ON asset
  WHEN (SELECT sealed FROM deployment WHERE id = OLD.deployment_id) = 1
  BEGIN SELECT RAISE(ABORT, 'deployment is sealed'); END;
"""


class RegistryError(Exception):
    """The registry refused an operation for a reason the caller should surface."""


class StalePublisher(RegistryError):
    """`expected_active` did not match. Carries the id the caller should have sent."""

    def __init__(self, name: str, current_active: int | None):
        self.name = name
        self.current_active = current_active
        super().__init__(
            f"{name} was published by someone else first; its active deployment is "
            f"{current_active!r}, not what this request expected")


@dataclasses.dataclass(frozen=True)
class ActiveDeployment:
    deployment_id: int
    name: str
    repo: str
    commit_sha: str
    entry_path: str
    title: str | None
    project: str | None
    purpose: str | None
    published_at: str
    assets: dict[str, Asset]


class Registry:
    """Owns the durable SQLite database. One instance per process, one connection per thread."""

    def __init__(self, path: str, *, now=time.time):
        self._path = path
        self._now = now
        self._local = threading.local()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._path, isolation_level=None, timeout=5.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def initialize(self) -> None:
        self._conn().executescript(_SCHEMA)
        self.assert_intact()

    def assert_intact(self) -> None:
        """Refuse to serve if the singleton meta rows are gone (finding A4, start-up half)."""
        rows = {r["k"] for r in self._conn().execute("SELECT k FROM registry_meta")}
        missing = {"generation", "generated_at"} - rows
        if missing:
            raise RegistryError(
                f"registry_meta is missing {sorted(missing)}. Refusing to serve: without the "
                f"generation row the index ETag would stop advancing and every client would "
                f"hold a stale page with nothing surfaced.")

    def generation(self) -> int:
        row = self._conn().execute(
            "SELECT v FROM registry_meta WHERE k='generation'").fetchone()
        return int(row["v"]) if row else 0

    def generated_at(self) -> int:
        row = self._conn().execute(
            "SELECT v FROM registry_meta WHERE k='generated_at'").fetchone()
        return int(row["v"]) if row else 0

    def _bump(self, conn: sqlite3.Connection, key: str, value: int | None) -> None:
        # `key` is always one of two internal constants, never request input, so the previous
        # f-string was not injectable. It is parameterized anyway: an f-string carrying a
        # value into SQL is the shape a reader has to stop and prove safe, and proving it
        # safe again after every future edit is a cost with no benefit.
        if value is None:
            cur = conn.execute("UPDATE registry_meta SET v = v + 1 WHERE k = ?", (key,))
        else:
            cur = conn.execute("UPDATE registry_meta SET v = ? WHERE k = ?", (value, key))
        if cur.rowcount != 1:
            # Finding A4. SQLite runs this happily against zero rows, so without the check the
            # swap would commit while the ETag never moved.
            raise RegistryError(
                f"registry_meta row {key!r} is missing, so the swap cannot advance it. Rolling "
                f"the whole publish back rather than committing a deployment nobody can see.")

    def publish(self, manifest: Manifest) -> int:
        """Insert, seal and activate, or raise `StalePublisher`. Returns the new deployment id."""
        conn = self._conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            cur = conn.execute(
                "INSERT INTO deployment(name,repo,commit_sha,entry_path,title,project,purpose,"
                "published_at,sealed) VALUES(?,?,?,?,?,?,?,?,0)",
                (manifest.name, manifest.repo, manifest.commit_sha, manifest.entry_path,
                 manifest.title, manifest.project, manifest.purpose,
                 manifest.published_at or ""))
            dep = int(cur.lastrowid)
            conn.executemany(
                "INSERT INTO asset(deployment_id,url_path,repo_path,blob_id,size,sha256,"
                "content_type) VALUES(?,?,?,?,?,?,?)",
                [(dep, a.url_path, a.repo_path, a.blob_id, a.size, a.sha256, a.content_type)
                 for a in manifest.assets])
            # Seal AFTER the assets land, or the insert above trips its own trigger.
            conn.execute("UPDATE deployment SET sealed = 1 WHERE id = ?", (dep,))

            if manifest.expected_active is None:
                swapped = conn.execute(
                    "INSERT OR IGNORE INTO active(name, deployment_id) VALUES(?,?)",
                    (manifest.name, dep)).rowcount
            else:
                swapped = conn.execute(
                    "UPDATE active SET deployment_id=? WHERE name=? AND deployment_id=?",
                    (dep, manifest.name, manifest.expected_active)).rowcount
            if swapped != 1:
                current = conn.execute("SELECT deployment_id FROM active WHERE name=?",
                                       (manifest.name,)).fetchone()
                conn.execute("ROLLBACK")
                raise StalePublisher(manifest.name,
                                     int(current["deployment_id"]) if current else None)

            self._bump(conn, "generation", None)
            self._bump(conn, "generated_at", int(self._now()))
            conn.execute("COMMIT")
            return dep
        except StalePublisher:
            raise
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass
            raise

    def active(self, name: str) -> ActiveDeployment | None:
        conn = self._conn()
        row = conn.execute(
            "SELECT d.* FROM active a JOIN deployment d ON d.id = a.deployment_id "
            "WHERE a.name = ?", (name,)).fetchone()
        if row is None:
            return None
        assets = {
            r["url_path"]: Asset(url_path=r["url_path"], repo_path=r["repo_path"],
                                 blob_id=r["blob_id"], size=int(r["size"]),
                                 sha256=r["sha256"], content_type=r["content_type"])
            for r in conn.execute("SELECT * FROM asset WHERE deployment_id = ?", (row["id"],))
        }
        return ActiveDeployment(
            deployment_id=int(row["id"]), name=row["name"], repo=row["repo"],
            commit_sha=row["commit_sha"], entry_path=row["entry_path"], title=row["title"],
            project=row["project"], purpose=row["purpose"], published_at=row["published_at"],
            assets=assets)

    def index_rows(self) -> list[dict]:
        """One row per ACTIVE deployment, for the server-rendered index."""
        return [dict(r) for r in self._conn().execute(
            "SELECT d.name, d.title, d.project, d.purpose, d.commit_sha, d.published_at "
            "FROM active a JOIN deployment d ON d.id = a.deployment_id ORDER BY d.name")]

    def index_projects(self) -> list[str]:
        """Project names for `classify()`, longest first.

        Finding C3: the earlier `SELECT DISTINCT project FROM deployment` was wrong twice. It
        included NULL, which then reached a length comparison, and it read history rather than
        the active set, so a retired project name could re-classify a live row.
        """
        rows = self._conn().execute(
            "SELECT DISTINCT d.project FROM active a JOIN deployment d ON d.id = a.deployment_id "
            "WHERE d.project IS NOT NULL")
        return sorted((r["project"] for r in rows), key=len, reverse=True)
