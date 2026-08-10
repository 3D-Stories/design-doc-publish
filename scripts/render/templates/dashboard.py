"""`dashboard` — current state at a glance (#13, wave 3; specs §4d).

First-read element: the sticky state bar, then the TL;DR panel. They are two SEPARATE
consecutive elements, so `.db-tldr` deliberately wraps only the preamble prose — a
`chips statebar` block authored above it stays outside the panel and stays sticky.

#40 rebuilt the body against `references/nsmith-html/status-report.html`. Re-opened and measured
while writing this, not recalled: its sections run HEADER, KEY METRICS, HIGHLIGHTS, VELOCITY
CHART, WORKSTREAMS, FOOTER, and the three this template takes are

* `.metrics` > `.metric`, each a `.label` + big `.value` + a `.delta` carrying `up`/`down`/`flat`
  + a `.spark` of seven `<span style="height:N%">` bars;
* `.highlights`, a `<ul>` whose every `<li>` opens with a `<strong>` lead sentence and continues
  with the detail in the same line;
* `.streams` > `.stream`, three side-by-side columns each headed `<h3><span class="dot green">`
  plus a status word, holding `.item`s of `.t` title / `.s` subtitle / `.tag` reference.

Two of the three needed NO new accepted tag, which is worth stating because the design that
reached this module assumed otherwise (see T4/D19 — the same assumption was wrong there):

* **KPI tiles are `stats`, already accepted and already shaped for this.** `_stats` reads
  `value | label | delta | spark` — the same four CONCEPTUAL fields as `.metric`, adapted to the
  renderer we already have rather than reproduced. The reference carries semantic
  `.delta.up`/`.down`/`.flat` classes and seven CSS-height bars; `_stats` emits an unclassified
  `.blk-delta` and an SVG `<polyline>`, so the direction of a delta is NOT machine-readable here
  and the spark is a line rather than bars. `db-spark` already existed for the sparkline; the
  tile itself just had no marker, so the BARE `stats` slot was free and `db-kpi` takes it.
* **Highlights are a `callout`**, already accepted; `db-highlight` is a new ROLE, not a new tag.

`nodes` IS newly accepted, and under D18 that needs both halves stated:

* **Owner requirement.** Issue #40's mapping table is owner-confirmed 2026-08-02 and names
  "status columns" for `dashboard`.
* **Type semantics.** A status board is defined by its GROUPING — an item means something only
  as "shipped" or "blocked", and the columns ARE those groups. That is two levels, and `nodes` is
  the only block in this type's vocabulary that carries hierarchy. The already-accepted
  alternatives were checked first rather than assumed away: `findings` gives
  `severity | title | text | prov`, which fits an item but is FLAT, and CSS cannot gather
  arbitrary siblings into columns without a wrapper element; `chips` and `callout` carry no
  structure at all. **Unlike T4's risk map — where the same `nodes` assumption turned out to be
  false because the reference's map is flat — the hierarchy here is really in the reference.**
  "The reference contains it" is still not the argument on its own.

Multi-root `nodes` becoming a row of columns is the ENGINE'S existing mechanism, not something
invented here: the shared layer already grids the top-level list (`.blk-nodes>ul{display:grid}`)
and `design`/`workflow` opt into `grid-template-columns:1fr 1fr` for their two-root pairs. This
just asks for three-ish tracks instead of two.

Emitted classes were read off a real render before this stylesheet was written. A `nodes columns`
block gives `ul > li.blk-node` (the stream, label only) each containing `ul > li.blk-node` with
`.blk-edge`/`.blk-label`/`.blk-text` — the edge is the `.tag`, and it comes FIRST in the DOM with
`flex-basis:100%` from the shared layer, so it is reordered below the title here.

NOT adopted, stated accurately:

* **The stream's status dot is not colour-coded, and cannot be from this grammar.** `_nodes`
  tokenises no field, so a stream heading is plain text with no `is-<state>` class — the
  reference's `.dot.green`/`.amber`/`.red` has no counterpart. Executed, not assumed. A coloured
  dot per column needs a tokenised field, which is a grammar change and not this PR.
* **The velocity bar chart is not adopted at all.** Stated precisely, because the first version
  of this sentence claimed a limitation the engine does not have: `stats` DOES carry a series of
  labelled magnitudes — one `.blk-value`/`.blk-label` per row, plus a proportional `.blk-fill`
  when a value is written `28/44`. What is missing is the reference's PRESENTATION: a standalone
  categorical chart drawing every column against one shared vertical scale. `stats` renders
  tiles, and a spark is per-tile. Left out because the owner-confirmed mapping does not name it
  and no presentation exists, not because the data could not be expressed.

FIXED — **#119**, closed 2026-08-05; the same defect `roadmap` carried, because they share
`roadmap_status_chip`. Kept in the past tense rather than deleted, so the next reader can see it
was dealt with.

**A page used to publish a status nobody wrote.** Verified through the real render path, before:

    ## Outlook

    Nothing has shipped yet.        ->  rendered  Outlook [SHIPPED]

The resolver word-matches completion vocabulary and returns the first hit. It recognised several
negators, but only within roughly the preceding two tokens, and `nothing` was not in the vocabulary
at all — so "No work shipped" was handled while "No work is done" and "Nothing shipped" were not.
#119 added the missing quantifier negators and replaced the two-token window with clause scope.
See `roadmap.py` for the measured before/after table; the two share `roadmap_status_chip`.

WHAT WAS FIXED — #90, in #112: the resolver no longer scans FENCED block cells. So the examples
this paragraph used to give are out of date. A "Key metrics" section whose TILES say "PRs merged"
no longer gets `[MERGED]` from them, because tiles are fenced. Stated precisely: fenced cells are
excluded; the SECTION HEADING and unfenced prose are still scanned, and a definitive heading
status takes precedence — `## Shipped work` renders `[SHIPPED]` however its prose reads, and that
heading precedence is by design, not a residue of the defect.

History worth keeping: `markdown.py` is byte-unchanged here so this predates the rebuild, but the
old body was a stack of `.mstone` epic cards that genuinely carried state, while this one invites
ordinary prose sections — which is what made the mismatch easy to hit. The fix once proposed here,
explicit heading/status metadata instead of keyword scanning, was considered and NOT taken; #112
changed the scanner instead, and #119 then closed the remaining negation gap in the same scanner.
"""
NAME = "dashboard"

