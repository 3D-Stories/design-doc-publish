<h1 align="center">design-doc-publish</h1>

<p align="center">
  <strong>Your design docs deserve better than a markdown preview.</strong>
</p>

<p align="center">
A Claude Code plugin that turns a markdown design document into a single self-contained HTML page
that looks like it was <em>designed</em>, not dumped. One file out. No build step, no CSS framework,
no JavaScript bundle, and nothing fetched at runtime.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/licence-MIT-blue?style=flat" alt="MIT licence">
  <img src="https://img.shields.io/badge/tests-2431_passed-2da44e?style=flat" alt="2431 tests passing">
  <img src="https://img.shields.io/badge/python-3.12-blue?style=flat" alt="Python 3.12">
  <img src="https://img.shields.io/badge/dependencies-stdlib_only-2da44e?style=flat" alt="Standard library only">
  <img src="https://img.shields.io/badge/document_types-11-blue?style=flat" alt="11 document types">
</p>

<p align="center">
  <a href="#what-the-output-looks-like">Output</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#publishing-one-setup-run-first">Publishing</a> ·
  <a href="#choosing-a---type">Document types</a> ·
  <a href="#what-you-can-rely-on-about-the-pages">Guarantees</a> ·
  <a href="#prerequisites">Prerequisites</a> ·
  <a href="#removing-it">Uninstall</a>
</p>

---

## What the output looks like

![A rendered page on a dark background: an eyebrow line reading DESIGN ARTIFACT with a timestamp, a
large title, then sectioned cards with a green left edge. One card header carries a small green DONE
chip, and the cards hold tables of phases and
risks](docs/examples/example-roadmap.png)

Both halves of that are committed, so neither can rot into a promise:
[`docs/examples/example-source.md`](docs/examples/example-source.md) is the ordinary markdown that
went in — no styling, no HTML — and
[`docs/examples/example-roadmap.html`](docs/examples/example-roadmap.html) is the page that came out.
Open the HTML in a browser and it is exactly what you see above.

## Features

- **One self-contained file** — styles and assets inlined. It works from a local disk, an email
  attachment, or a static host with nothing beside it.
- **Zero runtime fetches** — no web fonts, no CDN scripts, no analytics, no remote images.
- **No JavaScript at all** — not one `<script>` block, inline handler, or `javascript:` URL. A
  script-forbidding Content-Security-Policy costs the page nothing.
- **11 document types** — design, plan, UAT, audit, report, runbook, analysis, spec, tokens, map,
  deck. Each picks a template; `--style` overrides it.
- **Standard library only** — no third-party Python packages, on purpose.
- **Rendering needs no setup** — no account, no config, no network. Setup is only for publishing.
- **Publishes to Vercel in one command** — render, lint, deploy and verify, with the exit code as
  the verdict.

## Quick start

### 1. Add the marketplace

Inside Claude Code:

```
/plugin marketplace add 3D-Stories/design-doc-publish
```

### 2. Install the plugin

```
/plugin install design-doc-publish
```

Then start a **new** session. A session already running holds the paths it resolved at startup, so
it will not see a plugin installed after it began.

<details>
<summary><strong>Prefer the terminal?</strong></summary>

Both steps work outside a session with the Claude Code CLI:

```bash
claude plugin marketplace add 3D-Stories/design-doc-publish
claude plugin install design-doc-publish@design-doc-publish
```

Start a new session afterwards either way.

</details>

### 3. Render your first page

This works with nothing configured — no account, no workspace file, no network.

```bash
DDP=$(ls -d ~/.claude/plugins/cache/design-doc-publish/design-doc-publish/*/ | sort -V | tail -1)
printf '# Hello\n\nA first page.\n\n## A section\n\nSome prose.\n' > hello.md
python3 "$DDP/scripts/render-doc" --md hello.md --out hello.html --title "Hello"
```

Open `hello.html`. That is the whole loop.

<details>
<summary><strong>Why the first line, instead of naming a version?</strong></summary>

It finds whichever version you installed. A literal version would break on the next release, and
worse, could silently pick up a stale copy that uninstalling left behind.

`${CLAUDE_PLUGIN_ROOT}` is no help here: Claude expands it when it loads a skill, but your shell
does not, so it is useless in a command you paste.

</details>

<details>
<summary><strong>Cloned the repo instead?</strong></summary>

Run it from the checkout:

```bash
printf '# Hello\n\nA first page.\n\n## A section\n\nSome prose.\n' > hello.md
python3 scripts/render-doc --md hello.md --out hello.html --title "Hello"
```

</details>

## Publishing: one setup run first

Rendering needs nothing. **Publishing needs a Vercel account, and one setup run to record which
team to deploy to.** Nothing about your machine is assumed.

Inside Claude Code, run:

```
/design-doc-publish:setup
```

It reports what is missing rather than failing at it: whether the `vercel` CLI is installed, whether
you are signed in, which team you publish to, and where your configuration lives. **It installs
nothing and signs you into nothing** — where something must be installed, it shows you the command
and waits for you to decide.

<details>
<summary><strong>Running setup from a shell instead</strong></summary>

```bash
python3 "$DDP/scripts/setup.py"                              # the full report; only reads
python3 "$DDP/scripts/setup.py" --set-scope <your-team>      # checks you can use it first
python3 "$DDP/scripts/setup.py" --init-workspace             # creates a project list
python3 "$DDP/scripts/setup.py" --add-project my-project     # a name you can publish under
```

