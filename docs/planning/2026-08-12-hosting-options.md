# Docs hosting: Vercel to GitHub Pages

```chips
design options | wip
nothing implemented | note
owner decision pending | note
live exposure found | blocked
```

```callout
warn | Found during review: two PRIVATE repos are serving their whole docs trees publicly, today
Measured 2026-08-12, unauthenticated probes. `3D-Stories/rawgentic` (repo visibility
PRIVATE, 510 files under docs/) and `3D-Stories/3dstories-studio` (PRIVATE, 170 files)
both have Pages enabled with `public: true` — review reports, measurement CSVs and a
container-security-posture document all answer HTTP 200 to a bare curl. This predates this
design and is exactly the hazard the eligibility rule below exists to catch. These two
repos are the FIRST inputs to that gate, and whether each stays served is the owner's
call — options: make the repo public deliberately, disable Pages, or prune what docs/
carries.
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
info | Evidence: Pages serves the committed bytes faithfully — measured, with its scope stated
Measured 2026-08-12 on `3D-Stories/rawgentic`: the live
`3d-stories.github.io/rawgentic/workflow-diagram.html` is **byte-identical** to
`origin/main:docs/workflow-diagram.html` (both sha256 `af7d74c5…9659c0d`). Scope of this
evidence: one file, one repo, with `docs/.nojekyll` present (§1) — it proves fidelity of
the serving path, and it does NOT bless the configuration it was measured on: that repo is
private and should not be serving publicly at all (see the exposure callout above).
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

## 1. Doc hosting: how the committed HTML gets served

```options
Pages, legacy build from main:/docs | Zero per-repo build config — one settings toggle; serves exactly what merges; fidelity of the serving path measured live | Serving waits on an async Pages build after merge; soft limit of 10 branch builds per hour per site; ONE bad file fails the whole site build, so blast radius is the site, not the doc; no live preview before merge | chosen
Pages, Actions deploy | Deploy step is visible and gate-able in CI; exempt from the 10-builds-per-hour soft limit; can re-lint and preview-artifact in the workflow | A workflow file to roll out and maintain in every repo; needs pages:write + id-token:write permissions; more moving parts for the same bytes |
Status quo: Vercel per-doc projects | Already built and verified; instant alias and pre-merge preview URL; per-doc blast radius; hosting survives repo deletion | Custody chain broken by design (separate copy); one Vercel project per doc (~37 already, measured on #12); team-scope pinning and SSO-wall failure modes are permanent carrying costs | rejected
```

**Two preconditions for Option A, both load-bearing.** First: `docs/.nojekyll` must exist
before Pages is enabled. The legacy build IS the Jekyll build; without that file Jekyll
processes the tree, and six committed markdown files in `rawgentic/docs` alone carry
Liquid syntax (`{{`/`{%`) that would fail the WHOLE site build. Both live sites carry the
file today, which is why the fidelity evidence above holds. Second: the served scope is
the **entire `docs/` directory** — committing under `docs/` IS publishing under Option A.
Review reports, measurements, session notes: everything there is served. Audience is
therefore a property of the DIRECTORY, not of any manifest or index — a repo either keeps
`docs/` fully publishable or does not enable Pages.

**What replaces the pre-merge preview.** Vercel gave the author a live URL before the PR
existed. Under Option A nothing serves until after merge, so review happens on the
committed `.html` — opened locally (`file://` or a one-line local server), or attached as
a PR CI artifact if a repo wants a click-through. This loss is real and is the row most
likely to matter to the owner; it is stated here rather than discovered later.

**URL scheme (both Pages options).** A doc at `docs/planning/<file>.html` serves at
`https://<owner>.github.io/<repo>/planning/<file>.html` — the `/docs` prefix is the served
root. `<owner>` is a **per-repo fact**, not a workspace constant: most projects live under
`3D-Stories`, but e.g. `daimonia` and `xtoys` live under `crandrosoff` (measured). Stable
identity moves from a minted Vercel project name to **repo + committed path**, which is
exactly the custody property we want. The `{project}-{purpose}-{ref}` naming convention
survives as the index key and the recommended file slug. Accepted residual (peer finding,
now recorded): a repo rename, transfer, or default-branch change breaks every URL under
it — the manifest's stable ids and redirect entries cover *document* renames only, and
URL permanence beyond that would need a custom domain, which this design does not build.

**How the byte-identity verify carries over.** Stage 6's contract ("the URL serves exactly
the bytes just published") transfers intact and gets stronger: the comparison target is the
committed blob on `main`, so the check proves custody, not just delivery. The mechanics
change in three named ways. (1) Verify runs **after merge**: the publishing session (the
same actor that runs `publish_doc.py` today — a WF2/WF3 run or the owner) runs a
`verify-published` command post-merge; a repo may additionally wire it as a docs-verify
Action, but the session-run command is the baseline so Option A carries no mandatory
workflow file. (2) The wait loop polls the Pages build API
(`GET /repos/{owner}/{repo}/pages/builds/latest` until `status: built` for the merged
SHA) on a budget that must EXCEED the 10-minute build ceiling — today's ~25s stage-6
budget does not transfer. (3) **The merge is the publication trigger, never its
completion** — a doc is pending until its verify passes, and pending has a concrete home:
the docs-index lists a row only after its verify passes, so an unverified doc is visibly
absent, and a failed or delayed build is the verify command's reported failure, never a
silent success. Scope note (qwen finding): this verify path applies to **publicly served**
Pages only — every option chosen here serves publicly or routes to Confluence. An
access-controlled Enterprise Pages site answers with a login redirect, which the verifier
already refuses; verifying one would need an authenticated fetch this design deliberately
does not build.

```callout
warn | The private-repo caveat — the axis is PUBLIC vs NOT-PUBLIC, never personal vs work
GitHub's own docs: Pages is available for PUBLIC repos on Free, and for public AND private
repos on Pro/Team/Enterprise. But access-controlled (privately visible) Pages sites require
**GitHub Enterprise Cloud**. Below that plan, a private repo's Pages site is **public to
the whole internet** — which is not a hypothetical: it is the measured state of two repos
in this workspace today (top of page). Fail CLOSED: eligibility is the PAIR of facts
`repo.visibility == public` OR `pages.public == false` (access control confirmed) — read
from the API, never inferred from who owns the repo. A private repo is ineligible until
the owner explicitly flips it public or approves the exposure, whether it is a personal
project or a work mirror. A later visibility or plan change can expose a site while
nothing publishes, so eligibility is re-checked on a SCHEDULE (a small daily workflow
where the index lives), and again at every index rebuild (qwen finding: coupling the check
to publish events alone leaves a downgraded repo exposed until the next unrelated
publish).
```

```callout
info | Shared origin (peer finding)
Every project site under one owner shares the `<owner>.github.io` origin. A script on one
published page can read another page's storage on that origin. These docs are
self-contained by the existing lint gate (no external requests); the rule to keep is that
published HTML stays script-inert beyond the renderer's own inline behavior — which the
gate already enforces.
```

### Publish flow today (Vercel) — for comparison

```nodes
publish_doc.py
  render + lint | stages 1-3, local bytes gated before any network call
    vercel link + deploy | stage 5 uploads a SEPARATE copy from a temp dir | upload
      verify_live | stage 6 byte-compares the alias, retried over ~25s | fetch
        docs-index refresh | stage 7 rebuilds from vercel project ls | deploy
  commit + PR | the SAME bytes, on their own separate track | AC6
```

### Publish flow, Option A (Pages legacy) — proposed

```nodes
publish_doc.py
  render + lint | stages 1-3 unchanged, still local, still gated
    commit + PR + merge | the pair lands on main — the merge IS the deploy | ~
      Pages build | GitHub builds main:/docs; poll builds/latest past the 10-min ceiling | ~
        verify-published | run by the publishing session; byte-compare vs the committed blob | ~
          index refresh | row appears only after verify passes — pending = absent | ~
```

### Publish flow, Option B (Pages via Actions) — proposed

```nodes
merge to main
  docs-deploy workflow | triggers on docs/** path filter | push event ~
    upload-pages-artifact | packages the docs tree | ~
      deploy-pages | pages:write + id-token:write, exempt from build soft limit | ~
        verify job | same byte-identity fetch, inside the workflow run | ~
```

**Limits that matter (official docs, fetched 2026-08-12):** published site max 1 GB; soft
100 GB/month bandwidth; deploys time out at 10 minutes. None binds this workload — the
largest doc pages here are single-digit MB.

## 2. Index hosting, by audience

The split below is about **where readers look**, never about what may be served — serving
eligibility is §1's public/not-public gate, and it applies identically to personal and
work repos. A private personal repo (`chorestory` and `saystory` are both private today)
is treated exactly like a work repo until the owner flips it public.

```options
Public-eligible repos: keep the Vercel docs-index, rows link into github.io | No new hosting; the index page and its verify loop already exist; one-line change per row target | Keeps one Vercel project alive after the docs leave — so the vercel CLI, its team-scope pin and its SSO-wall failure mode stay in the loop for the index alone | chosen
Not-public repos (work mirrors, private personal): a Confluence index page, updated by Actions on merge | Docs list lives where work already looks; REST API v2 is a 40-line script or an off-the-shelf action (md2cf, confluence-updater, atlcli all fit) | Needs an API token as a repo secret; page updates must GET the version and increment it — on a 409 the job re-fetches the version and retries on a bounded backoff, and a persistent failure surfaces as a workflow annotation, never a silent skip | chosen
A Pages-hosted index (owner site or dedicated repo) | Zero external dependencies — the whole system becomes GitHub-only; same custody property as the docs | Needs a cross-repo rebuild trigger (repository_dispatch or schedule) since one repo cannot watch another; a new repo to own |
```

**Derivation, all options — from the manifest, and ONLY the manifest.** The index is
derived, never hand-edited (the #125 rule survives). Each repo commits a small
`docs/publications.json`: one entry per published doc — stable id, title, purpose, source
path, HTML path, audience, canonical URL. The index reads manifests and nothing else: the
GitHub API's only job is to LOCATE manifests (which repos have one) — it is never a second
derivation source, and no `docs/**/*.html` scan exists anywhere (one source, so the three
consumers cannot disagree). A rename is an explicit redirect entry instead of a silent
identity change, and the README table (§3) generates from the same rows. To be precise
about what the manifest governs (final-review finding): it governs what is **indexed**.
Under Option A the server serves the whole `docs/` tree regardless — a stray HTML file
never self-INDEXES, but it is still served, which is why §1 makes audience a property of
the directory. **Freshness:** rebuilt in the same post-merge step that verifies the doc
(option a), by the Actions job itself (option b), or on `repository_dispatch` (option c).
**The stage-7 anti-race check has a successor:** today's guard compares the built index
against a live `vercel project ls` count; its replacement invariant is "every index row
equals a manifest entry at the commit the rebuild enumerated" — the source is versioned
data, so an interleaved publisher's row is picked up by the next rebuild rather than
silently lost, and the rebuild reports the SHAs it read.

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
    | Hosting options | design | docs/planning/2026-08-12-hosting-options.md | (URL) |
    <!-- docs-list:end -->

**The rule that keeps it fresh:** the row is added or updated **inside the same PR that
adds or changes the doc** — never batched into a trailing docs PR. This is the existing
status-surface convention applied to documentation, and it is the process fix for the
freshness gap measured in the rawgentic diagram (a REV convention with no visible surface
drifted five releases; a README table makes the same drift visible in review).
Enforcement lives in **PR CI** (final-review correction: once the merge is the publish,
a publish-time refusal has nothing left to refuse) — a check that fails the PR when a doc
under `docs/` changes without its manifest row and README row.

## 4. Plugin impact and the retirement of vercel.app URLs

Stage-by-stage, for the chosen options:

```nodes
publish_doc.py
  stages 1-3 | render, name, lint — unchanged, still refuse before any network call
  stage 4 | becomes the eligibility PAIR: repo.visibility + pages.public, fail closed | gh api
  stage 5 | replaced by the PR merge; the asset allowlist moves to PR CI (see below) | ~
  stage 6 | verify-published: post-merge, poll past the build ceiling, byte-compare | ~
  stage 7 | index refresh per section 2, manifest-derived | ~
setup.py
  checks | ADDS gh auth + Pages eligibility; KEEPS the vercel checks while the index stays on Vercel | ~
build_index.py
  source | manifests located via the GitHub API replace vercel project ls | ~
```

**What goes, what stays, what grows (final-review correction — the first draft claimed the
whole security surface "disappears", which was wrong in both directions).** Goes: the
duplicate-project minting hazard (stages 4-5's hardest-won code) — there is no project to
mint. Stays: the team-scope pin and the SSO-wall failure mode, exactly as long as the
docs-index remains a Vercel project (§2 option a keeps `refresh_index`'s CLI call and its
pinned scope). Grows: `stage_assets` is today the gate that refuses shipping a non-image
reference — the measured `.env`/`credentials.json` case — and under Pages every file under
`docs/` is served whatever its suffix, so that allowlist has NO serving-side equivalent.
Its successor is the PR-CI check on the `docs/` diff (§3), plus §1's rule that a repo
either keeps `docs/` fully publishable or does not enable Pages.

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
```

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
peer raised is now RECORDED (§1) as an accepted residual rather than silently dropped.

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
evidence callout now states its own scope and the violation it sits on (C1); the
recommendation axis is public/not-public, never personal/work (C2); manifest wording
corrected to self-INDEXES with the served-tree consequence stated (H1); the redirect step
moved outside the lint gate, with the gate's refusal executed and quoted (H2); the
security-surface claim replaced by goes/stays/grows (H3); the post-merge verify got a
named runner and pending got a concrete home — absence from the index (H4);
`docs/.nojekyll` is a stated precondition and whole-site build failure a stated con (H5,
count corrected to six Liquid files); the pre-merge preview loss is acknowledged with its
replacement (H6); one derivation source (M1); the poll budget must exceed the build
ceiling (M2); verify-before-switch ordering (M3); the eligibility pair read from the API
(M4); the anti-race successor invariant named (M5); the rename residual recorded (M6);
`<owner>` made per-repo (L1); README enforcement moved to PR CI (L2); the evidence scoped
(L3).

Research notes: GitHub Pages limits, plan availability, and access-control gating fetched
from official GitHub docs 2026-08-12. Confluence pipeline options surveyed via Exa (REST
API v2, md2cf, confluence-updater, atlcli). Context7 was queried per the run's method but
returned no matching rows for the Pages deploy workflow; the canonical
`actions/starter-workflows/pages/static.yml` was read directly instead.

## Recommendation

```verdict
ship | Option A (Pages legacy main:/docs) for doc hosting, gated per repo on the PUBLIC/NOT-PUBLIC pair — never on personal vs work. Eligible today: public repos only (13 of 51 in 3D-Stories; a private repo becomes eligible only when the owner deliberately flips it public). Index split by where readers look: the existing Vercel docs-index for public-eligible repos, a Confluence index+mirror for everything Pages cannot serve. README Documentation sections everywhere, generated from the per-repo manifest, updated inside each issue's own PR, enforced in PR CI.
risk | Two private repos are serving publicly TODAY (top of page) — that decision precedes any migration work. One bad file under docs/ fails a whole site's Jekyll-legacy build, so docs/.nojekyll is a precondition. Serving waits on an async Pages build, so the verify poll budget must exceed the 10-minute ceiling. Pre-merge preview is lost and replaced by the committed .html. A repo rename still breaks its URLs — accepted residual.
```

```provenance
source | docs/planning/2026-08-12-hosting-options.md
project | design-doc-publish
measured | 2026-08-12
```
