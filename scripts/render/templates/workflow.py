"""`workflow` — how something flows, or how it is wired (#13, wave 3; specs §4d).

First-read element: the legend, then the diagram pair. A `nodes` block IS the frame: it
gets a bordered container, and a `callout inset` is pulled into the frame above it as
§4d's "what this means" note. Two `nodes` blocks side by side are the before/after pair.

§4d wrote its edges as arrows (`[a] --WAN--> [b]`); wave 2 replaced that with an
indentation tree because pipes-encoding-depth were unreadable (typed-blocks-grammar.md).
#13 restores the edge as an optional THIRD field per node, so depth stays indentation and
the edge keeps its label and its existing-versus-proposed state.

#41 gave this template a body. It had none: on a PROSE-ONLY source it was tag-for-tag
identical to `plain` (30 tags each, measured), because it declared markers but no `SECTIONS`
and no furniture, and a marker only attaches to a typed block. On a source carrying typed
blocks the two already differed (102 vs 273 tags on the repo's own `crossstyle.md`), since
`plain` renders a fence as a code listing — so a runbook built from prose alone came out as
a plain document, and one built around typed blocks did not. `--type runbook` maps here
(`publish_doc.py:94`).

`heading_tag` is "h2" DELIBERATELY. The seven other sectioned styles — roadmap, dashboard,
analysis, report, review, spec and uat — take `render_sections`' "h3" default because their
CSS was written for h3; a runbook stage is a major division and the shared sizing already
says so. It also keeps the authored heading LEVEL unchanged, which is the half of the
`test_template_bodies` heading contract that must not move: sectioning here is intended,
demotion would not be.

CURRENT POSITION IS PER-RAIL, NOT PER-PAGE, and that is a real limitation rather than a
design choice. `_steprail` gives every fence its own `<details name=…>` group and opens the
first row of each, so a runbook with one rail per stage shows SEVERAL steps highlighted at
once — measured: steps 1 and 4 of 6 open on load in a two-rail document. Closing an open
step leaves that rail with no highlight at all, because native disclosure has no "always one
open" mode. Both behaviours live in the shared engine, so no per-template change reaches
them. What this template guarantees is narrower and worth stating plainly: within one rail,
the open step is unmistakable.

The reference `flowchart.html` was NOT adapted, only read. It builds every step in script
from an empty `<main class="flow" id="flow" aria-label="Deploy pipeline steps"></main>`
(`:142`, filled from `:214`) and uses `innerHTML` twice (`:246`, `:280`), so with JavaScript
off its procedure disappears entirely — the header, legend and "select a step" hint are all
that remain. AC3 requires the opposite. Reveal-on-click here is the native `<details>` of
#39's rail, so this template ships NO script and the engine's inline-script carve-out stays
`uat`-only. Deliberately deferred rather than dropped: the reference's
process/decision/terminal types, its success/failure paths and its per-step timing and
command path. The rail grammar is a frozen four fields with `kind` validated against exactly
{action, check}; those would be a grammar change, not a body.
"""
NAME = "workflow"

# A stage per authored `##`. See the module docstring for why the heading stays h2.
# #76, last of the seven. This style has NO vendored reference — the issue says "first build was
# #41; re-judge against the approved direction" — so the frame derives from the approved visual
# spec (`docs/planning/2026-08-02-72-visual-spec.md`) rather than from a file's `<style>` block.
#
# 1000px: a runbook shows a stage's steps with their detail open, so it needs more than prose
# width and less than `design`'s comparison grid. It is the seventh distinct measure of the ten,
# which is the whole argument of #76 stated in one number.
#
# **This is one of only TWO styles whose `h2` slots are live** — `workflow` passes
# `heading_tag: "h2"` so its stage headings keep their level (the other is `design`, which is
# unsectioned). Everywhere else they are inert (D70).
FRAME = {
    "ground": "radial-gradient(1200px 600px at 80% -10%,#18222f 0%,var(--bg) 55%)",
    "measure": "1000px",
    "gutter": "0 20px 64px",
    "header_pad": "32px 0 12px",
    "header_rule": "none",
    "header_gap": "18px",
    "h1_size": "clamp(24px,3.2vw,32px)",
    "h2_size": "18.4px",
    "h2_rhythm": "2.4em 0 .6em",
}

