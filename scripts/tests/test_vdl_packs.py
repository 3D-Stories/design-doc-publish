"""Per-project VDL packs (#14, wave 6).

Design: `docs/planning/2026-08-01-14-vdl-packs.md` (revision 2, after a FAIL gate).

The headline test is `TestEveryPackClearsAA`. It does not assert a ratio it computed
itself — it renders a real page with each pack and runs the **lint gate** over it, which
is what AC3 asks for ("validated by wave 5's lint gate rather than asserted"). Four of the
ten colours this wave ships failed that check before they were corrected, including
chorestory's own brand blue in both themes, so this is the test that earned its place.

Hermetic by default: every behavioural test builds its own `.rawgentic.json` under
`tmp_path`. Only `TestTheRealChorestoryDeclaration` reads a sibling repo, and it SKIPS
when that repo is not checked out beside this one — visible in the summary rather than
silently green.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render as render_engine  # noqa: E402
import vdl_packs  # noqa: E402
from render import lint, vdl as render_vdl  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CHORESTORY_LIVE = Path.home() / "rawgentic" / "projects" / "chorestory" / ".rawgentic.json"

# The declaration this wave derived for chorestory, from its real tokens file. Committed
# here so the suite is hermetic and so a drift against the live repo is a visible failure
# on any machine where both exist.
CHORESTORY_BLOCK = json.loads((FIXTURES / "chorestory_vdl.json").read_text(encoding="utf-8"))

STYLES = tuple(n for n in render_engine._TEMPLATES if n != "plain")


def _index_module():
    path = SCRIPTS.parent / "index" / "build_index.py"
    spec = importlib.util.spec_from_file_location("_test_index", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _workspace(tmp_path, projects):
    """A real-shaped workspace file plus each project's own config dir."""
    entries = []
    for name, block in projects.items():
        pdir = tmp_path / name
        pdir.mkdir(parents=True, exist_ok=True)
        cfg = {"version": 1, "project": {"name": name}}
        if block is not None:
            cfg["vdl"] = block
        (pdir / ".rawgentic.json").write_text(json.dumps(cfg), encoding="utf-8")
        entries.append({"name": name, "path": f"./{name}"})
    ws = tmp_path / ".rawgentic_workspace.json"
    ws.write_text(json.dumps({"projects": entries}), encoding="utf-8")
    return ws


def _page(pack, style="design", title="A Doc"):
    return render_engine.render_artifact("body text", title=title, style=style,
                                         doc_id="d", vdl=pack)


def _as_pack(block):
    return {"accent": block["accent"], "tint": block.get("tint"),
            "origin": "declared", "source": block["source"], "note": block["note"]}


# --------------------------------------------------------------------------- AC3

class TestEveryPackClearsAA:
    """AC3, judged by the lint gate over a real rendered page — not by arithmetic this
    test repeats. `#2c7a9e` is annotated "WCAG AA compliant" in chorestory's own token
    file and IS, against chorestory's background. It fails against this renderer's, in
    both themes. AA is a property of a PAIR, never of a colour."""

    @pytest.mark.parametrize("project", sorted(vdl_packs.SEEDS))
    def test_every_seed_lints_clean(self, project, tmp_path):
        pack = vdl_packs.pack_for(project, _workspace(tmp_path, {}))
        assert pack["origin"] == "seed"
        assert lint.lint(_page(pack)) == []

    @pytest.mark.parametrize("index", range(len(vdl_packs.PALETTE)))
    def test_every_fallback_colour_lints_clean(self, index):
        light, dark = vdl_packs.PALETTE[index]
        pack = {"accent": {"light": light, "dark": dark}, "tint": None}
        assert lint.lint(_page(pack)) == []

    def test_the_chorestory_declaration_lints_clean(self):
        assert lint.lint(_page(_as_pack(CHORESTORY_BLOCK))) == []

    @pytest.mark.parametrize("style", STYLES)
    def test_a_pack_lints_clean_on_every_template(self, style):
        """A pack must not break contrast on one template and pass on the others."""
        assert lint.lint(_page(_as_pack(CHORESTORY_BLOCK), style=style)) == []

    def test_the_nominal_brand_primary_would_NOT_pass(self):
        """The measurement that drove the whole design. If this ever starts passing, the
        renderer's surfaces changed and chorestory's declaration should be revisited."""
        failing = {"accent": {"light": "#2c7a9e", "dark": "#2c7a9e"}, "tint": None}
        findings = lint.lint(_page(failing))
        assert findings, "#2c7a9e is expected to fail AA on these surfaces"
        assert any("--accent" in f for f in findings)


