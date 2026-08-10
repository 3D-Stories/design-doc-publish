"""A template owns its page frame (#69, lane A3 of epic #77).

The measurement that opened the issue: of 233 `.tpl-` rules in the registry, exactly one was
frame-level, and it was `.tpl-workflow`'s counter. Everything else was scoped
`.tpl-<style> .widget`, so all ten styles inherited one identical skeleton — same ground, same
900px measure, same header, same type scale — and a template could only ever decorate its
contents. That is why every page looked alike no matter how much CSS its template wrote.

The mechanism here is deliberately the one #42's PR 0 proved: the literals move out of the
stylesheet into named data and are substituted back through a `string.Template`, so the default
render is byte-for-byte what it was. What is new is that a template may declare its own values
for those slots, and the engine emits them scoped to that template's body class.

`plain` is the control. It declares nothing, receives no frame layer at all, and its bytes must
not move — proven here against the post-#73 baseline, with `test_byte_identity.py` untouched.
"""
import hashlib
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render  # noqa: E402
from render import frame as render_frame, lint, templates as render_templates  # noqa: E402

# Pinned by #73, the epic's single sanctioned re-baseline. #69 must not move it.
PLAIN_SHA_AFTER_73 = "c87d0fba0b6549879163701b185b07b19e6a59f95ac05129ca2c809c781ef009"  # re-pinned by #24
STYLE_SHA_AFTER_73 = "6fac708759265af85bc23045c072044cc9c2f1b00ca3c6e01841c85b069022e4"

MD = "# A page\n\nProse.\n\n## A section\n\nMore prose.\n"
RICH = tuple(render_templates.TEMPLATES)

# The SHA above is of THIS exact document, rendered with these exact arguments — the same fixture
# `test_tokens.py` pins. A byte oracle is meaningless without the input that produced it, and this
# suite briefly failed against its own constant by rendering a different one.
PLAIN_DOC = "# T\n\nbody\n"


def _page(style="plain"):
    return render.render_artifact(MD, title="A page", generated_at="x", style=style)


def _plain_pinned():
    return render.render_artifact(PLAIN_DOC, title="T", style="plain", generated_at="x")


def _css(html_text):
    return html_text.split("<style>", 1)[1].split("</style>", 1)[0]


def _measure_of(css, style):
    m = re.search(rf"\.tpl-{style} \.wrap\{{[^}}]*max-width:([^;}}]+)", css)
    return m.group(1) if m else None


class TestPlainIsUntouched:
    """AC2. The whole safety case for moving the frame out of the stylesheet."""

    def test_the_substitution_is_byte_inert(self):
        got = hashlib.sha256(render._STYLE.encode()).hexdigest()
        assert got == STYLE_SHA_AFTER_73, (
            "naming the frame slots was supposed to be inert against #73's baseline; "
            f"got {got}")

    def test_plains_render_is_unchanged(self):
        got = hashlib.sha256(_plain_pinned().encode()).hexdigest()
        assert got == PLAIN_SHA_AFTER_73, f"plain's bytes moved — AC2 violation; got {got}"

    def test_plain_receives_no_frame_layer(self):
        assert ".tpl-plain" not in _page("plain")

    def test_no_placeholder_survived(self):
        assert "$" not in render._STYLE


class TestEveryRichStyleDeclaresAFrame:
    def test_each_emits_a_frame_layer_for_every_slot(self):
        for style in RICH:
            css = _css(_page(style))
            for slot in render_frame.SLOTS:
                assert render_frame.slot_appears(css, style, slot), f"{style} missing {slot}"

    def test_the_frame_is_declared_data_not_hand_written_css(self):
        """A template declares values; only `frame.py` writes the rules. Otherwise the next
        style invents its own selector shape and #45 has nothing decidable to measure."""
        for module in render_templates.MODULES:
            for slot in getattr(module, "FRAME", {}):
                assert slot in render_frame.SLOTS, f"{module.NAME} declares unknown slot {slot}"

    def test_a_frame_layer_never_reaches_another_style(self):
        for style in RICH:
            css = _css(_page(style))
            others = {s for s in RICH if s != style}
            for other in others:
                assert f".tpl-{other} .wrap" not in css, f"{other}'s frame leaked into {style}"


