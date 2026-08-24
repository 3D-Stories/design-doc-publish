"""`harness.registry` — SQLite schema, the seal, and the compare-and-swap.

Every test runs against a real SQLite file under `tmp_path`, never a mock. WAL,
`BEGIN IMMEDIATE` and the triggers are the behaviour under test, and a mock of SQLite would
assert only that this file calls the functions this file calls.
"""
import sqlite3

import pytest

from harness.manifest import Asset, Manifest
from harness.registry import Registry, StalePublisher

A = Asset(url_path="/index.html", repo_path="docs/out/index.html", blob_id="a" * 40,
          size=10, sha256="b" * 64, content_type="text/html; charset=utf-8")


def manifest(name="proj-design-12", expected_active=None, assets=(A,), commit="c" * 40):
    return Manifest(name=name, repo="owner/repo", commit_sha=commit, entry_path="/index.html",
                    assets=tuple(assets), title="T", project="proj", purpose="design",
                    published_at="2026-08-24T00:00:00Z", expected_active=expected_active,
                    total_bytes=sum(a.size for a in assets))


@pytest.fixture()
def reg(tmp_path):
    r = Registry(str(tmp_path / "registry.db"))
    r.initialize()
    yield r
    r.close()


class TestSchema:
    def test_wal_is_on(self, reg):
        assert reg._conn().execute("PRAGMA journal_mode").fetchone()[0] == "wal"

    def test_foreign_keys_are_on(self, reg):
        assert reg._conn().execute("PRAGMA foreign_keys").fetchone()[0] == 1

    def test_the_singleton_meta_rows_exist(self, reg):
        assert reg.generation() == 0
        assert reg.generated_at() == 0

    def test_initialize_is_idempotent(self, tmp_path):
        p = str(tmp_path / "r.db")
        Registry(p).initialize()
        r = Registry(p)
        r.initialize()
        assert r.generation() == 0
        r.close()


class TestCompareAndSwap:
    def test_a_first_publish_with_null_expected_active_succeeds(self, reg):
        dep = reg.publish(manifest())
        assert dep > 0
        assert reg.active("proj-design-12").deployment_id == dep

    def test_a_second_null_expected_active_is_refused_as_stale(self, reg):
        reg.publish(manifest())
        with pytest.raises(StalePublisher):
            reg.publish(manifest())

    def test_the_correct_expected_active_succeeds(self, reg):
        first = reg.publish(manifest())
        second = reg.publish(manifest(expected_active=first))
        assert reg.active("proj-design-12").deployment_id == second

    def test_a_stale_expected_active_is_refused(self, reg):
        first = reg.publish(manifest())
        reg.publish(manifest(expected_active=first))
        with pytest.raises(StalePublisher):
            reg.publish(manifest(expected_active=first))

    def test_the_stale_error_carries_the_current_active_id(self, reg):
        first = reg.publish(manifest())
        with pytest.raises(StalePublisher) as exc:
            reg.publish(manifest())
        assert exc.value.current_active == first

    def test_a_refused_swap_leaves_no_orphan_deployment_row(self, reg):
        reg.publish(manifest())
        before = reg._conn().execute("SELECT COUNT(*) FROM deployment").fetchone()[0]
        with pytest.raises(StalePublisher):
            reg.publish(manifest())
        after = reg._conn().execute("SELECT COUNT(*) FROM deployment").fetchone()[0]
        assert after == before, "a rolled-back publish must leave nothing behind"

    def test_history_is_retained(self, reg):
        first = reg.publish(manifest())
        reg.publish(manifest(expected_active=first))
        rows = reg._conn().execute(
            "SELECT COUNT(*) FROM deployment WHERE name='proj-design-12'").fetchone()[0]
        assert rows == 2

    def test_two_names_do_not_interfere(self, reg):
        a = reg.publish(manifest(name="one-design-1"))
        b = reg.publish(manifest(name="two-design-1"))
        assert reg.active("one-design-1").deployment_id == a
        assert reg.active("two-design-1").deployment_id == b


class TestGenerationCounter:
    def test_it_increments_once_per_successful_swap(self, reg):
        assert reg.generation() == 0
        first = reg.publish(manifest())
        assert reg.generation() == 1
        reg.publish(manifest(expected_active=first))
        assert reg.generation() == 2

    def test_it_does_not_move_on_a_refusal(self, reg):
        reg.publish(manifest())
        with pytest.raises(StalePublisher):
            reg.publish(manifest())
        assert reg.generation() == 1

    def test_generated_at_moves_with_the_generation(self, reg):
        reg.publish(manifest())
        assert reg.generated_at() > 0

    def test_a_missing_generation_row_rolls_the_whole_swap_back(self, reg):
        # Finding A4: SQLite runs `UPDATE ... WHERE k='generation'` happily against zero
        # rows. Without the rowcount assertion the swap would commit and every client would
        # keep a stale index behind an ETag that never changed, with nothing surfaced.
        reg._conn().execute("DELETE FROM registry_meta WHERE k='generation'")
        with pytest.raises(Exception) as exc:
            reg.publish(manifest())
        assert "generation" in str(exc.value).lower()
        assert reg._conn().execute("SELECT COUNT(*) FROM active").fetchone()[0] == 0
        assert reg._conn().execute("SELECT COUNT(*) FROM deployment").fetchone()[0] == 0


