# Peer Consult — docs/planning/2026-08-23-github-doc-harness-spec.md

- Date: 2026-08-23
- Reviewer: Codex (peer designer)

## Approach

Build a host-routed artifact gateway with separate control and serving paths. A publish creates an immutable deployment from a full GitHub commit SHA: the harness resolves the rendered HTML and declared assets to Git blob IDs, verifies their hashes, prewarms an evictable cache, and atomically advances that name’s active deployment in SQLite. Requests resolve the exact registered manifest and fetch missing blobs from GitHub; no request follows a moving branch. The index is rendered from a consistent registry snapshot using the existing build_index.py presentation logic.

Run the gateway and cloudflared in one Compose stack, with no published host ports. Use explicit Cloudflare Access applications for registered document hostnames, the index, and the control API rather than an account-wide wildcard Access application. Cloudflare caching is bypassed; the harness’s content-addressed cache supplies performance and availability. Deployment verification is revision-aware: the publish call returns a deployment ID, and verify_live requests that ID, requires matching revision and digest headers, refuses redirects, and compares every registered artifact with the local publish output.

## Key decisions

- Pin every deployment to a full commit SHA and a manifest of Git blob IDs, sizes, media types, and SHA-256 digests. Branch names and the default branch are provenance inputs, never serving pointers; follow-up content changes require another complete publish.
- Treat pre-merge publication as an immutable candidate deployment. After merge, an optional reconciler may record the merge/default-branch commit as durable provenance only after confirming the complete blob manifest is identical. A closed-unmerged candidate is flagged or withdrawn according to an explicit retention policy.
- Use SQLite on a dedicated volume, with schema migrations, WAL mode, backups, append-only deployment history, and one atomic active-deployment pointer per name. This provides immediate publication, concurrency control, auditability, and rollback without cross-repository commits or merge latency.
- Make publishing a staged server-side validation followed by atomic activation. The client supplies name, repository, full commit SHA, entry path, explicit asset mapping, local digests, metadata, idempotency key, and expected current deployment. The server independently resolves and hashes GitHub objects before activation.
- Use compare-and-swap for concurrent publications of the same name. A stale publisher receives a conflict instead of silently overwriting a newer deployment; idempotent retries return the original deployment result.
- Expose the control API on a reserved exact hostname such as docs-control.3dstories.ca. Require both a Cloudflare Access service-token policy and DOC_HARNESS_PUBLISH_TOKEN. Keep control routes unavailable on document hosts and disable CORS.
- Prefer a read-only GitHub App installed only on approved repositories over a user PAT. Installation tokens are short-lived and automatically renewed; repository, owner, path, file-count, per-file-size, and total-deployment-size allowlists are enforced.
- Fetch immutable Git blobs on cache miss and cache by repository plus blob ID without a TTL, since the object cannot change. Use a bounded LRU cache, for example 2 GiB, on an explicitly disposable volume. Never substitute bytes from an older deployment when the active deployment’s blob is unavailable.
- Set browser responses to Cache-Control: private, no-cache and configure Cloudflare Cache Rules to bypass caching for document, index, and control hosts. Return an ETag based on the blob ID. This permits browser revalidation while preventing an edge-cached prior deployment from defeating verification.
- Have the publish response return a deployment ID. verify_live requests /?__deployment=<redacted> sends the Access service-token headers, disables redirects, and requires status 200, the expected X-Doc-Deployment and Digest headers, text/html, and byte equality. The harness returns 409 if that deployment is no longer active. The verifier repeats this for all manifest assets.
- Map assets through an explicit URL-path manifest rather than an unrestricted repository directory. `/` and optionally `/index.html` map to the entry HTML; each staged sibling asset maps to its declared root-relative URL. Decode once, reject dot segments, encoded separators, backslashes, collisions, and undeclared paths, and ignore query parameters for lookup.
- Extend the existing lint gate to discover local references in HTML and CSS and require every referenced same-origin resource to appear in the staged manifest. Cross-document subdomain resources are rejected; external resources remain subject to the existing document policy.
- Create exact Cloudflare Access applications, or exact host entries within an application if supported, from the registry. Do not protect `*.3dstories.ca` with one Access application because that can affect unrelated existing subdomains even though their DNS records override the tunnel wildcard.
- For human access, allow the owner’s identity policy; for automation, add a Service Auth policy containing the service token. Same-host asset requests inherit the browser’s Access session. Automated verification sends service-token headers on every HTML and asset request and treats an Access login redirect as failure.
- Serve the index only from active registry rows and render/cache it by registry generation. Titles and other renderable metadata are validated during publication; activation time is server-assigned. Conditional index requests use an ETag derived from the registry generation.
- Return 404 for unknown registered paths, 421 for unsupported hosts, 410 for deliberately withdrawn deployments, and 503 for an active cache miss that GitHub cannot satisfy. Cached bytes for the exact active blob may continue to be served during a GitHub outage, marked with X-Doc-Origin: cache; this is not a fallback to an older revision.
- Reserve names such as docs-index and docs-control, validate the DNS label length and hyphen grammar, and reject Host headers containing ports, uppercase ambiguity, multiple labels, or forwarded-host overrides. Only cloudflared can reach the container network.
- Backfill from a reviewed mapping of name to GitHub repository, path, and commit; `vercel project ls` is inventory, not sufficient source metadata. Stage each migration, compare the GitHub-backed bytes with the existing Vercel page, then activate. Run a short read-only coexistence window, switch publishing and references, and delete Vercel page deployments. Redirect-only Vercel projects are optional only if temporary third-party hosting remains acceptable.
- Pin container images by digest, run the gateway non-root with a read-only root filesystem, mount only registry and disposable-cache volumes, use Docker secrets, add health checks and resource limits, and alert on GitHub authentication failures, rate-limit pressure, cache-miss failures, reconciliation failures, and registry backup age.

