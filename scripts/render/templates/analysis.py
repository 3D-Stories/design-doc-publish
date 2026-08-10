"""`analysis` — a question answered at length (#13, wave 3; specs §4d).

First-read element: the headline answer, above the index of questions. Each h2 is one
question; its opening paragraph is the answer and everything after it is the evidence.

#40 rebuilt the body against nsmith's `concept-explainer.html`. Re-opened and
measured while writing this — and the extraction cross-checked against the raw file, because on
the previous task a regex silently dropped a section and its output was trusted. That page's
three prose sections are "How it works", "How it compares" and "Key terms", and the parts this
template takes are:

* `<ol class="steps">` — one `<li>` per step, each a `<b>` lead sentence followed by a
  `<span class="note">` detail. STATIC: every step is visible at once.
* `<table class="compare">` — a real three-column table, `Dimension` against two named
  approaches, whose cells carry `.naive`/`.ours` so the two sides read differently.
* `.note` — used exactly FOUR times on that page, all of them as the detail line of a step. Our
  measurement callout borrows that quiet voice; it is not a component the reference has.

This template had NO block markers at all before this (`MARKERS` was `{}`), so it is the largest
greenfield of the eight. It nonetheless takes **one** new accepted tag, not the two the design
that reached here assumed — the same over-assumption that was wrong on T4 and half wrong on T5:

* **The comparison table needs NO block and NO new tag.** Markdown tables already render, as a
  bare `<table>`, so the component this template gains is the STYLING of one. Executed: a
  three-column markdown table under `--style analysis` emits `<table><thead>…` with no wrapper
  and no warning. Styling a bare element scoped by `.tpl-analysis` is the established pattern
  here (`review` and `dashboard` both do it for `tbody tr:nth-child(even)`; `roadmap`, `uat` and
  `workflow` had no template table rule either, so `analysis` was NOT uniquely bare — an earlier
  version of this line claimed it was). No marker class exists because a markdown table gets no
  CLASS or wrapper hook; its structural hooks (`table`/`thead`/`tbody`/`td`) are all it has.
  Emitting an analysis-only class WOULD be possible — `doc_type` already reaches the markdown
  renderer — but it is a renderer change, so it is out of scope for a body PR rather than
  impossible. Pinned by its own test rather than by the marker table.
* **Measurement callouts are a `callout`**, already accepted; `an-measure` is a new ROLE.

`steps` IS newly accepted, and under D18 both halves are stated:

* **Owner requirement.** Issue #40's mapping table is owner-confirmed 2026-08-02 and names a
  "stepped figure" for `analysis`.
* **Type semantics.** This type answers a question with evidence, and a mechanism explained in
  ordered stages is evidence — "how it works" is the reference's own first section. `steps` is
  the grammar for an ordered list of titled stages with detail.

**`steprail` was rejected in favour of `steps`, deliberately.** The design that reached here named
`steprail`. Executed, both: `steprail` emits `<details name=…>` per stage — an EXCLUSIVE
disclosure rail where opening one closes the others (D8). Precisely: every step's number and
title stay visible in its `<summary>`; it is the DETAIL of all but one that is collapsed. The
reference's stepped figure is a plain `<ol>` with every step visible. `steps` emits
`<li class="blk-step">` with `.blk-n`/`.blk-title`/`.blk-text`, which is the reference's
`<b>`-lead-plus-`.note`-detail field for field, plus the number the `<ol>` was already implying.
Choosing the disclosure rail would have made the figure less faithful AND more interactive than
the page it copies.

NOT adopted, stated accurately:

* **The interactive demo is not adopted.** `.demo`/`.stage`/`.controls`/`.readout` is a scripted
  widget, and this engine's inline-script carve-out is `uat`-only by documented policy. Out of
  scope for a stylesheet.
* **The comparison table's per-side cell tinting is not reproduced.** `.naive`/`.ours` are classes
  on individual `<td>`s. Correcting an earlier version of this line: positional emphasis IS
  mechanically available — `tbody td:nth-child(2)` and `:nth-child(3)` would reach those columns
  with no renderer change. It is omitted because nothing in the grammar says column 2 means the
  naive option and column 3 the proposed one. A four-column or two-column comparison would get
  tinted arbitrarily, so the styling distinguishes only the first column, which is the dimension
  in any comparison table. The obstacle is missing SEMANTICS, not a missing selector.
* **`.glossary` ("Key terms") is not adopted** — the owner-confirmed mapping does not name it, and
  a definition list is `provenance`'s shape rather than a new component.

PARTLY FIXED, and the remainder is still live (corrected 2026-08-03 by #113).

The TWO cases this paragraph used to cite as failing ARE fixed. Executed against this file's own
import (the third row is a positive control, added here — it was never shown to be broken):

    confidence_chip("Q?", "Inferred, not measured — …")  -> INFERRED   (was MEASURED)
    confidence_chip("Q?", "Not measured.")               -> —          (was MEASURED)
    confidence_chip("Q?", "Measured on the live host.")  -> MEASURED   (control, unchanged)

History, kept because the reason it existed is worth keeping: the function word-matched the
confidence vocabulary in fixed order and returned the first hit, so an answer opening "Inferred,
not measured" carried a `MEASURED` chip — asserting the OPPOSITE of the sentence beneath it, on
the one doc type whose purpose is separating confirmed from inferred. Filed as #55, absorbed into
#21, fixed in #86.

FIXED — #119, closed 2026-08-05. The negator vocabulary was incomplete and its reach was short.
Executed, before and after:

    confidence_chip("Q?", "Nothing was measured.")       -> MEASURED   (before)  ->  —  (now)

`nothing` was not a recognised negator, and recognised ones only reached back a token or two.
`roadmap_status_chip` had the identical gap ("Nothing has shipped yet." -> SHIPPED), which is why
#119 covered both rather than one — and it needed only one change, because both chips reach the
same `_negated` beneath them. It added `nothing`/`none`/`neither` and widened the window from two
words to six. Coordinated negation is covered too: "Nothing was inferred or measured." reads `—`
where it used to read MEASURED.

The window's ONE known wrong answer, and the reasoning for accepting it, is recorded at
`_NEGATOR_REACH` in `markdown.py`. It errs toward the neutral chip, never toward asserting a
confidence level the answer did not claim — which is the direction that matters on this doc type.
"""
from ..markdown import confidence_chip

