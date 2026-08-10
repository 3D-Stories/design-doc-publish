"""#39 — the component vocabulary waves 3-5 build against.

Three new tags (`timeline`, `options`, `steprail`) and two extensions (`stats` gains a delta
and a sparkline; `steps` gains an optional requirement level). `findings` already was the
issue's "finding card" and gets nothing here — the gap there is card presentation, which is
template CSS and belongs to #40.

The tests that matter most are the ones about NOT breaking what exists: the legacy
`| accent` row, and the byte-identity of any page that does not use a new feature.
"""
import re
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render  # noqa: E402
from render import blocks  # noqa: E402


# --- stats: the delta and the sparkline, without disturbing the legacy row -----------

def test_the_committed_legacy_accent_row_is_unchanged():
    """`28/44 | highs confirmed | accent` is live in docs/typed-blocks-grammar.md. Field 3
    now means `delta`, so the literal `accent` must never be read as one."""
    out = blocks.render_block("stats", "28/44 | highs confirmed | accent")
    assert "is-accent" in out
    assert "blk-delta" not in out


def test_a_two_cell_stats_row_is_unchanged():
    assert "blk-delta" not in blocks.render_block("stats", "82 | sessions read")
    assert "blk-spark" not in blocks.render_block("stats", "82 | sessions read")


def test_a_delta_renders():
    out = blocks.render_block("stats", "155 | findings mined | +12")
    assert "blk-delta" in out and "+12" in out


def test_a_delta_and_an_accent_can_coexist():
    out = blocks.render_block("stats", "155 | findings | +12 | | accent")
    assert "blk-delta" in out and "is-accent" in out


def test_a_sparkline_renders_as_inline_svg():
    out = blocks.render_block("stats", "155 | findings | +12 | 3,5,4,8,9")
    assert "blk-spark" in out and "<svg" in out and "<polyline" in out
    assert "<img" not in out and "http" not in out


def test_a_sparkline_without_a_delta_still_works():
    out = blocks.render_block("stats", "155 | findings |  | 3,5,4,8")
    assert "blk-spark" in out


@pytest.mark.parametrize("series", ["nan", "inf", "1e400", "3", "", "banana,4",
                                    "nan,inf", "1,two,3"])
def test_a_sparkline_refuses_undrawable_data(series):
    """`_meter` already refuses non-finite input; a sparkline additionally cannot draw a
    single point (a one-point line is a lie about a trend). The numbers still render."""
    out = blocks.render_block("stats", f"155 | findings |  | {series}")
    assert "<svg" not in out
    assert "155" in out and "findings" in out


def test_a_constant_series_draws_a_flat_line_rather_than_dividing_by_zero():
    out = blocks.render_block("stats", "3 | steady |  | 3,3,3")
    assert "<svg" in out and "polyline" in out


def test_using_a_sparkline_records_the_feature_but_a_plain_stats_row_does_not():
    used, unused = {}, {}
    blocks.render_block("stats", "1 | a |  | 1,2,3", ctx=used)
    blocks.render_block("stats", "1 | a", ctx=unused)
    assert "stats:spark" in blocks.used_features(used)
    assert blocks.used_features(unused) == set()


# --- timeline ------------------------------------------------------------------------

def test_timeline_renders_its_rows_and_states():
    out = blocks.render_block("timeline", "09:14 | Alert fires | rate crosses 2% | past")
    assert "blk-timeline" in out and "is-past" in out
    assert "09:14" in out and "Alert fires" in out


def test_an_unknown_timeline_state_warns_and_falls_back(capsys):
    out = blocks.render_block("timeline", "09:14 | t | d | banana")
    assert "is-banana" not in out and "is-note" in out
    assert "banana" in capsys.readouterr().err


# --- options ---------------------------------------------------------------------------

def test_options_renders_a_card_per_row():
    out = blocks.render_block("options", "Debounce | small diff | per call site | chosen")
    assert "blk-options" in out and "is-chosen" in out
    assert "small diff" in out and "per call site" in out


def test_a_blank_stance_is_neutral_and_does_not_warn(capsys):
    out = blocks.render_block("options", "Shared hook | one impl | new surface |")
    assert "blk-options" in out
    assert "stance" not in capsys.readouterr().err