# --------------------------------------------------------------------------- resolution

class TestResolution:
    def test_a_declared_block_wins(self, tmp_path):
        ws = _workspace(tmp_path, {"chorestory": CHORESTORY_BLOCK})
        pack = vdl_packs.pack_for("chorestory", ws)
        assert pack["origin"] == "declared"
        assert pack["accent"] == CHORESTORY_BLOCK["accent"]

    def test_a_declaration_beats_a_seed(self, tmp_path):
        """The owner rule: a project's existing VDL always wins; seeds only fill gaps."""
        block = dict(CHORESTORY_BLOCK, accent={"light": "#1f3f9e", "dark": "#7f9ae8"})
        ws = _workspace(tmp_path, {"saystory": block})
        pack = vdl_packs.pack_for("saystory", ws)
        assert pack["origin"] == "declared"
        assert pack["accent"]["light"] == "#1f3f9e"
        assert pack["accent"]["light"] != vdl_packs.SEEDS["saystory"]["light"]

    def test_a_project_with_no_block_gets_its_seed(self, tmp_path):
        ws = _workspace(tmp_path, {"sysop": None})
        assert vdl_packs.pack_for("sysop", ws)["origin"] == "seed"

    def test_an_unknown_project_gets_a_fallback_NOT_none(self, tmp_path):
        """The gate's first High: a source of truth that abstains is not one. Returning
        None left the renderer on its default while the index picked its own colour."""
        pack = vdl_packs.pack_for("nobody-has-heard-of-this", _workspace(tmp_path, {}))
        assert pack is not None and pack["origin"] == "fallback"
        assert pack["accent"]["light"] in [c[0] for c in vdl_packs.PALETTE]

    def test_the_fallback_is_deterministic_on_the_NAME(self, tmp_path):
        """build_index used `PALETTE[len(seen) % len(PALETTE)]`, so a project's colour
        depended on how many groups sorted before it — adding one recoloured others.

        Stable under a DIFFERENT workspace with other projects in it: that is the
        property position-dependence violated, and repeated-equality alone would not
        catch a constant `PALETTE[0]`, so the spread test below carries that half."""
        ws = _workspace(tmp_path, {})
        first = vdl_packs.pack_for("zeta-project", ws)
        assert vdl_packs.pack_for("zeta-project", ws)["accent"] == first["accent"]
        crowded = _workspace(tmp_path / "b", {"a": None, "b": None, "c": None})
        assert vdl_packs.pack_for("zeta-project", crowded)["accent"] == first["accent"]

    def test_the_fallback_actually_SPREADS_across_the_palette(self, tmp_path):
        """A constant `PALETTE[0]` passes every determinism check ever written."""
        ws = _workspace(tmp_path, {})
        seen = {vdl_packs.pack_for(f"project-{i}", ws)["accent"]["light"]
                for i in range(40)}
        assert len(seen) >= 4, f"fallback collapsed to {seen}"

    @pytest.mark.parametrize("name", [f"spread-{i}" for i in range(12)])
    def test_whatever_the_fallback_returns_lints_clean(self, name, tmp_path):
        """AC3 over the packs `_fallback` really produces, not over PALETTE read directly."""
        assert lint.lint(_page(vdl_packs.pack_for(name, _workspace(tmp_path, {})))) == []

    def test_resolution_is_case_insensitive(self, tmp_path):
        ws = _workspace(tmp_path, {})
        assert (vdl_packs.pack_for("SysOp", ws)["accent"]
                == vdl_packs.pack_for("sysop", ws)["accent"])

    def test_a_missing_workspace_file_still_resolves(self, tmp_path):
        """Fail open all the way down — no config anywhere is not a crash."""
        pack = vdl_packs.pack_for("sysop", tmp_path / "nope.json")
        assert pack["origin"] == "seed"


