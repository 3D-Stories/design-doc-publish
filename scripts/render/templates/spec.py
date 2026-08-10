"""`spec` — what must be true (#13, wave 3; specs §4d).

First-read element: the requirement count and gate state. `.sp-req` sits on a `steps`
block, NOT on an h2 section: §4d asks for requirement ROWS carrying a stable ID and a
MUST/SHOULD chip, and `steps` is already `id | title | text` — a row with an ID. An h2
wrapper would have been neither. Keeps `_decorate_requirements` for the RFC-2119 badges.

#40 rebuilt the body against `references/nsmith-html/feature-explainer.html`. Re-opened and
measured while writing this, with the extraction cross-checked against the raw file. That page
carries an `<aside class="toc"><nav aria-label="On this page">` index, three `.card`s, and SEVEN
`<details>`: four step disclosures and three `class="faq"`, each with a `<summary>` and a
`.detail-body`. (Seven, not eight — an earlier count matched the literal `<details>` inside the
HTML COMMENT on line 312. Counting tags with a regex over un-stripped markup is the same mistake
that bit the `analysis` table test; strip comments first.) **All three FAQ items are CLOSED**; the
single `open` attribute in the file is on the first STEP disclosure, not on a FAQ.

**This PR adds NO new accepted tag.** Every component it delivers rides a grammar `spec` already
accepted, which is worth stating because the design that reached here assumed `steprail` was
needed. Checked, and it is not — see the deferral below.

* **On-this-page index** — `sp-index`, and it needs no block at all. `index_class` is an existing
  parameter of the shared section renderer (`markdown.py`): given one, it emits
  `<nav class="…"><ol>` of links to every h2, and stamps the matching `id="sN"` on each section.
  `analysis` already uses it as `an-index`. `spec` was sectioned but never asked for one.
* **Requirement cards** — `sp-req` already existed as a left-rule gutter on a `steps req` block;
  this restyles it into the reference's `.card`. No grammar change.
* **MUST/SHOULD treatment** — already shipped: `_decorate_requirements` badges the RFC-2119 verb
  and `steps` carries the optional level as its fourth field (D9), whose CSS lives in the shared
  `OPTIONAL_BLOCK_CSS["steps:level"]` layer. This template only had to style it in context.

DEFERRED, and it is an owner-named component, so it is called out rather than buried:
**the collapsible detail is NOT delivered.** The reference's `.faq` items are INDEPENDENT and
CLOSED `<details>` — measured, none carries a `name` attribute and none is `open`. The only
grammar in this engine that emits `<details>` is `steprail`, and it cannot express that
combination. Stated precisely, because an earlier version of this paragraph got the mechanism
wrong and review caught it:

1. It groups every step in a fence under one `name` (`rail-0`, `rail-1`, … one per FENCE), so
   steps in a fence are mutually EXCLUSIVE — opening one closes the rest. The reference's FAQ
   items open independently.
2. Its first row is emitted `open`. That is the INITIAL state only — clicking the summary closes
   it, verified in headless Chrome — so a one-row fence is genuinely collapsible. The earlier
   claim that it was "permanently expanded" was false. What one-row fences cannot give you is a
   set that starts CLOSED: each fence's single row is always initially open.

So the missing capability is precise: **independent, closed-by-default disclosure.** Neither
shape reaches it — separate one-row fences are independent but all start open, and one multi-row
fence starts all-but-one closed but enforces exclusivity.

An independent-disclosure block is a GRAMMAR addition, which is #39's territory rather than a
body rebuild whose gate is "only my style's bytes moved". **Filed as #57** — which records the gap
and the four decisions a fix must make — rather than faked with the wrong mechanism, and rather
than silently dropped. (#57 was corrected after review carried the same false "permanently
expanded" wording.)
"""
NAME = "spec"

# #69: a specification is read start to finish, so it takes the opposite frame to `uat`'s board
# — a narrow measure near the 65-character reading optimum, a heavy masthead that reads as a
# title page, and an airier gap between sections so clauses do not run together.
# #76 completes this frame — `spec` was the second of the two styles #69 left partial (it had
# seven slots; `ground` and `header_rule` were missing).
#
# Measured off `references/nsmith-html/feature-explainer.html` by reading its `<style>` (D66):
# `.wrap max-width:1080px; padding:3rem 1.25rem 5rem; display:grid`, `h1 clamp(1.9rem,4vw,2.7rem)`.
#
# **The measure DEPARTS from the reference, deliberately: 760px, not 1080px** — the same kind of
# stated departure `dashboard` takes (D72), and the spec's checklist allows it. A spec is read one
# requirement at a time and each is a short normative sentence; 760 is the narrowest of the ten and
# that is the point. 1080 would also collide with `design`, which is 1080 because it puts options
# side by side — the opposite need.
#
# What IS taken from the reference is its `.step-num`: a numbered marker that reads as an ordinal
# rather than as prose. That suits a requirement list, and it is visually distinct from `review`'s
# right-aligned severity gutter (D73), which is the other numbered-looking style.
FRAME = {
    "ground": "var(--bg)",
    "header_rule": "1px solid var(--line)",
    "measure": "760px",
    "gutter": "0 20px 88px",
    "header_pad": "60px 0 22px",
    "header_gap": "28px",
    "h1_size": "clamp(21px,3vw,27px)",
    "h2_size": "17px",
    "h2_rhythm": "2.2em 0 .5em",
}

