# Vercel-to-harness backfill — outcome report

Inventory converged: two agreeing walks, started 1787598540, completed 1787598548.

| Count | What |
| --- | --- |
| 181 | rows in the snapshot |
| 10 | rows PROCESSED by this run |
| 171 | rows `not_attempted` (sampled out) |
| 0 | rows now **live** on the harness |

## Flagged, by reason

| Reason | Rows |
| --- | --- |
| `harness_fetch_denied` | 2 |
| `mapping_not_found` | 8 |

## Every processed row

| Project | Outcome | Reason |
| --- | --- | --- |
| `3dstories-bench-design-judge-v3` | flagged | `mapping_not_found` |
| `3dstories-bench-report-camera-prompts` | flagged | `mapping_not_found` |
| `3dstories-bench-report-phases` | flagged | `mapping_not_found` |
| `3dstories-fleet-design-26` | flagged | `harness_fetch_denied` |
| `3dstories-fleet-plan-runner-pool` | flagged | `mapping_not_found` |
| `3dstories-studio-scene-storm-sea` | flagged | `mapping_not_found` |
| `airport-emergency-directory` | flagged | `mapping_not_found` |
| `claude-skills-46-replan` | flagged | `mapping_not_found` |
| `claude-skills-72-spike` | flagged | `mapping_not_found` |
| `claude-skills-design-12` | flagged | `harness_fetch_denied` |

## Not attempted

These rows were in the snapshot and this run did not touch them. They have NO outcome — not a flag — because no reason in the vocabulary would describe them truthfully. The selection rule was `--limit` over the snapshot in its recorded order.