class TestTwoStylesAreDistinctAtThePageLevel:
    """AC1 — the point of the whole issue. Not widgets: the page."""

    def test_uat_and_spec_do_not_share_a_measure(self):
        uat = _measure_of(_css(_page("uat")), "uat")
        spec = _measure_of(_css(_page("spec")), "spec")
        assert uat and spec and uat != spec, (uat, spec)

    def test_neither_is_merely_the_inherited_default(self):
        default = render_frame.DEFAULTS["measure"]
        assert _measure_of(_css(_page("uat")), "uat") != default
        assert _measure_of(_css(_page("spec")), "spec") != default

    def test_uat_declares_its_own_ground(self):
        """Its reference is a dark board with a radial wash, not a flat page."""
        assert render_frame.DEFAULTS["ground"] != render_templates.uat.FRAME["ground"]
        assert "radial-gradient" in _css(_page("uat"))

    def test_analysis_owns_every_slot_it_needs_rather_than_inheriting(self):
        """#76's AC2, for the first of the seven: a rebuilt style must not simply inherit
        `plain`'s frame. Asserted per slot, because declaring a FRAME dict that happens to
        restate the defaults would satisfy a bare "has a FRAME" check and change nothing."""
        declared = render_templates.analysis.FRAME
        for slot in ("ground", "measure", "h1_size", "h2_size", "h2_rhythm"):
            assert declared[slot] != render_frame.DEFAULTS[slot], slot

    def test_analysis_is_narrower_than_the_default_because_it_is_prose(self):
        """The one style that is mostly prose gets the shorter line, which is the whole
        argument for it owning a measure at all."""
        measure = _measure_of(_css(_page("analysis")), "analysis")
        assert measure == "880px"
        assert measure != render_frame.DEFAULTS["measure"]


class TestTheFrameIsTheBaseATemplateDecorates:
    def test_a_templates_own_css_comes_after_its_frame(self):
        """Equal specificity, so source order decides. A hand-written rule must win over the
        declared frame, or a template could never refine what it declared."""
        css = _css(_page("design"))
        assert css.index(".tpl-design .wrap") < css.index(".tpl-design h2{border-bottom")


class TestTheQualityFloorHolds:
    def test_contrast_passes_for_every_style(self):
        for style in ("plain",) + RICH:
            assert lint.check_contrast(_page(style)) == [], style

    def test_no_style_reaches_an_external_host(self):
        for style in ("plain",) + RICH:
            assert lint.check_external_requests(_page(style)) == [], style

    def test_no_style_reaches_an_external_host_even_when_the_doc_embeds_one(self):
        """#23: the test above passes for a reason weaker than it looks — `MD` contains no
        image, so no style was ever asked to emit one. This uses its own hostile document
        rather than widening `MD`, which many tests in this file share; a change there would
        have to be re-justified against every one of them. (`MD` is NOT the SHA-pinned
        fixture — `PLAIN_SHA_AFTER_73` / `STYLE_SHA_AFTER_73` pin `PLAIN_DOC`, here and in
        `test_tokens.py`. An earlier draft of this docstring said otherwise.)"""
        hostile = ("# A page\n\nProse.\n\n![shot](https://evil.example/x.png)\n\n"
                   "![shot2](//evil.example/y.png)\n\n![shot3](/\\evil.example/z.png)\n")
        for style in ("plain",) + RICH:
            page = render.render_artifact(hostile, title="A page", generated_at="x",
                                          style=style)
            assert lint.check_external_requests(page) == [], style
            assert "evil.example" not in re.sub(r"&lt;[^&]*&gt;", "", page).replace(
                "![shot](https://evil.example/x.png)", ""
            ).replace("![shot2](//evil.example/y.png)", "").replace(
                "![shot3](/\\evil.example/z.png)", ""
            ), f"{style}: evil.example survived outside the literal source text"
