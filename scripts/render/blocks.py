"""Typed fenced blocks — a fence whose info string names a block type, not a language.

Filled in by wave 2 (#17); wave 3 (#13) added the stylesheet, the optional **role** word,
and three optional trailing fields. The grammar was authored by hand FIRST, in
`docs/typed-blocks-grammar.md`; that exercise changed three of these tags before a
line of this module existed, which is why it happened in that order.

#13 adds a second word to the info string — a **role** — because a doc type can use one
block twice for different jobs (a dashboard has both a sticky state bar and a verdict chip
row). The role selects which marker class the template hangs on the block. This module
never learns what those classes mean: it is handed a `markers` dict by the template and
looks names up in it. Nothing here imports a template.

THREE PROPERTIES THIS MODULE MUST KEEP:

* **An unknown tag warns and degrades to a code listing.** A typo in a fence must
  never cost the document. Same for a malformed row inside a known block.
* **Escape-first.** Bodies are author text: every cell is `html.escape`d before any
  component markup wraps it. Nothing here may emit an unescaped `<`.
* **No colours.** The author never writes one and neither does this module — it emits
  semantic class names only. That is what keeps a per-project visual design language
  enforceable rather than advisory.

Every block is line-oriented and pipe-delimited; blank lines are skipped. A trailing
`| accent` marks emphasis where a type supports it — the author names emphasis, never
a colour.
"""
import html
import math
import re
import sys

# The wave-2 tag set, fixed by #17.
BLOCK_TAGS = ("stats", "verdict", "chips", "callout", "legend", "meter",
              "findings", "steps", "nodes", "provenance",
              # #39, the component vocabulary waves 3-5 build against.
              "timeline", "options", "steprail",
              # #68: what a total is MADE OF, which a single-value meter cannot say.
              "composition",
              # #68 PR 2: ordered containers — the phase structure itself.
              "phases",
              # #76: a real flow chart for `workflow` — boxes and arrows, not an indented tree.
              "flow",
              # #57: independent, closed-by-default disclosures — the one shape `steprail` cannot
              # emit, because its whole point is one-open-at-a-time.
              "faq")

# Which doc types accept which blocks (AC3). A doc type absent from this map has no
# policy — that means "no opinion", never "reject everything".
# #13 aligned this map to specs §4d, which is the authority on what each type contains.
# Wave 2 wrote it before the template bodies existed and it had drifted in both
# directions — `review` rejected the `stats` block its own KPI strip is made of, and
# `roadmap` rejected the `callout` its READ THIS FIRST stack is made of, while `design`
# and `dashboard` accepted everything. Both defects showed up the first time a real page
# of each type was rendered, not by reading. Kept in sync with the component-set table in
# `docs/design-language.md` by `test_doc_type_tags_match_the_documented_sets`.
DOC_TYPE_TAGS = {
    "analysis": {"verdict", "chips", "callout", "steps", "provenance"},
    "roadmap": {"timeline", "stats", "callout", "legend", "meter", "chips", "findings",
                "composition", "phases",
                "nodes", "provenance"},
    "report": {"timeline", "stats", "verdict", "callout", "steps", "provenance"},
    "design": {"options", "verdict", "callout", "nodes", "chips", "provenance"},
    "dashboard": {"stats", "chips", "callout", "findings", "nodes", "provenance"},
    "review": {"stats", "findings", "callout", "chips", "provenance"},
    # #57 adds `faq`: the reference this type's body was built from carries three independent,
    # closed-by-default disclosures, and no block could produce that shape. `analysis` was
    # considered and DECLINED — it already builds a question/answer surface structurally in its
    # section renderer, so a `faq` block there would give one doc type two ways to say the same
    # thing.
    "spec": {"chips", "callout", "steps", "provenance", "faq"},
    "workflow": {"steprail", "nodes", "legend", "callout", "chips", "provenance", "flow"},
    # #18, wave 4. The only interactive type; specs §4d.
    "uat": {"steps", "callout", "chips", "meter"},
    # #42, wave 5. A specimen sheet: it SHOWS tokens rather than tabulating them, so it needs
    # almost no component vocabulary — a legend for the token groups and a status chip row.
    "design-system": {"legend", "callout", "chips", "provenance"},
    # #42: a map is a graph — `nodes` carries the topology and its edge labels.
    "module-map": {"nodes", "legend", "callout", "chips", "provenance"},
    # #42: a slide carries a headline, a figure or two and at most one point.
    "slide-deck": {"stats", "callout", "chips", "provenance"},
}

# #130. Which blocks a styled page must ACTUALLY CARRY — the devices its own style opens
# with, as distinct from `DOC_TYPE_TAGS`, which says only which blocks it may USE.
# `lint.check_style_devices` enforces this at publish time; `check_blocks` (#127) is the
# weaker floor beneath it, satisfied by one component of any kind.
#
# DERIVED, NEVER INVENTED. Every entry is read out of the **First-read element** column of
# the "## Doc types" table in `docs/design-language.md`, where each cell carries a literal
# `— **blocks:**` annotation. That column is the source of truth and this is its mirror:
# `TestFirstReadDeviceContract.test_first_read_devices_match_the_documented_column` parses
# the column and requires exact equality, so editing one without the other turns the suite
# red. #130's own Risk section says a per-style table that becomes a SECOND source of truth
# is the whole design risk — the pinning test is what contains it.
#
# An EMPTY set is a statement, not an accident: `plain` and `analysis` open with something
# the renderer builds (`plain`'s <h1>; `analysis`'s `.an-answer` opening paragraph), so an
# author cannot omit it and there is nothing to require. The doc spells those cells
# `none (structural)` and the parser accepts no other spelling — an empty requirement that
# arrived by a regex matching nothing would be a gate that can never fail.
FIRST_READ_DEVICES = {
    "plain": frozenset(),
    "analysis": frozenset(),
    "roadmap": frozenset({"stats", "callout", "phases"}),
    "report": frozenset({"callout", "stats", "timeline"}),
    "design": frozenset({"options"}),
    "dashboard": frozenset({"chips", "stats"}),
    "review": frozenset({"stats", "findings"}),
    "spec": frozenset({"steps", "chips"}),
    "uat": frozenset({"meter"}),
    "workflow": frozenset({"flow", "legend", "steprail"}),
    # #149. These three arrived with #42 and had no "## Doc types" row, so #130 left them
    # un-opinionated. Derived from what each template actually BUILDS (`templates.MARKERS`),
    # never invented: `design-system` marks a token legend and a status chip row,
    # `module-map` marks the map and its key, `slide-deck` marks its figures.
    #
    # `slide-deck` requires ONLY its figures, deliberately: the comment on its DOC_TYPE_TAGS
    # entry describes a slide as carrying "a headline, a figure or two and AT MOST ONE point",
    # and "at most one" makes the point optional — requiring its `callout` would contradict
    # the template's own description of itself.
    "design-system": frozenset({"legend", "chips"}),
    "module-map": frozenset({"nodes", "legend"}),
    "slide-deck": frozenset({"stats"}),
}

# Styles with NO row in the "## Doc types" table, so no documented first-read element to
# derive from. Absent means "no opinion" — the same convention `DOC_TYPE_TAGS` states above.
#
# EMPTY as of #149, which gave the last three (`design-system`, `module-map`, `slide-deck`)
# a documented row. Kept rather than deleted, because it is the declared home for the next
# template added without one: `test_every_template_is_classified_exactly_once` requires every
# style to appear here or in `FIRST_READ_DEVICES`, so the suite goes red until someone chooses.
UNDOCUMENTED_FIRST_READ: frozenset[str] = frozenset()

_ACCENT = "accent"

# A semantic token becomes part of a class attribute. Escaping stops quote breakout
# but NOT spaces, so `high is-accent` would inject a second class and activate any
# present-or-future stylesheet rule. Only a strict slug may reach a class.
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _token(value: str, field: str) -> str:
    """A validated semantic token, or `note` plus a warning. The original text is
    never discarded — callers still render it as visible escaped text."""
    v = value.strip().lower()
    if not v:
        return "note"
    if _SLUG.match(v):
        return v
    _warn(f"{field} {value!r} is not a semantic token (lowercase letters, digits and "
          f"single hyphens only) — using 'note'; the text still renders")
    return "note"


def accepts(doc_type: str) -> set:
    """Tags `doc_type` accepts. An unknown doc type accepts everything (no policy)."""
    return DOC_TYPE_TAGS.get(doc_type, set(BLOCK_TAGS))


def _warn(msg: str) -> None:
    print(f"render_artifact: WARNING {msg}", file=sys.stderr)


# A pipe is the delimiter, so a prose field cannot contain one — `must | Preserve A | B |
# Needed by callers` silently shifts every later field along and drops the last. `\|` is a
# literal pipe. The sentinel is \x01, deliberately NOT the \x00 that `_decorate_requirements`
# uses as its hard-break placeholder, so the two can never be confused.
_PIPE_SENTINEL = "\x01"


def split_cells(line: str) -> list:
    """Split a row on `|`, honouring `\\|` as a literal pipe.

    ONE implementation, used by both `_validate` (which COUNTS fields) and `_rows` (which
    RENDERS them). Two splitters is exactly how a field count and its rendering drift apart:
    a row would validate as three fields and then render into four columns.
    """
    return [part.replace(_PIPE_SENTINEL, "|")
            for part in line.replace(r"\|", _PIPE_SENTINEL).split("|")]


def _rows(body: str):
    """Non-blank lines split on `|`, each cell stripped AND ESCAPED.

    Escaping happens here, once, at the single point every block type reads its
    content through — so no component can forget it.
    """
    for line in body.splitlines():
        if line.strip():
            yield [html.escape(c.strip()) for c in split_cells(line)]


def _cell(row, i, default=""):
    return row[i] if len(row) > i else default


def _accented(row, at):
    """True when the author appended `| accent` at position `at` or later."""
    return any(c == _ACCENT for c in row[at:])


# --- #13: template-supplied marker classes -------------------------------------------
#
# A template hands down a flat `markers` dict. Keys are either a wrapper slot — `"chips"`
# or `"chips:statebar"` when a role narrows it — or a sub-element slot, `"stats.bar"`.
# Values are fixed class names written by the template author, NEVER by the document
# author: a role only ever SELECTS a key, so no author text can reach a class attribute.
# `_assert_marker_slugs` pins that at import time.


def _prose(text: str, decorate=None) -> str:
    """A block cell that carries PROSE, optionally decorated (#13).

    Typed fences bypass `inline_fn`, so the RFC-2119 / severity / score decorators never
    reached block content — a `steps req` row promising a MUST chip rendered bare text.
    The decorator runs on ALREADY-ESCAPED text and only wraps it in a fixed span, exactly
    as it does for prose, so escape-first is unaffected.

    Applied ONLY to prose cells, never to a cell whose value becomes a class token: a
    decorated severity or tone would put markup where `_token` expects a slug.
    """
    return decorate(text) if decorate else text


def _mark(markers, slot: str) -> str:
    """The extra class for `slot`, ready to append inside a class attribute."""
    if not markers:
        return ""
    cls = markers.get(slot)
    return f" {cls}" if cls else ""


