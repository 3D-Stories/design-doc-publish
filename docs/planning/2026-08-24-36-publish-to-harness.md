# #36 — publish through the harness instead of Vercel

Design for the third child of #38. #34 shipped the harness; #35 shipped the container that would
put it on the internet. This child moves `publish_doc.py` off Vercel and onto the harness control
API.

Expected diff: **700-900 lines, most of it tests**. This document stays shorter than that.

**Revision 3**, after Step 4 pass 2 — 12 findings, 11 adopted and 1 declined as scope. Two of
them were found INDEPENDENTLY by the inline self-review and by the cross-model reviewer, so they
are treated as confirmed rather than plausible: the control endpoint had no reachable value at all
(M2, below), and the credentials were attached to a destination nothing validated (M7).

## The correction that matters most: there is no reachable default, so there is no default

Revision 1 assumed the public zone was reachable. Revision 2 corrected that and then made the same
mistake one layer down: it defaulted the control endpoint to the compose-network address
`http://harness:8080` and called it "reachable today". **It is not reachable from where
`publish_doc.py` runs**, and three committed files say so:

| Evidence | What it says |
| --- | --- |
| `compose.yaml` | the harness "publishes no host port and never will" |
| `docs/planning/2026-08-24-35-harness-go-live.md:490` | "port 8080 is not listening on the host" |
| `docs/runbooks/2026-08-24-35-harness-go-live.md:83` | `harness` is a compose SERVICE name; only another container on that network resolves it |

`publish_doc.py` runs on the host. So `harness:8080` names nothing it can reach, and no other
endpoint exists: no host port is published and no public hostname resolves.

**Owner decision D21: there is no default. The variable is required.**

| Setting | Value |
| --- | --- |
| `DOC_HARNESS_CONTROL_URL` | the control API base. **REQUIRED, no default.** Unset ⇒ stage 5 refuses with exit 25 |
| `DOC_HARNESS_PUBLIC_BASE` | the public host pattern for stage 6's edge half. Unset ⇒ that half SKIPS, visibly, with exit 26 |

Neither is guessed at runtime, and neither has a default that could be silently wrong. Both unset
states are DECLARED states with their own exit codes, never inferred ones.

**Where the origin verification actually runs.** From inside the compose network on the harness
host `10.0.17.205`, invoked as `docker compose exec`, with `DOC_HARNESS_CONTROL_URL` set to
`http://harness:8080` for that invocation only. That is an OPERATIONS step whose result is recorded
in the PR (see stage 6), never a pytest case — `capabilities.has_docker` is false for this project
and `pytest scripts/tests/ tests/ -q` must stay dependency-free.

Decided against, and why: publishing a host port contradicts `compose.yaml` and adds inbound
surface on that machine; running `publish_doc.py` itself as a container on the compose network is a
large scope addition that would change how every existing caller in the workspace invokes it.

## The inversion, which is the rest of the work

**The harness does not accept rendered bytes.** `harness/manifest.py:140` requires `repo`,
`commit_sha` ("a full 40-hex commit id, not a ref") and, per asset, `repo_path`, `blob_id`, `size`
and `sha256`. `harness/control.py:_publish` then fetches every blob FROM GITHUB and refuses on any
mismatch.

Today `deploy()` writes `index.html` into a temp workdir and ships those bytes. The page must
instead be **committed and pushed first**, and the publish pins that commit. The spec names this
*publish-before-merge* (lines 104-109) and accepts its one v1 risk: an abandoned PR lets GitHub GC
the SHA, after which serving follows the spec's F8 split.

**One consequence is a gift.** AC 2 asks for byte equality between the served page and the
just-rendered page. Because the harness serves the COMMITTED bytes, that one assertion also proves
the render matches the commit — "rendered but forgot to commit" becomes a caught failure.

## The change, stage by stage

Stages 1-4 (render, source gate, derive name, lint) keep their shape.

### Stage 4a — provenance, failing LOCALLY

