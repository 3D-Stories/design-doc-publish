# design-doc-publish — campaign log

Rolling program log: one section per issue, newest first. Created 2026-08-13 with issue
#23 (the shared-doc design-artifact convention; style roadmap).

```stats
8 | issues on this log
59 | newest: shipped, a minutes doc type and style
3192 | suite with this PR, was 3119
```

```callout
info | Read this first — what this log is
One section per issue, refreshed inside that issue's own PR (a filed-but-unstarted
issue gets a backlog section at WF1 time). The stats above always describe the NEWEST
state; older sections keep their text as historical record.
```

## #59 — A minutes doc type and style, for meeting minutes — shipped

PR open 2026-09-02, carrying the whole style. Refreshed here from the backlog section it
started as, which is this log's convention: a section is rewritten inside its own issue's PR.

The chip is stated in the HEADING deliberately. Left to the body it read DONE, picked out of
the phrase "records what was **done**" in the Robert's Rules paragraph below — a status
nobody wrote, sitting beside prose that still said "unstarted". `roadmap_status_chip` gives a
definitive HEADING status precedence precisely so the author can state it, and this is that.

**What shipped:** a `minutes` template module and its registration; `DOC_TYPE_TAGS` and
`FIRST_READ_DEVICES` entries, with `timeline` excluded so the type cannot express a
transcript; a `minutes` purpose on the CLI; four documentation surfaces; a gallery example
with its rendered page and screenshot; the cross-style rendered page; and the tests. The
suite goes 3119 to 3192 passing with no regression.

**What did NOT ship, stated because the gap is real:** the publish gate checks that a page
carries the three block TAGS its style opens with, never their role, position or content. So
a minutes page can drop its attendee region, or carry an unrelated verdict key, and still
publish. Role-level and semantic structure is guarded by `test_minutes_template.py` instead.

**The state before this issue, kept as the record it was written as.** There was no minutes
output. The roster was read rather than recalled: thirteen `--style`
templates and eleven `--type` purposes, and neither list carried a minutes entry. The only
occurrences of the word in this repository are two test comments about wall-clock time. Meeting
write-ups ship today as `--type analysis --style analysis`, which gives a section index and a
verdict block but no attendee block, no decision register and no action items with an owner.

**Three constraints came from external research rather than from intuition** — a four-lane run on
2026-09-02, reported at `claude_docs/research/2026-09-02-meeting-minutes-prior-art.md` in the
workspace, with every claim marked confirmed or inferred.

- **A minutes document is not a restyled analysis.** Robert's Rules of Order says minutes record
  what was **done**, not what was said, and that summarizing discussion is "improper". Confirmed
  from two fetched sources, one of them `robertsrules.com` itself. The `analysis` style is largely
  a record of what was said, so this is a different document and not a new stylesheet over it.
- **The agreed-versus-decided vocabulary is ours to invent.** Two lanes went looking for
  practitioner vocabulary separating a premise the room AGREED from a course of action it CHOSE.
  Neither found any. Practice makes the distinction by WORDING: an unvoted consensus takes a hedge
  phrase, a vote takes a full motion record with mover, seconder, exact wording and count. The
  first document to render is a brainstorm where the room agreed four premises and chose none of
  sixty options, so the distinction is load-bearing rather than academic.
- **No published convention covers a RANGED citation.** The one placement convention found is a
  transcription vendor's own house style, by its own admission, and it addresses a single timecode
  only. Ninety of the kickoff's 120 traces carry a distinct end segment, so
  `_(trace: 22:32, segments 381 to 393)_` sits outside every convention found. Unprecedented
  rather than wrong, and AC13 requires the template's docstring to say so.

**One fork is left to the design step, deliberately.** Two currently-used governance formats mark
a decision in opposite ways, and both were fetched: `openui/open-ui` and `json-ld/minutes` tag it
inline with `RESOLVED:`, while `nodejs/TSC` tags nothing and leaves a reader to infer it from
prose. Those first two are ONE witness and not two — both run the same Zakim and RRSAgent bots,
confirmed by reading the bots' own lines in each file. So an explicit marker is a choice, never a
standard.