def _wrap(tag: str, inner: str, extra: str = "") -> str:
    return f'<div class="blk blk-{tag}{extra}">{inner}</div>'


# An authored series is unbounded; this caps the emitted markup.
_SPARK_MAX_POINTS = 200

_PROPORTION = re.compile(r"^(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)$")


# --- #39: semantic membership, not just slug shape -----------------------------------
#
# `_token` validates a token's SHAPE. It cannot know that `banana` is not a timeline state,
# so `.is-banana` would sail through and quietly match nothing. Each component that carries
# a state declares the set it accepts.

# --- #166: a phase state is a STATUS, and a status no template colours is a defect ---------
#
# `_phase_item` fed the author's word to `_token`, which validates a slug's SHAPE. So the class
# and the visible label were the same string and could not diverge: an author writing `done` got
# `.is-done`, which NO template styled, so the chip fell through to the neutral grey and said
# DONE in grey. That is indistinguishable from a chip somebody meant to be grey, which is why it
# reached a live page (`rawgentic-next-plan-95`, 12 grey DONE chips) with nothing raising a hand.
#
# Two live pages had also reached for `ok`/`warn`/`crit` — SEVERITY words — on a rail whose job
# is status, because nothing documented what a status rail accepts. Same silence, second symptom.
#
# The fix has two halves and needs both:
#   * membership, HERE, so an unknown token warns instead of rendering quietly;
#   * a colour rule per token in every template that draws phases, pinned mechanically by
#     `test_phase_state_vocabulary.py`. Membership alone cannot know whether a template drew it.
#
# The groups say MEANING; the template says colour. That is what stops a fourth vocabulary.
# `ok`, `warn` and `crit` stay in — they are what every published roadmap already uses, and
# dropping them would repaint live pages rather than fix them.
#
# The words match `source_lint._DONE`/`_OPEN` and the `.blk-chip` rules further down this file,
# deliberately: `pending` is amber and `planned` is grey THERE too, so the split is the existing
# one rather than a new opinion.
_PHASE_STATE_FINISHED = frozenset({"ok", "done", "shipped", "merged"})
_PHASE_STATE_MOVING = frozenset({"warn", "active", "wip", "pending"})
_PHASE_STATE_STUCK = frozenset({"crit", "blocked", "failed"})

# Deliberately neutral, and a template must NOT colour these — the guard asserts the ABSENCE.
# "Not started" is a real state, and it only reads as one while it is the sole grey chip. Making
# grey a declared choice rather than a fallthrough is the whole point of this block.
_PHASE_STATE_NEUTRAL = frozenset({"note", "planned"})

_PHASE_STATE_COLOURED = _PHASE_STATE_FINISHED | _PHASE_STATE_MOVING | _PHASE_STATE_STUCK
_PHASE_STATES = _PHASE_STATE_COLOURED | _PHASE_STATE_NEUTRAL


# --- #167: one chip, two facts — TYPE in the word, PRIORITY in the colour -------------
#
# Every token above says exactly one thing: a state. A backlog rail needs two. `crit` says
# urgent and hides what the work IS; `bug` says what it is and, before #166, rendered silently
# grey. An author had to choose which half of the truth to show.
#
# So a compound token `<label>:<level>` carries both. The LABEL becomes the chip's word, the
# LEVEL picks its colour — `bug:must` is the word BUG in the red that `crit` already uses.
#
# **The level borrows an existing colour token; it never mints a new class.** That is the
# load-bearing design choice, not a shortcut. `test_phase_state_vocabulary.py` pins a colour
# rule per token in EVERY template that draws phases, so an `is-must` class would be a fresh
# obligation in every such template, and the first template to miss it would ship exactly the
# grey chip #166 fixed. Borrowing means a compound token cannot outrun the stylesheet.
#
# It also shrinks the injection surface rather than widening it. A bare token reaches a class
# through `_token`'s slug check; a compound one reaches a class only through the fixed map
# below, so no author text touches a class attribute on this path at all.
_PHASE_LABELS = frozenset({
    "bug", "feature", "chore", "hardening", "epic", "action", "note", "task",
})

# level -> the colour token it borrows. Read it as "draw me like this one".
_PHASE_LEVELS = {
    "must": "crit",     # red
    "should": "warn",   # amber
    "could": "note",    # grey — the declared neutral, so `could` is deliberately quiet
    "done": "ok",       # green
}


def _assert_phase_levels_are_drawable():
    """Every borrowed colour must be a token the templates already draw.

    Checked at import, like `_assert_marker_slugs`, because the failure it prevents is silent:
    a level pointing at a token no template styles would render grey and warn about nothing —
    which is the #166 defect re-entering through the door #167 opens.
    """
    unknown = sorted(set(_PHASE_LEVELS.values()) - _PHASE_STATES)
    if unknown:
        raise AssertionError(
            f"phase level(s) borrow colour token(s) that are not declared phase states: "
            f"{unknown}; add them to a group above or point the level at a drawn token")


_assert_phase_levels_are_drawable()

_SEMANTIC_SETS = {
    "timeline state": {"past", "now", "next"},
    "option stance": {"chosen", "rejected"},
    "requirement level": {"must", "must-not", "should", "should-not", "may"},
    "step kind": {"action", "check"},
    # #76: the three node shapes `flowchart.html` uses — `.term`, `.proc`, `.dec`.
    "flow node kind": {"term", "proc", "dec"},
    # A phase and its items share ONE vocabulary. Two would let a phase read `done` and its own
    # child read `complete`, which is the drift `source_lint._phase_child_drift` exists to catch.
    "phase state": _PHASE_STATES,
    "phase item state": _PHASE_STATES,
}


def _semantic(value: str, field: str, blank_ok: bool = False) -> str:
    """A token validated against its component's allowed set, or `note` plus a warning.

    `blank_ok` is for a field whose emptiness is meaningful in the grammar — an option with
    no stance is neutral, and warning about it would be noise.
    """
    raw = value.strip().lower()
    if not raw:
        return "" if blank_ok else _token(value, field)
    tok = _token(value, field)
    allowed = _SEMANTIC_SETS[field]
    if tok not in allowed:
        _warn(f"{field} {value!r} is not one of {sorted(allowed)} — using 'note'; "
              f"the text still renders")
        return "note"
    return tok


def _phase_chip(raw: str, field: str) -> tuple:
    """One chip cell, resolved to `(the word shown, the colour token)` — #167.

    Two grammars share this cell, and the colon is what tells them apart. A bare token is the
    #166 vocabulary and behaves exactly as before, word and colour both taken from it. A
    compound `<label>:<level>` splits the job: the label is the word, the level names a colour
    to borrow. Bare tokens are slugs and can never contain a colon, so the two cannot collide.

    A rejected compound keeps the author's ENTIRE original text as the word, not the half that
    parsed. `bug:urgnet` shows `bug:urgnet`, because showing `bug` would quietly present a typo
    as a successful parse — the reader would see a plausible chip and never learn it was wrong.
    """
    value = raw.strip()
    if ":" not in value:
        return value, _semantic(value, field)

    label, _, level = value.partition(":")
    label, level = label.strip().lower(), level.strip().lower()
    if label not in _PHASE_LABELS:
        _warn(f"{field} {raw!r} names label {label!r}, which is not one of "
              f"{sorted(_PHASE_LABELS)} — using 'note'; the text still renders")
        return value, "note"
    if level not in _PHASE_LEVELS:
        _warn(f"{field} {raw!r} names level {level!r}, which is not one of "
              f"{sorted(_PHASE_LEVELS)} — using 'note'; the text still renders")
        return value, "note"
    return label, _PHASE_LEVELS[level]


# A sparkline series: comma-separated numbers. Anything undrawable drops the graphic and
# keeps the numbers, which is the posture `_meter` already takes for a non-finite value.
def _sparkline(series: str, cls: str = "") -> str:
    # Do NOT drop blank parts: `1,,2` is malformed, and silently sampling it as a valid
    # two-point series presents author error as a measurement.
    parts = [p.strip() for p in series.split(",")]
    if any(not p for p in parts):
        _warn(f"sparkline {series!r} has an empty value — omitting the graphic; the "
              f"numbers still render")
        return ""
    try:
        values = [float(p) for p in parts]
    except ValueError:
        _warn(f"sparkline {series!r} is not a comma-separated number list — omitting the "
              f"graphic; the numbers still render")
        return ""
    if len(values) < 2 or not all(math.isfinite(v) for v in values):
        if values:
            _warn(f"sparkline {series!r} needs at least two finite values — omitting the "
                  f"graphic; the numbers still render")
        return ""
    if len(values) > _SPARK_MAX_POINTS:
        # A 100k-point series emitted ~900 KB of markup. Keep the endpoints and sample the
        # rest deterministically rather than letting an authored series set the page size.
        keep = _SPARK_MAX_POINTS
        values = [values[round(i * (len(values) - 1) / (keep - 1))] for i in range(keep)]
    lo, hi = min(values), max(values)
    span = hi - lo
    if not math.isfinite(span):
        # Every value being finite does NOT make the span finite: -1e308,1e308 overflows
        # to inf and produced a literal `nan` coordinate in the emitted SVG.
        _warn(f"sparkline {series!r} spans more than a float can represent — omitting the "
              f"graphic; the numbers still render")
        return ""
    step = 100.0 / (len(values) - 1)
    # A constant series has zero range: draw it flat at the midline rather than dividing
    # by zero. It is a real measurement and deserves to be shown as one.
    def _y(v):
        y = (20.0 - (v - lo) / span * 20.0) if span else 10.0
        # Belt and braces: never emit a coordinate outside the viewBox, and never a nan.
        return min(20.0, max(0.0, y)) if math.isfinite(y) else 10.0
    points = " ".join(f"{i * step:.1f},{_y(v):.1f}" for i, v in enumerate(values))
    return (f'<span class="blk-spark{cls}">'
            f'<svg viewBox="0 0 100 20" preserveAspectRatio="none" aria-hidden="true">'
            f'<polyline points="{points}"/></svg></span>')


