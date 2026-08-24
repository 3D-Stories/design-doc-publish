# #37 — Backfill the existing Vercel doc projects into the harness registry

Fourth and last child of epic #38. Spec: `docs/planning/2026-08-23-github-doc-harness-spec.md`.
Written 2026-08-24, after #36 merged as `355dbf2`. **REVISION 2** — revision 1 carried a
contradiction that defeated the whole drift check; see "What the gates changed".

```callout
info | Read this first — every number here was measured today, not carried
The harness is RUNNING on this host as of this design (loopback only, decision D27), so the
publish and serve paths below are probed facts rather than intentions. Where a figure disagrees
with the epic's earlier text, the figure here is the fresh measurement and it says so.
```

## What this child ships

A backfill script, the reviewed mapping it consumes, per-row activation gated on a byte-compare,
a written outcome report, and the parallel-run documentation. Vercel teardown stays out of scope,
and so does any change to `publish_doc.py` or to `harness/`.

## `platform_apis:` — the feasibility declaration, ten live probes

| API | How it was probed | What came back |
| --- | --- | --- |
| `vercel project list -F json --limit 100 [--next <ms>]` | ran, twice, to exhaustion | `{"projects": [{deprecated, id, latestProductionUrl, name, nodeVersion, updatedAt}], "pagination": {"next"}, "contextName", "elapsed"}` — 100 per page, **181 rows today**, and **no git or repository metadata at all** |
| harness `POST /v1/deployments` | ran, both body shapes | the manifest goes **FLAT**, with `expected_active` beside it. Nested under a `manifest` key is a **422 `name is required and is absent`**. Success is **201** `{deployment_id, name, commit_sha, assets, cache_warmed}` |
| **CAS: `expected_active: null` on an ABSENT name** | ran | **201**, `cache_warmed: true` |
| **CAS: `expected_active: null` on a PRESENT name** | ran | **409** `{"error": "stale publisher", "active_deployment_id": 2}` — a null baseline creates ONLY when absent |
| **CAS: a STALE id** | ran | **409**, and **the served bytes did not change** (43,421 before and after) |
| **CAS: the MATCHING id** | ran | **201** with a new `deployment_id`, the read-back reports it active, and the served bytes become the new page (22,882 = 22,882) |
| harness `GET /v1/deployments/<name>` | ran | **200** `{name, active_deployment_id, commit_sha, published_at}`. An unknown name returns nulls, **not** a 404. `published_at` came back `""`, so nothing may depend on it |
| harness serving, `GET /` with `Host: <name>.<zone>` | ran | **200**, `Content-Type: text/html; charset=utf-8`, `Etag` = the sha256 of the bytes, `X-Doc-Deployment: 1`, `X-Doc-Origin: cache` |
| `publish_doc.build_manifest` + `validate_manifest` | ran, imported by path | reusable unchanged. `content_type` must stay absent or the publish is a 422 |
| a live Vercel doc page | ran | **200**, and the bytes **differ** from the committed page — see the next section |

The four CAS rows exist because a review finding said, correctly, that one successful 201 proves
request shape and nothing about the semantics this design leans on. They are measured now.

## Three measured facts, and each one changes the design

### 1. Drift is the normal case, not the exception

The first row probed — `design-doc-publish-plan-campaign` — compares like this:

| Source | Bytes | sha256 (first 16) |
| --- | --- | --- |
| committed `docs/planning/campaign-log.html` at `355dbf2` | 43,421 | `7c4e10c44f8856d4` |
| the harness serving it, published from that commit | 43,421 | `7c4e10c44f8856d4` |
| the live Vercel page | 34,900 | `9fd7d5b78df62970` |

The GitHub-backed side is **byte-identical to the commit**, which is the half that matters for
correctness. The Vercel side is stale, because that page was updated in the #36 PR and Vercel was
never redeployed — and by then Vercel was no longer the deploy target.

So acceptance criterion 2's compare is a **drift detector that will fire often**. Any doc edited
since its last Vercel deploy fails it. The design therefore treats a mismatch as an ordinary,
expected outcome with its own bucket, never as an error, and the report distinguishes:

- **live** — provenance reviewed, the TARGET bytes committed and reachable, the compare passed
  byte-for-byte, the production publish succeeded under CAS, and the served page verified;
- **flagged** — everything else, always with exactly one reason: `mapping_not_found`,
  `mapping_ambiguous`, `mapping_invalid`, `uncommitted_or_unreachable`, `source_unavailable`,
  `vercel_changed`, `byte_mismatch`, `target_name_collision`, `stage_publish_failed`,
  `target_occupied`, `cas_conflict`, `final_verification_failed`, `skipped_by_reviewer`.

