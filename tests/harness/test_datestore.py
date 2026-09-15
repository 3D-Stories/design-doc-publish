"""The persistent date cache (#65).

Every restart used to re-ask GitHub for the dates of all 618 documents, which is the 5-to-7
minute cold boot in the container logs. Measured 2026-09-15: 618 date calls are 41.36s of a
52.66s cold walk, so persisting them is what turns a restart back into ~11s.

The store lives on the volume `compose.yaml` calls "disposable: rebuilds from GitHub by design".
That word is the whole contract, and it cuts both ways: losing the file must cost one slow boot
and nothing else, and **being unable to write the file must never stop the service starting**.
Half these tests are about that second half.
"""
import sqlite3

import pytest

from harness.datestore import DateStore

KEY = ("3D-Stories/rawgentic", "docs/planning/a.html", "a" * 40)
OTHER = ("3D-Stories/saystory", "docs/b.html", "b" * 40)
VALUE = ("2026-03-01T09:00:00Z", "2026-08-24T09:10:11Z")


def store(tmp_path, name="index-dates.db", log=None):
    s = DateStore(str(tmp_path / name), log=log)
    s.initialize()
    return s


class TestRoundTrip:
    def test_a_stored_pair_comes_back(self, tmp_path):
        s = store(tmp_path)
        s.put(KEY, VALUE)
        assert s.get(KEY) == VALUE

    def test_an_absent_key_is_a_miss_not_an_error(self, tmp_path):
        assert store(tmp_path).get(KEY) is None

    def test_a_path_with_a_quote_and_a_percent_round_trips(self, tmp_path):
        # Paths arrive from GitHub tree responses — external data. They reach SQL only as bound
        # parameters, never as literals, and this is what proves it.
        s = store(tmp_path)
        odd = ("3D-Stories/x", "docs/it's 100% \"odd\".html", "c" * 40)
        s.put(odd, VALUE)
        assert s.get(odd) == VALUE

    def test_the_blob_id_is_part_of_the_key(self, tmp_path):
        # Keying on content is the whole reason a refresh only pays for files that changed.
        s = store(tmp_path)
        s.put(KEY, VALUE)
        changed = (KEY[0], KEY[1], "d" * 40)
        assert s.get(changed) is None


class TestRestart:
    def test_a_second_store_over_the_same_file_reads_the_first_ones_rows(self, tmp_path):
        """AC5. This is the entire point of the module."""
        first = store(tmp_path)
        first.put(KEY, VALUE)
        first.close()

        second = store(tmp_path)
        assert second.get(KEY) == VALUE

    def test_a_fresh_file_is_simply_empty(self, tmp_path):
        assert store(tmp_path, name="brand-new.db").get(KEY) is None


class TestDegrading:
    """A store that cannot be used degrades to nothing. It never raises, and it never blocks boot.

    Probed live in the serving container on 2026-09-15: an unwritable path raises
    `sqlite3.OperationalError`, which is **not** an `OSError`, while `os.makedirs` on an
    unwritable parent raises `PermissionError`, which is. Catching only one of the two families
    would turn an unwritable volume into a failed boot — the one outcome #65 forbids.
    """

    def test_initialize_on_an_unwritable_path_does_not_raise(self, tmp_path):
        lines = []
        s = DateStore("/proc/definitely-not-writable/index-dates.db", log=lines.append)
        s.initialize()
        assert s.available is False
        assert len(lines) == 1
        assert "initialize" in lines[0]
        assert "index-dates.db" in lines[0]

    def test_an_unavailable_store_is_inert_rather_than_broken(self, tmp_path):
        s = DateStore("/proc/definitely-not-writable/index-dates.db", log=lambda _m: None)
        s.initialize()
        s.put(KEY, VALUE)                    # must not raise
        assert s.get(KEY) is None
        s.prune([KEY], {KEY[0]})             # must not raise

    @pytest.mark.parametrize("operation", ["get", "put", "prune"])
    def test_a_failure_AFTER_initialize_degrades_rather_than_raising(self, tmp_path, operation):
        """The case an unwritable-path test cannot reach: a disk that fills later.

        Without this, a full volume raises out of `put` in the middle of the walk and fails
        every index build from then on — an optimization turning into an outage.
        """
        lines = []
        s = store(tmp_path, log=lines.append)
        assert s.available is True

        def boom(*_a, **_k):
            raise sqlite3.OperationalError("database or disk is full")

        s._conn = boom
        lines.clear()

        if operation == "get":
            assert s.get(KEY) is None
        elif operation == "put":
            s.put(KEY, VALUE)
        else:
            s.prune([KEY], {KEY[0]})

        assert s.available is False
        assert len(lines) == 1
        assert operation in lines[0]

    def test_it_logs_once_and_not_once_per_row(self, tmp_path):
        lines = []
        s = store(tmp_path, log=lines.append)

        def boom(*_a, **_k):
            raise sqlite3.OperationalError("database or disk is full")

        s._conn = boom
        lines.clear()
        for _ in range(5):
            s.put(KEY, VALUE)
        assert len(lines) == 1

    def test_an_oserror_degrades_too_not_only_a_sqlite_error(self, tmp_path):
        lines = []
        s = store(tmp_path, log=lines.append)

        def boom(*_a, **_k):
            raise PermissionError("nope")

        s._conn = boom
        lines.clear()
        s.put(KEY, VALUE)
        assert s.available is False
        assert len(lines) == 1


