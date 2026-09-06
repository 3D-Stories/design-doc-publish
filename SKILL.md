---
name: design-doc-publish
description: Create or update design documents, architecture docs, plans, dashboards, reviews, and meeting minutes as Markdown plus styled HTML using the design-doc-publish renderer. Publish and verify them on the doc harness when requested, and diagnose publishing setup. Use for requests such as "publish the design doc", "artifact this", "render this plan", or "refresh the dashboard".
---

# Design Doc Publish for Codex

Use the bundled renderer and its design language. Keep the Markdown source and generated HTML together. Follow the current project's document location, `sharedDoc`, and publication conventions. A request to render locally or perform a read-only review does not authorize committing, pushing, publishing, or commenting elsewhere. For an authorized publication, prepare and validate the document before any approval that is still required; retain authorization already given in the session.

## Locate the package

This **installed bundle's root is the Codex skill directory**. Set `DDP_ROOT` to the absolute directory containing this loaded `SKILL.md`, as shown by Codex's skill listing. Resolve scripts and references from there, while running commands from the user's target project. Do not use the target project's `scripts/` or Claude's plugin-root variable. Install with the repository's `scripts/install_codex_skill.py`, which excludes nested Claude entrypoints from Codex discovery.

For the default installation:

```bash
DDP_ROOT="${CODEX_HOME:-$HOME/.codex}/skills/design-doc-publish"
```

Use the actual listed path instead if this skill was installed elsewhere. Set `DDP_ROOT` in each shell invocation that uses it; shell variables do not persist between tool calls. The complete package must include `scripts/`, `index/`, `harness/`, and `docs/`; copying only this entrypoint or the nested Claude skill leaves the runtime incomplete.

## Write and render

Read [docs/design-language.md](docs/design-language.md), especially **Doc types**, **Components**, and the selected template's requirements. Use [docs/examples/gallery/](docs/examples/gallery/) for examples of that style's source. The page needs a clear visual hierarchy, a deliberate project palette, readable contrast, and the template's required components. Use an available design skill if helpful; no Claude-only companion skill is required. Never hand-roll replacement HTML.

For an update, read [docs/updating-a-living-document.md](docs/updating-a-living-document.md) first. Sweep every occurrence of a changed fact: stats, phases, meters, tables, and prose. Preserve telemetry by passing the existing `--telemetry <file.json>` again. Do not mark a phase done over unfinished children or erase historically relevant qualifications.

Rendering alone needs Python 3.12+, no credentials, and no configuration:

```bash
python3 "$DDP_ROOT/scripts/render-doc" \
  --md docs/planning/<doc>.md --out docs/planning/<doc>.html \
  --title "<document title>" --style design
```

Pass `--project <name>` for the project's declared or seeded palette. Direct rendering does **not** prove the publication lint gate passed. With a workspace configuration, validate the full document before publishing:

```bash
python3 "$DDP_ROOT/scripts/publish_doc.py" \
  --md docs/planning/<doc>.md --title "<document title>" \
  --project <project-name> --type design --ref <issue-or-slug> --dry-run
```

`--dry-run` renders, names, lints, and validates local assets, then stops before Git or network operations. It writes HTML; it is not a read-only check. If setup is missing, use the renderer for a local-only deliverable and report that publication validation remains untested.

| `--type` | Default `--style` | Use |
| --- | --- | --- |
| `design` | `design` | Architecture and tradeoffs |
| `plan` | `roadmap` | Sequenced work and milestones |
| `spec` | `spec` | Normative requirements |
| `analysis` | `analysis` | Measurements and comparisons |
| `report` | `report` | Results of a run or review |
| `audit` | `review` | Findings against an existing artifact |
| `runbook` | `workflow` | Operational procedure |
| `uat` | `uat` | Acceptance checklist |
| `tokens` | `design-system` | Project design tokens |
| `map` | `module-map` | Parts and dependencies |
| `deck` | `slide-deck` | Presentation |
| `minutes` | `minutes` | Meeting decisions and actions |

`dashboard` and `plain` are **styles only**, selected with `--style`. Direct `render-doc` accepts a style, not `--type`. The publisher always requires a type, even with a style override.

Write the components the selected style requires. `--skip-component-checks` (alias `--allow-prose`) skips both component checks, but not template classification. Use overrides only when the intended document justifies them and disclose the skipped checks. Likewise, do not use `--ack-stale` or `--allow-unsupported-markdown` merely to make a refusal disappear. Narrative sectioned pages may need `--no-section-chips` to prevent status words in prose from creating unintended chips.