1. **Locate the repository from the RENDERED PAGE, never from cwd** (finding S1).
   `git -C <resolved parent of --out> rev-parse --show-toplevel`. `publish_doc.py` takes `--md`
   and `--out` as arbitrary paths and is used across the whole workspace, so the document
   routinely lives in a different repository from the process's cwd. Resolving via cwd pins the
   wrong repo; the benign failure is a 422, and the dangerous one is that the path exists in the
   wrong repo and the harness serves a **different file under the right name**, with every
   downstream check still passing. **Refuse when `--md` and `--out` resolve into different
   repositories.**
2. **Compare each asset against the COMMITTED blob, not against itself** (finding A2). Revision 1
   said "compare against `git hash-object`", which hashes working-tree bytes and proves nothing
   about the pinned commit. The check is `git rev-parse HEAD:<repo_path>` versus
   `git hash-object <file>`; unequal means the tree is ahead of the commit being pinned. A
   `HEAD:<repo_path>` that does not resolve means the asset is not committed at all.
3. **Reachability, against the remote the manifest actually names** (findings A6 and M5).
   "Is HEAD pushed" is not `git ls-remote` succeeding, and it is not ref-tip equality — a pushed
   commit that is no longer a tip is still perfectly reachable, and tip-matching would falsely
   reject it. But the rule is worthless unless the ref belongs to the SAME repository the manifest
   declares: a fork, a second GitHub remote, or a GitLab mirror all satisfy a bare reachability
   check while the harness cannot fetch the commit from `repo`. So the check is one bound
   sequence, and every branch of it refuses rather than guessing:

   1. Enumerate remotes. Select the ONE whose URL parses to a GitHub `owner/name`. **Two
      candidates, or none, refuses** — naming them. No implicit preference for `origin`.
   2. `repo` in the manifest IS that parsed `owner/name`, normalized (strip `.git`, lowercase the
      host). It is never taken from configuration or cwd.
   3. `git fetch <that remote>` must succeed. A failure refuses, quoting git's own message.
   4. `git rev-list --count <that remote>/<branch>..HEAD` is **0**. Anything else refuses, naming
      the unpushed commits.
   5. A detached HEAD, or no branch on that remote, refuses with that as the stated reason.

Each of these is a refusal the harness would eventually make. Making them locally turns a 422
about a blob id into one clear local sentence.

### Stage 5 — publish

Two control-API calls against `DOC_HARNESS_CONTROL_URL`:

1. `GET {control}/v1/deployments/<name>` → **200 with `active_deployment_id: null`** when nothing
   is published yet, never 404 (`harness/control.py:_read_back`, pinned at
   `tests/harness/test_control.py:184`). That null passes straight through. A **non-null** id is an
   integer and is sent back verbatim; a read-back whose id is present but not an integer refuses
   BEFORE the POST rather than coercing it.
2. `POST {control}/v1/deployments` with the manifest and `expected_active` — required, and sent
   explicitly; the parser refuses an omitted field with its own message that omission and null
   differ.

**The `/v1` prefix is not decoration** (finding M1). `_DEPLOYMENTS = "/v1/deployments"`
(`harness/control.py:34`) and an unprefixed path falls through to `404 no such control route`
(`harness/control.py:83`). Revision 2 wrote both paths without it.

**Both calls carry `Authorization: Bearer $DOC_HARNESS_PUBLISH_TOKEN`** — compared with
`hmac.compare_digest` against `f"Bearer {cfg.publish_token}"` (`harness/control.py:60-61`), and a
missing or wrong header is a 401 (`harness/control.py:75`), not a 500.

**The success contract, which revision 1 left unstated** (finding A7): **201** with
`{"deployment_id": <int>, "name", "commit_sha", "assets", "cache_warmed"}`
(`harness/control.py:217`). **Stage 6's `<id>` is that `deployment_id`** — never the id read back
in step 1, which is the PREVIOUS deployment. A 201 whose body lacks an integer `deployment_id` is
a failure, not a pass.

A **409** means another publisher won the race and carries the current active id
(`tests/harness/test_control.py:138`), reported as a race rather than a generic failure.

**Manifest rules inherited from the #34 boundary:** `url_path` must be canonically
percent-encoded, so a filename carrying a space or any of `+ ( ) , & ' = @ ! $ *` is refused with
422 unless encoded. **Do not send `content_type`** — the harness derives it.

