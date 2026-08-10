"""`design` — a proposal to change something (#13, wave 3; specs §4d).

First-read element: `.dz-lead`, the lede naming the single change that makes the proposal
work. Replaces the one-rule heading underline that was the entire `design` template
before this wave — the defect the epic was opened for.

#40 rebuilt the body against nsmith's `code-approaches.html`. Measured, that page
is: `.approach` cards stacked FULL WIDTH — not a row of tiles — each with a big mono
`.approach-num`, a title, and a two-column `.pc` grid of tinted pros/cons panels; then a
`.recommend` verdict band with an accent border and a gradient wash. No new marker was needed:
`options`, `nodes` and `callout` are all already accepted by this doc type, and all three
already had slots.

CASCADE NOTE. The template module is emitted BEFORE the shared optional layer
(`render/__init__.py`), so a rule here does NOT beat a shared rule by being later — it has to
win on specificity. `.tpl-design .dz-options .blk-opt` (0,3,0) beats `.blk-options .blk-opt`
(0,2,0). This bit once already: the card border rule silently killed the shared
`.blk-options .is-chosen` accent border (0,2,0) until it was restated at (0,4,0).
"""
NAME = "design"

# #76: this style's own page frame. Measured off nsmith's `code-approaches.html`
# by reading its `<style>` block (D66):
#
#   body   radial-gradient(1200px 600px at 50% -10%, rgba(124,156,255,.10), transparent 60%)
#   .wrap  max-width:1080px; padding:clamp(1.5rem,4vw,3.5rem) clamp(1rem,4vw,2rem) 4rem
#   h1     clamp(1.6rem,3.4vw,2.5rem); line-height:1.2; letter-spacing:-.02em
#   h2     1.3rem
#
# 1080px is the WIDEST of the seven rebuilt here, and it is the opposite call to `report`'s 820.
# A design doc exists to put options beside each other; `_options` renders a title with its for
# and against, and at 900px those columns crush. Width is the argument.
#
# **This is the one style whose `h2` slots actually do something.** `design` is UNSECTIONED — it
# takes only `preamble_class`, so `render_sections` leaves its authored `##` headings alone at
# their own level (the docstring below records why: sectioning demoted them to h3 and killed the
# accent rule). Every other rebuilt style re-emits section headings as `h3`, which makes those two
# slots inert there — D70.
FRAME = {
    "ground": ("radial-gradient(1200px 600px at 50% -10%,rgba(124,156,255,.10),transparent 60%),"
               "var(--bg)"),
    "measure": "1080px",
    "gutter": "0 clamp(16px,4vw,32px) 64px",
    "header_pad": "clamp(24px,4vw,56px) 0 12px",
    "header_rule": "none",
    "header_gap": "18px",
    "h1_size": "clamp(26px,3.4vw,40px)",
    "h2_size": "20.8px",
    "h2_rhythm": "1.9em 0 .6em",
}

SECTIONS = {"preamble_class": "dz-lead"}

MARKERS = {
    "options": "dz-options",
    "nodes:compare": "dz-compare",
    "callout:decision": "dz-decision",
}

