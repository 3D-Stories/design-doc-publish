"""A convention-resolved page serves its OWN images, and nothing else.

Found live on 2026-09-24: `2026-09-23-chorestory-mmo-mmo-gap-analysis` rendered with every one of
its seven `<img>` tags broken. The page was never published, so it had no registry row, and
`ConventionResolver.resolve` built a deployment whose asset table held `/index.html` and nothing
else. `serve` answers 404 for any path outside that table, so no image on a convention page could
ever load. Measured at the origin: 7 of 7 image requests 404, sequentially and concurrently, each
one after a full GitHub resolution of about 3.7 seconds.

These tests drive the WSGI callable, which is the entry path a real request takes.
"""
import hashlib
import io
import threading
import time

import pytest

from harness.app import make_app
from harness.cache import BlobCache
from harness.config import load_config
from harness.github import (BudgetExhausted, DeadlineExceeded, FakeGitHub, RateLimited)
from harness.registry import Registry


def git_blob_id(data): return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


CFG = load_config({"DOC_HARNESS_GITHUB_TOKEN": "g", "DOC_HARNESS_PUBLISH_TOKEN": "s3cr3t"})
REPO = "3D-Stories/rawgentic"
COMMIT, COMMIT2 = "c" * 40, "d" * 40
DOC = "docs/planning/2026-09-23-mmo-gap-analysis.html"
HOST = "2026-09-23-rawgentic-mmo-gap-analysis." + CFG.zone
FOLDER = "assets/2026-09-23-mmo-gap-analysis"
NAMES = ["p1-godot-web-build", "p1c-ios-simulator-ipad", "p3-kid-retarget",
         "p4-pixellab-ui-icons", "p6-pixellab-character", "p6-pixellab-ui-tiles",
         "p6-hybrid-hd2d"]


def png(tag: str) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + tag.encode() * 40


IMAGES = {f"/{FOLDER}/{n}.png": png(n) for n in NAMES}
# A name that needs encoding, referenced with a cache buster. The browser sends the DECODED
# path through WSGI, exactly as `TestStep11EncodedAssetNames` pins for the publish path.
SPACED = ("/shots/my shot.png", png("spaced"))

# Every shape the allowlist must refuse. Each one EXISTS in the tree, so a 404 here proves the
# rule refused it, not that the file was missing.
FORBIDDEN = {
    "unreferenced": ("docs/planning/" + FOLDER + "/unreferenced.png",
                     "/" + FOLDER + "/unreferenced.png"),
    "dotenv": ("docs/planning/.env", "/.env"),
    "escapes the page directory": ("docs/secret.png", "/secret.png"),
    "not an image suffix": ("docs/planning/data.json", "/data.json"),
    "a symlink": ("docs/planning/link.png", "/link.png"),
    "root-relative reference": ("docs/planning/root.png", "/root.png"),
    "the page by its repository path": (DOC, "/" + DOC),
}


def page_html(extra_refs=()) -> bytes:
    tags = [f'<p><img src="{FOLDER}/{n}.png" alt="{n}">' for n in NAMES]
    tags.append('<p><img src="shots/my%20shot.png?v=2" alt="spaced">')
    # References the allowlist must NOT turn into servable paths. `%2e%2e` is a dot-dot segment to
    # a browser too, so it requests `/secret.png` exactly as `../` does.
    tags += ['<img src="../secret.png">', '<img src="%2e%2e/secret.png">',
             '<img src="data.json">', '<img src="link.png">',
             '<img src="/root.png">', '<img src="missing.png">']
    tags += list(extra_refs)
    return ("<!doctype html><title>gap</title>\n" + "\n".join(tags)).encode()


PAGE = page_html()


