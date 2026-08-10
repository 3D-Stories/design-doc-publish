"""`report` — what was measured (#13, wave 3; specs §4d).

First-read element: the verdict headline plus the KPI strip. A KPI written as a
proportion (`28/44`) draws its own inline bar — §4d's "data tables with inline bars",
read through the KPI strip the same sentence specifies, so no new block type is needed.
Keeps `_decorate_scores`; the closing provenance section is titled "How this was measured".

#40 rebuilt the body against nsmith's `incident-report.html`. Measured, that page
is: an at-a-glance `.summary` strip of `.k`/`.v` pairs, a bordered `.panel` for the narrative, a
`.timeline` whose events hang off coloured `.marker` dots with mono timestamps, and a
`.checklist` of follow-up `.task`s with an `.owner` chip. The mapping here is
`stats` → the `.summary` grid, `callout summary` → the narrative `.panel`, `timeline` → the rail,
`steps followup` → the `.checklist`.

Getting that pairing the right way round matters and an earlier draft had it backwards: in the
reference, `.summary` IS the three-cell key/value grid under "At a glance", and the prose summary
is a SEPARATE bordered `.panel`. NOT adopted from the reference: its per-task `.owner` chip and
due/done metadata. `steps` emits number/title/text only, so an owner is just words in the text
field — modelling it properly is a renderer change, not a stylesheet one.

`steps` had to be added to `DOC_TYPE_TAGS["report"]` — a POLICY widening, taken on the
authority of issue #40's owner-confirmed mapping table (2026-08-02), which names a follow-up
checklist for `report`. The older §4d spec omits it; that doc is reconciled in this PR rather than
left to disagree: the accept map is enforced, and a fixture
using a rejected block trips `test_no_marker_fixture_uses_a_block_its_type_rejects`. The map and
the `## Doc types` table in `design-language.md` are compared for exact equality, so both move
together or neither does.

CASCADE NOTE (same as `design`): the template module is emitted BEFORE the shared optional layer,
so a rule here wins on specificity, never on order.
"""
NAME = "report"

# #76: this style's own page frame. Measured off nsmith's `incident-report.html` by
# reading its `<style>` block — that file is one of the twelve vendored templates carrying a
# `<script>`, and the repo's rule is to open those with JavaScript disabled (D66).
#
#   .wrap  max-width:820px; padding:2.5rem 1.25rem 4rem
#   h1     1.9rem; line-height:1.25
#   h2     1.05rem; UPPERCASE; letter-spacing:.08em  <- the distinctive one
#
# 820px is the narrowest of the ten. An incident report is read under pressure by someone
# deciding what to do, so the column is tight and the rhythm is dense — the opposite of `spec`,
# which is reference material read at leisure.
#
# The heading treatment is what makes this reference recognisable: section headings are not
# titles but LABELS — small, uppercase, wide-tracked, quiet. That reads as a log with named
# registers rather than as an essay, which is exactly what an incident report is. It lives in
# CSS below, for a reason worth knowing:
#
# **`h2_size` and `h2_rhythm` ARE INERT FOR EVERY SECTIONED STYLE, this one included.**
# `render_sections` splits on `##` and re-emits each section heading as the template's
# `heading_tag`, which defaults to `h3` — so a sectioned page contains no `h2` at all. The two
# h2 slots are still declared here because they are the honest values for this reference and
# because a future unsectioned page under this style would use them, but nothing on a rendered
# `report` page reads them today. Discovered by rendering and looking; every test passed while
# the rules matched nothing.
#
# The same is true of `analysis` as shipped in #93 — reported there rather than silently fixed
# from a different style's PR.
FRAME = {
    "ground": "var(--bg)",
    "measure": "820px",
    "gutter": "0 20px 64px",
    "header_pad": "40px 0 12px",
    "header_rule": "1px solid var(--line)",
    "header_gap": "22px",
    "h1_size": "clamp(24px,3.4vw,30px)",
    "h2_size": "16.8px",
    "h2_rhythm": "2.2em 0 1em",
}

SECTIONS = {"section_class": "rp-section"}

MARKERS = {
    "timeline": "rp-timeline",
    "stats": "rp-kpi",
    "stats.bar": "rp-bar",
    "callout:summary": "rp-summary",
    "callout:caveat": "rp-caveat",
    "steps:followup": "rp-followup",
}