def _stats(body, markers=None, decorate=None, ctx=None):
    """A KPI cell per row. A value written as a proportion (`28/44`) also draws a
    proportional fill — specs §4d's "KPI strip with inline bars" (#13). The fraction
    form is already the grammar's own example, so no new syntax is introduced, and a
    non-proportional value renders exactly as it did before.

    #39 adds an optional delta and an optional sparkline after the label. The literal
    `accent` is NEVER read as either: `28/44 | highs confirmed | accent` is live in the
    committed grammar page, and position 2 is where the delta now sits.
    """
    bar_cls = _mark(markers, "stats.bar")
    spark_cls = _mark(markers, "stats.spark")
    out = []
    for r in _rows(body):
        value, label = _cell(r, 0), _cell(r, 1)
        # The legacy grammar was `value | label | accent`, and that row is live in the
        # committed grammar page. Field 2 now means `delta`, so the legacy flag keeps its
        # meaning ONLY in a row that is exactly three cells; a widened row reads delta from
        # field 2, series from field 3, and accent from field 4 alone. Scanning for the
        # word anywhere — the first attempt — both ate a legitimate delta of "accent" and
        # accented a row whose dedicated field was blank.
        legacy = len(r) == 3 and _cell(r, 2) == _ACCENT
        delta = "" if legacy else _cell(r, 2)
        series = "" if legacy else _cell(r, 3)
        accented = legacy or _cell(r, 4) == _ACCENT
        bar = ""
        m = _PROPORTION.match(value)
        if m:
            num, den = float(m.group(1)), float(m.group(2))
            if den > 0:
                pct = max(0.0, min(100.0, num / den * 100))
                bar = (f'<span class="blk-bar{bar_cls}">'
                       f'<span class="blk-fill" style="width:{pct:.1f}%"></span></span>')
        delta_html = ""
        if delta:
            note_feature(ctx, "stats:delta")
            delta_html = f'<span class="blk-delta">{delta}</span>' 
        spark = ""
        if series:
            spark = _sparkline(series, spark_cls)
            if spark:
                note_feature(ctx, "stats:spark")
            else:
                # The graphic is gone but the author's data must not be. Silently dropping
                # `nan,0` loses text the author wrote, which this engine never does.
                note_feature(ctx, "stats:delta")
                spark = f'<span class="blk-delta">{series}</span>' 
        out.append(
            f'<div class="blk-item{" is-accent" if accented else ""}">'
            f'<span class="blk-value">{value}</span>{delta_html}'
            f'<span class="blk-label">{label}</span>{bar}{spark}</div>')
    return "".join(out)


def _timeline(body, markers=None, decorate=None, ctx=None):
    """`time | title | detail | state` — the rail `report` and `roadmap` need (#39)."""
    note_feature(ctx, "timeline")
    return "".join(
        f'<div class="blk-tl is-{_semantic(_cell(r, 3), "timeline state")}">'
        f'<span class="blk-when">{_cell(r, 0)}</span>'
        f'<span class="blk-title">{_prose(_cell(r, 1), decorate)}</span>'
        f'<span class="blk-text">{_prose(_cell(r, 2), decorate)}</span></div>'
        for r in _rows(body))


def _options(body, markers=None, decorate=None, ctx=None):
    """`title | for | against | stance` — side-by-side trade-offs for `design` (#39).

    A blank stance is neutral and does NOT warn: the grammar says so, and most options in
    a real comparison are neither chosen nor rejected.

    #134: EACH COLUMN CARRIES ITS LABEL IN THE MARKUP. Until now the only stance markers were
    CSS generated content — `content:"+ "`/`"- "` in the shared layer, `content:"FOR"`/`"AGAINST"`
    in `design` — so a screen-reader user met two unlabelled columns, and the label vanished with
    the stylesheet. `design.py` had already recorded exactly that and filed the follow-up this is.

    The label is REAL TEXT, one source of truth, and the generated copies are deleted rather than
    kept beside it. Keeping both would let them drift, and would also DOUBLE-ANNOUNCE: current
    browsers do expose generated content to the accessibility tree, so "For" plus a `+` glyph is
    read as "For plus …". The visible form is unchanged where it mattered — `design` restyles this
    same element to the uppercase block label it already showed.

    The label is styled, never hidden. A visually-hidden variant was considered and rejected: with
    the glyphs gone, hiding it would leave sighted readers no stance signal at all.
    """
    note_feature(ctx, "options")
    out = []
    for r in _rows(body):
        stance = _semantic(_cell(r, 3), "option stance", blank_ok=True)
        cls = f" is-{stance}" if stance else ""
        out.append(
            f'<div class="blk-opt{cls}">'
            f'<span class="blk-title">{_prose(_cell(r, 0), decorate)}</span>'
            f'<span class="blk-for"><span class="blk-lbl">For</span> '
            f'{_prose(_cell(r, 1), decorate)}</span>'
            f'<span class="blk-against"><span class="blk-lbl">Against</span> '
            f'{_prose(_cell(r, 2), decorate)}</span></div>')
    return "".join(out)


def _steprail(body, markers=None, decorate=None, ctx=None):
    """`n | title | detail | kind` — a runbook rail.

    A DISTINCT TAG, not a `steps` role: the second info-string word becomes `role` and is
    never consulted when selecting a renderer, and a template-selected variant would clash
    with `uat`'s checklist.

    Reveal-on-click and one-open-at-a-time are NATIVE — `<details name=…>` groups
    disclosures so opening one closes its siblings, with no script. That matters three
    ways: it keeps this engine's inline-script exception to `uat` alone, it cannot break
    the way a page-global script did once two rails shared a document, and it works with
    JavaScript disabled, which is the whole point for a runbook.

    The first step is `open`; every title is always visible and every detail is one click
    away. A browser without `name` grouping just allows several open at once — degraded,
    never broken.

    Current position IS `details[open]`, styled by CSS. An earlier attempt stamped a static
    `aria-current` on step one, which native disclosure then never moved — opening step two
    left the highlight on the closed step one. `open` cannot go stale because the browser
    owns it, and it is already an accessible state signal.

    #61: THE GROUP IS THE DOCUMENT, NOT THE FENCE — owner decision 2026-08-02, option 3 of the
    three the issue lists. A multi-stage runbook has one fence per stage, so a per-fence group
    meant every stage kept its own open step and a three-stage page showed three "current"
    positions at once. One `name` for the whole document gives exactly one, with no script.

    This REVERSES `_next_id`, which existed to keep two rails apart and whose docstring called a
    shared name "exactly the bug a page-global script had". That conflated two things: the old
    bug was a script going stale across rails, whereas a shared `<details name>` is native
    exclusive disclosure, where closing a sibling is the defined behaviour rather than a fault.
    The cost is real and was accepted: opening a step in stage 3 collapses what you were reading
    in stage 1.

    **What option 3 cannot fix.** There is no native "always exactly one open" mode, so closing
    the last open step still leaves nothing highlighted. Stated in the issue, stated in the
    question the owner answered, and left standing rather than papered over.

    **WHAT THIS BLOCK IS NOT FOR (#57 AC4).** Not a FAQ, and not any set of disclosures a reader
    should be able to open together. Neither shape this renderer can produce gets there:

    | shape | independent? | starts closed? |
    |---|---|---|
    | one multi-row fence | no — one `name` per document, so opening one closes its siblings | all but the first |
    | several one-row fences | yes | no — each fence's single row is emitted `open` |

    The exclusivity is the feature, not a limitation to work around: a runbook rail has a CURRENT
    step. Reaching for `steprail` to get a FAQ ships the wrong interaction under a correct-looking
    marker. Use the **`faq`** block, which emits neither `name` nor `open`. This paragraph exists so
    the next session does not repeat the evaluation #57 already did.
    """
    note_feature(ctx, "steprail")
    gid = "rail"
    # Only the FIRST rail on the page opens a step. Without this every stage still opened its
    # own first step — four `open` attributes in one exclusive group, which browsers resolve by
    # keeping the last, so the highlight landed on the final stage rather than the first.
    first_rail = ctx is None or not ctx.get("_rail_opened")
    if ctx is not None:
        ctx["_rail_opened"] = True
    out = []
    for i, r in enumerate(_rows(body)):
        kind = _semantic(_cell(r, 3), "step kind")
        op = " open" if (i == 0 and first_rail) else ""
        out.append(
            f'<li class="blk-rail-step is-{kind}">'
            f'<details name="{gid}"{op}>'
            f'<summary><span class="blk-n">{_cell(r, 0)}</span>'
            f'<span class="blk-title">{_prose(_cell(r, 1), decorate)}</span></summary>'
            f'<span class="blk-text">{_prose(_cell(r, 2), decorate)}</span>'
            f'</details></li>')
    return f'<ol class="blk-rail">{"".join(out)}</ol>'


def _faq(body, markers=None, decorate=None, ctx=None):
    """`question | answer` — independent, closed-by-default disclosures (#57).

    THE POINT OF THIS BLOCK is the one pair `_steprail` cannot emit: **no `name`**, so the items are
    independent, and **no `open`**, so every item starts closed. `_steprail` groups its disclosures
    deliberately — one-open-at-a-time is right for a runbook rail, where there is a current step, and
    wrong for a FAQ, where a reader wants two answers side by side. Neither of `_steprail`'s two
    shapes reaches this one: a multi-row fence shares a `name`, and one-row fences each emit `open`.

    Named for its CONTENT, as every other block here is (`options`, `findings`, `steps`), rather than
    for the `<details>` element it happens to use. The vendored reference's own class is `.faq`.

    Native `<details>` and nothing else — the engine's inline-script carve-out stays `uat`-only, and
    this needs no script to work at all. The browser's own disclosure marker is KEPT rather than
    suppressed: `_steprail` hides it because it supplies a rail indicator, a FAQ has none, and the
    triangle is then the only thing telling a reader the row opens.
    """
    note_feature(ctx, "faq")
    return "".join(
        f'<details class="blk-faq-item">'
        f'<summary>{_prose(_cell(r, 0), decorate)}</summary>'
        f'<span class="blk-text">{_prose(_cell(r, 1), decorate)}</span>'
        f'</details>'
        for r in _rows(body))


def _verdict(body, markers=None, decorate=None, ctx=None):
    return "".join(
        f'<div class="blk-row is-{_token(_cell(r, 0), "verdict status")}">'
        f'<span class="blk-key">{_cell(r, 0)}</span>'
        f'<span class="blk-text">{_prose(_cell(r, 1), decorate)}</span></div>'
        for r in _rows(body))


def _chips(body, markers=None, decorate=None, ctx=None):
    return "".join(
        f'<span class="blk-chip is-{_token(_cell(r, 1), "chip tone")}">{_cell(r, 0)}</span>'
        for r in _rows(body))


def _callout(body, markers=None, decorate=None, ctx=None):
    """First line is `tone | title`; everything after is body prose.

    Uniform rows made callout source unreadable — that came out of authoring the
    grammar page, not out of implementing this.
    """
    lines = body.splitlines()
    head, rest = (lines[0] if lines else ""), lines[1:]
    parts = [html.escape(c.strip()) for c in split_cells(head)]
    tone, title = (parts + ["", ""])[:2]
    prose = html.escape("\n".join(rest).strip())
    title_html = f'<div class="blk-title">{_prose(title, decorate)}</div>' if title else ""
    prose_html = f"<p>{_prose(prose, decorate)}</p>" if prose else ""
    return (f'<div class="blk-callout is-{_token(tone, "callout tone")}">'
            f'{title_html}{prose_html}</div>')


def _legend(body, markers=None, decorate=None, ctx=None):
    return "<dl>" + "".join(
        f'<dt class="blk-swatch is-{_token(_cell(r, 0), "legend key")}">{_cell(r, 0)}</dt>'
        f"<dd>{_cell(r, 1)}</dd>" for r in _rows(body)) + "</dl>"


