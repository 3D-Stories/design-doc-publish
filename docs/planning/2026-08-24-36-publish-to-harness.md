# #36 — publish through the harness instead of Vercel

Design for the third child of #38. #34 shipped the harness; #35 shipped the container that would
put it on the internet. This child moves `publish_doc.py` off Vercel and onto the harness control
API.

Expected diff: **700-900 lines, most of it tests**. This document stays shorter than that.

**Revision 2**, after Step 4 pass 1 — 13 findings, all adopted, none declined. One of them
(A4) changed the design rather than tightening it, and it is the first section below.

## The correction that matters most: publishing is blocked too, not just verifying

Revision 1 was built on a wrong assumption of mine. I knew no harness hostname resolves and
designed the *verification* around it — and did not notice that **the control API lives on the
same unreachable zone**, at `docs-control.3dstories.ca` (`harness/routing.py:38`). So revision 1
could not publish at all, not merely fail to prove it had.

**The control endpoint is therefore configurable, and its default is the reachable one.**

| Setting | Value |
| --- | --- |
| `DOC_HARNESS_CONTROL_URL` | the control API base. Default: the compose-network address `http://harness:8080`, reachable today |
| `DOC_HARNESS_PUBLIC_BASE` | the public host pattern for stage 6's edge half. Unset ⇒ that half SKIPS, visibly |

Neither is guessed at runtime. An unset public base is a declared state with a defined exit code
(below), never an inferred one.

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
3. **Reachability, with a stated acceptance rule** (finding A6). "Is HEAD pushed" is not
   `git ls-remote` succeeding, and it is not ref-tip equality — a pushed commit that is no longer
   a tip is still perfectly reachable, and tip-matching would falsely reject it. The rule is:
   `git rev-list --count <remote-tracking ref>..HEAD` is **0**, after a `git fetch`. Anything else
   refuses, naming the unpushed commits.

Each of these is a refusal the harness would eventually make. Making them locally turns a 422
about a blob id into one clear local sentence.

### Stage 5 — publish

Two control-API calls against `DOC_HARNESS_CONTROL_URL`:

1. `GET /deployments/<name>` → **200 with `active_deployment_id: null`** when nothing is published
   yet, never 404 (`harness/control.py:_read_back`, pinned at `tests/harness/test_control.py:184`).
   That null passes straight through.
2. `POST /deployments` with the manifest and `expected_active` — required, and sent explicitly;
   the parser refuses an omitted field with its own message that omission and null differ.

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
| origin | `DOC_HARNESS_CONTROL_URL`'s host | the manifest, the CAS, the echo, byte equality | runs |
| edge | `DOC_HARNESS_PUBLIC_BASE` | Cloudflare and Access | **skips visibly** while unset |

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

- edge half verified → exit 0.
- edge half skipped because `DOC_HARNESS_PUBLIC_BASE` is unset → **a dedicated non-zero exit**,
  with the skip and its reason on stdout. Callers that accept an origin-only publish opt in
  explicitly with `--allow-unverified-edge`, which then exits 0 and still prints the skip.
- origin half failed → the existing stage-6 code.

**The origin half is an OPERATIONS check, not a gate test** (finding A8). Revision 1 called it
"runnable now" with nothing cited. `capabilities.has_docker` is **false** for this project and the
gate is deliberately dependency-free — `pytest scripts/tests/ tests/ -q` must never require a
running container. So the origin verification is a documented ops step whose result is RECORDED in
the PR, and the pytest suite covers the new code with the HTTP layer faked, exactly as the
existing `FakeUrlopen` tests do.

### Stage 7 — deleted

`refresh_index` retires; the index is server-rendered from the registry snapshot (#34, spec D3).
**`index/build_index.py` itself SURVIVES** as the harness's shared renderer (finding S5) — only
`publish_doc.py`'s invocation and the index's Vercel deploy go.

### Flags, the name cap, lint, credentials

`--new-project` and `--vercel-scope` retire. `MAX_ALIAS_LABEL` moves 35 → **63**, the limit
`harness/routing.py:is_valid_label` enforces, kept as a lint WARNING.

Lint extends: every same-origin resource the HTML references must appear in the staged manifest.

**Credential hygiene** (finding S3). Three credentials cross this path:
`DOC_HARNESS_PUBLISH_TOKEN` (the POST bearer), `CF-Access-Client-Id` and
`CF-Access-Client-Secret` (the edge fetch). Each is read from the environment by name. **No error
path may render any of their values** — `publish_doc.py`'s existing failure path prints subprocess
logs verbatim, which is exactly the shape that leaks a header. A test asserts a failing publish
and a failing verify both produce output containing none of the three.

## What retires in the tests

| File | Fate |
| --- | --- |
| `test_scope_threading.py` (410 lines) | exists to thread `--vercel-scope`; retires with it |
| `test_vercel_timeout.py` (82 lines) | Vercel-specific |
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
- **NOT proven, declared** — the harness's GitHub grant over an arbitrary document repository,
  and anything past the Cloudflare edge. Neither is provable from here.

## Acceptance criteria mapping

| AC | Where it lands | How it is proved |
| --- | --- | --- |
| 1 | stages 4a + 5 | tests over the manifest builder and both control calls: `expected_active: null` first publish, the 409 race, and `deployment_id` read from the 201 |
| 2 | stage 6 | origin half runs as a recorded ops step; **edge half DEFERRED, skipping with a non-zero exit** |
| 3 | lint + cap 63 | a referenced same-origin resource missing from the manifest fails lint; a 40-char name warns and passes |
| 4 | delete `refresh_index` | a test asserts the symbol is gone and no Vercel index deploy remains; `build_index.py` still imports |
| 5 | `--dry-run` + the gate | `--dry-run` tests unchanged; gate green; **end-to-end live proof DEFERRED with AC 2** |

## This child does not close #36

Finding A1, and it is the same shape as #35. Two acceptance criteria cannot be met while no
harness hostname resolves, so the PR body says **Part of #36** and the issue stays **OPEN** with
what remains recorded on it. A merged child reading as green with AC 2 and AC 5 unmet is the
misreport this names.

## Deferred, and to where

Both deferrals are one blocker wearing two hats, and neither is this child's to clear:

- **AC 2's edge half** and **AC 5's end-to-end live proof** wait on #35's AC 2 and AC 3. They run
  with no code change once a hostname resolves and `DOC_HARNESS_PUBLIC_BASE` is set.

Local proxy for both: the origin-half verification against the compose network, which exercises
every line of the new code except the edge.
