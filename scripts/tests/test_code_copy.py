"""The copy affordance on an ordinary code listing (`codecopy`).

A published doc routinely carries a command the reader is meant to RUN. Selecting it by hand
out of a `<pre>` is the step where a command gets truncated, so the listing now ships a box
with its language and a copy button.

What these tests pin, and why each one exists:

* **`plain` is untouched.** It is documented as carrying no template CSS, it is pinned
  byte-for-byte by two other gates, and no `--type` implies it. The rich form must not leak
  into it, and the bare `<pre><code>` it always emitted must survive unchanged.
* **The inner listing is byte-identical in both forms.** Roughly a dozen existing tests assert
  `"<pre><code>" in out`. The rich form only WRAPS that string, so those assertions keep
  meaning what they meant.
* **The script is opt-in.** A rich page with no ordinary fence must emit no script at all —
  that is the second half of the CSP claim in the package docstring, and the half that
  `test_uat_template.py` cannot make because it never renders a plain fence.
* **Escape-first survives.** The fence's info string is author text and reaches an element,
  so a fence tagged `<script>` must not open one.
* **No dead control.** The button ships `hidden`; only the script reveals it. A reader with
  JavaScript disabled must not see a button that cannot work.

The click behaviour itself was verified in a real browser rather than asserted here — success,
the 2-second revert, the failure label, and clipboard text matching the listing. A DOM-free
pytest cannot execute the handler, and a test that re-implements it in Python would only be
testing the re-implementation.
"""
import re
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render  # noqa: E402
from render import blocks  # noqa: E402

FENCE = "# T\n\nRun it:\n\n```bash\npytest -q\n```\n"
NO_FENCE = "# T\n\nJust prose, and `inline code` which is not a fence.\n"
RICH = ("design", "report", "roadmap", "analysis", "dashboard", "review", "spec", "workflow")


def _page(md=FENCE, style="design"):
    return render.render_artifact(md, title="T", style=style, generated_at="2026-01-01 00:00 MST")


def _scripts(html):
    return re.findall(r"<script>(.*?)</script>", html, re.S)


# --- plain keeps exactly what it had ------------------------------------------------

def test_plain_emits_the_bare_listing_and_no_box():
    out = render._render_body(FENCE, style="plain")
    assert "<pre><code>pytest -q</code></pre>" in out
    assert "doc-code" not in out


def test_plain_emits_no_script_and_no_button():
    page = _page(style="plain")
    assert _scripts(page) == []
    assert "<button" not in page


def test_plain_records_no_feature():
    ctx = {}
    render._render_body(FENCE, style="plain", ctx=ctx)
    assert blocks.used_features(ctx) == set()


# --- the rich form wraps, never rewrites --------------------------------------------

@pytest.mark.parametrize("style", RICH)
def test_every_rich_style_boxes_an_ordinary_fence(style):
    page = _page(style=style)
    assert '<div class="doc-code">' in page, style
    assert '<button class="doc-code-copy" type="button" hidden>Copy</button>' in page, style


def test_the_inner_listing_is_byte_identical_to_the_plain_one():
    """A dozen existing tests grep for this exact string. The box wraps it, nothing else."""
    listing = "<pre><code>pytest -q</code></pre>"
    assert listing in render._render_body(FENCE, style="plain")
    assert listing in render._render_body(FENCE, style="design")


def test_the_box_carries_the_fence_info_string_as_its_label():
    assert '<span class="doc-code-lang">bash</span>' in _page()


def test_a_fence_with_no_info_string_is_labelled_code():
    page = _page("```\n2136 passed\n```\n")
    assert '<span class="doc-code-lang">code</span>' in page


def test_a_degraded_typed_block_gets_the_box_too():
    """A malformed `timeline` falls back to a code listing, and that listing is still
    something a reader may want to copy."""
    page = _page("```timeline\ntoo | few | fields\n```\n")
    assert '<div class="doc-code">' in page
    assert '<span class="doc-code-lang">timeline</span>' in page


