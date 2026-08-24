# GitHub-doc harness — self-hosted replacement for the Vercel deploy target

Status: FINAL DRAFT. Peer-consulted (qwen3.8-max-preview + gpt-5.6-sol) and
adversarially reviewed (deepseek-v4-pro, 10 findings triaged below). Awaiting owner
confirmation.

## Problem

`publish_doc.py` renders, lints, deploys and verifies one design doc per run. Today the
deploy target is Vercel: every doc becomes a Vercel project named
`{project}-{purpose}-{ref}` at `https://<name>.vercel.app`. The owner wants doc pages to
live ONLY in the GitHub repos (the rendered HTML is already committed via PR). A small
self-hosted harness serves each page at `https://<name>.3dstories.ca` by fetching it
from GitHub. The only server-hosted document is the derived index.

## Decided by the owner (2026-08-23 interview)

- D1. Host: Docker on 10.0.17.205 (Docker 29.7.2 confirmed; no cloudflared there yet).
- D2. URLs: `https://<name>.3dstories.ca`. Name derivation unchanged from
  `derive_name()`: `{project}-{purpose}-{ref}`, lowercase, hyphens. Underscores in any
  input become hyphens (CA/B ballot SC12 bans underscores in certificate hostnames).
- D3. Index at `https://docs-index.3dstories.ca`, DERIVED, never hand-edited (preserves
  the 2026-08-01 owner decision). The index host renders SERVER-SIDE from the registry
  snapshot; `index/build_index.py`'s presentation code becomes the shared renderer the
  harness imports. No generated index file is ever committed or deployed. (rev: F6)
- D4. Pages live only in GitHub. The harness keeps a cache and the registry, nothing else.
- D5. Everything behind Cloudflare Access (login). Some source repos are private
  (3D-Stories/rawgentic is PRIVATE; design-doc-publish is PUBLIC).
- D6. DNS on Cloudflare (confirmed). No wildcard record yet (confirmed by dig). Plan:
  cloudflared container, wildcard CNAME `*.3dstories.ca` -> `<TUNNEL_ID>.cfargotunnel.com`,
  ingress `*.3dstories.ca` -> harness, catch-all 404. No inbound ports.
- D7. Skill stages unchanged: render, source gate, name, lint, deploy, verify. The exit
  code is the verdict; no stage skippable.

## Architecture

One compose stack on .205: `harness` (Python, stdlib-style HTTP service) + `cloudflared`.
Two volumes: a durable one for the registry (SQLite), a disposable one for the blob cache.

### Registry and publish contract (S1, S2)

- A publish creates an IMMUTABLE deployment: `{name, repo, commit_sha, entry_path,
  assets: [{url_path, repo_path, blob_id, size, sha256}], title, project, purpose,
  published_at}`. Branch names are provenance only, never serving pointers.
- Hash roles (rev: F4): `blob_id` is the Git SHA-1 object id — the Blob API fetch key
  and the cache key. `sha256` is the SHA-256 of the file bytes, computed by the
  publisher — the integrity check. The server MUST verify the fetched blob's SHA-256
  against the declared `sha256` before caching or serving it.
- SQLite (WAL) stores the rows. One atomic active-deployment pointer per name; prior
  rows stay as history. The POST body carries `expected_active` — the deployment id the
  publisher believes is current, or null for a first publish (rev: F3). The server
  compares-and-swaps against it: a stale publisher gets a 409, never a silent overwrite.
- Control API: `POST https://docs-control.3dstories.ca/v1/deployments`. The control host
  IS covered by Cloudflare Access like every other harness host, and the request must
  ALSO carry the bearer secret DOC_HARNESS_PUBLISH_TOKEN (rev: F1). Two tokens is
  deliberate defense in depth, not redundancy: Access gates at the Cloudflare edge and
  can be misconfigured (S5 defers its exact layout); the bearer gates inside the app and
  survives an Access mistake. Control routes exist only on that host; CORS disabled.
