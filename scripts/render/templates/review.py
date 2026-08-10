"""`review` — findings, ranked (#13, wave 3; specs §4d).

First-read element: the verdict headline plus confirmed/refuted counts. Closes with
`.rv-weakest`, "The claim most likely to be wrong". Keeps `_decorate_severity`.

#40 rebuilt the body against nsmith's `annotated-pr.html`. Measured, the two
things that page has and we did not are:

* A `.riskmap` — a FLAT list of `.risk-row`s, one per changed file, sitting after the summary
  prose and before the file-level detail. It is the page's navigation aid: which parts of the
  artifact are worth opening.
* Review notes as CARDS, not gutter marks. Each `.note` is a panel with a severity-coloured
  3px left border and a head row carrying the pill, then the prose.

**Both are `findings`, and no new grammar or accepted tag was needed for either.** The two jobs
are told apart by a ROLE: `findings riskmap` → `.rv-riskmap`, bare `findings` → `.rv-sev`.
`render_block` looks up `tag:role` when a role is given and the bare `tag` otherwise, so the two
keys coexist in one marker map. `report` and `spec` use the same role-DISPATCH mechanism, but not
this map shape: their duplicated tags are role-qualified on both sides. Registry-scanned,
`review`'s `findings` is currently the only bare-plus-ROLE pair — a first rather than a
precedent, which is why a test pins it. Note the near-miss it must not be confused with: three
templates already pair a bare key with a DOT-qualified sub-slot (`report`'s `stats`/`stats.bar`,
`dashboard`'s `findings`/`findings.tail`, `workflow`'s `nodes`/`nodes.edge`). Those are internal
slots the renderer looks up itself, on parts of a block; a role is a word the AUTHOR writes on
the fence. Different mechanism, so not a precedent for this either.

**The risk row is an ADAPTATION of the reference's, not a field-for-field match.** The reference
row has THREE parts — `path`, one `.tag` whose text is the whole judgement ("needs attention"),
and `counts`. A `findings` row has four: `severity | title | text | provenance`. So this splits
the reference's single tag phrase into a tokenised severity pill plus a short reason of our own,
and the reason column is an addition the reference does not have. Mapping: path → `title`,
reason → `text`, severity → `sev`, counts → `provenance`.

An earlier version of this template mapped the risk map onto `nodes` and widened
`DOC_TYPE_TAGS["review"]` to accept it. Both pre-PR reviewers blocked that, and both were right:
the D18 justification rested on the risk map being "a labelled tree and not a flat list", which
the reference contradicts — its map is flat — and this very docstring contradicted it two
paragraphs later. `findings` also carries the counts field that `nodes` (three fields, warning on
a fourth) could not, and tokenises the severity that `nodes` renders as inert text. **So the
accept map is UNCHANGED by this PR** and D18 is not engaged at all: `findings` was already
accepted by `review`.

Emitted classes were read off a real render before this stylesheet was written, not guessed. A
risk row gives `.blk-finding.is-<level>` > `.blk-sev`/`.blk-title`/`.blk-text`/`.blk-prov`, in
that DOM order. The CSS below reorders them to path, reason, pill, counts — that is OUR reading
order, chosen to put the path first as the reference does, and `order` moves them VISUALLY only:
the emitted sequence stays severity, path, reason, counts, which is what a screen reader and a
text dump see. Semantic reordering would need renderer markup.

Behaviour worth knowing before writing a risk map, executed rather than assumed:

* **Severity is an OPEN set, and the pill's colour set is not closed either.** `_findings` calls
  `_token(value, "severity")` and `_SEMANTIC_SETS` has no "severity" entry, so any slug passes
  through. The colouring is a base rule plus three overrides, not a rule per level: `.blk-sev`
  itself carries the `--sev-low` treatment, and only `.is-critical`/`.is-high`/`.is-medium` have
  `>.blk-sev` overrides. So `low`, the reference's own `safe`, and any other valid slug all keep
  the base pill. Deliberate — an unrecognised severity keeps the author's word rather than being
  recoloured into a level it never claimed. (The CARD's left border is separate and is coloured
  for all four documented levels, `low` included; a test pins that.)
* **A row with fewer than three fields warns and degrades the WHOLE block to a code listing** —
  no marker, no card, nothing silently dropped. A three-field row renders normally, just without
  counts.
* **The locator sits under the prose, not beside the pill.** The reference's `.note-head` holds
  the tag and its `line 11` locator together above the paragraph; `_findings` emits `.blk-prov`
  last. CSS could co-locate it visually, exactly as the risk-map rules below reorder their spans
  — what needs a renderer change is a genuine `.note-head` WRAPPER, i.e. the semantic grouping,
  not the appearance. Left alone here rather than faked. The finding cards are otherwise a
  genuine adoption of the reference's panel, not a recolour.

CASCADE NOTE (as in `design`/`report`/`roadmap`), scoped to typed-block styling. A rich page's
stylesheet is assembled `_STYLE`, then `_COMPONENT_STYLE` + `BLOCK_CSS` (+ `_ROADMAP_STYLE` for
the two card templates), then THIS module, then whichever feature-keyed `OPTIONAL_BLOCK_CSS`
layers the page actually uses, then the per-project VDL token layer last
(`render/__init__.py`). Feature CSS is conditional, so it is not a layer every page carries. The
consequence relied on below: a rule here beats base `BLOCK_CSS` on BOTH specificity and source
order, and needs to win on specificity only against a later optional-feature rule.
"""
NAME = "review"

