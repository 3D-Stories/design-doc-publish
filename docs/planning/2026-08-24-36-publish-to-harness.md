# #36 — publish through the harness instead of Vercel

Design for the third child of #38. #34 shipped the harness; #35 shipped the container that would
put it on the internet. This child moves `publish_doc.py` off Vercel and onto the harness control
API.

Expected diff: **700-900 lines, most of it tests**. This document stays shorter than that.

**Revision 4.** Across three design passes this document accumulated 34 findings, and the
owner narrowed what the child claims (decision D22).

**Deliberately NOT recorded here** (Step 11 finding A3): the gate's own state — which budgets
are spent, what the breaker returned, whether the gate is closed. That belongs in the run's
orchestration metadata, where it is trusted, and a later reviewer should judge this document on
its merits rather than on text inside it announcing that review is finished. Two were found INDEPENDENTLY by both the
inline self-review and the cross-model reviewer, and are therefore treated as confirmed rather than
plausible: the control endpoint had no reachable value at all, and the operations command named a
file that is not in the image.

## The headline risk, stated first because merging this changes what works

**`publish_doc.py` loses the ability to publish anywhere the moment this merges.** Acceptance
criterion 1 retires `vercel link/deploy`, and the harness replacement cannot serve yet: no
hostname resolves, and the doc-harness stack is not running on `10.0.17.205` at all (`docker ps -a`
matches no harness container and no harness network). The spec's *parallel-run window*, where both
hosts serve during migration (#37), cannot open while only one of them is reachable.

This child is therefore code and tests, not a working publish path. The PR says **Part of #36**,
the issue stays **OPEN**, and the risk is the first line of the PR body rather than a footnote.

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

   1. Select the remote in this order, stopping at the first that resolves (finding N9 —
      revision 3 refused whenever two GitHub remotes existed, which is every ordinary
      fork-plus-upstream checkout, so it would have refused far more often than it caught
      anything):
      a. `--publish-remote <name>`, when given. An explicit override always wins.
      b. The current branch's configured upstream remote, when its URL parses to GitHub.
      c. The single GitHub remote, when there is exactly one.
      Only when none of those resolves does it refuse, naming every candidate it saw.
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
| `Host` header | `<name>.` plus the committed zone — **mandatory**: serving routes on the Host header, and the origin URL's own host is a bridge address, which routes to nothing. `harness/app.py:49` calls `resolve_host(environ["HTTP_HOST"], cfg.zone)`; `resolve_host` is `harness/routing.py:66` (finding N12 — revision 3 cited line 84, which is inside it rather than at it) | not set; the URL already carries it |
| Auth headers | none | `CF-Access-Client-Id`, `CF-Access-Client-Secret` |

`{deployment_id}` is the integer from the stage-5 **201**, never the id read back in step 1 — that
one is the PREVIOUS deployment, and verifying against it would pass while proving nothing.
`url_path` is used exactly as the manifest declares it, already canonically percent-encoded; it is
never re-encoded, re-normalized, or stripped of a query or fragment, because two spellings of one
resource are two cache keys (`harness/routing.py:89-95`).

Pass, per asset: 200, the `X-Doc-Deployment: <deployment_id>` echo (`harness/serving.py:56`,
pinned at `tests/harness/test_serving.py:56`), **that asset's own content type**, and byte
equality. Redirects disabled; an Access login redirect is a failure, not a retry.

**"That asset's own content type" needs a SHARED derivation, not a second copy** (finding N7). The
manifest deliberately carries no `content_type` — the harness derives it — so a publisher that
re-implements the extension mapping will drift, and drift here produces both false failures and
false passes. The publisher therefore imports the harness's own derivation rather than restating
it, and a parity test pins the two together across HTML, CSS, JavaScript, an image, an unknown
extension, and a type carrying a `charset` parameter. If the two ever disagree, the parity test
fails rather than a publish.

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
- edge half skipped → exit 26, always, with the skip and its reason on stdout.
- origin half failed → 16, the existing stage-6 code.

**Revision 3's `--allow-unverified-edge` is DELETED** (finding N3). It converted 26 into 0, which
contradicts the declared meaning of 0 and would let a caller reading only the status record a
criterion-2 pass that never happened. That is precisely the misreport this exit contract exists to
prevent, reintroduced by the thing meant to soften it. A caller that accepts an origin-only publish
interprets 26 itself, outside `publish_doc.py`, where the decision is visible in that caller's own
code. This also removes the one component revision 3 had to declare as serving no criterion.

**The origin half is an OPERATIONS check, not a gate test** (finding A8). Revision 1 called it
"runnable now" with nothing cited. `capabilities.has_docker` is **false** for this project and the
gate is deliberately dependency-free — `pytest scripts/tests/ tests/ -q` must never require a
running container. So the origin verification is a documented ops step whose result is RECORDED in
the PR, and the pytest suite covers the new code with the HTTP layer faked, exactly as the
existing `FakeUrlopen` tests do.

**Revision 3 named an invocation that cannot run** (finding N2, found by both passes). It said
`docker compose exec ... python3 /opt/publish/publish_doc.py`. The `Dockerfile` copies only
`harness/` and `index/` into the image, so the publisher is not in there. The image has no git,
and the process runs as the unprivileged `harness` user.

**The mechanism that does work was MEASURED on `10.0.17.205`, 2026-08-24.** The publisher stays on
the host and reaches the container directly at its bridge address:

```
CONTROL_IP=$(docker compose ps -q harness | xargs docker inspect \
  -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
DOC_HARNESS_CONTROL_URL="http://$CONTROL_IP:8080" \
DOC_HARNESS_ALLOW_BRIDGE_PLAINTEXT="$CONTROL_IP:8080" \
  python3 scripts/publish_doc.py --md <doc>.md --out <doc>.html
```

**The second variable is required and it names the exact endpoint** (Step 11 finding A1,
which caught this command failing after the credential work landed). Plaintext to the docker
bridge range is not granted by default: a range is not the one container you inspected. The
grant covers `host:port` exactly, so a bare `1` authorizes nothing.

The probe, run on this host with a throwaway container on its own bridge network and no published
port: `curl http://172.25.0.2:8080/` returned `HTTP/1.0 200 OK` carrying `X-Doc-Deployment`, while
`curl http://ddp-probe:8080/` returned `curl: (6) Could not resolve host`. So the host reaches a
container IP without any port being published, and never resolves a compose service name. That is
the whole of revision 2's error, measured rather than argued.

**This step has NOT been performed, and cannot be today**: the stack is not running here. It is
recorded as NOT performed. A step that could not run is never written up as a pass.

### The network failure contract (finding M11)

Every replacement call is bounded, because the only named timeout test retires with Vercel and a
server that accepts a connection and then stops responding would hang the CLI for ever.

**The client is `urllib.request.urlopen`, and the contract is what IT can enforce** (finding N8).
Revision 3 tabulated separate connect and read deadlines. `publish_doc.py` already uses
`urllib.request.urlopen(req, timeout=...)` (`scripts/publish_doc.py:763`), the repository has no
`requests` dependency, and the gate must stay dependency-free — so a separate connect deadline is
not available without adding one. `urlopen`'s `timeout` is a per-socket-operation deadline, not a
whole-call budget, and the contract says so rather than implying a total:

| Call | `timeout=` | Why |
| --- | --- | --- |
| stage 5 `GET /v1/deployments/<name>` | 20 s | a registry read |
| stage 5 `POST /v1/deployments` | 120 s | the harness fetches every blob from GitHub inside this call |
| stage 6, each fetch | 20 s | one asset |

Because a per-operation deadline does not bound a slow trickle, each stage ALSO carries a total
wall-clock budget checked between calls, and names whichever bound it hit. **Redirects stay
refused, not followed** — `verify_live` already does this (`scripts/publish_doc.py:808`).

**The POST is never retried automatically**: it is not idempotent, and a retry after an ambiguous
timeout races the `expected_active` compare-and-swap against a deployment its own first attempt may
have created. The refusal says so and names the read-back call the operator should run.

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
2. **Every credential is present before anything is built** (finding N6). A missing or
   half-present credential must fail as a LOCAL refusal, not indirectly as a 401 or a login
   redirect. Before either control call, the publish token must be present and non-empty. Before
   the edge half, the two Access values must be present and non-empty **as a pair** — one without
   the other refuses. Each refusal names the variable and never prints a value. Every
   missing-and-partial combination is tested.

3. **Nothing sends a credential to a destination that was not validated against a TRUSTED anchor**
   (findings M7 and N4, M7 found by both passes). Redaction protects the LOG. It does nothing about
   the wire or about the wrong server, and a syntactic rule does not establish server identity.
   Revision 3 allowed the bearer to go to *any* https host and to any dotless http host, which
   exfiltrates the token to whatever a mistaken or hostile environment names.

   **The anchor is committed configuration, never the same environment as the destination**
   (finding N11). Revision 3 validated the Access host against `DOC_HARNESS_ZONE`, which is
   environment-supplied — so an attacker who can set `DOC_HARNESS_PUBLIC_BASE` can set the zone to
   match it and pass validation. The zone is therefore pinned in committed project configuration.

   Before ANY header is attached, the destination URL is normalized and checked:
   - **userinfo, path, query and fragment are rejected outright** on a control base URL. Only
     scheme, host and port are permitted.
   - the **publish bearer** attaches only to an origin on an allowlist held in committed
     configuration: `https://` origins listed there, plus exactly the loopback origins and the
     container-bridge form the operations step uses. Any other origin refuses.
   - the **Access service-token headers** attach only over `https`, and only to a host equal to
     `<name>.` plus the COMMITTED zone.
   - **redirects stay refused everywhere** (`scripts/publish_doc.py:808` already does this), so no
     credential can follow a 3xx to a third host.

   Tests: an unexpected host, an invalid scheme, a URL carrying userinfo, and a control base
   carrying a path each refuse before any request is built. **The redirect test is different, and
   revision 3 got it backwards** (finding N10): it demanded the FIRST request carry no credentials,
   which would simply return 401 and prove nothing. It asserts instead that the initial request to
   the validated origin carries the credentials it should, that a 3xx is surfaced as a failure, and
   that **no follow-up request is made to the redirect target**.

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
- **Serving routes on the `Host` header** — `harness/app.py:49` calls `resolve_host` with
  `environ["HTTP_HOST"]`; `resolve_host` is defined at `harness/routing.py:66` and refuses a host
  outside the configured zone. This is why the origin half must set the header explicitly.
- **The HTTP client is `urllib.request.urlopen`** — `scripts/publish_doc.py:763`, one
  per-socket-operation `timeout=`, with redirects already refused at
  `scripts/publish_doc.py:808`. No `requests` dependency exists and none is added.
- **NOT proven, declared** — the harness's GitHub grant over an arbitrary document repository,
  and anything past the Cloudflare edge. Neither is provable from here.

## Acceptance criteria mapping

| AC | Where it lands | How it is proved |
| --- | --- | --- |
| 1 | stages 4a + 5 | tests over the manifest builder and both control calls: `expected_active: null` first publish, **a successful REPUBLISH over an existing deployment** (finding M12), the 409 race, a non-integer read-back id refusing before the POST, and `deployment_id` read from the 201 |
| 2 | stage 6 | **DEFERRED WHOLE — both halves** (owner decision D22). The code and its tests ship; neither half has been executed against a running harness, because none is running. Exit 26 records the edge skip |
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
| stage assets | RUN (unchanged — it touches no network and no git) |
| stage 4a repo/blob/reachability checks | **never** |
| `GET /v1/deployments/<name>` | never |
| `POST /v1/deployments` | never |
| stage 6, either half | never |

**Corrected during implementation, and the correction matters.** This table first said stage 4a
would run under dry-run with only the `git fetch` skipped, on the reasoning that the rest touches
no network. That was wrong, and an existing first-run test caught it: provenance needs a git
REPOSITORY, so a dry run started failing on documents that render perfectly — a behavior change on
the one flag whose acceptance criterion says it must not change.

Provenance is about PUBLISHING, and a dry run stops before publishing, so it has nothing to
establish. Moving stage 4a below the dry-run return also settles finding N10 outright: a dry run
performs no git at all, so there is no fetch to skip. Asserted directly: no subprocess `fetch`,
no git invocation, and no HTTP call of either kind.

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
| 0 | **the doc-harness stack is actually RUNNING on `10.0.17.205`** | AC 2 entirely, both halves | unowned — see below |
| 1 | a hostname resolves — the wildcard `*.3dstories.ca` CNAME | AC 2's edge half | #35 AC 2 |
| 2 | Cloudflare Access apps, policies and a service token | AC 2's edge half | #35 AC 3 |
| 3 | `DOC_HARNESS_GITHUB_TOKEN` genuinely grants read on the document's repository | AC 5's live proof | unowned — see below |

**Precondition 0 was discovered while reviewing this design and is recorded nowhere else.**
Measured 2026-08-24 on `10.0.17.205`: `docker ps -a` matches no harness or cloudflared container,
and no harness network exists. The stack has never been brought up here. Every previous artifact
treats missing DNS as the single blocker, and it is not — even the origin half, which needs no DNS
at all, has nothing to talk to. Bringing it up needs `DOC_HARNESS_GITHUB_TOKEN` and
`DOC_HARNESS_PUBLISH_TOKEN`, neither of which this run holds. **This is why AC 2 is deferred WHOLE
rather than by its edge half alone** (owner decision D22).

**Precondition 3 is independent of DNS and is the one nobody was tracking.** Stage 4a exercises the
PUBLISHER's git credentials, and the harness fetches blobs with a DIFFERENT identity. Every local
check can pass while the harness cannot read a single blob, and the symptom is a 502 that looks
like transport. It is recorded here as an explicit precondition with a preflight: before the live
proof is attempted, the grant is demonstrated by a recorded read of one blob from the target
repository using that token, and the result is pasted into whichever child performs it.

**There is no local proxy any more.** Revision 3 offered the origin-half verification as one.
Precondition 0 removes it: with nothing running, the origin half cannot be executed either. The
only evidence this child can produce is its test suite, with the HTTP layer faked.

## Declined, with the reason recorded

**M4 — no rollback after a failed verification.** The cross-model reviewer raised it as High: if
stage 6 fails after the stage-5 POST has activated the new deployment, the failed deployment keeps
serving, and nothing rolls back, quarantines, or verifies before activating.

**Raised TWICE and declined twice** — as M4 at pass 2, and again as N1 at pass 3, where the
reviewer located it at this very section. Neither the exact-key backstop nor the fuzzy layer
matched it, because both its wording and its stated location changed, so this is adjudicated by
hand and recorded in `dispositions.jsonl` so a fourth raising resolves mechanically.

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
| `--publish-remote` | AC 1 — the override that keeps remote selection deterministic on a fork-plus-upstream checkout |
| `skills/design-doc-publish/SKILL.md` updates | AC 1 — the retired flag and the new exit codes are documented where callers read them |
| The committed control-origin allowlist and pinned zone | AC 2 — the trust anchor the credential check needs |

**Revision 4 adds no component that serves no criterion.** Revision 3's one such addition,
`--allow-unverified-edge`, is deleted rather than declared.