**The harness's own GitHub grant is a precondition, and the local checks do NOT prove it**
(findings A5 and S4). Stage 4a exercises the PUBLISHER's git credentials; the harness fetches
blobs with `DOC_HARNESS_GITHUB_TOKEN`, a different identity that may not cover this repository.
Those checks can pass while the harness cannot read a single blob. So a 502 from the publish is
mapped to a message naming the **grant**, not the transport. Also stated plainly: publishing makes
the committed bytes readable by anyone who passes Access, so publishing from a private repository
is a deliberate exposure decision.

### Stage 6 — verify, in two halves with different standing

| Half | Endpoint | What it proves | Status |
| --- | --- | --- | --- |
| origin | `DOC_HARNESS_CONTROL_URL`'s host | the manifest, the CAS, the echo, byte equality | runs as an ops step |
| edge | `DOC_HARNESS_PUBLIC_BASE` | Cloudflare and Access | **skips visibly** while unset |

**The exact request, because revision 2 gave none** (finding M3). Without a template, plausible
implementations verify the ACTIVE deployment rather than the pinned one, hit the control route, or
request the wrong asset. Both halves iterate the SAME list — the entry page plus every asset in the
manifest, each by its own `url_path` — and differ only in URL and headers:

| | origin half | edge half |
| --- | --- | --- |
| URL | `{DOC_HARNESS_CONTROL_URL}{url_path}?__deployment={deployment_id}` | `{DOC_HARNESS_PUBLIC_BASE with <name> substituted}{url_path}?__deployment={deployment_id}` |
| `Host` header | `<name>.{DOC_HARNESS_ZONE}` — **mandatory**: serving routes on Host, and the origin URL's own host is the compose service name, which routes to nothing (`harness/routing.py:84`) | not set; the URL already carries it |
| Auth headers | none | `CF-Access-Client-Id`, `CF-Access-Client-Secret` |

`{deployment_id}` is the integer from the stage-5 **201**, never the id read back in step 1 — that
one is the PREVIOUS deployment, and verifying against it would pass while proving nothing.
`url_path` is used exactly as the manifest declares it, already canonically percent-encoded; it is
never re-encoded, re-normalized, or stripped of a query or fragment, because two spellings of one
resource are two cache keys (`harness/routing.py:89-95`).

Pass, per asset: 200, the `X-Doc-Deployment: <deployment_id>` echo (`harness/serving.py:56`,
pinned at `tests/harness/test_serving.py:56`), **that asset's own content type**, and byte
equality. Redirects disabled; an Access login redirect is a failure, not a retry.

**`text/html` applies to the ENTRY page only** (finding A3). Revision 1 put `text/html` in a pass
condition it then repeated for every asset, which would have rejected every valid CSS, JavaScript
and image asset. Each asset is checked against the content type the harness derives for its own
extension.

**The exit contract, which revision 1 left undefined** (finding S2). The issue's framing is that
the exit code IS the verdict, and `publish_doc.py` encodes the failing stage via `EXIT_BASE = 10`.
A skip that exits 0 is a pass to every caller and script. So:

**The numbers, because "a dedicated non-zero exit" is not one** (finding M8). `EXIT_BASE = 10`
(`scripts/publish_doc.py:100`) and there are seven stages, so **11 through 17 are taken** by
stage failures. A skip code inside that range is indistinguishable from a stage failure, which is
the exact misreport this contract exists to prevent. The declared-state codes therefore sit above
the block, at **25 and 26**:

| Exit | Meaning |
| --- | --- |
| 0 | published, and both verification halves passed |
| 11-17 | stage 1-7 FAILED (unchanged) |
| **25** | `DOC_HARNESS_CONTROL_URL` is unset — nothing was published (D21) |
| **26** | published and origin-verified; the edge half SKIPPED because `DOC_HARNESS_PUBLIC_BASE` is unset |

- edge half verified → exit 0.
- edge half skipped → exit 26, with the skip and its reason on stdout. Callers that accept an
  origin-only publish opt in explicitly with `--allow-unverified-edge`, which turns 26 into 0 and
  still prints the skip.
- origin half failed → 16, the existing stage-6 code.

