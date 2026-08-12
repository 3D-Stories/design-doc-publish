# Docs hosting: Vercel to GitHub Pages

```chips
design options | wip
nothing implemented | note
owner decision pending | note
live exposure found | blocked
```

## Why this document exists

Every design doc in this workspace ships as a committed `.md` + `.html` pair inside its
own repo. Where a SEPARATE copy of those bytes is served (today: Vercel, from a temp
directory), the served page and the committed page are only provably the same at the
moment stage 6 verifies them — the custody-chain break this document set out to design
away. Two owner review rounds then reshaped the goal: the primary use case is **work
documents**, work has **no GitHub Enterprise plan** (so private Pages is impossible), and
the rule is **one scope, one host** — personal stays on Vercel unchanged, work goes
Confluence end-to-end.

```callout
warn | Found during review: two PRIVATE repos are serving their whole docs trees publicly, today
Measured 2026-08-12, unauthenticated probes. `3D-Stories/rawgentic` (repo visibility
PRIVATE, 510 files under docs/) and `3D-Stories/3dstories-studio` (PRIVATE, 170 files)
both have Pages enabled with `public: true` — review reports, measurement CSVs and a
container-security-posture document all answer HTTP 200 to a bare curl. This predates
this design. Whether each stays served is the owner's call — options: make the repo
public deliberately, disable Pages, or prune what docs/ carries.
```

```callout
info | Evidence: Pages serves the committed bytes faithfully — measured, with its scope stated
Measured 2026-08-12 on `3D-Stories/rawgentic`: the live
`3d-stories.github.io/rawgentic/workflow-diagram.html` is **byte-identical** to
`origin/main:docs/workflow-diagram.html` (both sha256 `af7d74c5…9659c0d`). Scope: one
file, one repo, legacy build with `docs/.nojekyll` present. It proves fidelity of the
serving path — and does NOT bless the configuration it was measured on (see above).
```

## Freshness: what "the diagram is stale" actually was

The owner observed the workflow diagram "hasn't been updated in forever". Measured: the
**hosting is not the stale part**. The live copy exactly matches `main` (above), and `main`
last touched the file 2026-08-10 (`b29135be`). What IS stale is the content: the diagram's
newest REV entry says **plugin 3.158.0** while `origin/main` declares **3.163.0** — five
releases with no REV entry, despite the rev-diagram convention requiring a decision per PR.

Lesson: a hosting change fixes custody, not freshness. Freshness is a **process**
property — content updates ride inside each issue's own PR, and the README documentation
list in §3 is the surface that makes a missed update visible. The convention itself is
now tracked as rawgentic#1137.

## 0. The generic shape: profiles and backends