NAME = "analysis"

# #76: this style's own page frame — the thing #40 could not reach, because before #69 a template
# could only write `.tpl-analysis .some-widget{…}` and the frame was hardcoded once for everyone.
# That is why nine styles with 40-67% of their own CSS still read as one page.
#
# Measured off nsmith's `concept-explainer.html` — its `<style>` block read directly,
# not a description of it:
#
#   .wrap  max-width:880px; padding:48px 24px 96px
#   h1     clamp(28px,5vw,42px); line-height:1.12; letter-spacing:-.02em
#   h2     22px; margin:40px 0 14px
#   body   two radial washes over the page ground
#
# The measure is DELIBERATELY narrower than the 900px default. This type answers one question at
# length, so it is the one style that is mostly prose, and a shorter line is what makes long prose
# readable — 880px at this size is roughly 90 characters.
#
# The ground is two washes rather than the reference's three: its third sits behind an interactive
# demo stage this template has no equivalent of. Both are kept close to `--bg`, because `ground` is
# the one owned slot the contrast gate cannot see (`frame.py` says so, and it is why).
FRAME = {
    "ground": ("radial-gradient(1100px 560px at 82% -12%,#1a243f 0%,transparent 60%),"
               "radial-gradient(900px 500px at -12% 8%,#17203a 0%,transparent 55%),var(--bg)"),
    "measure": "880px",
    "gutter": "0 24px 96px",
    "header_pad": "48px 0 10px",
    "header_rule": "none",
    "header_gap": "26px",
    "h1_size": "clamp(28px,5vw,42px)",
    # #76 (D70): these two are INERT here and are kept only because they are the honest values
    # read off the reference. `analysis` is sectioned, so `render_sections` re-emits every `##`
    # as `h3` and nothing on a rendered page reads an `h2` rule. The reference's 22px/40px
    # rhythm is applied to `.an-q>h3` in the stylesheet instead, which is what the page has.
    # Discovered while building `report`, reported on #76, fixed here in the PR that closes it.
    "h2_size": "22px",
    "h2_rhythm": "40px 0 14px",
}

SECTIONS = {
    "section_class": "an-q",
    "lead_class": "an-answer",
    "chip_resolver": confidence_chip,
    "chip_class": "an-conf",
    "index_class": "an-index",
}

MARKERS = {
    "steps": "an-figure",
    "callout:measure": "an-measure",
}

