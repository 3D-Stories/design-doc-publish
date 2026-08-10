"""`slide-deck` — a document you present rather than read (#42, wave 5).

First-read element: the headline of the slide you are on. Nothing else on a slide competes with
it, which is what makes a deck a deck.

Measured off `references/nsmith-html/slide-deck.html` by reading its `<style>` block (D66):

    .slide  position:absolute; inset:clamp(16px,4vw,56px); max-width:1000px; max-height:640px
    h1      clamp(2.2rem,6vw,4rem); line-height:1.05; letter-spacing:-.02em
    h2      clamp(1.6rem,4vw,2.6rem); line-height:1.1
    devices .eyebrow, .stat/.num/.label, .lead, .progress

**THE ONE DEPARTURE, and it is forced.** The reference is a PAGINATED deck: slides are absolutely
positioned on top of each other and `.nav-btn` swaps them with script. This engine keeps its
inline-script exception to `uat` alone — `test_no_other_template_emits_a_script` pins it — so
pagination is not available here.

The script-free reading of the same design is **scroll-snap**: each section is a full-viewport
panel, and the browser snaps to one at a time. A reader still gets one slide at a time, still
advances with one gesture, and the page still works with JavaScript off, printing as a stack of
panels. What is lost is the arrow-key nav and the progress read-out, both of which need state.
That is stated rather than quietly dropped, and it is why there is no `.progress` here.

The type scale is the signature: `h1` runs to 64px, the largest of any style by a wide margin,
because a slide's headline is read from across a room and everything else on the page defers to
it. `stats` becomes the num-over-label pair the reference uses for its figures.
"""
NAME = "slide-deck"

# #45's gate: declared from the start.
#
# 1040px is the twelfth distinct measure. A slide is wider than prose and shorter-lined than a
# dashboard: the reference caps its stage at 1000px and this adds a little for the gutter it
# does not have.
#
# The ground is a WASH, and here it earns itself rather than being decoration — a deck is looked
# at from a distance, and a flat field at that size reads as an empty wall. Kept close to `--bg`
# because `ground` is the one owned slot the contrast gate cannot see.
FRAME = {
    "ground": "radial-gradient(1200px 700px at 50% -20%,#1b2333 0%,var(--bg) 60%)",
    "measure": "1040px",
    "gutter": "0 clamp(16px,4vw,56px) 0",
    "header_pad": "clamp(28px,6vw,64px) 0 10px",
    "header_rule": "none",
    "header_gap": "10px",
    "h1_size": "clamp(35px,6vw,64px)",
    "h2_size": "clamp(26px,4vw,42px)",
    "h2_rhythm": "0 0 .3em",
}

SECTIONS = {"section_class": "sd-slide", "heading_tag": "h2"}

MARKERS = {
    "stats": "sd-figures",
    "callout:point": "sd-point",
    "chips": "sd-tags",
}

CSS = """
/* Scroll-snap, not pagination — see the docstring for why script is unavailable here. Each
   section is a viewport-tall panel and the browser snaps to one at a time, so a reader still
   gets one slide per gesture with no state to keep. */
.tpl-slide-deck .wrap{scroll-snap-type:y mandatory;height:100vh;overflow-y:auto}
.tpl-slide-deck .sd-slide{scroll-snap-align:start;min-height:88vh;display:flex;
flex-direction:column;justify-content:center;padding:4vh 0;
border-top:1px solid var(--line)}
.tpl-slide-deck .sd-slide:first-of-type{border-top:none}
/* The headline is the slide. Everything else defers to it — that is the whole design, and it is
   why this style's h1/h2 are the largest of the twelve by a wide margin. */
.tpl-slide-deck h1{line-height:1.05;letter-spacing:-.02em;max-width:16ch}
.tpl-slide-deck .sd-slide>h2{line-height:1.1;letter-spacing:-.01em;max-width:18ch;
color:var(--ink)}
.tpl-slide-deck .sd-slide p{font-size:clamp(15px,1.6vw,19px);line-height:1.55;
color:var(--ink-2);max-width:56ch}
.tpl-slide-deck header .eyebrow{font-size:11.5px;letter-spacing:.16em}
/* Figures: the reference's num-over-label pair, at a size that survives being projected. */
.tpl-slide-deck .sd-figures{display:flex;flex-wrap:wrap;gap:36px;margin:26px 0 0}
.tpl-slide-deck .sd-figures .blk-item{display:flex;flex-direction:column-reverse;gap:4px}
.tpl-slide-deck .sd-figures .blk-value{font-size:clamp(30px,4vw,52px);font-weight:700;
letter-spacing:-.02em;font-variant-numeric:tabular-nums;line-height:1}
.tpl-slide-deck .sd-figures .blk-label{font:700 10.5px/1.6 ui-monospace,Menlo,Consolas,monospace;
letter-spacing:.14em;text-transform:uppercase;color:var(--ink-3)}
.tpl-slide-deck .sd-figures .is-accent .blk-value{color:var(--accent)}
/* The one point a slide is allowed to make beyond its headline. */
.tpl-slide-deck .sd-point>.blk-callout{border:none;border-left:3px solid var(--accent);
background:transparent;padding:2px 0 2px 18px;font-size:clamp(16px,1.8vw,21px)}
.tpl-slide-deck .sd-tags{gap:8px;margin-top:22px}
/* Printing a deck should give one slide per sheet, not a 12-metre ribbon. */
@media print{.tpl-slide-deck .wrap{height:auto;overflow:visible}
.tpl-slide-deck .sd-slide{min-height:0;break-after:page}}
/* A reader who asked for less motion should not be snapped around. */
@media (prefers-reduced-motion:reduce){.tpl-slide-deck .wrap{scroll-snap-type:none}}
"""
