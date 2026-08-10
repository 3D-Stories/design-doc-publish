"""#17 wave 2: typed fenced blocks — a fence whose info string names a block type.

The mechanism every template is built from, so it lands BEFORE the templates.

Non-negotiables:
* An **unknown tag warns and degrades to a code listing** — never fails the render.
  A doc is not worth losing over a typo in a fence.
* Escape-first still holds: block bodies are author text and are escaped before any
  component markup wraps them.
* `plain` is untouched. Typed blocks are a rich-style feature; plain keeps rendering
  every fence as a code listing, which is also the graceful-degradation story for any
  other markdown viewer.
"""
import re
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render  # noqa: E402
from render import blocks  # noqa: E402
from render import templates  # noqa: E402

TAGS = ("stats", "verdict", "chips", "callout", "legend", "meter",
        "findings", "steps", "nodes", "provenance",
        # #39 — the component vocabulary waves 3-5 build against.
        "timeline", "options", "steprail")

GRAMMAR_DOC = SCRIPTS.parent / "docs" / "typed-blocks-grammar.md"


def _render(src):
    return render._render_body(src, style="design")


def _fence(tag, body):
    return f"```{tag}\n{body}\n```\n"


# --- the tag set exists and each one renders a marked component -------------------

def test_every_tag_is_registered():
    """#17 fixed the wave-2 set; later waves ADD to it deliberately and name themselves here.
    #68 added `composition`, the segmented device the approved visual spec calls its
    signature — `meter` answers "how far along", this answers "made of what" — and then
    `phases`, the ordered container it measures. #76 added `flow`, a real flow chart
    for `workflow` — boxes and arrows, where `nodes` is an indentation tree.
    #57 added `faq`: independent, closed-by-default disclosures. `steprail` is the only other
    block that emits `<details>` and it cannot produce that shape — its `name` grouping makes
    the items exclusive and a one-row fence emits `open` — so this is a new tag rather than a
    flag on a block whose documented point is one-open-at-a-time."""
    assert set(blocks.BLOCK_TAGS) == set(TAGS) | {"composition", "phases", "flow", "faq"}


def test_every_tag_has_a_grammar_section_an_author_can_read():
    """A block type nobody can find out how to write is a block type nobody uses.

    This guard exists because `composition` shipped in PR 1 of #68 with no section in
    `typed-blocks-grammar.md` — the tag set, the doc-type map and the marker table were all
    updated and the one page an AUTHOR reads was not. Nothing failed, because nothing looked.
    """
    grammar = (SCRIPTS.parent / "docs" / "typed-blocks-grammar.md").read_text(encoding="utf-8")
    missing = [t for t in blocks.BLOCK_TAGS if f"\n## {t}\n" not in grammar]
    assert not missing, f"no grammar section for: {missing}"


@pytest.mark.parametrize("tag", TAGS)
def test_each_tag_renders_a_marked_component(tag):
    """AC1: each block renders its component with a `.tpl-`-convention marker."""
    body = {
        "stats": "82 | sessions read",
        "verdict": "ship | it is sound",
        "chips": "merged | done",
        "callout": "warn | Title\nBody prose.",
        "legend": "done | shipped",
        "meter": "Suite | 194 | 250",
        "findings": "high | A title | some detail",
        "steps": "1 | Do it | how",
        "nodes": "render\n  markdown | the parser",
        "provenance": "issue | #17",
        "timeline": "09:14 | Alert fires | rate crosses 2% | past",
        "options": "Debounce | small diff | per call site | chosen",
        "steprail": "1 | Fetch | at the pinned SHA | action",
    }[tag]
    out = _render(_fence(tag, body))
    assert f"blk-{tag}" in out, f"{tag} must carry its .tpl-convention marker"
    assert "<pre><code>" not in out, f"{tag} must render a component, not a code listing"


