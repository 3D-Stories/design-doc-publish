"""An image renders as a thumbnail that opens the full image (`imgzoom`, #78).

A bare `<img>` had no size rule anywhere in the renderer, so a wide diagram ran past the edge of
a phone-width page. Every accepted image in a rich template now renders as a thumbnail capped at
300 px, inside a link to the full image. A small script opens that link in a `<dialog>`.

What these tests pin, and why each one exists:

* **`plain` is untouched.** It renders no image at all (`_inline` has no image construct), its
  bytes are pinned elsewhere, and nothing here may leak into it.
* **The `<img>` itself is byte-identical.** Several existing tests grep for `<img src=...>`. The
  thumbnail only WRAPS that tag, so those assertions keep meaning what they meant.
* **Refusals are unchanged.** A refused or external image stays literal and inert, exactly as
  before, and records no feature.
* **No nested links, and no uncapped image.** A linked image, `[![a](a.png)](p.html)`, keeps its
  own target: wrapping it in a zoom link would have put an `<a>` inside an `<a>`. It still gets the
  thumbnail box, because a bare `<img>` is the very overflow this fixes, and the script skips it.
* **The script is opt-in.** A page with no accepted image emits no script and no CSS for it.
* **No dead control, no lost link.** With JavaScript off the thumbnail is still a plain link to the
  full image, so the fallback needs no script at all.

The modal itself (open, Escape, a click, the close button, focus return, a modified click left
alone) was checked in a real browser rather than asserted here, for the reason
`test_code_copy.py` gives: a DOM-free pytest cannot run the handler.
"""
import re
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render  # noqa: E402
from render import blocks, lint  # noqa: E402
# One definition of the DOM calls a renderer-owned script may not use: the list `codecopy` and
# `uat` are already held to. Only the one HTML-writing call that list predates is added here.
from test_code_copy import FORBIDDEN as _SHARED_FORBIDDEN  # noqa: E402

IMG = "# T\n\nThe flow:\n\n![Connect a calendar](flows/connect.png)\n"
NO_IMG = "# T\n\nJust prose, and a [link](other.html) which is not an image.\n"
TAG = '<img src="flows/connect.png" alt="Connect a calendar">'
THUMB = f'<a class="doc-img" href="flows/connect.png">{TAG}</a>'
# Every rich style, taken from the registry itself, so a new template is covered the day it lands.
RICH = tuple(sorted(k for k in render._TEMPLATES if k != "plain"))


def _page(md=IMG, style="design"):
    return render.render_artifact(md, title="T", style=style, generated_at="2026-01-01 00:00 MST",
                                  doc_id="t")


def _scripts(html):
    return re.findall(r"<script>(.*?)</script>", html, re.S)


def _features(md, style="design"):
    ctx = {}
    render._render_body(md, style=style, ctx=ctx)
    return blocks.used_features(ctx)


# --- plain keeps exactly what it had ------------------------------------------------

def test_plain_renders_no_image_and_no_thumbnail():
    out = render._render_body(IMG, style="plain")
    assert "<img" not in out
    assert "doc-img" not in out


def test_plain_page_carries_no_zoom_script_or_css():
    page = _page(style="plain")
    assert _scripts(page) == []
    assert "doc-zoom" not in page and "doc-img" not in page


# --- the rich form wraps, never rewrites --------------------------------------------

@pytest.mark.parametrize("style", RICH)
def test_every_rich_style_wraps_an_image_in_a_link_to_itself(style):
    assert THUMB in _page(style=style), style


def test_the_img_tag_inside_is_byte_identical_to_before():
    """The wrapper adds an anchor around the tag the renderer always emitted, nothing else."""
    assert TAG in render._render_body(IMG, style="design")


def test_an_image_in_a_table_cell_is_wrapped_too():
    md = "# T\n\n| Step | Picture |\n|---|---|\n| One | ![a](a.png) |\n"
    assert '<a class="doc-img" href="a.png"><img src="a.png" alt="a"></a>' in _page(md)


def test_the_feature_is_recorded_only_when_an_image_rendered():
    assert "imgzoom" in _features(IMG)
    assert "imgzoom" not in _features(NO_IMG)


