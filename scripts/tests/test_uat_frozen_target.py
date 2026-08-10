"""The `uat` rebuild against its frozen target (#75, lane B6).

The owner, looking at the rendered page on 2026-08-02: *"UAT still looks like shit."* They allowed
it has some of the right elements — checkboxes, comment boxes, a report you paste back — which
made it the closest of the ten and still not close.

The target is `docs/planning/shots/target-uat-checklist.png` and `-items.png`, captured from
a deployed UAT checklist page. **The capture is the spec, not the URL.** Its five
signature devices, and what each test below is holding in place:

1. a two-tone display headline, phrases alternating ink and accent, as the first-read element
2. a pill badge per part whose colour cycles, with the panel's left border matching it
3. real square checkboxes with coloured borders
4. a STOP callout carrying a mark, for the thing that must halt the tester
5. a sticky progress bar reading `n / total` in mono

Two of those needed engine surface, because a template's own stylesheet cannot reach them:
the headline split (only the AUTHOR knows where phrases divide) and the accent palette
(`test_it_declares_no_literal_colour_of_any_form` bans every hex, named colour and colour
function — `color-mix()` included — from a template's CSS, and the shared token layer has one
accent hue). Both are opt-in and both are byte-inert for the nine styles that decline them;
`TestTheEngineAdditionsAreOptIn` is what pins that.
"""
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render  # noqa: E402
from render import frame, templates  # noqa: E402

DOC = """# T

## Install

```steps
1 | Run the installer. | must
```

```callout stop
crit | Stop if the version is wrong
Anything else means the **wrong build**.
```

## The screenshot

```steps
2 | Take a screenshot. | must
```

## The sherpa model

```steps
3 | Pin a model. | must
```

## Regression sweep

```steps
4 | Old projects still open. | must
```
"""


def _page(title="Three builds | landed", style="uat", md=DOC):
    return render.render_artifact(md, title=title, style=style,
                                  generated_at="x", doc_id="d")


UAT_CSS = templates.CSS["uat"]


class TestTheTwoToneHeadline:
    def test_the_author_divides_the_phrases_and_both_are_emitted(self):
        page = _page()
        assert '<span class="h1-a">Three builds</span>' in page
        assert '<span class="h1-b">landed</span>' in page

    def test_the_two_tones_are_actually_different_colours(self):
        assert ".h1-a{color:var(--ink)}" in UAT_CSS
        assert ".h1-b{color:var(--tpl-a1" in UAT_CSS

    def test_phrases_alternate_rather_than_only_colouring_the_tail(self):
        page = _page(title="one | two | three | four")
        assert page.count('class="h1-a"') == 2
        assert page.count('class="h1-b"') == 2

    def test_the_separator_never_reaches_the_browser_tab(self):
        page = _page()
        assert "<title>Three builds landed</title>" in page
        assert "|" not in page[:page.index("</head>")]

    def test_a_title_with_no_separator_is_left_exactly_alone(self):
        page = _page(title="Just one phrase")
        assert "<h1>Just one phrase</h1>" in page

    def test_author_text_in_a_phrase_is_escaped(self):
        # NOT `"<script>" not in page`: `uat` legitimately ships exactly one inline script, so
        # that assertion could never fail for the reason it appears to test. What matters is that
        # the TITLE's markup was escaped and no SECOND script was created.
        page = _page(title="safe | <script>x</script>")
        assert "&lt;script&gt;x&lt;/script&gt;" in page
        assert page.count("<script>") == 1


class TestThePartAccentCycles:
    def test_four_distinct_accents_are_declared(self):
        assert len(set(templates.TEMPLATES["uat"].ACCENTS)) == 4

    def test_the_engine_emits_them_scoped_to_this_style(self):
        page = _page()
        assert "body.tpl-uat{--tpl-a1:" in page

    def test_every_part_reads_the_same_indirection(self):
        """One variable, four rules that set it — so re-ordering the cycle is a four-line
        change and not a sweep through every device that spends the accent."""
        for n in (2, 3, 4):
            assert f".ut-step:nth-of-type(4n+{n}){{--ut-a:var(--tpl-a{n}" in UAT_CSS

    def test_the_panel_edge_takes_the_part_accent(self):
        assert ".ut-step{border-left:3px solid var(--ut-a)}" in UAT_CSS

    def test_a_style_that_declares_no_palette_emits_none(self):
        assert "--tpl-a1" not in _page(style="report")

    def test_the_palette_layer_is_empty_without_a_declaration(self):
        assert frame.palette_layer("report", None) == ""
        assert frame.palette_layer("report", ()) == ""


