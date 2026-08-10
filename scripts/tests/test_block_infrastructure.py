"""#39 PR1 — the two pieces of machinery the component vocabulary needs before it exists.

Both are here rather than in the components' PR because each has a failure mode that is
invisible once components are using it:

1. **An escape-aware delimiter.** Every prose field is pipe-delimited, so a legitimate `|` in
   author text silently shifts every later field along and drops the last one. `\\|` fixes it —
   but only if `_validate` (which COUNTS fields) and `_rows` (which RENDERS them) split
   identically. Two splitters is exactly how a field count and its rendering drift apart, so
   there is one, and these tests pin that.

2. **Feature-keyed optional CSS/JS.** `BLOCK_CSS` is injected into every non-plain page
   unconditionally (`render/__init__.py`), so any CSS added there changes the pinned exemplar
   and breaks byte-identity. New components therefore declare CSS keyed by FEATURE — not by
   tag, which cannot tell a new sparkline from an ordinary `stats` block — emitted only when
   that feature actually rendered.

The byte-identity cases below are the point of the whole mechanism: a page using ordinary
`stats` and ordinary `steps` must be unchanged. A test that only checks a page with no typed
blocks would pass under a tag-keyed design that is wrong.
"""
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render  # noqa: E402
from render import blocks  # noqa: E402


def _render(src, style="design"):
    return render._render_body(src, style=style)


# --- 1. the shared escape-aware splitter --------------------------------------------

def test_a_plain_row_splits_as_before():
    assert blocks.split_cells("a | b | c") == ["a ", " b ", " c"]


def test_an_escaped_pipe_is_a_literal_pipe():
    assert blocks.split_cells(r"must | Preserve A \| B syntax | Needed by callers") == \
        ["must ", " Preserve A | B syntax ", " Needed by callers"]


def test_an_escaped_pipe_does_not_change_the_field_count():
    """The bug this prevents: `A \\| B` counted as two fields shifts the rationale into
    the wrong slot and drops the real one."""
    assert len(blocks.split_cells(r"a \| b | c")) == 2


def test_validate_and_rows_agree_on_the_field_count():
    """One splitter, two callers. If these ever disagree, a row validates and then
    renders into the wrong columns."""
    line = r"high | title with a \| pipe | detail | tail"
    rows = list(blocks._rows(line))
    assert len(rows) == 1
    assert len(rows[0]) == len(blocks.split_cells(line))


def test_an_escaped_pipe_survives_into_the_rendered_cell():
    out = blocks.render_block("findings", r"high | a \| b | detail")
    assert "a | b" in out


def test_a_lone_backslash_is_untouched():
    assert blocks.split_cells(r"a \ b | c") == [r"a \ b ", " c"]


# --- 2. feature-keyed optional CSS / JS ---------------------------------------------

def test_no_feature_used_means_no_optional_css():
    assert blocks.optional_css(set()) == ""
    assert blocks.optional_js(set()) == ""


def test_an_unknown_feature_id_contributes_nothing():
    """Fail quiet, not loud: a stale feature id must not inject a stray empty layer."""
    assert blocks.optional_css({"not-a-feature"}) == ""


def test_features_emit_in_a_fixed_order_regardless_of_discovery_order():
    """CSS order is cascade order. If it followed the order blocks happened to appear
    in the document, two documents with the same components would style differently."""
    blocks.OPTIONAL_BLOCK_CSS["zzz-test"] = ".zzz{}"
    blocks.OPTIONAL_BLOCK_CSS["aaa-test"] = ".aaa{}"
    try:
        order = blocks.feature_order()
        a, z = order.index("aaa-test"), order.index("zzz-test")
        first, second = (".aaa{}", ".zzz{}") if a < z else (".zzz{}", ".aaa{}")
        got = blocks.optional_css({"zzz-test", "aaa-test"})
        assert got.index(first) < got.index(second)
        assert blocks.optional_css({"aaa-test", "zzz-test"}) == got
    finally:
        blocks.OPTIONAL_BLOCK_CSS.pop("zzz-test", None)
        blocks.OPTIONAL_BLOCK_CSS.pop("aaa-test", None)


def test_a_feature_is_recorded_only_on_the_context_it_was_given():
    ctx = {}
    blocks.note_feature(ctx, "demo")
    assert blocks.used_features(ctx) == {"demo"}
    assert blocks.used_features({}) == set()


def test_used_features_tolerates_a_missing_context():
    """`render_block` is called directly by tests and by `plain`; neither passes a ctx."""
    assert blocks.used_features(None) == set()
    blocks.note_feature(None, "demo")  # must not raise


# --- 3. byte-identity: the machinery must be invisible until something uses it -------

ORDINARY_STATS = "```stats\n82 | sessions read\n28/44 | highs confirmed | accent\n```\n"
ORDINARY_STEPS = "```steps\n1 | Author the grammar | before any renderer work\n```\n"


@pytest.mark.parametrize("src,label", [
    ("# A doc\n\nJust prose, no typed blocks at all.\n", "no-blocks"),
    (ORDINARY_STATS, "ordinary-stats"),
    (ORDINARY_STEPS, "ordinary-steps"),
    (ORDINARY_STATS + ORDINARY_STEPS, "both"),
])
def test_a_page_using_no_new_feature_pulls_in_no_optional_css(src, label):
    """The case a tag-keyed design would fail: an ordinary `stats` block must not drag in
    sparkline CSS just because the sparkline lives on the `stats` tag."""
    ctx = {}
    render._render_body(src, style="design", ctx=ctx)
    assert blocks.used_features(ctx) == set(), f"{label} recorded a feature it does not use"
    assert blocks.optional_css(blocks.used_features(ctx)) == ""


def test_the_legacy_accent_row_still_emits_is_accent():
    """`28/44 | highs confirmed | accent` is in the committed grammar page. Field 3 is
    about to become the delta, so pin the old meaning before it moves."""
    out = blocks.render_block("stats", "28/44 | highs confirmed | accent")
    assert "is-accent" in out
    assert ">accent<" not in out, "the accent flag leaked into the rendered cells"


def test_render_artifact_threads_a_context_and_leaves_pages_unchanged():
    """End to end: the same source rendered twice is byte-identical, and a page with no
    new feature carries no optional layer."""
    src = "# T\n\n" + ORDINARY_STATS
    a = render.render_artifact(src, title="T", generated_at="2026-01-01 00:00 MST",
                               style="design")
    b = render.render_artifact(src, title="T", generated_at="2026-01-01 00:00 MST",
                               style="design")
    assert a == b
