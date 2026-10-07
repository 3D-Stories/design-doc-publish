"""Requirement cards never run past a phone-width page (#78, folded in by the owner).

The cards sit in a grid list. Its one implicit column was as wide as the widest card, and each
card's text track was `1fr`, whose minimum is the text's own unbreakable width. So one long word
stretched EVERY card in that list, and a real spec page was 369 px wide on a 360 px screen. It
was already so at 5.3.0. The acceptance rows had the same `auto 1fr` shape on their own.

These tests pin the rules that fix it. The width itself was measured in a real browser, on that
page and on a probe with a long code span in a card title, an unbreakable snake_case word in card
text, and a long code span in an acceptance row: each 360 px wide after, with every card title
still at the same x. A DOM-free pytest cannot lay out a grid, so it pins the rules rather than
re-implementing layout. `_decl` splits on braces and does not model `@media`: it reads the first
matching declaration it finds, so it suits rules that no `@media` block overrides, as these are.
"""
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render  # noqa: E402


def _rules():
    page = render.render_artifact("# Spec probe\n\nBody.\n", title="Spec probe", style="spec",
                                  generated_at="2026-01-01 00:00 MST")
    css = re.sub(r"/\*.*?\*/", "", page.split("<style>")[1].split("</style>")[0], flags=re.S)
    return [(r.split("{")[0].strip(), r.split("{", 1)[1]) for r in css.split("}") if "{" in r]


def _decl(selector, prop):
    for sel, body in _rules():
        if selector in [s.strip() for s in sel.split(",")]:
            m = re.search(re.escape(prop) + r"\s*:\s*([^;]+)", body)
            if m:
                return m.group(1).strip()
    return None


def test_the_card_list_column_may_shrink_below_its_widest_card():
    assert _decl(".tpl-spec .sp-req ol", "grid-template-columns") == "minmax(0,1fr)"


def test_the_card_text_track_may_shrink_below_its_longest_word():
    """The fixed 92px gutter stays first (the #40 T7 alignment rule); only the text track changes."""
    assert _decl(".tpl-spec .sp-req .blk-step", "grid-template-columns") == "92px minmax(0,1fr)"


def test_a_long_word_in_a_card_title_or_text_can_wrap():
    """`overflow-wrap` is inherited, so it reaches code, links and emphasis inside the cell."""
    for cell in (".tpl-spec .sp-req .blk-title", ".tpl-spec .sp-req .blk-text"):
        assert _decl(cell, "overflow-wrap") == "anywhere", cell


def test_acceptance_rows_get_a_shrinkable_text_track_and_a_capped_id_column():
    """`auto` let a long acceptance ID take the whole row and squeeze the title to 0px (measured
    by the second repair verifier). The ID column is capped at half the row instead."""
    assert (_decl(".tpl-spec .sp-ac .blk-step", "grid-template-columns")
            == "fit-content(50%) minmax(0,1fr)")
    for cell in (".tpl-spec .sp-ac .blk-title", ".tpl-spec .sp-ac .blk-text"):
        assert _decl(cell, "overflow-wrap") == "anywhere", cell


def test_a_long_acceptance_id_or_level_wraps_inside_its_column():
    for cell in (".tpl-spec .sp-ac .blk-n", ".tpl-spec .sp-ac .blk-level"):
        assert _decl(cell, "max-width") == "100%", cell
        assert _decl(cell, "overflow-wrap") == "anywhere", cell
