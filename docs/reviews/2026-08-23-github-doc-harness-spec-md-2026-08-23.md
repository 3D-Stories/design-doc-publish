# Adversarial Review — docs/planning/2026-08-23-github-doc-harness-spec.md

- Date: 2026-08-23
- Artifact type: spec
- Reviewer: Codex (model deepseek-v4-pro, reasoning effort config-default)
- Findings: 10 (Critical 2, High 4, Medium 4, Low 0)
- **[WARNING]** Possible secrets detected: token.

## Summary

The artifact describes a self-hosted harness to replace Vercel deploys for design docs, serving pages from GitHub via Cloudflare Access. It contains several internal contradictions and underspecifications that would cause implementation failures or security gaps if built as written.

## Findings

### 1. [Critical] internal-consistency · 0.95 confidence — Cloudflare Access layout (S5) and Control API paragraph

> Control API: POST https://docs-control.3dstories.ca/v1/deployments, guarded by BOTH a Cloudflare Access service token AND a bearer secret (name: DOC_HARNESS_PUBLISH_TOKEN). Control routes exist only on that host.

The control API is described as requiring BOTH a Cloudflare Access service token AND a bearer secret. However, the Cloudflare Access layout section (S5) states that Access is applied to '*.3dstories.ca' and that the service token policy is 'for publish verification and CI'. The control host 'docs-control.3dstories.ca' falls under the wildcard, so it would be behind Access. But the artifact also says 'Control routes exist only on that host' — implying the control host is separate from the doc-serving hosts. The contradiction is that if the control host is behind the same wildcard Access application, then the 'bearer secret' is redundant with the Access service token (both are bearer tokens presented in headers). If the control host is NOT behind Access, then the 'guarded by BOTH' claim is false. The concrete failure: an implementer cannot determine the correct authentication architecture, leading to either a security hole (control API exposed without Access) or broken integration (double auth that CI cannot satisfy).

**Recommendation:** In the 'Cloudflare Access layout (S5)' section, explicitly state whether docs-control.3dstories.ca is covered by the wildcard Access application or is a separate host with its own Access policy. If covered, remove the redundant 'bearer secret' requirement or explain why both are needed. If not covered, add a separate Access application for the control host and clarify that the bearer secret is the only auth for the control API.
**Ambiguity:** The artifact contradicts itself on whether the control host is behind Access and whether both auth mechanisms apply.

### 2. [Critical] internal-consistency · 0.9 confidence — verify_live (S4) and Serving path section