# --- options: the column labels live in the markup (#134) --------------------------------
#
# Before this, the ONLY stance markers were CSS generated content — `content:"+ "`/`"- "` in the
# shared layer and `content:"FOR"`/`"AGAINST"` in `design`. Generated content is not dependable
# semantic markup, so a screen-reader user met two unlabelled columns. `design.py` had already
# written that down and filed the follow-up; this is it.
#
# One source of truth: the label is markup NOW, so a CSS-generated copy may not survive alongside
# it — two labels that can drift is the defect, and it would also double-announce, because current
# browsers DO expose generated content to the accessibility tree.

_OPT_ROW = "Debounce | small diff | per call site | chosen"
_OPT_MD = f"# T\n\n```options\n{_OPT_ROW}\n```\n"


def test_each_option_column_carries_its_label_in_the_markup():
    out = blocks.render_block("options", _OPT_ROW)
    assert '<span class="blk-lbl">For</span>' in out
    assert '<span class="blk-lbl">Against</span>' in out


def test_the_label_precedes_its_column_text_so_it_is_announced_first():
    """Order is the whole point: the label has to arrive before the prose it labels."""
    out = blocks.render_block("options", _OPT_ROW)
    assert '<span class="blk-for"><span class="blk-lbl">For</span> small diff</span>' in out
    assert ('<span class="blk-against"><span class="blk-lbl">Against</span> per call site</span>'
            in out)


def test_a_real_space_separates_the_label_from_the_prose():
    """The separator is markup, NOT `margin-right`.

    A margin separates the label visually and leaves the DOM text fused — `Forsmall diff` — so
    text extraction, copy-paste and anything that concatenates text nodes get exactly the failure
    this change exists to prevent. The `content:"+ "` this replaced carried its own trailing space;
    dropping it is the easy regression, so it is pinned here rather than left to the eye.
    """
    out = blocks.render_block("options", _OPT_ROW)
    assert "</span> small diff" in out
    assert "</span> per call site" in out
    assert "Forsmall diff" not in out
    assert "Againstper call site" not in out


def _declarations(css):
    """CSS with `/* … */` comments stripped.

    These guards MUST read declarations only. Both rules this issue replaced are quoted verbatim
    in the comments that explain the replacement, so a bare substring search over the raw
    stylesheet finds the prose and reports the fix as un-applied — a test that fails on the
    correct implementation.
    """
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def test_the_shared_layer_no_longer_generates_a_stance_glyph():
    css = _declarations(blocks.OPTIONAL_BLOCK_CSS["options"])
    assert 'content:"+ "' not in css
    assert 'content:"- "' not in css
    assert ".blk-for::before" not in css
    assert ".blk-against::before" not in css


def _label_rules(css):
    """Every complete `selector{…}` rule whose SELECTOR names the label.

    Scoping the search to LINES containing `.blk-lbl` is not enough: a rule may carry its selector
    on one line and `display:none` on the next, and a per-line search waves that straight through.
    """
    rules = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", _declarations(css)):
        selector, body = m.group(1).strip(), m.group(2)
        if ".blk-lbl" in selector:
            rules.append((selector, body))
    return rules


def _all_stylesheets():
    """The shared options layer plus every template's own sheet.

    A template can hide the label at higher specificity, so guarding only the shared layer leaves
    twelve places the defect could still land.
    """
    from render import templates as render_templates
    sheets = {'OPTIONAL_BLOCK_CSS["options"]': blocks.OPTIONAL_BLOCK_CSS["options"]}
    for name, module in render_templates.TEMPLATES.items():
        css = getattr(module, "CSS", "")
        if css:
            sheets[f"templates/{name}"] = css
    return sheets


def test_the_label_is_never_hidden_from_assistive_tech():
    """AC1 is *reachable* by assistive tech, not merely present.

    `display:none` or `visibility:hidden` would satisfy "in the markup" and silently fail the AC —
    and with the glyphs deleted there would then be no stance signal left for anyone.
    """
    sheets = _all_stylesheets()
    assert _label_rules(sheets['OPTIONAL_BLOCK_CSS["options"]']), \
        "the label needs a rule of its own, or it inherits nothing"
    for where, css in sheets.items():
        for selector, body in _label_rules(css):
            assert "display:none" not in body, f"{where}: {selector}"
            assert "visibility:hidden" not in body, f"{where}: {selector}"