# The approved spec's §2 "Per-section accent" device, now reachable because #75 added
# `frame.palette_layer`. Values are the spec's own `--cyan` / `--violet` / `--amber`, sampled
# there from `shots/target-roadmap-milestones.png`.
#
# The spec is explicit that this accent IDENTIFIES a section and never signals state, so it is
# spent only on the stage marker and heading. The rail's own state colours are untouched.
ACCENTS = ("#38c6f4", "#b18aff", "#ffa62b")

SECTIONS = {"section_class": "wf-stage", "heading_tag": "h2"}

# Static furniture: a key for the two step kinds the rail marks. The rail renders them as
# CSS-generated content (`.is-action .blk-n::after{content:" do"}` in the shared layer), so
# nothing on the page says what "do" and "check" mean. Hidden unless a rail is present — see
# the CSS. `wf-key`, NOT `wf-legend`: that name is already the marker for the `legend` BLOCK.
BEFORE_BODY = ('<div class="wf-key">'
               '<span class="wf-kk is-do">do</span>'
               '<span class="wf-kt">an action to perform</span>'
               '<span class="wf-ksep" aria-hidden="true"></span>'
               '<span class="wf-kk is-check">check</span>'
               '<span class="wf-kt">a condition to confirm before moving on</span>'
               '</div>',)

MARKERS = {
    "steprail": "wf-rail",
    "nodes": "wf-node",
    "flow": "wf-flow",
    "nodes.edge": "wf-edge",
    "legend": "wf-legend",
    "callout:inset": "wf-inset",
}

