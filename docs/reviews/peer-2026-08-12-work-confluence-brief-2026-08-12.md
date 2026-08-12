# Peer Consult — docs/planning/2026-08-12-work-confluence-brief.md

- Date: 2026-08-12
- Reviewer: Codex (peer designer)

## Approach

Use git as the sole authoring authority and treat Confluence as a controlled publication projection. For each document, publish the committed HTML as a versioned attachment, maintain a stable Confluence page containing provenance metadata and an approved HTML macro bound to that attachment, then download the attachment through the API and verify exact byte identity against the git blob. Prefer the Atlassian-hosted Forge macro for the initial production deployment. Do not convert to ADF because that would discard JavaScript and break byte identity; do not build custom Forge UI until marketplace-app continuity or rendered-view assurance becomes a demonstrated requirement. Add a publication ledger recording repo, path, commit, blob hash, attachment/page identifiers, attachment version, macro implementation, verification time, and status. Distinguish custody verification from presentation health: custody proves stored bytes; a separate smoke check proves the macro remains installed and can render the current attachment without claiming pixel or runtime equivalence.

## Key decisions

- Model publication as idempotent reconciliation from manifests, not imperative page editing: resolve each document by a stable publication ID, inspect current page and attachment state, apply only necessary changes, and retry optimistic version conflicts with a bounded fresh-read loop.
- Use immutable, content-addressed attachment names such as `<doc-id>.<sha256>.html` and update the macro reference only after upload and byte verification succeed. Retain the previous verified attachment until the page update succeeds, enabling rollback and avoiding replacement ambiguity or stale attachment caches.
- Place human-readable provenance on every page: source repository/path, commit SHA, content hash, publication timestamp, and verification status. Store machine-readable publication state in the ledger or page metadata rather than inferring it from titles.
- Separate three gates: preflight verifies authentication, space access, app presence, and macro capability; custody verifies downloaded attachment bytes; presentation smoke-check verifies that the page still contains the expected macro configuration and that its rendered surface is reachable. Only the first two are required to assert byte identity.
- Adopt the Forge-hosted macro as the approved baseline because it minimizes data-residency expansion. Treat vendor-domain macros as separately approved backend variants with explicit domain, subprocessors, retention, telemetry, and incident-response review.
- Use a narrowly scoped automation identity dedicated to publishing. Store only the environment-variable name in configuration; resolve the secret at runtime, redact it from logs, and fail closed when absent. Separate publisher permissions from ordinary editor permissions where Confluence permits.
- Keep machine defaults limited to non-secret profile selection and endpoint defaults. Commit repository-specific publication configuration—profile override, space, index identity, and document mappings—so CI and developer runs reconcile the same targets.
- Rebuild the index from manifests but protect ownership boundaries: the publisher manages a clearly delimited generated region or a dedicated generated index page, preserving unrelated human-authored content.
- Define lifecycle states such as unpublished, staged, verified, active, degraded, and retired. A document becomes active only after upload verification and successful page/macro reconciliation; failures leave the last verified publication active.
- Establish an exit strategy before launch: retain original attachments and provenance independently of the macro, provide an attachment-download link on each page, and support switching the macro backend or exporting the publication mapping without republishing source content.

## Risks

- Attachment byte identity does not prove rendered behavior. The macro can transform content, inject runtime code, apply CSP restrictions, regress JavaScript support, or serve a stale attachment. Presentation must therefore be reported separately and never folded into the custody claim.
- An app uninstall, permission revocation, CSP change, outage, or vendor sunset can make pages non-rendering while attachments remain intact. Mitigate with scheduled health checks, explicit degraded status, direct download links, and a documented macro replacement runbook.
- Browser storage may be partitioned, blocked, cleared, or scoped to the macro/vendor origin. Treat localStorage-backed UAT state as best-effort and non-authoritative; validate it during the app proof-of-concept.
- Macro configuration may be editable by users with page-edit permission, allowing attachment substitution or relaxed security settings. Restrict editors where possible and have reconciliation detect configuration drift before declaring presentation healthy.
- API tokens may be broader than desired, and page/attachment APIs may require more privileges than publication alone. Security approval should document the effective permissions, account ownership, rotation, audit logging, and revocation path.
- Concurrent publishers can create duplicate attachments or overwrite page versions despite retry logic. Stable publication IDs, content-addressed names, fresh reads, bounded retries, and a per-space serialization mechanism reduce this risk.
- Caching at Confluence, Forge, or a vendor iframe may temporarily show old content after the API verifies new bytes. Content-addressed attachment names and post-update smoke checks avoid relying on cache invalidation.
- Index regeneration can lose entries when manifests are stale, inaccessible, or concurrently updated. Validate the complete manifest set before mutation and do not replace a previously valid index with a partial build.
- Marketplace capabilities and commercial terms can change. Pin the approved app and configuration in operational documentation, monitor app availability, and periodically exercise the migration path.
- Self-contained HTML still presents active-content risk. Preserve the existing no-network lint gate, forbid privileged parent communication, and include representative HTML/JS fixtures in the security proof-of-concept rather than relying only on vendor claims.

## Sketch

publish(repo, commit):
  load and validate all manifests
  render/lint outputs; require committed tree to match generated bytes
  resolve work profile and secret from configured environment-variable name
  preflight Confluence auth, target space, publisher permissions, and approved macro
  acquire per-space publication lease
  for each document:
    doc_id = stable manifest publication ID
    bytes = committed HTML blob
    digest = sha256(bytes)
    attachment_name = doc_id + "." + digest + ".html"
    page = find-or-create page by stored page ID or doc_id metadata
    if verified attachment with digest is absent:
      upload attachment_name
      download uploaded attachment through API
      require exact byte equality and digest equality
    reconcile page metadata and macro to attachment_name using current page version
    on conflict: reread, recompute desired patch, retry with bound
    confirm expected macro configuration/page reachability
    append publication-ledger record and mark active
  validate complete desired index, then reconcile its generated content
  release lease

scheduled verify:
  redownload every active attachment and compare with recorded digest
  inspect page-to-attachment macro binding and app availability
  classify independently as custody_ok and presentation_ok
  alert on mismatch, drift, missing app, permissions failure, or unreachable render

recovery:
  if a publish fails before page reconciliation, retain the prior active binding
  if the macro fails or is removed, mark presentation degraded while keeping custody status
  expose the verified attachment download and provenance immediately
  install an approved replacement macro, reconcile bindings from the ledger, smoke-test, then restore active status

---
_Peer proposal (report-only). Synthesize at your discretion._