def test_the_wrapper_is_not_in_the_typed_block_namespace():
    """`blk-` is a class token the lint gate reads as "this page carries a typed block"
    (`_BLOCK_MARKUP`). An ordinary fence is not a typed block, so it must not claim to be."""
    page = _page()
    assert "doc-code" in page
    assert 'class="blk-code' not in page


# --- the script is opt-in, and CSP-honest -------------------------------------------

def test_a_rich_page_with_no_fence_emits_no_script():
    page = _page(NO_FENCE)
    assert _scripts(page) == []
    assert "doc-code" not in page


def test_a_rich_page_with_a_fence_emits_exactly_one_script():
    assert len(_scripts(_page())) == 1


def test_many_fences_still_emit_one_script():
    """The layer is per PAGE, not per block — three fences must not stack three copies."""
    page = _page(FENCE + "```py\nx = 1\n```\n" + "```\nplain\n```\n")
    assert len(_scripts(page)) == 1
    assert page.count('<div class="doc-code">') == 3


def test_no_optional_css_when_no_fence_is_present():
    ctx = {}
    render._render_body(NO_FENCE, style="design", ctx=ctx)
    assert blocks.used_features(ctx) == set()
    assert blocks.optional_css(blocks.used_features(ctx)) == ""


def test_the_feature_registers_both_a_css_and_a_js_layer():
    assert blocks.optional_css({"codecopy"}) != ""
    assert blocks.optional_js({"codecopy"}) != ""


# --- the script's own contract ------------------------------------------------------

FORBIDDEN = ("innerHTML", "outerHTML", "document.write", "eval(")


@pytest.mark.parametrize("api", FORBIDDEN)
def test_the_script_uses_no_forbidden_dom_api(api):
    """The same list the uat script is held to."""
    assert api not in _scripts(_page())[0]


def test_the_script_is_inline_and_never_fetched():
    assert not re.search(r"<script[^>]+src=", _page(), re.I)


def test_the_script_reveals_the_button_it_depends_on():
    """The button ships hidden, so a JS-less reader sees no dead control. If the script ever
    stops revealing it, the feature silently disappears rather than failing loudly."""
    script = _scripts(_page())[0]
    assert "hidden=false" in script.replace(" ", "")


def test_the_script_states_failure_rather_than_going_quiet():
    assert "Press Ctrl+C" in _scripts(_page())[0]


def test_the_script_reads_the_listing_by_text_not_markup():
    """`textContent` copies the DECODED source. Copying innerHTML would paste `&lt;` to a
    reader who asked for `<`, which was verified live in a browser."""
    assert "code.textContent" in _scripts(_page())[0]


# --- escape-first still holds -------------------------------------------------------

def test_a_hostile_info_string_cannot_open_an_element():
    page = _page("```<script>alert(1)</script>\nbody\n```\n")
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert len(_scripts(page)) == 1, "only the component's own script may be present"


def test_hostile_fence_content_stays_inert():
    page = _page('```html\n<script>alert(1)</script> & "q"\n```\n')
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_an_attribute_break_attempt_in_the_info_string_is_escaped():
    page = _page('```x" onmouseover="alert(1)\nbody\n```\n')
    assert 'onmouseover="alert(1)"' not in page
    assert "&quot;" in page


# --- the styling does what the request asked for -------------------------------------

def test_the_css_gives_the_box_a_border_and_the_button_a_pointer():
    css = blocks.optional_css({"codecopy"})
    assert ".doc-code{" in css and "border:1px solid var(--line)" in css
    assert "cursor:pointer" in css


def test_the_inner_pre_gives_up_its_own_border_to_the_box():
    """Otherwise the bar and the listing stack two outlines instead of sharing one."""
    assert ".doc-code>pre{" in blocks.optional_css({"codecopy"})


def test_the_button_is_hidden_when_printed():
    """Paper cannot take a copy."""
    css = blocks.optional_css({"codecopy"})
    assert "@media print" in css and ".doc-code-copy{display:none}" in css


def test_the_button_has_a_visible_focus_ring():
    assert ".doc-code-copy:focus-visible" in blocks.optional_css({"codecopy"})


def test_the_css_reaches_no_external_host():
    css = blocks.optional_css({"codecopy"})
    assert "http://" not in css and "https://" not in css and "url(" not in css