@pytest.mark.parametrize("tag", TAGS)
def test_no_tag_emits_a_colour(tag):
    """The property that keeps a per-project VDL enforceable: the author never
    writes a colour, and neither does the block engine."""
    out = _render(_fence(tag, "a | b | accent"))
    for probe in ("#", "rgb(", "hsl(", "color:", "background:"):
        assert probe not in out, f"{tag} leaked a literal colour ({probe})"


# --- AC2: unknown tags degrade, never fail ----------------------------------------

def test_unknown_tag_warns_and_degrades_to_a_code_listing(capsys):
    out = _render(_fence("wibble", "1 | 2"))
    assert "<pre><code>" in out, "an unknown tag must degrade to a code listing"
    assert "1 | 2" in out
    err = capsys.readouterr().err
    assert "wibble" in err and "not a known block type" in err


def test_a_language_fence_is_still_a_code_listing(capsys):
    """`python` is a language, not a block type — it must render exactly as before
    and must NOT warn, or every code sample in every doc would emit noise."""
    out = _render("```python\nx = 1\n```\n")
    assert "<pre><code>" in out and "x = 1" in out
    assert "unknown" not in capsys.readouterr().err.lower()


def test_a_bare_fence_is_still_a_code_listing(capsys):
    out = _render("```\nplain code\n```\n")
    assert "<pre><code>" in out
    assert capsys.readouterr().err == ""


def test_a_malformed_row_does_not_kill_the_render(capsys):
    """A row the grammar cannot represent is author error, not a crash — and since
    the Step 11 review it degrades the WHOLE fence rather than rendering a component
    that silently drops the bad row. Both lines survive as a code listing."""
    out = _render(_fence("stats", "no pipe here\n82 | fine"))
    assert "<pre><code>" in out
    assert "no pipe here" in out and "82 | fine" in out
    assert "blk-stats" not in out
    assert "1 field" in capsys.readouterr().err


# --- AC3: a block a doc type does not accept warns --------------------------------

def test_doc_type_rejecting_a_tag_warns_but_still_renders(capsys):
    """AC3. The warning is the product — it must not silently drop content."""
    accepted = blocks.accepts("spec")
    rejected = next(t for t in TAGS if t not in accepted)
    out = blocks.render_block(rejected, "a | b", doc_type="spec")
    err = capsys.readouterr().err
    assert rejected in err and "spec" in err
    assert out, "a rejected block must still render, not vanish"


VALID_BODY = {
    "stats": "82 | sessions read", "verdict": "ship | sound",
    "chips": "merged | done", "callout": "warn | Title\nProse.",
    "legend": "done | shipped", "meter": "Suite | 194 | 250",
    "findings": "high | title | detail", "steps": "1 | title | how",
    "nodes": "root\n  child | desc", "provenance": "issue | #17",
    "timeline": "09:14 | Alert fires | rate crosses 2% | past",
    "options": "Debounce | small diff | per call site | chosen",
    "steprail": "1 | Fetch | at the pinned SHA | action",
}


def test_a_doc_type_that_accepts_everything_is_silent(capsys):
    for tag in blocks.accepts("design"):
        assert blocks.render_block(tag, VALID_BODY[tag], doc_type="design")
    assert capsys.readouterr().err == ""


def test_unknown_doc_type_does_not_warn(capsys):
    """An unknown doc type means "no policy", not "reject everything"."""
    blocks.render_block("stats", "1 | x", doc_type="not-a-real-type")
    assert capsys.readouterr().err == ""


# --- escape-first ------------------------------------------------------------------

HOSTILE_CELL = '<script>alert(1)</script> & <b>x</b>'