def test_the_hidden_label_guard_can_actually_fail():
    """A guard that cannot fail is not a guard — and this one just got rewritten.

    The multiline shape is the one the per-line version missed, so it is the one pinned here.
    """
    sneaky = ".blk-options .blk-lbl,\n.other{\n  display:none;\n}"
    rules = _label_rules(sneaky)
    assert rules, "the extractor must find a rule whose selector spans lines"
    assert any("display:none" in body for _, body in rules)


def test_the_design_template_label_is_real_dom_text_not_generated_content():
    from render.templates import design as design_tpl
    css = _declarations(design_tpl.CSS)
    assert 'content:"FOR"' not in css
    assert 'content:"AGAINST"' not in css
    assert ".dz-options .blk-lbl" in css
    # The visible form stays FOR/AGAINST; only its SOURCE changes.
    assert "text-transform:uppercase" in css


def test_the_label_reaches_every_rich_style():
    """`design` is the only doc type that ACCEPTS `options`; every other rich style renders the
    block anyway, with a "not accepted … rendering it anyway" warning. So the label has to be right
    in all of them, not in a sample of two.

    The byte oracle in `test_furniture_context.py` proves those pages MOVED; it cannot prove they
    moved CORRECTLY, because a sha says nothing about what is in the page. This does.
    """
    from render import templates as render_templates
    styles = sorted(render_templates.TEMPLATES)
    assert len(styles) >= 12, f"expected the full rich roster, got {styles}"
    for style in styles:
        page = render.render_artifact(_OPT_MD, title="T", style=style, generated_at="x")
        assert '<span class="blk-lbl">For</span> ' in page, style
        assert '<span class="blk-lbl">Against</span> ' in page, style


def test_the_label_never_reaches_plain():
    """`plain` leaves a typed fence as a code listing and never invokes the block engine, which
    is what keeps its bytes frozen through this change."""
    page = render.render_artifact(_OPT_MD, title="T", style="plain", generated_at="x")
    assert "blk-lbl" not in page


# --- steprail --------------------------------------------------------------------------

def test_steprail_is_a_distinct_tag_from_steps():
    assert "blk-steprail" in blocks.render_block("steprail", "1 | Fetch | detail | action")
    assert "blk-steprail" not in blocks.render_block("steps", "1 | Fetch | detail")


def test_steprail_distinguishes_an_action_from_a_check():
    out = blocks.render_block("steprail", "1 | Fetch | d | action\n2 | Confirm | d | check")
    assert "is-action" in out and "is-check" in out


def test_exactly_one_step_is_open_and_it_is_the_first():
    """Current position IS `details[open]`. A static `aria-current` was the first attempt
    and went stale the moment native disclosure moved `open` to another step."""
    out = blocks.render_block("steprail", "1 | a | d | action\n2 | b | d | check")
    assert out.count(" open>") == 1
    assert out.index(" open>") < out.index("blk-n\">2"), "the OPEN step must be the first"
    assert "aria-current" not in out, "a static current marker cannot track native open"


def test_steprail_content_is_complete_without_javascript():
    """A runbook that needs JS to be legible is worse than a plain one. Every step's
    detail is in the markup before any script runs."""
    out = blocks.render_block("steprail", "1 | Fetch | THE DETAIL | action")
    assert "THE DETAIL" in out
    assert "<script" not in out, "the block must not carry its own script"


def test_the_rail_needs_no_script_at_all():
    """Exclusivity is native `<details name=…>`. An inline script would also have been a
    second exception to this engine's documented uat-only CSP carve-out."""
    ctx = {}
    blocks.render_block("steprail", "1 | a | d | action", ctx=ctx)
    assert "steprail" in blocks.used_features(ctx)
    assert blocks.optional_js(blocks.used_features(ctx)) == ""


def test_a_rendered_rail_page_carries_no_script():
    page = render.render_artifact(
        "# T\n\n```steprail\n1 | Fetch | detail | action\n```\n",
        title="T", generated_at="2026-01-01 00:00 MST", style="workflow")
    assert "<script" not in page
    assert "<details" in page and "<summary" in page