**A sharper disagreement is recorded rather than resolved.** Robert's Rules says minutes record
what was done. The W3C convention keeps the FULL timestamped record of what was said and tags the
outcomes inside it. The two most-cited precedents disagree about what a minutes document IS.
Neither is wrong — one governs an assembly's official record, the other serves a working group
that wants its reasoning recoverable — and a template picks a side or serves both.

**No committed artifact found puts a synthesized answer above the record.** Both W3C artifacts
were read in full, the second one specifically in an attempt to falsify this, which failed: its
rendered page goes from the title straight into Topic 1, with no summary section and no
resolutions heading. A reader must scan the transcript line by line to find a decision. So the
summary-first shape has no precedent, and it fixes the exact defect that precedent carries.

**Deferred, with reasons rather than silently.** A structured owner field on `steps` is out of
scope: no block carries one, verified by grep, and `report.py:17-19` already declined it as a
renderer change rather than a stylesheet one. Owners go in as text. #39's optional fourth field is
the precedent if the block is ever widened, and widening it would touch `spec` and `report` too.
The publish-time stamp residual is #31. Generating the kickoff's actual minutes is content in
another repository.

**Risk sits in two places.** Two exact-equality tests pin `DOC_TYPE_TAGS` and `FIRST_READ_DEVICES`
against the `## Doc types` table in `docs/design-language.md`, so that table is part of the code
change and not documentation to follow up. And `test_docs_pages_current.py` arrived with #58 an
hour before this issue was filed, so no style has yet been added under it — the flow in
`regen_docs_pages.py` applies, rather than publishing first and fixing the gate afterwards.

Baseline to measure against, taken on `e74b409` on 2026-09-02: **3119 passed, 8 skipped, exit 0**,
in 53 seconds, on `pytest 9.0.3` and `node v22.22.1`.

## #56 — A committed page must re-render to itself

`campaign-log.html` was committed missing a whole section of its own markdown, and
re-rendering it with `--project design-doc-publish` also flipped the page accent from teal to
green. Two independent defects wearing one symptom, and a census found the blast radius was
**13 of 18** committed `docs/` pairs, not one.