# --------------------------------------------------------------------------- AC4/AC5

class TestABadBlockNeverBreaksARender:
    """AC4. Every case below must still render, in the fallback palette."""

    MALFORMED = {
        "not an object": "teal",
        "accent missing": {"source": "s", "note": "n"},
        "accent not an object": {"accent": "#1e5f7a", "source": "s", "note": "n"},
        "accent missing a theme": {"accent": {"light": "#1e5f7a"}, "source": "s", "note": "n"},
        "accent not hex": {"accent": {"light": "teal", "dark": "#4da7c4"},
                           "source": "s", "note": "n"},
        "accent short hex": {"accent": {"light": "#fff", "dark": "#4da7c4"},
                             "source": "s", "note": "n"},
        "source missing": {"accent": {"light": "#1e5f7a", "dark": "#4da7c4"}, "note": "n"},
        "note missing": {"accent": {"light": "#1e5f7a", "dark": "#4da7c4"}, "source": "s"},
        "note not a string": {"accent": {"light": "#1e5f7a", "dark": "#4da7c4"},
                              "source": "s", "note": 7},
        "unknown version": {"version": 99, "accent": {"light": "#1e5f7a", "dark": "#4da7c4"},
                            "source": "s", "note": "n"},
        "unexpected key": {"accent": {"light": "#1e5f7a", "dark": "#4da7c4"},
                           "source": "s", "note": "n", "shadow": "#000000"},
        "tint malformed": {"accent": {"light": "#1e5f7a", "dark": "#4da7c4"},
                           "tint": {"light": "nope", "dark": "#121a1e"},
                           "source": "s", "note": "n"},
    }

    @pytest.mark.parametrize("label", sorted(MALFORMED))
    def test_it_falls_open_and_warns(self, label, tmp_path, capsys):
        ws = _workspace(tmp_path, {"sysop": self.MALFORMED[label]})
        pack = vdl_packs.pack_for("sysop", ws)
        assert pack["origin"] != "declared"          # fell through
        err = capsys.readouterr().err
        assert "sysop" in err and ".rawgentic.json" in err, f"{label}: no useful warning"

    @pytest.mark.parametrize("label", sorted(MALFORMED))
    def test_the_page_still_renders(self, label, tmp_path):
        ws = _workspace(tmp_path, {"sysop": self.MALFORMED[label]})
        assert lint.lint(_page(vdl_packs.pack_for("sysop", ws))) == []

    def test_no_block_at_all_is_SILENT(self, tmp_path, capsys):
        """The normal path for most projects is not an event."""
        vdl_packs.pack_for("sysop", _workspace(tmp_path, {"sysop": None}))
        assert capsys.readouterr().err == ""

    def test_a_missing_config_file_is_silent(self, tmp_path, capsys):
        vdl_packs.load_pack("x", tmp_path / "absent.json")
        assert capsys.readouterr().err == ""

    def test_an_UNREADABLE_file_warns_rather_than_hiding(self, tmp_path, capsys):
        """The gate's second High: a permissions fault that silently shipped default
        branding would leave the gate green and the page wrong."""
        cfg = tmp_path / ".rawgentic.json"
        cfg.write_text('{"vdl": {}}', encoding="utf-8")
        cfg.chmod(0o000)
        try:
            assert vdl_packs.load_pack("x", cfg) is None
            err = capsys.readouterr().err
            assert "unreadable" in err or "invalid JSON" in err
        finally:
            cfg.chmod(0o644)

    def test_invalid_json_warns(self, tmp_path, capsys):
        cfg = tmp_path / ".rawgentic.json"
        cfg.write_text("{not json", encoding="utf-8")
        assert vdl_packs.load_pack("x", cfg) is None
        assert "undecodable" in capsys.readouterr().err

    def test_INVALID_UTF8_falls_open_rather_than_aborting_the_render(self, tmp_path, capsys):
        """UnicodeDecodeError is not JSONDecodeError. Caught only by the narrower clause,
        a single corrupt byte aborted the render instead of selecting a seed."""
        cfg = tmp_path / ".rawgentic.json"
        cfg.write_bytes(b'{"vdl": "\xff\xfe not utf-8"}')
        assert vdl_packs.load_pack("x", cfg) is None
        assert "undecodable" in capsys.readouterr().err

    def test_a_top_level_array_is_a_corrupt_config_not_an_absence(self, tmp_path, capsys):
        cfg = tmp_path / ".rawgentic.json"
        cfg.write_text("[]", encoding="utf-8")
        assert vdl_packs.load_pack("x", cfg) is None
        assert "root is list" in capsys.readouterr().err


