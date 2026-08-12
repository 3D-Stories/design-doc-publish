# Docs hosting: Vercel to GitHub Pages

```chips
design options | wip
nothing implemented | note
owner decision pending | note
live exposure found | blocked
```

## Why move: the custody chain

Every design doc in this workspace already ships as a committed `.md` + `.html` pair inside
its own repo. The Vercel deploy then publishes a **separate copy** of those bytes from a
temp directory (`publish_doc.py` stage 5). The served page and the committed page are only
provably the same at the moment stage 6 verifies them — after that, nothing ties them
together. A re-deploy, a stale alias, or a project rename can silently decouple the public
URL from the repo's history. That is the custody-chain break this document designs away:
**the repo should BE the host**, so the served bytes are the committed bytes by
construction, not by a one-shot check.

```callout
warn | Found during review: two PRIVATE repos are serving their whole docs trees publicly, today
Measured 2026-08-12, unauthenticated probes. `3D-Stories/rawgentic` (repo visibility
PRIVATE, 510 files under docs/) and `3D-Stories/3dstories-studio` (PRIVATE, 170 files)
both have Pages enabled with `public: true` — review reports, measurement CSVs and a
container-security-posture document all answer HTTP 200 to a bare curl. This predates this
design and is exactly the hazard the eligibility rule below exists to catch. These two
repos are the FIRST inputs to that gate, and whether each stays served is the owner's
call — options: make the repo public deliberately, disable Pages, or prune what docs/
carries. The served-folder rule below (owner decision, PR #22 review round) exists so a
mistake of this shape can never again expose more than one deliberately-curated folder.
```

```callout
info | Evidence: Pages serves the committed bytes faithfully — measured, with its scope stated
Measured 2026-08-12 on `3D-Stories/rawgentic`: the live
`3d-stories.github.io/rawgentic/workflow-diagram.html` is **byte-identical** to
`origin/main:docs/workflow-diagram.html` (both sha256 `af7d74c5…9659c0d`). Scope of this
evidence: one file, one repo, on the legacy build with `docs/.nojekyll` present — it
proves fidelity of the serving path, and it does NOT bless the configuration it was
measured on: that repo is private and should not be serving publicly at all (see the
exposure callout above).
```

## Freshness: what "the diagram is stale" actually was

The owner observed the workflow diagram "hasn't been updated in forever". Measured: the
**hosting is not the stale part**. The live copy exactly matches `main` (above), and `main`
last touched the file 2026-08-10 (`b29135be`). What IS stale is the content: the diagram's
newest REV entry says **plugin 3.158.0** while `origin/main` declares **3.163.0** — five
releases with no REV entry, despite the rev-diagram convention requiring a decision per PR.

Lesson for this design: a hosting migration fixes custody, not freshness. Freshness is a
**process** property — content updates must ride inside each issue's own PR (the same rule
the status-surface convention already states), and the README documentation list in §3 is
the surface that makes a missed update visible.

## 0. The generic shape: hosting is a configured backend

Owner decision (PR #22 review round): the plugin must stay usable by ANYBODY, so this
design does not replace one hardcoded host with another. The plugin's identity is the
contract, not the host: **render → lint → deliver → prove the served bytes equal the
committed bytes**. Any backend that can satisfy that verify step is a valid path.

- **Stages 1–3 (render, name, lint) are shared** across every backend — they already run
  with no account of any kind.
- **Stages 4–7 (eligibility, deliver, verify, index) dispatch per backend.**
- The backend is chosen in the plugin's own configuration (the same file `setup.py`
  manages today), with a per-repo override so one machine can publish personal docs to
  Pages and a work repo to nothing at all. The manifest (§2) records each doc's canonical
  URL, so the index never cares which backend served a row.