- **The accent was chosen by sha256.** `pack_for("design-doc-publish", …)` returned
  `origin: fallback`. All three doors were shut in order: the configured workspace entry is
  `{"name": "design-doc-publish"}` with **no `path`**, so `_project_config` returned `None`
  silently (`vdl_packs.py:207-211`, the deliberate #9 case); the project was absent from
  `SEEDS`; so `_fallback` hashed the name into `PALETTE`. The first of those reads
  `~/.config/design-doc-publish/workspace.json`, which is not in git — so a public page's
  branding depended on unversioned machine state.
- **The chain is made to CONVERGE, not reordered.** `declared`-beats-`seed` is deliberate
  (`vdl_packs.py:48-54` says so for chorestory), so instead the two reachable answers are made
  identical: a `SEEDS` entry plus a matching `vdl` block in this repository's own committed
  `.rawgentic.json`. Tests pin it in **both** directions — the agreement IS the fix, and either
  half alone leaves the other free to drift the defect back.
- **Convergence alone was NOT enough, and the cross-model review caught it at Critical.** A
  workspace file could still point the NAME at a *different tree* whose config declared another
  colour; production then emitted that colour while the new guard stayed green, because the
  guard passes `workspace_file=None` by design. Measured: production emitted
  `--accent:#eeeeee` where the committed sources say `#b7e87f`. The first draft of the design
  note had dismissed this as "a misconfigured workspace" — and AC2 has no misconfiguration
  exemption. Fixed on the owner's call: `_own_repository_config` now asks, BEFORE the chain,
  whether the requested project is the repository the module is executing inside, and if so that
  tree's own committed declaration wins. Verified to fire for this project ALONE —
  `chorestory`, `saystory`, `rawgentic`, `sysop` and an invented `payments-api` all still
  resolve through the chain untouched. The early answer still goes through `load_pack`, so a
  malformed own-declaration falls open to the seed rather than reaching the `<style>` sink
  unvalidated; and the seed is still the floor beneath it, tested against a checkout whose own
  config cannot be read.
- **That fix then had a hole of its own, and Step 11's cross-model pass found it.** With our own
  `vdl` block MALFORMED, resolution fell through to the workspace, which could point the name at
  another tree whose valid declaration won — AC2 re-opening on exactly the broken-config path.
  Every one of my own tests had passed `workspace_file=None`, so none exercised the fallback:
  the hole was in the test design as much as the code. Ownership and pack validity are now
  separate questions — once the executing repository is identified the workspace is not consulted
  for it at all, and `_seed_or_fallback` is factored out so `pack_for`'s two exits cannot drift.
  **One limit is recorded rather than glossed:** when our own config cannot be PARSED, ownership
  is genuinely undeterminable, so the workspace still answers there — and it now WARNS, which is
  what makes that acceptable. A test asserts the limit so it is a decision, not a gap.
- **A silent swallow, caught in my own inline review**, and worth recording because the reason
  was checkable and wrong: `_own_repository_config` swallowed parse errors on the grounds that
  warning would be noisy on the ordinary path, when the `exists()` check above already handles
  that path. A corrupt config was silently downgrading to the seed.
- **The colour is not a new choice.** `#4f7d15` / `#b7e87f` is `PALETTE[2]`, what the hash was
  already handing out, so this declares what three committed pages already wear. Measured
  rather than assumed: `css_layer` reads the pack only through `_colour` and `pack.get("tint")`
  (`render/vdl.py:39-50`, `:53-83`) and never emits `origin`, so fallback→seed moves **zero
  bytes** and both already-green planning pages stay byte-identical.
- **Nothing had ever guarded this class of drift.** Every byte-identity guard in the repository
  rendered with **no project pack** — `test_byte_identity.py:32` and
  `regen_rendered_styles.py:48` both omit `vdl` — so the accent layer was invisible to all of
  them, and `docs/examples/gallery/` and `docs/planning/` had no coverage at all.
  `test_docs_pages_current.py` + `regen_docs_pages.py` close that, following the
  `regen_rendered_styles.py` pattern: a committed manifest, packs resolved with
  `workspace_file=None`, completeness in both directions, a can-it-fail test, and sentinels
  the regenerator cannot rewrite.
- **Twelve stale gallery pages re-rendered.** Eleven were missing `a{color:var(--accent)}`;
  `roadmap` also missed the `.blk-ph-badge` wrap fix. Their stamps are unchanged — only the
  renderer moved, and bumping a stamp would falsely claim the document was updated.
- **The stamp is pinned in the manifest, and that has a cost stated rather than hidden.**
  `publish_doc.py` re-renders with the wall clock, has no `--generated-at`, and writes the file
  before its `--dry-run` check (`publish_doc.py:1289`), so publishing a covered page turns the
  guard red until the manifest stamp is bumped. Deferred as a High with that rationale; the fix
  changes a CLI surface and belongs in its own change.
- Two known gaps, named rather than left to be found: the 14 gallery `.png` screenshots go
  subtly stale once link colour changes (no test breaks — `test_example_gallery.py` asserts
  existence, not currency — and regenerating them needs a browser), and
  `docs/examples/example-roadmap.html` has no markdown source, so a pairs-based guard cannot
  cover it.

## #54 — Control calls through the edge carry the Access service-token pair

PR open 2026-08-25. Publishing worked from the harness host and nowhere else. Through the
public edge, Cloudflare Access answers a control call before the harness sees it, and a request
carrying only the publish bearer gets a 302 to the login — which `NO_REDIRECTS` rightly refuses.
`_control_request` now attaches `CF-Access-Client-Id` and `CF-Access-Client-Secret` when the
destination is the pinned TLS control host, the same pair stage 6 already sends for the page
fetch. A missing or half-present pair refuses locally, naming the variable, before a request
object exists. Loopback and bridge behaviour are unchanged.

Three review passes ran over it — inline, cross-model, and an adversarial refutation of eight
explicit claims — and between them they turned up more than the feature did.

```callout
warning | The readiness probe was leaking the publish bearer, two ways
`setup.probe_harness` validated NOTHING about its destination, so any host named in
`DOC_HARNESS_CONTROL_URL` received the publish bearer. It also followed redirects: measured
on CPython 3.12.3, a cross-host 302 delivered both `Authorization` and `CF-Access-Client-Id`
to the redirect target, and a Cloudflare Access login IS such a redirect. Both are fixed. The
allowlist is now imported from `publish_doc` rather than copied, because two copies of a
destination allowlist drift and the copy that drifts is the one that lets a credential out.
```

```phases
edge control calls | the Access pair rides stage 5, refused locally when incomplete | merged
probe hardening | destination allowlist + redirect refusal in setup.py, both found by review | merged
Access boundary | a dedicated `_ACCESS_CONTROL_HOSTS_TLS`, pinned equal to the bearer set by a test | merged
AC1 live proof | deferred to target: no credentials here, and the dedicated Access application is still pending in the gateway repo | blocked
```

The one acceptance criterion this PR cannot prove is the live round trip. Everything shipped is
publisher-side. The zone still has no dedicated docs-control Access application — the consult
records `service token isolated | pending` — so the server half stays unverified until the
gateway repo lands it. That is written into the PR body as a deferred verification with its
exact target check, never as a pass.

## #38 — Epic: replace the Vercel deploy target with the GitHub-doc harness

Filed 2026-08-23, backlog. Design docs stop being hosted on Vercel. Pages live only in
GitHub, and a Docker harness on the homelab serves the committed bytes at
`https://<name>.3dstories.ca` behind Cloudflare Access. The registry pins each publish to
an exact commit with a per-file manifest (Git blob id + SHA-256), so no request ever
follows a moving branch. The index becomes a server-rendered page at
`docs-index.3dstories.ca`, still derived, never hand-edited. Spec:
`docs/planning/2026-08-23-github-doc-harness-spec.md` — peer-consulted (qwen3.8-max,
gpt-5.6-sol), adversarially reviewed (deepseek-v4-pro: 10 findings, 8 fixed, 1 declined
with reason, 1 partial), owner-confirmed.

```phases
#34 harness service | registry, control API, serving path, derived index | merged
#35 go-live | cloudflared service merged; wildcard DNS and Cloudflare Access need an owner decision, so the issue stays open | blocked
#36 publish swap | publish_doc.py publishes and verifies through the control API; live verification deferred whole | merged
#37 migration | 181 projects today; the tool ships and the sample proves the harness cannot fetch private repositories | wip
```

## #37 — Backfill the Vercel doc projects, and the blocker the sample found

PR open 2026-08-24, fourth child of #38. One new script, `scripts/backfill_vercel.py`, standard
library only, five phases over an append-only run directory: `inventory`, `map`, `stage`,
`activate`, `report`. A page is identified by **hashing its live bytes against git history**, never
by parsing its project name — `{project}-{purpose}-{ref}` is ambiguous, so a name can parse to a
real but wrong project. The publish target is a separate field: the document's CURRENT committed
page. Comparing the historical match against Vercel would have been a tautology, and would have
migrated the stale version of every drifted document.

```phases
Design gate | 3 passes, 28 findings, all applied, closed budget-exhausted | done
Peer consult | blind cross-model proposal; found the compare-after-activate hole | done
Implementation | 8 tasks, 3 high-risk, red before green on every one | done
Per-task review | 2 passes, 17 findings, 4 Critical, 14 applied 3 carried | done
Code review | inline + cross-model, 5 findings, all High, all applied | done
Security scan | 0 blocking, 0 advisory, 0 skipped | done
The sample run | 181 rows inventoried, 10 processed, 0 live | done
```

```callout
crit | The sample found the epic's next blocker, and it is owner-gated
Zero rows went live, and that is the finding rather than a failure. Eight of the ten sampled pages
have live bytes that exist in NO commit anywhere in the workspace. The two that mapped cleanly both
failed `harness_fetch_denied`: their repositories are **private**, and the harness's GitHub
credential cannot read them. So until that grant widens, a real migration has nothing it can
activate — the same shape as #35's wildcard DNS and Access work, and the same owner decision.
```

Suite: **3043 passed, 8 skipped, exit 0** against a baseline of 2943 and 8 — plus 100 tests. The
Step 9 gate went RED first, and the failure was mine: this repository's own guard refused the
committed sample report because it enumerated 171 live Vercel project names, and this repo ships as
a plugin. The committed copy now uses stable handles.

## #36 — Publish through the harness, and the Vercel path retires

PR open 2026-08-24, third child of #38. `publish_doc.py` goes from seven Vercel stages to six
harness stages: render, name, lint, provenance, publish, verify. The inversion underneath is that
the harness **never receives rendered bytes** — it takes a manifest naming a repository, a 40-hex
commit and per-asset blob ids, then fetches every blob from GitHub itself. So the page must be
committed and pushed *before* it is published, and one consequence is a gift: stage 6's byte
equality now also proves the render matches the commit, which turns "rendered but forgot to commit"
into a caught failure. Version **2.0.0**, not 1.5.0 — `--new-project`, `--vercel-scope` and
`--limit` are gone, so an existing invocation now fails with argparse exit 2.

```phases
Design gate | 3 passes, 34 findings disposed, closed budget-exhausted by D22 | done
Implementation | red before green on every task with a red, 17 commits | done
Per-task review | 2 waves over the high-risk commits, 18 findings, 4 security | done
Code review | 12 findings, 11 applied, 1 carried, plus the adversarial diff layer | done
Security scan | 0 blocking, 0 advisory, 0 skipped — all five scanners ran | done
Live verification | no hostname resolves and the stack is not running | blocked
```

```callout
warn | Merging this removes the ability to publish, and that is deliberate
The Vercel deploy path goes away here, and the harness cannot serve yet: no `*.3dstories.ca`
hostname resolves, and the doc-harness stack is not running on 10.0.17.205 — measured, not
assumed. So this version renders and lints exactly as before and can publish nowhere until the
harness is live. Anyone who needs to publish today should stay on 1.4.0. Acceptance criterion 2 is
**deferred whole, both halves**, the PR says *Part of* #36 rather than closing it, and #36 stays
open. The likeliest-wrong claim in the deferred half is named in the PR: that the harness's
`X-Doc-Deployment` echo and derived content types survive Cloudflare unchanged.
```

Suite: **2943 passed, 8 skipped, exit 0** against a recorded baseline of 2823 and 8. The delta is
net — two whole Vercel test files were retired in the same change. This repository has no CI, so
that local run is the regression evidence.

## #34 — Harness service: registry, control API, serving path, derived index

PR open 2026-08-24, first child of #38. A new `harness/` package: thirteen stdlib-only modules
plus one entry point that is the only file importing a server, so the test gate never installs
waitress. Host maps to a registry row, the row pins an exact commit, and every blob is
SHA-256-verified against the manifest before it is cached or served. Publishing is one
compare-and-swap on a sealed row — the seal is enforced by database triggers, not remembered by
the application — and a stale publisher gets a 409 rather than a silent overwrite. The index
renders server-side from the registry, reusing the existing renderer rather than a second copy of
the presentation code.

The corrected migration figure lands here too: the epic section above said roughly 37 Vercel
projects, and walking `vercel project ls` to exhaustion returned 179, 163 of them carrying a
design-doc-publish purpose token. Between 4.4 and 4.8 times the stated number. #37 is scoped
against the real one.

```phases
Design gate | 3 passes, 25 findings disposed, closed budget-exhausted | done
Implementation | 14 tasks, 9 high-risk, red before green on every task with a red | done
Per-task review | 9 high-risk commits, one accumulated wave, all applied | done
Code review | 3 passes, 15 findings, 14 applied, 1 parked as scope | done
Security scan | 0 blocking, 0 skipped, 1 advisory declined with reason | done
Merge | awaiting review | pending
```

Two things a reader should not have to dig for. The service has **no CI to cite**: this
repository carries no `.github` directory, so the local full-suite run is the regression
evidence, measured at 2815 passed and 8 skipped against a Step-2 baseline of 2513 and 7. And one
slow-client concern is **deliberately deferred to #35**: waitress offers no absolute request
deadline, the container publishes no host port, and the remedy is edge termination, which is #35's
whole job.

## #28 — Row ages are frozen at build time

Filed and shipped 2026-08-14. Each index row's relative age (`3m`, `6h`) was baked into
the HTML at build time, so the page reported age-at-last-BUILD rather than age-now — a row
read `3m` for days until an unrelated publish rebuilt the index. Fix: `when()` also emits
the absolute instant as `data-updated` (epoch ms) plus `data-approx` for a deploy-inferred
time, and a new `_AGE_JS` constant — interpolated into the page's existing inline script —
re-renders every cell on load, on a 60s timer, and on `visibilitychange`, returning early
while the tab is hidden. The build-time string stays as the element's text, so a reader with
no JavaScript sees the page unchanged. No request is made, and `signature()` is untouched.

```phases
T1 markup carries the instant | data-updated + data-approx, on both emitters | done
  guard | the no-timestamp row gains neither attribute | done
T2 client renderer | _AGE_JS: on load, 60s timer, visibilitychange | done
  parity | node runs the shipped bytes against _ago() at every cutoff | done
T3 signature pin | the epoch attribute cannot move the change-detector | done
  teeth | three mutations, three kills, all reverted | done
T4 this log | #28 moved from backlog to shipped | done
```

```callout
warn | Residuals, recorded not hidden
One review finding declined with its reason: the renderer collects its cells once at load,
so a row added to the DOM later would not tick — the page never mutates its row set without
a reload, and the signature poll is what reloads it. One verification step was not measured
directly: a browser with JavaScript switched off. The noscript fallback rests on the served
bytes (fetched and inspected) plus a test pinning the build-time string as the cell's text.
```

## #23 — Page URL constructed from the project name 404s past 35 chars

Vercel truncates a `.vercel.app` label at 35 characters; `publish_doc.py` and
`build_index.py` constructed URLs from project names, so stage 6 refused perfect deploys
of long-named projects and the index carried dead links (5 of 20 live projects,
measured). Fix: read, never construct — the stage-2 cap refuses un-round-trippable
names toward a shorter `--ref`; `aliased_host` takes the domain from the deploy's own
Aliased line (line-start anchored, bound to the deterministic truncation); the index
emits the validated `latestProductionUrl`, bound to each row's own project.

```phases
T1 stage-2 alias cap | refuse at naming, not after deploy | done
  guard | MAX_ALIAS_LABEL=35, measured boundary cited | done
T2 read the deploy grant | aliased_host, stages 6 and 7 | done
  anchor | only a line STARTING with Aliased is a grant | done
  cut | truncated label must equal name[:35] minus trailing hyphens | done
T3 index reads the listing | latestProductionUrl, fail-closed + project-bound | done
T4 docs sweep | no constructed-URL promise existed — verified, zero changes | done
```

```callout
warn | Residuals, recorded not hidden
The 35-char cap is a measured constant, not a platform contract (adversarial finding):
drift surfaces as honest refusals, never silent wrongness. The exact-label branch stays
tolerant of a future cap change by design — the paired High finding asking to harden it
was declined for exactly that reason.
```

## 2026-08-24 — the Vercel era ends (5.0.0)

Owner instruction: rip every Vercel mention out of the plugin. What changed, in one entry:

- **The #37 backfill tool is deleted** (`scripts/backfill_vercel.py`, its 105 tests, both
  fixtures). Convention resolution (4.0.0) made the migration unnecessary; git history and the
  dated #37 documents keep the record.
- **`setup.py` checks the harness, not a vendor CLI**: workspace file, `DOC_HARNESS_CONTROL_URL`,
  `DOC_HARNESS_PUBLISH_TOKEN`, the edge pair — and a READ-ONLY probe of the control API's
  read-back route, proven over a real socket in `test_first_run.py`.
- **`user_config` lost the account scope**; it owns the workspace pointer alone. A vendor-free
  `validate_name` guards `--add-project`.
- **`publish_doc` control calls carry `Host: docs-control.<zone>` over plaintext**, fixing the
  measured #36 defect where a loopback publish was impossible and the live proof needed a
  hand-written client.
- **`build_index` is a pure renderer**: the standalone CLI that walked the vendor's project
  list is gone; the harness walk is its only data source.
- **`deploy_check` looks for a zone link**, not a vendor hostname.
- Dated planning, review, runbook and measurement documents are HISTORY and keep their words;
  this log gets entries appended, never rewritten.