CSS = """
/* #76 — the section heading as a LABEL, not a title. This is the one device that makes the
   incident-report reference recognisable at a glance: small, uppercase, wide-tracked and quiet,
   so the page reads as a log with named registers rather than as an essay.

   TARGETS `h3`, NOT `h2`, AND THAT IS NOT A TYPO. `render_sections` splits the document on `##`
   and emits each section heading as the template's `heading_tag`, which defaults to `h3`. So a
   SECTIONED style has no `h2` in its body at all — the first attempt here styled `h2` and
   changed nothing on the rendered page. Found by looking; no test would have failed, because
   the rule was present and valid, just unmatched.

   The same fact makes the frame's `h2_size`/`h2_rhythm` slots inert for every sectioned style.
   That is recorded in the FRAME comment above rather than quietly worked around. */
.tpl-report .rp-section>h3{text-transform:uppercase;letter-spacing:.08em;color:var(--ink-3);
font-weight:700;font-size:12.5px;margin:0 0 12px}
.tpl-report .rp-section{margin:34px 0 0}
/* The headline is the incident, and it is the one thing that should be read first. */
.tpl-report h1{line-height:1.25;max-width:24ch}
.tpl-report header .eyebrow{font-size:11px;letter-spacing:.13em}

.tpl-report .rp-section{margin-top:26px}
.tpl-report .rp-section h3{font-size:17px;color:var(--ink)}
/* At-a-glance panel — `.summary` in the reference. The report's opening claim, boxed, so the
   reader knows the answer before the evidence. */
.tpl-report .rp-summary{margin:18px 0 22px}
.tpl-report .rp-summary>.blk-callout{background:var(--surface);border:1px solid var(--line);
border-left:4px solid var(--accent);border-radius:12px;padding:14px 18px}
.tpl-report .rp-summary>.blk-callout>.blk-title{font-size:11px;letter-spacing:.07em;
text-transform:uppercase;color:var(--ink-3);font-family:ui-monospace,Menlo,Consolas,monospace}
/* KPI strip — the reference's `.k` label over a big `.v` value. */
.tpl-report .rp-kpi .blk-item{border-bottom:3px solid var(--accent);background:var(--surface);
border-radius:10px 10px 0 0;padding:10px 14px}
.tpl-report .rp-kpi .blk-value{font-size:26px;font-weight:700;letter-spacing:-.01em;
font-variant-numeric:tabular-nums}
.tpl-report .rp-kpi .blk-label{font-size:11px;letter-spacing:.06em;text-transform:uppercase;
color:var(--ink-3);font-family:ui-monospace,Menlo,Consolas,monospace}
.tpl-report .rp-bar{height:5px}
/* Timeline rail — the reference hangs each event off a ringed dot and colours it by state, so
   the eye finds "when did it turn" without reading. The shared layer draws a flat 8px dot.
   `_timeline` can emit exactly three declared states — `next`, `now`, `past` — plus `note`.
   `note` covers two DIFFERENT cases and the engine does not distinguish them: an unrecognised
   token (which warns) and a BLANK field (which does NOT — `_token` returns "note" before the
   warn path). An earlier version of this comment claimed blank warns; it does not. The
   base rule below IS the treatment for `next` and `note`: a hollow dot on the line colour, i.e.
   "nothing has happened here yet", which is right for both. Only `now` and `past` need to
   differ, so only they are overridden — a duplicate `.is-next` rule would say nothing. */
.tpl-report .rp-timeline{margin:18px 0;border-left-color:var(--line)}
.tpl-report .rp-timeline .blk-tl::before{width:11px;height:11px;left:-22px;top:12px;
background:var(--bg);border:2px solid var(--line)}
.tpl-report .rp-timeline .is-now::before{border-color:var(--accent);background:var(--accent)}
.tpl-report .rp-timeline .is-past::before{border-color:var(--ink-3)}
.tpl-report .rp-timeline .blk-when{font-weight:650;color:var(--ink-2)}
/* Follow-up checklist — `.checklist` in the reference: a bordered row per task, its number
   reading as a marker rather than as prose. Presentation only; `uat` owns real checkboxes. */
.tpl-report .rp-followup{margin:14px 0}
.tpl-report .rp-followup .blk-step{background:var(--surface);border:1px solid var(--line);
border-radius:10px;padding:10px 14px;margin:0 0 8px;border-bottom-style:solid}
.tpl-report .rp-followup .blk-n{font:700 11px/1.6 ui-monospace,Menlo,Consolas,monospace;
color:var(--accent);letter-spacing:.04em}
.tpl-report .rp-caveat>.blk-callout{border-left-color:var(--sev-med);background:var(--sev-med-bg)}
.tpl-report tbody tr:nth-child(even){background:var(--code)}
.tpl-report thead th{font:700 11px/1.6 ui-monospace,Menlo,Consolas,monospace;letter-spacing:.06em;
text-transform:uppercase;color:var(--accent);border-bottom:2px solid var(--accent);
text-align:left;padding:6px 10px}
.tpl-report blockquote{background:var(--code);border-left-color:var(--accent)}
"""