def tree_for(page: bytes, images: dict) -> list:
    rows = [{"path": DOC, "type": "blob", "mode": "100644", "sha": git_blob_id(page),
             "size": len(page)}]
    for url, data in images.items():
        rows.append({"path": "docs/planning" + url, "type": "blob", "mode": "100644",
                     "sha": git_blob_id(data), "size": len(data)})
    for label, (repo_path, _) in FORBIDDEN.items():
        if repo_path == DOC:
            continue
        data = ("forbidden " + label).encode()
        rows.append({"path": repo_path, "type": "blob",
                     "mode": "120000" if label == "a symlink" else "100644",
                     "sha": git_blob_id(data), "size": len(data)})
    return rows


def blobs_for(page: bytes, images: dict) -> dict:
    out = {(REPO, git_blob_id(page)): page}
    out.update({(REPO, git_blob_id(d)): d for d in images.values()})
    for label, (repo_path, _) in FORBIDDEN.items():
        data = ("forbidden " + label).encode()
        out[(REPO, git_blob_id(data))] = data
    return out


class SlowSource(FakeGitHub):
    """Holds each tree and blob call open long enough for concurrent requests to overlap, and
    records which blobs were asked for, so a refused path can be shown never to reach GitHub.

    It keeps its OWN call counts, under a lock. `FakeGitHub`'s counters are a bare `+= 1`, which
    is a read-modify-write, and eight threads released by one barrier are exactly the load that
    could lose an increment and fail a correct build.
    """

    def __init__(self, *a, delay=0.05, **kw):
        super().__init__(*a, **kw)
        self.delay = delay
        self.blob_ids = []
        self.counts = {"commit": 0, "tree": 0, "blob": 0}
        self._record = threading.Lock()

    def _count(self, kind):
        with self._record:
            self.counts[kind] += 1

    def commit(self, *a, **kw):
        self._count("commit")
        return super().commit(*a, **kw)

    def tree(self, *a, **kw):
        time.sleep(self.delay)
        self._count("tree")
        return super().tree(*a, **kw)

    def blob(self, repo, blob_id, *a, **kw):
        time.sleep(self.delay)
        with self._record:
            self.blob_ids.append(blob_id)
            self.counts["blob"] += 1
        return super().blob(repo, blob_id, *a, **kw)


ALL_IMAGES = dict(IMAGES, **{SPACED[0]: SPACED[1]})


@pytest.fixture()
def stack(tmp_path):
    reg = Registry(str(tmp_path / "r.db")); reg.initialize()
    cache = BlobCache(str(tmp_path / "c"), max_bytes=10_000_000); cache.initialize()
    src = SlowSource(trees={(REPO, COMMIT): tree_for(PAGE, ALL_IMAGES)},
                     blobs=blobs_for(PAGE, ALL_IMAGES),
                     commits={(REPO, "HEAD"): COMMIT},
                     repos=["rawgentic"])
    app = make_app(cfg=CFG, registry=reg, cache=cache, source=src)
    _wait_until_index_is_warm(app)
    yield app, src
    reg.close(); cache.close()


