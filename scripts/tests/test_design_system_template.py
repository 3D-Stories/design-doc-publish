"""#42 PR 1 — the `design-system` style.

The page that documents a project's design language. Issue #42 asks for brand colours, a type
scale, spacing and radius tokens, and component samples.

The hard criterion is AC4: it must render **a real project's VDL pack, not hardcoded sample
colours**. That looked impossible at first — `BEFORE_BODY` furniture is a trusted CONSTANT
(`render/__init__.py:340`), so it cannot carry a per-project value. It does not need to: the VDL
layer already defines `--accent` (and `--bg` when the pack is tinted) as custom properties on the
page, so a swatch painted `background:var(--accent)` resolves to THAT project's colour at render
time. Constant markup, live colour, and two different projects genuinely produce two different
pages — which is what these tests assert.

The radius samples work the same way one level up: the template's CSS interpolates
`tokens.RADII`, so PR 0's token data drives what the page displays. There is no second copy to
drift.
"""
import json
import re
import sys
from pathlib import Path
from unittest import mock

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render as render_artifact  # noqa: E402
from render import blocks, tokens  # noqa: E402
import vdl_packs  # noqa: E402

DOC = "# Tokens\n\n## Colour\n\nThe accent.\n\n## Type\n\nThe scale.\n"


def _workspace(tmp_path):
    """A real-shaped but EMPTY workspace file.

    Deliberately not this machine's own: with no project declaring a pack, every name
    resolves through `SEEDS`, which is committed data. A test that read the live
    workspace would pass or fail on whatever the owner happened to configure today.
    """
    ws = tmp_path / ".rawgentic_workspace.json"
    ws.write_text(json.dumps({"projects": []}), encoding="utf-8")
    return ws


def _render(project=None, ws=None):
    vdl = vdl_packs.pack_for(project, ws) if project else None
    return render_artifact.render_artifact(
        DOC, title="T", style="design-system", generated_at="x", vdl=vdl)


def _body(html):
    return re.search(r"<body[^>]*>(.*)</body>", html, re.S).group(1)


def _emitted(html):
    tok = set()
    for attr in re.findall(r'class="([^"]*)"', _body(html)):
        tok.update(attr.split())
    return tok


class TestItIsARegisteredStyle:
    def test_it_is_in_the_registry(self):
        assert "design-system" in render_artifact._TEMPLATES

    def test_it_carries_its_body_class(self):
        assert 'class="tpl-design-system"' in _render()


class TestAC4RealProjectPack:
    """The swatch must show the PROJECT's colour, not a colour written into the template."""

    def test_the_accent_swatch_is_painted_from_the_custom_property(self):
        css = re.search(r"<style>(.*?)</style>", _render(), re.S).group(1)
        assert re.search(r"\.ds-accent\{[^}]*background:var\(--accent\)", css), (
            "the accent swatch must resolve --accent at render time; a literal colour here "
            "is exactly the 'hardcoded sample colours' AC4 forbids")

    def test_no_hex_colour_is_written_into_the_template_css(self):
        from render.templates import design_system
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", design_system.CSS), (
            "design-system's own CSS must not name a colour — every swatch reads a token")

    def test_two_projects_render_different_pages(self, tmp_path):
        ws = _workspace(tmp_path)
        a, b = _render("rawgentic", ws), _render("chorestory", ws)
        assert a != b, "the pack is not reaching the page — both projects rendered identically"

    @pytest.mark.parametrize("project", sorted(vdl_packs.SEEDS))
    def test_the_projects_real_accent_reaches_the_page(self, project, tmp_path):
        """AC4 stated as a property, over every seeded project rather than one sample.

        One project passing could mean the page happens to carry that hex; all ten passing
        with ten different hexes cannot.
        """
        pack = vdl_packs.pack_for(project, _workspace(tmp_path))
        accent = pack["accent"]["light"]
        assert accent in _render(project, _workspace(tmp_path)), (
            f"{project}'s real accent {accent} is not in its own design-system page")


class TestTheRadiusScaleIsShown:
    def test_every_radius_token_appears_in_the_template_css(self):
        from render.templates import design_system
        for name, value in tokens.RADII.items():
            assert value in design_system.CSS, (
                f"radius {name}={value} is not shown by the page that documents it")

    def test_the_scale_is_driven_by_the_token_data_not_retyped(self):
        """Mutation-proof: the CSS must be BUILT from tokens.RADII, not merely agree with it.

        Found the same way PR 0's vacuity was found — literal values that happen to match pass
        every value check while the token has stopped driving anything. A module attribute
        declaring "I use RADII" is the same vacuity one level up: a module can say that and
        still be retyped. So this patches the token data and requires the OUTPUT to follow.
        """
        from render.templates import design_system
        with mock.patch.dict(tokens.RADII, {"xl": "99px"}, clear=False):
            built = design_system._build_css()
        assert "99px" in built and "ds-rad-xl" in built, (
            "a new radius token did not reach the CSS — the scale is retyped, not driven")
        assert "99px" not in design_system._build_css(), (
            "the patch leaked; this test proves nothing about the unpatched build")

    def test_every_radius_token_is_shown_on_the_page_itself(self):
        """The CSS carrying a value is not the page showing it: BEFORE_BODY must name each
        token too, or the rule exists with nothing to paint."""
        from render.templates import design_system
        html = _render()
        for name in tokens.RADII:
            assert f"ds-rad-{name}" in html, f"radius {name} has no sample on the page"


class TestMarkers:
    def test_swatch_marker_is_emitted(self):
        assert "ds-swatch" in _emitted(_render())

    def test_scale_marker_is_emitted(self):
        assert "ds-scale" in _emitted(_render())

    def test_markers_are_absent_from_every_other_style(self):
        for style in render_artifact._TEMPLATES:
            if style == "design-system":
                continue
            got = _emitted(render_artifact.render_artifact(
                DOC, title="T", style=style, generated_at="x"))
            assert "ds-swatch" not in got, style
            assert "ds-scale" not in got, style


class TestPolicy:
    def test_it_declares_its_accepted_tags(self):
        assert blocks.DOC_TYPE_TAGS["design-system"] == {
            "legend", "callout", "chips", "provenance"}

    def test_it_emits_no_script(self):
        """AC3's sibling: uat stays the only interactive template."""
        assert "<script" not in _render()
