"""`design-system` — the page that documents a project's design language (#42, wave 5).

First-read element: the project's own accent, beside the neutrals it does NOT own.

**AC4, and how it is met without injecting anything.** The issue requires a real project's VDL
pack, "not hardcoded sample colours". Furniture is a trusted CONSTANT (`render/__init__.py:340`),
so it cannot carry a per-project value — but it does not have to. `vdl.css_layer` already defines
`--accent` (and `--bg` when the pack declares a tint) as custom properties on the page, in all four
theme blocks. A swatch painted `background:var(--accent)` therefore resolves to THAT project's
colour at render time: constant markup, live value, and two projects genuinely produce two
different pages. `test_design_system_template.py` asserts exactly that, against real packs.

**What the project actually owns is two tokens, and the page says so.** `vdl.py:22-25` — a pack
overrides `--accent` and optionally `--bg`. Everything else is a renderer-owned neutral. An
earlier revision of this design claimed six swatches were "the project's pack"; a design reviewer
measured it and it was false. So the swatches are split into two labelled groups, and the neutral
group is marked as shared. Overstating this is the exact defect G3 caught.

**Type scale: shown, not stated.** The specimens are real `h1`/`h2`/`h3` elements, so the shared
stylesheet paints them at their true sizes. Printing "19px" beside a heading would be a
transcription that goes stale the moment someone edits `_STYLE` — the second-source-of-truth
problem this whole style exists to avoid.

**Radii: shown AND named**, because after PR 0 they have real names. `CSS` is BUILT from
`tokens.RADII` rather than agreeing with it by coincidence — `_build_css()` reads the token data,
and a test patches that data and asserts the output follows. PR 0 shipped a guard that passed
while a token had quietly stopped driving anything; the same trap is closed here by construction.

**Spacing is declared absent.** Measured on `_STYLE`: twelve distinct pixel values, eight used
exactly once. That is not a scale, and `--space-18` would document nothing reusable. The page says
so in one line rather than inventing a vocabulary — establishing a real one means changing the
stylesheet's values, which moves `plain`'s bytes and is blocked by AC5.

No script: `uat` remains the only interactive template.
"""
from .. import tokens

NAME = "design-system"

# #45's gate requires every style to own a frame, and this one is new, so it declares one from
# the start rather than being caught later the way `roadmap` was.
#
# 1160px: this page is a specimen sheet — swatch groups, type specimens and a radius scale sit
# side by side, and they need room to be compared at a glance. It is the tenth distinct measure.
#
# **The ground is the flat default, DECLARED on purpose** (D82). A page whose whole subject is
# colour must not tint what it is showing: a wash behind a swatch changes the swatch. The gate
# asks that a ground be DECIDED, not that it differ, and this is precisely the case that rule
# was written for — naming the default because it is right, not because nobody looked.
FRAME = {
    "ground": "var(--bg)",
    "measure": "1160px",
    "gutter": "0 24px 72px",
    "header_pad": "38px 0 14px",
    "header_rule": "1px solid var(--line)",
    "header_gap": "22px",
    "h1_size": "clamp(25px,3.4vw,34px)",
    "h2_size": "18px",
    "h2_rhythm": "2.1em 0 .7em",
}

SECTIONS = {"section_class": "ds-section"}

MARKERS = {
    "legend:tokens": "ds-legend",
    "chips:status": "ds-status",
}

