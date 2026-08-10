"""The section-status chip opt-out (`render_artifact(..., section_chips=False)`).

WHY THIS EXISTS. The roadmap/dashboard section chip is resolved by scanning the
section's own prose for completion vocabulary (see `roadmap_status_chip`). #119
hardened its negation handling, and the grammar-change alternative (explicit
heading metadata) was considered and deliberately NOT taken. Both left one shape
unfixable from the document side: a NARRATIVE page whose prose legitimately
discusses done/shipped/merged work as concepts. Measured on a real page
(rawgentic's graph-execution roadmap, 2026-08-10): "who may declare done" in a
thesis section rendered `The thesis [DONE]`, and a KPI section mentioning
"merged runs" rendered `[MERGED]` — statuses nobody wrote. Inline code does not
escape the scanner, and rewording is not available when the vocabulary words are
the section's subject matter.

So the escape is a PAGE-level opt-out, not a grammar change: `section_chips=False`
suppresses the chip on every section of a sectioned template. The default is
unchanged — this must stay byte-identical for every existing caller.
"""
import re
import sys
from pathlib import Path
import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import render as render_artifact  # noqa: E402

# Prose that legitimately discusses completion vocabulary without claiming it.
MD = (
    "## The thesis\n\nThe authority problem is who may declare done.\n\n"
    "## KPIs\n\nFollow-up incidence among merged runs is one baseline.\n"
)


@pytest.mark.parametrize("style", ["roadmap", "dashboard"])
def test_default_scans_and_chips(style):
    """The unchanged default: prose scanning stamps the chips (the #119 behavior)."""
    html = render_artifact.render_artifact(MD, title="T", style=style)
    assert ">DONE<" in html
    assert ">MERGED<" in html


@pytest.mark.parametrize("style", ["roadmap", "dashboard"])
def test_opt_out_removes_every_section_chip(style):
    """With section_chips=False no chip span renders at all — not even the neutral dash."""
    html = render_artifact.render_artifact(MD, title="T", style=style, section_chips=False)
    assert ">DONE<" not in html
    assert ">MERGED<" not in html
    # The heading itself survives, chip-less: no chip span inside any section heading.
    heads = re.findall(r"<h3[^>]*>(.*?)</h3>", html, re.S)
    assert any("The thesis" in h for h in heads)
    assert not any('class="chip' in h for h in heads)


def test_opt_out_leaves_sectioning_intact():
    """Opting out of chips must not opt out of section cards."""
    html = render_artifact.render_artifact(MD, title="T", style="roadmap", section_chips=False)
    assert 'class="mstone rm-epic"' in html


def test_default_is_byte_identical_to_omitting_the_kwarg():
    """`section_chips=True` is the default spelled out — same bytes, no drift."""
    a = render_artifact.render_artifact(MD, title="T", style="roadmap",
                                        generated_at="2026-08-10 00:00 MDT")
    b = render_artifact.render_artifact(MD, title="T", style="roadmap",
                                        generated_at="2026-08-10 00:00 MDT",
                                        section_chips=True)
    assert a == b


def test_analysis_confidence_chip_also_honors_the_opt_out():
    """`analysis` shares the section machinery; its confidence chip obeys the same switch."""
    md = "## Answer\n\nThis was measured directly.\n"
    on = render_artifact.render_artifact(md, title="T", style="analysis")
    off = render_artifact.render_artifact(md, title="T", style="analysis", section_chips=False)
    assert ">MEASURED<" in on
    assert ">MEASURED<" not in off
