"""`faq` — independent, closed-by-default disclosures (#57).

`steprail` was the only block emitting `<details>`, and it cannot produce this shape. Measured
against `main` when the issue was filed, and the reason is structural rather than incidental:

| shape | independent? | starts closed? |
|---|---|---|
| one multi-row `steprail` fence | no — one `name` per document, so opening one closes its siblings | all but the first |
| several one-row `steprail` fences | yes | no — each fence's single row is emitted `open` |

Neither reaches "independent AND closed by default", and `steprail`'s exclusivity is deliberate and
correct for a runbook rail. It is simply not a FAQ.

So the two attributes this block MUST NOT emit — `name` and `open` — are the whole point of it, and
the absence of each is pinned below. Absence assertions are dangerous on their own: they all pass
vacuously if the renderer emits no `<details>` at all. Every one here is therefore paired with a
positive assertion in the same test.
"""
import re
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render  # noqa: E402
from render import blocks  # noqa: E402

ROWS = ("Does it need a script? | No — native `<details>`, so it works with JS disabled.\n"
        "Can two be open at once? | Yes. Each item is independent.")
MD = f"# T\n\n```faq\n{ROWS}\n```\n"


def _page(style):
    return render.render_artifact(MD, title="T", style=style, generated_at="x")


class TestTheShapeSteprailCouldNotProduce:
    """The issue's whole reason for existing."""

    def test_one_disclosure_per_row_with_the_question_as_its_summary(self):
        out = blocks.render_block("faq", ROWS)
        assert out.count("<details") == 2, out
        assert out.count("<summary>") == 2
        assert "Does it need a script?" in out
        assert "Can two be open at once?" in out

    def test_the_items_are_independent_and_all_start_closed(self):
        """Both absences, each paired with the positive that stops it passing vacuously.

        `name` groups disclosures so opening one closes its siblings; `open` makes one start
        expanded. This block must emit neither, and no other test in the suite would notice if a
        later edit added them.
        """
        out = blocks.render_block("faq", ROWS)
        assert out.count("<details") == 2, "absence claims below are vacuous without this"
        # ATTRIBUTE-precise, not a bare substring: the fixture's second question deliberately
        # contains the word "open", so `"open" not in out` would fail on a correct renderer. The
        # same shape of mistake cost a cycle on #134 and on #133 before it.
        assert not re.search(r"<details[^>]*\bname=", out), \
            "a name attribute would make the items exclusive"
        assert not re.search(r"<details[^>]*\bopen\b", out), \
            "an open attribute would make an item start expanded"

    def test_the_answer_is_reachable_text_not_a_title_attribute(self):
        out = blocks.render_block("faq", ROWS)
        assert "native" in out and "independent" in out.lower()
        assert "title=" not in out


class TestItStaysNative:
    def test_a_rendered_faq_page_carries_no_script(self):
        """The engine's inline-script carve-out is `uat`-only, and this block does not need it."""
        page = _page("spec")
        assert "<details" in page, "no disclosure rendered, so the script claim proves nothing"
        assert "<script" not in page

    def test_the_summary_keeps_the_browsers_own_disclosure_marker(self):
        """`steprail` suppresses it because it supplies its own rail indicator. A FAQ has none, so
        the native triangle IS the affordance that says "clickable" — and keeping it costs no CSS
        and adds no generated content."""
        css = blocks.OPTIONAL_BLOCK_CSS["faq"]
        assert "list-style:none" not in css
        assert "::-webkit-details-marker" not in css


class TestTheAcceptMap:
    def test_spec_accepts_it(self):
        assert "faq" in blocks.accepts("spec")

    def test_rendering_it_under_spec_raises_no_not_accepted_warning(self, capsys):
        blocks.render_block("faq", ROWS, doc_type="spec")
        assert "not accepted" not in capsys.readouterr().err

    def test_analysis_does_not_accept_it(self, capsys):
        """Declined deliberately (#57 decision 3): `analysis` already builds a question/answer
        surface structurally in its section renderer, so a `faq` block there would give one doc
        type two ways to say the same thing."""
        assert "faq" not in blocks.accepts("analysis")


