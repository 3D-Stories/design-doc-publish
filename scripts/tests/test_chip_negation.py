"""Negated status and confidence words stop reading as their opposite (#21, absorbing #55).

`status_chip` scanned for "done" and `confidence_chip` for "measured", both word-boundary
matched and neither looking left. So a section saying **"not done"** got a green DONE chip and
one saying **"not measured"** got a MEASURED chip — the chip asserting the opposite of the
sentence it sits next to. Two functions, one defect, which is why #55 folded into #21.

A negated keyword is SKIPPED and the scan continues, rather than returning neutral on the spot:
"not done, in progress" should land on IN PROGRESS, which is what the sentence says. Only when
nothing survives the scan does the neutral chip appear — and a neutral chip is the honest answer
to "not done" on its own, because that text says what the state is not, never what it is.
"""
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

from render.markdown import confidence_chip, roadmap_status_chip, status_chip  # noqa: E402

NEUTRAL_STATUS = ("c-plan", "—")
NEUTRAL_CONF = ("c-unstated", "—")


class TestStatusNegation:
    def test_the_reported_case(self):
        assert status_chip("not done") == NEUTRAL_STATUS

    def test_every_negator_form(self):
        for text in ("not done", "is not done", "isn't done", "not yet done",
                     "never done", "no longer blocked", "cannot be done",
                     "won't be shipped", "hasn't merged"):
            assert status_chip(text) != ("c-conf", "DONE"), text
            assert status_chip(text)[1] not in ("SHIPPED", "MERGED", "COMPLETE"), text

    def test_an_unnegated_keyword_is_untouched(self):
        assert status_chip("done") == ("c-conf", "DONE")
        assert status_chip("shipped last week") == ("c-conf", "SHIPPED")
        assert status_chip("blocked on review") == ("c-defer", "BLOCKED")

    def test_the_scan_continues_past_a_negated_word(self):
        """The sentence still says what the state IS; do not throw that away."""
        assert status_chip("not done, in progress") == ("c-plan", "IN PROGRESS")

    def test_not_started_is_a_vocabulary_entry_not_a_negation(self):
        """`not started` is itself a status word — the negator IS the keyword's first word,
        so nothing precedes it and it must survive."""
        assert status_chip("not started") == ("c-plan", "NOT STARTED")

    def test_a_negator_in_an_earlier_clause_does_not_reach(self):
        """A `not` in an unrelated earlier clause must not silently neutralise a real status
        word later in the sentence.

        #119 changed the mechanism but not this requirement. The reach used to be a two-token
        window; it is now the keyword's own clause. This example was always protected by the
        semicolon — `_negated` splits on punctuation before it looks at any word — which is
        precisely why the window could be replaced without weakening the guarantee.
        """
        assert status_chip("this is not the place to argue; shipped") == ("c-conf", "SHIPPED")