def _meter(body, markers=None, decorate=None, ctx=None):
    """`label | value | max`. The maximum is explicit on purpose: inferring a scale
    is guessing at author intent (found while authoring the grammar page)."""
    out = []
    for r in _rows(body):
        label, value, maximum = _cell(r, 0), _cell(r, 1), _cell(r, 2)
        pct = ""
        try:
            v, m = float(value), float(maximum)
            # nan/inf/1e400 must NOT clamp to 100% — that presents an invalid
            # measurement as a complete one, which is worse than no bar at all.
            if math.isfinite(v) and math.isfinite(m) and m > 0:
                pct = f' style="width:{max(0.0, min(100.0, v / m * 100)):.1f}%"'
            else:
                _warn(f"meter {label!r} has a non-finite value ({value}/{maximum}) — "
                      f"omitting the bar; the numbers still render")
        except ValueError:
            pass  # non-numeric is author error: render the text, skip the bar
        out.append(
            f'<div class="blk-meter{" is-accent" if _accented(r, 3) else ""}">'
            f'<span class="blk-label">{label}</span>'
            f'<span class="blk-value">{value} / {maximum}</span>'
            f'<span class="blk-track"><span class="blk-fill"{pct}></span></span></div>')
    return "".join(out)


def _composition(body, markers=None, decorate=None, ctx=None):
    """`label | count | state` — a bar showing what a total is MADE OF (#68).

    `meter` answers "how far along": one value against a maximum. This answers a different
    question — "the nine open items are one critical, two unresolved and six ready" — and a
    single-value bar cannot express it at all. That gap is why a rendered `roadmap` page could
    show `3 / 9` and still tell a reader nothing about the shape of the work.

    Segments are proportional to their counts and coloured by STATE, never by a colour the
    author names: `state` goes through `_token`, so it can only ever become a slug, and a
    document cannot put markup in a class attribute. Counts are shown in the legend, so the bar
    stays a picture and the numbers stay readable.

    A non-numeric count omits the whole bar and warns rather than guessing a proportion — the
    same rule `_meter` follows for a non-finite value, for the same reason: a wrong picture of
    a measurement is worse than none.
    """
    rows = []
    for r in _rows(body):
        label, count, state = _cell(r, 0), _cell(r, 1), _cell(r, 2)
        try:
            n = float(count)
            if not math.isfinite(n) or n < 0:
                raise ValueError(count)
        except ValueError:
            _warn(f"composition row {label!r} has a non-numeric count ({count!r}) — omitting "
                  f"the bar; the legend still renders")
            return _composition_legend_only(rows + [(label, count, state)], body)
        rows.append((label, n, state))

    total = sum(n for _l, n, _s in rows)
    segs, legend = [], []
    for label, n, state in rows:
        cls = _token(state, "composition state")
        if total > 0:
            segs.append(f'<span class="blk-comp-seg is-{cls}" '
                        f'style="width:{n / total * 100:.1f}%"></span>')
        legend.append(f'<span class="blk-comp-key is-{cls}">'
                      f'{count_label(n)} {label}</span>')
    bar = f'<span class="blk-comp-bar">{"".join(segs)}</span>' if segs else ""
    return (f'<div class="blk-comp">{bar}'
            f'<span class="blk-comp-legend">{"".join(legend)}</span></div>')


def count_label(n: float) -> str:
    """`4` not `4.0`, but `2.5` survives — counts are usually whole and should read that way."""
    return str(int(n)) if float(n).is_integer() else f"{n:g}"


def _phases(body, markers=None, decorate=None, ctx=None):
    """Ordered containers: `title | badge | state`, with indented `id | text | state` items
    nested inside each one (#68, the PR that closes it).

    PR 1 gave `roadmap` the composition *device*. This gives the document a way to say what the
    phases ARE. Three gaps, one grammar:

    * **Containers.** A phase is a band with its own title and its own state badge, so the
      hierarchy phase-contains-item is visible rather than implied by document order.
    * **Nesting.** Depth is INDENTATION, borrowed verbatim from `_nodes` — wave 2 tried
      pipe-count-as-depth and rejected it as unreadable, and that finding does not need
      re-making. Tabs are expanded first, or visually-equal indentation would compare unequal.
    * **Order.** Phases render in document order and are NUMBERED here. That is the whole of
      "phases in order": the sequence becomes something a reader sees, not something they infer.

    **The bar is derived, never authored twice.** Each phase's segments come from the states of
    its own items and reuse PR 1's `.blk-comp-*` markup. Asking the author to restate the
    composition they just wrote item by item would let the two disagree, and a bar that
    contradicts the list under it is worse than no bar — the same reasoning `_composition` uses
    for refusing to guess a proportion.

    Arity is checked HERE rather than in `_validate`, for the reason `_nodes` gives: that
    function cannot know a row's shape when the shape depends on indentation.

    NOT a role on `timeline`. `timeline` is shared with `report`, so a phase mode would put two
    grammars in one renderer and risk `report`'s bytes — the same reason D56 made `composition` a
    type rather than a role on `meter`.
    """
    note_feature(ctx, "phases")
    phases: list[tuple[str, str, str, list]] = []
    for raw in body.splitlines():
        if not raw.strip():
            continue
        expanded = raw.expandtabs(4)
        indent = len(expanded) - len(expanded.lstrip())
        parts = [html.escape(c.strip()) for c in split_cells(raw.strip())]
        if len(parts) > 3:
            _warn(f"phases row {raw.strip()!r} has {len(parts)} fields; only 3 are used "
                  f"(title | badge | state for a phase, id | text | state for an item) — "
                  f"the extra ones are ignored")
        first, second, third = (parts + ["", ""])[:3]
        if indent and not phases:
            # Author error, but their content still renders: an item with nothing to sit
            # inside becomes a phase rather than disappearing.
            _warn(f"phases row {raw.strip()!r} is indented but no phase is open — "
                  f"rendering it as a phase of its own")
            indent = 0
        if indent:
            phases[-1][3].append((first, second, third))
        else:
            phases.append((first, second, third, []))

    out = []
    # #172: one advisory for the WHOLE block, gathered before rendering. Per-row would print the
    # same suggestion twenty times, which is how an advisory becomes noise people filter out.
    _typed_chip_nudge([state for _t, _b, state, _i in phases]
                      + [s for _t, _b, _st, items in phases for _id, _tx, s in items])

    for n, (title, badge, state, items) in enumerate(phases, 1):
        st_word, st = _phase_chip(state, "phase state")
        # Resolved ONCE per item, then handed to both consumers. The bar segment and the row
        # are two renderings of one state, so resolving in each place would warn twice for a
        # single author mistake — and a doubled warning reads as two mistakes.
        chips = [_phase_chip(s, "phase item state") for _id, _text, s in items]
        segs = "".join(f'<span class="blk-comp-seg is-{cls}"></span>' for _w, cls in chips)
        bar = f'<span class="blk-comp-bar">{segs}</span>' if segs else ""
        rows = "".join(
            _phase_item(item_id, text, word, cls, decorate,
                        _chip_title(raw_state, cls, ctx))
            for (item_id, text, raw_state), (word, cls) in zip(items, chips))
        # A phase names its chip word in the BADGE cell, so an authored badge always wins — that
        # is the grammar, and #167 does not change it. When the author left the badge empty AND
        # wrote a compound state, the label becomes the badge: otherwise `Phase | | bug:must`
        # would render no chip at all and the word the author typed would vanish, which is the
        # one thing this renderer never does with author text.
        badge_text = badge or (st_word if ":" in state else "")
        badge_html = (f'<span class="blk-ph-badge is-{st}"'
                      f'{_chip_title(state, st, ctx)}>{badge_text}</span>'
                      if badge_text else "")
        out.append(
            f'<div class="blk-ph is-{st}">'
            f'<div class="blk-ph-head"><span class="blk-ph-ord">{n:02d}</span>'
            f'<span class="blk-ph-title">{_prose(title, decorate)}</span>'
            f'{badge_html}</div>{bar}'
            f'<div class="blk-ph-items">{rows}</div></div>')
    return "".join(out)


def _flow(body, markers=None, decorate=None, ctx=None):
    """`kind | label | branch` — a real flow chart (#76).

    `workflow` already had `nodes`, and `nodes` is an indentation TREE. Wiring that tree with
    connectors made it a drawn tree; it still was not a flow chart, which is what the owner asked
    for twice. A flow chart is a SEQUENCE of shaped boxes joined by arrows, and the vendored
    `flowchart.html` is exactly that: a flex column of `.node`s separated by `.connector`s, with
    kinds `.term` / `.proc` / `.dec` and branches labelled on the arrows.

    So this is its own type rather than a role on `nodes` — the same reasoning D56 used for
    `composition` against `meter`. The two grammars are genuinely different (a tree has depth, a
    flow has order), and a role would have put both in one renderer and risked `nodes`' bytes in
    every style that uses it.

    **`n` nodes emit `n-1` connectors.** A trailing connector draws an arrow into nothing, which
    is why the tests pin the count rather than the presence.

    The optional third field labels the arrow ARRIVING at this node, because that is where a flow
    chart writes "yes" and "no" — on the arrow, never in the box. On the FIRST row nothing arrives,
    so a branch there is dropped with a warning rather than silently rendered somewhere it does
    not belong.

    Arity is checked here, not in `_validate`: a row may be one, two or three fields and only the
    kind is required, so a fixed minimum would reject a legitimate bare `proc`.
    """
    note_feature(ctx, "flow")
    rows = []
    for r in _rows(body):
        if len(r) > 3:
            _warn(f"flow row {' | '.join(r)!r} has {len(r)} fields; only 3 are used "
                  f"(kind | label | branch) — the extra ones are ignored")
        rows.append((_cell(r, 0), _cell(r, 1), _cell(r, 2)))

    out = []
    for i, (kind, label, branch) in enumerate(rows):
        if i:
            when = (f'<span class="blk-flow-when">{branch}</span>' if branch else "")
            out.append(f'<div class="blk-flow-link">{when}</div>')
        elif branch:
            _warn(f"flow row {label!r} carries a branch label {branch!r} but it is the FIRST "
                  f"node — nothing arrives at it, so the label is dropped")
        cls = _semantic(kind, "flow node kind")
        out.append(f'<div class="blk-flow-node is-{cls}">'
                   f'<span class="blk-flow-label">{_prose(label, decorate)}</span></div>')
    return "".join(out)


# The two words that carry ONLY urgency. `ok` and `note` are excluded deliberately: they read
# as status as well, so a rail using just those is not making the mistake this nudge is about.
_SEVERITY_ONLY = frozenset({"crit", "warn"})


# --- #173: hover tells you what the colour means --------------------------------------
#
# A chip is three uppercase letters in a colour. That is readable only to someone who already
# knows the vocabulary, which is the same gap #170 and #172 attacked from the documentation and
# the publish path. This attacks it from the page itself: hover a chip, read what it means.
#
# `title` and nothing else. It needs no JavaScript, survives the strict CSP these pages ship
# under, works in every browser, and is announced by screen readers. A custom tooltip would be
# prettier and would cost a script tag on a page whose whole contract is that it fetches and
# runs nothing.
_CTX_LEGEND = "_legend_meanings"