**`--allow-unverified-edge` is an ADDITION no acceptance criterion asked for** (finding M9). It is
kept because exit 26 alone would break every existing caller that treats non-zero as fatal, and it
is named in the PR body as an addition rather than folded in silently.

**The origin half is an OPERATIONS check, not a gate test** (finding A8). Revision 1 called it
"runnable now" with nothing cited. `capabilities.has_docker` is **false** for this project and the
gate is deliberately dependency-free — `pytest scripts/tests/ tests/ -q` must never require a
running container. So the origin verification is a documented ops step whose result is RECORDED in
the PR, and the pytest suite covers the new code with the HTTP layer faked, exactly as the
existing `FakeUrlopen` tests do. The exact invocation, on `10.0.17.205`:

```
docker compose exec -e DOC_HARNESS_CONTROL_URL=http://harness:8080 harness \
  python3 /opt/publish/publish_doc.py --md <doc>.md --out <doc>.html --allow-unverified-edge
```

Its stdout and exit code are pasted into the PR body. A run that cannot be performed is recorded
as NOT performed — never as a pass.

### The network failure contract (finding M11)

Every replacement call is bounded, because the only named timeout test retires with Vercel and a
server that accepts a connection and then stops responding would hang the CLI for ever:

| Call | Connect | Read |
| --- | --- | --- |
| stage 5 `GET /v1/deployments/<name>` | 5 s | 20 s |
| stage 5 `POST /v1/deployments` | 5 s | 120 s — the harness fetches every blob from GitHub inside this call |
| stage 6, each origin fetch | 5 s | 20 s |
| stage 6, each edge fetch | 5 s | 20 s |

A timeout is that stage's failure, with the call and the elapsed time named. **The POST is never
retried automatically**: it is not idempotent, and a retry after an ambiguous timeout races the
`expected_active` compare-and-swap against a deployment its own first attempt may have created.
The refusal says so and names the read-back call the operator should run.

### Stage 7 — deleted