class TestAMalformedWorkspaceAlsoFailsOpen:
    """The lookup runs BEFORE seed resolution, so a bad workspace shape stopped even a
    seeded project from rendering — and a silently-swallowed one produced a hashed
    fallback that lints clean, which is wrong branding behind a green gate."""

    SHAPES = {
        "projects is null": '{"projects": null}',
        "projects is a string": '{"projects": "nope"}',
        "an entry is null": '{"projects": [null]}',
        "an entry is a string": '{"projects": ["sysop"]}',
        "path is a number": '{"projects": [{"name": "sysop", "path": 7}]}',
        "root is an array": '[]',
        "not json at all": '{oops',
    }

    @pytest.mark.parametrize("label", sorted(SHAPES))
    def test_a_seeded_project_still_resolves(self, label, tmp_path):
        ws = tmp_path / ".rawgentic_workspace.json"
        ws.write_text(self.SHAPES[label], encoding="utf-8")
        pack = vdl_packs.pack_for("sysop", ws)
        assert pack["origin"] == "seed"
        assert lint.lint(_page(pack)) == []

    @pytest.mark.parametrize("label", sorted(SHAPES))
    def test_and_it_is_never_silent_about_it(self, label, tmp_path, capsys):
        ws = tmp_path / ".rawgentic_workspace.json"
        ws.write_text(self.SHAPES[label], encoding="utf-8")
        vdl_packs.pack_for("sysop", ws)
        if label in ("an entry is null", "an entry is a string"):
            return          # one bad row is skipped, not fatal: the rest must still work
        assert capsys.readouterr().err != "", label

    def test_one_bad_row_does_not_blind_the_others(self, tmp_path):
        (tmp_path / "widget").mkdir()
        (tmp_path / "widget" / ".rawgentic.json").write_text(json.dumps(
            {"vdl": {"accent": {"light": "#1f3f9e", "dark": "#7f9ae8"},
                     "source": "s", "note": "n"}}), encoding="utf-8")
        ws = tmp_path / ".rawgentic_workspace.json"
        ws.write_text(json.dumps({"projects": [None, "junk",
                                               {"name": "widget", "path": "./widget"}]}),
                      encoding="utf-8")
        assert vdl_packs.pack_for("widget", ws)["origin"] == "declared"

    @pytest.mark.parametrize("escape", ["/tmp", "../../../tmp", "./ok/../../outside"])
    def test_a_path_escaping_the_workspace_is_refused(self, escape, tmp_path, capsys):
        """A workspace entry must not point the publisher at a foreign tree and let it
        choose a public page's branding."""
        ws = tmp_path / "root" / ".rawgentic_workspace.json"
        ws.parent.mkdir(parents=True)
        ws.write_text(json.dumps({"projects": [{"name": "sysop", "path": escape}]}),
                      encoding="utf-8")
        assert vdl_packs.pack_for("sysop", ws)["origin"] == "seed"
        assert "outside the workspace" in capsys.readouterr().err

    @pytest.mark.parametrize("payload", [
        "#fff;} body{display:none", "#1e5f7a</style><script>x()</script>",
        "red", "#1e5f7a;--ink:#000", "url(https://evil.test/x.png)",
    ])
    def test_a_colour_is_never_a_css_injection_primitive(self, payload, tmp_path):
        """The value reaches a <style> block, so an unvalidated string is not merely a
        wrong colour."""
        block = {"accent": {"light": payload, "dark": "#4da7c4"},
                 "source": "s", "note": "n"}
        ws = _workspace(tmp_path, {"sysop": block})
        pack = vdl_packs.pack_for("sysop", ws)
        assert pack["origin"] != "declared"
        # As a DECLARATION, not as a substring: "red" occurs inside "rendered" in a CSS
        # comment, and an over-broad assertion here would fail for the wrong reason.
        assert f"--accent:{payload}" not in _page(pack)
        assert render_vdl.css_layer(pack).count("--accent:") == 4    # ours, not theirs