```options
vercel | Zero repo requirements; instant pre-merge preview URL; per-doc blast radius; today's working default — existing users keep working with no action | Custody chain broken by design (a separate copy is served); one project per doc; team-scope pin and SSO-wall carrying costs; auto-alias truncates project names past ~35 chars (measured live 2026-08-12) | rejected
pages-actions: Actions deploy of ONE designated folder | Serves exactly the folder you name (e.g. docs/public/) — publishing is an explicit placement, a stray file is never served; no Jekyll, so no .nojekyll hazard and no whole-site failure; exempt from the 10-builds-per-hour limit; can attach the rendered page as a PR preview artifact | A small workflow file per repo (three lines when it references one org-level reusable workflow); needs pages:write + id-token:write; serving still waits on the post-merge run | chosen
pages-legacy: branch build of /docs or root | Zero per-repo build config — one settings toggle; the rawgentic diagram proves the serving path today | GitHub allows ONLY the repo root or /docs as the source — a chosen subfolder is impossible, so committing under docs/ IS publishing, all 510 files of it; Jekyll runs unless docs/.nojekyll exists, and one bad Liquid file fails the WHOLE site; 10 builds/hour soft limit |
none: render and commit only | No account, no egress, no hosting — the committed pair is the deliverable; the right floor for repos whose docs must not be served | No live URL at all; readers open the committed .html locally |
```

**Why the stances land there for THIS workspace.** `vercel` is rejected as this
workspace's doc host by the custody argument — but it remains a fully supported backend,
because it is the current install base and the only path with a pre-merge live preview.
`pages-legacy` is not rejected generically — a public repo that already serves `/docs` and
wants zero setup is a legitimate user — but its cons row is exactly the whole-tree
property the owner declined, so it is not chosen here. `pages-actions` is the chosen
backend for this workspace, and the served folder is the point:

```callout
info | The served-folder rule (owner decision, PR #22 review round)
The whole docs/ tree is NOT served. One designated folder is (default `docs/public/`,
configurable per repo). The publishable `.md` + `.html` pair LIVES in that folder and only
there — one copy, no sync step, no drift. Everything else under docs/ (reviews,
measurements, planning notes, session records) stays unserved. Publishing a doc IS the PR
that places its pair in the folder and adds its manifest row — an explicit, reviewable
act. This replaces the serving-side role of today's stage-5 asset allowlist: nothing
reaches the served folder except what a reviewed PR deliberately put there.
```

## 1. The chosen path in detail (pages-actions)

**Delivery.** One org-level reusable workflow does the deploy; each repo's own workflow
file is three lines referencing it. Trigger: push to the default branch filtered on the
served folder's path. Steps: `configure-pages` → `upload-pages-artifact` with
`path: docs/public` → `deploy-pages` (permissions `pages: write`, `id-token: write` — the
canonical shape in `actions/starter-workflows/pages/static.yml`). Jekyll never runs; the
artifact is served raw.

**URL scheme.** A doc at `docs/public/<file>.html` serves at
`https://<owner>.github.io/<repo>/<file>.html`. `<owner>` is a **per-repo fact**, not a
workspace constant: most projects live under `3D-Stories`, but e.g. `daimonia` and
`xtoys` live under `crandrosoff` (measured). Stable identity moves from a minted Vercel
project name to **repo + committed path**. The `{project}-{purpose}-{ref}` naming
convention survives as the index key and the recommended file slug. Accepted residual
(peer finding, recorded): a repo rename, transfer, or default-branch change breaks every
URL under it — the manifest's stable ids and redirect entries cover *document* renames
only, and URL permanence beyond that would need a custom domain, which this design does
not build.