`vercel teams ls` lists the teams you belong to. If you are not signed in, setup prints the
`vercel login` command for you to run — it never runs it for you, because that is interactive and
changes your machine's sign-in for everything.

</details>

### Exactly what setup writes

**Two files, both under your home directory, and nothing else on your machine is touched.**

| Path | Holds |
| --- | --- |
| `~/.config/design-doc-publish/config.json` | which Vercel team to use, and which workspace file |
| `~/.config/design-doc-publish/workspace.json` | the project names you may publish under |

They live **outside** the plugin, so upgrading it does not lose them. **Neither ever holds a
credential** — signing in stays entirely with the `vercel` CLI. `--check`, `--json` and the bare
report only read.

**To undo everything, delete those two files.** That returns the machine to never-configured.

### Then publish

```bash
python3 "$DDP/scripts/publish_doc.py" --md docs/planning/my-doc.md \
  --title "My design doc" --project my-project --type design --ref 42
```

Render, lint, deploy and verify, in one command. `--dry-run` lints without publishing. The exit
code is the verdict.

## Prerequisites

| What | Why | Verified |
| --- | --- | --- |
| Python 3.12 | the renderer and its tests | 3.12.3, which produced the test count below. `setup.py` checks this first and says so plainly if yours is older |
| No third-party Python packages | the renderer is stdlib only, on purpose | — |
| A POSIX system | `setup.py` serializes its writes with `fcntl`, which Windows does not have. Rendering itself is platform-neutral | setup refuses with a sentence rather than a traceback where locking is unavailable |
| `vercel` CLI | only for deploying, not for rendering | needed from stage 4 |
| A Vercel account | only for deploying | `setup.py` checks you can reach your team before recording it |

## Choosing a `--type`

`--type` states the document's PURPOSE. Each purpose picks a template, and `--style` overrides that
if you want a different look for the same purpose.

| `--type` | template | choose it when |
| --- | --- | --- |
| `design` | `design` | proposing how something should be built |
| `plan` | `roadmap` | sequencing work that has phases or tasks |
| `uat` | `uat` | someone has to walk through and tick things off |
| `audit` | `review` | judging work that already exists |
| `report` | `report` | telling people what happened |
| `runbook` | `workflow` | somebody follows the steps under pressure |
| `analysis` | `analysis` | explaining a thing until it is understood |
| `spec` | `spec` | pinning behaviour precisely enough to build against |
| `tokens` | `design-system` | documenting colours, type and components |
| `map` | `module-map` | showing how parts of a system connect |
| `deck` | `slide-deck` | it will be presented rather than read |

## Chip state vocabulary

A chip is the small coloured word on a phase or table row. The set is closed — the renderer accepts
these and nothing else:

`active` · `blocked` · `crit` · `done` · `failed` · `merged` · `note` · `ok` · `pending` ·
`planned` · `shipped` · `warn` · `wip`

There is also a **compound form**, `<label>:<level>`. The label becomes the chip's word and the
level picks its colour, so `bug:must` renders a red chip reading BUG, `feature:should` an amber one
reading FEATURE, and `chore:could` a grey one reading CHORE. That lets you name your own categories
without inventing new colours.

The full grammar, and what happens to a token the renderer rejects, is in
[`docs/design-language.md`](docs/design-language.md). That file is the source of truth, and a test
keeps this section and it from drifting apart.

## What you can rely on about the pages

- **Self-contained.** One HTML file. Styles and any assets are inlined, so the page works from a
  local disk, an email attachment, or a static host with nothing else next to it.
- **It fetches nothing at runtime.** No web fonts, no CDN scripts, no analytics, no remote images.
  The one exception is not an exception in practice: if you write a link in your markdown, the page
  contains that link, and a reader may click it. Nothing loads without them choosing to.
- **It carries no script at all.** No inline event handler, no `javascript:` URL, no `<script>`
  block. A Content-Security-Policy that forbids scripts outright costs the page nothing, because
  there is nothing to block.
- **One honest caveat about CSP.** The styling lives in a single inline `<style>` block, so a policy
  with a strict `style-src` and no `'unsafe-inline'` will strip the design and leave you readable
  but unstyled. If you serve these under such a policy, allow that block by hash or nonce.

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest scripts/tests/ tests/ -q
```

Expected: **2431 passed, 7 skipped**, exit 0.

Several of those skips are deliberate and explain themselves under `pytest -rs`. Use `pytest`, not
`python3 -m pytest` — on the machine this package came from, the interpreter cannot import pytest
and only the standalone executable works.

## Removing it

```bash
claude plugin uninstall design-doc-publish
claude plugin marketplace remove design-doc-publish
```

Uninstalling deregisters the plugin but **leaves its files on disk**, in a version directory marked
`.orphaned_at` under `~/.claude/plugins/cache/design-doc-publish/`. Delete that directory yourself
if you want the space back.

Your configuration is separate and survives on purpose. Delete
`~/.config/design-doc-publish/` to remove that too.

## Licence

**MIT** — see [`LICENSE`](LICENSE). That covers the code and documentation written here.

It does not cover the third-party material vendored under `references/`, which stays under its own
terms. `references/artifact-organizer/` is MIT, granted by upstream, and its notice travels with it.
A second vendored set was **removed** rather than shipped, because no upstream grant existed and
handing it to other people would have been redistribution nobody authorised. The whole position,
including how to restore that set if a grant is ever established, is in
[`docs/third-party-notices.md`](docs/third-party-notices.md).
