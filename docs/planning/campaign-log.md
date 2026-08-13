# design-doc-publish — campaign log

Rolling program log: one section per WF2/WF3 issue, newest first. Created 2026-08-13
with issue #23 (the shared-doc design-artifact convention; style roadmap).

```stats
23 | first issue on this log
5 | commits on its branch
2471/2478 | suite at PR time
```

```callout
info | Read this first — what this log is
One section per implemented issue, refreshed inside that issue's own PR. The stats and
phases below always describe the NEWEST section; older sections keep their text as
historical record.
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