Owner decisions (PR #22 review rounds 1–2): the plugin must stay usable by ANYBODY, and a
user's real setups differ, so hosting is configured — never hardcoded — at two levels:

- **A machine PROFILE, asked once by `setup.py`: `personal` or `work`.** The profile
  picks the backend bundle. A **per-repo override** exists, because one machine touches
  both worlds.
- **One scope, one host.** A profile is one host family END TO END — docs and index
  together. No scope splits its docs and its index across two hosts (an earlier draft's
  mixed model, dropped by owner decision).
- The plugin's identity is the contract, not the host: **render → lint → deliver → prove
  the served bytes equal the committed bytes**. Stages 1–3 (render, name, lint) are
  shared and need no account. Stages 4–7 (eligibility, deliver, verify, index) dispatch
  per backend.

```options
vercel — the personal profile, unchanged | Works today, zero repo requirements, instant pre-merge preview URL, per-doc blast radius; the owner is content with its current shape | Custody chain broken by design (a separate copy is served); auto-alias truncates project names past ~35 chars (measured live 2026-08-12) — accepted for personal docs | chosen
confluence — the work profile | The one host work readers already use; no GitHub plan dependency at all; attachment download is API-native, so byte-identity custody verification survives intact | Rendering HTML needs a Marketplace macro app (Confluence never renders HTML attachments natively — deliberate XSS defense, CONFCLOUD-69015); the RENDERED view rides a third-party macro the verify cannot cover | chosen
pages-actions — Actions deploy of ONE designated folder | Serves exactly the folder you name (docs/public/): publishing is an explicit placement; no Jekyll hazard; exempt from build rate limits; full custody chain | Public serving only below Enterprise, so it fits PUBLIC repos; this workspace defers it — personal stays on Vercel by owner decision, and work has no Enterprise plan |
pages-legacy — branch build of /docs or root | Zero build config; the rawgentic diagram proves the serving path | Serves the WHOLE tree (root or /docs only — a chosen subfolder is impossible); Jekyll unless docs/.nojekyll; one bad Liquid file fails the whole site |
none — render and commit only | No account, no egress; the committed pair is the deliverable | No live URL; readers open the committed .html locally |
```

**Why the stances land there.** `vercel` was rejected in an earlier draft on the custody
argument; the owner then scoped that argument: personal docs are fine as they are, so
`vercel` IS the personal profile and nothing about it changes — including the docs-index.
`pages-actions` stays fully designed (below) as the plugin's public-repo path and this
workspace's future option; it is deferred, not rejected. `confluence` is the work
profile, designed in §1b. Migration/retirement of existing vercel.app URLs is therefore
**deferred with it** — nothing is retired while personal stays on Vercel.

## 1. The public-repo path (pages-actions) — designed, deferred here

Kept in full because the plugin is generic and a public repo wanting custody-grade
hosting picks this path.

**Delivery.** One org-level reusable workflow; each repo references it in three lines.
Trigger: push to the default branch filtered on the served folder. Steps:
`configure-pages` → `upload-pages-artifact` with `path: docs/public` → `deploy-pages`
(permissions `pages: write`, `id-token: write`). Jekyll never runs.

```callout
info | The served-folder rule (owner decision, PR #22 review round 1)
The whole docs/ tree is NOT served. One designated folder is (default `docs/public/`,
configurable per repo). The publishable `.md` + `.html` pair LIVES in that folder and
only there — one copy, no sync step, no drift. Everything else under docs/ (reviews,
measurements, planning notes) stays unserved. Publishing a doc IS the PR that places its
pair in the folder and adds its manifest row. This replaces the serving-side role of
today's stage-5 asset allowlist.
```

**URL scheme.** `docs/public/<file>.html` serves at
`https://<owner>.github.io/<repo>/<file>.html`; `<owner>` is a per-repo fact (`daimonia`
and `xtoys` live under `crandrosoff`, measured). Accepted residual (peer finding): a repo
rename or transfer breaks every URL under it — stable manifest ids and redirect entries
cover *document* renames only.

**Verify.** Post-merge: the publishing session runs `verify-published` — wait for the
deploy workflow, fetch, byte-compare against the committed blob on `main`. The merge is
the publication trigger, never its completion: a doc is pending (absent from the index)
until its verify passes. This path applies to publicly served Pages only; an
access-controlled site answers with a login redirect, which the verifier already refuses.

```callout
warn | The eligibility gate — the axis is PUBLIC vs NOT-PUBLIC, never personal vs work
Pages below Enterprise Cloud serves a private repo's site PUBLICLY (the measured state of
two repos in this workspace today). Fail CLOSED: eligibility is the PAIR
`repo.visibility == public` OR `pages.public == false`, read from the API. Re-checked on
a schedule and at every index rebuild — a plan or visibility change can expose a site
while nothing publishes. Confirmed 2026-08-12: the work org has NO Enterprise plan, so no
work repo is ever eligible — which is why the work profile is Confluence (§1b).
```

```callout
info | Shared origin (peer finding)
Project sites under one owner share the `<owner>.github.io` origin. Published HTML stays
script-inert beyond the renderer's own inline behavior — the existing lint gate already
enforces self-containment.
```

### Publish flow, pages-actions

```nodes
publish_doc.py
  render + lint | stages 1-3 unchanged, still local, still gated
    place the pair in docs/public/ | publishing IS this placement, inside the PR | ~
      merge | the reviewed pair lands on main | ~
        deploy workflow | upload-pages-artifact serves ONLY the designated folder | ~
          verify-published | byte-compare vs the committed blob | ~
            index refresh | row appears only after verify passes | ~
```

**Limits (official docs, fetched 2026-08-12):** 1 GB site, soft 100 GB/month, 10-minute
deploy timeout — none binds this workload.

## 1b. The work path: Confluence end-to-end

Constraint set (owner, 2026-08-12): no Enterprise plan, so no private Pages. Everything
work routes to Confluence — docs AND index. Research and two cross-model consults back
this section (reports: `docs/reviews/peer-2026-08-12-work-confluence-brief-2026-08-12.md`,
`docs/reviews/2026-08-12-work-confluence-brief-md-2026-08-12.md`; brief:
`docs/planning/2026-08-12-work-confluence-brief.md`).

**Can Confluence serve HTML with JavaScript? Natively NO, via a macro app YES.**
Confluence Cloud forces `Content-Disposition: attachment` on HTML attachments — a
deliberate, permanent XSS defense (CONFCLOUD-69015; the Atlassian KB says the behavior
stays). Marketplace macro apps render an ATTACHED HTML file inside a sandboxed iframe
where JavaScript runs but cannot touch the parent page or Confluence tokens. Our pages
fit that sandbox: the lint gate already forbids external requests, and the pages are
single-file and self-contained.

**App selection (consult-hardened).** Prefer the Forge-based HTML macro: it runs entirely
on Atlassian infrastructure, so the security review gains no new data-residency surface.
Vendor-domain macros (e.g. one that serves its iframe from the vendor's own host) are a
separately-approved fallback, reviewed for domain, subprocessors, retention and telemetry.
Qwen finding, adopted as a hard rule: **the macro's CSP mode is pinned to block-all (or a
whitelist matching the lint policy) — allow-all is forbidden**, and setup verifies the
configuration or fails with a named remediation.

**The mechanism, one doc at a time.** Git stays the sole authoring authority; Confluence
is a controlled publication projection (Codex's framing, adopted):

```nodes
work repo
  render + lint | stages 1-3, unchanged, local
    commit + PR + merge | the pair and its manifest row land on the work repo's main | ~
      upload attachment | v1 child/attachment endpoint; name is content-addressed: <doc-id>.<sha256>.html | ~
        custody verify | download the attachment raw, byte-compare vs the committed blob | ~
          bind the macro | page's HTML macro points at the VERIFIED attachment; provenance on the page | ~
            index page update | generated region only; 409 = re-read version, bounded retry | ~
```

Consult-adopted rules that make this operable:

- **Attachment upload is the v1 endpoint** (`/rest/api/content/{id}/child/attachment`) —
  qwen's Critical, adopted: the brief said "v2" loosely; v2 covers reads. A
  proof-of-concept validating upload, raw download (`Accept: application/octet-stream`)
  and byte round-trip is the FIRST implementation task, before anything else builds.
- **Content-addressed attachment names** (`<doc-id>.<sha256>.html`): the macro reference
  moves only after the new attachment verifies, the previous verified attachment is
  retained for rollback, and caches can never serve ambiguity.
- **Custody and presentation are SEPARATE gates** (Codex, adopted): byte-identity of the
  attachment is provable; the RENDERED view rides a third-party macro and is checked by a
  smoke look, reported separately, never folded into the custody claim.
- **Lifecycle states**: a doc is active only after upload-verify AND macro-bind succeed;
  failures leave the last verified publication active; macro-app trouble (uninstall,
  CSP change, vendor sunset) degrades pages to their attachment-download links — which is
  also the exit strategy: attachments and provenance survive the macro, so switching
  macro vendors never republishes content.
- **Scoped automation identity**: a dedicated publishing token, stored BY NAME (env var),
  redacted from logs, fail-closed when absent; page-edit permission restricted so the
  macro binding cannot be quietly repointed.
- **Deliberately NOT built at this scale** (tens of docs, one team): per-space
  serialization locks and a scheduled reconciliation fleet — bounded 409 retries plus a
  single scheduled macro-health check cover the same failures; noted as the scale-up
  path.

**The work index** is a Confluence page in the same space: a generated region (marker
comments, exactly like the README section) listing every doc from the manifests — title,
purpose, source commit, verification status, link to the doc's page. Human prose outside
the markers is never touched.

## 2. Indexes, per profile

One scope, one host — so each profile's index lives with its docs:

- **Personal:** the existing Vercel `docs-index` project, exactly as today. Unchanged,
  including its derivation; it modernizes to manifest-derivation only if/when personal
  ever migrates.
- **Work:** the Confluence index page (§1b). Derived from the per-repo
  `docs/publications.json` manifests — stable id, title, purpose, source path, HTML path,
  audience, canonical URL, serving backend. The manifest is the SINGLE derivation source
  for index and README both; the GitHub API only locates manifests. The stage-7 anti-race
  successor: every index row equals a manifest entry at the commit the rebuild
  enumerated, and the rebuild reports the SHAs it read.

## 3. The README "Documentation" section

Every project README gains a `## Documentation` section: one row per published doc —
title, purpose, committed `.md` path, live URL. **Generated from `docs/publications.json`**
so the README, the index and the manifest cannot disagree. Marker-fenced:

    <!-- docs-list:begin -->
    | Doc | Purpose | Source | Live |
    | --- | ------- | ------ | ---- |
    | Hosting options | design | docs/planning/2026-08-12-hosting-options.md | (URL) |
    <!-- docs-list:end -->

The row updates **inside the same PR that changes the doc** — the status-surface rule
applied to docs, and the process fix for the diagram's five-release drift. Enforcement
lives in PR CI: a check fails the PR when the manifest, the README section, and the
published set disagree. The cross-project convention is rawgentic#1137.

## 4. Plugin impact

```nodes
publish_doc.py
  stages 1-3 | render, name, lint — shared, unchanged
  stage 4 eligibility | vercel: project inspect · pages: the visibility/public pair · confluence: preflight (auth, space, macro app present, CSP mode pinned) | backend
  stage 5 deliver | vercel: CLI deploy · pages-actions: placement in the served folder · confluence: content-addressed attachment upload + macro bind | backend
  stage 6 verify | ONE shared contract: byte-identity vs the committed blob; per-backend wait strategy; confluence adds the separate presentation smoke look | backend
  stage 7 index | manifest-derived rows, per profile | backend
setup.py
  profile | asks personal or work ONCE per machine; per-repo override; work profile stores Confluence base URL, space key, token NAME | ~
  checks | per configured backend; work: macro app present + CSP pinned, or a named remediation | ~
```

What goes, what stays: the duplicate-project minting hazard exists only on `vercel` and
stays there (personal accepts it); the team-scope pin and SSO-wall stay exactly as long as
personal stays on Vercel — which is now by choice, not by residue. The stage-5 asset
allowlist keeps its serving-side role on `vercel`, is replaced by the served-folder rule
on `pages-actions`, and on `confluence` by the fact that only the deliberately-uploaded
attachment is ever served. **No vercel.app URL retirement happens now** — deferred with
the personal migration, and the ordered, evidence-gated retirement recipe from the
previous revision moves with it (verify destination → switch row → redirect script
outside the lint gate → owner-approved deletion).

## Review trail

```chips
codex peer consult x2 | done
qwen review x2 | done
opus final review | done
owner review round 2 | done
```

**Owner review round 2 (2026-08-12).** Decisions: the primary use case is WORK docs;
personal stays on Vercel in its current shape; one scope, one host (the round-1 mixed
model — Pages docs + Vercel index — is dropped); work has NO Enterprise plan (checked by
the owner in the org settings), so private Pages is impossible and work goes Confluence
for everything; setup gains the personal/work profile with per-repo override. The
GitHub-side design (§1) is kept as the plugin's generic public-repo path, deferred in
this workspace.

**Codex peer consult #2 — Confluence work path (gpt-5.6-sol, 2026-08-12).** Adopted:
git-as-sole-authority with Confluence as a projection; content-addressed attachment
names with verified-then-bind ordering and rollback retention; custody/presentation as
separate gates; lifecycle states with degraded-to-attachment-link; the exit strategy
(attachments outlive the macro vendor); scoped publishing identity by name;
committed per-repo publication config; generated-region index ownership. **Rejected,
scale-stated:** per-space serialization locks and a reconciliation fleet — bounded 409
retries plus one scheduled macro-health check at this scale.

**Qwen adversarial review #2 — the work brief (qwen3.8-max-preview, 2026-08-12;
1 Critical, 1 High, 1 Medium — all adopted).** Critical: attachment upload is the v1
endpoint, not v2 — corrected, and a round-trip proof-of-concept is the first
implementation task. High: the Forge macro's allow-all CSP mode contradicts the lint
gate — CSP pinned to block-all/whitelist, verified at setup. Medium: raw-byte retrieval
needs `Accept: application/octet-stream` and a round-trip test — added to the PoC.

**Round-1 trail (unchanged disposition, details in PR #22 history):** Codex peer consult
#1 (manifest model, fail-closed eligibility, shared-origin, pending-until-verified;
platform-scale machinery rejected); qwen review #1 (Confluence 409 retry and scheduled
eligibility re-check adopted; the authenticated-fetch High declined on measured grounds
with its kernel kept); Opus final review (2 Critical / 6 High / 6 Medium / 3 Low, all 17
dispositioned — its lead finding is the exposure callout at the top of this page,
verified independently before anything acted on it).