class TestContainment:
    def test_the_marker_reaches_spec(self):
        assert "blk-faq" in _page("spec")

    def test_it_never_reaches_plain(self):
        """`plain` leaves a typed fence as a code listing and never invokes the block engine."""
        page = _page("plain")
        assert "blk-faq" not in page
        assert "<details" not in page

    def test_hostile_cell_content_is_escaped_in_the_summary(self):
        out = blocks.render_block("faq", '<img src=x onerror=alert(1)> | plain answer')
        assert "<img" not in out
        assert "&lt;img" in out

    def test_a_payload_aimed_at_closing_the_summary_early_cannot(self):
        """Escape-first, so the payload is element TEXT rather than markup.

        `onerror=` and `onmouseover=` still appear as characters in the output — a naive grep for
        them reads as a vulnerability and is wrong. What matters is that `<` and `"` are escaped, so
        nothing is ever parsed as a tag or an attribute.
        """
        out = blocks.render_block("faq", '</summary><script>alert(1)</script> | a')
        assert "<script" not in out
        assert "&lt;/summary&gt;&lt;script&gt;" in out
        out2 = blocks.render_block("faq", '" onmouseover=alert(1) x=" | a')
        assert '"' not in out2.split("<summary>")[1].split("</summary>")[0]

    def test_hostile_content_in_the_ANSWER_is_escaped_too(self):
        """The answer cell is a second, equally reachable position. Pinned separately because a
        test that only covers the question passes while half the surface is unguarded."""
        out = blocks.render_block("faq", "q | <img src=x onerror=alert(1)>")
        assert "<img" not in out
        assert "&lt;img" in out

    @pytest.mark.parametrize("scheme", [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
    ])
    @pytest.mark.parametrize("cell", ["{link} | answer", "question | {link}"])
    def test_an_active_url_scheme_never_reaches_an_href_from_either_cell(self, scheme, cell):
        """Inline markdown runs in both cells, so a link is author-reachable in both.

        `_safe_url` (hardened by #122) is what stops this, and it was reaching this block already
        — but nothing asserted it did. This pins that it keeps reaching it, from either position.
        """
        out = blocks.render_block("faq", cell.format(link=f"[x]({scheme})"))
        assert "<script" not in out
        for bad in ('href="javascript:', 'href="data:', 'href="vbscript:'):
            assert bad not in out, f"{bad} survived in: {out}"

    def test_an_empty_fence_degrades_rather_than_emitting_an_empty_wrapper(self):
        assert blocks.render_block("faq", "") is None

    def test_blank_cells_render_blank_rather_than_being_rejected(self):
        """Deliberately NOT a rejection, and the reason matters.

        A cross-model review recommended requiring both cells to be non-empty. Declined: `chips`,
        `options` and `timeline` all render blank cells blank, and inventing an exception for this
        one tag would make the grammar less predictable, not safer. Two blank FIELDS still satisfy
        the arity check; a missing field does not, and that case degrades (above). Measured against
        the siblings before declining.
        """
        out = blocks.render_block("faq", " | an answer")
        assert "<summary></summary>" in out
        assert "an answer" in out

    def test_a_one_field_row_degrades_the_block_to_a_code_listing(self):
        """Proves the arity registration actually binds.

        `_MIN_CELLS`/`_MAX_CELLS` was one of the seven registration surfaces, and the one most
        easily forgotten — it was in fact missed on the first pass here and surfaced as a KeyError.
        A tag absent from those maps raises rather than degrading, so this is the test that would
        have caught it.
        """
        page = render.render_artifact("# T\n\n```faq\njust a question\n```\n",
                                      title="T", style="spec", generated_at="x")
        assert "<pre><code>" in page
        assert "<details" not in page
