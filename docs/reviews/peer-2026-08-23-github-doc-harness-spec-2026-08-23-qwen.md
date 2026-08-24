# Peer Consult — docs/planning/2026-08-23-github-doc-harness-spec.md

- Date: 2026-08-23
- Reviewer: Codex (peer designer)

## Approach

Implement a stateless Python HTTP harness that treats the GitHub repository as the sole source of truth for both content and registry metadata. Instead of maintaining a server-side database updated via API, the harness derives the registry dynamically by reading a canonical `docs-registry.json` file from a designated private GitHub repository on every request (cached briefly). Content is fetched via GitHub Blob API using immutable commit SHAs pinned in this registry file. The publish_doc.py script is modified to update this registry file via GitHub Contents API (create/update) as an atomic commit step immediately after pushing the rendered HTML, ensuring the registry entry and content exist simultaneously. Cloudflare Access Service Tokens are used for both the harness's backend fetches (to access private repos) and the verify_live stage, with the harness explicitly rewriting relative asset paths to absolute subdomain URLs to prevent cross-origin Access failures.

## Key decisions

- Registry-as-Code: Replace the proposed server-side SQLite/JSON DB and Publish API with a `docs-registry.json` file in a private GitHub repo. This eliminates server state, removes the need for a write endpoint on the harness, and makes the registry auditable/versioned alongside code.
- Atomic Publish Contract: Solve Q1 (publish-before-merge gap) by having publish_doc.py push the rendered HTML to the PR branch AND update the registry file to point to that specific commit SHA in the same logical operation. The registry always points to a valid, existing blob, never a dangling branch name.
- Asset Path Rewriting: Solve Q5 by having the harness parse HTML responses and rewrite relative src/href attributes to absolute URLs under the same subdomain. This ensures all assets pass through the same Cloudflare Access context, avoiding mixed-content or auth-failure issues with sibling files.
- Dual-Purpose Service Token: Use a single Cloudflare Access Service Token for both the harness's upstream GitHub fetches (if proxying through CF) and the downstream verify_live checks. Configure the token with permissions for both the harness origin and the GitHub API if proxied, or strictly for the harness origin if GitHub is direct.
- ETag-Only Caching with Stale-While-Revalidate: Reject TTL-based caching. Cache keyed by (name, sha). Serve cached content only if GitHub returns 304 or is unreachable. Never serve stale content for verify_live requests (detected via specific header/query param) to guarantee verification integrity.
- Blob API over Contents API: Always use the Git Blob API (raw media type) for fetching content. The Contents API has stricter size limits and returns base64 JSON by default; Blob API supports up to 100MB raw binary efficiently and handles assets/images correctly without transcoding.

## Risks

- Registry File Contention: Concurrent publishes updating docs-registry.json may cause 409 Conflict errors on GitHub Contents API. Mitigation: Implement optimistic concurrency with retry-and-merge logic in publish_doc.py, or serialize publishes via a lightweight lock/queue if volume increases.
- HTML Rewriting Fragility: Regex or lightweight parser rewriting of asset paths may break complex HTML structures or JS-generated URLs. Mitigation: Use a proper HTML parser (e.g., html.parser stdlib) and restrict rewriting to known safe attributes; accept that dynamic JS-loaded assets may require manual absolute paths in source.
- Service Token Scope Creep: Using one token for multiple contexts increases blast radius if compromised. Mitigation: Create dedicated tokens per environment/purpose; rotate regularly; audit CF Access logs.
- GitHub Rate Limit on Registry Reads: Every uncached page view triggers a registry file fetch. Mitigation: Cache the parsed registry in memory with a short TTL (e.g., 60s) and ETag revalidation; this is acceptable given low traffic but prevents redundant API calls during bursts.
- Verify_Live False Negatives: If the harness serves stale cache during verification, the check passes incorrectly. Mitigation: verify_live must send a cache-busting header (e.g., X-Verify-Live: true) that forces the harness to bypass cache and fetch fresh from GitHub.

## Sketch

docker-compose.yml defines two services: 'harness' (Python HTTP server) and 'cloudflared'. Harness mounts no volumes; config via env vars (GITHUB_TOKEN, CF_ACCESS_CLIENT_ID, CF_ACCESS_CLIENT_SECRET, REGISTRY_REPO). On startup, harness loads nothing. On request: 1) Parse Host header -> extract name. 2) Fetch docs-registry.json from REGISTRY_REPO (cached 60s w/ ETag). 3) Lookup name -> get {repo, path, sha}. 4) Fetch blob via GitHub Blob API (raw) using sha. 5) If HTML, parse and rewrite relative asset URLs to absolute https://<name>.3dstories.ca/<asset-path>. 6) Return response with ETag. publish_doc.py changes: After committing HTML to PR branch, call GitHub Contents API to update docs-registry.json with new entry pointing to HEAD sha of PR branch. verify_live: GET https://<name>.3dstories.ca/?verify=<redacted> with CF-Access-Client-Id/Secret headers; compare response body to local rendered file. Migration: Script reads vercel project ls, maps to repo/path/ref, writes initial docs-registry.json in one commit.

---
_Peer proposal (report-only). Synthesize at your discretion._