# The fallback vocabulary, used when the document defines no legend of its own. Wording matches
# `design-language.md` deliberately, so the page and the manual cannot say different things.
_STATE_MEANING = {
    "done": "finished", "shipped": "finished", "merged": "finished", "ok": "finished",
    "active": "in flight", "wip": "in flight", "pending": "in flight", "warn": "in flight",
    "blocked": "stuck", "failed": "stuck", "crit": "stuck",
    "note": "not started", "planned": "not started",
}
_LEVEL_MEANING = {"must": "must — highest priority",
                  "should": "should — real value, real cost",
                  "could": "could — scheduled, not started",
                  "done": "done — finished"}

_LEGEND_FENCE = re.compile(r"^```legend[^\n]*\n(.*?)^```", re.S | re.M)


def collect_legend(markdown: str, ctx) -> None:
    """Read every `legend` block in the source into `ctx`, for chip tooltips (#173).

    The document's own words beat the built-in vocabulary every time. An author who wrote
    `crit | blocker or owner decision` has said something more useful than "stuck", and it is
    the meaning their readers were given.

    Blocks render independently and in document order, and a legend commonly sits BELOW the rail
    it explains, so this cannot be done from inside `_legend`. One scan of the source is cheaper
    than a second pass over the output, and it cannot change a single rendered byte on its own.

    Later definitions lose to earlier ones. Two legends defining the same key is an authoring
    mistake either way, and preferring the first keeps the result stable rather than dependent
    on which block happens to come last.
    """
    if ctx is None:
        return
    meanings = ctx.setdefault(_CTX_LEGEND, {})
    for block in _LEGEND_FENCE.finditer(markdown or ""):
        for row in _rows(block.group(1)):
            key, meaning = _cell(row, 0).strip().lower(), _cell(row, 1).strip()
            if key and meaning and key not in meanings:
                meanings[key] = meaning


def _chip_title(raw_state: str, cls: str, ctx) -> str:
    """The `title=` attribute for one chip, or "" when there is nothing worth saying.

    Resolution order, most specific first: the document's own legend for the exact token the
    author wrote, then its legend for the colour token behind a compound, then the built-in
    vocabulary. A chip whose meaning cannot be improved on gets no attribute at all — an empty
    tooltip is worse than none, because it looks like a promise the page failed to keep.
    """
    raw = (raw_state or "").strip().lower()
    if not raw:
        return ""
    legend = (ctx or {}).get(_CTX_LEGEND) or {}
    label, _, level = raw.partition(":")

    if raw in legend:                       # the author explained this exact token
        text = legend[raw]
    elif level and cls in legend:           # a compound, and they explained its colour
        text = f"{label} · {legend[cls]}"
    elif level:                             # a compound, no legend: describe both halves
        text = f"{label} · {_LEVEL_MEANING.get(level, level)}"
    elif cls in legend:                     # a bare token they explained under its own name
        text = legend[cls]
    else:
        text = _STATE_MEANING.get(raw, "")
    # `_rows` has already escaped legend text; a built-in string is ours. Escaping again would
    # double-encode an `&` the author wrote, so the guard is that nothing unescaped reaches here.
    return f' title="{text}"' if text else ""


def _typed_chip_nudge(states) -> None:
    """One advisory per `phases` block when it reports status in SEVERITY words (#172).

    The gap this closes is a real one, measured. `rawgentic-plan-graph` was published twice on
    2026-08-10 with every chip a bare severity word, by a session running a renderer that already
    understood `<label>:<level>` — the engine was current and the author was simply never told.
    #170 put the vocabulary in `SKILL.md`, which fixes the next author who reads it; this reaches
    the author who does not, at the moment they publish.

    **Advisory, never a warning, and never a failure.** The document is valid: bare tokens are
    supported and will stay supported, and every page already published keeps rendering exactly
    as it does today. Printing `WARNING` here would train people to ignore real warnings.

    It cannot migrate anything, and does not pretend to. `warn` carries urgency and no work type,
    so nothing in the document says whether a row is a chore or a feature. The LEVEL half maps
    mechanically and is stated below; the LABEL half is always the author's call.

    Silent once the document has been converted — a nag that keeps firing after you have complied
    is a nag people learn to filter out.
    """
    words = [s.strip().lower() for s in states if s.strip()]
    if not words or any(":" in w for w in words):
        return                      # nothing to say, or the typed grammar is already in use
    if not any(w in _SEVERITY_ONLY for w in words):
        return                      # already reporting in status words
    print("render_artifact: NOTE this `phases` block reports status in severity words "
          "(crit/warn). A typed chip carries the work TYPE in its word and the priority in "
          "its colour — `bug:must`, `chore:should`, `feature:could`. Level maps "
          "crit->must, warn->should, note->could, ok->done; the label is yours to choose. "
          "Bare tokens keep working, so this is a suggestion, not a defect.", file=sys.stderr)


def _phase_item(item_id: str, text: str, word: str, cls: str, decorate=None, title="") -> str:
    """One work item inside a phase. The chip is omitted when the author named no state —
    an empty pill reads as a state rather than as the absence of one.

    `word` and `cls` arrive ALREADY resolved, by `_phase_chip`. They used to be one string
    derived here, which is precisely why #166 happened: the class and the visible label could
    not diverge, so a token no template styled was indistinguishable from one a template
    deliberately left grey. Splitting them is also what lets #167 put a TYPE in the word and a
    PRIORITY in the colour. `word` is what the reader sees; `cls` is only what the stylesheet
    matches, and no author text reaches it.
    """
    chip = (f'<span class="blk-ph-chip is-{cls}"{title}>{word}</span>'
            if word.strip() else "")
    return (f'<div class="blk-ph-item is-{cls}">'
            f'<span class="blk-ph-id">{item_id}</span>{chip}'
            f'<span class="blk-ph-text">{_prose(text, decorate)}</span></div>')


def _composition_legend_only(rows, body):
    """The failure path: no bar, but the author's numbers are still shown as text."""
    legend = "".join(
        f'<span class="blk-comp-key is-{_token(s, "composition state")}">{c} {l}</span>'
        for l, c, s in rows)
    return f'<div class="blk-comp"><span class="blk-comp-legend">{legend}</span></div>'


def _findings(body, markers=None, decorate=None, ctx=None):
    """`severity | title | text` plus an OPTIONAL fourth field, the provenance tail —
    specs §4d's "labelled gutter rows, each with a provenance tail" (#13). Omitting it
    renders exactly as before."""
    tail_cls = _mark(markers, "findings.tail")
    out = []
    for r in _rows(body):
        tail = _cell(r, 3)
        tail_html = (f'<span class="blk-prov{tail_cls}">{tail}</span>') if tail else ""
        out.append(
            f'<div class="blk-finding is-{_token(_cell(r, 0), "severity")}">'
            f'<span class="blk-sev">{_cell(r, 0)}</span>'
            f'<span class="blk-title">{_prose(_cell(r, 1), decorate)}</span>'
            f'<span class="blk-text">{_prose(_cell(r, 2), decorate)}</span>{tail_html}</div>')
    return "".join(out)


def _level(raw: str, ctx) -> str:
    """The optional RFC-2119 level chip. Shared by `_steps` and the uat checklist variant:
    `steps` validates a 4th field tag-wide, so a variant that rendered only three silently
    swallowed authored content — which is what the checklist did."""
    if not raw:
        return ""
    note_feature(ctx, "steps:level")
    return f'<span class="blk-level is-{_semantic(raw, "requirement level")}">{raw}</span>'


def _steps(body, markers=None, decorate=None, ctx=None):
    """`id | title | text` plus an OPTIONAL fourth field, the requirement level (#39).

    `spec` already composes this tag as `steps req` — "requirement ROWS carrying a stable
    ID and a MUST/SHOULD chip" — so the level is added HERE rather than as a second
    requirement component. One requirement concept; the stable ID is preserved.
    """
    out = []
    for r in _rows(body):
        raw = _cell(r, 3)
        level_html = ""
        if raw:
            note_feature(ctx, "steps:level")
            level = _semantic(raw, "requirement level")
            level_html = f'<span class="blk-level is-{level}">{raw}</span>'
        out.append(
            f'<li class="blk-step"><span class="blk-n">{_cell(r, 0)}</span>'
            f'<span class="blk-title">{_prose(_cell(r, 1), decorate)}</span>'
            f'<span class="blk-text">{_prose(_cell(r, 2), decorate)}</span>{level_html}</li>')
    return "<ol>" + "".join(out) + "</ol>"


def _steps_checklist(body, markers=None, decorate=None, ctx=None):
    """The `steps` VARIANT a uat page selects — a checklist row per step (#18).

    Engine-owned on purpose. The template only names `"checklist"`; it never supplies a
    renderer, so parsing, validation and escaping stay behind `_rows` where every other
    component's do. That boundary is what the wave-4 design gate rejected the first
    attempt for.

    Identity is split in two, which is the other thing that gate corrected:

    * NO `id` and no `for` are emitted at all — the `<label>` wraps its checkbox, as the
      target page does, which is what makes the whole row clickable and removes a second
      identifier that would have had to be unique page-wide;
    * the row's first cell is the LOGICAL id, carried in `data-k`/`data-note`, and it is
      what storage and the export key on. Unlike the target's positional `s0…s24`,
      inserting a row cannot reassign a tester's saved answers.

    An empty logical id, or one already used ANYWHERE on the page, raises and degrades
    the whole fence to a code listing. Substituting a sentinel — which `_token` would do — silently merges two
    items onto one checkbox and one storage key.
    """
    # PAGE-scoped, not fence-scoped. `ctx` is created once per document render, so a
    # page with two `steps` fences cannot emit the same id twice — which it did until a
    # Step 11 review caught it, silently merging two rows onto one storage key.
    seen: set[str] = ctx.setdefault("uat_ids", set()) if ctx is not None else set()
    out = []
    for r in _rows(body):
        logical = _cell(r, 0)
        if not logical:
            raise _Malformed("a checklist row has an empty id; every item needs one")
        if logical in seen:
            raise _Malformed(f"checklist id {logical!r} is duplicated on this page; ids "
                             f"key both storage and the export, so two rows cannot share one")
        seen.add(logical)
        out.append(
            f'<li class="ut-item">'
            f'<label class="ut-row">'
            # No `id`/`for`: the label WRAPS its checkbox, so the pairing needs neither,
            # and a generated id was one more thing that had to be unique page-wide.
            f'<input type="checkbox" data-k="{logical}">'
            f'<span class="ut-box"></span>'
            f'<span class="ut-txt"><span class="ut-n">{logical}</span>'
            f'<span class="ut-title">{_prose(_cell(r, 1), decorate)}</span>'
            f'<span class="ut-text">{_prose(_cell(r, 2), decorate)}</span>{_level(_cell(r, 3), ctx)}</span>'
            f'</label>'
            f'<textarea class="ut-note" data-note="{logical}" rows="2" '
            f'placeholder="Notes — what happened?"></textarea>'
            f'</li>')
    return '<ol class="ut-items">' + "".join(out) + "</ol>"


