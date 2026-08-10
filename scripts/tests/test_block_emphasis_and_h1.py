"""Emphasis inside typed blocks, and the duplicate `<h1>` (#67).

Both were found by opening a published page and reading it, after four rounds of structural
measurement had reported it healthy. The most prominent callout on that page said
`**two epic premises have gone stale**` to the reader, asterisks and all.

**Why render rather than warn.** #67 leaves the choice open — render the emphasis, or warn and
keep printing it literally. Rendering, because the visual spec approved in #72 depends on it:
its alert bands, item rows and stop callouts all carry a bolded lead-in, and rule 6 of that spec
says in terms that a body which cannot bold a word cannot use the vocabulary. A warning would
have satisfied the letter of AC1 and left the engine unable to emit the design it was just told
to emit.

**Escaping is not weakened to do it.** The inline pass runs on text that is ALREADY
`html.escape`d and only ever wraps it in a fixed set of tags, which is the same contract prose
has had all along — `_inline` is literally the function prose uses. Author text still cannot
reach a class attribute or open a tag; `test_author_text_cannot_inject_markup` pins that.

`plain` cannot be affected: `blocks.render_fence` is reached only when `rich` is true.
"""
import hashlib
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render  # noqa: E402

PLAIN_SHA_AFTER_73 = "c87d0fba0b6549879163701b185b07b19e6a59f95ac05129ca2c809c781ef009"  # re-pinned by #24


def _page(md, title="A page", style="roadmap"):
    return render.render_artifact(md, title=title, generated_at="x", style=style)


CALLOUT = """# A page

```callout
note | A **bold** title?
Detail with **bold** and *italic*.
```
"""

FINDINGS = """# A page

```findings
high | A finding | Detail with **bold** here.
```
"""


class TestEmphasisRendersInsideTypedBlocks:
    """AC1 + AC2 — the three places #67 measured."""

    def test_a_callout_title_bolds(self):
        assert "<strong>bold</strong> title?" in _page(CALLOUT)

    def test_a_callout_body_bolds_and_italicises(self):
        page = _page(CALLOUT)
        assert "<strong>bold</strong>" in page
        assert "<em>italic</em>" in page

    def test_a_findings_detail_bolds(self):
        assert "<strong>bold</strong>" in _page(FINDINGS, style="review")

    def test_no_literal_asterisks_survive(self):
        """The symptom as the reader met it."""
        assert "**" not in _page(CALLOUT)


class TestEscapingIsUnchanged:
    def test_author_text_cannot_inject_markup(self):
        md = "# A page\n\n```callout\nnote | <script>alert(1)</script>\nA <b>raw</b> tag.\n```\n"
        page = _page(md)
        assert "<script>" not in page
        assert "&lt;script&gt;" in page
        assert "<b>raw</b>" not in page

    def test_code_content_stays_verbatim(self):
        md = "# A page\n\n```\nliteral **not bold** here\n```\n"
        assert "**not bold**" in _page(md)


class TestOneH1:
    """AC3.

    The issue's own diagnosis is the fix: *an exact-string match is the wrong test for "is this
    the same heading"*. So an abbreviated title is recognised as the same heading and dropped —
    one `<h1>`, silently, because nothing surprising happened. A genuinely different heading is
    still the author's and still survives, but it warns that the page will carry two.
    """

    def test_identical_heading_yields_one_h1(self):
        assert _page("# My Title\n\nbody\n", title="My Title").count("<h1") == 1

    def test_the_issues_own_abbreviated_case_yields_one_h1(self):
        md = "# Backlog re-evaluation — epics E1 to E5, after the audit\n\nbody\n"
        assert _page(md, title="Backlog re-evaluation — epics E1 to E5").count("<h1") == 1

    def test_abbreviation_is_recognised_in_either_direction(self):
        assert _page("# Short\n\nbody\n", title="Short, expanded for the page").count("<h1") == 1

    def test_case_and_spacing_do_not_make_it_a_different_heading(self):
        assert _page("#   my   title\n\nbody\n", title="My Title").count("<h1") == 1

    def test_an_abbreviated_heading_drops_silently(self, capsys):
        md = "# Backlog re-evaluation — epics E1 to E5, after the audit\n\nbody\n"
        _page(md, title="Backlog re-evaluation — epics E1 to E5")
        assert capsys.readouterr().err == ""

    def test_a_genuinely_different_heading_survives_but_warns(self, capsys):
        """It is the author's own heading, so it stays — the defect was the SILENCE."""
        page = _page("# Different Heading\n\nbody\n", title="Doc Title")
        assert page.count("<h1") == 2
        assert "two h1" in capsys.readouterr().err.lower()

    def test_a_non_leading_h1_is_left_alone(self):
        """Only the LEADING heading is the title restated; a later one is content."""
        md = "# A page\n\nbody\n\n# A second top-level heading\n\nmore\n"
        assert _page(md, title="A page").count("<h1") == 2


class TestPlainIsUnreachable:
    def test_plain_bytes_are_untouched(self):
        got = render.render_artifact("# T\n\nbody\n", title="T", style="plain", generated_at="x")
        assert hashlib.sha256(got.encode()).hexdigest() == PLAIN_SHA_AFTER_73

    def test_plain_leaves_a_fence_as_a_code_listing(self):
        assert "**bold**" in render.render_artifact(
            CALLOUT, title="A page", style="plain", generated_at="x")