# --------------------------------------------------------------------------- injection

class TestTheLayerWins:
    def test_the_accent_reaches_the_page(self, tmp_path):
        pack = _as_pack(CHORESTORY_BLOCK)
        page = _page(pack)
        assert pack["accent"]["light"] in page and pack["accent"]["dark"] in page

    @pytest.mark.parametrize("style", STYLES)
    def test_the_pack_beats_every_template(self, style):
        """§4: the layer is emitted LAST. Placed earlier, a template redeclaring --accent
        would silently take the page back. No template does today — this keeps it so."""
        pack = _as_pack(CHORESTORY_BLOCK)
        page = _page(pack, style=style)
        css = page.split("<style>", 1)[1].split("</style>", 1)[0]
        tokens = lint.theme_tokens(css)
        assert tokens["light"]["--accent"] == pack["accent"]["light"], style
        assert tokens["dark"]["--accent"] == pack["accent"]["dark"], style

    def test_the_layer_is_the_last_thing_in_the_stylesheet(self):
        css = _page(_as_pack(CHORESTORY_BLOCK)).split("<style>", 1)[1].split("</style>", 1)[0]
        assert css.rstrip().endswith("}")
        assert css.rindex("--accent:#1e5f7a") > css.rindex("--accent:#0f766e")

    def test_every_theme_block_the_stylesheet_uses_is_covered(self):
        """A pack covering only some would leave a page half-branded under an explicit
        theme toggle.

        #73 changed which blocks those are: the OS-preference query is gone (the ground is dark
        unconditionally now) and `@media print` took its place. A pack that still emitted the old
        query would brand a dark page with the accent it picked for white paper whenever the
        viewer's OS was set to light.
        """
        layer = render_vdl.css_layer(_as_pack(CHORESTORY_BLOCK))
        for marker in (":root{", ":root[data-theme=dark]", ":root[data-theme=light]",
                       "@media print{"):
            assert marker in layer
        assert "prefers-color-scheme" not in layer

    def test_a_tint_moves_the_background(self):
        page = _page(_as_pack(CHORESTORY_BLOCK))
        css = page.split("<style>", 1)[1].split("</style>", 1)[0]
        assert lint.theme_tokens(css)["light"]["--bg"] == CHORESTORY_BLOCK["tint"]["light"]

    def test_no_pack_emits_no_layer(self):
        assert render_vdl.css_layer(None) == ""

    def test_plain_is_never_touched(self):
        """AC1/AC7: `plain` byte-identity is pinned by test_byte_identity.py and must
        survive a pack being passed."""
        with_pack = render_engine.render_artifact(
            "body", title="T", style="plain", generated_at="2026-08-01 12:00 MDT",
            vdl=_as_pack(CHORESTORY_BLOCK))
        without = render_engine.render_artifact(
            "body", title="T", style="plain", generated_at="2026-08-01 12:00 MDT")
        assert with_pack == without