def test_the_feature_count_holds_rich_styles_to_the_registry():
    """Thirteen when this was written. A shrinking registry is a change worth noticing."""
    assert len(RICH) >= 13 and "plain" not in RICH


DISCARDED = "# T\n\n```steps\na | ![a](a.png) | x | MUST\na | duplicate | x | MUST\n```\n"


def test_an_image_in_a_discarded_typed_block_records_no_feature():
    """Astra F1 (#78 review): the duplicate step id makes the whole fence fall back to a listing,
    so no thumbnail survives. Recording the feature while the doomed block was still being
    rendered left a zoom script and CSS on a page with no image."""
    page = render.render_artifact(DISCARDED, title="T", style="uat",
                                  generated_at="2026-01-01 00:00 MST", doc_id="t")
    assert "<img" not in page
    assert "doc-zoom" not in page and ".doc-img{" not in page
    assert not any("showModal" in sc for sc in _scripts(page))
    assert "imgzoom" not in _features(DISCARDED, style="uat")


# --- refusals and links behave exactly as before -------------------------------------

def test_an_external_image_stays_literal_and_records_no_feature():
    md = "# T\n\n![x](https://evil.example/x.png)\n"
    page = _page(md)
    assert "doc-img" not in page
    assert '<img src="https://evil.example' not in page
    assert "imgzoom" not in _features(md)


def test_a_bad_scheme_image_stays_literal():
    assert "doc-img" not in _page("# T\n\n![x](javascript:alert(1))\n")


LINKED = "# T\n\n[![a](a.png)](page.html)\n"


def test_a_linked_image_keeps_its_own_target_and_never_nests_links():
    out = render._render_body(LINKED, style="design")
    assert '<a class="doc-img doc-img-link" href="page.html"><img src="a.png" alt="a"></a>' in out
    assert 'href="a.png"' not in out
    assert not re.search(r"<a\b[^>]*>(?:(?!</a>).)*<a\b", out, re.S), "an <a> nested in an <a>"


def test_a_linked_image_is_capped_like_a_thumbnail():
    """Measured: left bare, a 996 px linked diagram made a 360 px page 1036 px wide."""
    assert "imgzoom" in _features(LINKED)
    assert ".doc-img{" in _page(LINKED)


def test_the_script_skips_a_linked_image():
    """A linked image already says where it goes. The modal would hijack that click."""
    assert "a.doc-img:not(.doc-img-link)" in _scripts(_page(LINKED))[0]


def test_an_image_inside_link_text_is_capped_without_nesting_links():
    """`[see ![a](a.png) here](p.html)`: the image sits mid-text, so the LINK cannot be the box.
    It gets a span box instead, which caps it and nests nothing."""
    out = render._render_body("# T\n\n[see ![a](a.png) here](p.html)\n", style="design")
    assert '<a href="p.html">see <span class="doc-img"><img src="a.png" alt="a"></span> here</a>' in out
    assert not re.search(r"<a\b[^>]*>(?:(?!</a>).)*<a\b", out, re.S), "an <a> nested in an <a>"


def test_only_a_zooming_thumbnail_shows_a_zoom_cursor():
    """A linked image is a link, so it keeps the browser's own link cursor."""
    css = blocks.optional_css({"imgzoom"})
    assert "a.doc-img:not(.doc-img-link){cursor:zoom-in}" in css
    assert "cursor" not in css.split(".doc-img{", 1)[1].split("}", 1)[0]


# --- the script is opt-in, one per page, and CSP-honest -------------------------------

def test_a_rich_page_with_no_image_emits_no_script_and_no_zoom_css():
    page = _page(NO_IMG)
    assert _scripts(page) == []
    assert "doc-zoom" not in page and ".doc-img{" not in page


def test_a_rich_page_with_an_image_emits_exactly_one_script():
    assert len(_scripts(_page())) == 1


def test_many_images_still_emit_one_script():
    page = _page(IMG + "\n![b](b.png)\n\n![c](c.png)\n")
    assert len(_scripts(page)) == 1
    assert page.count('<a class="doc-img"') == 3


