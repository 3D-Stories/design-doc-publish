# design-doc-publish — campaign log

Rolling program log: one section per issue, newest first. Created 2026-08-13 with issue
#23 (the shared-doc design-artifact convention; style roadmap).

```stats
3 | issues on this log
38 | newest: epic in flight, #34 PR open
2815/2823 | suite at last PR
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
#34 harness service | registry, control API, serving path, derived index | PR open
#35 go-live | cloudflared tunnel, wildcard DNS, Cloudflare Access | pending
#36 publish swap | publish_doc.py deploy/verify to the control API | pending
#37 migration | backfill 179 Vercel projects, 163 with a purpose token, byte-compare per row | pending
```

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
