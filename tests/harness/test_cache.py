"""`harness.cache` — the content-addressed blob store, its LRU, and its crash windows.

Every crash window named in the design has a test here. The design claims that co-locating the
index and the bytes makes whole-volume loss consistent, and finding A3 correctly objected that
it does NOT make a filesystem write and a SQLite write atomic. So each boundary between the two
is exercised by simulating the crash and asserting reconciliation repairs it.
"""
import hashlib
import os
import threading
import time

import pytest

from harness.cache import BlobCache, CacheConflict

H = lambda b: hashlib.sha256(b).hexdigest()  # noqa: E731


@pytest.fixture()
def cache(tmp_path):
    c = BlobCache(str(tmp_path / "cache"), max_bytes=1000)
    c.initialize()
    yield c
    c.close()


class TestStoreAndRead:
    def test_a_stored_blob_reads_back_exactly(self, cache):
        cache.put("a" * 40, b"hello", H(b"hello"))
        with cache.open("a" * 40, H(b"hello"), 5) as fh:
            assert fh.read() == b"hello"

    def test_a_miss_returns_none(self, cache):
        assert cache.open("f" * 40, H(b"x"), 1) is None

    def test_a_sha256_mismatch_on_write_refuses_and_stores_nothing(self, cache):
        with pytest.raises(CacheConflict):
            cache.put("a" * 40, b"hello", H(b"different"))
        assert cache.total_bytes() == 0
        assert cache.open("a" * 40, H(b"hello"), 5) is None

    def test_no_temporary_file_is_left_after_a_refused_write(self, cache):
        with pytest.raises(CacheConflict):
            cache.put("a" * 40, b"hello", H(b"different"))
        assert os.listdir(cache.tmp_dir) == []


class TestCacheHitInvariant:
    def test_a_hit_whose_sha256_disagrees_is_purged_and_missed(self, cache):
        # Finding B6: the cache is keyed by blob_id, but each deployment declares its own
        # sha256 and size. The key alone does not prove the entry is the right bytes for
        # THIS asset, and serving them would carry the requesting deployment's ETag.
        cache.put("a" * 40, b"hello", H(b"hello"))
        assert cache.open("a" * 40, H(b"other bytes"), 5) is None
        assert cache.total_bytes() == 0, "the conflicting entry must be purged, not kept"

    def test_a_hit_whose_size_disagrees_is_purged_and_missed(self, cache):
        cache.put("a" * 40, b"hello", H(b"hello"))
        assert cache.open("a" * 40, H(b"hello"), 999) is None
        assert cache.total_bytes() == 0


class TestLru:
    def test_eviction_removes_the_least_recently_used_first(self, cache):
        cache.put("a" * 40, b"x" * 400, H(b"x" * 400))
        cache.put("b" * 40, b"y" * 400, H(b"y" * 400))
        with cache.open("a" * 40, H(b"x" * 400), 400) as fh:   # touch a, so b is oldest
            fh.read()
        cache.put("c" * 40, b"z" * 400, H(b"z" * 400))
        assert cache.open("b" * 40, H(b"y" * 400), 400) is None
        with cache.open("a" * 40, H(b"x" * 400), 400) as fh:
            assert fh.read() == b"x" * 400

    def test_eviction_stops_at_the_bound(self, cache):
        for i in range(6):
            data = bytes([i]) * 300
            cache.put(f"{i}" * 40, data, H(data))
        assert cache.total_bytes() <= 1000

    def test_a_blob_larger_than_the_whole_bound_is_not_cached_and_evicts_nothing(self, cache):
        cache.put("a" * 40, b"x" * 400, H(b"x" * 400))
        huge = b"h" * 2000
        cache.put("b" * 40, huge, H(huge))
        assert cache.open("b" * 40, H(huge), 2000) is None, "it must not be stored"
        with cache.open("a" * 40, H(b"x" * 400), 400) as fh:
            assert fh.read() == b"x" * 400, "and it must not have evicted the existing entry"