def _nodes(body, markers=None, decorate=None, ctx=None):
    """Depth is INDENTATION; pipes split `label | description | edge`.

    The first grammar used pipe count for depth. Writing a real three-level tree that
    way was unreadable — you had to count separators to see structure — so the
    grammar changed before this was written.

    #13 adds the OPTIONAL third field: the edge reaching this node from its parent, a
    trailing `~` marking it proposed rather than existing. That restores what specs §4d
    asks a `workflow` diagram for (labelled, solid-versus-dashed edges) without bringing
    back pipes-as-hierarchy, which is the thing wave 2 actually rejected. One- and
    two-field rows are untouched: indentation is read from the raw line, never from the
    pipe count.

    Arity is checked HERE, not in `_validate` — that function `continue`s past every
    `nodes` row, so the `_MIN_CELLS`/`_MAX_CELLS` entries never applied to this type and
    a fourth field was silently dropped.
    """
    edge_cls = _mark(markers, "nodes.edge")
    out, stack = [], []          # open (indent, opened_inside_li) levels

    def _close_to(indent):
        while stack and stack[-1][0] > indent:
            _ind, nested = stack.pop()
            out.append("</ul>" + ("</li>" if nested else ""))

    for raw in body.splitlines():
        if not raw.strip():
            continue
        # Tabs would make visually-equal indentation compare unequal.
        expanded = raw.expandtabs(4)
        indent = len(expanded) - len(expanded.lstrip())
        parts = [html.escape(c.strip()) for c in split_cells(raw.strip())]
        if len(parts) > 3:
            _warn(f"nodes row {raw.strip()!r} has {len(parts)} fields; only 3 are used "
                  f"(label | description | edge) — the extra ones are ignored")
        label, desc, edge = (parts + ["", ""])[:3]
        _close_to(indent)
        if not stack or stack[-1][0] < indent:
            # a child list belongs INSIDE its parent <li>, and siblings at the same
            # depth share ONE <ul> — reopen the parent item to descend.
            nested = bool(stack) and bool(out) and out[-1].endswith("</li>")
            if nested:
                out[-1] = out[-1][: -len("</li>")]
            out.append("<ul>")
            stack.append((indent, nested))
        desc_html = f'<span class="blk-text">{desc}</span>' if desc else ""
        edge_html = ""
        if edge:
            # A trailing `~` marks the edge proposed rather than existing. It is stripped
            # from the visible label — the state is the dashed rule, not a stray glyph.
            proposed = edge.endswith("~")
            text = edge[:-1].strip() if proposed else edge
            state = " is-proposed" if proposed else ""
            edge_html = f'<span class="blk-edge{edge_cls}{state}">{text}</span>'
        out.append(
            f'<li class="blk-node">{edge_html}'
            f'<span class="blk-label">{label}</span>{desc_html}</li>')
    while stack:
        _ind, nested = stack.pop()
        out.append("</ul>" + ("</li>" if nested else ""))
    return "".join(out)


def _provenance(body, markers=None, decorate=None, ctx=None):
    return "<dl>" + "".join(
        f"<dt>{_cell(r, 0)}</dt><dd>{_cell(r, 1)}</dd>" for r in _rows(body)) + "</dl>"


# Minimum cells a row of each type needs. A row below its minimum means the author
# wrote something this grammar cannot represent — warn and degrade the WHOLE fence to
# a code listing rather than rendering a component that silently drops their content.
# `nodes` and `phases` are deliberately absent from both tables: `_validate` skips their rows
# entirely (arity depends on indentation, not a fixed shape), so an entry here would look like
# a guard while doing nothing. Each renderer checks its own arity instead.
_MIN_CELLS = {
    "stats": 2, "verdict": 2, "chips": 2, "legend": 2, "meter": 3,
    "findings": 3, "steps": 3, "provenance": 2, "callout": 2,
    "timeline": 4, "options": 4, "steprail": 4,
    # #68: label | count | state — all three are load-bearing; a missing state has no colour.
    "composition": 3,
    # #57: question | answer. Two FIELDS required — a one-field row degrades the whole block to a
    # code listing, because a disclosure with no answer is an empty box. Two BLANK fields still
    # render blank, exactly as `chips`, `options` and `timeline` do; that is the engine-wide
    # convention and this tag does not invent an exception to it. Measured, not assumed.
    "faq": 2,
}

# Cells each type consumes. An author who writes more than this has been silently
# truncated until now, so it warns.
_MAX_CELLS = {
    # #39: stats gained a delta and a sparkline (value|label|delta|spark|accent), and
    # steps gained an optional requirement level (id|title|text|level).
    "stats": 5, "verdict": 2, "chips": 2, "legend": 2, "meter": 4,
    # #13: findings gained an optional 4th field, the provenance tail.
    "findings": 4, "steps": 4, "provenance": 2, "callout": 2,
    "timeline": 4, "options": 4, "steprail": 4,
    "composition": 3,
    "faq": 2,
}


class _Malformed(Exception):
    """Raised when a body cannot be represented by its tag's grammar."""


def _validate(tag: str, body: str) -> None:
    """Warn-and-raise on a body the grammar cannot represent."""
    lines = [ln for ln in body.splitlines() if ln.strip()]
    if not lines:
        raise _Malformed(f"{tag} block is empty")
    if tag == "callout":
        if len(split_cells(lines[0])) < 2:
            raise _Malformed(
                "callout's first line must be `tone | title`")
        return
    if tag in ("nodes", "phases", "flow"):
        return  # arity is indentation-dependent; each renderer checks its own
    lo, hi = _MIN_CELLS[tag], _MAX_CELLS[tag]
    for ln in lines:
        n = len(split_cells(ln))
        if n < lo:
            raise _Malformed(
                f"{tag} row {ln.strip()!r} has {n} field(s); {lo} required")
        if n > hi:
            _warn(f"{tag} row {ln.strip()!r} has {n} fields; only {hi} are used — "
                  f"the extra ones are ignored")


_RENDERERS = {
    "stats": _stats, "verdict": _verdict, "chips": _chips, "callout": _callout,
    "legend": _legend, "meter": _meter, "findings": _findings, "steps": _steps,
    "nodes": _nodes, "provenance": _provenance,
    "timeline": _timeline, "options": _options, "steprail": _steprail,
    "composition": _composition, "phases": _phases, "flow": _flow,
    "faq": _faq,
}

# #18: alternative renderers a template may SELECT BY NAME. Both implementations live
# here; a template declares `BLOCK_VARIANTS = {"steps": "checklist"}` and never hands
# this module a callable. That keeps every component's markup, and its escaping, owned
# by the engine — the boundary the wave-4 design gate insisted on.
_VARIANTS = {
    ("steps", "checklist"): _steps_checklist,
}


def render_block(tag: str, body: str, doc_type: str | None = None,
                 markers=None, role: str | None = None, decorate=None,
                 variants=None, ctx=None) -> str | None:
    """Render one typed block, or return None if `tag` is not a block type.

    None means "not ours" — the caller then renders the fence as a code listing,
    which is also what every other markdown viewer does. A tag that IS ours but is
    not accepted by `doc_type` still renders; the warning is the product (AC3), and
    silently dropping author content would be worse than an unstyled block.

    `markers` is the template's marker map (#13); `role` is the fence's optional second
    word, which narrows which marker slot applies. A role is only ever a KEY LOOKUP — it
    never becomes a class itself — so no author text can reach a class attribute.
    """
    if tag not in _RENDERERS:
        return None
    if doc_type is not None and tag not in accepts(doc_type):
        _warn(f"block type {tag!r} is not accepted by doc type {doc_type!r} — "
              f"rendering it anyway; accepted here: {sorted(accepts(doc_type))}")
    render = _RENDERERS[tag]
    if variants and tag in variants:
        chosen = _VARIANTS.get((tag, variants[tag]))
        if chosen is None:
            _warn(f"unknown {tag!r} variant {variants[tag]!r} — using the default renderer")
        else:
            render = chosen
    try:
        _validate(tag, body)
        # #39: every renderer takes ctx now, so the old "is this a variant?" test —
        # which decided whether ctx was passed at all — is gone. Uniform signature.
        inner = render(body, markers, decorate, ctx)
    except _Malformed as e:
        # Degrade the WHOLE fence, so nothing the author wrote is lost. A variant may
        # raise from inside its own render (identity checks need the parsed rows), so
        # the call is inside the same guard as `_validate`.
        _warn(f"{e} — degrading this {tag} block to a code listing")
        return None
    extra = ""
    if markers:
        # A role narrows the slot; with no role the bare tag is the slot. An unlisted
        # role warns and renders unmarked — never drops the block.
        if role:
            extra = _mark(markers, f"{tag}:{role}")
            if not extra:
                _warn(f"fence role {role!r} is not defined for {tag!r} in doc type "
                      f"{doc_type!r} — rendering the block without its marker")
        else:
            extra = _mark(markers, tag)
    return _wrap(tag, inner, extra)


def render_fence(info: str, body: str, doc_type: str | None = None,
                 markers=None, decorate=None, variants=None,
                 ctx=None) -> str | None:
    """Dispatch a fence info string.

    Returns None for a bare fence or a language fence — both are code listings and
    neither warns, or every code sample in every doc would emit noise. An info string
    that is not a known language AND not a known block type warns once and still
    degrades to a code listing (AC2).

    The info string may carry a second word, the **role** (#13). It is only consulted
    when the template supplied a `markers` map; with `markers=None` the suffix is ignored
    exactly as it was before #13, so no existing caller gains a warning. A THIRD word is
    always warned about — it used to vanish silently, which is how a mistyped role would
    hide.
    """
    words = (info or "").strip().split()
    if not words:
        return None
    tag = words[0].lower()
    if tag in _RENDERERS:
        # The extra-word warning belongs HERE, not above: a language fence legitimately
        # carries attributes (```js title="x"```), and warning on those would be the
        # noise this module already refuses to make.
        if len(words) > 2:
            _warn(f"fence info string {info.strip()!r} has {len(words)} words; only the "
                  f"type and an optional role are read — the rest are ignored")
        role = words[1].lower() if len(words) > 1 else None
        return render_block(tag, body, doc_type=doc_type, markers=markers,
                            role=role, decorate=decorate, variants=variants, ctx=ctx)
    # Not a block tag. Warn ONLY when the body actually looks like block grammar
    # (pipe-delimited rows) — otherwise every code sample in an unlisted language
    # would warn, and warnings people learn to ignore are worse than none. This
    # replaces a fixed language allowlist, which was already wrong for the
    # `powershell` fences in this repo.
    if tag not in _KNOWN_LANGUAGES and any("|" in ln for ln in body.splitlines()):
        _warn(f"fenced block type {tag!r} is not a known block type — degrading to a "
              f"code listing (block types: {', '.join(BLOCK_TAGS)})")
    return None


# Languages common in these docs. The list exists ONLY to keep a legitimate code
# sample from warning; anything not here and not a block tag gets the AC2 warning,
# which is the safe direction — a noisy warning beats a silently mis-typed block.
_KNOWN_LANGUAGES = {
    "bash", "sh", "shell", "zsh", "console", "python", "py", "javascript", "js",
    "typescript", "ts", "json", "yaml", "yml", "toml", "ini", "html", "css", "sql",
    "diff", "patch", "text", "txt", "markdown", "md", "rust", "go", "java", "c",
    "cpp", "ruby", "php", "swift", "kotlin", "xml", "csv", "make", "makefile",
    "dockerfile", "jsonl", "regex", "http", "graphql", "mermaid",
    "powershell", "ps1", "bat", "cmd", "nginx", "apache", "vim", "lua", "r",
    "scala", "perl", "elixir", "erlang", "haskell", "clojure", "tex", "latex",
}


