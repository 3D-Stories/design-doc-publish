"""`harness.cache` — the content-addressed blob store, its LRU, and its crash windows.

Every crash window named in the design has a test here. The design claims that co-locating the
index and the bytes makes whole-volume loss consistent, and finding A3 correctly objected that
it does NOT make a filesystem write and a SQLite write atomic. So each boundary between the two
is exercised by simulating the crash and asserting reconciliation repairs it.
"""
import hashlib
import os
import threading

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


class TestSingleFlightWaiterFallback:
    """Step 8a inline review, finding I2.

    `get_or_fetch` set the in-flight event BEFORE popping the shared result, so a waiter
    woken by that event raced the pop. Losing the race meant falling back to `open()`, and
    for a blob too large to cache `open()` is always a miss — so the waiter raised
    `CacheError` and the request became a 502 for a page that had just been fetched
    successfully. A duplicate fetch is the right trade against that.
    """

    def test_a_waiter_that_misses_the_shared_result_fetches_rather_than_raising(self, cache):
        import hashlib
        big = b"x" * 5000                      # larger than the 1000-byte bound: never cached
        sha = hashlib.sha256(big).hexdigest()
        # Simulate the lost race directly: an event that is already set, with no result
        # recorded, is exactly the state a waiter sees when the leader popped first.
        ev = threading.Event(); ev.set()
        cache._inflight["a" * 40] = ev
        cache._results.pop("a" * 40, None)
        got = cache.get_or_fetch("a" * 40, sha, len(big), lambda: (big, sha))
        assert got == big, "the waiter must return the bytes, not raise"