Chip states are a closed vocabulary: `done/shipped/merged/ok` (green), `active/wip/pending/warn` (amber), `blocked/failed/crit` (red), and `planned/note` (grey). Compound chips use `<label>:<level>`: labels `bug`, `feature`, `chore`, `hardening`, `epic`, `action`, `note`, `task`; levels `must`, `should`, `could`, `done`. Unknown states warn and render grey.

Images must exist beside or below the Markdown and use relative paths. Missing files, parent traversal, escaping symlinks, rooted paths, external images, and data URLs are refused. Relative assets are copied into the deployment; the document fetches nothing from another host. External citation links are allowed.

## Publishing setup

Reuse the owner's existing workspace and environment. Check configuration before changing it. If the owner has configured a trusted shell environment file at the path below, load it in the **same shell invocation** as the publisher or setup checker; exports do not persist between Codex tool calls:

```bash
DDP_ENV="${XDG_CONFIG_HOME:-$HOME/.config}/design-doc-publish/publish-env.sh"
if [ -f "$DDP_ENV" ]; then . "$DDP_ENV"; fi
python3 "$DDP_ROOT/scripts/setup.py" --check
```

The optional file is user configuration, never bundled in this repository. It can export endpoint settings and read credentials from an existing secret store at execution time. Do not print credential values, use shell tracing, put secrets into command arguments or Git, or copy them into the skill. Respect explicitly supplied environment settings.

`setup.py --check` performs a bounded **read-only** harness probe: exit 0 is ready; 2 means missing environment or incomplete Access credentials; 3 means denied; 4 means workspace/config trouble; 5 means unreachable. `--json` **always exits 0**: inspect `status` and `can_proceed`. A successful setup probe is readiness, not proof that a page was published or rendered correctly.

For a requested first-time setup, `setup.py --init-workspace` creates user configuration and `setup.py --add-project <name>` adds a project to the owned workspace. `--set-workspace <path>` adopts an existing workspace without claiming ownership. Explain those writes before running them; never overwrite an existing workspace to clear a refusal. Configuration defaults to `~/.config/design-doc-publish/` (or `XDG_CONFIG_HOME`); the publisher also accepts `--config` and `--workspace-file`.

Publishing requires `DOC_HARNESS_CONTROL_URL` (no default) and `DOC_HARNESS_PUBLISH_TOKEN`. A public `https://docs-control.<zone>` endpoint also requires **both** `CF_ACCESS_CLIENT_ID` and `CF_ACCESS_CLIENT_SECRET`. `DOC_HARNESS_PUBLIC_BASE` enables public-edge verification and also requires that pair. A deliberately configured plaintext bridge additionally requires `DOC_HARNESS_ALLOW_BRIDGE_PLAINTEXT=<exact-host:port>`; never add that exception to bypass an endpoint refusal.

## Publish and verify

For an explicitly requested or already authorized pinned publication:

1. Render and pass `publish_doc.py --dry-run`; inspect the generated page in an available real browser and exercise its controls. For a publication, remove secret values and private infrastructure identifiers from public content.
2. Stage the Markdown, HTML, and needed assets **by name**, commit on a feature branch, and push through the project's authorized PR process. Never push directly to main. The harness fetches committed GitHub bytes, not local files.
3. Run the same publisher arguments **without `--dry-run`**, in a shell with the publishing environment loaded. Read the actual exit code and stage output. Stop on failure; diagnose it before retrying.
4. Open the resulting **live** URL in a browser and exercise its controls. Byte identity does not prove visual rendering. If browser access is unavailable, say so; do not claim a visual check.

Some workspaces serve committed `docs/` HTML by convention without an explicit publish call. Follow that project's documented flow when selected, and distinguish a predicted URL from an observed live page. Do not add a pinned publication merely because an HTML file was committed.

Publisher exit **0** means origin and edge verification passed. **25** means the required control URL is absent. **26** means published and origin-verified with edge verification **skipped**; it is not a complete pass and must not trigger a blind re-publish. Codes **11–17** are stage failures. Even after a nonzero exit, inspect the reported stage: a later verification failure can follow a successful publish.

Report labelled links to the source, HTML/PR, and observed live page as applicable, plus what was actually verified and what remains. Post an issue comment or message only when the user authorized that communication. Do not label rendered, committed, reachable, origin-verified, edge-verified, and visually checked as interchangeable outcomes.
