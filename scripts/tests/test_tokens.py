"""#42 PR 0 — the radius token scale, and the oracle that keeps it inert.

Issue #42 asks `design-system` to document a project's spacing and radius tokens. There were none:
the values were literals in the stylesheet, so a page printing them would have been a transcription
that drifts the moment someone edits the CSS.

`render/tokens.py` now DRIVES the stylesheet — `_STYLE` is a `string.Template` and the radii are
substituted in — so there is one source, not two. The risk that buys is obvious: `_STYLE` is the
one stylesheet AC5 freezes, and `plain` carries it with no template layer on top. So the guard here
is not a literal count, which would pass on a stylesheet that had quietly changed shape; it is the
exact SHA-256 of the rendered bytes, captured from `688ec13` BEFORE this change existed.

If a future change means to alter a radius, both hashes below fail and must be updated
deliberately, with the byte-identity exemplar regenerated in the same commit. That is the intended
friction — AC5 is a promise about emitted bytes, and this is where it is kept.
"""
import hashlib
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render as render_artifact  # noqa: E402
from render import tokens  # noqa: E402

# RE-BASELINED ONCE, by #73, which forces dark as the ground. That issue is epic #77's single
# sanctioned exception to the frozen-bytes rule and says so out loud; every later child treats
# these as frozen again. Renamed off `_BEFORE_42` in the same breath, because after a re-baseline
# a constant called "before 42" would be naming an anchor it no longer has.
#
#   Before #73 (anchored at 688ec13, pre-tokens.py):
#     style cc3972e4b53e4c7c1e712ff37273d1074518f0ef5330484b66b62fb45e4fcc6f
#     plain 2b1f84f37be4b3c51b8193b0f5545c01dfdf51eb92871c4077c912a7e8b0330a
#
#   Recompute with:
#     python3 -c "import render,hashlib; print(hashlib.sha256(render._STYLE.encode()).hexdigest())"
STYLE_SHA_AFTER_73 = "6fac708759265af85bc23045c072044cc9c2f1b00ca3c6e01841c85b069022e4"
PLAIN_SHA_AFTER_73 = "c87d0fba0b6549879163701b185b07b19e6a59f95ac05129ca2c809c781ef009"  # re-pinned by #24
PLAIN_DOC = "# T\n\nbody\n"


def _plain():
    return render_artifact.render_artifact(
        PLAIN_DOC, title="T", style="plain", generated_at="x")


def _radii_in(css):
    """Every `border-radius` value in a stylesheet, minus the pill idiom.

    `999px` is not a token — it is the "make this a pill" idiom, and naming it would invite an
    author to reach for a size that is not on the scale. Comments are stripped first: this suite
    has been bitten five times by a pattern matching its own prose.
    """
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return {m.group(1) for m in re.finditer(r"border-radius:\s*([0-9]+px)", css)
            if m.group(1) != "999px"}


class TestSubstitutionIsByteForByteInert:
    """The whole safety case for touching `_STYLE` at all.

    #42's own proof — that naming the radii was inert — was discharged when it landed, against
    the pre-substitution bytes at 688ec13. What these two guards do from now on is stop the
    stylesheet moving by ACCIDENT: any change to `_STYLE` or to `plain`'s render fails here and
    has to be re-baselined on purpose, in an issue that says it is doing so.
    """

    def test_the_stylesheet_is_unchanged_since_73(self):
        got = hashlib.sha256(render_artifact._STYLE.encode()).hexdigest()
        assert got == STYLE_SHA_AFTER_73, (
            "the base stylesheet's bytes moved — if that was deliberate, re-baseline here and "
            f"regenerate the exemplar in the same commit; expected {STYLE_SHA_AFTER_73}, got {got}")

    def test_a_plain_render_is_unchanged_since_73(self):
        got = hashlib.sha256(_plain().encode()).hexdigest()
        assert got == PLAIN_SHA_AFTER_73, (
            f"plain's rendered bytes moved — AC5 violation unless deliberate; got {got}")

    def test_no_placeholder_survived_into_the_output(self):
        """A mistyped key would leave `$radius_sm` sitting in the CSS."""
        assert "$radius" not in render_artifact._STYLE
        assert "$" not in render_artifact._STYLE


class TestTheScaleIsRealAndFullyConsumed:
    def test_every_radius_in_the_stylesheet_came_from_a_token(self):
        used = _radii_in(render_artifact._STYLE)
        named = set(tokens.RADII.values())
        assert used <= named, (
            f"the stylesheet uses radii {sorted(used - named)} that no token names — "
            f"a literal crept back in and design-system cannot document it")

    def test_every_named_radius_is_actually_used(self):
        used = _radii_in(render_artifact._STYLE)
        named = set(tokens.RADII.values())
        assert named <= used, (
            f"tokens.RADII names {sorted(named - used)}, which the stylesheet does not use — "
            f"a token nobody consumes documents something that does not exist")

    def test_names_are_stable_slugs(self):
        for name in tokens.RADII:
            assert re.fullmatch(r"[a-z]+", name), name

    def test_there_are_exactly_three(self):
        assert len(tokens.RADII) == 3, tokens.RADII

    def test_the_template_really_is_driven_by_the_tokens(self):
        """The other tests in this class all pass if a placeholder is reverted to its literal.

        Found by mutation: putting `border-radius:12px` back into the template keeps every byte
        identical and keeps `12px` "in use", so the value guards above stay green while the token
        has quietly stopped driving anything. Only the TEMPLATE can distinguish the two, so it is
        what gets asserted — the same vacuity trap that has now bitten this epic three times.
        """
        tpl = render_artifact._STYLE_TPL
        for name in tokens.RADII:
            assert f"$radius_{name}" in tpl, (
                f"$radius_{name} is not a placeholder in _STYLE_TPL — tokens.RADII[{name!r}] "
                f"is documentation, not a source")
        assert not _radii_in(tpl), (
            f"_STYLE_TPL still hard-codes {sorted(_radii_in(tpl))} instead of substituting a token")


class TestSpacingIsHonestlyAbsent:
    def test_no_spacing_scale_is_claimed(self):
        """#42 asks for spacing tokens; the stylesheet has twelve ad-hoc values and no scale.
        Inventing names would be transcription, so the absence is asserted rather than papered
        over — if someone later adds a real scale, this test is the reminder to say so."""
        assert tokens.SPACING_SCALE is None