Research notes: GitHub Pages limits and plan gating from official GitHub docs; Confluence
attachment behavior from Atlassian KB + issue tracker; macro app capabilities from
Marketplace listings and vendor docs (Narva, Appfire, Forge-based) — all fetched
2026-08-12 via Exa and WebFetch. Context7 was queried both rounds; its Confluence and
Actions libraries returned no matching rows for these specific questions, so primary
sources were read directly.

## Recommendation

```verdict
ship | Two profiles, one host each. Personal: vercel, byte-for-byte as today — docs, index, preview, all of it. Work: Confluence end-to-end — committed pair in git, content-addressed HTML attachment uploaded via the v1 endpoint, custody proven by raw download byte-compare, rendered through a Forge-based HTML macro with CSP pinned to block-all, one generated index page per space, manifest-derived. setup.py asks the profile once per machine with a per-repo override. First implementation task: the attachment round-trip proof-of-concept, then the macro-app approval at work, then the backend interface (stages 4-7) — an epic, not an issue.
risk | The rendered work view rides a third-party macro the custody check cannot cover — custody and presentation are reported as separate claims, and the exit strategy keeps attachments readable without the macro. The macro app needs a work admin install and security approval BEFORE any of this ships — that approval is the critical path. Two private repos still serve publicly today (top of page) — unresolved, owner's call. The plugin keeps a live Vercel dependency for the personal profile by explicit choice.
```

```provenance
source | docs/planning/2026-08-12-hosting-options.md
project | design-doc-publish
measured | 2026-08-12
```
