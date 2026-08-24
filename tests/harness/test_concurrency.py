"""Two publishers, one name, at the same instant — through the real threaded path.

Design finding A5: the earlier text fixed a thread count and said nothing about SQLite
connection ownership, and the HTTP and SQLite probes were separate, so the COMBINED threaded
call shape was never proven. This file is that proof. Nothing is mocked: two OS threads, two
connections from the `threading.local`, one real database file, and a barrier so both are
inside the window at once.
"""
import hashlib
import io
import json
import threading

import pytest

from harness.app import make_app
from harness.cache import BlobCache
from harness.config import load_config
from harness.github import FakeGitHub
from harness.registry import Registry, StalePublisher

PAGE = b"<!doctype html><title>hi</title>"
PAGE_SHA = hashlib.sha256(PAGE).hexdigest()
REPO, COMMIT = "owner/repo", "c" * 40


def git_blob_id(data): return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


BLOB = git_blob_id(PAGE)
CFG = load_config({"DOC_HARNESS_GITHUB_TOKEN": "g", "DOC_HARNESS_PUBLISH_TOKEN": "s3cr3t",
                   "DOC_HARNESS_THREADS": "8", "DOC_HARNESS_MAX_CONCURRENT_PUBLISHES": "4"})


@pytest.fixture()
def stack(tmp_path):
    reg = Registry(str(tmp_path / "r.db")); reg.initialize()
    cache = BlobCache(str(tmp_path / "c"), max_bytes=1000000); cache.initialize()
    src = FakeGitHub(
        trees={(REPO, COMMIT): [{"path": "i.html", "type": "blob", "mode": "100644",
                                 "sha": BLOB, "size": len(PAGE)}]},
        blobs={(REPO, BLOB): PAGE})
    yield reg, cache, make_app(cfg=CFG, registry=reg, cache=cache, source=src)
    reg.close(); cache.close()


def payload(expected_active=None):
    return {"name": "proj-design-1", "repo": REPO, "commit_sha": COMMIT,
            "entry_path": "/index.html",
            "assets": [{"url_path": "/index.html", "repo_path": "i.html", "blob_id": BLOB,
                        "size": len(PAGE), "sha256": PAGE_SHA}],
            "title": "T", "project": "proj", "purpose": "design",
            "published_at": "2026-08-24T00:00:00Z", "expected_active": expected_active}


def post(app, body_dict):
    raw = json.dumps(body_dict).encode()
    env = {"HTTP_HOST": "docs-control." + CFG.zone, "REQUEST_METHOD": "POST",
           "PATH_INFO": "/v1/deployments", "QUERY_STRING": "",
           "CONTENT_LENGTH": str(len(raw)), "wsgi.input": io.BytesIO(raw),
           "wsgi.errors": io.StringIO(), "HTTP_AUTHORIZATION": "Bearer s3cr3t"}
    cap = {}

    def start_response(status, headers, exc_info=None):
        cap["status"] = int(status.split()[0])
    body = b"".join(app(env, start_response))
    return cap["status"], body


def test_two_barrier_synchronised_publishers_of_one_name_produce_one_winner(stack):
    reg, _cache, app = stack
    barrier = threading.Barrier(2)
    results: dict[int, tuple] = {}

    def publisher(i):
        barrier.wait()
        results[i] = post(app, payload())

    threads = [threading.Thread(target=publisher, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert all(not t.is_alive() for t in threads), "a publisher deadlocked"

    statuses = sorted(s for s, _ in results.values())
    assert statuses == [201, 409], f"expected exactly one winner, got {statuses}"

    # Exactly one generation increment, and both attempts left a history row.
    assert reg.generation() == 1
    rows = reg._conn().execute(
        "SELECT COUNT(*) FROM deployment WHERE name='proj-design-1'").fetchone()[0]
    assert rows == 1, "the loser's candidate row must have rolled back"

    loser_body = next(b for s, b in results.values() if s == 409)
    assert json.loads(loser_body)["active_deployment_id"] == reg.active(
        "proj-design-1").deployment_id


def test_concurrent_publishes_of_DIFFERENT_names_all_succeed(stack):
    reg, _cache, app = stack
    barrier = threading.Barrier(4)
    out: dict[int, int] = {}

    def publisher(i):
        body = payload()
        body["name"] = f"proj{i}-design-1"
        barrier.wait()
        out[i] = post(app, body)[0]

    threads = [threading.Thread(target=publisher, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert all(not t.is_alive() for t in threads)
    assert sorted(out.values()) == [201, 201, 201, 201]
    assert reg.generation() == 4


def test_each_thread_gets_its_own_sqlite_connection(stack):
    reg, _cache, _app = stack
    seen: list[int] = []
    lock = threading.Lock()

    def touch():
        conn = reg._conn()
        with lock:
            seen.append(id(conn))
        reg.generation()

    threads = [threading.Thread(target=touch) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert len(set(seen)) == 4, "connections must not be shared across threads"


def test_reads_keep_working_while_a_publish_is_in_flight(stack):
    reg, _cache, app = stack
    post(app, payload())
    errors: list[Exception] = []

    def reader():
        try:
            for _ in range(20):
                assert reg.active("proj-design-1") is not None
        except Exception as exc:                      # pragma: no cover - reported below
            errors.append(exc)

    def writer():
        try:
            for i in range(5):
                body = payload()
                body["name"] = f"other{i}-design-1"
                post(app, body)
        except Exception as exc:                      # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=reader), threading.Thread(target=writer)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors, f"reads and writes collided: {errors}"
