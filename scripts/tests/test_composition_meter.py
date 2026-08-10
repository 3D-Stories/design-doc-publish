"""The segmented composition meter (#68, PR 1 of lane B5).

The `roadmap` style has no roadmap. #40 gave it components — `timeline`, `stats`, `meter`,
`legend`, `findings`, `nodes` — and it still could not show sequence, phase or progress
composition at a glance. The owner, looking at a hand-built page beside a rendered one:
*"its kinda fucked up that the roadmap doesnt actually have a roadmap/milestone diagram"*.

This PR delivers the device the approved visual spec calls the signature one
(`docs/planning/2026-08-02-72-visual-spec.md`, §2): **a bar showing what a total is MADE OF, not
one percentage.** The existing `meter` is single-value — it can say `3 / 9` but never what the
nine are. That is the specific gap the issue names.

A NEW block type rather than a role on `meter`, so `meter`'s bytes cannot move and only the
styles that accept `composition` change at all.

Grammar: `label | count | state`, one row per group. Segments are proportional to count and
coloured by state; the legend counts each group. Deliberately NOT a percentage — the whole point
is the parts.
"""
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render  # noqa: E402
from render import blocks  # noqa: E402

DOC = """# T

```composition
critical | 1 | crit
unresolved | 2 | warn
ready | 4 | ok
```
"""


def _page(style="roadmap", md=DOC):
    return render.render_artifact(md, title="T", style=style, generated_at="x")


class TestItShowsWhatTheTotalIsMadeOf:
    def test_one_segment_per_group(self):
        assert _page().count('<span class="blk-comp-seg') == 3

    def test_segments_are_proportional_to_their_counts(self):
        """1 : 2 : 4 of a total of 7."""
        page = _page()
        for pct in ("14.3%", "28.6%", "57.1%"):
            assert pct in page, pct

    def test_each_group_carries_its_state_not_a_colour(self):
        page = _page()
        for state in ("is-crit", "is-warn", "is-ok"):
            assert state in page, state

    def test_the_legend_counts_every_group(self):
        page = _page()
        assert "1 critical" in page.lower()
        assert "2 unresolved" in page.lower()
        assert "4 ready" in page.lower()

    def test_a_single_group_fills_the_bar(self):
        md = "# T\n\n```composition\nall done | 5 | ok\n```\n"
        assert "100.0%" in _page(md=md)


class TestItFailsSafely:
    def test_a_non_numeric_count_warns_and_does_not_emit_a_bar(self, capsys):
        md = "# T\n\n```composition\nbroken | many | ok\n```\n"
        page = _page(md=md)
        assert "composition" in capsys.readouterr().err.lower()
        assert '<span class="blk-comp-seg' not in page

    def test_a_zero_total_does_not_divide_by_zero(self):
        md = "# T\n\n```composition\nnone | 0 | ok\n```\n"
        page = _page(md=md)
        assert 'class="blk-comp"' in page

    def test_author_text_cannot_reach_a_class_attribute(self):
        md = '# T\n\n```composition\n<script>x</script> | 1 | ok"><b>\n```\n'
        page = _page(md=md)
        assert "<script>" not in page
        assert '"><b>' not in page


class TestItIsScopedToTheStylesThatAcceptIt:
    def test_roadmap_accepts_it(self):
        assert "composition" in blocks.DOC_TYPE_TAGS["roadmap"]

    def test_a_style_that_does_not_accept_it_warns(self, capsys):
        _page(style="spec")
        assert "not accepted" in capsys.readouterr().err.lower()

    def test_plain_leaves_it_as_a_code_listing(self):
        assert 'class="blk-comp' not in _page(style="plain")
