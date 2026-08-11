"""`roadmap` — what is planned and what is blocking (#13, wave 3; specs §4d).

First-read element: the stat strip plus a READ THIS FIRST stack of severity callouts.
The `.mstone` card markup predates #13 (it is #199's) and is kept: `.rm-epic` rides
alongside it rather than replacing it, so existing pages and their tests are unaffected.

#40 rebuilt the body against nsmith's `implementation-plan.html`. Measured, that
page is: a `.gantt` of `.gantt-row`s each pairing a `.gantt-label` with a proportional
`.gantt-track`/`.gantt-bar`; a `.diagram` whose `.node`s are joined by accented `.flow` paths; and
a risk list whose rows carry a `.sev` pill coloured by level. Mapping: `timeline` → the phase
rail, `nodes flow` → the data-flow figure, `findings` → the risk table.

NOT adopted, stated accurately — an earlier version of this paragraph got the reason wrong twice
and review caught both:

* The reference's gantt is NOT SVG. It is `<div class="gantt-bar" style="left:0%;width:33%">` —
  positioned divs with percentage left/width. What actually blocks reproducing it is DATA, not
  drawing: a proportional bar needs a start and a duration, and the `timeline` grammar is
  `time | title | detail | state`, with no field for either. So this rail is NOT weighted, and
  the earlier claim that it "gains the reference's phase weighting" was false — every marker here
  is the same fixed 4px x 22px bar. Real weighting means extending the grammar, which is a
  renderer change and not this PR.
* The data-flow diagram and its arrows ARE SVG. Our `nodes` is an indentation tree — wave 2
  replaced pipe-encoded depth because the pipes were unreadable (`typed-blocks-grammar.md`) and
  #13 restored the edge as an optional THIRD field. The tree keeps its shape; only the framing
  and the edge weight come from the reference.

`findings` and `nodes` were added to `DOC_TYPE_TAGS["roadmap"]`, and §4d reconciled to match, on
the authority of issue #40's owner-confirmed mapping table (2026-08-02), which names a risk table
and a data-flow figure for `roadmap`.

Emitted classes were read off a real render before this stylesheet was written, not guessed:
`findings` gives `.blk-finding.is-<level>` > `.blk-sev`/`.blk-title`/`.blk-text`/`.blk-prov`, and
`nodes` gives nested `ul > li.blk-node` > `.blk-edge`/`.blk-label`/`.blk-text`. The role key is
`nodes:flow` — a bare `nodes` key does NOT match a `nodes flow` fence, which warns and drops the
marker.

FIXED — **#119**, closed 2026-08-05. The paragraph below is kept in the past tense because the
next reader's real question is "has this been dealt with", and a deleted paragraph answers nothing.

**A page used to publish a status nobody wrote.** Verified through the real render path, before:

    ## Outlook

    Nothing has shipped yet.        ->  rendered  Outlook [SHIPPED]

The resolver word-matches completion vocabulary and returns the first hit. It recognised several
negators, but only within roughly the preceding two tokens, and `nothing` was missing from the
vocabulary entirely. Measured before the fix:

    "No work shipped."          -> —          (handled even then)
    "No work is done."          -> DONE       (negator out of reach)
    "Nothing shipped."          -> SHIPPED    (negator not in the vocabulary)
    "This is not yet merged."   -> —          (handled even then)

So it was two gaps, an incomplete vocabulary AND a reach limit — not, as an earlier draft of this
paragraph said, "leading quantifiers are unhandled": `no` was already recognised. #119 added
`nothing`/`none`/`neither` and widened the window from two words to six. All four rows above now
read `—`. `dashboard` shares `roadmap_status_chip` and was fixed by the same change; `analysis`'s
`confidence_chip` shares the scanner beneath it and was too.

ONE SHAPE IS STILL WRONG, and it is wrong in the safe direction: "There is no doubt the work is
done." reads `—` rather than DONE, because `no doubt` is an affirmation wearing a negator and its
distance from the keyword is identical to the real negation in "It is not true that the work is
done." No window can separate those two; only modelling negator SCOPE can. The chip therefore
under-claims there instead of asserting a status nobody wrote. See `_NEGATOR_REACH` in
`markdown.py` for the measurement behind the constant, and the named test in
`test_chip_negation.py` that keeps this visible.

WHAT WAS FIXED, so the next reader does not re-fix it — #90, in #112. The scanner no longer reads
FENCED blocks. Verified: a section headed "Risks" whose only "merged" is inside a ```` ```meter ````
fence now renders `Risks [—]`, where it used to render `Risks [MERGED]`. That fenced `meter` row
was this paragraph's original example, and it is out of date; the defect it illustrated is not.

History worth keeping: this paragraph said "(follow-up filed)" from #40 until 2026-08-02, when #68
PR 2 searched all 200 issues, open and closed, and found no such issue had ever been filed. #68's
`phases` block made the defect sharply easier to hit — a phase band exists to carry state words,
so any section holding one trips the scanner where before it took unlucky prose. `markdown.py` is
byte-unchanged here, so this predates the rebuild; the rebuilt body invites generic sections
(Phases, How it connects, Risks) where the old one assumed status-bearing epic cards.

The fix once proposed here — explicit heading/status metadata instead of prose scanning, a grammar
change — was considered and NOT taken. #112 changed the scanner instead. Do not read the paragraph
above as an outstanding request for a grammar change; #119 is scoped to the negation gap.

CASCADE NOTE (as in `design`/`report`): the template module is emitted BEFORE the shared optional
layer, so a rule here wins on specificity, never on order.
"""
NAME = "roadmap"

