# design-doc-publish — campaign log

Rolling program log: one section per issue, newest first. Created 2026-08-13 with issue
#23 (the shared-doc design-artifact convention; style roadmap).

```stats
5 | issues on this log
37 | newest: PR open, the Vercel backfill
2943/3043 | suite, baseline to this PR
```

```callout
info | Read this first — what this log is
One section per issue, refreshed inside that issue's own PR (a filed-but-unstarted
issue gets a backlog section at WF1 time). The stats above always describe the NEWEST
state; older sections keep their text as historical record.
```

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