**How the byte-identity verify carries over.** Stage 6's contract ("the URL serves exactly
the bytes just published") transfers intact and gets stronger: the comparison target is
the committed blob on `main`, so the check proves custody, not just delivery. The
mechanics, in three named parts. (1) Verify runs **after merge**: the publishing session
(the same actor that runs `publish_doc.py` today — a WF2/WF3 run or the owner) runs a
`verify-published` command post-merge; the deploy workflow's own completion is the wake
signal, and a repo may add a verify job inside the workflow itself. (2) The wait budget is
bounded by the deploy workflow's runtime plus propagation — and must comfortably exceed
today's ~25-second stage-6 budget, which does not transfer (the pages-legacy backend
instead polls `GET /repos/{owner}/{repo}/pages/builds/latest` past its 10-minute build
ceiling). (3) **The merge is the publication trigger, never its completion** — a doc is
pending until its verify passes, and pending has a concrete home: the docs-index lists a
row only after its verify passes, so an unverified doc is visibly absent, and a failed or
delayed deploy is the verify command's reported failure, never a silent success. Scope
note (qwen finding): this verify path applies to **publicly served** Pages only — an
access-controlled Enterprise Pages site answers with a login redirect, which the verifier
already refuses.

**What replaces the pre-merge preview.** Vercel gave the author a live URL before the PR
existed. Under any Pages backend nothing serves until after merge, so review happens on
the committed `.html` — opened locally, or attached by the deploy workflow's PR-run as a
CI artifact. This loss is real and stated here rather than discovered later. A setup that
cannot live without pre-merge preview keeps the `vercel` backend — that is what generic
means.

```callout
warn | The eligibility gate — the axis is PUBLIC vs NOT-PUBLIC, never personal vs work
GitHub's own docs: Pages is available for PUBLIC repos on Free, and for public AND private
repos on Pro/Team/Enterprise. But access-controlled (privately visible) Pages sites require
**GitHub Enterprise Cloud**. Below that plan, a private repo's Pages site is **public to
the whole internet** — which is not a hypothetical: it is the measured state of two repos
in this workspace today (top of page). The served-folder rule shrinks the blast radius of
a mistake; it does NOT change this gate. Fail CLOSED: eligibility is the PAIR of facts
`repo.visibility == public` OR `pages.public == false` (access control confirmed) — read
from the API, never inferred from who owns the repo. A private repo is ineligible until
the owner explicitly flips it public or approves the exposure, whether it is a personal
project or a work mirror (`chorestory` and `saystory` are private personal repos today
and are treated exactly like work repos until then). A later visibility or plan change
can expose a site while nothing publishes, so eligibility is re-checked on a SCHEDULE (a
small daily workflow where the index lives), and again at every index rebuild (qwen
finding: coupling the check to publish events alone leaves a downgraded repo exposed
until the next unrelated publish).
```

```callout
info | Shared origin (peer finding)
Every project site under one owner shares the `<owner>.github.io` origin. A script on one
published page can read another page's storage on that origin. These docs are
self-contained by the existing lint gate (no external requests); the rule to keep is that
published HTML stays script-inert beyond the renderer's own inline behavior — which the
gate already enforces.
```

### Publish flow today (vercel backend) — for comparison

```nodes
publish_doc.py
  render + lint | stages 1-3, local bytes gated before any network call
    vercel link + deploy | stage 5 uploads a SEPARATE copy from a temp dir | upload
      verify_live | stage 6 byte-compares the alias, retried over ~25s | fetch
        docs-index refresh | stage 7 rebuilds from vercel project ls | deploy
  commit + PR | the SAME bytes, on their own separate track | AC6
```

### Publish flow, pages-actions (chosen) — proposed

```nodes
publish_doc.py
  render + lint | stages 1-3 unchanged, still local, still gated
    place the pair in docs/public/ | publishing IS this placement, inside the PR | ~
      merge | the reviewed pair lands on main | ~
        deploy workflow | upload-pages-artifact serves ONLY the designated folder | ~
          verify-published | run by the publishing session; byte-compare vs the committed blob | ~
            index refresh | row appears only after verify passes — pending = absent | ~
```

### Publish flow, pages-legacy — supported, not chosen here

```nodes
publish_doc.py
  render + lint | stages 1-3 unchanged
    commit + PR + merge | the pair lands anywhere under docs/ — ALL of docs/ is served | ~
      Pages build | Jekyll unless docs/.nojekyll; poll builds/latest past the 10-min ceiling | ~
        verify-published | same byte-identity contract | ~
```