# Each tag gets a body of the RIGHT SHAPE carrying hostile content in a cell the tag
# actually renders. (callout's first cell is a consumed tone marker, so the hostile
# text goes in its title instead — putting it in the tone would test nothing.)
HOSTILE_BODY = {
    "stats": f"{HOSTILE_CELL} | label", "verdict": f"ship | {HOSTILE_CELL}",
    "chips": f"{HOSTILE_CELL} | done", "callout": f"warn | {HOSTILE_CELL}",
    "legend": f"done | {HOSTILE_CELL}", "meter": f"{HOSTILE_CELL} | 1 | 2",
    "findings": f"high | {HOSTILE_CELL} | d", "steps": f"1 | {HOSTILE_CELL} | d",
    "nodes": f"{HOSTILE_CELL}", "provenance": f"key | {HOSTILE_CELL}",
    "timeline": f"09:14 | {HOSTILE_CELL} | d | past",
    "options": f"{HOSTILE_CELL} | a | b | chosen",
    "steprail": f"1 | {HOSTILE_CELL} | d | action",
}


@pytest.mark.parametrize("tag", TAGS)
def test_block_bodies_are_escaped(tag):
    out = _render(_fence(tag, HOSTILE_BODY[tag]))
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert "<b>x</b>" not in out


def test_block_output_only_uses_whitelisted_tags():
    import re
    src = "".join(_fence(t, "a | b | accent") for t in TAGS)
    # `a | b | accent` is too short to reach the sparkline or the rail, so add rows that do
    # — otherwise the whitelist silently stops covering the components that widened it.
    src += _fence("stats", "155 | findings | +12 | 3,5,4,8,9")
    src += _fence("steprail", "1 | Fetch | at the pinned SHA | action")
    out = _render(src)
    # #39 adds `svg` and `polyline` because AC3 requires the sparkline to be inline SVG
    # rather than an <img> or an external request. Both are static, self-contained markup
    # with no script surface. This is an allowlist EXTENSION for a capability that was
    # deliberately added — not a guard being relaxed to make new code pass.
    allowed = {"p", "br", "div", "span", "ul", "ol", "li", "dl", "dt", "dd",
               "section", "h3", "h4", "strong", "em", "code", "pre", "table",
               "thead", "tbody", "tr", "th", "td", "svg", "polyline",
               # #39: `details`/`summary` give the step rail reveal-on-click and
               # one-open-at-a-time natively, which is how it ships with no script at all.
               "details", "summary",
               # `button` arrives with the copy control on an ordinary code listing, and
               # reaches this test through a DEGRADED typed block — a malformed `timeline`
               # or `steprail` falls back to exactly that listing. The element carries no
               # inline handler and no `formaction`: the markup is inert, and the page's one
               # script binds to it by class after the fact. Same shape as the two
               # extensions above — a capability deliberately added, not a guard relaxed.
               "button"}
    for t in re.findall(r"<\s*/?\s*([A-Za-z][A-Za-z0-9]*)", out):
        assert t.lower() in allowed, f"unexpected tag <{t}>"


# --- plain is untouched -------------------------------------------------------------

@pytest.mark.parametrize("tag", TAGS)
def test_plain_renders_every_typed_block_as_a_code_listing(tag):
    """Typed blocks are a rich feature. In plain — and in any other markdown viewer —
    the fence degrades to a code listing rather than mangling the content."""
    out = render._render_body(_fence(tag, "82 | sessions read"), style="plain")
    assert "<pre><code>" in out
    assert "82 | sessions read" in out
    assert f"blk-{tag}" not in out


# --- the hand-authored grammar page actually renders --------------------------------

def test_the_authored_grammar_page_renders_every_block():
    """The page written BEFORE the renderer (the issue's own risk mitigation) must
    render — every fence in it becomes a component, none degrade."""
    out = _render(GRAMMAR_DOC.read_text(encoding="utf-8"))
    for tag in TAGS:
        assert f"blk-{tag}" in out, f"the grammar page's {tag} block did not render"


def test_nodes_uses_indentation_for_depth():
    """The authoring exercise changed this grammar: pipes encoded depth, which was
    unreadable past two levels. Depth is indentation; the single pipe splits
    label from description."""
    out = _render(_fence("nodes", "render\n  markdown | the parser\n  blocks | typed\nscripts"))
    assert out.count("<ul>") >= 2, "a child level needs its own list"
    assert out.count("<ul>") == out.count("</ul>")