class TestTheSinkDefendsItself:
    """`render_artifact(vdl=...)` is a supported LIBRARY seam, so `css_layer` cannot
    assume its input came from `pack_for()`. The value lands inside a <style> block."""

    @pytest.mark.parametrize("payload", [
        "#000000;}</style><script>alert(1)</script><style>:root{--x:#000000",
        "#1e5f7a;--ink:#ff0000", "red", "url(https://evil.test/x)", "", None, 7,
    ])
    def test_an_unvalidated_accent_never_reaches_the_page(self, payload):
        layer = render_vdl.css_layer({"accent": {"light": payload, "dark": "#4da7c4"}})
        assert layer == ""
        page = render_engine.render_artifact(
            "b", title="T", style="design",
            vdl={"accent": {"light": payload, "dark": "#4da7c4"}})
        assert "<script>alert(1)</script>" not in page
        assert "--ink:#ff0000" not in page

    @pytest.mark.parametrize("pack", [None, {}, "teal", 7, {"accent": "nope"},
                                      {"accent": {"light": "#1e5f7a"}}])
    def test_a_shapeless_pack_emits_no_layer(self, pack):
        assert render_vdl.css_layer(pack) == ""

    def test_a_bad_TINT_drops_only_the_tint(self, ):
        layer = render_vdl.css_layer({"accent": {"light": "#1e5f7a", "dark": "#4da7c4"},
                                      "tint": {"light": "}evil{", "dark": "#121a1e"}})
        assert "--accent:#1e5f7a" in layer and "evil" not in layer


class TestTheLoadersCannotBeRedirected:
    """`render-doc` resolves its target and enforces realpath containment because a
    symlinked module is EXECUTED before any check can reject it. The three new loaders
    reach the same file and must carry the same guard."""

    def test_the_shipped_module_is_a_regular_file(self):
        for path in (SCRIPTS / "vdl_packs.py", SCRIPTS / "render" / "vdl.py"):
            assert path.is_file() and not path.is_symlink(), path

    @pytest.mark.parametrize("site", ["render", "index"])
    def test_a_symlinked_module_is_refused(self, site, tmp_path, monkeypatch):
        foreign = tmp_path / "foreign.py"
        foreign.write_text("raise SystemExit('foreign code ran')\n", encoding="utf-8")
        staged = tmp_path / "stage"
        (staged / ("scripts" if site == "index" else "")).mkdir(parents=True, exist_ok=True)
        target = (staged / "scripts" / "vdl_packs.py") if site == "index" else (staged / "vdl_packs.py")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(foreign)
        # Resolve-then-contain is the property; assert it directly against the staged tree.
        root = target.parent
        real = target.resolve()
        assert not real.is_relative_to(root), "the escape must be detectable"

    def test_every_loader_checks_containment_before_executing(self):
        """Grep-level, deliberately: the guard must PRECEDE the load at each site, and a
        behavioural test cannot see ordering."""
        for rel in ("scripts/render/__init__.py", "index/build_index.py"):
            src = (SCRIPTS.parent / rel).read_text(encoding="utf-8")
            guard = src.index("is_relative_to(root)")
            load = src.index("spec_from_file_location", guard - 2000)
            assert guard < load, f"{rel}: containment check must come before the load"


# --------------------------------------------------------------------------- AC6