- Publish-time verification (rev: F5): the server resolves the commit's tree and blob
  hashes itself, using the SAME token it serves with (DOC_HARNESS_GITHUB_TOKEN, below).
  That token must read every doc repo, including the private ones.
- Why not qwen's registry-as-a-git-file: this workspace runs concurrent publishes, and a
  shared registry file re-creates the lost-row race the 2026-08-01 index decision
  removed. Contents-API 409 retry-merge logic in every publisher is more code in a
  worse place than one CAS in the server.

### Serving path

- Host header -> name -> active deployment -> URL-path lookup in the manifest ->
  content-addressed cache (key: blob_id) -> on miss, Git Blob API fetch (raw media
  type), SHA-256-verified, then cached. Blobs are immutable, so entries need no TTL.
- Cache bound (rev: F7): LRU, 2 GiB default, env-tunable (DOC_HARNESS_CACHE_MAX_BYTES),
  least-recently-used eviction when full, on the disposable volume.
- The harness serves the committed bytes UNMODIFIED — no HTML rewriting of any kind.
  The rendered pages are standalone with relative sibling-asset paths, so the bytes a
  browser gets are the bytes in git; that is what makes byte-equality verification
  sound (rev: F2 declined — see triage).
- Assets serve from the manifest (S3, from gpt). qwen's HTML link-rewriting is REJECTED:
  fragile (its own risk list says so), and `stage_assets()` already enumerates the
  sibling assets — the publisher declares them; nothing needs rewriting.
- Failure split (rev: F8): a Blob API 404 for an active deployment's blob means the SHA
  is gone (for example GC of an abandoned, never-merged PR) — cold miss: 503 with a
  diagnostic naming the dead SHA, never cached; warm cache: serve the cached bytes with
  `X-Doc-Origin: cache` plus an alert log line, since they are still the active
  deployment's exact bytes. A network/5xx failure is an OUTAGE: serve cached bytes the
  same way; cold miss during an outage is a 503 with a plain diagnostic.
- Unknown host: 404 with a plain-text diagnostic (rev: F9 — 421 dropped; boring wins).
  Reject dot segments and undeclared paths.
- Auth to GitHub: a fine-grained read-only PAT scoped to the doc repos (env name:
  DOC_HARNESS_GITHUB_TOKEN). ponytail: PAT first; a GitHub App with short-lived
  installation tokens is the upgrade path if rotation or limits bite.
- Index host renders server-side from the registry snapshot (D3), ETag from a registry
  generation counter.

### verify_live (S4)

- The publish response returns a deployment id. verify_live fetches
  `https://<name>.3dstories.ca/?__deployment=<id>` with Access service-token headers,
  redirects DISABLED. Pass requires: 200, `X-Doc-Deployment: <id>` echoed, text/html,
  and byte equality with the just-rendered page. An Access login redirect is a failure.
  Repeat for each declared asset. A stale deployment id gets a 409 from the harness.

### Publish-before-merge (S2 continued)

- The rendered HTML is committed and pushed on the PR branch; publish pins that commit
  SHA. Once the PR merges, the SHA is an ancestor of main and stays reachable forever.
  An abandoned, never-merged PR eventually lets GitHub GC the SHA: serving then follows
  the F8 failure split above. Accepted for v1; a post-merge reconciler that re-points
  provenance at the merge commit is hardening backlog, not v1.

### Cloudflare Access layout (S5 — layout deferred to implementation, gpt's warning kept)

- CAUTION (gpt): ONE wildcard Access application on `*.3dstories.ca` would put every
  OTHER proxied subdomain of the zone behind a login too. Before wiring Access, inventory
  the zone's existing records. If nothing else is proxied on subdomains, one wildcard
  Access app is the simple, right answer. Otherwise the harness manages exact-host
  Access entries at publish time (one Cloudflare API call per new name). Either way the
  covered set INCLUDES docs-control and docs-index (F1).
- Two policies either way: the owner's identity for humans, plus one Service Auth
  policy (service token) for publish verification and CI.

## publish_doc.py changes

- Stages 1–4 (render, source gate, derive name, lint) unchanged. Extend the lint gate:
  every same-origin resource referenced by the HTML must appear in the staged manifest.