class TestThePartPillIsCountedNotAuthored:
    def test_the_number_comes_from_a_counter(self):
        assert 'content:"part " counter(ut-part)' in UAT_CSS

    def test_the_counter_is_reset_once_and_incremented_per_part(self):
        assert "main{counter-reset:ut-part}" in UAT_CSS
        assert ".ut-step{counter-increment:ut-part}" in UAT_CSS

    def test_the_pill_takes_the_part_accent(self):
        assert "background:var(--ut-a)}" in UAT_CSS


class TestTheCheckboxesAreReal:
    def test_the_box_is_large_enough_to_read_as_a_checkbox(self):
        assert "width:24px;height:24px" in UAT_CSS

    def test_the_border_takes_the_part_accent(self):
        assert "border:2px solid var(--ut-a" in UAT_CSS

    def test_a_checked_box_draws_a_tick_rather_than_only_filling(self):
        """A filled square and a checked square look the same to someone who cannot see the
        fill against the panel. The tick is drawn."""
        assert "input:checked+.ut-box::after" in UAT_CSS

    def test_focus_is_visible(self):
        assert "input:focus-visible+.ut-box{outline:2px solid" in UAT_CSS


class TestTheStopCalloutIsUnmissable:
    def test_it_carries_a_drawn_mark(self):
        assert ".ut-stop>.blk-callout::before" in UAT_CSS
        assert ".ut-stop>.blk-callout::after" in UAT_CSS

    def test_the_mark_is_drawn_not_fetched(self):
        """Self-contained output: no request may leave the page."""
        page = _page()
        assert "url(" not in page
        assert "<img" not in page

    def test_it_still_reaches_the_page_through_its_own_marker(self):
        assert "ut-stop" in _page()


class TestTheEngineAdditionsAreOptIn:
    """The two additions #75 needed must cost the other nine styles nothing. The per-style SHA
    oracle in `test_furniture_context.py` is the real proof; these say WHY it holds."""

    # `workflow` left this list in #76: it now declares `ACCENTS` too, for the approved spec's
    # per-section accent device. That is the mechanism being USED as intended, not a leak — the
    # property under test is that a style which declines a capability is unaffected by it, and
    # the eight below still decline both. `HEADLINE` is still `uat`'s alone.
    @pytest.mark.parametrize("style", ["plain", "analysis", "roadmap", "report", "design",
                                       "dashboard", "review", "spec"])
    def test_no_other_style_declares_either(self, style):
        mod = templates.TEMPLATES.get(style)
        assert getattr(mod, "ACCENTS", None) is None
        assert getattr(mod, "HEADLINE", None) is None

    def test_the_headline_split_is_still_uat_alone(self):
        declaring = [n for n, m in templates.TEMPLATES.items()
                     if getattr(m, "HEADLINE", None) is not None]
        assert declaring == ["uat"], declaring

    @pytest.mark.parametrize("style", ["plain", "analysis", "report", "design",
                                       "dashboard", "review", "spec", "workflow"])
    def test_a_pipe_in_a_title_stays_literal_for_a_style_that_declines_the_split(self, style):
        page = render.render_artifact("# T\n\nbody\n", title="a | b", style=style,
                                      generated_at="x")
        assert "<h1>a | b</h1>" in page
        assert 'class="h1-a"' not in page


class TestTheStylesheetStillObeysItsOwnRules:
    def test_no_literal_colour_survived_the_rebuild(self):
        """AC5's guard lives in `test_uat_template.py` and runs over the whole stylesheet; this
        is the reminder at the rebuild's own door, because the rebuild is what would break it."""
        import re
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", UAT_CSS)
        assert "color-mix(" not in UAT_CSS.lower()

    def test_the_palette_literals_live_in_the_engine_not_the_stylesheet(self):
        assert all(a.startswith("#") for a in templates.TEMPLATES["uat"].ACCENTS)
        assert templates.TEMPLATES["uat"].ACCENTS[0] not in UAT_CSS