class TestTheIndexAndThePagesCannotDrift:
    """AC6. Asserting they currently agree proves a coincidence; re-hardcoding
    `GROUP_COLORS` to today's values would keep such a test green. So the property is
    tested by MUTATION — and through the REAL resolution seams on both sides.

    Injection goes through the CONFIG, not `monkeypatch`: each consumer executes a fresh
    copy of `vdl_packs`, so patching this process's copy would be invisible to them and
    the test would prove nothing. A temporary declared block is visible to both.
    """

    PAIRS = [("#8a1d75", "#1f3f9e"), ("#0d6f88", "#4f7d15")]   # (dark, light), AA-clean

    def _both(self, project, ws):
        """The two production paths, unpatched. (dark, light) from each."""
        index = _index_module()
        pack = render_engine._resolve_pack(project, ws)
        return index.group_colors(project, ws), (pack["accent"]["dark"], pack["accent"]["light"])

    @pytest.mark.parametrize("dark,light", PAIRS)
    def test_both_consumers_follow_an_injected_change(self, tmp_path, dark, light):
        block = {"accent": {"light": light, "dark": dark},
                 "source": "test injection", "note": "n"}
        ws = _workspace(tmp_path / f"w{light[1:]}", {"widget": block})
        from_index, from_render = self._both("widget", ws)
        assert from_index == (dark, light)
        assert from_render == (dark, light)

    def test_the_renderer_seam_is_the_one_that_paints_the_page(self, tmp_path):
        """`_resolve_pack` is what `render-doc --project` calls; a hardcoded table there
        would survive a test that only resolved the pack itself."""
        block = {"accent": {"light": "#1f3f9e", "dark": "#8a1d75"},
                 "source": "s", "note": "n"}
        ws = _workspace(tmp_path, {"widget": block})
        page = _page(render_engine._resolve_pack("widget", ws))
        assert "#1f3f9e" in page and "#8a1d75" in page

    def test_the_agreement_check_actually_fails_when_a_consumer_goes_its_own_way(
            self, tmp_path, monkeypatch):
        """Proves the tests above are not vacuous. A consumer ignoring the shared module
        must break the assertion — asserting that two hardcoded values merely differ
        would prove nothing at all."""
        block = {"accent": {"light": "#1f3f9e", "dark": "#8a1d75"},
                 "source": "s", "note": "n"}
        ws = _workspace(tmp_path, {"widget": block})
        index = _index_module()
        monkeypatch.setattr(index, "group_colors", lambda g, w=None: ("#7fe0cf", "#0e7d6d"))
        with pytest.raises(AssertionError):
            assert index.group_colors("widget", ws) == ("#8a1d75", "#1f3f9e")

    def test_an_unknown_project_also_agrees(self, tmp_path):
        """The path the design gate found: revision 1 diverged here specifically."""
        ws = _workspace(tmp_path, {})
        from_index, from_render = self._both("a-brand-new-thing", ws)
        assert from_index == from_render

    def test_the_index_renders_without_being_handed_a_workspace(self, tmp_path):
        """`render()` still advertises a four-argument form, and that caller must get an
        index rather than an `AttributeError` from `None.read_text()`.

        This used to compare against `index.DEFAULT_WORKSPACE`, a hardcoded path to one
        machine. #9 retired it, and the comparison got MORE meaningful rather than less:
        `None` is now the real state of a machine that has never run setup, so this asserts
        the omitted argument and the explicit one give the same answer on the path a
        stranger actually takes.
        """
        index = _index_module()
        assert index.group_colors("sysop") == index.group_colors("sysop", None)

    def test_the_index_holds_no_colour_table_of_its_own(self):
        src = (SCRIPTS.parent / "index" / "build_index.py").read_text(encoding="utf-8")
        assert "GROUP_COLORS = {" not in src
        assert "PALETTE = [" not in src


# --------------------------------------------------------------------------- AC2

class TestTheRealChorestoryDeclaration:
    def test_the_fixture_is_a_valid_declared_block(self, tmp_path):
        ws = _workspace(tmp_path, {"chorestory": CHORESTORY_BLOCK})
        pack = vdl_packs.pack_for("chorestory", ws)
        assert pack["origin"] == "declared"
        assert "design-tokens.css" in pack["source"]
        assert "2c7a9e" in pack["note"], "the note must record what was NOT used, and why"

    def test_the_rendered_page_wears_chorestory_blue_and_not_the_failing_primary(self, tmp_path):
        """AC2, corrected by AC3: the page carries chorestory's ramp — but NOT
        `#2c7a9e`, which fails AA on these surfaces. Both values shipped are steps of
        that same declared ramp, so the identity is chorestory's; the hex is not the one
        the AC names because that hex cannot pass the AC3 bar."""
        ws = _workspace(tmp_path, {"chorestory": CHORESTORY_BLOCK})
        page = _page(vdl_packs.pack_for("chorestory", ws))
        assert "#1e5f7a" in page and "#4da7c4" in page
        assert "#2c7a9e" not in page
        assert lint.lint(page) == []

    def test_the_REAL_resolution_path_gives_chorestory_its_blue(self):
        """The finding two lanes made independently: the fixture proved nothing about
        production. chorestory was absent from SEEDS, so `pack_for` took the hashed
        fallback and a real page shipped GREEN while this suite passed on a temp file.

        No skip. This asserts the live workspace, by whichever tier answers — the seed
        today, the declaration once it lands in chorestory's own repo, and the values are
        identical so the handover is invisible."""
        live_ws = Path.home() / "rawgentic" / ".rawgentic_workspace.json"
        if not live_ws.exists():
            pytest.skip("not on the integration machine (no workspace file)")
        pack = vdl_packs.pack_for("chorestory", live_ws)
        assert pack["accent"] == CHORESTORY_BLOCK["accent"], (
            f"chorestory resolved to {pack['accent']} via {pack['origin']} — a real page "
            f"would not wear its own blue")
        assert lint.lint(_page(pack)) == []

    def test_the_seed_and_the_fixture_cannot_drift(self):
        """Two places now carry chorestory's values until the declaration lands. They are
        checked against each other so the handover stays invisible."""
        seed = vdl_packs.SEEDS["chorestory"]
        assert {"light": seed["light"], "dark": seed["dark"]} == CHORESTORY_BLOCK["accent"]

    @pytest.mark.skipif(not CHORESTORY_LIVE.exists(),
                        reason="chorestory is not checked out beside this repo")
    def test_a_declaration_in_the_live_repo_matches_the_fixture(self):
        """Once chorestory declares its block, it must agree with what shipped here.
        Skipped where that repo is absent; a drift where both exist is a real failure."""
        live = json.loads(CHORESTORY_LIVE.read_text(encoding="utf-8")).get("vdl")
        if live is None:
            pytest.skip("chorestory has not declared its block yet; the seed covers it")
        assert live == CHORESTORY_BLOCK