class TestTheNegatorVocabularyAndItsReach:
    """#119. Two distinct gaps, both live after #21/#55 and #90/#112 were genuinely fixed:
    `nothing` was not a negator at all, and recognised negators only reached back two tokens.
    A fix aimed at one misses the other, so both tables from the issue are pinned here.
    """

    # Every row of the issue's roadmap/dashboard table. `roadmap` and `dashboard` share
    # `roadmap_status_chip`, so covering it covers both templates.
    @pytest.mark.parametrize("prose,expected", [
        ("Nothing has shipped yet.", "—"),      # was SHIPPED — `nothing` was not a negator
        ("No work is done.", "—"),              # was DONE — negator three tokens away
        ("This is not yet merged.", "—"),       # already correct
        ("This was merged last week.", "MERGED"),
        ("Ordinary prose about risk.", "—"),
    ])
    def test_the_roadmap_table(self, prose, expected):
        assert roadmap_status_chip("Section", prose)[1] == expected

    # And the sibling resolver, on the doc type whose whole purpose is separating confirmed
    # from inferred. AC2: whatever vocabulary is chosen is tested for BOTH resolvers.
    @pytest.mark.parametrize("answer,expected", [
        ("Nothing was measured.", "—"),         # was MEASURED
        ("Inferred, not measured.", "INFERRED"),
        ("Measured live.", "MEASURED"),
    ])
    def test_the_confidence_table(self, answer, expected):
        assert confidence_chip("Q?", answer)[1] == expected

    @pytest.mark.parametrize("negator", ["nothing", "none", "neither"])
    def test_each_added_negator_works_in_both_resolvers(self, negator):
        assert status_chip(f"{negator} of it shipped") == NEUTRAL_STATUS
        assert confidence_chip("Q?", f"{negator} of it was measured") == NEUTRAL_CONF

    @pytest.mark.parametrize("prose", [
        "No work is done.",                          # 3 tokens
        "No part of this has shipped.",              # 5 tokens
        "Nothing in the current milestone is done.",  # 6 tokens
    ])
    def test_a_negator_reaches_across_its_whole_clause_not_two_tokens(self, prose):
        assert status_chip(prose) == NEUTRAL_STATUS

    @pytest.mark.parametrize("prose,expected", [
        # The far side of the window: a negator this far away governs a different statement.
        ("This is not a risk and the work is done.", "DONE"),
        ("Nothing is certain but the API work shipped.", "SHIPPED"),
        ("No amount of arguing will change the fact that this shipped.", "SHIPPED"),
        ("There is no risk; the work is done.", "DONE"),
    ])
    def test_a_distant_negator_still_does_not_reach(self, prose, expected):
        """Widening the window is only safe while these keep working. A seventh word of reach
        neutralises the first two, which is what bounds the constant from above."""
        assert status_chip(prose)[1] == expected

    @pytest.mark.parametrize("prose", [
        "This is not yet merged.",
        "not yet done",
        "It is not so much done as abandoned.",
    ])
    def test_an_adverb_between_negator_and_keyword_does_not_break_it(self, prose):
        assert status_chip(prose)[1] not in ("MERGED", "DONE", "SHIPPED", "COMPLETE")


class TestTheCasesCrossModelReviewFound:
    """Three shapes the issue did not contain, all of which published the opposite of their own
    sentence. The first two are why a named clause-BOUNDARY set was tried and then rejected:
    every named boundary is a place a negation leaks through.
    """

    def test_coordinated_negation_negates_both_halves(self):
        """With `nor` treated as a clause boundary this published SHIPPED — the scan skipped the
        negated `done` and then found `shipped` on the far side of the `nor`. It reads worse than
        the original defect, because the sentence denies both words explicitly."""
        assert status_chip("The work is neither done nor shipped.") == NEUTRAL_STATUS

    def test_coordinated_negation_in_the_confidence_resolver_too(self):
        assert confidence_chip("Q?", "Nothing was inferred or measured.") == NEUTRAL_CONF

    @pytest.mark.parametrize("prose,fn,neutral", [
        ("It is not true that this was measured.", "conf", NEUTRAL_CONF),
        ("It is not true that the work is done.", "status", NEUTRAL_STATUS),
    ])
    def test_a_negated_complement_clause_is_still_negated(self, prose, fn, neutral):
        """`not true that X` denies X. With `that` treated as a boundary the negation stopped at
        it and the chip asserted X."""
        got = confidence_chip("Q?", prose) if fn == "conf" else status_chip(prose)
        assert got == neutral

    def test_the_one_shape_this_rule_gets_wrong_and_why_it_is_the_safe_direction(self):
        """`no doubt` is an affirmation wearing a negator. Its distance from the keyword is the
        same as the `not` in "It is not true that the work is done", where the negation is real —
        so no window can separate them, and this one is deliberately resolved the safe way.

        The chip under-claims rather than asserting a status nobody wrote. Asserted here so the
        limitation is visible in the suite instead of surfacing as a surprise; if scope modelling
        ever lands, this expectation should flip to DONE.
        """
        assert status_chip("There is no doubt the work is done.") == NEUTRAL_STATUS


class TestConfidenceNegation:
    def test_the_reported_case(self):
        assert confidence_chip("not measured", "") == NEUTRAL_CONF

    def test_negation_in_the_body_also_counts(self):
        assert confidence_chip("Some heading", "this was not measured") == NEUTRAL_CONF

    def test_an_unnegated_keyword_is_untouched(self):
        cls, label = confidence_chip("measured", "")
        assert label == "MEASURED" and cls != "c-unstated"

    def test_neither_naming_a_level_is_still_neutral(self):
        assert confidence_chip("A heading", "some prose") == NEUTRAL_CONF
