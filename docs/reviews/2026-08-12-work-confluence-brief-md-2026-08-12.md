# Adversarial Review — docs/planning/2026-08-12-work-confluence-brief.md

- Date: 2026-08-12
- Artifact type: plan
- Reviewer: Codex (model qwen3.8-max-preview, reasoning effort config-default)
- Findings: 3 (Critical 1, High 1, Medium 1, Low 0)

## Summary

The artifact proposes serving design-doc HTML in Confluence Cloud via attachments and third-party macros, with byte-identity verification. It contains a critical feasibility gap regarding unproven REST API v2 attachment upload capabilities and a high-severity security contradiction between the preferred Forge app's 'allow-all' CSP mode and the project's strict no-external-requests lint gate.

## Findings

### 1. [Critical] feasibility · 0.95 confidence — Proposed work path > 2. Deliver

> Deliver: a publish step (CI job on merge, or the publishing session) uploads the committed `.html` as an ATTACHMENT to that doc's Confluence page via REST API v2

The plan relies on uploading attachments via Confluence Cloud REST API v2 without proving this endpoint exists or supports binary file uploads in the project's configuration. Confluence Cloud API v2 is primarily for content/properties; attachment management has historically been restricted to API v1 or specific Forge endpoints. If API v2 does not support attachment creation/upload as assumed, the entire 'Deliver' and 'Verify' workflow is impossible to implement as specified.

**Recommendation:** In 'Proposed work path' section item 2, replace 'via REST API v2' with 'via REST API v1 /content/{id}/child/attachment (verified)' or provide a concrete proof-of-concept reference confirming v2 attachment upload support. Add a pre-implementation validation task to verify the specific API endpoint and authentication scope required for attachment upload.

### 2. [High] security · 0.85 confidence — Research findings > 3 & Proposed work path > 4

> "HTML Macro for Confluence (Free)" — runs entirely on Atlassian Forge... CSP modes (block-all / whitelist / allow-all); ... prefer the Forge-based macro

The artifact prefers the Forge-based macro partly because it stays on Atlassian infrastructure, but notes it supports an 'allow-all' CSP mode. This directly contradicts the stated constraint that 'the lint gate already forbids external requests.' If the admin configures the preferred macro to 'allow-all' (a documented option), the rendered content can make external requests, violating the security model the lint gate enforces. The plan lacks a mechanism to enforce or verify the macro's CSP configuration matches the lint policy.

**Recommendation:** In 'Proposed work path' item 4 ('App selection'), add a mandatory configuration requirement: 'Forge macro MUST be configured to CSP mode "block-all" or "whitelist" matching lint policy; "allow-all" is forbidden. Plugin setup must verify macro CSP setting via API or fail with remediation.' Also add to 'Questions for the peer': 'Can the Forge macro CSP mode be enforced/audited programmatically?'

### 3. [Medium] completeness · 0.7 confidence — Proposed work path > 3. Verify (custody)

> Verify (custody): download the attachment back via the REST API and byte-compare against the committed blob. Attachment download is API-native, so the verify contract survives intact

The verification step assumes downloading the attachment via REST API will return the exact original bytes. However, Confluence Cloud may apply transformations (e.g., virus scanning metadata, encoding changes, or CDN caching headers) that could alter the response body or require specific Accept headers to get raw bytes. The plan does not specify how to handle potential API-level byte mutations or what HTTP headers/parameters are needed to guarantee raw binary retrieval.

**Recommendation:** In 'Proposed work path' item 3 ('Verify'), add: 'Download must use Accept: application/octet-stream and validate Content-MD5 or ETag header if available. Document expected behavior for virus-scanned files. Include test case verifying byte-identity after round-trip through Confluence API.'
**Ambiguity:** Unclear whether Confluence REST API guarantees bit-for-bit identical download without transformation or special headers.

---
_Report-only: this review does not edit the artifact. Findings are advisory; incorporate them at your discretion._