Plus one **campaign-level** outcome, `inventory_failed`, because a truncated or invalid listing is
not a row condition and must never be reported as a complete campaign.

Two row outcomes, not three. The criterion's own words are "activated or flagged", and a `drifted`
bucket would have been a third state satisfying neither. Drift is `byte_mismatch`: a reason, not an
outcome. `source_unavailable` exists because a 429, a timeout or a missing `latestProductionUrl` is
a transport failure, and mapping one onto a content verdict would be a lie in the report.

```callout
warn | The consequence for AC 3, stated plainly rather than discovered at the end
"All projects end either activated or flagged" cannot mean "mostly activated". On today's evidence
a large share of the 181 rows will be flagged `byte_mismatch`. That is the criterion working, and
the report is the deliverable — not a high activation count.
```

### 2. `publish_doc.py` cannot talk to a local harness, so this script owns its control client

`assert_bearer_destination` permits the publish bearer over `http` only to
`^(?:localhost|127\.\d+\.\d+\.\d+|::1)$` or the `172.16/12` bridge range with an exact grant, and
over `https` only to `docs-control.3dstories.ca`. But `harness/routing.py:resolve_host` answers
only when the Host header is exactly `<one-label>.<configured zone>` — a shape no loopback literal
and no bare IP can take. The two halves cannot both be satisfied, which is why #36's live proof
stayed deferred even with the harness up.

This child does **not** fix that — `publish_doc.py` is out of scope. It carries its own thin
control client that sends `Host: docs-control.<zone>` to an operator-supplied address, exactly as
the verification probes did. `build_manifest` and `validate_manifest` are still imported and
reused; only the HTTP call is local.

### 3. The project count is live, so the report timestamps its own measurement

Today's walk returns **181 projects, 160 carrying a publication-purpose token**. The epic recorded
**179 / 163** from #34's walk earlier the same day. Two projects appeared in between, which is
what a workspace where sessions publish docs looks like. Nothing here hard-codes a total: the
report states the count it measured and the instant it measured it.

## What the gates changed, before anything was built

Three gates ran on revision 1: a cross-model **peer consult** (blind — it saw only the problem), the
in-repo **quality-bar rubric** (deep pass, 7 findings), and a cross-model **adversarial review** of
this document (11 findings, every one confirmed against the text rather than accepted on authority).
Records: `claude_docs/.wf2-state/37/step3_peer.json`, `step4_adversarial.json`.

```callout
crit | The contradiction that would have shipped, and it defeated the entire point
Revision 1 identified each document by finding the historical blob whose bytes MATCH the live Vercel
page, and then compared that same blob against Vercel. Identical by construction. So `byte_mismatch`
could essentially never fire, the drift detector was decorative, and — worse — a stale Vercel page
would have been re-published as the harness's live copy, migrating the OLD version of every drifted
document. Revision 2 separates the two questions: the hash match is PROVENANCE (which document is
this?), and the publish TARGET is the current committed page at the remote tip. The compare is then
target-versus-Vercel, which is a real question with a real answer.
```

The peer found the other structural hole: revision 1 published a row under its REAL name and
compared afterwards, so a mismatch would have left the wrong page live under a trusted name with no
way back — the control API has no deactivate, and `GET /v1/deployments/<name>` returns metadata only,
so a prior manifest cannot be reconstructed. Its three refinements were taken as well: identify by
hashing against git history rather than guessing from a name; seal the comparison into a short-lived
plan and re-check Vercel immediately before activating; and refuse a production name that is already
active and not this run's.

The remaining confirmed findings, and what each changed: no outcome for transport failures
(`source_unavailable`, `inventory_failed`); an editable mapping trusted on re-read (now re-validated
from scratch, `mapping_invalid`); a hyphenated name parsing to a valid but WRONG project (now every
viable split is searched, with a workspace-wide collision check); a POST that is not atomic with its
journal entry (now a write-ahead `pending` record); two rows resolving to one production name (now a
pre-flight uniqueness check plus ROW-scoped deployment ownership); a post-publish verification
failure that let the campaign continue with bad bytes live (now a campaign halt); an unguarded custom
control client (now a destination guard of its own); two overlapping predicates (now an explicit
decision order); staging rows appearing on the public index (now compare-before-publish, so only
rows about to activate are staged); a missing statement of where the bearer comes from; an omitted
`title`/`project`/`purpose` on the manifest; an unbounded history search; a false "one seam" claim in
the test plan; and a report headed for a directory that does not exist.

Declined, with reasons: the peer's eight subcommands and in-script `self-test` — five subcommands,
and the tests belong in the existing pytest suite, which is the established way here.

