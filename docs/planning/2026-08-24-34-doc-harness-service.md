# Design — doc-harness service (issue #34)

Epic #38, child 1 of 4. Implements the confirmed spec
`docs/planning/2026-08-23-github-doc-harness-spec.md`.

Scope of THIS child: the harness service, runnable and testable locally with no Cloudflare
dependency. Cloudflare (#35), `publish_doc.py` changes (#36) and migration (#37) are out.

Author: claude-opus-5. **Revision 3.** This document has been through the Step 4 design gate
twice. Pass 1 returned 13 findings and pass 2 returned 12, from two independent reviewers plus my
own self-review each time. Every one was adopted; three were dissolved as duplicates of a
higher-severity twin. The two change tables at the end — [What revision 2
changed](#what-revision-2-changed) and [What revision 3 changed](#what-revision-3-changed) — name
the finding that forced each change. Two of revision 2's claims were **falsified by a live probe**
and are corrected here rather than quietly dropped.

## Approaches considered

### A1 — framework-free WSGI core, bounded server in the container

The application is a plain WSGI callable (PEP 3333) with **no framework and no dependency**.
Every test invokes that callable directly — no socket, no thread, no Docker. Only the container
entry point imports a server: `waitress`, pinned, which supplies bounded worker concurrency and
mature HTTP parsing. `sqlite3` in WAL mode for the registry. A content-addressed blob cache on
disk with LRU eviction tracked in its own SQLite file on the cache volume.

- **Pros.** The test gate stays dependency-free, because no test imports the server. Serving is
  a dictionary lookup and a file read, so a framework buys nothing. Concurrency is bounded by a
  configured worker count rather than unbounded. PEP 3333 is the stdlib interface and `wsgiref`
  is in the standard library, so this satisfies the spec's "Python, stdlib-style HTTP service".
- **Cons.** Adds the repository's first runtime dependency, confined to one file and one image.
  Routing, bearer checking and conditional requests are still ordinary Python code to write.
- **Effort.** Large but flat: roughly 1,500–1,900 lines across ~11 files, plus tests.
- **Risk.** Low-medium. `waitress` 3.0.2 is pure Python with **zero transitive dependencies**
  (measured; see the platform block), which is about as small a supply-chain addition as exists.

### A2 — stdlib `http.server.ThreadingHTTPServer`

This was revision 1's selection. It is recorded here because it was refuted, not merely passed
over.

- **Pros.** No runtime dependency at all.
- **Cons.** `ThreadingHTTPServer` spawns one thread per connection with no bound, and the stdlib
  documents `http.server` as not recommended for production. Three independent passes refuted
  it: the peer consult, the adversarial review (A2, High, confidence 0.93) and my own
  self-review (S4). The adversarial reviewer's specific objection is the decisive one — the
  safety argument for A2 rests on cloudflared and Access behavior that issue #34 *explicitly
  excludes from its own scope*, so #34 would be shipping a service whose safety it cannot
  demonstrate.
- **Risk.** Medium-high, and the risk sits in the part #34 cannot test.

### A3 — ASGI framework (FastAPI + uvicorn)

- **Pros.** Routing, validation and JSON handling for free.
- **Cons.** Pulls FastAPI, uvicorn, pydantic and their transitive tree for five routes and one
  bearer check. Pydantic models would duplicate a manifest contract the publisher already owns.
- **Risk.** Medium organizationally. Rejected on proportionality.

### A4 — materialize every page to disk at publish time, serve statically

- **Cons.** Deletes the failure split F8 exists to specify: with no read-time fetch there is no
  dead-SHA-versus-outage distinction to make. The disposable volume stops being disposable, which
  contradicts D4. Publish latency becomes proportional to total page size.
- **Risk.** High against the spec: it silently changes the durability model.

## Selected approach: A1

A1 is chosen. A4 is rejected because it changes the durability model the owner decided in D4.
A3 is rejected on proportionality. A2 is rejected because its safety case depends on a sibling
issue's work that this issue excludes.

The tension A2 existed to avoid — "do not add a dependency" — is resolved rather than traded
away, because the dependency does not reach the code under test. `harness/app.py` is a plain
WSGI callable that imports nothing outside the standard library. `harness/__main__.py` is the
only file that imports `waitress`, and no test imports `harness.__main__`.

## Concurrency model

*(New in revision 2. Finding A5: the separate HTTP and SQLite probes did not prove the combined
threaded call shape, and connection ownership was undefined.)*

- **One process. Multiple threads.** `waitress` is configured with a fixed `threads` count
  (`DOC_HARNESS_THREADS`, default 8). That number IS the concurrency bound. There is no path by
  which the service creates an unbounded number of workers.
- **Slow clients are bounded too** *(finding S9)*. `channel_timeout` and `connection_limit` are
  set explicitly (`DOC_HARNESS_CHANNEL_TIMEOUT` 60 s, `DOC_HARNESS_CONNECTION_LIMIT` 100) rather
  than inherited, so the bound is a decision somebody made and can be read off the config table.
- **Publishes cannot starve serving** *(finding B3)*. A semaphore admits at most
  `DOC_HARNESS_MAX_CONCURRENT_PUBLISHES` (default 2, and start-up refuses a value not at least
  two below `DOC_HARNESS_THREADS`) concurrent publishes, so serving workers always remain. A
  publish that cannot get a slot returns **429** with `Retry-After`, never a queue that ties up a
  thread.
- **Running two harness processes against one cache volume is UNSUPPORTED and is enforced, not
  merely documented.** At start-up the process takes an exclusive `flock` on
  `<cache dir>/.harness.lock` and refuses to start if it cannot, naming the held lock. The
  compose file declares a single replica. The cache's in-process lock and single-flight map are
  correct only under that invariant, so the invariant is checked rather than assumed.
- **SQLite connection ownership is one connection per thread**, held in a `threading.local`,
  opened lazily and closed at thread exit. Connections are never shared across threads and never
  passed as arguments. Every connection is opened with the same pragmas, applied at open time:
  `journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=5000`, `synchronous=FULL` on the durable
  registry and `synchronous=NORMAL` on the disposable cache index.
- **Every write path uses `BEGIN IMMEDIATE`.** A `sqlite3.OperationalError` naming a lock
  becomes HTTP 503 with a `Retry-After`, never a 500 and never a silent retry loop.
- **GitHub I/O never happens inside a write transaction.** Publish validation fetches and
  verifies everything first, then opens a short transaction that touches only SQLite. This keeps
  the write lock held for milliseconds regardless of manifest size.
- The tests exercise this for real: a concurrency test drives two barrier-synchronized publishers
  of the same name through the real threaded path and asserts exactly one wins with a 409 for the
  other.

## Module layout

```
harness/
  __init__.py
  __main__.py        # THE ONLY file that imports waitress. Reads config, takes the cache lock, serves app.
  app.py             # the WSGI callable. Zero non-stdlib imports. Every test targets this.
  config.py          # env parsing into one frozen dataclass; all defaults in one place
  registry.py        # SQLite: schema, seal, CAS, history, generation counter
  manifest.py        # manifest parsing + validation (pure, no I/O)
  github.py          # GitHubSource Protocol + the real urllib client (trees AND blobs)
  cache.py           # content-addressed LRU blob cache, leases, single-flight, reconciliation
  routing.py         # Host canonicalization, zone allowlist, path canonicalization
  control.py         # POST /v1/deployments, GET /v1/deployments/<name>
  serving.py         # page/asset serving, failure classification, response headers
  indexpage.py       # server-side index render, reusing index/build_index.py
  requirements.txt   # waitress==3.0.2 — the container installs this; the test gate never does
Dockerfile
compose.yaml
```

## The import seam for `index/build_index.py` (AC 4)

**Decision: load it by path with `importlib`, from `harness/indexpage.py`. Do not make `index/`
a package, and do not copy the code.**

Measured at `0021355a`: `index/` has no `__init__.py`, and `scripts/tests/test_build_index.py`
already loads the module with `importlib.util.spec_from_file_location`. Adding `index/__init__.py`
would create a top-level package with about as collision-prone a name as exists on `sys.path`, and
would change how pytest sees a directory that 53 existing test files depend on. The peer consult
recommended adding it; that recommendation is declined for this child, with the reason recorded
here — extraction into a properly named shared module is the right long-term shape and it is a
refactor #34 does not need.

**Probed, not assumed.** Loading the module by path and calling `signature(rows)` then
`render(rows, stamp, now, sig)` on hand-built registry-shaped rows returns 14,532 bytes of HTML
containing the row title, with no import-time side effect.

**One additive change to `index/build_index.py`.** `render()` hardcodes the eyebrow
`"vercel · living documentation"`. Add a keyword-only `eyebrow: str | None = None` defaulting to
today's exact string, so every existing caller and test is unaffected, and the harness passes
`"3dstories · living documentation"`. That is the only edit #34 makes outside `harness/`.

`build_rows()` is NOT reused — it is Vercel-shaped and fetches page titles over HTTP with a
thread pool. The registry already holds the title, so the harness builds
`{name, url, title, group, chip, updated, updated_src}` rows itself and calls `classify()` and
`group_colors()` for the group and chip.

## Registry schema and the compare-and-swap (AC 2, AC 3)

```sql
CREATE TABLE deployment (
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
CREATE INDEX deployment_by_name ON deployment(name, id DESC);

CREATE TABLE asset (
  deployment_id INTEGER NOT NULL REFERENCES deployment(id),
  url_path      TEXT NOT NULL,
  repo_path     TEXT NOT NULL,
  blob_id       TEXT NOT NULL,
  size          INTEGER NOT NULL,
  sha256        TEXT NOT NULL,
  content_type  TEXT NOT NULL,
  PRIMARY KEY (deployment_id, url_path)
);

CREATE TABLE active (
  name          TEXT PRIMARY KEY,
  deployment_id INTEGER NOT NULL REFERENCES deployment(id)
);
CREATE TABLE registry_meta (k TEXT PRIMARY KEY, v INTEGER NOT NULL);
INSERT INTO registry_meta(k, v) VALUES ('generation', 0), ('generated_at', 0);
```

Two changes from revision 1, both from the peer consult. Assets are **normalized into their own
table with `url_path` as part of the primary key**, so lookup is an exact indexed read rather
than a JSON scan, and a duplicate `url_path` is refused by the database. And `sealed` makes
immutability **database-enforced**, so "immutable" stops being a convention the application must
remember.

**`content_type` is derived server-side, not declared** *(finding S7)*. The confirmed spec's
manifest contract is exactly `{url_path, repo_path, blob_id, size, sha256}`. Taking a content
type from the publisher would silently widen the contract that #36 must satisfy, and #36 has not
been written yet, so the widening would surface there instead of here. The column is populated by
`manifest.py` from the `url_path` extension against a conservative allowlist — `html`, `css`,
`js`, `svg`, `png`, `jpg`/`jpeg`, `webp`, `woff2`, `json`, `txt` — defaulting to
`application/octet-stream`. `X-Content-Type-Options: nosniff` ships on every response regardless.

```sql
CREATE TRIGGER deployment_sealed_no_update BEFORE UPDATE ON deployment
  WHEN OLD.sealed = 1 BEGIN SELECT RAISE(ABORT, 'deployment is sealed'); END;
CREATE TRIGGER deployment_sealed_no_delete BEFORE DELETE ON deployment
  WHEN OLD.sealed = 1 BEGIN SELECT RAISE(ABORT, 'deployment is sealed'); END;

-- The asset rows are where the served bytes are actually described, so sealing the parent
-- row alone leaves the immutability claim false (finding B2, and independently S8). All
-- THREE mutations are covered: without the INSERT trigger a sealed deployment could still
-- gain a new url_path, which changes what it serves just as effectively as an UPDATE.
CREATE TRIGGER asset_sealed_no_insert BEFORE INSERT ON asset
  WHEN (SELECT sealed FROM deployment WHERE id = NEW.deployment_id) = 1
  BEGIN SELECT RAISE(ABORT, 'deployment is sealed'); END;
-- The UPDATE trigger must also refuse a REPARENT (finding C7). Checking only the OLD parent
-- leaves a hole: an asset on an UNSEALED deployment can be moved into a sealed one by
-- updating deployment_id, which adds a served path to the supposedly immutable target
-- without ever firing the INSERT trigger.
CREATE TRIGGER asset_sealed_no_update BEFORE UPDATE ON asset
  WHEN (SELECT sealed FROM deployment WHERE id = OLD.deployment_id) = 1
    OR (SELECT sealed FROM deployment WHERE id = NEW.deployment_id) = 1
    OR NEW.deployment_id <> OLD.deployment_id
  BEGIN SELECT RAISE(ABORT, 'deployment is sealed'); END;
CREATE TRIGGER asset_sealed_no_delete BEFORE DELETE ON asset
  WHEN (SELECT sealed FROM deployment WHERE id = OLD.deployment_id) = 1
  BEGIN SELECT RAISE(ABORT, 'deployment is sealed'); END;
```

This is why step 2 of the swap below seals **after** the asset rows are inserted: sealing first
would make the deployment's own asset insert fail its own trigger.

**The swap**, inside one `BEGIN IMMEDIATE`, after all GitHub verification has already passed:

1. Insert the `deployment` row and its `asset` rows.
2. `UPDATE deployment SET sealed = 1 WHERE id = ?` — from here the row cannot change.
3. The CAS:
   - `expected_active` null (first publish):
     `INSERT OR IGNORE INTO active(name, deployment_id) VALUES (?, ?)`. `rowcount == 0` means a
     row already exists, so this publisher is stale → **409**, and the transaction rolls back so
     the candidate deployment leaves no orphan.
   - `expected_active` an id:
     `UPDATE active SET deployment_id=? WHERE name=? AND deployment_id=?`. `rowcount == 0` means
     the pointer moved → **409**, same rollback.
4. `UPDATE registry_meta SET v = v + 1 WHERE k = 'generation'` — **and assert `rowcount == 1`**.
   *(Finding A4. SQLite executes this happily against zero rows if the singleton meta row is
   missing, which would commit the swap without advancing the ETag and leave every client holding
   a stale index with nothing surfaced.)* `rowcount != 1` rolls the whole transaction back, logs
   an alert containing no secrets, and returns **500**. Start-up also validates that both
   `registry_meta` rows exist before serving a single request.
5. `UPDATE registry_meta SET v = ? WHERE k = 'generated_at'` with the current epoch, same
   assertion. See the index section for why the timestamp is stored with the generation.
6. Commit.

The 409 body names the caller's current active id, so a stale publisher can retry correctly
without a second round trip.

## Publish-time verification (AC 3)

The control handler does not trust the publisher's manifest.

**Tree resolution walks path components with non-recursive Tree API calls, memoizing each tree
for the request.** *(Finding A6 flagged that this call was load-bearing with no spike and no
client seam. The peer consult independently recommended the non-recursive walk.)* Two reasons,
and the second is the stronger one:

1. `?recursive=1` truncates. GitHub sets `truncated: true` past its response limit and returns a
   partial tree, which a naive implementation reads as "path absent". Measured today the two
   real doc repos do **not** truncate (`design-doc-publish` 199 entries, `rawgentic` 2,398, both
   `truncated=false`), so this is a latent failure rather than a present one — but it is
   silent when it arrives, and it arrives as a repo grows.
2. The component walk yields each entry's **`type` and `mode`**, which is how symlinks and
   submodules are rejected by name rather than by hope.

Per declared asset:

- Every path component must resolve, and the final entry must be `type: blob` with
  `mode: 100644` or `100755`. **`mode 120000` (symlink) and `mode 160000` (gitlink/submodule) are
  refused with a named reason**, as the spec's "Later" list requires; a `tree` where a blob was
  declared is refused too.
- The entry's `sha` must equal the declared `blob_id`, and its `size` the declared `size`.
- The fetched bytes must hash to the declared `sha256`, **and their recomputed Git blob SHA-1
  must equal `blob_id`** — the peer's point: verifying only the publisher-declared SHA-256 leaves
  the lookup key itself unverified.
- The fetched byte count must not exceed `DOC_HARNESS_MAX_BLOB_BYTES` *(finding S1 — the spec
  names a publish-time size cap under "Do now" and revision 1 omitted it)*.

**`entry_path` is validated too, before any fetch** *(finding B7)*. It must canonicalize to
itself under the SAME routine routing uses, and exactly one declared asset's `url_path` must
equal it. Without this a manifest passes every per-asset check and activates while `/` resolves
to a declared-path miss — a brand-new deployment whose front page is 404.

Any mismatch refuses the whole deployment with **422** and a diagnostic naming the first
offending path and what differed. An unauthorized, rate-limited, malformed or incomplete tree
response is NOT a manifest error and does not return 422: it is **502**, with a distinct log
line, because blaming the publisher for an upstream failure sends the wrong person to debug it.

**Verified bytes are STAGED, and enter the cache only after the CAS commits** *(finding B5)*.
Fetched blobs are written under `<cache dir>/staging/<publish id>/` and are NOT counted in the
LRU and NOT eligible for eviction while the publish is in flight. On commit they are moved into
the cache with the normal insert ordering; on a 409 or any refusal the whole staging directory
is deleted. Admitting before the CAS would let a *losing* publisher evict the active
deployment's warm blobs on its way to being rejected, turning healthy reads into
GitHub-dependent misses during exactly the window when a retry storm is likeliest. A publish
that commits has therefore warmed the cache for every asset, deliberately: the first reader
never pays a cold miss on a fresh publish.

**Publish-request bounds**, all refused before any fetch begins:

| bound | env | default |
|---|---|---|
| control request body | `DOC_HARNESS_MAX_BODY_BYTES` | 1 MiB |
| declared assets per deployment | `DOC_HARNESS_MAX_ASSETS` | 200 |
| single blob | `DOC_HARNESS_MAX_BLOB_BYTES` | 100 MiB (the Blob API ceiling) |
| total bytes fetched per publish | `DOC_HARNESS_MAX_PUBLISH_BYTES` | 256 MiB |
| per-request GitHub timeout | `DOC_HARNESS_HTTP_TIMEOUT` | 20 s |
| **end-to-end publish deadline** | `DOC_HARNESS_PUBLISH_DEADLINE` | 120 s |
| **GitHub calls per publish** | `DOC_HARNESS_MAX_GITHUB_CALLS` | 300 |
| **concurrent publishes** | `DOC_HARNESS_MAX_CONCURRENT_PUBLISHES` | 2 |

**Why the last three exist** *(finding B3, High)*. Per-call bounds alone do not bound the
operation. 200 assets at a 20-second per-call timeout is roughly 4,000 seconds of one worker,
and eight such publishes would occupy every thread and take serving down while every listed
per-call limit was still being honored. So the publish carries a **monotonic end-to-end
deadline**, a **hard cap on total GitHub calls** (tree walks included), and the concurrency
semaphore from the concurrency model. Exceeding either aborts the publish with **504** and
changes nothing.

**The deadline is enforced DURING each call, not merely before it** *(finding C2)*. Checking only
at the top of the loop bounds the number of calls, not the time: one call started at 119 seconds
can run for another 20, and a response that trickles bytes indefinitely holds the worker for as
long as it keeps trickling. So `github.py` derives a per-call socket timeout from the
**remaining** deadline (`min(DOC_HARNESS_HTTP_TIMEOUT, remaining)`), and the streaming body read
re-checks the remaining deadline **on every chunk**, closing the response and raising at expiry.
A slow-trickle regression test proves the whole publish ends inside the deadline, not merely that
each individual call does.

**The body bounds are what waitress actually does, measured — not what I first assumed.**
*(Finding S2 asked for the bound; finding B4 correctly objected that the exact behavior was
unverified. It was probed on a raw socket and two of revision 2's claims were wrong.)* waitress
is configured with `max_request_body_size = DOC_HARNESS_MAX_BODY_BYTES`, and then:

| request | who answers | status |
|---|---|---|
| `Content-Length` within the cap | the app | 200 |
| `Content-Length` over the cap | **waitress, before the app is entered at all** | 413 |
| `Content-Length` absent | the app (`CONTENT_LENGTH` is `None`) | **411** |
| `Content-Length` malformed | **waitress, before the app** | **400**, not 411 |
| `Transfer-Encoding: chunked` | **waitress de-chunks it** and hands the app a plain `CONTENT_LENGTH` with the header stripped | 200, bounded by the same cap |

The last two rows are corrections. Revision 2 said an unparseable length would be 411 — waitress
answers 400 first. Revision 2 also said a chunked body would be "refused outright" — the
application cannot refuse what it cannot see, and it does not need to, because waitress has
already applied the same byte bound. Do not write app code to reject chunked requests: it would
be dead code that reads as a security control.

## Routing and serving (AC 1, AC 5)

**Host handling — the zone is an allowlist, checked first.** *(Finding A1, High, confidence 0.98,
and independently my own S3. Revision 1 took the leftmost label with no zone check, so
`docs-control.evil.example` reached the control router.)*

Lowercase the `Host`, strip an optional port, and then require:

1. the host ends with `"." + DOC_HARNESS_ZONE`, and
2. the remaining prefix is exactly ONE non-empty DNS label — no dots, no empty labels.

Anything else is 404 with a plain-text diagnostic, before any registry lookup.
Forwarded headers (`X-Forwarded-Host` and friends) are **never** consulted. Probed against
`docs-control.evil.example`, `a.b.3dstories.ca` and the bare zone — all three 404.

`docs-control` and `docs-index` are reserved names; control routes exist only on the control host
and 404 everywhere else.

**Path handling.** Decode once, canonicalize once, then require an exact `asset.url_path` match.
Reject any path that is not already canonical, any `.` or `..` segment, any backslash, and any
NUL. `/` maps to the deployment's `entry_path`. **There is no traversal surface**, because no
filesystem path is ever derived from request input: the asset table is the allowlist and the
cache is addressed by blob id.

**Methods and conditionals.** `GET` and `HEAD` only; everything else is 405 with `Allow`. The
strong `ETag` is the asset's `sha256`, so `If-None-Match` returns 304 without touching the cache.
No ranges, no compression, no directory indexes, no fallback files, and no HTML rewriting of any
kind.

Response headers: `X-Doc-Deployment: <id>`, `Content-Type` from the manifest,
`Content-Length`, `ETag`, `X-Content-Type-Options: nosniff`, and `X-Doc-Origin: fetch | cache`.
`?__deployment=<id>` is compared against the active id (409 when stale) and stripped before
lookup.

**Failure classification (AC 5).** Revision 1's table was internally incoherent and the peer
consult caught it: it promised an alert on a warm hit after a dead SHA, but a warm hit never
contacts GitHub, so the service cannot know the SHA died. Corrected — the split is on **what an
attempted fetch returned**, and a warm hit is simply a hit:

| situation | response |
|---|---|
| cache hit | 200, `X-Doc-Origin: cache`. No GitHub call, so no classification to make. |
| miss, fetch 404 (dead SHA) | 503, plain-text diagnostic **naming the dead blob SHA**. Never cached. |
| miss, fetch times out / 5xx / network error | 503, generic plain-text diagnostic; the detail goes to the structured log, not the response. |
| miss, fetch 401/403 | 503, and a **distinct** token-or-rate-limit alert log line — never the dead-SHA diagnostic. `x-ratelimit-remaining: 0` distinguishes rate limit from auth. |
| fetch succeeded, hash mismatch | 502. Purge any suspect cache entry. Never cached, never served. |
| a concurrent request populated the cache while this fetch was failing | 200 from cache, `X-Doc-Origin: cache`, **plus** an alert line — this is the only warm path that alerts, and it alerts because a fetch really did fail. |
| unknown host, or host outside the zone | 404, plain text |
| declared-path miss | 404, plain text |

## Blob cache (AC 1)

Content-addressed by `blob_id`, two-level fanout (`ab/abcdef…`), on the disposable volume.
Bound `DOC_HARNESS_CACHE_MAX_BYTES`, default 2 GiB. The LRU index is a separate SQLite file **on
the cache volume**, so index and bytes are lost together:

```sql
CREATE TABLE blob (blob_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL,
                   size INTEGER NOT NULL, last_access INTEGER NOT NULL);
```

**Cache-hit invariant** *(finding B6)*. The cache is keyed by `blob_id`, but each deployment
declares its own `sha256` and `size`, so the key alone does not prove the entry is the right
bytes for THIS asset. Before a hit is used, the row's `sha256` and `size` must equal the
requesting asset's. On mismatch the entry is purged and refetched. If the refetched bytes
reproduce the conflict, the request is **502** with a structured alert and **neither** version is
served — a disagreement about what a blob id means is not something to resolve by guessing.
Without this rule the dual-hash check is defeated at the moment it matters, because the response
would carry the requesting deployment's `ETag` and `Content-Length` over some other deployment's
bytes.

**Consistency protocol.** *(Finding A3: co-locating index and bytes makes whole-volume loss
consistent but does not make a filesystem write and a SQLite write atomic. Every crash window
below is named and has a defined recovery.)*

- **Insert order:** stream to `<dir>/tmp/<uuid>` while hashing → verify SHA-256 → `os.replace()`
  into the final path → *then* insert the `blob` row. A crash between the rename and the insert
  leaves an orphan FILE, which start-up reconciliation deletes.
- **Evict order:** delete the `blob` row → *then* `os.unlink()` the file. A crash between them
  leaves an orphan FILE again, never a row pointing at nothing.
- **A missing file is always a recoverable cache MISS, never an error.** Any `open()` that raises
  `FileNotFoundError` deletes the stale row and refetches. This is the invariant that makes every
  crash window above harmless.
- **Start-up reconciliation:** after taking the exclusive process lock and **before** the listener
  accepts a connection: delete everything under `tmp/`, **delete every directory under
  `staging/`**, delete rows whose file is absent, delete files with no row, then recompute the
  total and evict down to the bound. If reconciliation cannot complete, **fail start-up** rather
  than serve from an unaccounted cache.
  *(Finding C1. Revision 3 introduced `staging/` and did not add it here. Staged bytes are
  outside LRU accounting by design, so a crash or kill mid-publish orphans up to
  `DOC_HARNESS_MAX_PUBLISH_BYTES` — 256 MiB — per interrupted publish, invisibly, until the volume
  fills and both publishing and caching break. This is a defect revision 3 created while fixing
  B5.)*
- **Eviction never races a reader.** A reader takes a *lease*: it `open()`s the file and holds the
  descriptor for the whole response. Eviction only unlinks. On POSIX the directory entry goes but
  the inode survives while any descriptor is open, so the reader streams to completion from a
  file that no longer has a name. Nothing waits and nothing truncates.
- **Single-flight:** concurrent misses on the same `blob_id` share one in-flight fetch through a
  per-key event map under the cache lock, so a burst of ten requests for a cold page makes one
  GitHub call.
- Capacity is **reserved before the download starts**, so a large fetch cannot overshoot the
  bound mid-flight. A single blob larger than the whole bound is streamed through without being
  cached, rather than evicting everything to fail anyway.
- **Verification on write, not on every read.** The peer consult argued for re-hashing the cached
  file before every response. Declined, with the reason recorded: content-addressed entries are
  written only after verification and the store is not shared or writable by anything else, so
  re-hashing a 100 MB file on every request buys a trusted-storage guarantee this threat model
  does not need. Revisit if the cache volume ever becomes shared.

## Index host (AC 4)

One SQLite snapshot reads the active deployments and both `registry_meta` values, builds rows,
and calls the reused `render()`. The rendered body is cached in memory keyed by generation.

**The project list for `classify()` comes from the REGISTRY, not from a workspace file**
*(finding S10)*. `classify(name, projects)` needs a list of project names, and in
`build_index.py` that list comes from `known_projects(workspace_file)`, which returns `[]` when
there is no workspace file. The container has no `.rawgentic_workspace.json`, so taking that path
would put every row in the `other` bucket and silently delete the grouping that is most of the
index's value. Instead the harness runs, **exactly**:

```sql
SELECT DISTINCT d.project FROM active a
  JOIN deployment d ON d.id = a.deployment_id
 WHERE d.project IS NOT NULL;
```

then sorts longest-first exactly as `known_projects` does, so a longer project name wins over a
shorter sibling prefix.

*(Finding C3 corrects revision 3, which wrote `SELECT DISTINCT project FROM deployment` — wrong
twice. `project` is nullable, so a NULL would reach a `len()` comparison and raise while rendering
the index. And reading `deployment` rather than `active` includes retired history, so an obsolete
project name could re-classify a live row.)* An active deployment whose `project` is NULL renders
in the `other` group, which is the honest answer rather than a guess.

`group_colors` is called with `workspace_file=None`, whose documented behavior is to degrade to
the name hash. That degradation is fine: a colour is cosmetic and a group is not.

**`generated_at` is stored alongside `generation` and passed as `render()`'s `now`.** *(Peer
consult.)* `render()` emits relative ages ("6h"), so deriving the ETag from the generation alone
while letting `now` follow the wall clock would make the ETag *wrong* — the body would change
while the validator did not. Pinning `now` to the generation's own timestamp makes body and ETag
agree by construction. The accepted cost: server-rendered age labels advance only when the
registry changes. The page's existing client-side `_ago` twin keeps the displayed ages ticking in
the browser, so the visible effect is limited to a client with JavaScript disabled.

`ETag: "gen-<generation>"`, `If-None-Match` honored.

## Configuration

| env var | default | meaning |
|---|---|---|
| `DOC_HARNESS_GITHUB_TOKEN` | — | **required**; fine-grained read-only PAT covering every doc repo |
| `DOC_HARNESS_PUBLISH_TOKEN` | — | **required**; bearer for the control host |
| `DOC_HARNESS_ZONE` | `3dstories.ca` | the allowlisted suffix |
| `DOC_HARNESS_REGISTRY_PATH` | `/var/lib/doc-harness/registry.db` | durable volume |
| `DOC_HARNESS_CACHE_DIR` | `/var/cache/doc-harness` | disposable volume |
| `DOC_HARNESS_CACHE_MAX_BYTES` | `2147483648` | LRU bound |
| `DOC_HARNESS_MAX_BODY_BYTES` | `1048576` | control request body cap |
| `DOC_HARNESS_MAX_BLOB_BYTES` | `104857600` | single-asset cap |
| `DOC_HARNESS_MAX_ASSETS` | `200` | declared assets per deployment |
| `DOC_HARNESS_MAX_PUBLISH_BYTES` | `268435456` | total bytes fetched per publish |
| `DOC_HARNESS_HTTP_TIMEOUT` | `20` | seconds, per GitHub request |
| `DOC_HARNESS_PUBLISH_DEADLINE` | `120` | seconds, end-to-end per publish |
| `DOC_HARNESS_MAX_GITHUB_CALLS` | `300` | tree plus blob calls per publish |
| `DOC_HARNESS_MAX_CONCURRENT_PUBLISHES` | `2` | must be at least 2 below `DOC_HARNESS_THREADS` |
| `DOC_HARNESS_THREADS` | `8` | waitress worker threads — the concurrency bound |
| `DOC_HARNESS_CHANNEL_TIMEOUT` | `60` | seconds, waitress slow-client cutoff |
| `DOC_HARNESS_CONNECTION_LIMIT` | `100` | waitress accepted-connection ceiling |
| `DOC_HARNESS_BIND` | `0.0.0.0:8080` | listen address |
| `DOC_HARNESS_GITHUB_API` | `https://api.github.com` | overridden in tests |

`DOC_HARNESS_MAX_BODY_BYTES` is passed to waitress as `max_request_body_size` as well as being
checked in the app, which is what makes the 413 arrive before the app is entered.

Both required tokens are read at start-up; the process refuses to start without them, naming the
missing variable. Secrets are referenced by NAME everywhere — compose file, tests, this document.

`compose.yaml` declares one `harness` service (single replica), `registry` (durable) and
`blobcache` (disposable) volumes, **no published host ports**, and `restart: unless-stopped`.
The `Dockerfile` installs `harness/requirements.txt` and runs `python3 -m harness`. cloudflared
is #35's to add.

## Testability (AC 6)

Every test is hermetic: no network, no Docker, no GitHub, and **no waitress**.

- `github.py` defines a `GitHubSource` Protocol with **two** methods — `tree(repo, sha)` and
  `blob(repo, blob_id)` — and typed `NotFound`, `Unavailable` and `Unauthorized` errors.
  *(Finding A6: revision 1's one-method `BlobFetcher` had no seam for tree resolution, so the
  publish path could not be tested hermetically at all.)* Tests inject a fake backed by dicts.
- **The WSGI callable is invoked directly** with a constructed `environ`. Probed: host routing,
  the zone allowlist including the `docs-control.evil.example` attack, and the bearer 401 all
  behave identically through a direct call and through a real socket under waitress.
- SQLite runs against `tmp_path`, so WAL, `BEGIN IMMEDIATE` and the seal triggers are exercised
  for real rather than mocked.
- Crash-window tests for each cache boundary: orphan file with no row, row with no file, leftover
  `tmp/` entry — each asserted to reconcile at start-up and to restore the byte bound.
- A barrier-synchronized concurrency test runs two publishers of one name through the real
  threaded path and asserts exactly one 200 and one 409.

**One test does NOT bypass the production server, deliberately** *(finding C5)*. Every bound in
the table above — the pre-application 413, the 400 on a malformed length, chunk decoding, the
channel timeout, the connection limit — is enforced by waitress, configured at the
`harness/__main__.py` call site. A direct-WSGI test cannot see any of them, so a mistyped or
dropped waitress argument would silently remove a load-bearing production bound and every test
would stay green. `tests/harness/test_production_server.py` therefore starts the real
`python3 -m harness` entrypoint and drives it over raw sockets. It **skips** when waitress is not
importable, so the dependency-free gate is preserved, and the skip is visible rather than silent.

Test files under `tests/harness/`: `test_config.py`, `test_routing.py`, `test_manifest.py`,
`test_registry.py`, `test_github.py`, `test_cache.py`, `test_serving.py`, `test_control.py`,
`test_indexpage.py`, `test_app.py`, `test_concurrency.py`, `test_entrypoint.py`,
`test_production_server.py`. The gate `pytest scripts/tests/ tests/ -q` already covers `tests/`.

## Acceptance-criteria mapping

*(Finding C6: the design referenced ACs by number without stating them, so nobody could check
coverage from this document alone.)*

| AC | What it requires (abbreviated from issue #34) | Where this design answers it | Test |
|---|---|---|---|
| 1 | Python HTTP service in a new `harness/` package; Host→registry; manifest files fetched by Git blob id; every blob SHA-256-verified before cache or serve; bounded LRU, 2 GiB default, `DOC_HARNESS_CACHE_MAX_BYTES` | Selected approach; Routing and serving; Blob cache | `test_routing.py`, `test_serving.py`, `test_cache.py` |
| 2 | `POST /v1/deployments`, control host only, immutable record with the named fields; CAS via `expected_active` with 409; bearer `DOC_HARNESS_PUBLISH_TOKEN` | Registry schema and the CAS; Publish-request bounds | `test_registry.py`, `test_control.py` |
| 3 | The server resolves the commit tree itself and refuses activation on a blob or hash mismatch | Publish-time verification | `test_github.py`, `test_control.py` |
| 4 | `docs-index` renders server-side from the registry, reusing `index/build_index.py` presentation code; ETag from a registry generation counter | The import seam; Index host | `test_indexpage.py` |
| 5 | Failure split — blob 404 versus outage; unknown host 404; dot segments and undeclared paths rejected | Routing and serving, failure table | `test_routing.py`, `test_serving.py` |
| 6 | Compose file with the harness container and two volumes; pytest covers CAS, serving and verification; the whole gate is green | Configuration; Testability | `test_entrypoint.py`, `test_production_server.py`, and the full gate |
| 7 | The confirmed spec, markdown plus rendered HTML, committed in this PR under `docs/planning/` | File changes | verified by inspection at Step 9 |

## File changes

**New:** the twelve `harness/` files above, `harness/requirements.txt`, `Dockerfile`,
`compose.yaml`, and ten test files under `tests/harness/`.

**Modified:**

- `index/build_index.py` — one keyword-only `eyebrow` parameter on `render()`, defaulting to the
  current string.
- `docs/planning/2026-08-23-github-doc-harness-spec.md` — committed by this PR (AC 7). **Line 142
  currently reads:**
  `window; Vercel teardown timing is the owner's call. Roughly 37 projects.`
  **Replace it with:**
  `window; Vercel teardown timing is the owner's call. 179 projects as of 2026-08-24, 163 of them carrying a design-doc-publish purpose token.`
  *(Finding A7: revision 1 said "corrected" while quoting only the stale figure, so an implementer
  could not tell what to write.)* The rendered HTML must carry the same number.
- `README.md` — a harness section, and the changelog fragment per the pre-PR checklist.
- `.gitignore` — add `.venv/` *(finding S6)*, plus the local cache and registry paths used when
  running the harness outside Docker.

**Also committed by AC 7:** the rendered HTML of the spec, which does not exist yet — only the
12,110-byte `.md` is on disk.

## Declared scope addition

*(Finding S5. Recorded here and repeated in the PR body rather than shipped quietly.)*

`GET /v1/deployments/<name>` serves **no acceptance criterion of #34**. AC 2 names only the POST.
It exists because **#36 AC 1** says the previous deployment id is read back from the control API
before publishing. Shipping it here is a deliberate epic-dependency addition. The alternative is
#36 reopening #34's control API, which is worse.

**Its contract is normative, because an under-specified endpoint forces exactly the reopening it
was added to avoid** *(finding B1, High)*. #36 has to write a parser against this:

- **Route:** `GET /v1/deployments/<name>` on the control host only. 404 on any other host, like
  every other control route.
- **Auth:** the same `DOC_HARNESS_PUBLISH_TOKEN` bearer as the POST, compared with
  `hmac.compare_digest`. No bearer or a wrong bearer is 401.
- **Name handling:** canonicalized by the same routine routing uses. A name that is not a single
  valid lowercase DNS label is **400**, never 404, so a caller can tell a malformed request from
  an absent deployment.
- **200:** `Content-Type: application/json`, body exactly
  `{"name": "<name>", "active_deployment_id": <integer>, "commit_sha": "<sha>", "published_at": "<ISO 8601 UTC>"}`.
- **No active deployment: 200**, body `{"name": "<name>", "active_deployment_id": null, "commit_sha": null, "published_at": null}`.
  *(Finding C9 corrects revision 3, which said 404 here and then claimed callers would need no
  special case. Those two statements contradict each other: many HTTP clients raise on 4xx or skip
  body parsing entirely, so a 404 forces exactly the special case the contract promised to avoid.
  404 is now reserved for an unknown ROUTE or a non-control host.)* A first publish therefore
  reads `null` and passes it straight back as `expected_active`.
- **Consistency:** read in one snapshot, so `active_deployment_id` and `commit_sha` always
  describe the same deployment.
- A contract test in `tests/harness/test_control.py` pins every row above. #36 re-uses that test
  rather than writing its own guess at the shape.

Roughly 40 lines and one test.

## Error handling and failure modes

- Missing required env var, unwritable registry, missing `registry_meta` row, or an unobtainable
  cache lock → refuse to start, name the cause, exit non-zero. A service that accepts publishes
  and silently loses them is the worst available behavior.
- Malformed manifest → 422 naming the offending field. No partial write.
- `expected_active` mismatch → 409 naming the caller's current active id. Never a silent
  overwrite.
- Upstream tree/blob failure at publish → 502, distinct from the publisher's own 422.
- SQLite lock contention → 503 with `Retry-After`, never a 500.
- Generation counter did not advance → whole swap rolled back, alert, 500.
- Cache volume lost → rebuilds from GitHub on demand, by design.
- Crash mid-cache-write → orphan file, deleted at start-up.

## Security implications

- **Two independent gates on the control host.** Cloudflare Access at the edge (#35) and the
  `DOC_HARNESS_PUBLISH_TOKEN` bearer inside the app. #34 ships the bearer, so it must be correct
  alone: `hmac.compare_digest`, never `==`; never logged, never echoed, never in an error body.
- **The zone allowlist is enforced in #34's own code**, not delegated to #35's proxy config.
  This is the A1 fix and it is the difference between a boundary and an assumption.
- **No path-traversal surface exists by construction** — no filesystem path is derived from
  request input.
- Bytes are hash-verified against both SHA-256 and the Git blob SHA-1 before being cached or
  served, so a confused or compromised upstream response cannot become a served page.
- Symlinks and submodules are refused at publish, so a manifest cannot smuggle a pointer out of
  the repository.
- Every request is bounded: body size, asset count, blob size, total publish bytes, HTTP timeout,
  and worker threads. *(Finding A2 required these to be enforceable numbers, not assurances.)*
- `render()` already escapes its inputs; registry-sourced titles flow through the same escaping,
  and a test pins that a title containing markup is escaped in the rendered index.
- The GitHub PAT is read-only and fine-grained. Both secrets are referenced by name only.
- **Production enablement is conditional on #35 proving network isolation and the exact Access
  policy for every harness host** *(finding A2)*. #34's own bounds hold regardless, which is the
  point of enforcing them here.

## Known limitation carried forward, not fixed here

**Slow-client connection saturation is bounded but not eliminated.** *(Finding C4, High,
DEFERRED with rationale — recorded in `deferrals.json` and re-presented at Step 11.)*

The objection is correct and I am not going to pretend otherwise. `channel_timeout` is an
**inactivity** timeout, not an absolute request deadline. A client that dribbles one byte every
59 seconds resets it forever. With `DOC_HARNESS_CONNECTION_LIMIT` at 100, one hundred such
clients can hold every channel and the harness stops accepting new connections. Neither
`channel_timeout` nor `connection_limit` establishes a total-duration or minimum-throughput
bound, and waitress does not offer one.

Why it is deferred rather than fixed in #34:

1. **Waitress cannot express the fix.** The remedy is an absolute receive deadline plus a
   minimum data rate, which means either a custom reaper thread walking waitress internals, or a
   front proxy. The first is real complexity built against another project's private structures.
2. **The front proxy is #35's whole job**, and Cloudflare terminates slow clients at its edge
   before a byte reaches this service.
3. **The exposure in #34's own scope is nil**: the container publishes no host port and is
   reachable only from cloudflared on the compose network.

What keeps this from being the hand-wave finding A2 rightly attacked: it is written down with the
number attached, it is a **deferred High that Step 11 must re-present**, and it becomes an
explicit, testable prerequisite on #35 rather than an assumption — **#35 must prove that a slow
client is terminated at the edge before reaching the harness.** A2 objected to leaning on #35
silently. This leans on #35 loudly.

## Recorded prerequisite for #37

*(Finding C8, disposed as out of scope for #34 rather than adopted into it.)*

The reviewer is right that `DOC_HARNESS_GITHUB_TOKEN` must read **every** doc repository, and
that the probes here cover only two of them (`design-doc-publish`, public, and `rawgentic`,
private). #34 migrates nothing and publishes nothing, so no repository outside those two is
exercised by this child. The gap is real for **#37**, which touches roughly 179 projects.

Recorded as a prerequisite on #37, and repeated in this PR's body: before #37 activates any row,
enumerate every repository in the migration set and run one exact Trees-plus-Blobs probe per
repository **using the production token identity**. A repository outside the token's scope must
be surfaced as a flagged row, which is what #37 AC 2 already does with a failing compare.

## Platform / external dependencies

```
platform_apis:
- api: GET /repos/{repo}/git/blobs/{sha} with Accept application/vnd.github.raw, on the GitHub REST API
  feasibility: verified via spike — the exact shipped invocation, run 2026-08-24 against
    3D-Stories/design-doc-publish blob 9ac35a3856f485556312e48a4c55b835fd0decd7: rc 0, 17679 bytes,
    sha256 7147f6cd8f0d9b24639247f68d15557d62e380a246aecfe1e2a26a7837611d4e, byte-identical to
    `git cat-file blob` (cmp rc 0). Repeated against the PRIVATE repo 3D-Stories/rawgentic
    (visibility=private) blob 77d446412fdc8e6aa821d3dbea9b5f2152e8f346: rc 0, 1265130 bytes.
  failure: fail-loud
- api: GET /repos/{repo}/git/trees/{sha} non-recursive, walked per path component, on the GitHub REST API
  feasibility: verified via spike — run 2026-08-24, walked docs then planning then
    campaign-log.md from commit 0021355a in 3D-Stories/design-doc-publish. Each step returned the
    entry's type and mode (tree 040000, tree 040000, blob 100644 size 3897) and the final blob sha
    9dd73de4a320bf3d7e38ec583b999715bcd547fa, equal to `git rev-parse`. The mode field is what
    makes the symlink and gitlink refusals above implementable. Truncation measured on the same
    day for context: recursive=1 returned truncated=false at 199 entries for design-doc-publish
    and at 2398 for rawgentic, so truncation is latent rather than present.
  failure: fail-loud
- api: sqlite3 WAL journal mode with BEGIN IMMEDIATE compare-and-swap, on the Python stdlib sqlite3 module
  feasibility: verified via spike — the exact DDL and CAS statements above, Python 3.12.3 /
    SQLite 3.45.1, 2026-08-24. PRAGMA journal_mode=WAL returned 'wal'. First publish with
    expected=None succeeded, a second expected=None was refused, the correct expected=d1
    succeeded, a stale expected=d1 against actual=d2 was refused, the generation counter reached 2
    for two successful swaps, and all 3 history rows were retained.
  failure: fail-loud
- api: PEP 3333 WSGI callable served by waitress.create_server, on waitress 3.0.2
  feasibility: verified via spike — run 2026-08-24. `pip show` reports waitress 3.0.2; the
    installed tree contains 0 compiled extensions and `pip list` shows waitress as the ONLY
    package installed beside pip, so it has zero transitive dependencies. The same WSGI callable
    was exercised twice: invoked DIRECTLY with a constructed environ (no socket), and served by
    waitress.create_server(threads=4) over a real socket. Both agreed on every case, including
    docs-control.evil.example returning 404 and the bearer returning 401 then 200.
  failure: fail-loud
- api: waitress request-body handling with max_request_body_size, on waitress 3.0.2
  feasibility: verified via spike — run 2026-08-24 over RAW SOCKETS against
    waitress.create_server(max_request_body_size=1024), recording what the WSGI app saw in each
    case. Content-Length 4: app entered, CONTENT_LENGTH '4', 200. Content-Length 5000: 413 and
    the app was NEVER entered. Absent Content-Length: app entered with CONTENT_LENGTH None, so
    the 411 is the application's to return. Malformed Content-Length 'abc': 400 from waitress,
    app never entered — NOT the 411 revision 2 claimed. Transfer-Encoding chunked: waitress
    de-chunked it and handed the app CONTENT_LENGTH '4' with the Transfer-Encoding header
    stripped, so the application cannot refuse a chunked body and does not need to.
  failure: fail-loud
- api: POSIX flock exclusion, unlink-while-open, and same-directory os.replace, on the Docker local volume driver
  feasibility: verified via spike — run 2026-08-24 twice. First on the host (ext4). Then INSIDE
    a container (python:3.12-slim) with a real Docker named volume mounted at
    /var/cache/doc-harness on Docker 29.7.2, which /proc/mounts reports as ext4. Both runs: a
    second PROCESS taking LOCK_EX|LOCK_NB raised BlockingIOError while the first held it, and the
    lock was reacquirable after the holder was killed; a reader that opened a 3,000,000-byte file
    and then had it unlinked mid-read still read all 3,000,000 bytes with a matching SHA-256
    while the path was gone; os.replace within one directory swapped the content and removed the
    temp name. The throwaway volume was deleted after the probe.
  failure: fail-loud
- api: importlib.util.spec_from_file_location loading index/build_index.py, then render() and signature()
  feasibility: verified via spike — run 2026-08-24 from the repo root: import fired no side
    effect, render(rows, stamp, now, sig) on hand-built registry-shaped rows returned 14532 bytes
    containing the row title, and signature(rows) returned a stable digest. Confirmed the string
    "vercel · living documentation" IS emitted, which is why the eyebrow parameter is required.
  failure: fail-loud
```

## Multi-PR assessment

The change exceeds 500 lines. **Recommendation: one PR.**

The seven criteria describe one service whose parts do not stand alone: a registry with no
serving path is untestable end to end, and a serving path with no registry has nothing to serve.
Splitting would produce PRs that each pass their own tests while proving nothing about the whole,
and would multiply the merge chain in an epic with three children already queued behind this one.
The one separable piece is AC 7, the spec documents, and separating it would be worse — the spec
is what a reviewer needs in order to review the code.

Reviewability is bought with commit granularity instead: one commit per plan task, each with its
tests green, so the diff reads a layer at a time.

## What revision 2 changed

Every finding below was ADOPTED. None was declined or deferred. Two were dissolved as duplicates
under the documented dedupe rule.

| # | Severity | From | Change made |
|---|---|---|---|
| A1 | High | adversarial | Host must match `DOC_HARNESS_ZONE` exactly, one label, forwarded headers ignored. Probed with the attack case. |
| A2 | High | adversarial | Bounded server (waitress, fixed threads) replaces unbounded `ThreadingHTTPServer`; every request bound is now a named, enforced number; production enablement made conditional on #35. |
| S1 | High | self-review | `DOC_HARNESS_MAX_BLOB_BYTES`, the publish-time size cap the spec named and revision 1 omitted. |
| S2 | High | self-review | `DOC_HARNESS_MAX_BODY_BYTES`, with 413 before read and 411 on an absent length. |
| A3 | Medium | adversarial | Full cache consistency protocol: mutation ordering, missing-file-is-a-miss, start-up reconciliation, crash-window tests. |
| A4 | Medium | adversarial | `rowcount == 1` asserted on the generation UPDATE; whole swap rolls back otherwise; start-up validates the singleton rows. |
| A5 | Medium | adversarial | New "Concurrency model" section: one connection per thread, pragmas, enforced single process, lock-error mapping. |
| A6 | Medium | adversarial | Git Trees spike added to the platform block; `GitHubSource` Protocol gains `tree()`; symlinks and gitlinks refused; upstream failure is 502, not 422. |
| A7 | Medium | adversarial | Spec line 142's exact replacement text is now stated verbatim. |
| S5 | Medium | self-review | `GET /v1/deployments/<name>` declared as an epic-dependency scope addition, in its own section and in the PR body. |
| S6 | Low | self-review | `.venv/` added to `.gitignore`. |
| S3 | Medium | self-review | **Dissolved** — duplicate of A1 (same remedy; A1 is High and carries the attack case). |
| S4 | Medium | self-review | **Dissolved** — duplicate of A2 (same remedy; A2 is High). |

Adopted from the peer consult (gpt-5.6-sol), with provenance: the WSGI-core-plus-bounded-server
shape; the normalized `asset` table and the database-enforced `sealed` immutability; the
memoized non-recursive tree walk; recomputing the Git blob SHA-1 as well as the SHA-256;
cache leases, capacity reservation and single-flight; pinning `generated_at` with the generation
so the index ETag stays truthful; the enforced single-process cache lock.

Declined from the peer consult, with reasons stated where they arise above: adding
`index/__init__.py` (collision-prone top-level name, and it changes collection for 53 existing
test files); re-hashing cached bytes before every response (a trusted-storage guarantee this
threat model does not need).

## What revision 3 changed

Revision 2 went back through the same gate. The second cross-model pass returned 8 findings and
my own second self-review returned 4. All 12 were adopted; one was dissolved as a duplicate.

| # | Severity | From | Change made |
|---|---|---|---|
| B1 | High | adversarial | The read-back endpoint now has a **normative contract** — route, auth, name canonicalization, the exact 200 body, a 404 body carrying `null` so a first publish needs no special case, snapshot consistency, and a contract test #36 reuses. |
| B2 | High | adversarial | Seal triggers extended to `asset` on **INSERT, UPDATE and DELETE**. INSERT matters: without it a sealed deployment could gain a new `url_path`. |
| B3 | High | adversarial | End-to-end publish deadline, a hard cap on GitHub calls per publish, and a publish semaphore kept below the thread count so serving can never be starved. 200 assets × 20 s was ~4,000 s of one worker with every per-call bound honored. |
| B4 | High | adversarial | Probed on raw sockets, and **two of revision 2's claims were wrong**: a malformed `Content-Length` is 400 from waitress, not 411; and a chunked body is de-chunked before the app sees it, so it cannot be, and need not be, refused. `max_request_body_size` is now configured, which is what puts the 413 ahead of the app. |
| B5 | Medium | adversarial | Fetched bytes stay **staged and outside LRU accounting until the CAS commits**, so a losing publisher cannot evict the active deployment's warm blobs on its way to a 409. |
| B6 | Medium | adversarial | Cache-hit invariant: the row's `sha256` and `size` must match the requesting asset's, else purge and refetch, else 502 serving neither. |
| B7 | Medium | adversarial | `entry_path` must canonicalize to itself and match exactly one declared asset, checked before any fetch. Otherwise a valid-looking publish activates with a 404 front page. |
| B8 | Medium | adversarial | Filesystem primitives probed inside a container on a real Docker named volume, not merely asserted from POSIX. |
| S7 | Medium | self-review | `content_type` derived server-side from the extension, so the manifest contract #36 must satisfy is not silently widened. |
| S9 | Low | self-review | `channel_timeout` and `connection_limit` stated explicitly rather than inherited. |
| S10 | Medium | self-review | The index project list comes from `SELECT DISTINCT project FROM deployment`, because the container has no workspace file and every row would otherwise fall into the `other` bucket. |
| S8 | Medium | self-review | **Dissolved** — duplicate of B2, which is High and additionally names INSERT. |

Loop-back accounting: `design` is now 2 of 2 and the global total is 2 of 3.