> verify_live fetches `https://<name>.3dstories.ca/?__deployment=<redacted> with Access service-token headers, redirects DISABLED. Pass requires: 200, `X-Doc-Deployment: <id>` echoed, text/html, and byte equality with the just-rendered page.

The verify_live step requires byte equality between the fetched page and 'the just-rendered page'. However, the serving path section states that the harness serves assets from a content-addressed cache keyed by blob_id, and that 'qwen's HTML link-rewriting is REJECTED'. This means the HTML served by the harness contains absolute or relative URLs to assets (images, CSS, JS) that reference the GitHub repo paths. The 'just-rendered page' was rendered locally and may contain different asset URLs (e.g., local file paths or relative paths that differ from the served URLs). The artifact does not specify any URL normalization or rewriting, so byte equality is impossible unless the local render output is identical to the served output. The concrete failure: verify_live will always fail because the served HTML contains URLs that differ from the locally rendered HTML, or the implementer will be forced to add URL rewriting (which the artifact explicitly rejects).

**Recommendation:** In the verify_live section, specify that byte equality comparison must be performed after normalizing asset URLs in both the local render and the served page to a canonical form (e.g., relative paths from the doc root), or change the comparison to a structural/DOM equality check that ignores URL differences. Alternatively, accept that the harness must perform URL rewriting at serve time (contradicting the rejection of qwen's approach) and update the serving path section.
**Ambiguity:** The artifact rejects URL rewriting but requires byte equality between locally rendered and served HTML, which is contradictory.

### 3. [High] completeness · 0.85 confidence — Registry and publish contract (S1, S2) and Control API paragraph

> The harness stores rows in SQLite (WAL). One atomic active-deployment pointer per name; prior rows stay as history. Concurrent publishes of one name resolve by compare-and-swap: the stale publisher gets a 409, never a silent overwrite.

The artifact specifies a compare-and-swap (CAS) mechanism for concurrent publishes but does not define the CAS token or version field. CAS requires a known previous state to compare against — typically a version number, timestamp, or previous deployment ID. The publisher must include this in the POST request, but the control API specification only mentions the deployment payload, not a CAS token. Without this, the server cannot distinguish between 'I expect to replace deployment X' and 'I am creating a new deployment unconditionally'. The concrete failure: the implementer will either implement a last-write-wins race condition (defeating the purpose of CAS) or will have to invent a CAS token scheme that may not match the author's intent.

**Recommendation:** In the control API specification, add a required field to the POST body (e.g., `expected_active_deployment_id` or `cas_version`) that the publisher must provide, and specify that the server compares this against the current active deployment pointer before activating the new deployment.

### 4. [High] completeness · 0.8 confidence — Registry and publish contract (S1, S2)

> A publish creates an IMMUTABLE deployment: `{name, repo, commit_sha, entry_path, assets: [{url_path, repo_path, blob_id, size, sha256}], title, project, purpose, published_at}`.

The deployment record includes `blob_id` and `sha256` for each asset, but the artifact does not specify whether these are the same value or different. GitHub's Blob API uses SHA-1 blob IDs (git object hashes), while `sha256` typically refers to SHA-256. The serving path says 'content-addressed cache (key: blob_id)' and 'on miss, Git Blob API fetch', implying blob_id is a Git SHA-1. But the manifest also includes `sha256`, which is a different hash. The artifact does not explain how these two hashes relate, which one is used for integrity verification, or whether the server verifies the sha256 against the fetched blob bytes. The concrete failure: the implementer may use the wrong hash for cache keys or integrity checks, leading to cache poisoning or failed verification.

**Recommendation:** In the deployment record specification, clarify that `blob_id` is the Git SHA-1 object hash (used for Blob API fetches and cache keys) and `sha256` is a separate SHA-256 hash of the file content used for integrity verification. Specify that the server MUST verify the fetched blob's SHA-256 against the declared `sha256` before caching or serving.

### 5. [High] feasibility · 0.75 confidence — Control API paragraph and Auth to GitHub paragraph

> The server resolves the commit's tree itself, verifies each declared file's blob hash, then activates.

The artifact states the server resolves the commit's tree and verifies each declared file's blob hash. However, the deployment manifest is submitted by the publisher via the control API. The server is expected to independently verify that the declared files exist at the declared paths in the declared commit. This requires the server to have read access to the source repository (which may be private, per D5: '3D-Stories/rawgentic is PRIVATE'). The artifact mentions a 'fine-grained read-only PAT scoped to the doc repos' for serving, but does not specify whether this same token is used for publish-time verification or if a separate token with broader scope is needed. The concrete failure: the server may be unable to verify private repo assets during publish, either failing all publishes or silently accepting unverified manifests.

**Recommendation:** In the control API section, explicitly state that the server uses the same DOC_HARNESS_GITHUB_TOKEN for publish-time tree verification, and confirm that this token has read access to all repos that may be published (including private ones). If a separate token is needed, specify its name and scope.

### 6. [High] internal-consistency · 0.85 confidence — Decided by the owner (D3) and publish_doc.py changes section

> Index at `https://docs-index.3dstories.ca`, DERIVED, never hand-edited (preserves the 2026-08-01 owner decision). Reuse `index/build_index.py` rendering; swap the data source from `vercel project ls` to the harness registry.

The index is described as being at 'docs-index.3dstories.ca' and 'DERIVED, never hand-edited'. Later, the publish_doc.py changes section says: 'index/build_index.py: data source swaps to GET docs-control/v1/deployments (or the index host renders server-side and build_index becomes the shared renderer — implementer's choice, same output either way)'. This creates a contradiction: if the index host renders server-side, then the index is derived from the registry, which is consistent. But if build_index.py is used as a client-side script that fetches from the control API, then the index HTML must be generated and committed somewhere, which contradicts 'DERIVED, never hand-edited' (committing a generated file is a form of editing/deployment). The artifact leaves this choice to the implementer without resolving the contradiction. The concrete failure: the implementer may choose the client-side option and end up with a hand-maintained or CI-committed index file, violating the owner's requirement.

**Recommendation:** Remove the implementer's choice and mandate that the index is rendered server-side by the harness from the registry snapshot. Specify that the index host serves the rendered HTML directly, never from a committed file.
**Ambiguity:** The artifact gives the implementer a choice that contradicts the owner's requirement.

