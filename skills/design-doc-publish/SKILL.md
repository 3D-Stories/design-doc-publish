---
name: design-doc-publish
description: Use whenever a design document, architecture document, plan review, program dashboard, or heavy review report is produced or updated in any project in this workspace — the standing mandate is that every such doc ships as BOTH committed markdown+HTML in the repo AND a page published to the doc harness. Also use when the user says "publish the design doc", "make the dashboard", "deploy the doc", or "artifact this". Use it for UPDATES too, not only first publication — "update the plan", "update the roadmap", "refresh the dashboard", "the doc is out of date", "mark that issue done in the plan" — updating one of these pages is a multi-site sweep with its own discipline and its own gates.
---

# Design Doc Publish

A design doc is done when its `.md` and `.html` are committed **and** the page is live; the exit code is the verdict. **Order matters: render with `--dry-run`, commit both files, push, then publish** — the harness serves the bytes in the commit and never receives the file.

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/publish_doc.py" \
  --md docs/planning/<doc>.md --title "#<issue> <title>" \
  --project <rawgentic-project> --type design --ref <issue>
```

Absolute path — a skill runs from whatever project is bound. `DOC_HARNESS_CONTROL_URL` (**required, no default**; unset exits **25**) and `DOC_HARNESS_PUBLISH_TOKEN` carry the publish; a plaintext bridge endpoint additionally needs `DOC_HARNESS_ALLOW_BRIDGE_PLAINTEXT=<host:port>` naming it exactly, and a control URL of `https://docs-control.<zone>` — which is how any machine that is not the harness host publishes at all — additionally REQUIRES both `CF_ACCESS_CLIENT_ID` and `CF_ACCESS_CLIENT_SECRET` — omitting both refuses at stage 5 just as setting one does. Optional `DOC_HARNESS_PUBLIC_BASE`: unset skips edge verification and exits **26**, which is **not a pass** — it published and origin-verified, nothing past Cloudflare. 11-17 stay stage failures.
`--ref` is the issue number or a short slug; `--project` is a rawgentic project, or `workspace`. `--style` overrides the template a `--type` implies. Two styles have no `--type` at all and are reachable only this way: `--style dashboard` for the dashboard template, and `--style plain` for an unstyled document with no template CSS. `plain` is also the one style where a code fence stays a bare listing: everywhere else it renders as a box with a **Copy** button, labelled by the fence's info string — so name the language on any fence a reader is meant to run.

## The one real decision: `--type`

| `--type` | Template | Use it for |
|---|---|---|
| `design` | `design` | how something will be built, and why |
| `plan` | `roadmap` | sequenced work with milestones |
| `spec` | `spec` | normative requirements (MUST / SHOULD) |
| `analysis` | `analysis` | measurement, comparison, a question answered |
| `report` | `report` | the outcome of a run or a review |
| `audit` | `review` | findings against an existing thing |
| `runbook` | `workflow` | a procedure someone follows under pressure |
| `uat` | `uat` | an interactive acceptance checklist |
| `tokens` | `design-system` | a project's own colours, type and radii, shown |
| `map` | `module-map` | what the parts are and what depends on what |
| `deck` | `slide-deck` | something you present, one point per screen |
| `minutes` | `minutes` | what a meeting agreed and decided, and who owes what |

Every style above is built from **components you have to write** — a composition meter, a phase
rail, a timeline, finding cards. Write none, or none of the ones that style **opens with**, and the
gate refuses it. `--skip-component-checks` (alias `--allow-prose`) skips those two checks, not the
template-classification one; a re-publish needs `--telemetry <f.json>` or telemetry drops. A sectioned
style SCANS heading prose for its chip — narrative pages get statuses nobody wrote: `--no-section-chips`. Per style, in full: `${CLAUDE_PLUGIN_ROOT}/docs/design-language.md`.

## The state cell of a chip is a CLOSED set, not free text

| Write | Colour |
|---|---|
| `done` `shipped` `merged` `ok` | green — finished |
| `active` `wip` `pending` `warn` | amber — moving |
| `blocked` `failed` `crit` | red — stuck |
| `planned` `note` | grey — not started, a choice and not a gap |
| `<label>:<level>` — `bug:must` `feature:should` `chore:could` `task:done` | the LABEL is the chip's word, the LEVEL picks its colour |

An unknown word warns and renders grey. Labels: `bug` `feature` `chore` `hardening` `epic`
`action` `note` `task`. Levels: `must` `should` `could` `done`. Prefer the status word to the
severity word in a new document. Full rules: the design-language.md named above.

## Images: write them relative to the markdown, and they must exist

| you write | what happens |
|---|---|
| `![x](assets/diagram.png)` | the publisher copies that file into the deploy directory, so it resolves on the live URL |
| `![x](d.png)`, `![x](sub/d.png?v=2)`, `![x](my%20d.png)` | same — a query string and percent-encoding are handled |
| `![x](missing.png)` | **publish fails at stage 5, nothing deploys** — it would 404 |
| `![x](../out.png)`, or a symlink leaving the directory | refused: these pages are public and the neighbour directory is somebody's repo |
| `![x](/rooted.png)` | refused — the deploy root is not the document's directory, so either guess ships a broken page |
| `![x](https://host/i.png)` | refused at RENDER time, left as literal text; a page fetches nothing from another host. An `<a href>` off-host is fine — a citation is not a request |
| `![x](data:image/png;base64,…)` | refused; nothing is inlined |

## What the script cannot decide

- **Is it any good?** Owner, verbatim (2026-07-31): *"build me a visually stunning HTML page using
  proper VDL, contrasting colors and elements that draw my eye to where they need to be drawn."*
  Contrast is checked arithmetically; a real type scale, consistent heading and table treatment, and
  a clear first-read element are not — and untouched template defaults are not a VDL. Load
  `frontend-design` + `frontend-design-extras`; for charts or KPI rows, `dataviz` + `dataviz-extras`.
- **Does it render?** Byte identity is not rendering. Open the LIVE page in a browser and drive
  anything interactive. Never judge it by reading the source.
- **Is it safe in public?** World-readable: secrets by NAME only; strip internal IPs, hostnames and
  hardware identifiers such as drive serials.
- **Where does it belong, and did the update actually land everywhere?** Some projects keep ONE rolling doc — check for `sharedDoc` first. Updating one is a sweep, not an edit: the same fact sits in a `stats` count, a `phases` row, a `meter` and the prose, and publishing refuses when a phase reads done over children that read open, or when this revision marks something done that another line still calls open (`--ack-stale` to override). It also refuses eight markdown constructs this renderer passes through literally, `~~strikethrough~~` among them. The sweep it cannot do for you, and the eight constructs: `${CLAUDE_PLUGIN_ROOT}/docs/updating-a-living-document.md`.
- **Committing and reporting.** Never push to main; no blanket `git add`. Stage the `.md` + `.html`
  pair by name under a conventional commit — it rides in the implementing PR when one exists, else a
  standalone `docs:` PR. Check both files are in the diff and it references the issue, then comment
  the URL there and report labelled links (`.md`, `.html` + PR, live URL) with what you verified.
