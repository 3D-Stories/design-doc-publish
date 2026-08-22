"""Hard-wrapped list items must stay inside their <li> (owner report, 2026-08-22).

Standard markdown allows a list item to wrap across lines, the follow-on lines
indented to the item's content column:

    - [The unified plan](...) — the decisions, the sprawl assessment, the
      prevention system, and §8b's full number map.

The rich renderer emitted the first line as a self-closed <li> and dropped the
continuation into a bare <p> BESIDE the list — measured live on the unified-roadmap
page, where every wrapped bullet split mid-sentence at the left margin.

Rich-mode only, like the other #16 list fixes: `plain` is frozen byte-for-byte and
keeps its old behavior, pinned here too.
"""
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render as render_artifact  # noqa: E402


def _render(md, style="roadmap"):
    return render_artifact.render_artifact(md, title="T", style=style,
                                           generated_at="2026-08-01 12:00 MDT")


WRAPPED = (
    "# Doc\n\n## Section\n\n"
    "- [A plan](https://example.com/) — the decisions, the assessment, the\n"
    "  prevention system, and the full number map.\n"
    "- second item stays its own bullet.\n"
)


def test_a_wrapped_item_joins_into_one_li():
    html = _render(WRAPPED)
    assert "prevention system, and the full number map.</li>" in html
    # the continuation must not become a paragraph beside the list
    assert "<p>prevention system" not in html


def test_the_join_is_a_single_space_soft_wrap():
    html = _render(WRAPPED)
    assert "the prevention system" in html


def test_the_next_bullet_is_still_its_own_item():
    html = _render(WRAPPED)
    assert "<li>second item stays its own bullet.</li>" in html


def test_a_blank_line_still_ends_the_list():
    md = "# D\n\n## S\n\n- only item\n\na real paragraph after the list.\n"
    html = _render(md)
    assert "<li>only item</li>" in html
    assert "<p>a real paragraph after the list.</p>" in html


def test_multiple_continuation_lines_all_join():
    md = ("# D\n\n## S\n\n- first line\n  second line\n  third line\n")
    html = _render(md)
    assert "<li>first line second line third line</li>" in html


def test_an_unindented_line_stays_a_paragraph():
    # Column-0 prose after a bullet is NOT a continuation — it ends the list.
    md = "# D\n\n## S\n\n- an item\nplain prose at column zero.\n"
    html = _render(md)
    assert "<li>an item</li>" in html
    assert "plain prose at column zero." in html
    assert "an item plain prose" not in html


def test_a_nested_bullet_is_not_swallowed_as_continuation():
    md = "# D\n\n## S\n\n- parent\n  - child\n"
    html = _render(md)
    assert "<li>child</li>" in html


def test_inline_markup_in_the_continuation_still_renders():
    md = "# D\n\n## S\n\n- head of item\n  tail with [a link](https://example.com/x).\n"
    html = _render(md)
    assert '<a href="https://example.com/x"' in html


def test_plain_stays_frozen_with_the_old_split():
    html = _render(WRAPPED, style="plain")
    # plain's contract is byte-stability, not correctness — the continuation
    # remains outside the <li> there, exactly as before this fix.
    assert "the</li>" in html