### 7. [Medium] completeness · 0.7 confidence — Serving path section

> Host header -> name -> active deployment -> URL-path lookup in the manifest -> content-addressed cache (key: blob_id) -> on miss, Git Blob API fetch (raw media type). Blobs are immutable, so cached entries need no TTL; the cache is a bounded LRU on the disposable volume.

The serving path describes a cache keyed by blob_id with no TTL, on a disposable volume. The failure modes section says 'cache-volume loss (rebuilds from GitHub by design)'. However, the artifact does not specify the cache eviction policy for the bounded LRU — what is the maximum size, and what happens when the cache is full? Without a size limit, the disposable volume could fill up, causing writes to fail. The concrete failure: the cache volume fills up, new cache entries cannot be written, and every request becomes a GitHub API call, potentially hitting rate limits.

**Recommendation:** In the serving path section, specify the maximum cache size (e.g., 1 GB or a percentage of the volume) and the eviction policy (e.g., least-recently-used eviction when the cache exceeds the limit).

### 8. [Medium] completeness · 0.65 confidence — Publish-before-merge (S2 continued) and Serving path section

> An abandoned, never-merged PR eventually lets GitHub GC the SHA: the page then 503s with a diagnostic naming the dead SHA. Accepted for v1; a post-merge reconciler that re-points provenance at the merge commit is hardening backlog, not v1.

The artifact accepts that abandoned PRs will eventually cause 503 errors when GitHub garbage-collects the commit SHA. However, it does not specify how the harness detects this condition or how the diagnostic is generated. The serving path says 'a cold miss during an outage is a 503 with a plain diagnostic', but a GC'd SHA is not an outage — the blob simply doesn't exist. The harness needs to distinguish between 'GitHub is down' (serve cached bytes if available) and 'SHA no longer exists' (always 503). The artifact does not specify how the harness makes this distinction. The concrete failure: the harness may incorrectly serve cached bytes for a GC'd SHA during a transient GitHub error, or may fail to generate the promised diagnostic.

**Recommendation:** In the serving path or failure modes section, specify that a 404 from the Git Blob API for a blob that is part of the active deployment should result in a 503 with a diagnostic naming the dead SHA, and that this response should NOT be cached or served from cache.

### 9. [Medium] consistency · 0.6 confidence — Serving path section

> Reject dot segments, undeclared paths, unknown hosts (421).

The serving path says to reject 'unknown hosts' with a 421 status code. HTTP 421 means 'Misdirected Request' and is defined in RFC 7540 for HTTP/2 when a request is sent to a server that cannot produce a response for the request's Host header. However, the artifact also mentions Cloudflare Access and cloudflared tunnel, which likely terminate TLS and forward requests over HTTP/1.1 or HTTP/2. The 421 status is specific to HTTP/2 and may not be appropriate for HTTP/1.1. The artifact does not specify the HTTP version(s) the harness supports. The concrete failure: the harness may return 421 on HTTP/1.1 connections, which is non-standard and may confuse clients or intermediaries.

**Recommendation:** Specify that the harness returns 421 for unknown hosts on HTTP/2 connections, and 404 or 400 for unknown hosts on HTTP/1.1 connections, or clarify that the harness only supports HTTP/2.

### 10. [Medium] feasibility · 0.55 confidence — Migration (S7)

> Backfill script builds a reviewed mapping: Vercel project name -> repo, path, commit. `vercel project ls` is inventory only (gpt) — the HTML's home repo/path comes from the committed files. Each row activates only after a byte-compare of the GitHub-backed page against the live Vercel page.

The migration section requires a byte-compare of the GitHub-backed page against the live Vercel page before activation. However, as noted in the verify_live finding, byte equality between the locally rendered page and the served page is problematic due to URL differences. The same issue applies here: the GitHub-backed page (served by the new harness) will have different asset URLs than the Vercel-served page (which may have Vercel-specific URLs or different path structures). The byte-compare will fail for all pages, blocking migration. The concrete failure: migration cannot proceed because no pages pass the byte-compare.

**Recommendation:** Change the migration activation criterion from byte-compare to a structural comparison (e.g., DOM tree equality after normalizing URLs) or a manual visual review, or specify that the byte-compare is performed after URL normalization.

---
_Report-only: this review does not edit the artifact. Findings are advisory; incorporate them at your discretion._