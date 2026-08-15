# Peer Consult — docs/planning/2026-08-12-hosting-options.md

- Date: 2026-08-12
- Reviewer: Codex (peer designer)

## Approach

Adopt a policy-driven, manifest-based publishing system with two delivery lanes. Public repositories—and private repositories only when access-controlled GitHub Pages is available—serve committed HTML through GitHub Pages from `main:/docs`. Private repositories without that capability publish a clearly labeled Confluence mirror while retaining the repository Markdown and HTML at an immutable commit as the canonical record. Each documentation PR updates a committed publication manifest and a generated README section. After merge, an asynchronous reconciler waits for the Pages build associated with that commit, compares the live response with the exact Git blob, updates the appropriate audience index, and records publication status. Migration proceeds by publishing and verifying new destinations, switching indexes, installing temporary redirects at old Vercel URLs, observing a grace period, and only then deleting Vercel projects.

## Key decisions

- Use GitHub Pages legacy deployment from `main:/docs` for eligible repositories; the deployed source is the reviewed default branch rather than a separately assembled artifact.
- Fail closed on repository visibility. Enable Pages only for public repositories or where private-site access control has been positively verified; repository privacy alone is insufficient.
- Introduce `docs/publications.json` as the allowlisted source of publication metadata: stable ID, title, purpose, source path, HTML path, audience, canonical URL, and lifecycle state. Do not infer published documents by scanning every HTML file.
- Generate the README `Documentation` table from the manifest in the same PR. CI rejects missing files, duplicate IDs or URLs, unsafe paths, stale generated tables, and Markdown/HTML pairs that disagree.
- Treat merge as the publication trigger, not publication completion. A post-merge workflow polls the Pages build for the merged commit, then fetches the canonical URL and byte-compares the decoded response with the HTML blob from that exact commit.
- Persist publication state externally or as workflow evidence—repository, commit SHA, build ID, URL, expected digest, observed digest, and verification time—without creating automated follow-up commits on every deployment.
- Use a dedicated GitHub Pages catalog repository for the public index, updated by repository dispatch and repaired by scheduled reconciliation. Use Confluence for the work index and, where private Pages is unavailable, for generated document mirrors linked back to immutable repository commits.
- Serialize index updates and use optimistic concurrency. Event-driven updates provide low latency; a scheduled full reconciliation repairs missed dispatches, deleted documents, renamed repositories, and partial failures.
- Keep pre-network rendering, sanitization, link checking, and deterministic-output checks in the authoring command. Remove Vercel project creation, alias management, and temporary upload staging from the normal path.
- Give every publication a stable manifest ID independent of repository or filename. Renames update the canonical URL and create an explicit redirect entry rather than silently changing identity.
- Retire Vercel in batches: inventory mappings, publish and verify every destination, switch indexes, deploy redirects, monitor redirect traffic and verification health during a defined grace period, then require owner approval for deletion.
- Restrict published HTML to a safe static subset. Reject inline scripts, executable embeds, forms, and uncontrolled external resources because project Pages sites under the same organization share an origin.

## Risks

- A successful merge can be followed by a failed or delayed Pages build. Publication must remain visibly pending or failed, with alerting and a retry/rebuild procedure.
- The legacy Pages build soft-rate limit can delay repositories with frequent documentation merges. Coalesce reconciliation, avoid automated rebuild commits, and define a threshold for moving high-volume repositories to an Actions deployment.
- A visibility or plan change can expose a previously private site. A scheduled policy audit must disable publication and alert on any mismatch between repository classification and Pages access control.
- Confluence mirrors are copies and can drift. Each mirror must display its source commit and digest, and reconciliation must detect divergence; the repository remains canonical.
- Repository transfers, renames, default-branch changes, and document moves alter Pages URLs. Stable IDs and managed redirects reduce breakage but cannot guarantee permanence without a custom routing domain.
- Cross-repository catalog updates require credentials and concurrency control. Scope credentials narrowly, protect the catalog branch, serialize writes, and retain scheduled repair.
- Exact-byte verification can be confused by CDN propagation, content encoding, authentication redirects, or custom error pages. Verification must follow only expected redirects, validate status and content type, retry boundedly, and compare the decoded body.
- Manifest and generated README enforcement adds authoring friction. Provide one command that renders the pair, updates the manifest and README, and runs the same checks as CI.
- Public HTML may disclose sensitive content or introduce active-content risk. Publication eligibility, secret scanning, sanitization, and explicit audience classification must be merge gates.
- Temporary Vercel redirects remain an operational dependency during migration. Keep an inventory with owners and removal dates, and do not delete projects until redirect traffic and verification evidence satisfy the exit criteria.

## Sketch

Authoring lane:
  edit .md
    -> publish command renders deterministic .html
    -> update docs/publications.json
    -> regenerate README Documentation table
    -> local lint/security/link checks
    -> PR CI repeats checks
    -> merge to main

Eligible Pages lane:
  merge SHA
    -> GitHub Pages builds main:/docs
    -> reconciler waits for build tied to SHA
    -> fetch canonical URL
    -> compare response bytes to git blob at SHA
    -> record VERIFIED
    -> dispatch public catalog update

Private fallback lane:
  merge SHA
    -> render/update Confluence mirror with source SHA and digest
    -> read back and validate metadata/content
    -> update work index
    -> record VERIFIED_MIRROR

Repair loop:
  scheduled policy audit + manifest reconciliation
    -> detect missing, stale, exposed, renamed, or orphaned publications
    -> retry safe operations
    -> alert on policy or byte mismatches

Migration:
  inventory old URL -> stable publication ID -> new URL
    -> publish new destination
    -> verify
    -> switch index
    -> install old-URL redirect
    -> observe grace period
    -> owner-approved Vercel deletion

---
_Peer proposal (report-only). Synthesize at your discretion._