# #76: this style's own page frame. Measured off nsmith's `annotated-pr.html` by
# reading its `<style>` (D66): `.wrap max-width:920px; padding:32px 20px 80px`.
#
# 920px sits deliberately between `report`'s 820 and `design`'s 1080. A review is a findings list
# read top to bottom like a report, but each finding carries an evidence tail that a 820px column
# wraps badly.
#
# The reference is an ANNOTATED DIFF — 20 `.row`s each pairing a mono `.ln` line number with a
# `.gut` gutter and `.code`. What transfers is not the diff (we render no code) but its READING
# POSTURE: a fixed mono gutter down the left that the eye tracks, with the severity sitting in it.
# That is the device below, and it is why this style does not look like `report`, whose findings
# have no gutter at all.
#
# `h2_size`/`h2_rhythm` are inert here — `review` is sectioned, so headings become `h3` (D70).
FRAME = {
    "ground": "var(--bg)",
    "measure": "920px",
    "gutter": "0 20px 80px",
    "header_pad": "32px 0 12px",
    "header_rule": "1px solid var(--line)",
    "header_gap": "20px",
    "h1_size": "clamp(24px,3.6vw,33px)",
    "h2_size": "17px",
    "h2_rhythm": "2em 0 .7em",
}

SECTIONS = {"section_class": "rv-section"}

MARKERS = {
    "chips:hypo": "rv-hypo",
    "findings": "rv-sev",
    "callout:weakest": "rv-weakest",
    "findings:riskmap": "rv-riskmap",
}

CSS = """
/* #76 — the reference's reading posture, not its content. An annotated diff runs a fixed mono
   gutter down the left that the eye tracks line by line; a review is read the same way, one
   finding at a time. So each finding gets that gutter, with its severity sitting IN it rather
   than floating inline. This is what keeps `review` from looking like `report`, whose findings
   have no gutter. Targets `h3` — `review` is sectioned (D70). */
.tpl-review .rv-sev .blk-finding{display:grid;grid-template-columns:74px 1fr;gap:0 14px;
align-items:start;padding:11px 0;border-left:2px solid var(--line);padding-left:14px}
.tpl-review .rv-sev .blk-sev{grid-column:1;text-align:right;font-variant-numeric:tabular-nums}
.tpl-review .rv-sev .blk-title,
.tpl-review .rv-sev .blk-text,
.tpl-review .rv-sev .blk-prov{grid-column:2}
.tpl-review .rv-sev .is-critical{border-left-color:var(--sev-crit)}
.tpl-review .rv-sev .is-high{border-left-color:var(--sev-high)}
.tpl-review .rv-sev .is-medium{border-left-color:var(--sev-med)}
@media(max-width:640px){.tpl-review .rv-sev .blk-finding{grid-template-columns:1fr}
.tpl-review .rv-sev .blk-sev{text-align:left}}
.tpl-review h1{line-height:1.2;max-width:24ch}
.tpl-review header .eyebrow{font-size:11px;letter-spacing:.13em}

.tpl-review .rv-section{margin-top:26px}
.tpl-review .rv-hypo .blk-chip{background:none;border:1px solid var(--line);
padding:4px 10px;font-size:11px}
/* Finding cards — the reference's `.note`: a panel with a severity-coloured left border. The
   shared layer draws findings as rows separated by a bottom rule; the card's `border` shorthand
   is emitted later at equal specificity, so it replaces that separator outright and the
   last-child case needs no rule of its own. */
.tpl-review .rv-sev{display:grid;gap:12px;margin:18px 0}
.tpl-review .rv-sev .blk-finding{background:var(--surface);border:1px solid var(--line);
border-left:3px solid var(--line);border-radius:10px;padding:12px 16px}
.tpl-review .rv-sev .is-critical{border-left-color:var(--sev-crit)}
.tpl-review .rv-sev .is-high{border-left-color:var(--sev-high)}
.tpl-review .rv-sev .is-medium{border-left-color:var(--sev-med)}
.tpl-review .rv-sev .is-low{border-left-color:var(--sev-low)}
.tpl-review .rv-sev .blk-title{font-size:15px}
.tpl-review .rv-sev .blk-prov{margin-top:2px}
.tpl-review .rv-weakest>.blk-callout{border-left-color:var(--sev-crit);background:var(--sev-crit-bg)}
.tpl-review tbody tr:nth-child(even){background:var(--code)}
.tpl-review blockquote{border-left-color:var(--accent);color:var(--ink-2)}
/* Risk map — the reference's `.riskmap`: one row per part of the artifact, read before the
   file-level detail. Same `findings` grammar as the cards above, so the row must be flattened
   out of the shared two-column grid into a single line, and the four spans reordered from their
   DOM order (severity, path, reason, counts) to OUR reading order (path, reason, pill, counts),
   which leads with the path as the reference does. Visual only — see the docstring. The pill
   needs no colour rule here: the shared base `.blk-sev` plus its three `.is-<level>` overrides
   already cover it. */
.tpl-review .rv-riskmap{display:grid;gap:8px;margin:18px 0}
.tpl-review .rv-riskmap .blk-finding{display:flex;flex-wrap:wrap;align-items:center;
gap:6px 14px;background:var(--surface);border:1px solid var(--line);border-radius:10px;
padding:11px 15px}
.tpl-review .rv-riskmap .blk-title{order:1;flex:1 1 auto;font:550 13.5px/1.5 ui-monospace,Menlo,
Consolas,monospace;word-break:break-all}
.tpl-review .rv-riskmap .blk-text{order:2;flex:0 1 auto;grid-column:auto;color:var(--ink-3);
font-size:12.5px}
.tpl-review .rv-riskmap .blk-sev{order:3;flex:0 0 auto}
.tpl-review .rv-riskmap .blk-prov{order:4;flex:0 0 auto;grid-column:auto;margin:0}
"""
