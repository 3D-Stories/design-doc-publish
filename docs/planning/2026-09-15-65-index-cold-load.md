# The index stops rebuilding on the reader's request (#65)

Design, 2026-09-15, **revision 4 — final**. Issue:
[#65](https://github.com/3D-Stories/design-doc-publish/issues/65).

`index.3dstories.ca` answers in 93.697s when its 900-second cache has expired and 0.071s when it
has not. The page is identical both times — 301,664 bytes, 616 documents, 61 repositories. The
only variable is whether the snapshot was already in memory.

Expected diff: **~600 inserted lines, over half of them tests.**

## Two decisions taken without the owner

Both were put to the owner with `AskUserQuestion` at the Step-4 gate. No answer arrived in ten
minutes, so each was decided on the evidence, taking the option that is easiest to overturn.

**1. A stale listing is capped at six hours by default.** The adversarial review filed this twice
— revision 2 at confidence 0.90, revision 3 at 0.99, the second time explicitly rejecting an
opt-in bound as no mitigation at all. The concern: stale-while-revalidate means a GitHub outage
leaves the listing — repository names, document paths, titles, dates — visible indefinitely,
including for a repository whose access was revoked. Today an outage returns 503 instead, so this
genuinely removes an existing disclosure bound.

**Decision:** `DOC_HARNESS_INDEX_MAX_STALE_AGE`, **defaulting to `21600` (six hours)**. Past that
age the index answers `IndexTooStale` → 503 until a build succeeds. `0` means no bound and is an
explicit operator opt-in.

**Why six hours and not the reviewer's 900.** The TTL is already 900 seconds, so a bound of 900
makes the stale window exactly zero and a stale snapshot is never served at all — acceptance
criteria 1 and 2 could then never pass, and the whole issue is unfixed. Any working bound must
exceed the TTL. Six hours never fires in normal operation, because a build takes 11 to 53 seconds
measured, so it costs the feature nothing; and it caps disclosure during an outage at six hours
instead of forever. **Undo: set the variable to `0` for unbounded or `900` for today's behavior.**
One environment variable in either direction, no code change.

**2. The first boot on a brand-new cache volume takes ~53 seconds, and that is accepted.** Not
"seconds" — see the measurement below. The alternative both reviewers raised, persisting the whole
assembled listing, was called out of scope by the peer itself and adds roughly 150 lines plus its
own staleness rule. **Decision:** ship the two-phase flattened walk (measured 52.66s against
170.87s) and accept it. A *normal* restart is **11.30s measured**, because the persistent date
store removes the 618 date calls — and a normal restart is what the issue's verification clause
is about. **Undo: none needed; nothing is foreclosed.** Persisting the snapshot is still available
later as a separate change.

## Why it is slow

Four defects, all confirmed in source at `ce583a40`:

1. **A stale cache is rebuilt INLINE, on the reader's request.** `ConventionIndex.snapshot`
   (`harness/convention.py:244-246`) returns the snapshot only while fresh, then falls through to
   the whole walk and returns at `:301`. `harness/app.py:110` waits for it before rendering.
2. **The walk is serial.** `convention.py:248` is a plain `for repo in sorted(...)` loop.
3. **The date cache is in-process only.** `self._dates` (`convention.py:222`) is keyed on the blob
   id, so a refresh only pays for changed files — but it dies with the process.
4. **Nothing refreshes after boot, and nothing guards a refresh.** `app.py:64-77` starts one warm
   thread at boot. `ConventionIndex` holds no lock at all.

The ETag cannot help: the 304 decision is inside `render_index`
(`harness/indexpage.py:105-107`), reached only after `snapshot()` returns.

## Measured, live, inside the running container against the real GitHub account

All on 2026-09-15, through the container's own `HttpGitHub` and the production
`Budget(600s, 3000 calls)`.

| Measurement | Result |
|---|---|
| Listing 61 repositories | 2.33s, one call |
| 4 repositories, serial (`commit` + `tree`) | 5.59s — **1.40s each** |
| 16 repositories, pool of 8 | **3.05s**, peak in-flight exactly 8, per-repository mean 1.10s |
| **Full cold walk, empty date store, one task per repository, pool 8** | **170.87s**, 738 calls, peak in-flight 8, 3 isolated `Unavailable`, zero 403s |
| **Full cold walk, empty date store, TWO-PHASE flattened, pool 8** | **52.66s** — phase 1 (61 × commit+tree) **11.30s**, phase 2 (618 × file_dates) **41.36s** |
| GitHub core rate limit after ~1,500 calls in three bursts | 5000 of 5000, zero secondary limits |

One of those rows is load-bearing and it was not predicted by reasoning:

- **170.87s.** Revision 2 claimed a concurrent walk reaches a serving index in seconds. It does
  not, with one task per repository: the pool parallelizes across repositories, but each
  repository's `file_dates` calls run serially inside its own task, so the largest repository is
  the entire critical path. Flattening the work into two phases through the same pool of 8 cuts it
  **3.2×**, and that remedy was measured before it was adopted, not after.

Phase 1's **11.30s** is the number the issue's verification clause actually asks about: with the
date store populated, a restart pays only phase 1.

## The approach

### a. Stale-while-revalidate

| State | The reader gets | Behind it |
|---|---|---|
| Fresh (`monotonic - at <= ttl`) | the snapshot | nothing |
| Stale, within `max_stale_age` (or unbounded) | **the stale snapshot, immediately** | a background build starts, unless one is running or the cool-off is active |
| Stale, past `max_stale_age` (only when configured) | `IndexTooStale` → **503** | a background build starts |
| Cold, no build running | blocks — this caller leads | one walk |
| Cold, a build already running | `IndexBuilding` → **503 + `Retry-After: 5`** | it does not join the wait |
| Cold, inside the failure cool-off | `IndexCoolingDown` → **503 + `Retry-After: <seconds left>`** | nothing |

**One flag, named `_building`.** It covers the cold build and the background refresh alike. There
is no separate `_refreshing`; revision 2 used both names for one thing, which would have left the
flag permanently set on one path and frozen the index.

**Only the leader blocks.** A second cold caller raises `IndexBuilding`, which `app.py` maps to
503 with an honest message — *"the document listing is still being built; retry shortly"* —
distinct from the existing *"could not be built from GitHub"*. Revision 1 had followers wait. Two
independent reviewers rejected that and they are right: waitress serves with `threads=8`, so
enough blocked index readers occupy every worker and **document** requests, which never touch the
index, stop being served. This repository already encodes exactly that rule at `app.py:43`, where
`publish_slots` exists because "publishing must never be able to occupy every worker".

**The warm-up 503 window is accepted and measured.** Because `app.py:77`'s boot thread is the
leader, every index reader during warm-up gets 503 + `Retry-After`. That window is **11.3s** on a
populated date store and **52.7s** on a fresh volume. It replaces a window in which those readers
would have blocked a worker each.

All three 503 classes subclass `GitHubError`, so if a specific handler in `app.py` were ever
removed the fallback is the existing 503 rather than a 500.

**The TTL is measured on `time.monotonic()`.** The class injects one `now=time.time` today for
both freshness and the reader-visible `generated_at`; a wall-clock step can make an expired
snapshot fresh again. A second injected clock, `monotonic=time.monotonic`, is added for freshness
only. `generated_at` keeps the wall clock, because a human reads it.

**A failed build suppresses the next one for `REFRESH_COOLDOWN = 60.0` seconds**, cold or stale.
Stale readers keep the stale snapshot; cold readers get `IndexCoolingDown` carrying the real
remaining seconds. Without it, a GitHub outage turns every request into a fresh 61-repository walk
attempt. Fixed rather than exponential: the TTL is already 900s, and an exponential schedule needs
its own state and its own test.

**`thread.start()` is wrapped.** It can raise `RuntimeError` when no more threads can be made. If
it raises after `_building` was set, the target never runs its `finally` and the index freezes on
its last snapshot until restart — the exact invariant the `finally` protects. The caller catches
it, reacquires the lock, clears `_building`, starts the cool-off, logs, **re-checks the snapshot
age against `max_stale_age` under that same lock**, and returns the stale snapshot only if it is
still inside the bound — otherwise `IndexTooStale`. Returning it unconditionally would bypass the
disclosure bound at exactly the moment the process is under resource pressure.

**The background build needs its own budget.** `ConventionIndex` takes an optional zero-argument
`refresh_budget` callable. **Absent it, stale rebuilds inline exactly as today**, so every
existing test keeps its semantics. That fallback is fail-silent — the class could be correct while
the service never uses it — so Task T6 asserts the wiring, and that assertion is the surface.

### b. One build at a time, and an honest call count

- `self._lock` (`RLock`) guards `_snapshot`, `_at`, `_building`, `_cooldown_until`, `_flight`.
- `self._dates_lock` (`Lock`) guards `_dates`.

**No lock is held across a GitHub call or a SQLite call.** `_dates_for` reads the memo under the
lock, releases it, goes to the store and then the network, then retakes the lock to install.

Two threads can both miss the same key. Within one walk they cannot: the key is
`(repo, path, blob_id)`, each entry is visited once, and one build runs at a time. So per-key
single-flight — which both reviewers proposed — guards a race the structure already excludes.

**`Budget` becomes thread-safe** with an `RLock` — reentrant, because `spend_call` and
`socket_timeout` both call `check`, and a plain `Lock` deadlocks on the first call. Proved by
breaking it on purpose: swapping in a `Lock` hangs the guard test, which then had to be killed.

**This one is DEFENSIVE, and the record is corrected here.** An earlier revision of this document
claimed the live spike measured a lost increment — "40 calls counted where 41 were made". That was
wrong: the expected figure was 41 only if every repository costs two calls, and one repository
failed on `commit` and never reached `tree`, so 40 was the correct count. The race is real by
construction — `spend_call` is a check-then-act over a read-modify-write — but it was **not
reproducible** on CPython 3.12: 16 threads x 1500 increments, four trials, `setswitchinterval(1e-7)`
and a clock that yields inside `check()`, all lost exactly zero. The fix ships because the issue
asks for it, because it costs one uncontended acquire against a 1.4-second round trip, and because
it stops being theoretical on a free-threaded build. Not because anything was observed to break.

**Rejected: per-worker budget slices.** The total cap would become `pool_size × per_worker_cap` —
the one global bound becomes a per-worker bound that scales with a tuning knob. The lock costs one
uncontended acquire against a 1.40s round trip; measured per-repository mean was 1.10s concurrent
versus 1.40s serial, so there is no contention to pay for.

### c. The walk: two phases through one pool

```
phase 1: ThreadPoolExecutor(max_workers=N).map(commit+tree, sorted(repos))   #  61 tasks
phase 2: ThreadPoolExecutor(max_workers=N).map(file_dates,  every document)  # 618 tasks
assemble: merge in sorted(repo) order, sort rows, digest, publish
```

One task per repository was the obvious shape and it is **3.2× slower** — 170.87s against 52.66s
— because a repository's date calls serialize inside its own task. Both numbers are measured on
the real account with an empty store.

**Each task returns one immutable result and mutates nothing shared:**
`_RepoWalk(repo, commit, entries_or_none, unreadable_reason)` from phase 1, and
`(key, added, updated, failed)` from phase 2. The single assembler merges every field in
`sorted(repos)` order, so rows, `projects`, `unreadable`, the `generation` digest and the prune
inputs are all independent of completion order.

#### A shared failure must not be recorded as 61 local ones

`DeadlineExceeded`, `BudgetExhausted` and `Unauthorized` are all **subclasses of `GitHubError`**
(`harness/github.py:46-63`), and **both** existing handlers catch the base class — the
per-repository one at `convention.py:254-258` and **`_dates_for`'s own at `convention.py:239-240`**.

So today an expired token makes all 61 repositories `unreadable`, `snapshot()` returns
**successfully** with `rows: []`, and `app.py` renders a confident **empty index page** rather than
the 503 it would render if the call had raised. Three fixes, all in this change:

```python
_WALK_FATAL = (DeadlineExceeded, BudgetExhausted, Unauthorized)
# in _dates_for AND in each phase task, BEFORE `except GitHubError`:
except _WALK_FATAL:
    raise
```

1. **Fatal errors are re-raised from both handlers** and fail the whole build.
2. **Zero rows with a non-empty `unreadable` is an unconditional build failure** — it raises,
   rather than merely declining to publish. Revision 2's guard only protected an *existing*
   snapshot, so a cold start where every repository failed locally still published a confident
   empty page. An org with genuinely no documents and no unreadable repositories still publishes
   an empty listing, correctly, because nothing failed.
3. **If every attempted date lookup failed, the build fails.** A single failure still lists its
   document — see the carry-forward rule next. But a *systemic* date outage blanks every date, and
   a blank date changes the generated hostname for any document whose filename carries no date, so
   **shared links break**. "Every attempt failed" is the crisp line between one hiccup and an
   outage.

#### Carry forward what the last good snapshot already knew

Guards 2 and 3 are all-or-nothing, and the reviewer was right that a *partial* failure slips
between them. Two cases, both measured as real — the full cold-walk spike saw **3 repositories
fail transiently in one walk**:

- **A repository unreadable this build, listed in the last one.** Without a rule, the new snapshot
  simply drops that repository's documents, so one transient hiccup makes ~200 `rawgentic`
  documents vanish from the index for up to fifteen minutes.
- **A document's date lookup failing this build, known in the last one.** Without a rule, its
  dates go blank, and a blank date **changes that document's hostname** — a shared link breaks
  over one 500 from GitHub.

So the assembler **carries forward from the previous snapshot**: rows for any repository that was
unreadable this build, and the `(added, updated)` pair for any key whose lookup failed. Both are
keyed exactly as the snapshot already is, so the carry-forward is a lookup, not a merge heuristic.
On a **cold** build there is nothing to carry forward, and the all-or-nothing guards above are
what protect it.

Rejected: the reviewer's stricter rule — refuse the whole candidate whenever `unreadable` is
non-empty and a prior snapshot exists. With 61 repositories and a measured 3 transient failures in
one walk, that would block most index updates indefinitely. Carrying forward keeps the listing both
fresh and complete.

#### Cancellation

On the first `_WALK_FATAL`, a shared `threading.Event` is set, every task checks it before each
GitHub call, and the executor is shut down with `cancel_futures=True`. Without it, an expired
credential still fires the remaining repositories' calls at an API already refusing them.

#### Shutdown

The pool's workers are not daemon threads; `concurrent.futures` joins them at exit, so a process
stopping mid-build waits for in-flight calls, each bounded by `Budget.socket_timeout`.

**The honest consequence, stated rather than spiked:** a `docker compose down` issued while a
build is running can take Docker's full stop grace period — ten seconds by default — before the
container is killed, where today it would exit sooner. Nothing is lost when that happens: the
snapshot is rebuildable and the date store is autocommit. The adversarial review asked for a
container-termination spike measuring the effective signal, grace period and exit latency in each
phase. Declined: this change alters neither the signal handling nor the grace period, and
`waitress.serve` never returns, so the container has always been stopped by signal then SIGKILL.
A spike would measure Docker's documented behavior, not this design's.

No shutdown protocol is added — the peer proposed a coordinator thread with `close()`,
cancellation and a join bound, which is machinery for a graceful stop this process never performs.

#### Pool size

`DOC_HARNESS_INDEX_WORKERS`, default 8, **validated as 1..32 — a value outside it raises
`ConfigError` and refuses the boot. It is never silently clamped to a boundary**, because a
mistyped 64 that quietly becomes 32 is a setting the operator cannot see is wrong. Eight is
measured, not assumed: peak
in-flight exactly 8, zero 403s, 5000 of 5000 core limit remaining after roughly 1,500 calls across
three bursts. Before raising it, measure the same two things: wall-clock of the whole walk, and
the count of 403 responses carrying `x-ratelimit-remaining: 0`. A pool that goes faster while
collecting 403s is slower, because those are now fatal to the walk.

### d. Persist the date cache

```python
class DateStore:
    """(repo, path, blob_id) -> (added, updated), on the disposable cache volume."""
    def initialize(self) -> None            # never raises; sets self.available
    def get(self, key) -> tuple | None      # miss on any failure
    def put(self, key, value) -> None       # no-op on any failure
    def prune(self, live_keys, walked_repos) -> None
```

```sql
CREATE TABLE IF NOT EXISTS file_date (
  repo    TEXT NOT NULL,
  path    TEXT NOT NULL,
  blob_id TEXT NOT NULL,
  added   TEXT NOT NULL,
  updated TEXT NOT NULL,
  PRIMARY KEY (repo, path, blob_id)
) WITHOUT ROWID;
```

`WITHOUT ROWID` because every access is a composite-primary-key lookup: the table becomes the
index instead of carrying a second one.

**Where it lives:** `os.path.join(cfg.cache_dir, "index-dates.db")` — the `blobcache` volume,
mounted at `/var/cache/doc-harness` and declared in `compose.yaml` as "disposable: rebuilds from
GitHub by design". Losing it costs one 52.7-second boot, which is that volume's contract.

**Connection discipline** copies `BlobCache._conn` (`harness/cache.py:105-114`): thread-local
connection, `isolation_level=None`, WAL, `synchronous=NORMAL`, `busy_timeout=5000`.

**All four operations degrade, not just `initialize`.** Each catches `sqlite3.Error` **and**
`OSError`, logs **once** naming the operation and the path, sets `available = False`, and returns
a miss or a no-op. A disk that fills *after* a successful `initialize` would otherwise raise out
of `put`, inside the walk, and fail every build from then on. Both exception families are
required, and that was probed: an unwritable path raises `sqlite3.OperationalError`, which is
**not** an `OSError`, while `os.makedirs` on an unwritable parent raises `PermissionError`, which
is.

**Lookup order is memory, store, GitHub.** A store hit seeds memory. A GitHub result is installed
in memory first, then written best-effort, so a full disk cannot discard a result in hand.

**A failed `file_dates` is never memoized and never persisted.** Today's code already returns
`("", "")` without writing the memo (`convention.py:239-241`). Persisting it would poison every
future restart with a permanent blank date for a document that has one.

**Every value reaches SQL as a bound parameter.** Paths come from GitHub tree entries — external
data. Probed: `docs/it's 100% "odd".html` round-trips through `?` parameters.

**Pruning is scoped to the repositories actually walked.** `prune(live_keys, walked_repos)` deletes
rows whose `repo` was walked successfully but whose full key was not observed, so a permanently
unreadable repository neither blocks pruning for everyone else nor loses its own rows on no
evidence. Probed: the walked repository's stale rows went 77 → 1 while an unwalked repository's 77
were untouched.

#### The known limitation, named rather than designed away

Blob identity proves **content** identity, not **history** identity. Delete a document and re-add
it with byte-identical content: `(repo, path, blob_id)` is unchanged while its real `added` and
`updated` have moved, so the cached row keeps the old dates.

- **Consequence:** that one row sorts by its old `updated`, and if its filename carries no date
  its URL keeps the old one. The second half is the *stated goal* — owner decision 2026-08-24, a
  URL dated by last change moves and breaks shared links.
- **This already happens today**, for the life of a process. Persisting makes the window unbounded
  instead of restart-bounded.
- **Undo:** delete `index-dates.db`, or `docker compose down -v`. The volume is disposable.

**The reviewer's fix — adding the repository head commit to the key — is refuted.** Every push
moves the head, so every document in that repository would miss on the next walk: roughly 200
extra `file_dates` calls per push to `rawgentic`, which is precisely the cost blob-keying exists
to avoid. The issue also specifies this key explicitly.

## File changes

| File | Change |
|---|---|
| `harness/github.py` | `Budget` takes an `RLock` around `remaining`, `check`, `spend_call`, `socket_timeout`. |
| `harness/datestore.py` | **New.** `DateStore`. Stdlib only. |
| `harness/convention.py` | `IndexBuilding` / `IndexCoolingDown` / `IndexTooStale`; two locks; the cold leader/follower split; the background build with cool-off; the two-phase pool walk with cancellation; `_WALK_FATAL` in both handlers; the three publication guards; the `DateStore` read-through. |
| `harness/app.py` | The three 503 classes handled before the existing `except GitHubError`. Pass `refresh_budget`, the store, the worker count and `max_stale_age` into `ConventionIndex`. `make_app` gains `date_store=None`. |
| `harness/__main__.py` | Build and `initialize()` the `DateStore` from `cfg.cache_dir`; pass it to `make_app`. |
| `harness/config.py` | `index_workers` (default 8, validated 1..32) and `index_max_stale_age` (default 21600). |
| `compose.local-port.yaml` | **New.** The `127.0.0.1:18081` loopback mapping, committed so it cannot evaporate from `/tmp` again. Not applied by a bare `docker compose up`, so production is unchanged. |
| `tests/harness/test_convention.py` | SWR, cold leader/follower, one build, two-phase concurrency, fatal-vs-local, the three publication guards, cool-off, thread-start failure, stale bound. |
| `tests/harness/test_datestore.py` | **New.** Round trip, restart, degrade at each of the four operations, prune scoping, odd paths. |
| `tests/harness/test_github.py` | `Budget` under concurrent `spend_call`. |
| `tests/harness/test_app.py` | The three 503 splits and their `Retry-After`, and that the wiring is actually done. |

## Configuration changes

| Variable | Default | Validation |
|---|---|---|
| `DOC_HARNESS_INDEX_WORKERS` | 8 | 1..32. Outside → `ConfigError`, boot refused. Never clamped. |
| `DOC_HARNESS_INDEX_MAX_STALE_AGE` | `21600` (6 hours) | `0` (unbounded, explicit opt-in) or an integer > the TTL. A positive value ≤ the TTL → `ConfigError`, because it would make the stale window zero and acceptance criteria 1 and 2 unreachable. |

No compose change — `blobcache:/var/cache/doc-harness` is already mounted and already disposable.
No Dockerfile change — it already creates and chowns that directory to uid 10001.

`_index_budget()` (`app.py:58-62`) stays at `Budget(http_timeout * 30, max_github_calls * 10)` —
600 seconds and 3,000 calls at the defaults — and the reasoning is now measured rather than
inherited. A full cold walk spent **738 calls of 3,000** and finished with **429.1 seconds of the
600 remaining**. The deadline is wall-clock, so concurrency does not consume more of it. The site
would need roughly 2,200 documents before the call cap bit.

## Error handling and failure modes

| Failure | Behavior |
|---|---|
| Background build raises `GitHubError` | Logged. Previous snapshot stays. The reader never sees it. 60-second cool-off starts. |
| Background build raises anything else | Same. `_building` cleared in a `finally`. |
| `thread.start()` raises | `_building` cleared by the caller, cool-off started, stale snapshot returned. |
| Cold first build raises `GitHubError` | Propagates to the leader. `app.py:112-116` answers **503**, unchanged. |
| A second cold caller arrives | `IndexBuilding` → **503 + `Retry-After: 5`**, worker released at once. |
| A cold caller inside the cool-off | `IndexCoolingDown` → **503 + `Retry-After: <seconds left>`**. |
| The shared budget runs out mid-walk | `DeadlineExceeded` / `BudgetExhausted` re-raised past **both** handlers, stop event set, pending futures cancelled. |
| The credential is refused | `Unauthorized`, same path. An expired token now yields 503, not a confident empty index. |
| One repository unreadable, warm build | Named in `unreadable[]`. **Its rows are carried forward from the previous snapshot**, so a transient hiccup cannot make its documents vanish. Its store rows are not pruned. |
| One repository unreadable, cold build | Named in `unreadable[]`. Nothing to carry forward, so its documents are simply absent this build, as today. |
| Every repository unreadable, zero rows | **Build failure**, cold or warm. Cold → 503; warm → the old snapshot stands. |
| Every attempted date lookup failed | **Build failure.** |
| A single `file_dates` fails, warm build | **The previous snapshot's `(added, updated)` for that key is carried forward**, so the document's hostname cannot change because of one 500. Not memoized, not persisted, retried next walk. |
| A single `file_dates` fails, cold build | `("", "")` — the document is still listed, deliberately (`convention.py:230-233`). |
| The date store fails at any operation | Logged once, `available = False`, miss/no-op. Never a boot failure, never a failed build. |
| Snapshot older than `max_stale_age` | `IndexTooStale` → 503, on every path including the `thread.start()` failure branch. Default six hours, so it fires only during a real outage. |
| The system clock jumps | Freshness is on `time.monotonic()`. Only `generated_at` moves. |
| Process stops mid-build | The daemon thread dies; the pool is joined at exit. The store is autocommit, so completed rows survive. |

## Security implications

No new request surface: no route, no header, no query parameter. Two new environment variables,
read once at boot, validated and clamped.

- **The token still never reaches an exception.** `Budget`'s lock changes no message, and
  `DateStore` never sees a credential. The store holds repository names, paths, blob ids and ISO
  dates — all already printed on the index page.
- **External data reaches SQL only as bound parameters.** Probed with a path containing a quote
  and a percent.
- **Concurrency does not widen the budget.** The lock makes the existing cap enforceable under a
  shared `Budget`. No loss was observed on this runtime — see change (b) — so this is hardening,
  not a fixed leak, and it is described that way rather than oversold.
- **An expired credential now fails loudly.** Today it renders an empty index; after this change
  it is a 503. A blank index is indistinguishable from "the org has no documents", so this is a
  security-relevant improvement.
- **Stale metadata exposure is bounded by default.** `DOC_HARNESS_INDEX_MAX_STALE_AGE` defaults to
  six hours, so a listing cannot outlive a revocation indefinitely. Following any link changes
  nothing either way: `ConventionResolver` asks GitHub per request and returns 502/404. Setting the
  variable to `900` restores today's bound exactly, at the cost of the feature; `0` removes it. See
  **Two decisions taken without the owner**.
- **A 503 carrying `Retry-After` reveals only that a build is running or cooling down.**
- **Who can reach the page at all is unchanged by this design and is not claimed as evidence
  here.** The index sits behind Cloudflare Access today and still will; nothing in this change
  adds, removes, or relies on that control, so no capability citation for it is offered and none
  is load-bearing. The adversarial review asked for an Access policy citation and a negative-access
  spike; both are declined as outside a change that touches no routing and no authentication.

## Platform / external dependencies

platform_apis:
- api: `concurrent.futures.ThreadPoolExecutor(max_workers=8)` with `map` / `submit` /
  `future.result()` / `shutdown(cancel_futures=True)`, CPython 3.12, inside the serving container
  feasibility: verified via spike — 2026-09-15, live inside `design-doc-publish-harness-1`. Eight
  submits, one raising: the seven good futures returned `[0, 2, 4, 8, 10, 12, 14]`, the eighth
  re-raised `ValueError('boom 3')` at `.result()`, `threading.active_count()` back to 1 after the
  context manager exited. Python 3.12.14. The two-phase shape this design ships was then run end
  to end (below).
  failure: fail-loud
- api: **`urllib.request.urlopen` called concurrently through one shared `HttpGitHub` and one
  shared `Budget`, in the exact two-phase shape and the exact production call mix**
  feasibility: verified via spike — 2026-09-15, live, real GitHub account, container's own
  `HttpGitHub`, production `Budget(600, 3000)`, empty date store, pool 8. **61 repositories and
  618 documents: phase 1 11.30s, phase 2 41.36s, total 52.66s, 738 calls of 3,000, peak in-flight
  exactly 8, 3 isolated `Unavailable`, zero 403s, GitHub core limit 5000 of 5000 after.** The
  shared `Budget`'s count came back exactly right in both spikes, so this run observed no
  miscount. The
  one-task-per-repository shape was measured first at 170.87s, which is why the design ships two
  phases. `HttpGitHub` holds no connection pool — `urllib` opens a connection per call — and
  installs no cookie processor, so the only shared mutable state is `urllib.request`'s lazily
  built module-level opener, which is idempotent to build twice.
  failure: fail-loud
- api: `sqlite3.connect` with `PRAGMA journal_mode=WAL` on `/var/cache/doc-harness` as uid 10001,
  written from 8 threads via thread-local connections, **against the exact shipped
  `WITHOUT ROWID` schema**
  feasibility: verified via spike — 2026-09-15, live, with the schema in this document verbatim.
  uid 10001, directory writable, 8 threads × 77 `INSERT OR REPLACE` → **616 rows in 0.132s**, zero
  errors, `PRAGMA journal_mode` read back `wal`, 80 KB on disk at the site's real document count.
  A path containing a quote and a percent round-tripped through bound parameters. The scoped
  `prune` took the walked repository 77 → 1 and left an unwalked repository's 77 untouched. SQLite
  3.46.1.
  failure: fail-loud
- api: the degrade path — `sqlite3.connect` + `PRAGMA` against a location this uid cannot write
  feasibility: verified via spike — 2026-09-15, same container. `/etc/probe65-dates.db` and
  `/nonexistent-dir-65/dates.db` both raised `sqlite3.OperationalError: unable to open database
  file`; `os.makedirs('/etc/probe65dir')` raised `PermissionError: [Errno 13]`. **This is why the
  degrade path catches `sqlite3.Error` AND `OSError`** — the sqlite failure is not an `OSError`,
  and catching only that would turn an unwritable volume into a failed boot, the one outcome the
  issue forbids.
  failure: fail-silent
  surface: every `DateStore` operation logs one line naming the operation and the path through the
  `log=` callable `make_app` already takes, and sets `available = False`. Tests assert the log line
  and that the index still builds, for `initialize`, `get`, `put` and `prune` separately.
- api: `HttpGitHub._classify` mapping a GitHub **403** onto a `_WALK_FATAL` type
  feasibility: verified via existing-call-site — `harness/github.py:238-246`. Every 403 returns
  `Unauthorized`, whether or not `x-ratelimit-remaining` is `0`; only the message differs. So a
  primary or secondary rate limit is already fatal to the walk, and no new exception type is
  needed. The adversarial review was right that the live spike observed zero 403s and therefore
  proves nothing here — the call site does. A unit test with a 403 response carrying
  `x-ratelimit-remaining: 0` pins the mapping so it cannot regress.
  failure: fail-loud
- api: a custom `Retry-After` response header through `_plain` → `start_response` → waitress
  feasibility: verified via existing-call-site — `harness/app.py:99` already returns
  `_plain(429, "too many publishes in flight; retry shortly", {"Retry-After": "30"})`. Exact API,
  exact response object, exact serving stack. The adversarial review asked for a spike here; the
  call site already is the evidence, so the request is declined rather than performed.
  failure: fail-loud

## Multi-PR assessment

One PR. No phase ships value alone: stale-while-revalidate without the two-phase walk still leaves
a 171-second cold boot, and the concurrent walk without the fatal-error classification would
publish an empty index the first time the budget ran out.

## Deployment preflight — blocking, before any post-deploy measurement

**Item 1 — CLEARED.** Four files differ between the running container and current `main`:
`harness/__init__.py` (4 diff lines), `index/build_index.py` (493), `scripts/user_config.py` (93),
`scripts/vdl_packs.py` (131). All four were diffed. They are already-merged, already-reviewed
work: PR #52 ("the Vercel era ends") and PR #58/#56 (the declared accent).
`git log --since="2026-08-24 23:31"` over those four paths returns exactly `e74b409 (#58)`. A
rebuild ships reviewed work, not unreviewed drift. `harness/convention.py` and `harness/app.py`
are byte-identical to `main`, so the 93.697s was measured on exactly the code this changes.

**Item 2 — CLOSED by this change.** The `127.0.0.1:18081` mapping is not in the committed
`compose.yaml`. It came from an override under `/tmp` which no longer exists, so recreating the
container from committed configuration alone loses the endpoint the measurement uses. A
replacement is committed here as `compose.local-port.yaml` — per the owner's standing rule, never
`/tmp`.

**Committing it does not prove the deploy consumes it**, so the preflight is a sequence, not a
file. Run exactly:

```bash
# 1. prove the override is in the EFFECTIVE configuration, before anything is recreated
docker compose -f compose.yaml -f compose.local-port.yaml config | grep -A2 '^ *ports:'
#    require: 127.0.0.1:18081 -> 8080

# 2. record what is about to ship
git rev-parse HEAD

# 3. recreate, with BOTH files named
docker compose -f compose.yaml -f compose.local-port.yaml up -d --build

# 4. record what actually shipped, and prove the route answers BEFORE any timing
docker inspect design-doc-publish-harness-1 --format '{{.Image}} {{.State.StartedAt}}'
curl -sf -o /dev/null -H "Host: index.3dstories.ca" http://127.0.0.1:18081/ || echo "ROUTE DOWN — stop"
```

Only then collect timings, and record the commit and the image digest beside the numbers.

## Verification beyond the unit tests

Re-run the origin measurement from the issue after the preflight, the rebuild and the redeploy.
Expected, from the measurements above: the first load after a >15-minute idle is well under a
second; a restart with the date store populated reaches a serving index in about 11 seconds; a
restart on a wiped volume takes about 53 seconds.

## Review provenance

Three independent cross-model passes, all `gpt-5.6-sol`, each blind to the ones before it:

| Pass | Verb | Result |
|---|---|---|
| Step 3 peer consult | `review_runner.py consult` | An independent design from the problem statement alone |
| Step 4 pass 1, on revision 1 | `review-artifact --type design` | 8 findings, 5 High |
| Step 4 pass 2, on revision 2 | `review-artifact --type design` | 9 findings, 4 High |
| Step 4 pass 3, on revision 3 | `review-artifact --type design` | 9 findings, 5 High |

Each result's `status`, `backend`, `backend_switched`, `reviewer_model` and `input_sha256` was
verified before it was read. Every finding was then checked against the cited source before being
treated as fact; two were downgraded and eight refuted on that evidence.

**Discovery stopped after pass 3, deliberately.** Three broad passes returned 8, 9 and 9 findings.
That is not an artifact getting worse — a broad review looks somewhere the last one did not, so it
finds new things every time by construction. Continuing would have spent the whole loop-back
budget on a method error rather than a defect (`regression-resistant-review`, invoked here).
Revision 4 applies pass 3's accepted findings as one bounded **repair round**, verified against
pass 3's own contract rather than by a fourth discovery pass. The remaining risk is stated plainly:
a fourth pass would find more text to tighten, and none of it would be the code this document
exists to authorize.

**Adopted (24):** the `_dates_for` handler swallowing budget errors; ordinary `GitHubError` not
always being repository-local; the cold-start zero-rows hole; the systemic-date-failure hole;
**the partial-failure hole, per repository and per document, answered by carrying forward the last
good snapshot**; cold followers starving the workers; the `_refreshing`/`_building` name collision;
the monotonic TTL; the failure cool-off on both paths; the `thread.start()` window **and its
stale-bound recheck**; the `IndexCoolingDown` response shape; **a bounded default stale age**; the
degrade contract on all four store operations; the immutable per-task result; fatal cancellation;
the undeclared shared transport; never persisting a failed date; `WITHOUT ROWID`; the deployment
preflight **and its effective-configuration assertion**; `compose.local-port.yaml` named in the
file list; **rejection rather than clamping for an out-of-range worker count**; the 403 mapping
pinned by a test; and the scoped prune.

**Refuted or declined (11):**

| Proposal | Why not |
|---|---|
| Add the repository head commit to the date-store key | Every push moves the head, so every document in that repository misses — ~200 extra calls per push to `rawgentic`, the exact cost blob-keying avoids. The issue specifies this key. |
| Spike the `Retry-After` header | `app.py:99` already sets one on the existing 429: same API, same response object, same stack. |
| A hard `MAX_STALE_AGE` of exactly 900s | 900 **is** the TTL, so the stale window would be zero and acceptance criteria 1 and 2 could never pass. A bound of six hours is shipped on by default instead; see the decisions at the top. |
| Refuse any candidate whenever `unreadable` is non-empty | With 61 repositories and 3 transient failures measured in a single walk, that blocks most index updates. Carrying forward the previous snapshot's rows is both fresh and complete. |
| A container-termination spike measuring signal, grace period and exit latency | This change alters neither signal handling nor the grace period. The one real consequence — a stop during a build can take Docker's full ten seconds — is stated under Shutdown. |
| A Cloudflare Access policy citation and a negative-access spike | The change touches no routing and no authentication, and nothing in it relies on Access as evidence. |
| Spike the 403-to-exception mapping | `harness/github.py:238-246` already maps every 403 to `Unauthorized`, which is fatal. The call site is the evidence; a test pins it. |
| A long-lived coordinator thread with `close()` and a bounded join | Machinery for a graceful shutdown this container never performs. |
| Per-key single-flight on `_dates` | Each key is visited once per walk by one worker, one build at a time. No reachable race. |
| A metrics surface — latency, peak in-flight, 403/429 counts, stale age | No criterion asks for it and the service has none at all. The measurement it supports is written down under change (c). |
| Persist the whole last-good snapshot | Out of scope, as the peer itself noted; ~150 lines and its own staleness rule. Available later. |
| Exponential retry backoff; `PRAGMA user_version` | A fixed 60s cool-off against a 900s TTL; and the volume is disposable, so a schema change gets a new filename. |