# Trusted CONSTANT furniture: no author text reaches it at any point, which is why the engine
# emits it unescaped. Every colour comes from a custom property, so nothing here is a literal.
BEFORE_BODY = (
    '<div class="ds-panel">'
    '<div class="ds-group">'
    '<div class="ds-grouphead">This project owns these</div>'
    '<div class="ds-swatch"><span class="ds-chip ds-accent"></span>'
    '<code>--accent</code><span class="ds-note">brand accent</span></div>'
    '<div class="ds-swatch"><span class="ds-chip ds-bg"></span>'
    '<code>--bg</code><span class="ds-note">page tint, when the pack declares one</span></div>'
    '</div>'
    '<div class="ds-group">'
    '<div class="ds-grouphead">Shared neutrals &mdash; the same in every project</div>'
    '<div class="ds-swatch"><span class="ds-chip ds-ink"></span><code>--ink</code></div>'
    '<div class="ds-swatch"><span class="ds-chip ds-surface"></span><code>--surface</code></div>'
    '<div class="ds-swatch"><span class="ds-chip ds-line"></span><code>--line</code></div>'
    '<div class="ds-swatch"><span class="ds-chip ds-code"></span><code>--code</code></div>'
    '</div>'
    '<div class="ds-scale">'
    '<div class="ds-grouphead">Type scale &mdash; rendered at its real sizes</div>'
    '<h1>Heading one</h1><h2>Heading two</h2><h3>Heading three</h3>'
    '<p>Body text, and <code>inline code</code>.</p>'
    '</div>'
    '<div class="ds-radii">'
    '<div class="ds-grouphead">Radius scale</div>'
    + "".join(
        f'<div class="ds-rad"><span class="ds-radbox ds-rad-{name}"></span>'
        f'<code>{name}</code><span class="ds-note">{value}</span></div>'
        for name, value in tokens.RADII.items()
    )
    + '</div>'
    '<p class="ds-gap">There is no named spacing scale yet: the stylesheet uses twelve distinct '
    'values, eight of them once. Naming those would document nothing reusable.</p>'
    '</div>'
)


def _build_css():
    """CSS built FROM the token data, so the page cannot disagree with the stylesheet.

    A test patches `tokens.RADII` and asserts the output follows. Returning a constant that
    merely happened to match would pass every value check while naming nothing — the vacuity
    PR 0's mutation run caught one layer down.
    """
    rad = "".join(
        f".tpl-design-system .ds-rad-{name}{{border-radius:{value}}}\n"
        for name, value in tokens.RADII.items()
    )
    return """
.tpl-design-system .ds-panel{margin:18px 0}
.tpl-design-system .ds-group{background:var(--surface);border:1px solid var(--line);
border-radius:12px;padding:12px 16px;margin:12px 0}
.tpl-design-system .ds-grouphead{color:var(--ink-3);font-size:11px;font-weight:700;
letter-spacing:.08em;text-transform:uppercase;margin-bottom:8px}
.tpl-design-system .ds-swatch{display:flex;align-items:center;gap:10px;margin:6px 0}
.tpl-design-system .ds-note{color:var(--ink-3);font-size:12.5px}
/* Every swatch reads a custom property. On a page rendered with a project's VDL pack the first
   two resolve to THAT project's colours; the rest are the renderer's neutrals in every project. */
.tpl-design-system .ds-chip{width:34px;height:20px;border-radius:5px;border:1px solid var(--line);
display:inline-block;flex:none}
.tpl-design-system .ds-accent{background:var(--accent)}
.tpl-design-system .ds-bg{background:var(--bg)}
.tpl-design-system .ds-ink{background:var(--ink)}
.tpl-design-system .ds-surface{background:var(--surface)}
.tpl-design-system .ds-line{background:var(--line)}
.tpl-design-system .ds-code{background:var(--code)}
/* The specimens are real headings, so the shared stylesheet sizes them. Nothing is transcribed. */
.tpl-design-system .ds-scale{background:var(--surface);border:1px solid var(--line);
border-radius:12px;padding:12px 16px;margin:12px 0}
.tpl-design-system .ds-scale h1,.tpl-design-system .ds-scale h2,
.tpl-design-system .ds-scale h3{margin:.25em 0}
.tpl-design-system .ds-radii{background:var(--surface);border:1px solid var(--line);
border-radius:12px;padding:12px 16px;margin:12px 0}
.tpl-design-system .ds-rad{display:flex;align-items:center;gap:10px;margin:6px 0}
/* Sized and filled so the CURVATURE is the thing you see. The first build used a 34x24
   box in `--code`, and 4px / 8px / 12px were indistinguishable on screen — the page that
   documents the radius scale could not show it. Correct CSS, useless page; found by
   looking at it, not by measuring it. A solid fill and a bigger box make the corner read. */
.tpl-design-system .ds-radbox{width:64px;height:44px;background:var(--accent);
display:inline-block;flex:none}
""" + rad + """.tpl-design-system .ds-gap{color:var(--ink-3);font-size:12.5px}
.tpl-design-system .ds-section{margin-top:24px}
.tpl-design-system .ds-legend .blk-legend{border-left:3px solid var(--accent)}
"""


CSS = _build_css()