**Limits that matter (official docs, fetched 2026-08-12):** published site max 1 GB; soft
100 GB/month bandwidth; deploys time out at 10 minutes. None binds this workload — the
largest doc pages here are single-digit MB.

## 2. Index hosting, by audience

The split below is about **where readers look**, never about what may be served — serving
eligibility is §1's public/not-public gate, and it applies identically to personal and
work repos.

```options
Public-eligible repos: keep the Vercel docs-index, rows link into github.io | No new hosting; the index page and its verify loop already exist; one-line change per row target | Keeps one Vercel project alive after the docs leave — so the vercel CLI, its team-scope pin and its SSO-wall failure mode stay in the loop for the index alone | chosen
Not-public repos (work mirrors, private personal): a Confluence index page, updated by Actions on merge | Docs list lives where work already looks; REST API v2 is a 40-line script or an off-the-shelf action (md2cf, confluence-updater, atlcli all fit) | Needs an API token as a repo secret; page updates must GET the version and increment it — on a 409 the job re-fetches the version and retries on a bounded backoff, and a persistent failure surfaces as a workflow annotation, never a silent skip | chosen
A Pages-hosted index (owner site or dedicated repo) | Zero external dependencies — the whole system becomes GitHub-only; same custody property as the docs | Needs a cross-repo rebuild trigger (repository_dispatch or schedule) since one repo cannot watch another; a new repo to own |
```

**Derivation, all options — from the manifest, and ONLY the manifest.** The index is
derived, never hand-edited (the #125 rule survives). Each repo commits a small
`docs/publications.json`: one entry per published doc — stable id, title, purpose, source
path, HTML path, audience, canonical URL, **and the backend that serves it**. The index
reads manifests and nothing else: the GitHub API's only job is to LOCATE manifests (which
repos have one) — it is never a second derivation source, and no `docs/**/*.html` scan
exists anywhere (one source, so the three consumers cannot disagree). A rename is an
explicit redirect entry instead of a silent identity change, and the README table (§3)
generates from the same rows. Under the served-folder rule the manifest and the folder say
the same thing two ways, and the PR-CI check (§3) fails a PR where they disagree.
**Freshness:** rebuilt in the same post-merge step that verifies the doc (option a), by
the Actions job itself (option b), or on `repository_dispatch` (option c). **The stage-7
anti-race check has a successor:** today's guard compares the built index against a live
`vercel project ls` count; its replacement invariant is "every index row equals a manifest
entry at the commit the rebuild enumerated" — the source is versioned data, so an
interleaved publisher's row is picked up by the next rebuild rather than silently lost,
and the rebuild reports the SHAs it read.

**The custody rule for Confluence.** The repo stays the document of record, always. For
repos Pages cannot serve, the Confluence page carries the content too — a **labeled
mirror**, stamped with the source commit and content digest so drift is detectable — but
it never becomes canonical.

## 3. The README "Documentation" section

Every project README gains a maintained `## Documentation` section: one table row per
published doc — title, purpose, the committed `.md` path, and the live URL. **Generated
from the same `docs/publications.json` the index reads (§2)**, so the README, the index
and the manifest cannot disagree. Marker-fenced so tooling can rewrite it without touching
hand-written prose:

    <!-- docs-list:begin -->
    | Doc | Purpose | Source | Live |
    | --- | ------- | ------ | ---- |
    | Hosting options | design | docs/public/2026-08-12-hosting-options.md | (URL) |
    <!-- docs-list:end -->

**The rule that keeps it fresh:** the row is added or updated **inside the same PR that
adds or changes the doc** — never batched into a trailing docs PR. This is the existing
status-surface convention applied to documentation, and it is the process fix for the
freshness gap measured in the rawgentic diagram (a REV convention with no visible surface
drifted five releases; a README table makes the same drift visible in review).
Enforcement lives in **PR CI** (final-review correction: once the merge is the publish,
a publish-time refusal has nothing left to refuse) — a check that fails the PR when the
served folder changes without its manifest row and README row, or vice versa.