def test_an_image_and_a_fence_emit_one_script_each():
    """Two features, two layers, in the fixed declaration order, never a merged blob."""
    scripts = _scripts(_page(IMG + "\n```bash\npytest -q\n```\n"))
    assert len(scripts) == 2
    assert "doc-code" in scripts[0] and "showModal" in scripts[1]


def test_the_feature_registers_both_a_css_and_a_js_layer():
    assert blocks.optional_css({"imgzoom"}) != ""
    assert blocks.optional_js({"imgzoom"}) != ""


# --- the script's own contract ------------------------------------------------------

FORBIDDEN = tuple(_SHARED_FORBIDDEN) + ("insertAdjacentHTML",)


@pytest.mark.parametrize("api", FORBIDDEN)
def test_the_script_uses_no_forbidden_dom_api(api):
    assert api not in _scripts(_page())[0]


def test_the_script_is_inline_and_never_fetched():
    assert not re.search(r"<script[^>]+src=", _page(), re.I)


def test_the_script_opens_a_modal_dialog():
    script = _scripts(_page())[0]
    assert "createElement('dialog')" in script and "showModal()" in script


def test_the_script_stands_down_where_dialog_is_unsupported():
    """No `showModal` means the link keeps its plain behaviour: open the full image."""
    assert "typeofdlg.showModal!=='function'" in _scripts(_page())[0].replace(" ", "")


def test_the_script_leaves_a_modified_click_alone():
    """Ctrl-, Cmd-, Shift- and middle-click mean "open it elsewhere". Hijacking them breaks a
    reader's own way of opening the image in a new tab."""
    script = _scripts(_page())[0].replace(" ", "")
    for key in ("e.button!==0", "e.metaKey", "e.ctrlKey", "e.shiftKey", "e.altKey"):
        assert key in script, key


def test_the_script_returns_focus_to_the_thumbnail_on_close():
    script = _scripts(_page())[0]
    assert "addEventListener('close'" in script and "opener.focus()" in script


def test_the_script_writes_the_caption_as_text_not_markup():
    """The caption is the alt text, which is author text. `textContent` cannot open an element."""
    assert "cap.textContent" in _scripts(_page())[0]


# --- escape-first still holds -------------------------------------------------------

def test_a_hostile_alt_cannot_break_the_attribute():
    page = _page('# T\n\n![x" onerror="alert(1)](a.png)\n')
    assert 'onerror="alert(1)"' not in page
    assert "&quot;" in page


def test_a_hostile_url_cannot_break_the_href():
    assert 'onmouseover="alert(1)"' not in _page('# T\n\n![a](a.png"onmouseover="alert(1))\n')


# --- the styling does what the request asked for -------------------------------------

def test_the_thumbnail_is_capped_at_300px_and_never_wider_than_its_column():
    assert "max-width:min(300px,100%)" in blocks.optional_css({"imgzoom"})


def test_the_thumbnail_image_scales_with_its_box():
    css = blocks.optional_css({"imgzoom"})
    assert re.search(r"\.doc-img img\{[^}]*max-width:100%[^}]*height:auto", css)


def test_the_thumbnail_has_a_visible_focus_ring():
    assert ".doc-img:focus-visible" in blocks.optional_css({"imgzoom"})


def test_print_shows_the_image_at_full_column_width():
    """Paper cannot open a modal, so a printed page gets the full image, not a thumbnail."""
    assert re.search(r"@media print\{\.doc-img\{max-width:100%", blocks.optional_css({"imgzoom"}))


def test_the_modal_dims_the_page_behind_it():
    assert ".doc-zoom::backdrop{" in blocks.optional_css({"imgzoom"})


def test_the_css_reaches_no_external_host():
    css = blocks.optional_css({"imgzoom"})
    assert "http://" not in css and "https://" not in css and "url(" not in css


# --- the page still passes the pre-publish gate ---------------------------------------

@pytest.mark.parametrize("style", RICH)
def test_a_page_with_a_thumbnail_passes_the_lint_gate(style):
    """A real title, because the gate rightly refuses the placeholder `T` the other tests use."""
    page = render.render_artifact(IMG, title="Connect a calendar", style=style,
                                  generated_at="2026-01-01 00:00 MST", doc_id="t")
    assert lint.lint(page) == []