CSS = """

/* Stages. The wrapper is the STRUCTURE a prose runbook was missing — the unconditional key
   below also changes the tag sequence, so the wrapper is not the only difference from
   `plain`, just the one that means anything. The divider is what makes a stage visible on a
   page carrying no typed block. */
.tpl-workflow{counter-reset:wf-stage}
.tpl-workflow .wf-stage{counter-increment:wf-stage;border-top:1px solid var(--line);
margin-top:20px;padding-top:20px}
.tpl-workflow .wf-stage:first-of-type{border-top:0;margin-top:0;padding-top:0}
/* Printed runbooks are real: a page break between a stage heading and its steps leaves an
   operator holding unlabelled instructions. Measured in Chrome's letter-size print preview,
   where "3 Verify and close" and its warning sat at the foot of page 1 with all three of its
   steps on page 2. `break-inside` on the stage is a request, not a guarantee, for a stage
   longer than a page — hence also pinning the heading to what follows it. */
.tpl-workflow .wf-stage{break-inside:avoid}
.tpl-workflow .wf-stage>h2{break-after:avoid}
@media print{.tpl-workflow .wf-rail .blk-rail-step{break-inside:avoid}}
/* Numbers, and the key below, appear only on a page that carries a RAIL. `workflow` also
   serves topology documents built from `nodes` and an authored `legend`, and numbering
   "Current network / Failure domains / Link legend" 1-2-3 asserts a procedure that does not
   exist. The rail is the page's own declaration that it IS a procedure. */
.tpl-workflow:has(.wf-rail) .wf-stage>h2::before{content:counter(wf-stage);
display:inline-block;min-width:1.5em;margin-right:10px;text-align:center;
font:700 13px ui-monospace,Menlo,Consolas,monospace;color:var(--accent);
background:var(--code);border-radius:8px;padding:2px 0;vertical-align:2px}

/* The step-kind key. Hidden by default: `BEFORE_BODY` is unconditional, and a do/check key
   above a network diagram that has neither is misleading furniture, not harmless emptiness.
   `uat`'s always-on meter is not a precedent — every uat page owns its meter, while a
   rail-free workflow page is ordinary. */
.tpl-workflow .wf-key{display:none;align-items:center;gap:8px;flex-wrap:wrap;
background:var(--code);border-radius:10px;padding:8px 14px;margin:0 0 18px;
font-size:12.5px;color:var(--ink-2)}
.tpl-workflow:has(.wf-rail) .wf-key{display:flex}
.tpl-workflow .wf-kk{font:700 11px ui-monospace,Menlo,Consolas,monospace;letter-spacing:.04em}
/* The same two tokens the shared rail uses for its `do` and `check` markers, so the key and
   the thing it explains cannot drift apart. */
.tpl-workflow .wf-kk.is-do{color:var(--accent)}
.tpl-workflow .wf-kk.is-check{color:var(--req-c)}
.tpl-workflow .wf-ksep{width:1px;height:14px;background:var(--line)}

/* Current position WITHIN a rail — see the module docstring for why a page with several
   rails has several. The spine deliberately does NOT get any border colour of `var(--accent)`:
   the shared rail marks the OPEN step with a 2px accent left border, and painting the whole
   spine that same colour hid it — measured at 2px rgb(15,118,110) for both, so the operator
   could only find their place by spotting the expanded paragraph. A second and third
   redundant channel as well as the border, because 2px of colour is not enough to find
   under pressure. */
.tpl-workflow .wf-rail .blk-rail-step:has(details[open]){background:var(--code);
border-radius:0 10px 10px 0}
.tpl-workflow .wf-rail .blk-rail-step:has(details[open]) .blk-title{font-weight:750}

/* #76 — THE DIAGRAM. Owner, looking at the rebuilt page: "dont you think a workflow diagram
   should have a workflow diagram?" They were right, and it is the same catch they made on
   `roadmap` in #68: the style had every component and no picture.

   `nodes` was rendering as an indented list against a flat left rule — a TREE, not a diagram.
   Nothing on it said "this connects to that". What a reader needs is boxes joined by visible
   wires, and the grammar already carries everything required: indentation is the topology and
   the optional third field is the edge LABEL. So no grammar change and no renderer change —
   only the wires, drawn.

   Built from the elbow up: a spine down each level, a horizontal wire into every child, an
   arrowhead where the wire meets the box, and the edge label sitting ON the wire rather than
   floating in the text. `::before`/`::after` on `.blk-node` were unused anywhere in the engine
   (checked before writing, after two collisions earlier in this issue). */
.tpl-workflow .wf-node{background:var(--code);border:1px solid var(--line);
border-radius:14px;padding:18px 20px}
.tpl-workflow .wf-node .blk-node{background:var(--surface);border-color:var(--line);
position:relative;padding:9px 13px}
/* The spine. Thicker than the shared 1px rule and in the stage's own accent, so the diagram
   reads as structure rather than as an indented list. */
.tpl-workflow .wf-node ul ul{margin-left:30px;padding-left:26px;
border-left:2px solid var(--wf-a,var(--accent))}
/* The wire into each child, and its arrowhead. `top:19px` centres it on the child's first
   line at this padding and font size — measured on a rendered page, not guessed. */
.tpl-workflow .wf-node ul ul>.blk-node::before{content:"";position:absolute;left:-26px;top:19px;
width:20px;height:2px;background:var(--wf-a,var(--accent))}
.tpl-workflow .wf-node ul ul>.blk-node::after{content:"";position:absolute;left:-8px;top:14px;
border:5px solid transparent;border-left-color:var(--wf-a,var(--accent));border-right-width:0}
/* The spine runs the full height of its level and does NOT stop at the last wire. An attempt to
   trim it with a `box-shadow` mask is deleted rather than kept: it did not work — a 6px shadow at
   the wire's own y cannot cover the run below it — and a rule that does nothing is worse than an
   honest convention. Terminating the spine needs the last child's height, which CSS cannot reach
   here without fixing the box size. A spine spanning the level is the ordinary tree-diagram
   convention anyway; noted so the next person does not re-attempt the mask.
   Both pseudo-elements on `.blk-node` are spent (wire, arrowhead), which is why there is no third
   element to draw a mask with. */
/* The edge label rides ON the wire. The shared layer gives it `flex-basis:100%`, which drops it
   onto its own line under the box; here it is a pill above the box instead, which is where a
   diagram puts an edge name. */
.tpl-workflow .wf-edge{flex-basis:auto;display:inline-block;margin:0 0 4px;padding:1px 8px;
border-radius:999px;background:var(--code);border:1px solid var(--line);
color:var(--wf-a,var(--accent));font-weight:700}
.tpl-workflow .wf-edge.is-proposed{color:var(--ink-3);border-bottom:1px dashed var(--ink-3);font-weight:400}
.tpl-workflow .wf-legend{background:var(--code);border-radius:10px;padding:12px 16px}
.tpl-workflow .wf-inset{margin-top:-8px}
.tpl-workflow .wf-inset>.blk-callout{border-left-color:var(--ink-3);font-size:13.5px}
/* Before/after is two roots in ONE nodes block — see design.py. */
@media(min-width:820px){.tpl-workflow .wf-node>ul{grid-template-columns:1fr 1fr}}

/* #76 — the approved spec's per-section accent (§2), appended AFTER the base rules on purpose.
   `test_the_counter_is_reset_incremented_and_consumed` and `..._separated_from_the_title` each
   read the FIRST rule matching their selector, so an addition that shares a selector with the
   stage counter must sit last — otherwise the guard reads this rule as the base and reports a
   counter that is not incremented. Both fired when this block was at the top; they were right.

   Each stage owns one of the spec's three hues and spends it on the stage number this template
   ALREADY draws and on the stage's own top rule — never on a new marker, and never on state.
   The spec is explicit: the accent identifies the section, the rail's colours signal state. */
.tpl-workflow .wf-stage{--wf-a:var(--tpl-a1,var(--accent));border-top-color:var(--wf-a)}
.tpl-workflow .wf-stage:nth-of-type(3n+2){--wf-a:var(--tpl-a2,var(--accent))}
.tpl-workflow .wf-stage:nth-of-type(3n+3){--wf-a:var(--tpl-a3,var(--accent))}
.tpl-workflow:has(.wf-rail) .wf-stage>h2::before{color:var(--wf-a);border-color:var(--wf-a)}
.tpl-workflow h1{line-height:1.18;max-width:22ch}
.tpl-workflow header .eyebrow{font-size:11px;letter-spacing:.13em}

/* #76 — THE FLOW CHART. Owner, twice: the page needed a diagram, and then that the wired tree
   still was not one. It is right — a tree has depth, a flow has ORDER, and drawing wires on a
   tree does not turn it into a sequence.

   Built from `flowchart.html`, measured: `.flow` is a flex column with `gap:0` so the spacing IS
   the connectors; `.node` is a centred box at `max-width:460px`; `.connector` is a 2px x 28px
   rule between nodes. Three shapes carry meaning — a terminal is a pill, a step is a rectangle,
   a decision is a rotated square. The arrowhead sits at the bottom of each connector, so every
   arrow points INTO the box it feeds.

   Drawn in CSS, no SVG and no script: the output stays self-contained and the whole chart
   survives with the stylesheet disabled as a plain ordered list of labels. */
.tpl-workflow .wf-flow{display:flex;flex-direction:column;align-items:center;gap:0;
background:var(--code);border:1px solid var(--line);border-radius:14px;padding:22px 20px}
.tpl-workflow .blk-flow-node{width:100%;max-width:460px;text-align:center;
background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:11px 16px;
font-weight:650}
/* A terminal starts or ends the flow, so it is a pill and it carries the stage accent. */
.tpl-workflow .blk-flow-node.is-term{border-radius:999px;border-color:var(--wf-a,var(--accent));
color:var(--wf-a,var(--accent))}
/* A decision is the only place the flow can fork, so it is the only shape that is not a
   rectangle.
   `clip-path`, NOT a rotated pseudo-element. The first attempt rotated an inset `::before` 45deg;
   on a box far wider than it is tall that produces a long diagonal SLAB, not a diamond, and it
   overflowed into the boxes above and below — plainly wrong the moment the page was opened, and
   invisible to every test. `clip-path` cannot overflow its own box, so the shape is correct at
   any text length.
   The trade-off, stated: a clipped element cannot carry a border, so the decision reads by FILL
   and by its amber label rather than by an outline. Generous padding keeps the text clear of the
   sloped edges. */
.tpl-workflow .blk-flow-node.is-dec{max-width:420px;border:none;padding:30px 72px;
background:var(--sev-med-bg);
clip-path:polygon(50% 0,100% 50%,50% 100%,0 50%)}
.tpl-workflow .blk-flow-node.is-dec .blk-flow-label{color:var(--defer)}
@media(max-width:560px){.tpl-workflow .blk-flow-node.is-dec{padding:26px 40px}}
/* The connector, and its arrowhead. `gap:0` on the column means this element IS the spacing. */
.tpl-workflow .blk-flow-link{position:relative;width:2px;height:30px;background:var(--line);
display:flex;align-items:center}
.tpl-workflow .blk-flow-link::after{content:"";position:absolute;left:50%;bottom:-1px;
transform:translateX(-50%);border:6px solid transparent;border-top-color:var(--line);
border-bottom-width:0}
/* The branch label sits BESIDE the arrow, which is where a flow chart writes yes and no. */
.tpl-workflow .blk-flow-when{position:absolute;left:12px;white-space:nowrap;
font:700 10px/1.6 ui-monospace,Menlo,Consolas,monospace;letter-spacing:.1em;
text-transform:uppercase;color:var(--ink-3);background:var(--code);padding:0 6px}
@media(max-width:640px){.tpl-workflow .blk-flow-node.is-dec{max-width:100%}}
"""