class TestPrune:
    """Every edit leaves its predecessor's row behind for ever, so the store is swept.

    Scoped to the repositories actually WALKED, because a repository the credential cannot read
    tells us nothing about which of its rows are live.
    """

    def test_a_dead_row_in_a_walked_repository_is_removed(self, tmp_path):
        s = store(tmp_path)
        live = (KEY[0], KEY[1], "new" + "a" * 37)
        s.put(KEY, VALUE)
        s.put(live, VALUE)
        s.prune([live], {KEY[0]})
        assert s.get(KEY) is None
        assert s.get(live) == VALUE

    def test_a_row_in_an_UNWALKED_repository_survives(self, tmp_path):
        # One unreadable repository must not cost another repository its cache.
        s = store(tmp_path)
        s.put(KEY, VALUE)
        s.put(OTHER, VALUE)
        s.prune([KEY], {KEY[0]})
        assert s.get(KEY) == VALUE
        assert s.get(OTHER) == VALUE

    def test_pruning_nothing_live_in_a_walked_repository_empties_only_that_one(self, tmp_path):
        s = store(tmp_path)
        s.put(KEY, VALUE)
        s.put(OTHER, VALUE)
        s.prune([], {KEY[0]})
        assert s.get(KEY) is None
        assert s.get(OTHER) == VALUE

    def test_prune_is_safe_to_call_twice(self, tmp_path):
        s = store(tmp_path)
        s.put(KEY, VALUE)
        s.prune([KEY], {KEY[0]})
        s.prune([KEY], {KEY[0]})
        assert s.get(KEY) == VALUE


class TestThreads:
    def test_eight_threads_can_write_at_once(self, tmp_path):
        """The walk writes from a pool of 8. Connections are thread-local, as in `BlobCache`.

        Probed live in the container against this exact schema: 8 threads x 77 inserts, 616
        rows, 0.132s, zero errors.
        """
        import threading

        s = store(tmp_path)
        start = threading.Barrier(8)
        errors = []

        def worker(n):
            try:
                start.wait()
                for i in range(25):
                    s.put((f"3D-Stories/r{n}", f"docs/p{i}.html", "e" * 40), VALUE)
            except Exception as exc:                     # noqa: BLE001 - the assertion IS this
                errors.append(repr(exc))

        ts = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert errors == []
        assert s.get(("3D-Stories/r7", "docs/p24.html", "e" * 40)) == VALUE


class TestTheLoggerItself:
    def test_a_logging_callback_that_raises_does_not_break_the_never_raise_contract(self, tmp_path):
        """The whole point of this class is that it cannot raise at a caller. A logger that
        throws while REPORTING a storage failure would break exactly that, and during
        `initialize` it would abort the boot — the one outcome #65 forbids."""
        def angry(_message):
            raise RuntimeError("the log sink is on fire")

        s = DateStore("/proc/definitely-not-writable/index-dates.db", log=angry)
        s.initialize()                                   # must not raise
        assert s.available is False

        good = DateStore(str(tmp_path / "ok.db"), log=angry)
        good.initialize()
        assert good.available is True

        def boom(*_a, **_k):
            raise sqlite3.OperationalError("disk is full")

        good._conn = boom
        good.put(KEY, VALUE)                             # must not raise
        assert good.get(KEY) is None
        good.prune([KEY], {KEY[0]})
        assert good.available is False