CSS = """
/* #76 — the frame's companions. The FRAME slots above own ground, measure and type scale; these
   are the treatments that only make sense once those exist.

   THE EYEBROW, as the reference has it: an inline-block pill in accent over a tint of itself,
   not a bare line of small caps. `--req-c-bg` rather than a new value — it is the accent hue's
   own tint, already in the token layer and already contrast-scored there. */
.tpl-analysis header .eyebrow{display:inline-block;color:var(--accent);
background:var(--req-c-bg);border:1px solid var(--line);border-radius:999px;padding:5px 13px;
font-size:11.5px;letter-spacing:.14em}
/* The headline gets the reference's tight leading and a measure of its own: a display line that
   runs the full 880px reads as a paragraph, not a title. */
.tpl-analysis h1{line-height:1.12;max-width:20ch}
/* The lede — the reference's `.lead`. This type's first-read element is the headline ANSWER, and
   the subtitle is where it lands. */
.tpl-analysis header .sub{font-size:17.5px;line-height:1.6;color:var(--ink-2);max-width:62ch}
.tpl-analysis .an-index{background:var(--surface);border:1px solid var(--line);
border-radius:12px;padding:10px 18px;margin:18px 0}
.tpl-analysis .an-index ol{margin:.2em 0;padding-left:1.2em}
.tpl-analysis .an-index li{margin:.25em 0}
.tpl-analysis .an-index a{color:var(--ink-2);text-decoration:none;border-bottom:1px solid var(--line)}
.tpl-analysis .an-index a:hover{color:var(--accent);border-bottom-color:var(--accent)}
.tpl-analysis .an-q{border-top:1px solid var(--line);padding-top:14px;margin-top:24px}
/* #76/D70: the reference's 22px section scale and 40px rhythm, applied where the page can
   actually read them. The FRAME's h2 slots cannot reach a sectioned style. */
.tpl-analysis .an-q>h3{font-size:22px;margin:40px 0 14px}
.tpl-analysis .an-q h3{font-size:17px;display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
.tpl-analysis .an-answer{font-size:16.5px;line-height:1.55;color:var(--ink);font-weight:550;
border-left:3px solid var(--accent);padding-left:14px;margin:.5em 0 .9em}
/* The base .chip shape lives in _ROADMAP_STYLE, which only roadmap and
   dashboard inject — so an analysis chip needs its own shape, not just a
   colour, or it renders as tight coloured text. */
.tpl-analysis .an-conf{font:10.5px/1.4 ui-monospace,Menlo,Consolas,monospace;
font-weight:700;letter-spacing:.05em;padding:2px 8px;border-radius:999px;
text-transform:uppercase;white-space:nowrap}
.tpl-analysis .c-measured{color:var(--req-c);background:var(--req-c-bg)}
.tpl-analysis .c-confirmed{color:var(--req-c);background:var(--req-c-bg)}
.tpl-analysis .c-inferred{color:var(--sev-med);background:var(--sev-med-bg)}
.tpl-analysis .c-unstated{color:var(--ink-3);background:var(--code)}
/* Stepped figure — the reference's `<ol class="steps">`: the number is the quiet index, the lead
   sentence carries the weight, and the detail drops to the note voice underneath it. Static, so
   there is nothing to open; see the docstring for why this is `steps` and not `steprail`. */
.tpl-analysis .an-figure{background:var(--surface);border:1px solid var(--line);
border-radius:12px;padding:14px 18px;margin:18px 0}
.tpl-analysis .an-figure ol{display:grid;gap:12px;margin:0;padding:0}
.tpl-analysis .an-figure .blk-step{display:grid;grid-template-columns:auto 1fr;gap:2px 12px}
.tpl-analysis .an-figure .blk-n{grid-row:1/3;font:700 13px/1.5 ui-monospace,Menlo,Consolas,
monospace;color:var(--accent);align-self:start}
.tpl-analysis .an-figure .blk-title{font-weight:650;color:var(--ink)}
.tpl-analysis .an-figure .blk-text{color:var(--ink-3);font-size:13.5px;line-height:1.55}
/* Measurement callout — the reference's `.note` voice, promoted to a panel because in this type
   a measurement is the evidence the answer rests on. */
.tpl-analysis .an-measure>.blk-callout{background:var(--code);border-left-color:var(--accent);
border-radius:10px;padding:10px 15px}
.tpl-analysis .an-measure .blk-title{font:11px/1.5 ui-monospace,Menlo,Consolas,monospace;
letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3)}
/* Comparison table — the reference's `<table class="compare">`. No marker: a markdown table gets
   no CLASS or wrapper hook from the renderer (its structural hooks — table/thead/tbody/td — are
   all it has), so this styles the bare element scoped to this template, exactly as `review` and
   `dashboard` do for their zebra rows.
   `:not(.telemetry):not(.gates)` is NOT defensive dressing. The renderer appends its own
   `table.gates` and `table.telemetry` inside `<main>`, so an unqualified `.tpl-analysis table`
   restyled them too — a leak the cross-style gate CANNOT see, because it stays inside `analysis`.
   Found by review, reproduced, then excluded.
   The row-header column is `tbody td:first-child`, NOT `tbody th`: markdown emits every body
   cell as `<td>`, so the `th` form was a dead selector that styled nothing. Also review's. */
.tpl-analysis table:not(.telemetry):not(.gates){border:1px solid var(--line);border-radius:12px;
border-collapse:separate;border-spacing:0;overflow:hidden;margin:18px 0}
.tpl-analysis table:not(.telemetry):not(.gates) thead th{background:var(--code);
font:11px/1.5 ui-monospace,Menlo,Consolas,monospace;letter-spacing:.06em;text-transform:uppercase;
color:var(--ink-3);text-align:left}
.tpl-analysis table:not(.telemetry):not(.gates) tbody td:first-child{font-weight:650;
color:var(--ink)}
.tpl-analysis table:not(.telemetry):not(.gates) tbody tr:nth-child(even){background:var(--code)}
"""