def test_two_rails_on_one_page_share_one_group():
    """SUPERSEDED BY #61, owner decision 2026-08-02 — this test previously asserted the
    OPPOSITE, that two rails are independent groups.

    Its old rationale was that a shared name "would make opening a step in one rail close a
    step in the other — the exact bug a page-global script had". That conflated two different
    things. The old bug was a *script* going stale across rails; a shared `<details name>` is
    native exclusive disclosure, where closing a sibling is the defined behaviour, not a fault.

    Independence is what produced #61: a multi-stage runbook has one fence per stage, so every
    stage kept its own open step and the page showed several "current" positions at once. The
    owner chose option 3 — one group per document — accepting that opening a step in stage 3
    collapses what you were reading in stage 1.

    Rewritten to the new contract rather than deleted, so the reversal is visible to whoever
    reads this next. Full coverage lives in `test_single_current_step.py`.
    """
    page = render.render_artifact(
        "# T\n\n```steprail\n1 | a | d | action\n```\n\n```steprail\n2 | b | d | check\n```\n",
        title="T", generated_at="2026-01-01 00:00 MST", style="workflow")
    import re
    names = re.findall(r'<details name="([^"]+)"', page)
    assert len(names) == 2 and len(set(names)) == 1, f"rails no longer share a group: {names}"
    assert page.count(" open>") == 1, "exactly one step is current, page-wide"


def test_every_step_is_its_own_disclosure():
    out = blocks.render_block("steprail", "1 | a | d | action\n2 | b | d | check", ctx={})
    assert out.count("<details") == 2 and out.count(" open>") == 1


def test_an_unknown_step_kind_warns_rather_than_becoming_an_action(capsys):
    """`chek` silently becoming `action` turns a verification step into a do step."""
    out = blocks.render_block("steprail", "1 | Verify backup | d | chek")
    assert "is-action" not in out
    assert "chek" in capsys.readouterr().err


# --- steps gains an optional requirement level ------------------------------------------

def test_a_three_cell_steps_row_is_unchanged():
    assert "blk-level" not in blocks.render_block("steps", "R1 | title | text")


def test_steps_takes_an_optional_level():
    out = blocks.render_block("steps", "R1 | Reject it | Aborting beats guessing | must")
    assert "blk-level" in out and "is-must" in out


@pytest.mark.parametrize("level", ["must", "must-not", "should", "should-not", "may"])
def test_every_rfc2119_level_is_accepted(level):
    out = blocks.render_block("steps", f"R1 | t | x | {level}")
    assert f"is-{level}" in out


def test_an_unknown_level_warns_and_falls_back(capsys):
    out = blocks.render_block("steps", "R1 | t | x | banana")
    assert "is-banana" not in out
    assert "banana" in capsys.readouterr().err


# --- cross-cutting -----------------------------------------------------------------------

NEW_TAGS = ("timeline", "options", "steprail")


@pytest.mark.parametrize("tag", NEW_TAGS)
def test_each_new_tag_is_registered(tag):
    assert tag in blocks.BLOCK_TAGS and tag in blocks._RENDERERS


@pytest.mark.parametrize("tag", NEW_TAGS)
def test_a_literal_pipe_survives_in_every_new_prose_field(tag):
    body = {"timeline": r"09:14 | a \| b | c \| d | past",
            "options": r"a \| b | c \| d | e \| f | chosen",
            "steprail": r"1 | a \| b | c \| d | action"}[tag]
    out = blocks.render_block(tag, body)
    assert out.count("a | b") == 1, f"{tag} lost the escaped pipe"


@pytest.mark.parametrize("tag", NEW_TAGS)
def test_a_short_row_degrades_rather_than_rendering_lossily(tag):
    assert blocks.render_block(tag, "only-one-cell") is None


@pytest.mark.parametrize("tag", NEW_TAGS)
def test_new_tags_are_escaped_like_every_other(tag):
    out = blocks.render_block(tag, "<script>x</script> | b | c | d")
    assert "<script>x" not in out and "&lt;script&gt;" in out