`claude-skills-design-130`, `claude-skills-design-mockups`, `claude-skills-design-templates`, `claude-skills-plan-36`, `claude-skills-plan-786`, `design-doc-publish-design-hosting`, `design-doc-publish-design-hosting-options`, `design-doc-publish-plan-campaign`, `docs-index`, `herdr-dashboard-design-107`, `herdr-dashboard-issue-audit`, `herdr-dashboard-plan`, `herdr-dashboard-uat-113`, `herdr-dashboard-uat-epic-a`, `herdr-dashboard-uat-queue-uat`, `lumenquire-design-90`, `lumenquire-design-91`, `lumenquire-plan-batch`, `lumenquire-plan-issue-tree`, `lumenquire-uat-gap`, `lumenquire-uat-phase1`, `oneshot-bench-analysis-curation`, `oneshot-bench-analysis-prompt-corpus`, `oneshot-bench-design-44`, `oneshot-bench-design-55`, `oneshot-bench-design-57`, `oneshot-bench-design-checks`, `oneshot-bench-design-dev-deploy`, `oneshot-bench-design-runner-ui`, `oneshot-bench-runbook-workflows`, `rawgentic-735-design`, `rawgentic-765-bakeoff-map`, `rawgentic-765-decision`, `rawgentic-840-design`, `rawgentic-analysis-1081`, `rawgentic-analysis-1176`, `rawgentic-analysis-713`, `rawgentic-analysis-756-spikes`, `rawgentic-analysis-762`, `rawgentic-analysis-autoretry-fit`, `rawgentic-analysis-backlog-post-m1`, `rawgentic-analysis-claude-tag`, `rawgentic-analysis-epic-path`, `rawgentic-analysis-executor-tokens`, `rawgentic-analysis-gh-claude`, `rawgentic-analysis-handoff-fit`, `rawgentic-analysis-owner-notes`, `rawgentic-analysis-traycer-decision`, `rawgentic-audit-bloat-review`, `rawgentic-audit-doctor-plus`, `rawgentic-audit-feature-state`, `rawgentic-audit-roadmap-accuracy`, `rawgentic-audit-roadmap-coverage`, `rawgentic-audit-scope-inject`, `rawgentic-design-1080`, `rawgentic-design-1086`, `rawgentic-design-1089`, `rawgentic-design-1186`, `rawgentic-design-1209`, `rawgentic-design-1210`, `rawgentic-design-1213`, `rawgentic-design-1293`, `rawgentic-design-1294`, `rawgentic-design-1330`, `rawgentic-design-1330-part2`, `rawgentic-design-1331`, `rawgentic-design-1337`, `rawgentic-design-1401`, `rawgentic-design-1402`, `rawgentic-design-1411`, `rawgentic-design-1417`, `rawgentic-design-1475`, `rawgentic-design-1477`, `rawgentic-design-1555`, `rawgentic-design-391`, `rawgentic-design-594`, `rawgentic-design-726`, `rawgentic-design-769`, `rawgentic-design-855`, `rawgentic-design-909`, `rawgentic-design-923`, `rawgentic-design-932`, `rawgentic-design-943`, `rawgentic-design-944`, `rawgentic-design-963`, `rawgentic-design-publish-pipeline`, `rawgentic-epic-635-uat`, `rawgentic-epic-635-uat-console`, `rawgentic-memorypalace-analysis-74`, `rawgentic-memorypalace-analysis-77`, `rawgentic-memorypalace-analysis-ev`, `rawgentic-memorypalace-analysis-sib`, `rawgentic-next-analysis-107`, `rawgentic-next-analysis-115`, `rawgentic-next-design-160`, `rawgentic-next-plan-95`, `rawgentic-next-plan-backlog-audit`, `rawgentic-next-report-99`, `rawgentic-next-runbook-109`, `rawgentic-next-runbook-95-laptop`, `rawgentic-next-spec-106`, `rawgentic-next-spec-108`, `rawgentic-plan-1058`, `rawgentic-plan-1402-impl-plan`, `rawgentic-plan-1405-what-moves`, `rawgentic-plan-1417`, `rawgentic-plan-1463-merge-slot`, `rawgentic-plan-756`, `rawgentic-plan-871`, `rawgentic-plan-backlog-audit`, `rawgentic-plan-campaign-log`, `rawgentic-plan-flow-friction`, `rawgentic-plan-g3-readiness`, `rawgentic-plan-graph`, `rawgentic-plan-integration-roadmap`, `rawgentic-plan-integration-tests`, `rawgentic-plan-pr-queue`, `rawgentic-plan-roadmap-v2`, `rawgentic-plan-techdebt-sprint`, `rawgentic-plan-unified-plan`, `rawgentic-plan-unified-roadmap`, `rawgentic-report-1139`, `rawgentic-report-diagram-refresh`, `rawgentic-test-suite-review`, `rawgentic-uat-667`, `rawgentic-workflow-diagram`, `restore-uat`, `saystory-avx512-floor`, `saystory-design-169-pr-b`, `saystory-design-347`, `saystory-design-design-log`, `saystory-epic-251-uat`, `saystory-epic-state-map`, `saystory-hardware-milestones`, `saystory-plan-252`, `saystory-plan-backlog-audit`, `saystory-staleness-audit`, `saystory-uat-118`, `saystory-uat-374`, `saystory-uat-checklist`, `saystory-uat-hardware`, `stars-coc-mvp-design-arewethereyet-integration`, `sysop-69-gh-cli`, `sysop-analysis-qwen38-measured`, `sysop-design-network-topology`, `sysop-design-qwen38-fleet-mac`, `sysop-plan-r740xd-expansion`, `sysop-report-asus-g18`, `thewanderinginn-analysis-102`, `thewanderinginn-analysis-103`, `thewanderinginn-analysis-109`, `thewanderinginn-analysis-170`, `thewanderinginn-analysis-81`, `thewanderinginn-analysis-81-calib`, `thewanderinginn-analysis-tts`, `thewanderinginn-design-109`, `thewanderinginn-design-11`, `thewanderinginn-design-143`, `thewanderinginn-design-25`, `thewanderinginn-design-41`, `thewanderinginn-design-45`, `thewanderinginn-plan-backlog-reeval`, `thewanderinginn-plan-rest-of-series`, `thewanderinginn-plan-tts-build`, `thewanderinginn-spec-166`, `workspace-analysis-airport-directory`, `workspace-analysis-powerbi-plugin`, `workspace-audit-forensics-0730`, `workspace-audit-harness-0727`, `workspace-runbook-qwen-cli`, `workspace-uat-uat-test`