def test_callout_first_line_is_tone_and_title():
    out = _render(_fence("callout", "warn | Do not fix plain\nByte-identity is an AC."))
    assert "Do not fix plain" in out
    assert "Byte-identity is an AC." in out
    assert "warn |" not in out, "the tone marker must be consumed, not printed"


def test_meter_requires_an_explicit_maximum():
    """The authoring exercise found an inferred scale was a guess at author intent."""
    out = _render(_fence("meter", "Children merged | 3 | 9"))
    assert "blk-meter" in out
    assert "3" in out and "9" in out


# --- Step 11 review findings, each reproduced then fixed ---------------------------

def test_malformed_row_degrades_the_whole_fence_instead_of_dropping_content(capsys):
    """Step 11 #1 (High): a callout with no pipe turned the author's entire prose
    into a CSS class and rendered an EMPTY component — silent content loss."""
    assert blocks.render_block("callout", "Just prose, no pipe") is None
    assert "first line must be" in capsys.readouterr().err
    out = _render(_fence("callout", "Just prose, no pipe"))
    assert "<pre><code>" in out and "Just prose, no pipe" in out


@pytest.mark.parametrize("tag,body", [
    ("stats", "only-one-cell"), ("meter", "label | 3"), ("findings", "high | title"),
    ("steps", "1 | title"), ("provenance", "keyonly"), ("legend", "keyonly"),
])
def test_short_rows_degrade_rather_than_render_a_lossy_component(tag, body):
    assert blocks.render_block(tag, body) is None


def test_extra_cells_warn_rather_than_being_silently_truncated(capsys):
    # #13 gave findings a 4th field (the provenance tail), so the truncation
    # guard moves to the 5th.
    blocks.render_block("findings", "high | title | detail | tail | EXTRA")
    assert "extra" in capsys.readouterr().err.lower()


def test_a_semantic_token_cannot_inject_a_second_class(capsys):
    """Step 11 #2 (Medium): escaping stops quote breakout but not SPACES, so
    `high is-accent` emitted `class="blk-finding is-high is-accent"`."""
    out = blocks.render_block("findings", "high is-accent | t | d")
    assert 'is-note"' in out, "an invalid token must fall back, not be interpolated"
    assert "is-high is-accent" not in out
    assert "high is-accent" in out, "the author's text must still be visible"
    assert "not a semantic token" in capsys.readouterr().err


def test_nodes_siblings_share_one_list_and_children_nest_inside_the_parent():
    """Step 11 #3 (Medium): every line opened its own <ul>, and each <li> closed
    before its descendants — invalid structure and wrong hierarchy."""
    out = blocks.render_block("nodes", "root\n  child\n  child2\nsib")
    assert out.count("<ul>") == 2, "one list per depth, not one per line"
    assert out.count("<ul>") == out.count("</ul>")
    assert out.count("<li") == out.count("</li>")
    assert "</span><ul>" in out, "a child list must open inside its parent li"
    assert "</ul></li>" in out, "and close before that li closes"


def test_nodes_tabs_and_spaces_indent_the_same():
    tabbed = blocks.render_block("nodes", "root\n\tchild")
    spaced = blocks.render_block("nodes", "root\n    child")
    assert tabbed == spaced


@pytest.mark.parametrize("value,maximum", [("nan", "1"), ("inf", "inf"),
                                           ("1e400", "1"), ("1", "nan")])
def test_meter_never_presents_a_non_finite_value_as_complete(value, maximum, capsys):
    """Step 11 #4 (Medium): nan and inf clamped to width:100% — an invalid
    measurement rendered as a finished one."""
    out = blocks.render_block("meter", f"x | {value} | {maximum}")
    assert "width:" not in out
    assert "non-finite" in capsys.readouterr().err
    assert value in out, "the numbers themselves must still render"