class TestCrashWindows:
    def test_an_orphan_file_with_no_row_is_deleted_at_start_up(self, cache, tmp_path):
        cache.put("a" * 40, b"hello", H(b"hello"))
        cache._conn().execute("DELETE FROM blob WHERE blob_id=?", ("a" * 40,))
        cache.reconcile()
        assert cache.open("a" * 40, H(b"hello"), 5) is None
        assert cache.total_bytes() == 0

    def test_a_row_with_no_file_is_deleted_at_start_up(self, cache):
        cache.put("a" * 40, b"hello", H(b"hello"))
        os.unlink(cache.path_for("a" * 40))
        cache.reconcile()
        assert cache._conn().execute("SELECT COUNT(*) FROM blob").fetchone()[0] == 0
        assert cache.total_bytes() == 0

    def test_a_leftover_temporary_file_is_deleted_at_start_up(self, cache):
        stray = os.path.join(cache.tmp_dir, "half-written")
        with open(stray, "wb") as fh:
            fh.write(b"partial")
        cache.reconcile()
        assert os.listdir(cache.tmp_dir) == []

    def test_an_abandoned_staging_directory_is_deleted_at_start_up(self, cache):
        # Finding C1: staged bytes sit outside LRU accounting by design, so a crash
        # mid-publish orphans up to DOC_HARNESS_MAX_PUBLISH_BYTES invisibly, per publish,
        # until the volume fills.
        d = cache.staging_dir("publish-123")
        with open(os.path.join(d, "blob"), "wb") as fh:
            fh.write(b"abandoned")
        cache.reconcile()
        assert os.listdir(cache.staging_root) == []

    def test_a_missing_file_is_a_miss_not_an_error(self, cache):
        # The invariant that makes every window above harmless.
        cache.put("a" * 40, b"hello", H(b"hello"))
        os.unlink(cache.path_for("a" * 40))
        assert cache.open("a" * 40, H(b"hello"), 5) is None
        assert cache._conn().execute("SELECT COUNT(*) FROM blob").fetchone()[0] == 0

    def test_reconcile_restores_the_byte_total(self, cache):
        cache.put("a" * 40, b"x" * 400, H(b"x" * 400))
        cache._conn().execute("UPDATE blob SET size = 999999 WHERE blob_id=?", ("a" * 40,))
        cache.reconcile()
        assert cache.total_bytes() == 400


class TestLease:
    def test_a_reader_finishes_after_the_file_is_unlinked_mid_read(self, cache):
        payload = os.urandom(600)
        cache.put("a" * 40, payload, H(payload))
        fh = cache.open("a" * 40, H(payload), len(payload))
        head = fh.read(100)
        os.unlink(cache.path_for("a" * 40))          # the evictor
        rest = fh.read()
        fh.close()
        assert head + rest == payload


class TestStaging:
    def test_staged_bytes_are_not_counted_in_the_lru(self, cache):
        # Finding B5: admitting before the CAS lets a LOSING publisher evict the active
        # deployment's warm blobs on its way to being rejected.
        cache.put("a" * 40, b"x" * 400, H(b"x" * 400))
        d = cache.staging_dir("p1")
        staged = cache.stage("p1", "b" * 40, b"y" * 900, H(b"y" * 900))
        assert os.path.exists(staged)
        assert cache.total_bytes() == 400, "staging must not touch LRU accounting"
        with cache.open("a" * 40, H(b"x" * 400), 400) as fh:
            assert fh.read() == b"x" * 400, "and must not have evicted anything"
        assert os.path.isdir(d)

    def test_discarding_a_publish_removes_its_whole_staging_directory(self, cache):
        cache.stage("p1", "b" * 40, b"y", H(b"y"))
        cache.discard_staging("p1")
        assert not os.path.exists(cache.staging_dir("p1", create=False))

    def test_committing_admits_the_staged_blobs_to_the_cache(self, cache):
        cache.stage("p1", "b" * 40, b"y" * 100, H(b"y" * 100))
        cache.commit_staging("p1", [("b" * 40, H(b"y" * 100), 100)])
        with cache.open("b" * 40, H(b"y" * 100), 100) as fh:
            assert fh.read() == b"y" * 100
        assert cache.total_bytes() == 100
        assert not os.path.exists(cache.staging_dir("p1", create=False))