## 4. Plugin impact and the retirement of vercel.app URLs

Stage-by-stage. Stages 1–3 stay one shared implementation; stages 4–7 become the backend
interface, and each backend implements the four:

```nodes
publish_doc.py
  stages 1-3 | render, name, lint — shared, unchanged, refuse before any network call
  stage 4 eligibility | vercel: project inspect · pages: the visibility/public PAIR, fail closed · none: always | backend
  stage 5 deliver | vercel: CLI deploy · pages-actions: place pair in the served folder · legacy: commit under docs/ · none: commit | backend
  stage 6 verify | ONE shared contract: byte-identity vs the committed blob, per-backend wait strategy | backend
  stage 7 index | manifest-derived rows, per audience (section 2) | backend
setup.py
  checks | per configured backend: gh auth + Pages eligibility, or the existing vercel checks, or nothing for none | ~
build_index.py
  source | manifests located via the GitHub API replace vercel project ls | ~
```

**What goes, what stays, what grows (final-review correction — an earlier draft claimed
the whole security surface "disappears", which was wrong in both directions).** Goes, on
Pages backends: the duplicate-project minting hazard — there is no project to mint. Stays:
the team-scope pin and the SSO-wall failure mode, for every setup that keeps a `vercel`
backend or the Vercel docs-index (§2 option a keeps `refresh_index`'s CLI call and its
pinned scope). Grows, then shrinks: `stage_assets` is today the gate that refuses shipping
a non-image reference — the measured `.env`/`credentials.json` case — and a served TREE
has no serving-side equivalent; the served-FOLDER rule closes most of that gap (nothing is
served that a reviewed PR did not place), and the PR-CI check on the served folder's diff
(§3) is the explicit successor.

**Existing vercel.app URLs (~37 projects).** Retirement is evidence-gated and ordered so
no reader ever holds a dead link (final-review corrections applied): (1) publish and
**verify each new destination live**; (2) only then switch that doc's index row to the
github.io URL; (3) replace each vercel.app page with a meta-refresh redirect to its new
home — written and deployed by a small dedicated redirect script OUTSIDE `publish_doc.py`,
because the lint gate refuses a meta refresh as an external request (executed against the
gate 2026-08-12, finding `external-requests: external request via meta refresh`) and that
refusal is correct for real documents; (4) after a grace period the owner deletes the
Vercel projects — the only destructive step, and it is theirs. Exit criterion for (4):
every destination verified live and the docs-index carrying zero vercel.app rows.

## Review trail

```chips
codex peer consult | done
qwen adversarial review | done
opus final review | done
owner review round 1 | done
```

**Owner review round 1 (PR #22, 2026-08-12).** Two directions, both applied. First: do
NOT serve the whole `docs/` tree — a designated folder is served, and it must exist as an
explicit thing. That requirement is impossible on the legacy build (root or `/docs` only),
so it flipped the chosen backend from pages-legacy to pages-actions and produced the
served-folder rule (§0). Second: the plugin must stay generic — several paths, picked by
each user's setup — which produced the backend model in §0 (`vercel`, `pages-actions`,
`pages-legacy`, `none`, sharing stages 1–3 and the byte-identity verify contract). The
owner also named the workspace-wide documentation inconsistency as its own problem;
that is filed as a separate rawgentic issue, not solved here.

**Codex peer consult (gpt-5.6-sol, 2026-08-12, report:
`docs/reviews/peer-2026-08-12-hosting-options-2026-08-12.md`).** Adopted: the
`docs/publications.json` manifest as the derivation source for index and README (no
scan-to-publish, stable ids, explicit rename redirects); fail-closed Pages eligibility with
re-checks on rebuild; the shared-origin note; pending-until-verified publication state;
Confluence work mirrors labeled with source commit and digest. **Rejected, with reasons:**
an external publication-state store, a dedicated catalog repo with `repository_dispatch`
fan-in, and a scheduled reconciliation fleet — right for a many-team platform, out of
proportion for ~37 documents with one owner; the post-merge verify plus manifest-derived
index covers the same failure classes at this scale, and the catalog repo remains §2
option (c) if the personal side ever drops Vercel entirely. The rename/transfer risk the
peer raised is RECORDED (§1) as an accepted residual rather than silently dropped.

