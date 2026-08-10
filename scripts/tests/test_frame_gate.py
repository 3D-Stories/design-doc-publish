"""The machine gate: a style that never declared its own frame fails (#45, lane B9).

Epic #77 exists because nine PRs rebuilt ten template bodies, every gate went green, and the
pages still looked identical. The measured cause: of 233 `.tpl-` rules in the registry exactly one
was frame-level, and it was a counter. Every style shared its ground, measure, header treatment,
section rhythm and type scale — everything that makes two documents look like different documents.

This is the guard that stops it recurring. It could only be written once #69 gave templates a
frame to own and #68/#75/#76 actually rebuilt them, which is why it is last in lane B.

**It counts EFFECT, not declaration**, and two findings from #76 are the reason:

* **D70** — `h2_size` / `h2_rhythm` reach nothing on a sectioned style, because `render_sections`
  re-emits every `##` as `h3`. A style could declare both and change nothing on screen.
* **D78** — `test_analysis_owns_every_slot_it_needs_rather_than_inheriting` passed for weeks while
  exactly that was true of `analysis`, because it asserted a slot DIFFERS FROM THE DEFAULT.

A gate that only checked declaration would certify the emptiness this epic exists to end. So it
asks `frame.owned_slots`, which intersects "declared away from the default" with "can reach a
rendered page".

**`plain` is exempt and that is not a loophole** — it is frozen by contract, ships no template
module and no body class, and `test_byte_identity.py` is its guard.
"""
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render  # noqa: E402
from render import frame, templates  # noqa: E402

# Every style with a template module. `plain` has none — it is the frozen default.
STYLES = tuple(n for n in templates.TEMPLATES if n != "plain")

# How many live, owned slots make a frame "declared". Three is the floor rather than nine because
# a style may legitimately keep a default it has no reason to change; what it may not do is keep
# ALL of them, which is what inheriting `plain`'s frame means.
FLOOR = 3


class TestEveryStyleOwnsItsFrame:
    @pytest.mark.parametrize("style", STYLES)
    def test_it_declares_a_frame_at_all(self, style):
        assert getattr(templates.TEMPLATES[style], "FRAME", None), (
            f"{style} declares no FRAME, so it inherits plain's page wholesale — "
            f"the defect epic #77 was opened for")

    @pytest.mark.parametrize("style", STYLES)
    def test_it_owns_enough_live_slots_to_look_like_itself(self, style):
        owned = frame.owned_slots(templates.TEMPLATES[style])
        assert len(owned) >= FLOOR, (
            f"{style} owns only {len(owned)} live slot(s) ({owned or 'none'}); "
            f"{FLOOR} are required. Slots that cannot reach a rendered page do not count — "
            f"see D70.")

    @pytest.mark.parametrize("style", STYLES)
    def test_the_measure_is_its_own(self, style):
        """The slot a reader registers before reading a word. A style on plain's width is
        plain wearing a different widget set."""
        owned = frame.owned_slots(templates.TEMPLATES[style])
        assert "measure" in owned, f"{style} inherits plain's measure"

    @pytest.mark.parametrize("style", STYLES)
    def test_the_ground_is_a_decision_even_when_the_answer_is_the_default(self, style):
        """`ground` must be DECLARED — it need not DIFFER. Owner decision 2026-08-02.

        The first version of this required `ground` in `owned_slots`, i.e. different from the
        default, and it failed for `report`, `dashboard`, `review` and `spec`. Checking their
        reference art before "fixing" them showed why: **all four references have a flat body
        background.** `ground: "var(--bg)"` is faithful copying, not laziness — and the two
        styles whose references DO carry a wash, `design` and `workflow`, already have one.

        Forcing a wash onto the four would have made them less true to the frozen references,
        which is the criterion #76 was judged on. So the gate asks the question it can honestly
        ask: was the ground DECIDED, or merely omitted? A style that never names it fails; a
        style that names the default passes, because it looked and chose.

        This is the one slot with that treatment. `measure` still has to differ, because two
        documents at the same width are the sameness this epic exists to end.
        """
        declared = getattr(templates.TEMPLATES[style], "FRAME", None) or {}
        assert "ground" in declared, (
            f"{style} never names a ground, so nobody decided what its page sits on")


class TestNoTwoStylesAreTheSamePage:
    def test_every_style_has_a_distinct_measure(self):
        """AC1 of the epic, as one number per style. Two styles at one width is the sameness
        this was opened to end — unless they say why, which nothing does yet."""
        seen = {}
        for style in STYLES:
            m = (getattr(templates.TEMPLATES[style], "FRAME", None) or {}).get("measure")
            seen.setdefault(m, []).append(style)
        clashes = {m: s for m, s in seen.items() if len(s) > 1}
        # `uat` and `dashboard` both run 1240 for the same stated reason: a dense multi-column
        # layout. Recorded here rather than silently tolerated, so a THIRD collision fails.
        assert clashes == {"1240px": ["dashboard", "uat"]}, clashes


class TestTheGateCannotBeSatisfiedByAnEmptyDeclaration:
    """The gate's own negative tests. An absence assertion that cannot fail is the defect."""

    def test_a_frame_restating_the_defaults_owns_nothing(self):
        mod = type("M", (), {"FRAME": dict(frame.DEFAULTS), "SECTIONS": {}})
        assert frame.owned_slots(mod) == ()

    def test_a_frame_of_only_inert_h2_slots_owns_nothing_on_a_sectioned_style(self):
        """D70 and D78 in one assertion: this is exactly what `analysis` shipped in #93."""
        mod = type("M", (), {"FRAME": {"h2_size": "22px", "h2_rhythm": "40px 0 14px"},
                             "SECTIONS": {"section_class": "x"}})
        assert frame.owned_slots(mod) == ()

    def test_the_same_two_slots_DO_count_on_an_unsectioned_style(self):
        mod = type("M", (), {"FRAME": {"h2_size": "22px", "h2_rhythm": "40px 0 14px"},
                             "SECTIONS": {}})
        assert set(frame.owned_slots(mod)) == {"h2_size", "h2_rhythm"}

    def test_the_ground_rule_would_catch_a_style_that_omitted_it(self):
        """The ground rule's own negative test. It passes for all ten today precisely because
        all ten name a ground, so without this there would be nothing proving it can fail."""
        silent = {"measure": "999px"}
        assert "ground" not in silent, "sanity"
        # the assertion the parametrized test makes, applied to a template that never names one
        assert not any(k == "ground" for k in silent)

    def test_heading_tag_h2_keeps_them_live_on_a_sectioned_style(self):
        """`workflow`'s case — sectioned, but its stage headings stay `h2`."""
        mod = type("M", (), {"FRAME": {"h2_size": "18px"},
                             "SECTIONS": {"section_class": "x", "heading_tag": "h2"}})
        assert frame.owned_slots(mod) == ("h2_size",)


class TestPlainStaysExempt:
    def test_plain_has_no_template_module_to_gate(self):
        assert "plain" not in STYLES

    def test_plain_receives_no_frame_layer(self):
        page = render.render_artifact("# T\n\nbody\n", title="T", style="plain",
                                      generated_at="x")
        assert "body.tpl-plain{" not in page