## The design

One new file, `scripts/backfill_vercel.py`, standard library only, five subcommands over one
append-only run directory. Every command is read-only unless given both an explicit `--execute`
flag and the digest of the plan it is executing.

| Command | What it does | Writes |
| --- | --- | --- |
| `inventory` | walk the Vercel listing to exhaustion, twice, until two snapshots agree | immutable snapshot + `measured_at`, or a recorded cutoff |
| `map` | for each row: fetch the live bytes, find the commit whose blob matches them | `mapping.json`, the human review surface |
| `stage` | publish under a staging label, fetch it, compare to a fresh Vercel fetch | per-row evidence, and a sealed activation plan |
| `activate` | re-check Vercel, then CAS-publish the production name and verify what it serves | per-row `live` or `flagged` |
| `report` | assert every row in the snapshot ended `live` or `flagged`, then write it up | the committed markdown report |

### `inventory` — bounded, and honest about not being atomic

`vercel project list -F json --limit 100`, following `pagination.next` until absent, then again. Two
consecutive agreeing walks become the row set. **Bounded** by `--max-walks` (default 3) and an
elapsed-time cap: on exhaustion the last fully completed walk is frozen as a **non-atomic cutoff
snapshot**, identified by its start and completion instants rather than by a single moment — a
paginated walk cannot establish an atomic set at an instant, and claiming otherwise would be false.
Rows first seen after that walk are reported separately, without asserting which side of any instant
they were created on. A non-zero `vercel` exit, a malformed listing, or a page missing its `projects`
array is **`inventory_failed`**: the campaign stops rather than reporting a partial walk as complete.

### `map` — provenance from the bytes, target from the tip

The naming convention `{project}-{purpose}-{ref}` narrows the search. It never decides the answer.

1. Fetch the live Vercel page with **`Accept-Encoding: identity`** — a gzipped body would make every
   byte-compare meaningless — and take its sha256. A missing `latestProductionUrl`, an auth failure,
   a timeout, or a 429 past its retry bound is **`source_unavailable`**, with the final transport
   error kept verbatim as evidence and never mapped onto a content verdict.
2. Enumerate **every** syntactically viable `{project}-{purpose}-{ref}` split whose project exists in
   `.rawgentic_workspace.json`, and search the union of those repositories. When more than one split
   is viable, or none is, search **all** projects: the hash is the evidence, not the name.
3. In each candidate repository, search committed `.html` blobs **through history**, not just at
   `HEAD`. Bounded, because ~30 repositories × all of history is not a search anyone should start:
   narrow to paths whose basename or parent directory carries the ref, then per candidate path run
   `git log --all --format=%H -- <path>` and resolve `git rev-parse <commit>:<path>`, comparing each
   blob's sha256 to the live hash. `--history-cap` bounds commits examined per path, and hitting it
   is RECORDED on the row, so a capped search is never reported as exhaustive. **Never assume `HEAD`
   produced the deployment** — most of these pages were published from a commit that is now old,
   which is the whole reason this searches history.
4. Before accepting a unique match, run a **workspace-wide collision check**: the same bytes in
   another repository make the row `mapping_ambiguous` listing every candidate, even when the
   narrowing had produced one. No match at all is `mapping_not_found`, with the naming evidence kept
   so a human can finish it by hand.
5. **The publish TARGET is a separate field from the provenance match.** Provenance answers "which
   document is this"; the target is that document's `.md`/`.html` pair **at the remote tip**, which is
   what a migration should serve. Both are recorded. Where the target hash equals the live Vercel
   hash the page never drifted; where it differs, `stage` flags `byte_mismatch` — now a question with
   a real answer rather than a tautology.
6. Assert the target blobs are committed and reachable from the tip commit, reusing
   `publish_doc.assert_blob_committed`, `assert_head_reachable` and `select_remote`. Not pushed →
   `uncommitted_or_unreachable`. **Nothing is ever auto-committed or auto-pushed** to make a row pass.
7. **Production-name uniqueness** is enforced across the whole mapping before anything is staged. Two
   rows resolving to one name are both `target_name_collision` and neither is staged, because
   whichever went second would replace the first under a trusted name.

`mapping.json` is the review surface: a human may correct a guess, delete a row (recorded as an
explicit `skipped_by_reviewer` tombstone rather than a silent absence), or add one by hand. Its
sha256 is the **mapping digest**.

### The mapping is UNTRUSTED input on every re-read

