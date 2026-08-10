# Rawgentic artifact design language

Every artifact the `render` engine (`user/design-doc-publish/scripts/render/`) renders — a WF1 issue spec, a WF2/WF3 design
doc, a WF14 run-feedback report, a campaign dashboard, an adversarial-review report —
shares ONE visual system: a single palette, one type scale, one set of component badges,
and one human-first document skeleton. This doc is the reference for that system; the
values below are read from `render/__init__.py` (the `_STYLE` and `_COMPONENT_STYLE`
blocks), never invented, and drift-guarded by `user/design-doc-publish/scripts/tests/test_render_artifact.py`.

## Tokens

Base palette — every value is a CSS custom property defined in four blocks in `_STYLE`:
**`:root` carries the DARK values**, the two `:root[data-theme=…]` overrides remain, and
`@media print` restores the light ones.

**Dark is the ground, not a preference (#73, owner decision 2026-08-02).** Before that, dark sat
behind `@media(prefers-color-scheme:dark)`, so a page was dark only if the *viewer's* operating
system was — and every state colour in the approved visual direction
(`docs/planning/2026-08-02-72-visual-spec.md`) needs a dark ground to read. A page still prints
light, because a forced-dark page sent to a printer is a solid dark rectangle.

The two `[data-theme]` blocks render nothing on their own — no emitted page stamps the attribute
— but they are load-bearing: `lint.theme_tokens()` reads exactly those two to score contrast in
both themes, and a VDL pack brands a page through them.

| Token       | Light     | Dark      | Role                         |
| ----------- | --------- | --------- | ---------------------------- |
| `--bg`      | `#f6f7f8` | `#12181c` | page background              |
| `--surface` | `#ffffff` | `#1a2228` | card / telemetry surface     |
| `--ink`     | `#1a2126` | `#e7edf0` | primary text + headings      |
| `--ink-2`   | `#4b5a63` | `#a8b6bd` | body copy, list items        |
| `--ink-3`   | `#667279` | `#76858f` | muted: blockquote, footer    |
| `--line`    | `#dde3e6` | `#2a353c` | borders, rules, table lines  |
| `--accent`  | `#0f766e` | `#2dd4bf` | eyebrow, links, left accents |
| `--code`    | `#eef1f3` | `#232d34` | code background, zebra rows   |

Component tokens — defined in `_COMPONENT_STYLE`, injected by every non-plain template
(the four severity ramps drive both the review badges and the requirement prohibition
badges; `--req-c` drives the affirmative RFC-2119 badge):

| Token           | Light     | Dark      | Role                       |
| --------------- | --------- | --------- | -------------------------- |
| `--sev-crit`    | `#b91c1c` | `#f87171` | critical severity text     |
| `--sev-crit-bg` | `#fdecec` | `#3b1717` | critical severity fill     |
| `--sev-high`    | `#c2410c` | `#fb923c` | high severity text         |
| `--sev-high-bg` | `#fdeee2` | `#3a2410` | high severity fill         |
| `--sev-med`     | `#955a06` | `#fbbf24` | medium severity text       |
| `--sev-med-bg`  | `#f8f2e2` | `#302a14` | medium severity fill       |
| `--sev-low`     | `#4b5a63` | `#a8b6bd` | low severity text          |
| `--sev-low-bg`  | `#eef1f3` | `#232d34` | low severity fill          |
| `--req-c`       | `#0f766e` | `#2dd4bf` | affirmative requirement    |
| `--req-c-bg`    | `#e6f2f0` | `#123531` | affirmative requirement bg |

Type scale (from `_STYLE`):

- **Body** — `15px/1.6` system stack (`-apple-system, "Segoe UI", Roboto, Helvetica,
  Arial, sans-serif`), on `--ink` over `--bg`.
- **h1** — `clamp(22px, 4vw, 30px)`, weight `750`, letter-spacing `-.02em`.
- **h2** — `19px`, weight `700`.
- **h3** — `16px`, weight `650`.
- **code / pre** — `12.5px/1.4` mono stack (`ui-monospace, Menlo, Consolas, monospace`)
  on a `--code` fill; tables are `13.5px`.

Spacing conventions (from `_STYLE`):

- `.wrap` — `max-width: 900px`, centred, `padding: 0 20px 72px`.
- `header` — `padding: 40px 0 18px`, bottom rule in `--line`.
- `pre` — `padding: 12px 14px`, `--line` border, 8px radius; `blockquote` — `14px` left
  pad behind a 3px `--accent` rule.

**Those are the DEFAULTS, not the only possibility** — since #69 a template may declare its own.
See the next section.

## The page frame — what a template owns (#69)

Until #69 the frame above was hardcoded once and a template could only write
`.tpl-<style> .some-widget{…}`. Of 233 `.tpl-` rules in the registry exactly one was frame-level
and it was a counter, which is why ten styles carrying 40–67% of their own page's CSS still looked
like one page.

The literals now live in `render/frame.py` as named slots, substituted back into `_STYLE` through
the same `string.Template` seam #42 used for the radius scale. Substituting the defaults is
byte-inert, which is what keeps `plain` frozen. A template declares overrides as `FRAME = {...}`
in its own module; only `frame.py` writes selectors.

### Owned

| Slot | Default | What it decides |
|---|---|---|
| `ground` | `var(--bg)` | what the page sits on — a flat colour or a wash over `--bg` |
| `measure` | `900px` | content width |
| `gutter` | `0 20px 72px` | how the content is inset |
| `header_pad` | `40px 0 18px` | the masthead's weight |
| `header_rule` | `1px solid var(--line)` | whether the masthead is ruled off |
| `header_gap` | `20px` | space below the masthead |
| `h1_size` | `clamp(22px,4vw,30px)` | top of the type scale |
| `h2_size` | `19px` | second step |
| `h2_rhythm` | `1.4em 0 .4em` | vertical spacing between sections |

Declared today: `uat` (a 1240px board with a radial wash and no header rule — its reference is a
four-column kanban), `spec` (a 760px reading column with a title-page masthead), `dashboard`
(1240px, scanned not read). The other six declare the defaults explicitly; #76 rebuilds them.

The layer is emitted for **every** non-plain style even when nothing differs, so `#45`'s gate can
tell "declared the default" from "has not been rebuilt", and so the cross-style guard's
`--foundation` mode has something to see.

### Withheld, and why

- **The body font family.** Output must stay self-contained (`test_no_external_hosts`), and both
  frozen targets reach their look on system fonts. A per-style family invites the first webfont.
- **Ink and line colours.** `lint.theme_tokens()` scores contrast by reading the two
  `[data-theme]` blocks only. A per-style ink would be invisible to that gate, so a style could
  ship unreadable text and still pass. Colour stays token-level, where it is measured.
- **The shell's structure** — `body > .wrap > header/main/footer`. Templates declare; they do not
  restructure. Every typed block composes against that shape and `uat`'s script addresses it.

**One gap worth knowing:** `ground` is the single owned slot the contrast gate cannot see, because
it is a background value rather than a token. A wash must stay close enough to `--bg` that the
scored pairs still hold. Nothing enforces that — say so in the PR when you change it.

## Components

Contract table — the exact CSS class, what it means, and which template(s) emit it. A
decorator only fires under the template whose registry entry names it (see Templates);
the zebra and evidence accents are plain CSS carried by a template's accent block.

| Class                                                              | Purpose                                        | Emitted by (template)                    |
| ------------------------------------------------------------------ | ---------------------------------------------- | ---------------------------------------- |
| `.score`                                                           | `N/5` fidelity chip (`_decorate_scores`)       | report                                   |
| `.sev` + `.sev-critical`/`.sev-high`/`.sev-medium`/`.sev-low`      | `Severity: <Level>` badge (`_decorate_severity`) | review                                 |
| `.req` + `.req-must`/`.req-must-not`/`.req-should`/`.req-should-not`/`.req-may` | RFC-2119 keyword badge (`_decorate_requirements`) | spec                              |
| `.chip` + `.c-conf`/`.c-defer`/`.c-plan`                           | completion-status chip on a card title         | roadmap, dashboard                       |
| `.mstone`                                                          | h2 section rendered as a bubble card           | roadmap, dashboard                       |
| `table` / `thead` zebra (`tbody tr:nth-child(even)` on `--code`)   | striped rows for scan-ability                  | report, review, dashboard (accent block), design (#40: also an accent `thead`, for the trade-off table) |
| `blockquote` evidence accent (left rule / fill in `--accent`/`--code`) | quoted evidence stands out from prose      | report, review (accent block)            |
| `.doc-code` + `.doc-code-bar`/`.doc-code-lang`/`.doc-code-copy`    | an ordinary code fence, boxed with its language and a copy button | every RICH style — this one is markdown, not a typed block |

### State tokens — what a chip ACCEPTS, not just which block emits it (#166)

The table above says which component each template emits. It never said which **words** a
component's state field accepts, and that omission shipped a defect: a `phases` chip took the
author's own word as its CSS class, so `done` produced `.is-done`, no template carried a
`.is-done` rule, and the chip rendered in the neutral grey while reading DONE. Nothing warned,
because the class was a valid slug. Three published pages carried it before anyone looked.

The second symptom was the same silence: with no documented vocabulary, two documents used
`ok`/`warn`/`crit` — **severity** words — on a rail that reports **status**, while a third used
`done`. One page said DONE and two said OK for the same fact.

**`phases` — the state field on a phase row and on an item row.** Closed set. A word outside it
warns and falls back to `note`; the author's text still renders.

| Write | Colour | Means | Tokens |
| --- | --- | --- | --- |
| finished | green (`--chip-c` on `--sev-low-bg`) | the work is done | `done`, `shipped`, `merged`, `ok` |
| moving | amber (`--sev-med`) | the work is in flight | `active`, `wip`, `pending`, `warn` |
| stuck | red (`--sev-crit`) | the work cannot proceed; the item id turns red too | `blocked`, `failed`, `crit` |
| not started | grey (`--ink-3` on `--code`) | deliberately neutral | `planned`, `note` |

**The compound token `<label>:<level>` (#167) — one chip, two facts.** Every bare token above
says exactly one thing: a state. A backlog rail needs two — what KIND of work an item is, and
how urgent it is. `crit` said urgent and hid the kind; `bug` said the kind and rendered grey.

The **label becomes the chip's word**; the **level picks its colour**. Write `bug:must` and the
chip reads BUG in red.

| Level | Colour | Borrows the token |
| --- | --- | --- |
| `must` | red | `crit` |
| `should` | amber | `warn` |
| `could` | grey | `note` |
| `done` | green | `ok` |

Labels: `bug`, `feature`, `chore`, `hardening`, `epic`, `action`, `note`, `task`.

Examples: `bug:must` → BUG red. `feature:should` → FEATURE amber. `chore:could` → CHORE grey.
`task:done` → TASK green. Case is the template's job, as for every other chip.

Four rules hold this together:

* **A level BORROWS a colour; it never mints a class.** `must` resolves to the same `is-crit`
  the bare token uses. Minting `is-must` would owe every phases-drawing template a new rule, and
  the first template to miss it would ship the grey chip #166 fixed. An import-time assertion
  pins that every borrowed token is one the templates already draw.
* **Bare tokens are untouched.** The colon is the only switch, and a bare token is a slug that
  cannot contain one. Every legacy document renders byte-identically.
* **An unknown label or level is loud**, exactly like an unknown bare token — it warns and falls
  back to `note`. A rejected compound shows the author's WHOLE original text, not the half that
  parsed: `bug:urgnet` renders `bug:urgnet`, because rendering a confident `bug` would present a
  typo as a successful parse.
* **A label is a type, not a status.** `source_lint` reads `<label>:done` as done and the other
  three levels as open, and it strips the label first so that `note:done` — whose label collides
  with an open-list word — does not read as done and open at once.

On a phase header the badge cell still supplies the word, so an authored badge wins. When the
badge is empty and the state is compound, the label becomes the badge, because otherwise
`Phase | | bug:must` would render no chip and the author's word would vanish.

Three rules that keep this from decaying again:

* **The grey group is asserted as an ABSENCE.** A template must not colour `planned` or `note`.
  Grey only reads as a choice while it is the only grey chip; the moment a fourth colour lands
  there, "deliberately neutral" and "nobody styled it" look identical again — which is the
  defect.
* **The groups live in `blocks.py`, the colours live in the template.** The group name carries
  the meaning, the stylesheet carries the paint. A template that accepts `phases` and does not
  colour every non-grey token fails `test_phase_state_vocabulary.py`.
* **Severity words are legacy, kept only so published pages keep their appearance.** Write the
  status word in a new document. `done` states what `ok` merely implies.

The same vocabulary drives `source_lint`'s stale-child check, which reads a row as finished or
open. A token that check cannot see is a hole in it, so the two lists are pinned equal by a test.

### `.doc-code` — the copy affordance on a code listing

A published doc routinely carries a command the reader is meant to RUN. Selecting it by hand
out of a `<pre>` is where a command gets truncated, so an ordinary fence renders as a box: a
header bar carrying the fence's info string (`bash`, `python`, or `code` when the fence names
nothing), and a **Copy** button.

Four properties, each one a decision rather than an accident:

- **Not in the `blk-` namespace.** Every other component here is a typed block. This one is
  plain markdown, and the lint gate reads `class="…blk-…"` as "this page carries a typed
  block" (`_BLOCK_MARKUP`). A fence claiming that token would make the gate lie.
- **Rich styles only.** `plain` is documented as carrying no template CSS and is pinned
  byte-for-byte by two gates, so it keeps the bare `<pre><code>`. No `--type` implies `plain`,
  so a published doc gets the box unless its author asks for the unstyled form.
- **The listing inside is byte-identical to the plain one.** The box WRAPS `<pre><code>…`,
  never rewrites it, so a fence degrades to the same listing everywhere else.
- **The button ships `hidden`.** The page's one script reveals it, so a reader with JavaScript
  disabled never sees a control that cannot work, and the listing stays selectable regardless.

This is the second of the renderer's two scripted features (`uat` is the other), and the only
one that can appear on a non-`uat` page. The script is inline, never fetched, uses none of
`innerHTML`/`outerHTML`/`document.write`/`eval`, and copies `textContent` — so the reader gets
`<script>` and not `&lt;script&gt;`. On an insecure origin, where `navigator.clipboard` is
absent, it falls back to `execCommand` and then says `Press Ctrl+C` rather than going quiet.
A page with no ordinary fence emits no script at all.

## Templates

The registry is `render._TEMPLATES` — one row per entry, in registry order.
"Renderer family" is the block renderer; "CSS layers" are the extra blocks appended to
`_STYLE`; "Decorator" is the inline pass composed after `_inline` (badge markup on
already-escaped text).

| Template    | Renderer family     | CSS layers                                | Decorator                | Surface + canonical invocation                                                                              |
| ----------- | ------------------- | ----------------------------------------- | ------------------------ | ----------------------------------------------------------------------------------------------------------- |
| `plain`     | `_render_body_plain`| none                                      | none                     | legacy / default — no template CSS, decorator, or body class; block semantics gained GFM tables (#343) and soft-wrap paragraph joining (#344); the fallback for any unknown style.             |
| `analysis`  | `render_sections`   | component + blocks + analysis             | none                     | a question answered at length — `--style analysis`. The default for a doc with no declared type. |
| `roadmap`   | `render_sections`   | component + blocks + roadmap              | none                     | h2 bubble cards + completion chips; epic and milestone state.                                               |
| `report`    | `render_sections`   | component + blocks + report               | `_decorate_scores`       | WF14 run-feedback reports — `--style report`.                                                               |
| `design`    | `render_sections`   | component + blocks + design               | none                     | WF2/WF3 design artifacts + the WORKSPACE `design-doc-publish` skill — `--style design`. See the gap note below. |
| `dashboard` | `render_sections`   | component + blocks + roadmap + dashboard  | none                     | campaign / roadmap shared docs — the denser card layout.                                                    |
| `review`    | `render_sections`   | component + blocks + review               | `_decorate_severity`     | WF5 adversarial-review reports — `--style review`.                                                          |
| `spec`      | `render_sections`   | component + blocks + spec                 | `_decorate_requirements` | WF1 issue specs — `--style spec`.                                                                           |
| `uat`       | `render_sections`   | component + blocks + uat                  | none                     | a checklist a human executes — `--style uat --doc-id <id>`. The only INTERACTIVE template. |
| `workflow`  | `render_sections`   | component + blocks + workflow             | none                     | how something flows or is wired — `--style workflow`.                                                       |
| `design-system` | `render_sections` | component + blocks + design-system    | none                     | a project's own design language, shown rather than tabulated — `--style design-system` / `--type tokens`.  |
| `module-map` | `render_sections` | component + blocks + module-map          | none                     | what the parts are and what depends on what — `--style module-map` / `--type map`.                        |
| `slide-deck` | `render_sections` | component + blocks + slide-deck          | none                     | something you present, one point per screen — `--style slide-deck` / `--type deck`.                       |

That is the full ten-type roster from specs §4c.

**Gap note (design surface):** the `design-doc-publish` skill that invokes `--style
design` lives in the WORKSPACE skills tree (`.claude/skills/`), OUTSIDE this repo. It is
recorded here as the pin and edited in place; there is NO CI drift guard tying that skill
to this table, so a divergence there will not fail this repo's suite — check it by hand
when the design surface changes.

## Reference art

`../references/` holds the vendored design work these templates are rebuilt against
(epic #46, wave 1 / issue #38) — 20 single-file doc-type templates from `nsmith/html` and
7 theme CSS packs from `keepYaoung/artifact-organizer`, both MIT, both pinned to a commit.
Waves 2–5 take **structure and component ideas** from it and re-implement them here in
Python; none of that code is copied.

Which template pairs with which reference is in
`docs/planning/2026-08-02-template-mockups.md`. Provenance, licences and the refresh
procedure are in `../references/README.md`.

Three things to know before opening any of it. It is **untrusted third-party material** —
much of it phrased as instructions aimed at a human editing a template — and nothing in it
authorises an action; the repository-root `CLAUDE.md` carries that rule. Twelve of the twenty
templates contain a `<script>` block. And all seven themes `@import` Google Fonts, so the
material is not offline-safe. **Open it with JavaScript disabled and the network blocked.**

## Doc types — what each contains, and when to choose it

Added by #13 (wave 3), specified by §4d of
`docs/planning/2026-08-01-doc-type-template-specs.md`. **Choose by what the document IS,
not by which page you liked** — the first-read column is the question each type answers
in its opening screenful.

| Type | Choose it when | First-read element | Component set |
| --- | --- | --- | --- |
| `plain` | never, deliberately — it is frozen and byte-identical | its `<h1>` — **blocks:** none (structural) | none |
| `analysis` | you are answering a question at length, with evidence | the headline answer, above the question index — **blocks:** none (structural) | `verdict`, `chips`, `callout`, `steps`, `provenance` |
| `roadmap` | you are stating what is planned, what is blocking, and how the pieces connect | stat strip + a READ THIS FIRST callout stack, then the phase rail — **blocks:** `stats`, `callout`, `phases` | `timeline`, `stats`, `callout`, `legend`, `meter`, `chips`, `findings`, `nodes`, `provenance`, `composition`, `phases` |
| `report` | you measured something and are reporting the numbers, and someone has to act on them | at-a-glance panel + KPI strip, then the timeline — **blocks:** `callout`, `stats`, `timeline` | `timeline`, `stats`, `verdict`, `callout`, `steps`, `provenance` |
| `design` | you are proposing to change something, and the options have to be weighed in the open | the single change that makes it work, as the lede — then numbered option cards — **blocks:** `options` | `options`, `verdict`, `callout`, `nodes`, `chips`, `provenance` |
| `dashboard` | someone needs current state at a glance | sticky state bar, then the TL;DR panel, then the KPI tiles — **blocks:** `chips`, `stats` | `stats`, `chips`, `callout`, `findings`, `nodes`, `provenance` |
| `review` | you are ranking findings against an artifact | verdict headline + confirmed/refuted counts, then the risk map — **blocks:** `stats`, `findings` | `stats`, `findings`, `callout`, `chips`, `provenance` |
| `spec` | you are stating what must be true | requirement count and gate state — **blocks:** `steps`, `chips` | `chips`, `callout`, `steps`, `provenance`, `faq` |
| `uat` | a human must execute a checklist and report back | the progress meter, reading `0 / N` — **blocks:** `meter` | `steps`, `callout`, `chips`, `meter` |
| `workflow` | you are showing how something flows or is wired | the flow chart, then the legend and the stage rails — **blocks:** `flow`, `legend`, `steprail` | `steprail`, `nodes`, `legend`, `callout`, `chips`, `provenance`, `flow` |
| `design-system` | you are showing a project's own colours, type and radii | the token swatch grid, then the legend naming each group and the status chips — **blocks:** `legend`, `chips` | `legend`, `callout`, `chips`, `provenance` |
| `module-map` | you are showing what the parts are and what depends on what | the map itself, then its key — **blocks:** `nodes`, `legend` | `nodes`, `legend`, `callout`, `chips`, `provenance` |
| `slide-deck` | you are presenting, one point per screen | the headline, then its figures — **blocks:** `stats` | `stats`, `callout`, `chips`, `provenance` |

**The `— **blocks:**` annotation on each first-read cell is the source of truth for
`blocks.FIRST_READ_DEVICES`** (#130), which `publish_doc.gate()` enforces: a styled page must carry
**every** block its own style opens with, not merely one component of any kind (that weaker floor
is `check_blocks`, #127). The annotation is derived from the prose beside it and never invented —
`TestFirstReadDeviceContract` in `test_template_bodies.py` parses this column and requires exact
equality with the code, so the two cannot drift. Edit the annotation here, not the map.

### The three publish-time component checks, and which flag reaches which

| Check | Refuses | Reached by `--skip-component-checks`? |
|---|---|---|
| `check_blocks` (#127) | a styled page with **no** typed blocks at all | yes |
| `check_style_devices` (#130) | a styled page missing any block its style **opens with** | yes |
| `check_template_classification` (#130) | an **unknown** `tpl-` class, or more than one `<body>` carrying one | **no — always fails** |

The first two are disjoint by construction, so exactly one of them ever reports and a single publish
failure never reads as two. The third is deliberately outside the flag: `--skip-component-checks`
means "this document really is prose", and an unclassified template class or a second `<body>` is
structural corruption rather than a statement about prose. **`--allow-prose` is the older name for
that flag and still works** (#151); it named one check honestly until #130 put a second behind it.

Style discovery **tokenises** the `<body>` class attribute (#150), so `class="theme tpl-roadmap"`,
`class='tpl-roadmap'`, `<BODY>` and an unquoted value are all recognised. Before that it required
`tpl-<style>` to be the entire double-quoted lowercase value, and anything else read as a page this
engine never drew — i.e. exempt from all three checks. A page with **no** `tpl-` token stays exempt,
which is load-bearing: `plain` emits no body class, and neither does a hand-rolled or pre-engine
page (#128).

### Run telemetry does not cross the publish path by itself (#152)

`render_artifact` builds the **Run telemetry** section from a run-record mapping, and the WF2
design-artifact step passes one automatically. `publish_doc.py` does not infer it — pass
`--telemetry <file.json>` or the section is absent.

This matters when **re-publishing a page some other step created**. Without the flag the regenerated
page loses the section, and if the only copy of those figures lived in that generated file, it is
gone. Measured on this repo's own campaign log during #130: the HTML carried Run telemetry and
Quality gates, the markdown never had, and the records behind them sat in an untracked store. An
empty `{}` is accepted and renders the "telemetry unavailable" placeholder — a record present but
empty, which the renderer deliberately distinguishes from absent. Malformed telemetry is a loud
stage-1 failure, never a quietly dropped section.

Two rows read `none (structural)` because their first-read element is built by the RENDERER rather
than declared by an author — `plain`'s `<h1>`, and `analysis`'s headline answer (`.an-answer`, an
opening paragraph, see the markers table below). There is nothing for a gate to require, and the
words are exact: an empty requirement must always be a statement someone made, never the residue of
a parser that matched nothing. `design-system`, `module-map` and `slide-deck` arrived with #42 and had no row here at all, so they
were un-opinionated — the same convention `DOC_TYPE_TAGS` states for an absent type. **#149 gave
them one**, derived from what each template actually builds (`templates.MARKERS`) rather than
invented. `slide-deck` requires only its figures on purpose: `blocks.py` describes a slide as
carrying "a headline, a figure or two and **at most one** point", and "at most one" means the
point is optional, so requiring its `callout` would contradict the template's own description.
`UNDOCUMENTED_FIRST_READ` is now empty, and the completeness test keeps it honest: a new template
must be classified in one place or the other or the suite goes red.

### Markers, and the fence role

Every component carries a marker class so a test can pin its presence under its own type
AND its absence under the others (`test_template_bodies.py`). Where a type uses one block
for two different jobs, the author disambiguates with a **role** — a second word on the
fence info string. A role never becomes a class: it selects a key in the template's own
marker map, so no author text reaches a class attribute.

| Type | Structural markers | Block markers (fence to write) |
| --- | --- | --- |
| `analysis` | `.an-q` section, `.an-answer` opening paragraph, `.an-conf` confidence chip, `.an-index` jump index | `.an-figure` (`steps`), `.an-measure` (`callout` role `measure`); its comparison table is a plain markdown table, styled with no marker |
| `roadmap` | `.rm-epic` (beside the legacy `.mstone`) | `.rm-timeline` (`timeline`), `.rm-meter` (`meter`), `.rm-child` (`chips`), `.rm-risk` (`findings`), `.rm-flow` (`nodes` role `flow`), `.rm-phase` (`phases`) |
| `report` | `.rp-section` | `.rp-summary` (`callout` role `summary`), `.rp-timeline` (`timeline`), `.rp-kpi` (`stats`), `.rp-bar` (a `stats` value written `28/44`), `.rp-followup` (`steps` role `followup`), `.rp-caveat` (`callout` role `caveat`) |
| `design` | `.dz-lead` preamble | `.dz-options` (`options`), `.dz-compare` (`nodes` role `compare`), `.dz-decision` (`callout` role `decision`) |
| `dashboard` | `.db-tldr` preamble prose, `.mstone` sections | `.db-kpi` (`stats`), `.db-spark` (a `stats` sparkline), `.db-statebar` (`chips` role `statebar`), `.db-attention` (`findings`), `.db-prov` (a findings row's 4th field), `.db-highlight` (`callout` role `highlight`), `.db-columns` (`nodes` role `columns`) |
| `review` | `.rv-section` | `.rv-hypo` (`chips` role `hypo`), `.rv-sev` (`findings`), `.rv-weakest` (`callout` role `weakest`), `.rv-riskmap` (`findings` role `riskmap`) |
| `spec` | `.sp-section`, `.sp-index` jump index | `.sp-req` (`steps` role `req`), `.sp-ac` (`steps` role `ac`), `.sp-gate` (`chips` role `gate`) |
| `uat` | `.ut-step` section, `.ut-meter`, `.ut-filter` and `.ut-export` furniture | `.ut-board` (`steps`, the checklist), `.ut-item` + `.ut-note` (every `steps` row), `.ut-stop` (`callout` role `stop`) |
| `workflow` | `.wf-stage` section (heading stays `h2`), `.wf-key` furniture — shown only on a page that carries a rail | `.wf-rail` (`steprail`), `.wf-node` (`nodes`), `.wf-edge` (a node's 3rd field), `.wf-legend` (`legend`), `.wf-inset` (`callout` role `inset`), `.wf-flow` (`flow`) |

An **unlisted role warns and renders the block unmarked** — it never drops content. A
template that declares no role map ignores the suffix entirely, exactly as before #13.

### Two places this deviates from §4d, deliberately

- **`.wf-edge` is a node's third field, not an arrow.** §4d sketched workflow edges as
  `[a] --WAN--> [b]`. Wave 2 replaced that grammar because pipes-encoding-depth were
  unreadable at three levels (`typed-blocks-grammar.md`). #13 restores the edge as an
  optional third field per node — depth stays indentation, and the edge keeps its label
  plus an existing-versus-proposed state (trailing `~`).
- **`.sp-req` is a `steps` row, not an h2 section.** §4d asks for requirement rows with a
  stable ID and a MUST/SHOULD chip. `steps` is already `id | title | text`; an h2 wrapper
  would have been neither an ID nor a row.

### `uat` is interactive, and the two ways it differs

`uat` is the only template that declares more than structure and style, and the only one that
ships behaviour. Both extras are declarative — it supplies no callable:

- **`BLOCK_VARIANTS = {"steps": "checklist"}`.** `blocks.py` holds two `steps` renderers and the
  template names one. A checklist row is a label-wrapped checkbox plus a comment box, and every
  item gets both — the target page has 25 items and only 16 comment boxes, which is the defect
  this template exists to correct. Parsing and escaping stay in the engine.
- **`BEFORE_BODY` / `AFTER_BODY`.** Trusted CONSTANT furniture — the sticky meter, the export
  control, the script — emitted around the rendered body. They contain no author text at any
  point, which is what makes them safe to emit unescaped.

**Identity.** The DOM `id` is generated (`uat-check-<n>`), so it is unique by construction, and no
`for` is emitted because the label wraps its checkbox. The row's own first cell is the LOGICAL id,
carried in `data-k`/`data-note`, and it is what storage and the export key on — so inserting an
item cannot reassign a tester's saved answers, which is a real hazard on the positionally-keyed
target. An empty or duplicated id degrades the whole fence to a code listing rather than silently
merging two items onto one checkbox.

**Storage** is one page-scoped, schema-versioned key, `uat:<doc_id>:v1`, holding a single JSON
blob, with `try`/`catch` on both read and write so a browser with storage disabled degrades to a
working-but-forgetful checklist. `--doc-id` is explicit on purpose: a title-derived key would make
two pages sharing a title share all state, and would abandon every saved answer on a rename.
Omitting it warns.

**CSP: one stated exemption.** The engine's "survives a strict Content-Security-Policy" claim holds
for every template except `uat`, which emits a single inline `<script>` — a strict
`script-src 'self'` must permit an inline script, or its hash, for that style alone. No other
template emits a script at all, and a test pins that. Zero `innerHTML`, `outerHTML`,
`document.write` or `eval` anywhere.

### The block stylesheet

`blocks.BLOCK_CSS` styles all ten typed-block components and is injected by every
non-plain template. Wave 2 shipped the block engine with **no stylesheet at all** — the
markup existed and every component rendered as unstyled stacked text — which is why this
lives in wave 3. Every value in it is a `var(--…)` token from `_STYLE` or
`_COMPONENT_STYLE`, so a per-project VDL pack (wave 6) restyles all of it by overriding
tokens and no component hardcodes a colour.

## Human-first skeleton

Every templated artifact opens with its verdict-first lead section — the at-a-glance
summary, decision, status, or verdict — before any evidence or detail, so the document
reads top-down for a human. The renderer does not enforce this; it is an authoring
contract on the markdown fed in. Per template, the lead section is:

- **report** → "At a glance" — the headline pass/fail and the one-line delta.
- **design** → "Decision" — what was chosen, up front, before the rationale.
- **dashboard** → "Status" — the campaign's current state in one card.
- **review** → "Verdict" — confirmed / refuted / inconclusive before the findings.
- **spec** → "Summary" — the issue's ask in one paragraph before the requirements.
- **analysis** → the headline answer, before the question index (#13).
- **roadmap** → the stat strip and the READ THIS FIRST callouts (#13).
- **workflow** → the legend, before any diagram the reader has to decode (#13).
- **uat** → the progress meter, so a tester sees how much is left before starting (#18).

This mirrors the WF14 rubric precedent — see `skills/run-feedback/references/rubric.md`,
"Report structure — human-first", which established verdict-first lead sections for
run-feedback reports.

### The lint gate found these tokens failing AA

Wave 5 (#12) added a mechanical contrast check, and its first honest run failed the
engine's own output in four places. All four are fixed above and in `_STYLE` /
`_ROADMAP_STYLE`; they are recorded here because a palette change is the kind of thing
that otherwise looks arbitrary six months later.

| Token pair | Was | Now | Why it failed |
| --- | --- | --- | --- |
| `--ink-3` on `--bg` (light) | 3.32:1 | 4.61:1 | muted text is still body text, so 4.5 applies |
| `--ink-3` on `--bg` (dark) | 4.40:1 | 4.71:1 | same, marginally under |
| `--sev-med` on `--sev-med-bg` (light) | 4.41:1 | 5.02:1 | badge text on its own fill |
| `--defer` on `--defer-bg` (light) | 4.41:1 | 5.02:1 | chip text on its own fill |

Two calls worth recording rather than burying. `--line` is held to "must merely differ"
rather than 3.0: a hairline divider is decorative, and WCAG 1.4.11 covers controls and
meaningful graphics, not every rule. And the gate initially scored BOTH themes with the
dark palette, because a bare `:root{` regex also matches the `:root` nested inside the
dark media query — it reads the explicit `[data-theme=…]` blocks now.

## Security invariants

The renderer is fed possibly-untrusted spec text, so the design language is enforced on
already-safe HTML. These invariants are load-bearing, not stylistic:

- **Escape-first.** Every piece of text — markdown body, title, telemetry — is
  `html.escape`d BEFORE any block or inline transform. A `<script>` in a spec renders as
  inert `&lt;script&gt;` text, never active markup.
- **CSP-safe / self-contained.** Inline CSS only; no external host (no CDN link/script/
  font/img), so the artifact survives a strict Content-Security-Policy and renders
  anywhere offline.
- **Decorators run on escaped text, outside code spans.** Every badge decorator wraps the
  output of `_inline` and only touches the segments OUTSIDE `<code>…</code>`, so a literal
  quote like `` `Severity: High` `` or `` `MUST` `` stays undecorated, and every inserted
  `<span>` wraps inert, already-escaped text.
- **`_inline` closed grammar.** `_inline` may only emit attribute-free `<code>`/`<strong>`
  — pinned by `test_inline_closed_grammar_guard`. The decorators' code-span split relies
  on this; growing `_inline` (e.g. links/attributes) forces revisiting the decorators.

## Exemplar

`docs/design-language-example.md` is a fixture exercising every block the renderer
handles (headings, wrapped + hard-break bold, a table, a blockquote, a fenced code block
whose `MUST`/`3/5` stay verbatim, score/severity/RFC-2119 lines). Its committed render,
`docs/design-language-example.html`, is reproducible byte-for-byte from source with a
PINNED stamp and the `design` style. Regenerate it with exactly this one-liner (run from
the repo root):

```
PYTHONPATH="$PWD/user/design-doc-publish/scripts" python3 -m render \
  --md user/design-doc-publish/docs/design-language-example.md \
  --out user/design-doc-publish/docs/design-language-example.html \
  --title "Design-language exemplar" --style design \
  --generated-at "2026-07-10 12:00 MDT"
```

**Reproducibility contract:** `test_exemplar_reproducible_byte_for_byte` re-renders the
fixture with the same pinned `generated_at` + `title` + `style` and byte-compares to the
committed HTML. Any renderer change that alters the design-style output must regenerate
this exemplar in the same commit, or the guard fails — the exemplar is the executable
proof that this doc and the renderer agree.