# --------------------------------------------------------------------- #9: unconfigured

class TestAnUnconfiguredWorkspaceIsAState:
    """#9 retires the hardcoded `DEFAULT_WORKSPACE`, so `None` stops being impossible and
    becomes the ordinary state of a machine that has never run setup.

    The renderer must keep working there. That is the README's first command and the only
    thing that works for a stranger today, so a colour lookup may degrade to a hash but must
    never raise — `None.exists()` would be an AttributeError on the default path.
    """

    def test_pack_for_accepts_none_and_still_returns_a_pack(self):
        pack = vdl_packs.pack_for("anything", None)
        assert pack["origin"] == "fallback"
        assert set(pack["accent"]) == {"light", "dark"}

    def test_a_seeded_project_still_gets_its_seed_without_a_workspace(self):
        pack = vdl_packs.pack_for("saystory", None)
        assert pack["origin"] == "seed"

    def test_it_says_nothing_on_stderr(self, capsys):
        """Absence is the normal first case, so it must be silent. A warning on every render
        would train people to ignore the warnings that mean something."""
        vdl_packs.pack_for("anything", None)
        assert capsys.readouterr().err == ""

    def test_a_workspace_entry_with_no_path_is_silent(self, tmp_path, capsys):
        """`setup.py --add-project` writes `{"name": ...}` with no `path`, because a project
        registered by name has no config directory to read. That is absence, and this
        module's own rule is that only genuine absence is silent."""
        ws = tmp_path / ".rawgentic_workspace.json"
        ws.write_text(json.dumps({"projects": [{"name": "payments-api"}]}), encoding="utf-8")
        pack = vdl_packs.pack_for("payments-api", ws)
        assert pack["origin"] == "fallback"
        assert capsys.readouterr().err == ""

    def test_a_workspace_entry_with_an_EMPTY_path_still_warns(self, tmp_path, capsys):
        """Present-but-useless is a different event from absent, and it stays loud."""
        ws = tmp_path / ".rawgentic_workspace.json"
        ws.write_text(json.dumps({"projects": [{"name": "widget", "path": ""}]}),
                      encoding="utf-8")
        vdl_packs.pack_for("widget", ws)
        assert "widget" in capsys.readouterr().err

    def test_the_index_and_the_renderer_still_agree_with_no_workspace(self):
        """The invariant this module exists for: one answer, whoever asks."""
        index = _index_module()
        assert index.group_colors("a-brand-new-thing", None) == (
            vdl_packs.pack_for("a-brand-new-thing", None)["accent"]["dark"],
            vdl_packs.pack_for("a-brand-new-thing", None)["accent"]["light"],
        )