def _wait_until_index_is_warm(app, timeout=5.0):
    """The boot warm-up walks the same source. Waiting for it keeps its calls out of the counts
    these tests take, so every count below is this page's and nobody else's."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        cap, _ = call(app, "index." + CFG.zone, "/")
        if not cap["status"].startswith("503"):
            return
        time.sleep(0.01)


def call(app, host, path="/"):
    env = {"HTTP_HOST": host, "REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": "",
           "wsgi.input": io.BytesIO(b""), "wsgi.errors": io.StringIO(), "CONTENT_LENGTH": ""}
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = b"".join(app(env, start_response))
    return captured, body


def load_concurrently(app, paths):
    """Every path at once, released by one barrier: a cold browser load of the page."""
    barrier = threading.Barrier(len(paths))
    results = {}

    def hit(path):
        barrier.wait()
        results[path] = call(app, HOST, path)

    threads = [threading.Thread(target=hit, args=(p,)) for p in paths]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    assert not any(t.is_alive() for t in threads), "a request never finished"
    return results


class TestEveryImageServes:
    def test_seven_sibling_images_serve_under_a_cold_concurrent_load(self, stack):
        app, src = stack
        paths = ["/"] + list(ALL_IMAGES)
        results = load_concurrently(app, paths)
        cap, body = results["/"]
        assert cap["status"].startswith("200"), cap["status"]
        assert body == PAGE
        for url, data in ALL_IMAGES.items():
            cap, body = results[url]
            assert cap["status"].startswith("200"), (url, cap["status"], body[:80])
            assert body == data, url
            assert cap["headers"]["Content-Type"] == "image/png", url

    def test_a_cold_burst_reads_the_tree_once_and_each_blob_once(self, stack):
        # Before the fix every request resolved the page from scratch: a commit, a recursive
        # tree and the whole HTML blob, PER IMAGE. A cold load of this page was 24 GitHub calls
        # before one image could even be looked up.
        app, src = stack
        before = dict(src.counts)
        paths = ["/"] + list(ALL_IMAGES)
        load_concurrently(app, paths)
        assert src.counts["tree"] - before["tree"] == 1
        assert src.counts["blob"] - before["blob"] == 1 + len(ALL_IMAGES)
        # The commit is still read on EVERY request. That is what keeps a push visible at once,
        # and it is the one call per request this fix keeps on purpose.
        assert src.counts["commit"] - before["commit"] == len(paths)

    def test_a_second_load_of_the_same_commit_reads_no_tree_and_no_blob(self, stack):
        app, src = stack
        paths = ["/"] + list(ALL_IMAGES)
        load_concurrently(app, paths)
        before = dict(src.counts)
        for path in paths:
            cap, _ = call(app, HOST, path)
            assert cap["status"].startswith("200"), (path, cap["status"])
        assert (src.counts["tree"], src.counts["blob"]) == (before["tree"], before["blob"])

    def test_a_push_is_visible_on_the_next_request(self, stack):
        # The resolution is cached per COMMIT, never per hostname alone, so a new commit is a
        # new resolution and nobody waits for a timer to see their edit.
        app, src = stack
        first = f"/{FOLDER}/{NAMES[0]}.png"
        cap, body = call(app, HOST, first)
        assert body == IMAGES[first]
        changed = dict(ALL_IMAGES, **{first: png("changed")})
        src._trees[(REPO, COMMIT2)] = FakeGitHub(
            trees={(REPO, COMMIT2): tree_for(PAGE, changed)})._trees[(REPO, COMMIT2)]
        src._blobs.update(blobs_for(PAGE, changed))
        src._commits[(REPO, "HEAD")] = COMMIT2
        cap, body = call(app, HOST, first)
        assert cap["status"].startswith("200"), cap["status"]
        assert body == png("changed")


class TestTheAllowlistHolds:
    """These pass WITHOUT the fix too, because before it every path was a 404. That is inherent
    to a negative test: they pin the security property, and `TestEveryImageServes` is what shows
    the feature exists. Neither class is redundant, so do not delete either as a duplicate."""

    @pytest.mark.parametrize("label", sorted(FORBIDDEN))
    def test_a_path_the_page_does_not_reference_as_an_image_is_404(self, stack, label):
        app, src = stack
        load_concurrently(app, ["/"] + list(ALL_IMAGES))
        repo_path, url = FORBIDDEN[label]
        cap, _ = call(app, HOST, url)
        assert cap["status"].startswith("404"), (label, cap["status"])
        if repo_path == DOC:
            return                  # the page's own blob IS fetched, legitimately, for `/`
        data = ("forbidden " + label).encode()
        assert git_blob_id(data) not in src.blob_ids, (
            "%s: the refused file's bytes were fetched from GitHub" % label)

    @pytest.mark.parametrize("path", [
        "/" + FOLDER + "/../../secret.png", "/missing.png", "/" + FOLDER + "/",
        "/" + FOLDER, "/assets//x.png"])
    def test_traversal_and_absent_paths_are_404(self, stack, path):
        app, _ = stack
        cap, _ = call(app, HOST, path)
        assert cap["status"].startswith("404"), (path, cap["status"])


class TestEveryAllowedImageTypeRenders:
    def test_every_allowed_suffix_is_served_as_an_image(self):
        # Review finding 2: the allowlist admitted `.gif`, `.avif` and `.ico`, and the content
        # type table had none of them, so those images were served as
        # `application/octet-stream` under `nosniff` — which a browser refuses to render. The
        # two tables live in different modules, so this test is what keeps them agreeing.
        from harness.convention import _reference_reader
        from harness.manifest import content_type_for
        wrong = {suffix: content_type_for("/x" + suffix)
                 for suffix in sorted(_reference_reader().ASSET_SUFFIXES)
                 if not content_type_for("/x" + suffix).startswith("image/")}
        assert not wrong, wrong


class FullVolumeCache(BlobCache):
    """A cache volume with no space left. `put` fails the way the real disk fails it."""

    def _write_bytes(self, target, data):
        raise OSError(28, "No space left on device")


class TestAFullCacheVolumeStillServes:
    def test_the_page_and_its_images_serve_when_nothing_can_be_cached(self, tmp_path):
        # Review finding 1: `BlobCache.get_or_fetch` treats a failed cache write as a warming
        # problem and serves the bytes in hand (Step 11 finding F2). The resolver's own write did
        # not, so a full volume turned every convention page into a 500 — and because the write
        # ran before the page was remembered, every retry re-read the whole tree.
        reg = Registry(str(tmp_path / "r.db")); reg.initialize()
        cache = FullVolumeCache(str(tmp_path / "c"), max_bytes=10_000_000); cache.initialize()
        src = SlowSource(trees={(REPO, COMMIT): tree_for(PAGE, ALL_IMAGES)},
                         blobs=blobs_for(PAGE, ALL_IMAGES),
                         commits={(REPO, "HEAD"): COMMIT}, repos=["rawgentic"])
        app = make_app(cfg=CFG, registry=reg, cache=cache, source=src)
        _wait_until_index_is_warm(app)
        try:
            before = dict(src.counts)
            results = load_concurrently(app, ["/"] + list(ALL_IMAGES))
            for path, (cap, body) in results.items():
                assert cap["status"].startswith("200"), (path, cap["status"])
                assert body == (PAGE if path == "/" else ALL_IMAGES[path]), path
            # Still resolved once. Nothing could be cached, so `serve` fetches each blob again,
            # which is the cost of a full volume and not a defect of this path.
            assert src.counts["tree"] - before["tree"] == 1
        finally:
            reg.close(); cache.close()


class TestTransientFailuresAreNever404:
    """A rate limit or a spent budget says nothing about whether the file exists. Answering 404
    for one tells a reader their image is gone when it is not, so it is a 503 that says when to
    come back."""

    @pytest.mark.parametrize("error", [
        RateLimited("GitHub rate limit is exhausted (403)"),
        DeadlineExceeded("deadline"),
        BudgetExhausted("budget")], ids=["rate-limited", "deadline", "budget"])
    @pytest.mark.parametrize("where", ["commit", "image blob"])
    def test_it_is_a_503_with_retry_after(self, stack, error, where):
        app, src = stack
        url = f"/{FOLDER}/{NAMES[0]}.png"
        if where == "commit":
            src._errors[(REPO, "HEAD")] = error
        else:
            call(app, HOST, "/")                      # the page itself resolves cleanly
            src._errors[(REPO, git_blob_id(IMAGES[url]))] = error
        cap, _ = call(app, HOST, url)
        assert cap["status"].startswith("503"), cap["status"]
        assert int(cap["headers"]["Retry-After"]) > 0
