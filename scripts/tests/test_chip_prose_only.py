"""A section's status chip reads the author's PROSE, never a typed block's cells (#90).

Chips were resolved against the section's raw source — fences and all — so any section merely
CONTAINING a completion word published a status nobody wrote. Measured on a real page rendered
2026-08-02:

    ## Phases                      ->  COMPLETE   (a phase band's state badge says `complete`)
    ## Composition across the epic ->  MERGED     (a composition row is labelled `merged`)
    ## Risks                       ->  DONE       (prose inside a findings row)

`Risks [DONE]` is the dangerous one: it asserts the risks are handled.

The distinction the fix draws: a typed block's cells are **data the author wrote about the
work**; the section's prose is **the author's claim about the section**. Only the second may set
the chip. Same family as #21 — a chip stating something the author never said — so #21's
negation handling is re-asserted here to prove it survived.

**Everything asserts on the emitted chip SPAN, never a bare class name.** The `.c-conf` CSS rule
ships on every roadmap, dashboard and analysis page, so `"c-conf" in html` can never fail.

**Everything drives the real renderer.** The fix lives in `render_sections`, at the one line that
hands a body to a chip resolver, so a test calling a resolver directly would prove nothing about
the page. That placement is deliberate: it fixes `analysis`'s `confidence_chip` by the same line,
which the roadmap and analysis docstrings both describe as the sibling of this defect.
"""
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render as render_artifact  # noqa: E402

FIXED_TS = "2026-07-04 17:05 MST"

CHIP = re.compile(r'<span class="chip (c-[\w-]+)[^"]*">([^<]*)</span>')

NEUTRAL_STATUS = ("c-plan", "—")
NEUTRAL_CONF = ("c-unstated", "—")


def _chips(md, style):
    """Every chip the rendered page actually emits, as (css_class, label) in order."""
    html = render_artifact.render_artifact(
        md, title="Test Doc", generated_at=FIXED_TS, style=style)
    return CHIP.findall(html)


def _chip(md, style):
    """The one section chip on a single-section page."""
    found = _chips(md, style)
    assert found, f"no chip emitted at all for style={style}"
    return found[0]


# The three cases measured on the real page, in the shape they were measured.

PHASES = """## Phases

```phases
Wave 1 | complete | the machinery
Wave 2 | in flight | the art
```
"""

COMPOSITION = """## Composition across the epic

```composition
merged | 31 | done
open | 3 | active
```
"""

RISKS = """## Risks

```findings
schema drift | the migration is done and cannot be replayed
```
"""


class TestTheReportedCases:
    """Each of these three published a status its author never wrote."""

    def test_phases_section_is_not_complete(self):
        assert _chip(PHASES, "roadmap") == NEUTRAL_STATUS

    def test_composition_section_is_not_merged(self):
        assert _chip(COMPOSITION, "roadmap") == NEUTRAL_STATUS

    def test_risks_section_is_not_done(self):
        # The dangerous one: a DONE chip beside "Risks" asserts they are handled.
        assert _chip(RISKS, "roadmap") == NEUTRAL_STATUS


class TestBothStylesThatShareTheResolver:
    def test_dashboard_carries_the_same_fix(self):
        assert _chip(RISKS, "dashboard") == NEUTRAL_STATUS

    def test_the_block_content_still_renders(self):
        # Stripping the fence from the SCAN must not strip it from the PAGE.
        html = render_artifact.render_artifact(
            RISKS, title="T", generated_at=FIXED_TS, style="roadmap")
        assert "schema drift" in html


class TestTheSiblingResolver:
    """`analysis` passes `confidence_chip`, and it had the same defect.

    Its own docstring calls this "the sibling `chip_resolver` defect that `roadmap` and
    `dashboard` carry". Fixing at the shared call site rather than inside
    `roadmap_status_chip` is what reaches it, so it is pinned here.
    """

    def test_a_fenced_measured_is_not_the_authors_confidence(self):
        md = ("## Is the ceiling real?\n\n"
              "```callout\nnote | Throughput\nMeasured at 4k rps on the live host.\n```\n")
        assert _chip(md, "analysis") == NEUTRAL_CONF

    def test_analysis_prose_still_sets_confidence(self):
        md = "## Is the ceiling real?\n\nMeasured on the live host.\n"
        assert _chip(md, "analysis")[0] == "c-measured"


class TestProseStillDrivesTheChip:
    """AC2: the fix must not make the chip deaf to what the author actually wrote."""

    def test_prose_saying_done_still_chips_done(self):
        md = "## Slot 12 — telemetry\n\n**Status.** PR #198 merged, DONE."
        assert _chip(md, "roadmap") == ("c-conf", "DONE")

    def test_prose_outside_a_fence_wins_over_the_fence(self):
        md = ("## Slot 12\n\n"
              "```phases\nWave 1 | blocked | x\n```\n\n"
              "All shipped. DONE.\n")
        assert _chip(md, "roadmap") == ("c-conf", "DONE")

    def test_a_definitive_heading_still_wins(self):
        # #40's precedence rule is untouched: the author states it in the heading.
        md = "## Slot 11 — ABANDONED per AC4\n\n```meter\nmerged | 3\n```\n"
        assert _chip(md, "roadmap")[0] == "c-defer"

    def test_negation_survives(self):
        # #21 must stay intact through this change.
        assert _chip("## Slot 3\n\nThe work is not done.\n", "roadmap") == NEUTRAL_STATUS


class TestFenceEdges:
    def test_an_unclosed_fence_is_treated_as_prose(self):
        # `_render_body_plain` renders an unclosed fence's remainder as normal text and
        # warns. The scanner must agree with what the reader sees, so this DONE counts.
        md = "## Slot 4\n\n```phases\nWave 1 | x | y\n\nAll shipped. DONE.\n"
        assert _chip(md, "roadmap") == ("c-conf", "DONE")

    def test_a_fence_info_string_is_not_prose(self):
        # The word lives on the fence line itself, which is markup, not the author's claim.
        assert _chip("## Slot 5\n\n```done\nx\n```\n", "roadmap") == NEUTRAL_STATUS

    def test_two_fences_with_prose_between_them(self):
        md = ("## Slot 6\n\n"
              "```meter\nmerged | 2 | 9\n```\n\n"
              "Still under review.\n\n"
              "```findings\nhigh | Rollback | shipped already, so revert first\n```\n")
        assert _chip(md, "roadmap") == NEUTRAL_STATUS

    def test_an_indented_fence_still_closes(self):
        # The h2 boundary scan matches fences on the STRIPPED line, so an indented fence
        # opens and closes. The chip scan uses the same rule or the two disagree.
        md = "## Slot 7\n\n  ```meter\n  merged | 2 | 9\n  ```\n\nnothing stated here\n"
        assert _chip(md, "roadmap") == NEUTRAL_STATUS

    def test_a_section_of_pure_prose_is_unaffected(self):
        # No fence at all: the fix must be a no-op on the common case.
        md = "## Slot 8\n\nThis one shipped last week.\n"
        assert _chip(md, "roadmap") == ("c-conf", "SHIPPED")