**Qwen adversarial review (qwen3.8-max-preview, 2026-08-12, report:
`docs/reviews/2026-08-12-hosting-options-md-2026-08-12.md`; 1 High, 2 Medium).** Adopted:
the Confluence 409 retry rule; the scheduled eligibility re-check. **Partially declined,
with the reason recorded:** the High finding asked stage-6 verify to authenticate with a
repo-scoped token — measured false on the mechanism (a private repo's public Pages site
answers an unauthenticated fetch with 200), and an access-controlled site would hit the
verifier's existing redirect-refusal. The kernel kept: the verify path is explicitly
scoped to publicly served Pages. The final review then correctly turned the decline's own
premise — "every option chosen here serves publicly" — into the eligibility question at
the top of this page.

**Opus final review (2026-08-12; 2 Critical, 6 High, 6 Medium, 3 Low — all 17
dispositioned).** Its lead finding was VERIFIED INDEPENDENTLY before anything was acted
on: the two private repos serving publicly (exposure callout, top of page). Applied: the
evidence callout states its own scope and the violation it sits on (C1); the
recommendation axis is public/not-public, never personal/work (C2); the served-tree
consequence is stated wherever the manifest is discussed (H1 — now largely superseded by
the served-folder rule); the redirect step moved outside the lint gate, with the gate's
refusal executed and quoted (H2); the security-surface claim replaced by goes/stays/grows
(H3); the post-merge verify got a named runner and pending got a concrete home — absence
from the index (H4); `.nojekyll` and whole-site build failure are stated as pages-legacy
properties (H5, count corrected to six Liquid files); the pre-merge preview loss is
acknowledged with its replacement and with the vercel backend as the keep-preview path
(H6); one derivation source (M1); the wait budget must exceed the backend's ceiling (M2);
verify-before-switch ordering (M3); the eligibility pair read from the API (M4); the
anti-race successor invariant named (M5); the rename residual recorded (M6); `<owner>`
made per-repo (L1); README enforcement moved to PR CI (L2); the evidence scoped (L3).

Research notes: GitHub Pages limits, plan availability, and access-control gating fetched
from official GitHub docs 2026-08-12. Confluence pipeline options surveyed via Exa (REST
API v2, md2cf, confluence-updater, atlcli). Context7 was queried per the run's method but
returned no matching rows for the Pages deploy workflow; the canonical
`actions/starter-workflows/pages/static.yml` was read directly instead.

## Recommendation

```verdict
ship | Make hosting a configured backend with one shared contract (render, lint, byte-identity verify): vercel stays supported as the zero-setup path with pre-merge preview; pages-actions serves ONE designated folder (default docs/public/) and is this workspace's choice; pages-legacy remains for public repos that accept whole-tree serving; none covers repos whose docs must not be served. Eligibility for any Pages backend is the public/not-public pair, per repo. Index split by where readers look: the Vercel docs-index for public-eligible repos, Confluence index+mirror otherwise. README Documentation sections everywhere, generated from the per-repo manifest, updated inside each issue's own PR, enforced in PR CI.
risk | Two private repos are serving publicly TODAY (top of page) — that decision precedes any migration work, and the served-folder rule only shrinks future blast radius. Serving on Pages backends waits on a post-merge run, and pre-merge preview exists only on the vercel backend. A repo rename still breaks its URLs — accepted residual. The backend abstraction is the largest plugin change in this design: stages 4-7 become an interface, and that is an epic, not an issue.
```

```provenance
source | docs/planning/2026-08-12-hosting-options.md
project | design-doc-publish
measured | 2026-08-12
```
