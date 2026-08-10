"""`module-map` — what the parts are and how they depend on each other (#42, wave 5).

First-read element: the map itself. A module map is a graph, and the reader's first question is
always "what talks to what", never "what is the prose".

Measured off `references/nsmith-html/module-map.html` by reading its `<style>` block (D66) — that
file is one of the twelve vendored templates carrying a `<script>`, so it is read, not opened:

    .wrap  max-width:980px; padding:48px 24px 96px
    h1     clamp(28px,5vw,40px); line-height:1.15; letter-spacing:-.02em
    h2     21px; margin:36px 0 14px
    .card  linear-gradient(180deg, var(--panel) 0%, var(--panel-2) 100%)

**No new block type.** `nodes` is already an indentation tree whose optional third field is the
EDGE reaching a node from its parent — which is exactly a dependency arrow. #76 added `flow` for
`workflow` because a flow has ORDER and a tree does not; a module map genuinely IS a tree of
containment with labelled edges, so it needs the grammar that already exists. Adding a type here
would be the mistake `flow` avoided, made in reverse.

What the reference contributes is the TREATMENT: nodes as raised cards with a top-to-bottom
gradient, the edge label promoted to a badge on the connector, and a `hot` marker (8 uses on that
page) for the parts that matter most. `hot` maps to the accent; nothing else on the page competes
with it.
"""
NAME = "module-map"

# #45's gate: declared from the start.
#
# 980px is the eleventh distinct measure. A map is wider than prose because two sibling cards
# should sit side by side, and narrower than a dashboard because a graph read at a glance stops
# being readable past three columns.
#
# **The ground is the flat default, NAMED on purpose** (D82). The reference puts its depth in the
# cards — they carry a gradient — and a page that also washed would flatten them by competing.
FRAME = {
    "ground": "var(--bg)",
    "measure": "980px",
    "gutter": "0 24px 96px",
    "header_pad": "44px 0 12px",
    "header_rule": "none",
    "header_gap": "22px",
    "h1_size": "clamp(28px,5vw,40px)",
    "h2_size": "21px",
    "h2_rhythm": "36px 0 14px",
}

SECTIONS = {"section_class": "mm-section"}

MARKERS = {
    "nodes": "mm-map",
    "nodes.edge": "mm-edge",
    "legend": "mm-key",
    # A ROLE, not a bare tag: `hot` means "this is where the risk is", and a map may also
    # carry an ordinary chip row that should not be shouted. A bare `chips` marker accented
    # both — caught by rendering a page whose `chips hot` fence came out unmarked, because
    # the lookup key for a role is `chips:hot` and nothing answered it.
    "chips:hot": "mm-hot",
}

CSS = """
/* The map. Nodes are raised cards over a flat page — the reference puts its depth in the card
   gradient, so the page behind them stays plain or the two compete and both lose. */
.tpl-module-map .mm-map{background:var(--code);border:1px solid var(--line);
border-radius:14px;padding:18px 20px;margin:18px 0}
.tpl-module-map .mm-map .blk-node{background:linear-gradient(180deg,var(--surface) 0%,
var(--code) 100%);border:1px solid var(--line);border-radius:11px;padding:10px 14px}
.tpl-module-map .mm-map ul ul{margin-left:26px;padding-left:22px;
border-left:2px solid var(--line)}
/* Siblings sit side by side once there is room — that is what the 980px measure buys, and it is
   why a map is not a list. Below 760px it stacks, because a two-column graph on a phone is worse
   than a one-column one. */
@media(min-width:760px){.tpl-module-map .mm-map>ul>.blk-node>ul{display:grid;
grid-template-columns:1fr 1fr;gap:10px}}
/* The edge label is the dependency's NAME, so it is promoted out of the prose onto a badge —
   `imports`, `calls`, `reads` are the words a reader is scanning for. */
.tpl-module-map .mm-edge{display:inline-block;margin:0 0 4px;padding:1px 8px;border-radius:999px;
background:var(--code);border:1px solid var(--line);color:var(--ink-3);
font:700 9.5px/1.6 ui-monospace,Menlo,Consolas,monospace;letter-spacing:.1em;
text-transform:uppercase}
.tpl-module-map .mm-edge.is-proposed{border-style:dashed;color:var(--ink-3)}
/* `hot` — the reference's marker for the parts that carry the risk. Exactly one thing on a map
   should pull the eye, so this is the only accent-coloured element in the stylesheet. */
.tpl-module-map .mm-hot .blk-chip{color:var(--accent);border:1px solid var(--accent);
background:transparent}
.tpl-module-map .mm-key{background:var(--surface);border:1px solid var(--line);
border-radius:12px;padding:10px 16px}
.tpl-module-map h1{line-height:1.15;max-width:20ch}
.tpl-module-map header .eyebrow{font-size:11px;letter-spacing:.13em}
"""