`stage` and `activate` re-validate every row from scratch: schema, then **recompute** the blob id and
sha256 from the recorded `commit:path`, then re-run reachability for that exact commit. Any mismatch
is `mapping_invalid` and nothing is published. The digest proves the file has not changed since it was
reviewed; it says nothing about whether its contents are TRUE, and a hand-edited row is exactly where
an untrue one comes from.

### `stage` — compare first, then prove the harness serves it

Per row, independently, inside an exception boundary. The decision order is explicit, because two
predicates otherwise overlap:

1. Re-fetch the live Vercel page. **Changed since `map`** (hash differs from the recorded one) →
   `vercel_changed`, and stop. This test comes first and settles it.
2. Unchanged → compare it to the **target** bytes. Different → `byte_mismatch`, and stop, having
   touched no registry at all. This is the drift detector, and nothing has been published.
3. Build the manifest with `publish_doc.build_manifest` and `validate_manifest` (unchanged,
   `content_type` stays absent or the publish is a 422), then add the three optional metadata keys
   the harness accepts and the derived index renders — `title`, `project`, `purpose`
   (`harness/manifest.py:215`, `harness/registry.py:196`) — as a dict update after the call, so
   `publish_doc.py` stays untouched. Without them a backfilled row lands on the index with no
   grouping at all.
4. **Write-ahead, then publish.** Durably record `pending` — target name, intended content hash,
   `expected_active`, row identity — BEFORE sending, and record the returned deployment id
   immediately after. A crash between the two is then recoverable: on resume, reconcile the pending
   intent against `GET` metadata and the served bytes rather than guessing.
5. Publish under a **staging label** (`bf<run>-<name>`, truncated to a valid 63-char DNS label) with
   `expected_active: null` — measured to create only when the name is absent and to 409 otherwise, so
   an existing staging name is `stage_publish_failed`, never an overwrite.
6. Wait for `cache_warmed: true` (`false` is a failure, not a pass), then `GET /` on
   `Host: <staging>.<zone>` and compare to the target bytes. Not identical →
   `final_verification_failed`; the known candidate is a percent-encoded asset name (#34's boundary
   learning), and it is worth stopping the campaign over rather than continuing.
7. A row passing all of that enters the **activation plan**, sealed with its own digest and an expiry.

```callout
warn | Staging rows are REAL registry rows and they appear on the public index
Checked, not assumed: `Registry.index_snapshot` selects every active row with no filter
(`harness/registry.py:196`) and `render_index` renders all of them. Comparing before publishing is
what keeps that number small — only rows about to activate are ever staged. Every staging label and
deployment id is listed in the report, and the runbook says to retire them, because the control API
has no delete.
```

### `activate` — the only command that touches a production name

1. Re-check **both** digests, the activation plan's and the mapping's, and re-validate the row as
   above. A row a human deleted after `stage` must not activate, and a plan digest cannot see that.
2. Re-fetch Vercel and require the sealed hash. Different → `vercel_changed`, no publish.
3. `GET /v1/deployments/<name>`. Active and **not this ROW's own recorded deployment** →
   `target_occupied`. Row-scoped, not run-scoped: a run-wide exception would let a second row replace
   the first row's page under a shared name.
4. Write-ahead `pending`, then publish the **same manifest bytes** staging proved, with
   `expected_active` set to what step 3 read. A 409 → `cas_conflict` (measured: the 409 body carries
   the current `active_deployment_id`, and the served bytes do not change).
5. `GET /` on the production host and verify bytes, ETag and `X-Doc-Deployment`. **A failure here
   halts the whole campaign**, because the production name has already changed and per-row isolation
   would otherwise leave unverified bytes live under a trusted name while the run carried on. It
   journals the deployment id, prints an operator-visible error, and refuses further activation until
   a verified forward repair has run.

### Credentials and the destination guard

The publish bearer and the Vercel session come from the **environment only**. Neither is written to
the run directory, the journal, the report or an error message, and no HTTP error body is echoed
verbatim into output — that exact defect was found and fixed during #36's review, where a server
could reflect the `Authorization` header into its own JSON. The report records that a token was
present, never any part of its value.

Because this client cannot use `assert_bearer_destination`, it carries an equivalent of its own,
checked **before** `Authorization` is attached: the base URL must be `http` with an **IP literal**
whose connected peer is loopback, or an address explicitly granted by an environment variable naming
that exact `host:port`; DNS names, redirects, proxies and non-HTTP schemes are refused. The validated
peer and the Host header are logged, so what the token was sent to is a matter of record rather than
of trust. Dropping the guard because the URL "is local" is precisely how a typo or a hostile address
gets a bearer token.

### Undo, stated honestly