## Risks

- A pre-merge commit can eventually become unreachable if its branch is deleted and it is never merged. Merge reconciliation, closed-PR handling, and alerts for unresolved candidate deployments are required; the cache must not be treated as the durable source.
- Creating one Access configuration per hostname introduces Cloudflare API coupling during publication. Access configuration must succeed before registry activation, and reconciliation must repair drift without exposing a registered host.
- A wildcard Access application could unexpectedly place unrelated 3dstories.ca subdomains behind login. Exact-host configuration and an inventory test are release blockers.
- Service-token misconfiguration commonly produces a login redirect or Access HTML with status 200 after redirect following. Verification must disable redirects and validate deployment headers and content type, not just compare the final status.
- The VM, SQLite volume, and tunnel are single points of failure. Tested registry backups and a documented restore procedure are necessary; higher availability can be added later without changing the registry contract.
- GitHub App revocation, token issuance failure, API outage, or rate limiting prevents uncached objects from loading. Prewarming and immutable caching limit impact, but a lost cache plus GitHub outage correctly yields 503.
- Persistent cache storage may be perceived as another document store. It must be explicitly disposable, bounded, reconstructable solely from GitHub and the registry, and excluded from backups.
- Incorrect asset discovery can yield pages whose HTML verifies while images, fonts, scripts, or CSS fail. Manifest-complete linting and asset-by-asset live verification are needed.
- Git LFS pointers, submodules, very large assets, unusual media types, and range-dependent content do not behave like ordinary Git blobs. Reject unsupported forms initially and publish documented size and type limits.
- Rendered HTML is active content. Subdomain isolation protects documents from one another, but unsafe external scripts, navigation, downloads, or same-origin control endpoints remain security concerns; use restrictive headers compatible with the renderer and keep control/index on separate hosts.
- An activation followed by a failed external verification leaves a new deployment active. Server-side digest validation minimizes this risk, while append-only history and an authenticated rollback operation provide recovery.
- Migration inventory can identify Vercel names without reliably recovering their GitHub source coordinates. Any row without independently verified repository, path, commit, and byte match must remain unactivated.
- Name collisions or labels exceeding DNS limits can emerge from normalization. Publication must reject collisions and reserved names before making Cloudflare or registry changes.

## Sketch

publish_doc.py
  render -> source gate -> derive name -> lint/manifest -> commit and push
  POST docs-control.3dstories.ca/v1/deployments
    Access service token + harness bearer
    {name, repo, commit_sha, entry_path, assets, digests,
     expected_active, idempotency_key, metadata}
                         |
                         v
Harness control path: validate -> obtain GitHub App token -> resolve tree/blob IDs
                      -> fetch and hash all artifacts -> prewarm cache
                      -> ensure exact-host Access policy -> SQLite transaction
                      -> return {deployment_id, manifest_digest}
                         |
                         v
verify_live:
  GET https://<name>.3dstories.ca/?__deployment=<redacted>
  require 200 + matching X-Doc-Deployment + Digest + exact bytes
  repeat for each declared asset; redirects are errors

Browser/verification request
  Cloudflare Access -> cloudflared -> host router
    docs-index       -> registry snapshot -> build_index renderer
    docs-control     -> authenticated control API
    registered name -> active deployment -> exact URL manifest lookup
                                      -> content-addressed cache hit
                                      -> otherwise GitHub blob fetch
    unknown host     -> 421

Durable volume: SQLite registry and deployment history
Disposable volume: bounded immutable-blob cache
GitHub: sole durable location of HTML and asset bytes
Cloudflare: TLS, exact-host Access enforcement, edge cache bypass

---
_Peer proposal (report-only). Synthesize at your discretion._