# #45: this style's own page frame — and the hole its own machine gate found.
#
# #68 rebuilt this body twice (the composition meter, then the phase bands) and never gave the
# PAGE a frame, so `roadmap` was still inheriting `plain`'s wholesale while carrying the epic's
# flagship devices. Nothing caught it: the byte oracle only proves a style MOVED, and every
# marker test only proves a class exists. #45's gate failed on it the first time it ran, which
# is the entire argument for having a machine gate at all.
#
# Derived from the approved visual spec (`docs/planning/2026-08-02-72-visual-spec.md`) and its
# frozen target `shots/target-roadmap-milestones.png` — the capture is the spec.
#
# 1120px: a roadmap carries phase bands with items nested inside them, so it needs more width
# than a findings list (`review`, 920) and less than a card wall (`dashboard`, 1240). It is the
# ninth distinct measure of the ten.
#
# The ground is a wash rather than the flat default, per spec rule 2 — "depth by ground, not
# shadow". Kept close to `--bg` because `ground` is the one owned slot the contrast gate cannot
# see (`frame.py` says so).
FRAME = {
    "ground": "radial-gradient(1000px 520px at 70% -8%,#17202c 0%,var(--bg) 58%)",
    "measure": "1120px",
    "gutter": "0 22px 72px",
    "header_pad": "36px 0 14px",
    "header_rule": "none",
    "header_gap": "20px",
    "h1_size": "clamp(26px,3.6vw,36px)",
    # Inert here — `roadmap` is sectioned, so its headings are re-emitted as `h3` (D70). Declared
    # because they are the honest values; `frame.owned_slots` correctly does not count them.
    "h2_size": "20px",
    "h2_rhythm": "2em 0 .6em",
}

SECTIONS = {"section_class": "mstone rm-epic", "chip_resolver": "status"}

MARKERS = {
    "timeline": "rm-timeline",
    "meter": "rm-meter",
    "chips": "rm-child",
    "findings": "rm-risk",
    "nodes:flow": "rm-flow",
    "phases": "rm-phase",
}