# #69: a dashboard is scanned, not read — its tiles want room to sit side by side rather than
# stack in a reading column, and its masthead is a status bar rather than a title page.
# #76 completes what #69 started here — this was one of only two styles with a partial frame.
# Measured off `references/nsmith-html/status-report.html` by reading its `<style>` (D66):
#
#   --maxw 880px · .wrap padding:40px 20px 72px
#   h1     clamp(26px,5vw,38px); line-height:1.12; letter-spacing:-.02em
#   h2     13px; UPPERCASE; letter-spacing:.1em; muted   <- `.section-head`
#
# **The measure DEPARTS from the reference, deliberately: 1240px, not 880px.** #69 set 1240 for
# this style because its job is a dense card layout — a campaign dashboard puts many cards in a
# row, and the reference is a single-column status report that happens to share the doc type.
# Narrowing to 880 would also collide with `analysis`, which really is 880 for the opposite
# reason (it is prose). The spec's review checklist allows a departure that states itself; this
# is that statement.
#
# `h2_size`/`h2_rhythm` are declared for completeness but are INERT here — `dashboard` is
# sectioned, so its headings are re-emitted as `h3` (D70). The heading treatment is in CSS.
FRAME = {
    "ground": "var(--bg)",
    "measure": "1240px",
    "gutter": "0 24px 72px",
    "header_pad": "34px 0 12px",
    "header_rule": "none",
    "header_gap": "18px",
    "h1_size": "clamp(26px,5vw,38px)",
    "h2_size": "13px",
    "h2_rhythm": "2em 0 .8em",
}

SECTIONS = {"section_class": "mstone", "chip_resolver": "status",
            "preamble_class": "db-tldr"}

MARKERS = {
    "chips:statebar": "db-statebar",
    "findings": "db-attention",
    "findings.tail": "db-prov",
    "stats.spark": "db-spark",
    "stats": "db-kpi",
    "callout:highlight": "db-highlight",
    "nodes:columns": "db-columns",
}