# --- #13: the stylesheet the block engine shipped without ----------------------------
#
# Wave 2's acceptance was explicitly "no template work in this wave", so every component
# above emitted markup with no rule behind it — a `stats` strip rendered as stacked plain
# text. This block is injected by every non-plain template and by none of `plain`.
#
# Colours are TOKENS ONLY: every value below is a `var(--…)` already defined in `_STYLE`
# or `_COMPONENT_STYLE`, so a per-project VDL pack (wave 6) restyles all of it by
# overriding tokens, and no component hardcodes a hex.

# --- #39: optional, FEATURE-keyed layers ---------------------------------------------
#
# `BLOCK_CSS` below is injected into every non-plain page unconditionally, so anything added
# to it changes the pinned exemplar and breaks byte-identity. A new component therefore
# declares its CSS here instead, and it is emitted ONLY when that component actually rendered.
#
# The key is a FEATURE id, not a tag. A tag cannot distinguish a sparkline from an ordinary
# `stats` block — both are `stats` — so a tag-keyed layer would drag new CSS into every page
# that used the old component. `stats:spark`, `steps:level`, `timeline`, … name the feature.
#
# A feature id is recorded on the per-document ctx ONLY on successful emission, so a warned,
# degraded or malformed block contributes nothing.

OPTIONAL_BLOCK_CSS: dict = {
    "stats:spark": """
.blk-stats .blk-spark{display:block;margin-top:6px;height:20px}
.blk-stats .blk-spark svg{width:100%;height:20px;overflow:visible}
.blk-stats .blk-spark polyline{fill:none;stroke:var(--accent);stroke-width:1.5;
vector-effect:non-scaling-stroke}
""",
    "stats:delta": """
.blk-stats .blk-delta{font-size:12px;font-weight:650;color:var(--ink-3);margin-left:6px}
""",
    "steps:level": """
.blk-step .blk-level{font-size:11px;font-weight:700;letter-spacing:.03em;padding:1px 6px;
border-radius:5px;text-transform:uppercase;color:var(--req-c);background:var(--req-c-bg)}
.blk-step .blk-level.is-must-not,.blk-step .blk-level.is-should-not{color:var(--sev-crit);
background:var(--sev-crit-bg)}
""",
    "timeline": """
.blk-timeline{border-left:2px solid var(--line);padding-left:16px}
.blk-timeline .blk-tl{position:relative;padding:8px 0}
.blk-timeline .blk-tl::before{content:"";position:absolute;left:-21px;top:14px;width:8px;
height:8px;border-radius:999px;background:var(--line)}
.blk-timeline .is-now::before{background:var(--accent);box-shadow:0 0 0 3px var(--accent-soft,transparent)}
.blk-timeline .blk-when{font:11.5px/1.4 ui-monospace,Menlo,Consolas,monospace;color:var(--ink-3)}
.blk-timeline .blk-title{display:block;font-weight:650}
.blk-timeline .blk-text{display:block;color:var(--ink-2)}
""",
    "options": """
.blk-options{display:flex;flex-wrap:wrap;gap:12px}
.blk-options .blk-opt{flex:1 1 220px;background:var(--surface);border:1px solid var(--line);
border-radius:12px;padding:12px 14px}
.blk-options .is-chosen{border-color:var(--accent);border-width:2px}
.blk-options .is-rejected{opacity:.72}
.blk-options .blk-title{display:block;font-weight:700;margin-bottom:6px}
.blk-options .blk-for,.blk-options .blk-against{display:block;font-size:13px}
/* #134 — the stance label is MARKUP now (`_options` emits `.blk-lbl`), not `content:"+ "`/`"- "`
   on a pseudo-element. Generated content is not dependable semantic markup, and keeping a copy
   here beside the real one would both drift and double-announce. A word also beats a bare sign at
   a glance and does not lean on colour alone — the argument `design.py` had already made for its
   own labels. Styled, never hidden: with the glyphs gone, hiding this leaves no stance signal.

   The gap between label and prose is a REAL SPACE in the markup, not a margin here. The old
   `content:"+ "` carried its own trailing space; an early version of this dropped it and leaned on
   `margin-right`, which separates the label visually while leaving the DOM text fused as
   "Forfewest files" — so text extraction, copy-paste, and any consumer that concatenates text nodes
   got the exact failure this change exists to prevent. One space does both jobs, so there is no
   margin here to keep in sync with it. Found twice independently: in a browser, and by review. */
.blk-options .blk-lbl{font-weight:700}
.blk-options .blk-for .blk-lbl{color:var(--req-c)}
.blk-options .blk-against .blk-lbl{color:var(--sev-high)}
""",
    "faq": """
/* #57 — independent, closed-by-default disclosures. Deliberately does NOT suppress the browser's
   own disclosure marker: `steprail` hides it because it supplies a rail indicator, a FAQ has none,
   and the triangle is then the only affordance saying the row opens. That also keeps this rule set
   free of generated content, which #134 has just finished removing from the options block. */
.blk-faq{display:grid;gap:8px}
.blk-faq .blk-faq-item{background:var(--surface);border:1px solid var(--line);
border-radius:10px;padding:10px 14px}
.blk-faq summary{cursor:pointer;font-weight:650}
.blk-faq .blk-text{display:block;color:var(--ink-2);padding:6px 0 0}
""",
    "codecopy": """
/* An ordinary fenced listing, in a box with its language and a copy button. RICH ONLY —
   `plain` carries no template CSS by definition and stays a bare <pre>. The box owns the
   border, radius and ground that `pre` supplies on its own elsewhere, so the bar and the
   listing share one outline instead of stacking two. */
.doc-code{margin:0 0 14px;border:1px solid var(--line);border-radius:10px;
background:var(--code);overflow:hidden}
.doc-code-bar{display:flex;align-items:center;justify-content:space-between;gap:12px;
padding:5px 8px 5px 14px;border-bottom:1px solid var(--line)}
.doc-code-lang{font:11.5px/1.4 ui-monospace,Menlo,Consolas,monospace;color:var(--ink-3);
overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.doc-code-copy{flex:none;font:11.5px/1.4 ui-monospace,Menlo,Consolas,monospace;
color:var(--ink-2);background:var(--surface);border:1px solid var(--line);border-radius:6px;
padding:3px 10px;cursor:pointer}
.doc-code-copy:hover{color:var(--accent);border-color:var(--accent)}
.doc-code-copy:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.doc-code-copy[data-state=ok]{color:var(--accent);border-color:var(--accent)}
.doc-code-copy[data-state=fail]{color:var(--ink-2);border-color:var(--ink-3)}
.doc-code>pre{margin:0;border:0;border-radius:0;background:none}
/* Paper cannot take a copy. Printing the control would print a button that does nothing. */
@media print{.doc-code-copy{display:none}}
""",
    "steprail": """
.blk-steprail .blk-rail{list-style:none;margin:0;padding:0;border-left:2px solid var(--line)}
.blk-steprail .blk-rail-step{position:relative;padding:8px 0 8px 16px}
.blk-steprail .blk-rail-step:has(details[open]){border-left:2px solid var(--accent);
margin-left:-2px;padding-left:18px}
.blk-steprail summary{cursor:pointer;list-style:none}
.blk-steprail summary::-webkit-details-marker{display:none}
.blk-steprail .blk-n{font:11.5px/1.4 ui-monospace,Menlo,Consolas,monospace;color:var(--ink-3)}
.blk-steprail .blk-title{font-weight:650;margin-left:6px}
.blk-steprail .blk-text{display:block;color:var(--ink-2);padding:4px 0 0 18px}
.blk-steprail .is-check .blk-n::after{content:" check";color:var(--req-c);font-weight:700}
.blk-steprail .is-action .blk-n::after{content:" do";color:var(--accent);font-weight:700}
""",
}

# Only `codecopy` needs a script, and it needs one irreducibly: writing to the clipboard has
# no HTML or CSS expression. Everything else here stays declarative — the rail's exclusivity
# is native `<details name>`, not JavaScript.
#
# The contract this script keeps, and the tests that pin each clause:
#   * It reveals the button it depends on. The button ships `hidden`, so a reader with
#     JavaScript disabled never sees a control that cannot work.
#   * It reads `textContent` and writes `textContent`. No `innerHTML`, no `document.write`,
#     no `eval` — the same forbidden list the `uat` script is held to.
#   * It touches nothing outside `.doc-code`, so it cannot perturb a page that has no fence.
#   * It states failure. An insecure origin has no `navigator.clipboard`, so the button says
#     "Press Ctrl+C" rather than silently doing nothing.
OPTIONAL_BLOCK_JS: dict = {
    "codecopy": """<script>
(function(){
var boxes=document.querySelectorAll('.doc-code');
if(!boxes.length)return;
function fallback(text){
var ta=document.createElement('textarea');
ta.value=text;ta.setAttribute('readonly','');
ta.style.position='fixed';ta.style.top='-1000px';ta.style.opacity='0';
document.body.appendChild(ta);ta.select();
var ok=false;
try{ok=document.execCommand('copy');}catch(e){ok=false;}
document.body.removeChild(ta);
return ok;
}
function flash(btn,label,state){
btn.textContent=label;
btn.setAttribute('data-state',state);
window.clearTimeout(btn.getAttribute('data-timer'));
btn.setAttribute('data-timer',window.setTimeout(function(){
btn.textContent='Copy';btn.removeAttribute('data-state');},2000));
}
Array.prototype.forEach.call(boxes,function(box){
var btn=box.querySelector('.doc-code-copy');
var code=box.querySelector('code');
if(!btn||!code)return;
btn.hidden=false;
btn.addEventListener('click',function(){
var text=code.textContent;
function done(ok){flash(btn,ok?'Copied':'Press Ctrl+C',ok?'ok':'fail');}
if(navigator.clipboard&&window.isSecureContext){
navigator.clipboard.writeText(text).then(function(){done(true);},
function(){done(fallback(text));});
}else{done(fallback(text));}
});
});
})();
</script>""",
}


_CTX_FEATURES = "_features"


def feature_order() -> list:
    """Declaration order for the optional layers. Sorted, not discovery order: CSS order is
    cascade order, so two documents with the same components must emit the same cascade
    regardless of the order their blocks happen to appear in."""
    return sorted(set(OPTIONAL_BLOCK_CSS) | set(OPTIONAL_BLOCK_JS))


def note_feature(ctx, feature: str) -> None:
    """Record that `feature` really rendered. A None ctx is fine — `plain` and direct
    `render_block` callers have no document to attribute it to."""
    if ctx is None:
        return
    ctx.setdefault(_CTX_FEATURES, set()).add(feature)


def used_features(ctx) -> set:
    if not ctx:
        return set()
    return set(ctx.get(_CTX_FEATURES, ()))


def optional_css(features) -> str:
    return "".join(OPTIONAL_BLOCK_CSS[f] for f in feature_order()
                   if f in features and f in OPTIONAL_BLOCK_CSS)