CSS = """
/* #76 — the frame's companions only. Two rules, deliberately few.
   An earlier draft of this PR also added a two-column `.dz-options` grid "so the wide measure
   pays for itself". Both wrong: the grid was DEAD (the `.dz-options` rule further down sets
   `display:block` at equal specificity and later source order), and it contradicted a decision
   this file already records — cards stack FULL WIDTH because "a trade-off you have to READ is
   not a 220px tile". The width pays for itself inside each card, where the for/against grid is
   two columns and needs the room. Deleted rather than reconciled. */
.tpl-design h1{line-height:1.2;max-width:22ch}
.tpl-design header .eyebrow{font-size:11px;letter-spacing:.14em}
.tpl-design .dz-lead{background:var(--surface);border:1px solid var(--line);
border-left:4px solid var(--accent);border-radius:12px;padding:4px 20px 14px;margin:6px 0 26px}
.tpl-design .dz-lead>p:first-child{font-size:17.5px;line-height:1.55;color:var(--ink);font-weight:550}
/* Option cards. Stacked full-width, because a trade-off you have to READ is not a 220px tile;
   the shared layer's flex row is overridden here at higher specificity. */
.tpl-design .dz-options{margin:22px 0;display:block;counter-reset:dz-opt}
.tpl-design .dz-options .blk-opt{counter-increment:dz-opt;display:grid;gap:10px 14px;
grid-template-columns:1fr 1fr;grid-template-areas:"head head" "pro con";
background:var(--surface);border:1px solid var(--line);border-radius:14px;
padding:16px 18px;margin:0 0 16px;flex:none}
.tpl-design .dz-options .blk-opt>.blk-title{grid-area:head;display:flex;gap:12px;
align-items:baseline;font-size:19px;letter-spacing:-.01em;margin:0}
.tpl-design .dz-options .blk-opt>.blk-title::before{content:counter(dz-opt,decimal-leading-zero);
font:700 22px/1.1 ui-monospace,Menlo,Consolas,monospace;color:var(--accent);flex:none}
.tpl-design .dz-options .blk-for{grid-area:pro;background:var(--req-c-bg);
border:1px solid var(--line);border-radius:10px;padding:9px 12px;font-size:13.5px}
.tpl-design .dz-options .blk-against{grid-area:con;background:var(--sev-high-bg);
border:1px solid var(--line);border-radius:10px;padding:9px 12px;font-size:13.5px}
/* #134 SETTLED THE FOLLOW-UP THIS COMMENT USED TO NAME. It said these labels were CSS-generated
   content, so not dependable semantic markup, that the reference uses real DOM text
   (`<h4>Pros</h4>`), and that making it semantic "means changing the renderer, which moves every
   style's bytes and so cannot ride in a per-template PR". That is exactly what #134 did: `_options`
   now emits a real `.blk-lbl` element, every rich style's bytes moved, and `plain` did not.
   So this is no longer a `::before` at all — it RESTYLES the markup label the renderer emits.
   Only the typography is set here; the colours come from the shared layer, which reaches this
   template because the wrapper carries both `blk-options` and `dz-options`. `text-transform`
   keeps the visible form FOR/AGAINST while the accessible name stays the emitted "For"/"Against".
   The space the renderer emits after the label collapses harmlessly against a block. */
.tpl-design .dz-options .blk-lbl{display:block;font:700 10px/1.6
ui-monospace,Menlo,Consolas,monospace;letter-spacing:.07em;text-transform:uppercase}
/* Restated at (0,4,0): the card rule above is (0,3,0) and was silently beating the shared
   `.blk-options .is-chosen` (0,2,0), so the chosen card lost its accent border. Measured. */
.tpl-design .dz-options .blk-opt.is-chosen{border-color:var(--accent);border-width:2px}
.tpl-design .dz-options .blk-opt.is-rejected{opacity:.72}
.tpl-design .dz-options .is-chosen>.blk-title::after{content:"CHOSEN";font:700 10px/1.6
ui-monospace,Menlo,Consolas,monospace;letter-spacing:.07em;color:var(--accent);
border:1px solid var(--accent);border-radius:999px;padding:1px 8px;margin-left:auto;flex:none}
@media(max-width:640px){.tpl-design .dz-options .blk-opt{grid-template-columns:1fr;
grid-template-areas:"head" "pro" "con"}}
/* A today/proposed pair is TWO ROOTS in one `nodes compare` block, so the
   grid goes on the top-level list. Two separate fences cannot pair — each is
   its own wrapper with a single child. */
@media(min-width:720px){.tpl-design .dz-compare>ul{grid-template-columns:1fr 1fr}}
.tpl-design .dz-compare{background:var(--code);border-radius:12px;padding:10px 14px}
/* The verdict band — `.recommend` in the reference. A gradient wash rather than a flat fill, so
   the decision reads as the page's conclusion and not as one more callout. */
.tpl-design .dz-decision{margin:24px 0 8px}
.tpl-design .dz-decision>.blk-callout{border:1px solid var(--accent);border-left-width:1px;
border-radius:14px;padding:16px 18px;
background:linear-gradient(180deg,var(--accent-soft),transparent)}
.tpl-design .dz-decision>.blk-callout>.blk-title::before{content:"DECISION";display:block;
font:700 10px/1.6 ui-monospace,Menlo,Consolas,monospace;letter-spacing:.07em;color:var(--accent)}
/* Trade-off table. Styled, deliberately NOT markered: a markdown table emits a bare <table> with
   no hook, and `section_class` is not a table marker — using it would flip `design` into
   sectioned rendering and demote its h2s. */
.tpl-design table{border-collapse:collapse;width:100%;margin:14px 0}
.tpl-design thead th{font:700 11px/1.6 ui-monospace,Menlo,Consolas,monospace;
letter-spacing:.06em;text-transform:uppercase;color:var(--accent);
border-bottom:2px solid var(--accent);text-align:left;padding:6px 10px}
.tpl-design tbody td{padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}
.tpl-design tbody tr:nth-child(even){background:var(--code)}
.tpl-design h2{border-bottom:2px solid var(--accent);padding-bottom:.15em}
"""