CSS = """
/* #76 — the reference's `.section-head`: a small wide-tracked label with a hairline running out
   to the right of it, so the eye finds the register boundaries while scanning tiles. That rule
   is what distinguishes this from `report`, whose headings are the same size and casing but
   sit alone; here the line does the separating and the label stays quiet.
   Targets `h3` because `dashboard` is sectioned — see the FRAME note and D70. */
.tpl-dashboard .mstone>h3{display:flex;align-items:center;gap:14px;font-size:13px;
letter-spacing:.1em;text-transform:uppercase;color:var(--ink-3);font-weight:700;margin:0 0 14px}
.tpl-dashboard .mstone>h3::after{content:"";flex:1;height:1px;background:var(--line)}
.tpl-dashboard h1{line-height:1.12;letter-spacing:-.02em;max-width:20ch}
.tpl-dashboard header .eyebrow{font-size:11px;letter-spacing:.13em}

.tpl-dashboard .db-statebar{position:sticky;top:0;z-index:2;background:var(--bg);
border-bottom:1px solid var(--line);padding:8px 0;margin:0 0 14px}
.tpl-dashboard .db-statebar .blk-chip{font:10.5px/1.4 ui-monospace,Menlo,Consolas,monospace;
text-transform:none;letter-spacing:.02em}
.tpl-dashboard .db-tldr{background:var(--surface);border:1px solid var(--line);
border-left:4px solid var(--accent);border-radius:12px;padding:4px 18px 12px;margin:0 0 22px}
.tpl-dashboard .db-attention{background:var(--surface);border:1px solid var(--line);
border-radius:12px;padding:4px 16px}
.tpl-dashboard .db-prov{color:var(--ink-3);font-style:normal}
.tpl-dashboard tbody tr:nth-child(even){background:var(--code)}
.tpl-dashboard .mstone{padding:10px 14px;margin:10px 0}
/* Specificity-bumped on the move: the shared `.blk-stats .blk-spark polyline` is (0,2,1),
   EQUAL to this rule, which used to win only because it sat later in the same string.
   Emitted earlier now, so it must win on specificity — (0,3,1). */
.tpl-dashboard .blk-stats .db-spark polyline{stroke:var(--accent)}
/* KPI tiles — the reference's `.metric`: the value is the loud element, the label a quiet
   eyebrow ABOVE it, and the delta a coloured line under both. The shared strip already lays
   cells out in a row; what changes here is the vertical order inside a cell and the emphasis. */
.tpl-dashboard .db-kpi{gap:14px;margin:18px 0}
.tpl-dashboard .db-kpi .blk-item{display:flex;flex-direction:column;gap:3px;
background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.tpl-dashboard .db-kpi .blk-label{order:1;font:11px/1.4 ui-monospace,Menlo,Consolas,monospace;
letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3)}
.tpl-dashboard .db-kpi .blk-value{order:2;font-size:30px;line-height:1.1;letter-spacing:-.02em}
.tpl-dashboard .db-kpi .blk-delta{order:3;font-size:12px;color:var(--ink-2)}
/* `.blk-bar` MUST carry an order. A proportional value (`28/44`) emits one, and an unordered
   flex child defaults to order 0 — ahead of every field numbered here — so omitting this rule
   put the bar above the label. That is a regression on a `dashboard` stats form that already
   worked, found by review and reproduced before fixing; a test now pins the whole sequence. */
.tpl-dashboard .db-kpi .blk-bar{order:4}
.tpl-dashboard .db-kpi .blk-spark{order:5;margin-top:4px}
/* Highlights — the reference's `.highlights`: a bordered panel whose lead sentence carries the
   weight. Our callout already emits a bold `.blk-title`, so the panel is the only new part. */
.tpl-dashboard .db-highlight>.blk-callout{background:var(--surface);
border-left-color:var(--accent);border-radius:12px;padding:12px 16px}
.tpl-dashboard .db-highlight .blk-title{font-size:14.5px}
/* Status columns — the reference's `.streams`: one column per state, each headed by the state
   word with its items beneath. The columns come from gridding the TOP-LEVEL list, which is the
   engine's existing multi-root mechanism (`design` and `workflow` do the same for two roots).
   `auto-fit` rather than a fixed three, because the number of states is the author's choice and
   a fourth column should wrap rather than overflow. */
.tpl-dashboard .db-columns{margin:18px 0}
.tpl-dashboard .db-columns>ul{grid-template-columns:repeat(auto-fit,minmax(210px,1fr));
gap:16px;align-items:start}
.tpl-dashboard .db-columns>ul>li.blk-node{display:block;background:none;border:0;padding:0;
margin:0}
.tpl-dashboard .db-columns>ul>li.blk-node>.blk-label{display:block;
font:11px/1.6 ui-monospace,Menlo,Consolas,monospace;letter-spacing:.06em;
text-transform:uppercase;color:var(--ink-3);border-bottom:1px solid var(--line);
padding-bottom:6px;margin-bottom:8px}
.tpl-dashboard .db-columns ul ul{margin:0;padding:0;border-left:0;display:grid;gap:8px}
.tpl-dashboard .db-columns ul ul .blk-node{margin:0;padding:10px 13px;border-radius:10px}
.tpl-dashboard .db-columns .blk-label{order:1;flex-basis:100%;font-weight:650}
.tpl-dashboard .db-columns .blk-text{order:2;flex-basis:100%;color:var(--ink-3);
font:12px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.tpl-dashboard .db-columns .blk-edge{order:3;flex-basis:auto;text-transform:none;
letter-spacing:.02em;color:var(--ink-3)}
"""