class TestSingleFlight:
    def test_two_concurrent_misses_on_one_blob_cause_exactly_one_fetch(self, cache):
        calls = []
        started = threading.Barrier(2)

        def fetch():
            calls.append(1)
            return b"payload", H(b"payload")

        def worker(out, i):
            started.wait()
            out[i] = cache.get_or_fetch("a" * 40, H(b"payload"), 7, fetch)

        out = {}
        ts = [threading.Thread(target=worker, args=(out, i)) for i in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert out[0] == out[1] == b"payload"
        assert len(calls) == 1, "single-flight must collapse the duplicate fetch"


class TestSingleFlightOutcomeHandoff:
    """Step 8a findings I2 and R5 together, because two earlier attempts each fixed one
    and broke the other.

    I2: the result was published into a shared dict and popped AFTER the event was set, so a
    waiter raced the pop. Losing the race fell through to `open()`, which for a blob too
    large to cache is always a miss — the waiter raised, and a page that had just been
    fetched successfully became a 502.

    The next attempt had the losing waiter fetch again. That stopped the raise and defeated
    R5: the coalescer's whole purpose is exactly ONE upstream call, and that version made
    two.

    Handing every waiter a reference to the same outcome object satisfies both.
    """

    def test_a_blob_too_large_to_cache_still_reaches_every_waiter(self, cache):
        import hashlib
        big = b"x" * 5000                      # over the 1000-byte bound: never stored
        sha = hashlib.sha256(big).hexdigest()
        calls = []
        start = threading.Barrier(3)
        out = {}
        # Step 11 finding F15. The barrier releases three threads, but it cannot make the fetch
        # still be IN FLIGHT when the other two reach the election — and an in-memory fetch
        # returns immediately. A leader could therefore finish and drop its in-flight entry
        # before a sibling arrived, which elected a second leader and made a second call. The
        # test then failed roughly three runs in eight while the coalescer was working exactly
        # as designed. A blob this large is never stored, so no cache re-check can close that
        # window: holding the fetch open until every sibling is blocked is what makes the
        # measurement about coalescing rather than about thread scheduling.
        entering = threading.Semaphore(0)

        def fetch():
            calls.append(1)
            # Which thread wins the election is not knowable in advance, so every thread
            # signals; the leader's own signal is already released by the time it gets here.
            for _ in range(3):
                assert entering.acquire(timeout=20), "a caller never reached the coalescer"
            # Both siblings are past their signal and heading for the lock. The pause is
            # generous by orders of magnitude against an uncontended lock acquisition, and it
            # is the whole reason this measures coalescing rather than thread scheduling.
            time.sleep(0.05)
            return big, sha

        def worker(i):
            start.wait()
            entering.release()
            out[i] = cache.get_or_fetch("a" * 40, sha, len(big), fetch)

        ts = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=20)
        assert all(not t.is_alive() for t in ts)
        assert all(v == big for v in out.values()), "no waiter may raise or get short data"
        assert len(calls) == 1, "and there must still be exactly one upstream call"

    def test_a_fetch_failure_reaches_every_waiter_with_its_own_type(self, cache):
        import hashlib
        sha = hashlib.sha256(b"never arrives").hexdigest()
        start = threading.Barrier(3)
        out = {}

        class Upstream404(Exception):
            pass

        def fetch():
            raise Upstream404("gone")

        def worker(i):
            start.wait()
            try:
                cache.get_or_fetch("a" * 40, sha, 13, fetch)
                out[i] = "NO RAISE"
            except Upstream404:
                out[i] = "Upstream404"
            except Exception as exc:
                out[i] = type(exc).__name__

        ts = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=20)
        assert set(out.values()) == {"Upstream404"}, (
            f"every waiter needs the leader's real error type, got {out}")

class TestStep11Bound:
    """Step 11 F2: the bound has to hold DURING the write, not only after it."""

    def test_room_is_made_before_the_write_lands_not_after(self, tmp_path):
        """The bound must hold DURING the write, which is only observable AT the write."""
        c = BlobCache(str(tmp_path / "c"), max_bytes=1000)
        c.initialize()
        seen = []
        real_write = c._write_bytes
        try:
            def watched(target, data):
                seen.append(c.total_bytes() + len(data))
                return real_write(target, data)
            c._write_bytes = watched
            c.put("a" * 40, b"x" * 600, H(b"x" * 600))
            c.put("b" * 40, b"y" * 600, H(b"y" * 600))
            assert seen == [600, 600], (
                "at each write, already-accounted bytes plus the incoming blob must fit inside "
                f"the 1000-byte bound; saw {seen}")
            assert c.total_bytes() <= 1000
        finally:
            c._write_bytes = real_write
            c.close()

    def test_a_cache_write_failure_still_returns_the_verified_bytes(self, cache, monkeypatch):
        def boom(*_a, **_k):
            raise OSError(28, "No space left on device")
        monkeypatch.setattr(cache, "_write_bytes", boom)
        got = cache.get_or_fetch("c" * 40, H(b"hello"), 5, lambda: (b"hello", H(b"hello")))
        assert got == b"hello", "a full cache volume must not fail a verified fetch"

    def test_a_hash_mismatch_still_propagates_through_get_or_fetch(self, cache):
        with pytest.raises(CacheConflict):
            cache.get_or_fetch("d" * 40, H(b"hello"), 5, lambda: (b"other", H(b"hello")))


class TestStep11Reconcile:
    """Step 11 F6: start-up must not claim a reconciliation it could not perform."""

    def test_reconcile_refuses_when_an_orphan_cannot_be_removed(self, tmp_path, monkeypatch):
        from harness.cache import CacheError
        c = BlobCache(str(tmp_path / "c"), max_bytes=1000)
        c.initialize()
        try:
            orphan = os.path.join(c.blob_dir, "ab", "ab" + "c" * 38)
            os.makedirs(os.path.dirname(orphan), exist_ok=True)
            with open(orphan, "wb") as fh:
                fh.write(b"orphan")

            def refuse(path):
                raise OSError(1, "Operation not permitted")
            monkeypatch.setattr(os, "unlink", refuse)
            with pytest.raises(CacheError):
                c.reconcile()
        finally:
            c.close()

    def test_discard_staging_stays_best_effort(self, cache):
        cache.discard_staging("never-created")