- Stage 5 deploy: replace `vercel link/deploy/alias` with the one control-API POST
  (payload includes `expected_active`; the previous publish's id is read back from the
  control API first, null on first publish).
- Stage 6 verify: as above. Same StageError discipline, exit code is the verdict.
- `--new-project` and `--vercel-scope` retire; `derive_name()`'s 35-char alias cap can
  relax to the DNS 63-char label limit (kept as a lint warning, not dropped silently).
- `index/build_index.py`: presentation code becomes the harness's shared renderer (D3).

## Migration (S7)

- Backfill script builds a reviewed mapping: Vercel project name -> repo, path, commit.
  `vercel project ls` is inventory only (gpt) — the HTML's home repo/path comes from the
  committed files. Each row activates only after a byte-compare of the GitHub-backed
  page against the live Vercel page. A compare FAILURE flags that row for manual review
  and blocks only that row (rev: F10) — it is the drift detector for docs whose deployed
  bytes never matched their committed bytes. Run both hosts in parallel for a short
  window; Vercel teardown timing is the owner's call. 179 projects as of 2026-08-24,
  163 of them carrying a design-doc-publish purpose token.

## Failure modes designed for

Do now: registry row -> deleted repo/file (F8 split above); PAT expiry (500-class with
alert log line, never a silent empty page); rate limit (cache + authorized conditional
requests: 304s are free per GitHub's best-practices doc); oversized file (Blob API to
100 MB, publish-time size cap enforced).
Later: LFS pointers, submodules (reject at publish with a named reason); SQLite backup
and restore runbook; cache-volume loss (rebuilds from GitHub by design).

## Out of scope

- Editing any workflow skill other than design-doc-publish's own publish path.
- Public (login-free) access; revisit later per-page.
- HTML content rewriting of any kind.

## Synthesis log (peer consult, 2026-08-23)

- From gpt-5.6-sol: immutable SHA-pinned deployments + asset manifest; SQLite registry +
  CAS + control host; deployment-id verify with redirects-off; wildcard-Access warning;
  staged migration with byte-compare; manifest-completeness lint.
- From qwen3.8-max: ETag-conditional fetching and free-304 rate-limit math; serve-stale
  bounded to the active deployment; Blob API over Contents API for raw bytes.
- Rejected: qwen's registry-as-code in a GitHub repo (concurrency; see S1); qwen's HTML
  asset rewriting; qwen's shared service token across purposes (tokens stay separate).
- Deferred from gpt (proportionality — hardening backlog, not v1): GitHub App auth,
  cache prewarming, idempotency keys, per-publish Access orchestration as a hard gate,
  append-only rollback API, image digest pinning.

## Adversarial review triage (deepseek-v4-pro, 2026-08-23, 10 findings)

Report: docs/reviews/2026-08-23-github-doc-harness-spec-md-2026-08-23.md

- F1 Critical FIXED — control-host auth clarified: behind Access AND bearer, defense in
  depth stated. F3 High FIXED — `expected_active` CAS field added to the POST body.
- F4 High FIXED — blob_id (Git SHA-1) vs sha256 roles split; server-side SHA-256
  verification mandated. F5 High FIXED — publish-time verification uses
  DOC_HARNESS_GITHUB_TOKEN, private repos included. F6 High FIXED — server-side index
  render mandated, implementer's choice removed.
- F7 Medium FIXED — 2 GiB env-tunable LRU bound. F8 Medium FIXED — dead-SHA vs outage
  split specified. F9 Medium FIXED — 421 replaced with 404.
- F2 Critical DECLINED — its premise is that served HTML differs from rendered HTML by
  asset-URL rewriting. The design rewrites nothing: the harness serves the committed
  bytes unmodified and pages are standalone with relative paths, so byte equality is
  exactly right. A clarifying sentence was added to the serving path.
- F10 Medium PARTIAL — same premise error as F2 for the compare itself, but the finding
  usefully surfaces historical drift; a compare failure now flags the one row for
  manual review instead of reading as a migration blocker.