There is no deactivate. Undo is a **forward repair**: re-publish a previously journaled good
manifest with the current deployment id as `expected_active` — measured to work, and to 409 rather
than clobber when the id is stale. For a name this run activated from
nothing, there is no "absent" to return to — which is why comparing before publishing, the staging
step, the digest gates, the row-scoped ownership, the null-baseline CAS and the collision check all
exist. Staging deployments also persist as
registry artifacts; the report lists them so an operator can decide.

### The report

`docs/measurements/2026-08-24-37-backfill-<run>.md`, committed. `docs/measurements/` already
holds this project's run telemetry, so the report reuses an existing home rather than inventing a
`docs/reports/` convention for one file. It carries the snapshot's start and completion
instants (or the cutoff plus the separately-listed later additions), one line per row with outcome
and reason, totals per reason that add up to the row count, and every staging label left behind. It **asserts** that every row in the snapshot ended `live` or `flagged`
and fails if one did not — that assertion is what makes acceptance criterion 3 checkable rather
than claimed.

### The parallel-run window

Documented in `docs/runbooks/`, honestly: for a `live` row the dual-host window **opens at
activation and does not close**, because deleting the Vercel project is out of scope. The runbook
records which rows are live where, the last instant byte identity was verified, how to forward-repair
a row, and the order to retire Vercel projects in once somebody decides to. The window cannot be
*public* until a hostname resolves, which is #35's remaining owner-gated work.

### Tests, offline by construction

`scripts/tests/test_backfill_vercel.py` in the existing suite. Temporary git repositories give real
blob ids and real history. There are **two** injected seams, not one, because the inventory is a
subprocess (`vercel project list`) while the page fetch and the harness calls are HTTP — a single
seam would have been a lie in the design and a fake in the tests.

Covered: history-blob discovery in an OLD commit; a project name containing a purpose word; a ref
that is itself a purpose token; every-viable-split enumeration; the workspace-wide collision check;
gzip refused by `Accept-Encoding: identity`; each `source_unavailable` transport case and its retry
bound; `inventory_failed` on a malformed listing and on a non-zero CLI exit; the walk bound and the
non-atomic cutoff; a hand-edited `mapping_invalid` row; a `skipped_by_reviewer` tombstone;
`target_name_collision`; **no publish of any kind for a row that fails the compare**, asserted by
spying on the transport, which is the invariant this whole design turns on; the write-ahead record
present before the POST and reconciled on resume; `cache_warmed: false` treated as a failure; a
served-bytes mismatch HALTING the campaign rather than flagging one row; row-scoped
`target_occupied`; `cas_conflict`; digest and expiry enforcement; the destination guard refusing a
DNS name and a redirect before the bearer is attached; per-row isolation for pre-publish failures;
and the report's completeness assertion FAILING when a row is missing. No test needs Vercel, GitHub
or a running harness.

## Risks, and what each one costs

| Risk | Why it is bounded |
| --- | --- |
| A page's live bytes were never committed anywhere, or two repositories hold identical generated pages | Exact-hash matching plus a mandatory human review makes false attribution hard, and both cases have their own flag reason. Some rows legitimately stay flagged, and that is the honest outcome. |
| Continuous publishing moves the inventory or the Vercel bytes mid-campaign | Two agreeing snapshots or an explicit cutoff, a sealed plan with an expiry, and a re-fetch immediately before activation. Final closure wants a brief publishing pause, which the runbook says. |
| A mistaken activation cannot be undone to "absent" | Staging first, digest gates, null-baseline CAS, and the occupied-name refusal. Undo is a forward repair, and the design says so rather than implying a rollback exists. |
| 181 rows × several HTTP calls is slow, or hits a rate limit | Rows are independent and journaled, so a run resumes; `--limit` bounds one pass; GitHub fetches happen inside the harness under its own call budget. |
| Staging labels accumulate in the registry | Every one is listed in the report with its label and deployment id, so cleanup is a decision somebody can make rather than a surprise. |
| A crash between a POST and its journal entry | The write-ahead `pending` record, and a resume that reconciles against `GET` metadata and the served bytes rather than guessing. |
| The bearer reaching somewhere it should not | The destination guard, checked before `Authorization` is attached, with the validated peer logged. |

## What this child does NOT do

It does not touch `publish_doc.py` or `harness/`. It does not delete a Vercel project. It does not
make the harness public — no DNS, no Cloudflare, nothing outward-facing. It does not run the full
181-row campaign: the owner asked for a real byte-compare on a **sample**, so the sample runs against
the local harness and the full campaign is deferred with its reason recorded. And it does not claim
the migration is finished: with the harness reachable only on loopback, an activated row is live for
this host, and the public parallel-run window still waits on #35.