SECTIONS = {"section_class": "sp-section", "index_class": "sp-index"}

MARKERS = {
    "steps:req": "sp-req",
    "steps:ac": "sp-ac",
    "chips:gate": "sp-gate",
}

CSS = """
/* #76 — the reference's `.step-num`: the requirement id reads as an INDEX into a normative
   list, not as prose. `review`'s gutter (D73) is right-aligned severity text, so the two
   numbered-looking styles do not converge.

   THE TRACK WIDTH IS NOT TOUCHED, and that is deliberate. A first attempt set
   `grid-template-columns:34px 1fr` here and broke a measured decision this template already
   carries: the id and the RFC-2119 level pill SHARE column one, and #40 T7 fixed it at a
   >=90px track because `auto` sized it by the level WORD (44px MUST, 60px SHOULD, 36px MAY) so
   every card's title began at a different x. `test_requirement_cards_share_one_gutter_width…`
   caught the regression immediately — the guard did its job. Only the numeral is styled here;
   the gutter that holds it is left exactly as it was. */
.tpl-spec .sp-req .blk-n,.tpl-spec .sp-ac .blk-n{display:inline-flex;align-items:center;
justify-content:center;min-width:26px;padding:2px 7px;border:1px solid var(--line);
border-radius:8px;background:var(--bg);font:700 11px/1.4 ui-monospace,Menlo,Consolas,monospace;
color:var(--accent)}
.tpl-spec h1{line-height:1.15;max-width:22ch}
.tpl-spec header .eyebrow{display:inline-block;font-size:11.5px;letter-spacing:.13em;
border:1px solid var(--line);border-radius:999px;padding:4px 12px;background:var(--surface)}

.tpl-spec .sp-section{margin-top:24px}
/* On-this-page index — the reference's `.toc` aside. Emitted by the shared section renderer
   from `index_class`; nothing here parses headings. */
.tpl-spec .sp-index{background:var(--surface);border:1px solid var(--line);border-radius:12px;
padding:10px 18px;margin:18px 0}
.tpl-spec .sp-index ol{margin:.2em 0;padding-left:1.2em}
.tpl-spec .sp-index li{margin:.25em 0}
.tpl-spec .sp-index a{color:var(--ink-2);text-decoration:none;
border-bottom:1px solid var(--line)}
.tpl-spec .sp-index a:hover{color:var(--accent);border-bottom-color:var(--accent)}
/* Requirement cards — the reference's `.card`: a panel per requirement with the stable ID as a
   mono index, rather than the bare left rule this was before. The RFC-2119 badge and the
   optional MUST/SHOULD level come from the shared layer; only the frame is new. */
.tpl-spec .sp-req{margin:18px 0}
/* The grid goes on the `<ol>`, not on `.sp-req`. `.sp-req` has exactly ONE child — the list — so
   gridding it spaced nothing; the cards are the `<li>`s inside. Review caught the no-op. */
.tpl-spec .sp-req ol{display:grid;gap:10px;margin:0;padding:0}
.tpl-spec .sp-req .blk-step{background:var(--surface);border:1px solid var(--line);
border-left:3px solid var(--accent);border-radius:10px;padding:12px 16px;margin:0;
grid-template-columns:92px 1fr}
/* The gutter is a FIXED width, not `auto`. The ID and the RFC-2119 level pill share column one,
   and the pill's width follows its word — so on `auto` the column measured 44px for MUST, 60px
   for SHOULD and 36px for MAY, and every card's title started at a different x. Browser-measured
   across a five-level probe, not guessed.
   92px, not 64px: the accepted set is must / must-not / should / should-not / may
   (`_SEMANTIC_SETS["requirement level"]`), and the two hyphenated ones measure 72.1px and 88.6px
   — both of which the first attempt's 64px track wrapped. Review measured them.
   An UNRECOGNISED level is deliberately not dropped — `_semantic` warns and still renders the
   author's text — so the pill is additionally constrained rather than trusted to fit: a long one
   wraps inside the gutter instead of overlapping the title, which is what it did before. */
.tpl-spec .sp-req .blk-level{justify-self:start;max-width:100%;overflow-wrap:anywhere}
.tpl-spec .sp-req .blk-n{color:var(--accent);font-weight:700;
font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;letter-spacing:.04em}
.tpl-spec .sp-req .blk-title{font-size:15px}
.tpl-spec .sp-ac .blk-step{border-bottom-style:dashed}
.tpl-spec .sp-ac .blk-n{color:var(--ink-3)}
.tpl-spec .sp-gate .blk-chip{border-radius:5px;font:10.5px/1.4 ui-monospace,Menlo,Consolas,monospace}
.tpl-spec table th{color:var(--accent)}
.tpl-spec li{margin:.2em 0}
"""