def test_meter_still_draws_a_bar_for_ordinary_numbers():
    out = blocks.render_block("meter", "x | 3 | 9")
    assert 'style="width:33.3%"' in out


def test_an_unlisted_language_fence_does_not_warn(capsys):
    """Step 11 #5 (Low): a fixed language allowlist warned on real fences — this
    repo already contains ```powershell. The policy is now: warn only when the body
    actually looks like block grammar."""
    assert blocks.render_fence("powershell", "Get-Item x") is None
    assert blocks.render_fence("somethingnew", "no pipes here at all") is None
    assert capsys.readouterr().err == ""


def test_a_typoed_block_tag_still_warns(capsys):
    """The warning that matters must survive the noise reduction."""
    assert blocks.render_fence("statz", "82 | sessions read") is None
    assert "statz" in capsys.readouterr().err


# --- #133: `--accent-soft` defined once, not improvised per component -------------------

class TestAccentSoftIsATokenNotAnImprovisation:
    """#133 (from #78 item 1, originally #46's D15). Components wanting a low-intensity accent
    fill each invented their own `color-mix`, and since the #77 rebuild there is a LIVE consumer
    waiting on the token: the timeline's `is-now` halo styles itself with
    `box-shadow: 0 0 0 3px var(--accent-soft, transparent)`, so the halo rendered as NOTHING on
    every style, in both modes.

    THE ISSUE'S AC1 AND AC4 CANNOT BOTH HOLD LITERALLY, and this suite encodes the resolution.
    AC1 says define it "wherever `--accent` is" — that is `_STYLE`, which `plain` also receives.
    AC4 says `plain` stays byte-identical. `blocks.py`'s own comment already recorded the
    consequence: anything added to the shared block "changes the pinned exemplar and breaks
    byte-identity", and #75 wrote it down too ("adding hues to the shared `:root` block moves
    EVERY style's bytes, `plain` included, which AC2 forbids outright").

    So the token is defined wherever it can be CONSUMED: `BLOCK_CSS`, which every non-plain
    template receives and `plain` receives none of. `plain` renders every typed block as a code
    listing, so it can never hold a timeline halo — a token there would be bytes with no possible
    consumer. AC1's intent is met in full, including VDL packs, because the value is DERIVED from
    `var(--accent)` rather than declared per theme.
    """

    def _page(self, style="design", body=None):
        md = body if body is not None else (
            "## H\n\n```timeline\n2026-01-01 | now | Shipped\n```\n")
        return render.render_artifact(md, title="T", style=style)

    def test_the_token_is_defined_and_derived_from_the_accent(self):
        """Derived, not declared per theme: one declaration then tracks every theme block AND any
        VDL pack override, because `--accent` and `--accent-soft` sit on the same element and the
        pack's `--accent` wins by source order."""
        css = blocks.BLOCK_CSS
        assert "--accent-soft:" in css, "the token must be defined where it can be consumed"
        assert "var(--accent)" in css.split("--accent-soft:")[1][:80], (
            "it must DERIVE from --accent, so a VDL pack that sets --accent yields a matching soft")
        assert not re.search(r"--accent-soft:\s*#", css), "no hardcoded hex — packs must restyle it"

    @pytest.mark.parametrize("style", sorted(s for s in render._TEMPLATES if s != "plain"))
    def test_every_non_plain_style_defines_it(self, style):
        assert "--accent-soft:" in self._page(style)

    def test_plain_does_not_define_it_and_cannot_consume_it(self):
        """AC4. `plain` gets no block layer at all, so this is byte-inert there by construction —
        and `plain` renders a timeline as a code listing, so there is no halo to colour."""
        page = self._page("plain")
        assert "--accent-soft" not in page
        assert "blk-timeline" not in page

    def test_the_halo_no_longer_depends_on_the_transparent_fallback(self):
        """AC2. The rule may keep its fallback as belt-and-braces, but the token it names must
        actually be defined on the page, so the fallback is never what renders."""
        page = self._page("design")
        assert "var(--accent-soft" in page, "the halo consumer is present"
        assert "--accent-soft:" in page, "and the token is defined, so the fallback is unused"

    def test_the_design_decision_gradient_uses_the_token(self):
        """AC3. `design.py` improvised `color-mix(in srgb,var(--accent) 12%,transparent)` inline.
        The token's value is that exact mix, so substituting it changes no rendering."""
        design_css = templates.CSS["design"]
        assert "color-mix" not in design_css, "the improvisation must be gone"
        assert "var(--accent-soft)" in design_css

    @staticmethod
    def _mixes(css):
        """Every `color-mix(…)` with its parentheses balanced, and where it starts.

        A `color-mix\\([^)]*\\)` regex stops at the nested `var(--accent)` paren — the first draft of
        this guard did exactly that and failed against the correct implementation.
        """
        for m in re.finditer(r"color-mix\(", css):
            i, depth = m.end(), 1
            while i < len(css) and depth:
                depth += (css[i] == "(") - (css[i] == ")")
                i += 1
            yield m.start(), css[m.start():i]

    def test_no_component_improvises_an_accent_mix_any_more(self):
        """AC3 as a standing guard, across every template and the block layer.

        Scoped to mixes that reference `var(--accent)`, which is what AC3 is about. Step 11 caught
        the first version policing EVERY `color-mix()` anywhere: that would have failed a future
        unrelated mix — two neutrals, a severity tint — for no reason connected to this issue, and
        it is not this test's business to forbid colour mixing in general.
        """
        sources = dict(templates.CSS)
        sources["BLOCK_CSS"] = blocks.BLOCK_CSS
        for name, css in sources.items():
            for start, mix in self._mixes(css):
                if "var(--accent)" not in mix:
                    continue
                # `rstrip` so ordinary whitespace after the colon is not a failure — Step 11 flagged
                # that too, and a guard that trips on formatting is a guard people delete.
                head = css[:start].rstrip()
                assert head.endswith("--accent-soft:"), (
                    f"{name} improvises an accent mix instead of using the token: {mix} "
                    f"(at ...{head[-50:]!r})")

    def test_the_guard_permits_an_unrelated_mix_and_still_catches_an_accent_one(self):
        """Step 11's finding, pinned both ways — the narrowing must not have disarmed the guard."""
        cls = type(self)
        unrelated = ".x{background:color-mix(in srgb,var(--line) 50%,var(--surface))}"
        assert [m for _, m in cls._mixes(unrelated)], "the extractor sees it"
        assert all("var(--accent)" not in m for _, m in cls._mixes(unrelated)), "and skips it"
        improvised = ".x{background:color-mix(in srgb,var(--accent) 30%,transparent)}"
        starts = [s for s, m in cls._mixes(improvised) if "var(--accent)" in m]
        assert starts and not improvised[:starts[0]].rstrip().endswith("--accent-soft:"), (
            "an improvised accent mix must still be caught")

    def test_a_vdl_pack_page_yields_a_matching_soft_without_the_pack_declaring_one(self):
        """AC1's real requirement. A pack overrides `--accent`; because the soft token derives from
        it, the pack gets a matching halo for free and cannot forget to supply one."""
        pack = {"accent": {"light": "#1e5f7a", "dark": "#7ad0ee"}, "origin": "test"}
        page = render.render_artifact(
            "## H\n\n```timeline\n2026-01-01 | now | Shipped\n```\n",
            title="T", style="design", vdl=pack)
        assert "--accent:#1e5f7a" in page and "--accent:#7ad0ee" in page
        assert "--accent-soft:" in page
        assert not re.search(r"--accent-soft:[^;}]*#", page), (
            "the pack must not need its own soft value — a hex here means it was declared, "
            "not derived, and a future pack would have to remember to supply one")
