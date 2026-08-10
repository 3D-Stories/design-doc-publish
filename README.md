# design-doc-publish

Turns a markdown design document into a single self-contained HTML page that looks like it was
designed, not dumped. One file out. No build step, no CSS framework, no JavaScript bundle.

It is a Claude Code plugin, so the usual way to use it is to let Claude drive it. You can also run
it directly, and everything below is a command you can paste into a terminal.

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

## Install it

Two commands. The first one is easy to miss, and without it the second cannot find anything:

```bash
claude plugin marketplace add 3D-Stories/design-doc-publish
claude plugin install design-doc-publish@design-doc-publish
```

Then start a **new** session. A session that is already running holds paths it resolved at startup,
so it will not see a plugin installed after it began.

## Your first page

This works with nothing configured — no account, no workspace file, no network.

**If you installed the plugin**, the scripts live inside the install, so point at them there. Note
that the path is written out in full: `${CLAUDE_PLUGIN_ROOT}` is expanded by Claude when it loads a
skill, and your shell does **not** expand it, so it is no use in a command you paste.

```bash
DDP=~/.claude/plugins/cache/design-doc-publish/design-doc-publish/1.0.0
printf '# Hello\n\nA first page.\n\n## A section\n\nSome prose.\n' > hello.md
python3 "$DDP/scripts/render-doc" --md hello.md --out hello.html --title "Hello"
```

**If you cloned the repo instead**, run it from the checkout:

```bash
printf '# Hello\n\nA first page.\n\n## A section\n\nSome prose.\n' > hello.md
python3 scripts/render-doc --md hello.md --out hello.html --title "Hello"
```

Open `hello.html`. That is the whole loop.

## Honest limits, before you install anything

**Rendering works for anyone. Publishing does not work for anyone but the author yet.**

`scripts/publish_doc.py` renders, lints, deploys to Vercel and verifies the live page, in seven
stages. **Stage 1 works for you. Stage 2 refuses**, and that is measured, not estimated:

```
publish_doc: 1/7 rendered hello.html (design template)
publish_doc: FAILED at stage 2: --project '<name>' is not a rawgentic project in
~/rawgentic/.rawgentic_workspace.json, and is not the literal 'workspace' bucket.
```

Two things are still hardcoded to one machine: the workspace file that stage 2 validates
`--project` against, and the Vercel team the deploy stages target. So use `scripts/render-doc`
above, which has neither dependency, rather than `publish_doc.py`.

[Issue #9](https://github.com/3D-Stories/design-doc-publish/issues/9) is the first-run setup flow
that fixes both. **No release is tagged until it lands**, because tagging one would advertise
something that is not true yet.

## Prerequisites

| What | Why | Verified |
| --- | --- | --- |
| Python 3.12 | the renderer and its tests | 3.12.3, which produced the test count below |
| No third-party Python packages | the renderer is stdlib only, on purpose | — |
| `vercel` CLI | only for deploying, not for rendering | needed from stage 4 |
| A Vercel account | only for deploying | see the limits above |

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

Expected: **2235 passed, 7 skipped**, exit 0.

Three of those skips are deliberate and explain themselves under `pytest -rs`. Use `pytest`, not
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

## Licence

**MIT** — see [`LICENSE`](LICENSE). That covers the code and documentation written here.

It does not cover the third-party material vendored under `references/`, which stays under its own
terms. `references/artifact-organizer/` is MIT, granted by upstream, and its notice travels with it.
A second vendored set was **removed** rather than shipped, because no upstream grant existed and
handing it to other people would have been redistribution nobody authorised. The whole position,
including how to restore that set if a grant is ever established, is in
[`docs/third-party-notices.md`](docs/third-party-notices.md).