class TestSealTriggers:
    def test_a_sealed_deployment_cannot_be_updated_or_deleted(self, reg):
        dep = reg.publish(manifest())
        c = reg._conn()
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("UPDATE deployment SET commit_sha='d'*40 WHERE id=?", (dep,))
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("DELETE FROM deployment WHERE id=?", (dep,))

    def test_a_sealed_deployments_assets_cannot_be_inserted_updated_or_deleted(self, reg):
        # Finding B2. The INSERT case matters most: a new url_path changes what a sealed
        # deployment serves just as effectively as editing one.
        dep = reg.publish(manifest())
        c = reg._conn()
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO asset(deployment_id,url_path,repo_path,blob_id,size,sha256,"
                      "content_type) VALUES(?,'/new.css','x','a'*40,1,'b'*64,'text/css')", (dep,))
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("UPDATE asset SET blob_id='d'*40 WHERE deployment_id=?", (dep,))
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("DELETE FROM asset WHERE deployment_id=?", (dep,))

    def test_an_asset_cannot_be_reparented_into_a_sealed_deployment(self, reg):
        # Finding C7. Checking only the OLD parent leaves this hole: an asset on an unsealed
        # deployment moved into a sealed one adds a served path without firing the INSERT
        # trigger.
        sealed = reg.publish(manifest())
        c = reg._conn()
        c.execute("INSERT INTO deployment(name,repo,commit_sha,entry_path,published_at,sealed) "
                  "VALUES('scratch','o/r','c'*40,'/i.html','now',0)")
        unsealed = c.execute("SELECT id FROM deployment WHERE name='scratch'").fetchone()[0]
        c.execute("INSERT INTO asset(deployment_id,url_path,repo_path,blob_id,size,sha256,"
                  "content_type) VALUES(?,'/x.css','x','a'*40,1,'b'*64,'text/css')", (unsealed,))
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("UPDATE asset SET deployment_id=? WHERE deployment_id=?", (sealed, unsealed))


class TestReads:
    def test_active_returns_none_for_an_unknown_name(self, reg):
        assert reg.active("nope-design-1") is None

    def test_active_carries_the_manifest_assets(self, reg):
        reg.publish(manifest())
        act = reg.active("proj-design-12")
        assert act.entry_path == "/index.html"
        assert act.assets["/index.html"].sha256 == "b" * 64
        assert act.commit_sha == "c" * 40

    def test_index_rows_only_include_active_deployments(self, reg):
        first = reg.publish(manifest())
        reg.publish(manifest(expected_active=first, commit="d" * 40))
        rows = reg.index_rows()
        assert len(rows) == 1
        assert rows[0]["commit_sha"] == "d" * 40

    def test_index_projects_excludes_null_and_reads_only_active(self, reg):
        # Finding C3. `SELECT DISTINCT project FROM deployment` was wrong twice: `project`
        # is nullable, so a NULL reaches a length comparison and raises, and reading
        # `deployment` lets retired history re-classify a live row.
        reg.publish(manifest(name="alpha-design-1"))
        c = reg._conn()
        c.execute("INSERT INTO deployment(name,repo,commit_sha,entry_path,published_at,project,"
                  "sealed) VALUES('ghost-design-1','o/r','c'*40,'/i.html','now','retired',1)")
        reg.publish(manifest(name="beta-design-1"))
        projects = reg.index_projects()
        assert "retired" not in projects, "history must not classify live rows"
        assert "proj" in projects

    def test_a_null_project_on_an_active_row_does_not_raise(self, reg):
        reg.publish(manifest())
        c = reg._conn()
        c.execute("INSERT INTO deployment(name,repo,commit_sha,entry_path,published_at,project,"
                  "sealed) VALUES('nullproj-design-1','o/r','c'*40,'/i.html','now',NULL,0)")
        rid = c.execute("SELECT id FROM deployment WHERE name='nullproj-design-1'").fetchone()[0]
        c.execute("INSERT INTO active(name,deployment_id) VALUES('nullproj-design-1',?)", (rid,))
        assert reg.index_projects() == sorted(["proj"], key=len, reverse=True)