def optional_js(features) -> str:
    return "".join(OPTIONAL_BLOCK_JS[f] for f in feature_order()
                   if f in features and f in OPTIONAL_BLOCK_JS)


# #133: `--accent-soft` lives HERE, and the placement is the whole decision.
#
# The issue asks for it "wherever `--accent` is", which is `_STYLE` — but `plain` receives `_STYLE`
# too, and the same issue requires `plain` to stay byte-identical. Those two cannot both hold. The
# consequence was already written down twice: the comment above says anything added to this block
# "changes the pinned exemplar and breaks byte-identity", and #75 recorded that "adding hues to the
# shared `:root` block moves EVERY style's bytes, `plain` included, which AC2 forbids outright".
#
# So it is defined wherever it can be CONSUMED. Every non-plain template gets this block; `plain`
# gets none of it, and `plain` renders every typed block as a code listing, so it can never hold a
# timeline halo — a token there would be bytes with no possible consumer.
#
# DERIVED, not declared per theme. One declaration then tracks all four theme blocks AND any
# per-project VDL pack, because `--accent` and `--accent-soft` sit on the same `:root` element and
# the pack's `--accent` wins on source order. A pack therefore cannot forget to supply a matching
# soft value, which is what AC1 was actually protecting against. The mix is exactly the one
# `design.py` improvised inline, so substituting the token there changes no rendering.
#
# BROWSER BASELINE, and the honest reading of the consumer's fallback (Step 11).
# `color-mix()` is required. It has been interoperable since 2023 (Chrome 111, Safari 16.2,
# Firefox 113), and these pages are read on a current browser, so no `@supports` ladder is carried.
#
# The consumer writes `var(--accent-soft, transparent)`, and THAT FALLBACK CANNOT FIRE now that the
# token is declared — a custom property accepts any token stream, so `var()` substitutes it and the
# `box-shadow` is then invalid at computed-value time in an engine without `color-mix()`, which
# makes the shadow `none` rather than `transparent`. Same invisible halo, reached a different way.
# The fallback is kept as harmless belt-and-braces, but it is NOT the compatibility story: the
# baseline above is. Anyone lowering that baseline has to add the `@supports` ladder, not trust the
# fallback.
BLOCK_CSS = """
:root{--accent-soft:color-mix(in srgb,var(--accent) 12%,transparent)}
.blk{margin:14px 0}
.blk-stats{display:flex;flex-wrap:wrap;gap:10px}
.blk-stats .blk-item{flex:1 1 130px;background:var(--surface);border:1px solid var(--line);
border-radius:10px;padding:10px 12px;display:flex;flex-direction:column;gap:2px}
.blk-stats .blk-value{font-size:22px;font-weight:750;letter-spacing:-.02em;color:var(--ink)}
.blk-stats .is-accent .blk-value{color:var(--accent)}
.blk-stats .blk-label{font:11px/1.3 ui-monospace,Menlo,Consolas,monospace;
letter-spacing:.06em;text-transform:uppercase;color:var(--ink-3)}
.blk-bar{display:block;height:4px;border-radius:999px;background:var(--code);margin-top:6px}
.blk-bar .blk-fill{display:block;height:100%;border-radius:999px;background:var(--accent)}
.blk-verdict .blk-row{display:flex;gap:10px;align-items:baseline;padding:8px 0;
border-bottom:1px solid var(--line)}
.blk-verdict .blk-row:last-child{border-bottom:0}
.blk-verdict .blk-key{font:11px/1.4 ui-monospace,Menlo,Consolas,monospace;font-weight:700;
letter-spacing:.06em;text-transform:uppercase;color:var(--accent);flex:0 0 auto;min-width:64px}
.blk-verdict .blk-text{color:var(--ink);font-size:16px;font-weight:600}
.blk-chips{display:flex;flex-wrap:wrap;gap:6px}
.blk-chip{font-size:11px;font-weight:700;letter-spacing:.04em;padding:3px 9px;
border-radius:999px;text-transform:uppercase;white-space:nowrap;
color:var(--ink-2);background:var(--code);border:1px solid var(--line)}
.blk-chip.is-done,.blk-chip.is-shipped,.blk-chip.is-merged{color:var(--req-c);
background:var(--req-c-bg);border-color:transparent}
.blk-chip.is-wip,.blk-chip.is-pending{color:var(--sev-med);background:var(--sev-med-bg);
border-color:transparent}
.blk-chip.is-blocked,.blk-chip.is-failed{color:var(--sev-crit);background:var(--sev-crit-bg);
border-color:transparent}
.blk-callout>.blk-callout{border-left:3px solid var(--ink-3);background:var(--code);
border-radius:0 8px 8px 0;padding:10px 14px}
.blk-callout .blk-title{font-weight:700;color:var(--ink);margin-bottom:.2em}
.blk-callout p{margin:0;color:var(--ink-2)}
.blk-callout .is-warn,.blk-callout .is-high{border-left-color:var(--sev-high);
background:var(--sev-high-bg)}
.blk-callout .is-stop,.blk-callout .is-critical{border-left-color:var(--sev-crit);
background:var(--sev-crit-bg)}
.blk-callout .is-note,.blk-callout .is-info{border-left-color:var(--accent)}
.blk-legend dl{display:grid;grid-template-columns:auto 1fr;gap:6px 12px;margin:0}
.blk-legend dt{font:11px/1.6 ui-monospace,Menlo,Consolas,monospace;font-weight:700;
letter-spacing:.05em;text-transform:uppercase;color:var(--ink-2);
border-left:3px solid var(--ink-3);padding-left:8px}
.blk-legend dt.is-done{border-left-color:var(--req-c)}
.blk-legend dt.is-blocked{border-left-color:var(--sev-crit)}
.blk-legend dt.is-solid{border-left-color:var(--accent)}
/* #171: the rest of the status vocabulary. Three tokens had a colour and the other ten did
   not, so a legend whose keys happened to be `crit`/`warn`/`ok`/`note` — the four a roadmap
   actually uses — rendered four identical grey bars. A legend exists to say what a colour
   means, and that one could not: every row looked the same as every other.
   Measured on the live `rawgentic-plan-graph` page before the fix.
   Grouped to match `.blk-chip` above rather than invented here, so a legend key and a chip
   carrying the same word cannot disagree about its colour. */
.blk-legend dt.is-shipped,.blk-legend dt.is-merged,.blk-legend dt.is-ok{
border-left-color:var(--req-c)}
.blk-legend dt.is-failed,.blk-legend dt.is-crit{border-left-color:var(--sev-crit)}
.blk-legend dt.is-wip,.blk-legend dt.is-pending,.blk-legend dt.is-active,
.blk-legend dt.is-warn{border-left-color:var(--sev-med)}
/* `note` and `planned` are deliberately absent: they are the declared NEUTRAL states, and the
   base rule's `--ink-3` is their colour. Adding a rule here would be the same mistake in
   reverse — see `_PHASE_STATE_NEUTRAL`. A key outside the vocabulary entirely (`solid` above,
   or a line style in a module map) also keeps the neutral bar, correctly: the legend's key
   space is open by design, and only the status words carry a status colour. */
.blk-legend dd{margin:0;color:var(--ink-2);font-size:13.5px}
.blk-meter{display:grid;grid-template-columns:1fr auto;gap:2px 12px;margin:8px 0}
.blk-meter .blk-label{color:var(--ink-2);font-size:13.5px}
.blk-meter .blk-value{font:12px/1.4 ui-monospace,Menlo,Consolas,monospace;color:var(--ink-3)}
.blk-meter .blk-track{grid-column:1/-1;height:6px;border-radius:999px;background:var(--code);
overflow:hidden}
.blk-meter .blk-fill{display:block;height:100%;background:var(--accent)}
.blk-meter.is-accent .blk-fill{background:var(--accent)}
.blk-findings .blk-finding{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;
padding:10px 0;border-bottom:1px solid var(--line)}
.blk-findings .blk-finding:last-child{border-bottom:0}
.blk-sev{font-size:10.5px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;
padding:2px 7px;border-radius:999px;white-space:nowrap;align-self:start;
color:var(--sev-low);background:var(--sev-low-bg)}
.is-critical>.blk-sev{color:var(--sev-crit);background:var(--sev-crit-bg)}
.is-high>.blk-sev{color:var(--sev-high);background:var(--sev-high-bg)}
.is-medium>.blk-sev{color:var(--sev-med);background:var(--sev-med-bg)}
.blk-findings .blk-title{font-weight:650;color:var(--ink)}
.blk-findings .blk-text{grid-column:2;color:var(--ink-2);font-size:13.5px}
.blk-prov{grid-column:2;font:11.5px/1.5 ui-monospace,Menlo,Consolas,monospace;
color:var(--ink-3)}
.blk-steps ol,.blk-steps{margin:0;padding:0;list-style:none}
.blk-step{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;padding:9px 0;
border-bottom:1px solid var(--line)}
.blk-step:last-child{border-bottom:0}
.blk-step .blk-n{font:11.5px/1.5 ui-monospace,Menlo,Consolas,monospace;font-weight:700;
color:var(--accent);align-self:start}
.blk-step .blk-title{font-weight:650;color:var(--ink)}
.blk-step .blk-text{grid-column:2;color:var(--ink-2);font-size:13.5px}
.blk-nodes ul{list-style:none;margin:0;padding:0}
.blk-nodes ul ul{margin-left:18px;padding-left:14px;border-left:1px solid var(--line)}
.blk-node{background:var(--surface);border:1px solid var(--line);border-radius:8px;
padding:7px 11px;margin:6px 0;display:flex;flex-wrap:wrap;gap:2px 10px;align-items:baseline}
/* A child list lives INSIDE its parent <li>, so on a flex parent it becomes a flex
   SIBLING of the label and renders beside it instead of beneath. Found by looking at a
   rendered three-level tree, not by reading the markup. */
.blk-node>ul{flex-basis:100%;margin-top:6px}
/* Two roots in ONE nodes block are a before/after pair; a template opts in by
   gridding this top-level list. Two separate fences cannot pair — each is its
   own wrapper with a single child. */
.blk-nodes>ul{display:grid;gap:0 16px}
.blk-node .blk-label{font-weight:650;color:var(--ink)}
.blk-node .blk-text{color:var(--ink-3);font:11.5px/1.5 ui-monospace,Menlo,Consolas,monospace}
.blk-edge{flex-basis:100%;font:10.5px/1.4 ui-monospace,Menlo,Consolas,monospace;
letter-spacing:.05em;text-transform:uppercase;color:var(--accent)}
.blk-edge.is-proposed{color:var(--ink-3);border-bottom:1px dashed var(--ink-3);
align-self:start;display:inline-block;flex-basis:auto}
.blk-provenance dl{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;margin:0;
font-size:13px}
.blk-provenance dt{font:11px/1.5 ui-monospace,Menlo,Consolas,monospace;font-weight:700;
letter-spacing:.05em;text-transform:uppercase;color:var(--ink-3)}
.blk-provenance dd{margin:0;color:var(--ink-2)}
"""