`refresh_index` retires; the index is server-rendered from the registry snapshot (#34, spec D3).
**`index/build_index.py` itself SURVIVES** as the harness's shared renderer (finding S5) — only
`publish_doc.py`'s invocation and the index's Vercel deploy go.

### Flags, the name cap, lint, credentials

`--new-project` and `--vercel-scope` retire. `MAX_ALIAS_LABEL` moves 35 → **63**, the limit
`harness/routing.py:is_valid_label` enforces, kept as a lint WARNING.

Lint extends: every same-origin resource the HTML references must appear in the staged manifest.

**Credential hygiene, in two parts** (findings S3 and M7). Three credentials cross this path:
`DOC_HARNESS_PUBLISH_TOKEN` (the POST bearer), `CF-Access-Client-Id` and
`CF-Access-Client-Secret` (the edge fetch). Each is read from the environment by name.

1. **Nothing renders a value.** **No error path may print any of the three** —
   `publish_doc.py`'s existing failure path prints subprocess logs verbatim, which is exactly the
   shape that leaks a header. A test asserts a failing publish and a failing verify both produce
   output containing none of the three.
2. **Nothing sends a credential to an unvalidated destination** (finding M7, found by both review
   passes). Redaction protects the LOG; it does nothing about the wire or the wrong server. Both
   base URLs come from the environment, so either can name any host and any scheme. The
   destination is therefore checked BEFORE any header is attached:
   - the Access service-token headers attach only over **https** and only to a host equal to
     `<name>.{DOC_HARNESS_ZONE}`;
   - the publish bearer attaches only over **https**, with one explicit exception: a plain-`http`
     URL whose host is a bare label with no dot (the compose service name) or a loopback address.
     Any other plain-`http` destination refuses rather than sending the token;
   - redirects stay disabled everywhere, so no credential can follow a 302 to a third host.

   Three tests: an unexpected host, an invalid scheme, and a redirect each produce a request
   carrying none of the three headers.

## What retires in the tests

| File | Fate |
| --- | --- |
| `test_scope_threading.py` (410 lines) | exists to thread `--vercel-scope`; retires with it |
| `test_vercel_timeout.py` (82 lines) | Vercel-specific — its RISK does not retire, so a new `test_harness_timeouts.py` covers the four bounded calls above |
| `test_publish_doc.py` (1831 lines) | ~6 classes rewritten: deploy binding, alias-domain verifier, project reuse/creation, cache-busted verification, index refresh, alias cap |

Each retired class names, in its removal commit, the new test covering the same risk — or states
that the risk left with Vercel.

## platform_apis

- **`git hash-object` produces exactly the manifest's `blob_id`. PROBED** with the shipped
  invocation, 2026-08-24: `git hash-object <file>` and `harness.control.git_blob_id` on the same
  bytes both returned `3aacd64bfcaf1000acb479e260f479b9c6b8bc90`.
- **Read-back null-on-first-publish** — exact existing call site (#226), `_read_back`, pinned at
  `tests/harness/test_control.py:184`.
- **201 + `deployment_id`** — `harness/control.py:217`.
- **`X-Doc-Deployment` echo** — `harness/serving.py:56`, pinned at `tests/harness/test_serving.py:56`.
- **409 compare-and-swap** — pinned at `tests/harness/test_control.py:138` and
  `tests/harness/test_concurrency.py:87` (exactly one winner).
- **The control endpoint is NOT reachable from the publisher's own execution context. MEASURED
  against three committed files, 2026-08-24**: `compose.yaml` ("publishes no host port and never
  will"), `docs/planning/2026-08-24-35-harness-go-live.md:490` ("port 8080 is not listening on the
  host"), `docs/runbooks/2026-08-24-35-harness-go-live.md:83` (`harness` is a compose service
  name). This is why `DOC_HARNESS_CONTROL_URL` has no default (D21) — revision 2 declared a
  default `reachable today` on no evidence at all, which is the failure mode this block exists to
  catch.
- **Control route prefix `/v1`** — `harness/control.py:34`; an unprefixed path 404s at
  `harness/control.py:83`.
- **Bearer auth on both control calls** — `harness/control.py:60-61`, compared with
  `hmac.compare_digest`; 401 at `harness/control.py:75`.
- **Serving routes on the `Host` header** — `harness/routing.py:84`, which is why the origin half
  must set it explicitly.
- **NOT proven, declared** — the harness's GitHub grant over an arbitrary document repository,
  and anything past the Cloudflare edge. Neither is provable from here.

## Acceptance criteria mapping

| AC | Where it lands | How it is proved |
| --- | --- | --- |
| 1 | stages 4a + 5 | tests over the manifest builder and both control calls: `expected_active: null` first publish, **a successful REPUBLISH over an existing deployment** (finding M12), the 409 race, a non-integer read-back id refusing before the POST, and `deployment_id` read from the 201 |
| 2 | stage 6 | origin half runs as a recorded ops step; **edge half DEFERRED, skipping with exit 26** |
| 3 | lint + cap 63 | a referenced same-origin resource missing from the manifest fails lint; a 40-char name warns and passes |
| 4 | delete `refresh_index` | a test asserts the symbol is gone and no Vercel index deploy remains; `build_index.py` still imports |
| 5 | `--dry-run` + the gate | the dry-run boundary below, asserted directly; gate green; **end-to-end live proof DEFERRED with AC 2** |

**The republish case is the one revision 2 omitted** (finding M12). Every listed test passed with a
client that always sends `null`, because first-publish, the 409 race and reading `deployment_id`
never exercise a non-null read-back. Without it the central path — publishing a document a second
time — could return 409 for ever and no test would notice.

### What `--dry-run` does, stated rather than inherited (finding M10)

AC 5 says dry-run behavior is unchanged, but stage 4a introduces a mandatory `git fetch` — network
access and a remote-ref mutation that did not exist before — and "the existing tests still pass"
does not define a boundary. So:

| Operation | Under `--dry-run` |
| --- | --- |
| render, source gate, derive name, lint | RUN (unchanged) |
| stage 4a repo/blob/reachability checks | RUN, **except** the `git fetch`, which is SKIPPED |
| `GET /v1/deployments/<name>` | never |
| `POST /v1/deployments` | never |
| stage 6, either half | never |

Skipping the fetch keeps dry-run offline, which is what "unchanged" has to mean for a flag whose
whole point is that it touches nothing. Reachability is then checked against the remote-tracking
ref as it already stands, and says so in its output. Three assertions cover this directly, rather
than relying on the legacy tests: no subprocess `fetch`, and no HTTP call of either kind.

## This child does not close #36

Finding A1, and it is the same shape as #35. Two acceptance criteria cannot be met while no
harness hostname resolves, so the PR body says **Part of #36** and the issue stays **OPEN** with
what remains recorded on it. A merged child reading as green with AC 2 and AC 5 unmet is the
misreport this names.

## Deferred, and to where

Revision 2 called these "one blocker wearing two hats" and said both clear with no code change
once DNS resolves. **That was false, and internally so** (finding M6): the same design separately
declares the harness's GitHub grant unproven. There are THREE preconditions, not one, and none is
this child's to clear:

| # | Precondition | Blocks | Owner |
| --- | --- | --- | --- |
| 1 | a hostname resolves — the wildcard `*.3dstories.ca` CNAME | AC 2's edge half | #35 AC 2 |
| 2 | Cloudflare Access apps, policies and a service token | AC 2's edge half | #35 AC 3 |
| 3 | `DOC_HARNESS_GITHUB_TOKEN` genuinely grants read on the document's repository | AC 5's live proof | unowned — see below |

**Precondition 3 is independent of DNS and is the one nobody was tracking.** Stage 4a exercises the
PUBLISHER's git credentials; the harness fetches blobs with a DIFFERENT identity. Every local check
can pass while the harness cannot read a single blob, and the symptom is a 502 that looks like
transport. It is recorded here as an explicit precondition with a preflight: before the live proof
is attempted, the grant is demonstrated by a recorded read of one blob from the target repository
using that token, and the result is pasted into whichever child performs it.

Local proxy for all three: the origin-half verification against the compose network, which
exercises every line of the new code except the edge.

## Declined, with the reason recorded

**M4 — no rollback after a failed verification.** The cross-model reviewer raised it as High: if
stage 6 fails after the stage-5 POST has activated the new deployment, the failed deployment keeps
serving, and nothing rolls back, quarantines, or verifies before activating.

**Declined as scope, not refuted.** The finding is correct. It is also work no acceptance criterion
asks for — the reviewer's own `criterion_relations` marks the concern `relation: scope` with an
empty `criterion_refs`. AC 1 specifies the publish; AC 2 specifies the verification; neither asks
for a transactional relationship between them. Adding pre-activation verification or a
compare-and-swap rollback changes the harness contract, and harness code is explicitly out of this
issue's scope.

What happens instead: the failure is LEGIBLE rather than silent. A stage-6 failure exits 16 and
says, in the refusal, that deployment `<id>` is active and unverified, and names the read-back call
that shows the current state. It is noted in the PR body. It is not filed as an issue — a review
finding becomes an issue only when the owner says so.

## What revision 3 added, and which criterion each addition serves

Every component this revision introduces, and the criterion it exists for. A component serving no
criterion would be a scope addition; there is exactly one, and it is declared.

| Added | Serves |
| --- | --- |
| `DOC_HARNESS_CONTROL_URL` required, no default; exit 25 when unset | AC 1 — without it the publish cannot run at all |
| The `docker compose exec` origin-verification invocation | AC 2 — it is how the origin half is actually performed |
| `/v1` on both control paths; the `Authorization: Bearer` header | AC 1 |
| The bound remote-selection sequence in stage 4a | AC 1 — the manifest's `repo` must be the repo the harness fetches from |
| Exact request templates and the mandatory `Host` header for both halves | AC 2 |
| Exit codes 25 and 26 | AC 2 — a skip that exits 0 reports a pass |
| Destination validation before attaching any credential | AC 2 — the criterion names the Access headers, so where they may be sent is part of it |
| Connect and read timeouts, and the no-auto-retry rule | AC 1 and AC 2 |
| The republish and non-integer-read-back test cases | AC 1 |
| The stated `--dry-run` boundary | AC 5 |
| Precondition 3, the GitHub grant, in the deferred table | AC 5 |
| **`--allow-unverified-edge`** | **an ADDITION.** No criterion asks for a flag. It exists so exit 26 does not break callers that treat non-zero as fatal, and it is named as an addition in the PR body. |