CSS = """
.tpl-roadmap .rm-epic{border-left-width:4px}
.tpl-roadmap .rm-meter{margin:10px 0 4px}
.tpl-roadmap .rm-meter .blk-track{height:8px}
.tpl-roadmap .rm-child{gap:5px}
.tpl-roadmap .rm-child .blk-chip{font-size:10.5px;padding:2px 8px}
/* Phase rail — what we take from the reference's `.gantt` is that a row is a PHASE, not a log
   entry: the marker is a short bar rather than a dot, and the phase name is the heavy element
   while the `when` shrinks to a label. It is NOT proportional — see the docstring; every bar is
   the same size, because the grammar carries no duration. */
.tpl-roadmap .rm-timeline{margin:18px 0;border-left-color:var(--line)}
.tpl-roadmap .rm-timeline .blk-tl{padding:10px 0}
.tpl-roadmap .rm-timeline .blk-tl::before{width:4px;height:22px;border-radius:2px;left:-19px;
top:12px;background:var(--line)}
.tpl-roadmap .rm-timeline .is-now::before{background:var(--accent)}
.tpl-roadmap .rm-timeline .is-past::before{background:var(--ink-3)}
.tpl-roadmap .rm-timeline .blk-when{font-size:10.5px;letter-spacing:.06em;text-transform:uppercase}
.tpl-roadmap .rm-timeline .blk-title{font-size:15.5px}
/* Risk table — the reference's `.sev` pill, coloured by level, ahead of the risk text so the
   column of pills is scannable on its own.
   Severity is NOT a closed set here, which is worth knowing before reading the four rules below.
   `_findings` calls `_token(value, "severity")` and `_SEMANTIC_SETS` has no "severity" entry, so
   ANY slug passes straight through — `blocker` yields `is-blocker`, and a blank field yields
   `is-note`. Neither warns. Executed, not assumed. The four rules colour the four levels the rest
   of the engine already uses (`review` styles the same set); anything else keeps the base pill
   shape with no fill, and the author's own word still renders inside it. Deliberate: an
   unrecognised severity should look unrecognised, not be silently recoloured. */
.tpl-roadmap .rm-risk{background:var(--surface);border:1px solid var(--line);border-radius:12px;
padding:4px 16px;margin:14px 0}
.tpl-roadmap .rm-risk .blk-finding{border-bottom:1px solid var(--line);padding:10px 0}
.tpl-roadmap .rm-risk .blk-finding:last-child{border-bottom:none}
.tpl-roadmap .rm-risk .blk-sev{display:inline-block;font:700 10px/1.6 ui-monospace,Menlo,
Consolas,monospace;letter-spacing:.06em;text-transform:uppercase;padding:2px 9px;
border-radius:999px;margin-right:8px}
.tpl-roadmap .rm-risk .is-critical .blk-sev{color:var(--sev-crit);background:var(--sev-crit-bg)}
.tpl-roadmap .rm-risk .is-high .blk-sev{color:var(--sev-high);background:var(--sev-high-bg)}
.tpl-roadmap .rm-risk .is-medium .blk-sev{color:var(--sev-med);background:var(--sev-med-bg)}
.tpl-roadmap .rm-risk .is-low .blk-sev{color:var(--sev-low);background:var(--sev-low-bg)}
/* Data-flow figure — the reference's `.diagram`: a framed figure whose nodes are boxes and
   whose edges are accented. The tree stays a tree; only the framing and the edge weight come
   from the reference. */
.tpl-roadmap .rm-flow{background:var(--code);border:1px solid var(--line);border-radius:12px;
padding:12px 16px;margin:16px 0}
.tpl-roadmap .rm-flow .blk-node{background:var(--bg)}
.tpl-roadmap .rm-flow .blk-edge{color:var(--accent);font:700 10.5px/1.6 ui-monospace,Menlo,
Consolas,monospace;letter-spacing:.05em}
.tpl-roadmap .rm-flow .blk-label{font-weight:650}
/* #68: the segmented composition meter — the signature device of the approved visual spec
   (docs/planning/2026-08-02-72-visual-spec.md §2). One segment per group, proportional to its
   count, coloured by STATE. The gap between segments is what makes it read as parts of a whole
   rather than one bar; a solid bar is what `meter` already is. */
.tpl-roadmap .blk-comp{margin:14px 0}
.tpl-roadmap .blk-comp-bar{display:flex;gap:5px}
.tpl-roadmap .blk-comp-seg{height:9px;border-radius:5px;background:var(--ink-3)}
.tpl-roadmap .blk-comp-seg.is-crit{background:var(--sev-crit)}
.tpl-roadmap .blk-comp-seg.is-warn{background:var(--sev-med)}
.tpl-roadmap .blk-comp-seg.is-ok{background:var(--chip-c)}
/* #166: the STATUS half of the phase vocabulary. Strictly additive — the three severity rules
   above keep their exact declarations, because every roadmap published so far is drawn with
   them and a repaint is not a fix. The groups are declared in `blocks.py`; this layer only
   says which colour each group takes, and `test_phase_state_vocabulary.py` fails when a
   declared token has no rule here. */
.tpl-roadmap .blk-comp-seg.is-done,.tpl-roadmap .blk-comp-seg.is-shipped,
.tpl-roadmap .blk-comp-seg.is-merged{background:var(--chip-c)}
.tpl-roadmap .blk-comp-seg.is-active,.tpl-roadmap .blk-comp-seg.is-wip,
.tpl-roadmap .blk-comp-seg.is-pending{background:var(--sev-med)}
.tpl-roadmap .blk-comp-seg.is-blocked,
.tpl-roadmap .blk-comp-seg.is-failed{background:var(--sev-crit)}
.tpl-roadmap .blk-comp-legend{display:flex;flex-wrap:wrap;gap:6px 20px;margin-top:9px;
font-size:10.5px;font-weight:700;letter-spacing:.11em;text-transform:uppercase;color:var(--ink-3)}
.tpl-roadmap .blk-comp-key{display:inline-flex;align-items:center;gap:7px}
.tpl-roadmap .blk-comp-key::before{content:"";width:8px;height:8px;border-radius:2px;
background:var(--ink-3)}
.tpl-roadmap .blk-comp-key.is-crit::before{background:var(--sev-crit)}
.tpl-roadmap .blk-comp-key.is-warn::before{background:var(--sev-med)}
.tpl-roadmap .blk-comp-key.is-ok::before{background:var(--chip-c)}
/* #68 PR 2: the phase band — the container the composition meter measures.
   Spec §2 "Tracks as first-class containers": a titled band with its own state badge, its own
   segmented bar, and its work items nested INSIDE it. Depth by ground, not shadow (spec rule 2):
   the band sits on `--surface` and its item strip sinks back to `--bg`, which is the two-ground
   version of the target's three. The ordinal is what makes the sequence visible — it is the
   "phases in order" the issue title asks for, and it is why the gutter is fixed-width and mono:
   `01` and `10` must line up or the column stops reading as a sequence. */
.tpl-roadmap .rm-phase{margin:18px 0;display:flex;flex-direction:column;gap:14px}
.tpl-roadmap .blk-ph{background:var(--surface);border:1px solid var(--line);
border-radius:12px;padding:14px 16px;border-left:4px solid var(--ink-3)}
.tpl-roadmap .blk-ph.is-crit{border-left-color:var(--sev-crit)}
.tpl-roadmap .blk-ph.is-warn{border-left-color:var(--sev-med)}
.tpl-roadmap .blk-ph.is-ok{border-left-color:var(--chip-c)}
.tpl-roadmap .blk-ph.is-done,.tpl-roadmap .blk-ph.is-shipped,
.tpl-roadmap .blk-ph.is-merged{border-left-color:var(--chip-c)}
.tpl-roadmap .blk-ph.is-active,.tpl-roadmap .blk-ph.is-wip,
.tpl-roadmap .blk-ph.is-pending{border-left-color:var(--sev-med)}
.tpl-roadmap .blk-ph.is-blocked,
.tpl-roadmap .blk-ph.is-failed{border-left-color:var(--sev-crit)}
.tpl-roadmap .blk-ph-head{display:flex;align-items:baseline;gap:12px}
.tpl-roadmap .blk-ph-ord{flex:none;width:26px;font:700 13px/1.4 ui-monospace,Menlo,
Consolas,monospace;color:var(--ink-3);font-variant-numeric:tabular-nums}
.tpl-roadmap .blk-ph-title{flex:1;font-size:15.5px;font-weight:700}
.tpl-roadmap .blk-ph-badge{flex:0 1 auto;min-width:0;max-width:100%;white-space:normal;overflow-wrap:anywhere;font:700 10px/1.6 ui-monospace,Menlo,Consolas,monospace;
letter-spacing:.11em;text-transform:uppercase;padding:2px 9px;border-radius:6px;
color:var(--ink-3);border:1px solid var(--line)}
.tpl-roadmap .blk-ph-badge.is-crit{color:var(--sev-crit);background:var(--sev-crit-bg);
border-color:transparent}
.tpl-roadmap .blk-ph-badge.is-warn{color:var(--sev-med);background:var(--sev-med-bg);
border-color:transparent}
.tpl-roadmap .blk-ph-badge.is-ok{color:var(--chip-c);background:var(--sev-low-bg);
border-color:transparent}
.tpl-roadmap .blk-ph-badge.is-done,.tpl-roadmap .blk-ph-badge.is-shipped,
.tpl-roadmap .blk-ph-badge.is-merged{color:var(--chip-c);background:var(--sev-low-bg);
border-color:transparent}
.tpl-roadmap .blk-ph-badge.is-active,.tpl-roadmap .blk-ph-badge.is-wip,
.tpl-roadmap .blk-ph-badge.is-pending{color:var(--sev-med);background:var(--sev-med-bg);
border-color:transparent}
.tpl-roadmap .blk-ph-badge.is-blocked,
.tpl-roadmap .blk-ph-badge.is-failed{color:var(--sev-crit);background:var(--sev-crit-bg);
border-color:transparent}
/* One segment per ITEM, so the bar is a picture of the list beneath it. Equal widths (spec §2)
   — `flex:1` rather than an inline percentage, so the renderer does no arithmetic and the
   segments cannot drift out of step with the rows they stand for. */
.tpl-roadmap .blk-ph > .blk-comp-bar{margin:11px 0 0}
.tpl-roadmap .blk-ph .blk-comp-seg{flex:1}
.tpl-roadmap .blk-ph-items{margin-top:11px}
.tpl-roadmap .blk-ph-items:empty{display:none}
/* 38px = the ordinal's 26px plus the head's 12px gap, so an item's id starts exactly under
   its phase's title. At 26px they were three-quarters aligned, which reads as a mistake
   rather than as a level of hierarchy — found by looking, not by a test. */
.tpl-roadmap .blk-ph-item{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;
padding:8px 0 8px 38px;border-top:1px solid var(--line)}
.tpl-roadmap .blk-ph-id{font:700 11.5px/1.6 ui-monospace,Menlo,Consolas,monospace;
color:var(--ink-2);border-bottom:2px solid var(--line);padding-bottom:1px}
.tpl-roadmap .blk-ph-item.is-crit .blk-ph-id{color:var(--sev-crit);
border-bottom-color:var(--sev-crit)}
/* The id accent marks TROUBLE only, which is why it is not the whole vocabulary: if every state
   coloured the id, none of them would stand out. `blocked` and `failed` join `crit` because they
   are the same group (`_PHASE_STATE_STUCK`), and the guard pins that the group and these rules
   name the same three words. Written as its own rule rather than appended to the selector list
   above, so the `is-crit` line stays byte-for-byte what shipped. */
.tpl-roadmap .blk-ph-item.is-blocked .blk-ph-id,
.tpl-roadmap .blk-ph-item.is-failed .blk-ph-id{color:var(--sev-crit);
border-bottom-color:var(--sev-crit)}
.tpl-roadmap .blk-ph-chip{font:700 9.5px/1.7 ui-monospace,Menlo,Consolas,monospace;
letter-spacing:.11em;text-transform:uppercase;padding:1px 7px;border-radius:6px;
color:var(--ink-3);background:var(--code)}
.tpl-roadmap .blk-ph-chip.is-crit{color:var(--sev-crit);background:var(--sev-crit-bg)}
.tpl-roadmap .blk-ph-chip.is-warn{color:var(--sev-med);background:var(--sev-med-bg)}
.tpl-roadmap .blk-ph-chip.is-ok{color:var(--chip-c);background:var(--sev-low-bg)}
/* The reported defect: DONE rendered grey because nothing matched `.is-done`. These take the
   SAME declarations as `.is-ok` above rather than a new green, so a page that says DONE and a
   page that says OK do not become two different-looking claims about the same thing. Measured
   AA on both: 7.54 dark, 4.82 light. */
.tpl-roadmap .blk-ph-chip.is-done,.tpl-roadmap .blk-ph-chip.is-shipped,
.tpl-roadmap .blk-ph-chip.is-merged{color:var(--chip-c);background:var(--sev-low-bg)}
.tpl-roadmap .blk-ph-chip.is-active,.tpl-roadmap .blk-ph-chip.is-wip,
.tpl-roadmap .blk-ph-chip.is-pending{color:var(--sev-med);background:var(--sev-med-bg)}
.tpl-roadmap .blk-ph-chip.is-blocked,
.tpl-roadmap .blk-ph-chip.is-failed{color:var(--sev-crit);background:var(--sev-crit-bg)}
.tpl-roadmap .blk-ph-text{flex:1 1 240px;color:var(--ink-2);font-size:14px}
"""
