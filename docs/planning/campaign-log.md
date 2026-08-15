# design-doc-publish — campaign log

Rolling program log: one section per issue, newest first. Created 2026-08-13 with issue
#23 (the shared-doc design-artifact convention; style roadmap).

```stats
2 | issues on this log
28 | newest: shipped, PR open
2492/2499 | suite at last PR
```

```callout
info | Read this first — what this log is
One section per issue, refreshed inside that issue's own PR (a filed-but-unstarted
issue gets a backlog section at WF1 time). The stats above always describe the NEWEST
state; older sections keep their text as historical record.
```

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
