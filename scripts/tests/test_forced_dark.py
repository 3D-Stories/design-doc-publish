"""Dark is the ground, not a preference (#73, lane A2 of epic #77).

Before this issue every token had a dark value, but it sat behind
`@media(prefers-color-scheme:dark)` — so a page was dark only if the *viewer's* operating system
was. Both frozen targets are unconditionally dark, and every state colour in the approved
direction (`docs/planning/2026-08-02-72-visual-spec.md`) needs a dark ground to read at all. A red
critical band on a light-grey page is a different device.

So: the bare `:root` carries the dark values, and `@media print` restores the light ones, because
a forced-dark page sent to a printer is a solid dark rectangle.

The two `[data-theme]` blocks stay. They render nothing on their own — no emitted page stamps the
attribute — but `lint.theme_tokens()` reads exactly those two blocks to score contrast, and a VDL
pack overrides through them. Deleting them would blind the contrast gate.
"""
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render  # noqa: E402
from render import lint, vdl as render_vdl  # noqa: E402

# Read off the stylesheet the renderer actually emits, never hardcoded here twice over.
DARK_BG, LIGHT_BG = "#12181c", "#f6f7f8"
DARK_INK, LIGHT_INK = "#e7edf0", "#1a2126"

MD = "# A page\n\nSome prose.\n\n## A section\n\nMore prose.\n"
STYLES = ("plain", "roadmap", "report", "design", "dashboard",
          "review", "spec", "workflow", "analysis", "uat")

# `^:root{` at line start is the BARE block. `@media(...){:root{` keeps its `:root` mid-line, and
# the toggle blocks carry a `[`, so neither is matched. Same trick lint.py uses, inverted.
_BARE_ROOT = re.compile(r"^:root\{([^}]*)\}", re.M)
_TOKEN = re.compile(r"(--[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{3,8})")
_PRINT = re.compile(r"@media print\{([^{]*)\{([^}]*)\}\}")


def _css(html_text):
    return html_text.split("<style>", 1)[1].split("</style>", 1)[0]


def _page(style="plain", **kw):
    return render.render_artifact(MD, title="A page", generated_at="2026-08-02 12:00 MDT",
                                  style=style, **kw)


def _bare_root_tokens(css):
    """Every bare `:root` declaration, later layers winning — the browser's own cascade."""
    found = {}
    for block in _BARE_ROOT.findall(css):
        found.update(dict(_TOKEN.findall(block)))
    return found


def _print_tokens(css):
    found = {}
    for _selector, block in _PRINT.findall(css):
        found.update(dict(_TOKEN.findall(block)))
    return found


class TestTheGroundIsDark:
    def test_the_default_root_is_dark_for_every_style(self):
        for style in STYLES:
            tokens = _bare_root_tokens(_css(_page(style)))
            assert tokens["--bg"] == DARK_BG, style
            assert tokens["--ink"] == DARK_INK, style

    def test_no_style_gates_its_theme_on_the_viewers_os(self):
        for style in STYLES:
            assert "prefers-color-scheme" not in _page(style), style

    def test_the_component_layer_is_dark_by_default(self):
        """A rich style injects severity tokens; they must not stay light on a dark page."""
        tokens = _bare_root_tokens(_css(_page("review")))
        assert tokens["--sev-crit"] == "#f87171"
        assert tokens["--sev-crit-bg"] == "#3b1717"

    def test_the_roadmap_layer_is_dark_by_default(self):
        tokens = _bare_root_tokens(_css(_page("roadmap")))
        assert tokens["--chip-c"] == "#2dd4bf"
        assert tokens["--defer"] == "#fbbf24"


class TestPrintGoesLight:
    def test_print_restores_the_light_ground(self):
        for style in STYLES:
            tokens = _print_tokens(_css(_page(style)))
            assert tokens["--bg"] == LIGHT_BG, style
            assert tokens["--ink"] == LIGHT_INK, style

    def test_print_restores_the_component_layer_too(self):
        """Otherwise a printed page carries near-black badge fills on white paper."""
        tokens = _print_tokens(_css(_page("review")))
        assert tokens["--sev-crit-bg"] == "#fdecec"

    def test_print_restores_the_roadmap_layer_too(self):
        tokens = _print_tokens(_css(_page("roadmap")))
        assert tokens["--chip-c-bg"] == "#e6f2f0"

    def test_print_beats_an_explicit_dark_toggle(self):
        """`:root[data-theme=dark]` outranks a bare `:root` on specificity, so a print block
        selecting only `:root` would leave a manually-darkened page printing dark."""
        css = _css(_page("design"))
        selectors = [sel for sel, _ in _PRINT.findall(css)]
        assert selectors, "no @media print block at all"
        for sel in selectors:
            assert "[data-theme=dark]" in sel, sel


class TestTheContrastGateCanStillSee:
    def test_both_toggle_blocks_survive(self):
        """lint.theme_tokens() reads these two and nothing else. No blocks, no contrast gate."""
        for style in STYLES:
            themes = lint.theme_tokens(_css(_page(style)))
            assert set(themes) == {"light", "dark"}, style

    def test_the_contrast_gate_passes_on_the_new_ground(self):
        for style in STYLES:
            assert lint.check_contrast(_page(style)) == [], style

    def test_the_print_block_does_not_masquerade_as_the_dark_theme(self):
        """The print block selects `:root,:root[data-theme=dark]` and sets LIGHT values. An
        unanchored toggle regex matches inside it and, being last, scores light as dark — every
        dark ratio then silently becomes a light one. Caught by this test, not by inspection."""
        dark = lint.theme_tokens(_css(_page("design")))["dark"]
        assert dark["--bg"] == DARK_BG
        assert dark["--ink"] == DARK_INK


class TestVdlPacksFollowTheSameRule:
    PACK = {"accent": {"light": "#1e5f7a", "dark": "#7fd4f0"}}

    def test_a_packs_default_accent_is_its_dark_one(self):
        """The base ground is dark unconditionally, so a pack whose bare `:root` carried the
        light accent would brand a dark page with a colour chosen for white."""
        tokens = _bare_root_tokens(render_vdl.css_layer(self.PACK))
        assert tokens["--accent"] == "#7fd4f0"

    def test_a_pack_does_not_reintroduce_the_os_gate(self):
        assert "prefers-color-scheme" not in render_vdl.css_layer(self.PACK)

    def test_a_pack_still_prints_its_light_accent(self):
        assert _print_tokens(render_vdl.css_layer(self.PACK))["--accent"] == "#1e5f7a"

    def test_a_pack_still_reaches_the_lint_gate_through_both_toggles(self):
        page = _page("design", vdl=self.PACK)
        themes = lint.theme_tokens(_css(page))
        assert themes["light"]["--accent"] == "#1e5f7a"
        assert themes["dark"]["--accent"] == "#7fd4f0"
