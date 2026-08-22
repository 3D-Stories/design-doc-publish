"""Links must be readable on the dark ground (owner report, 2026-08-22).

The base stylesheet never declared an `a{color}` rule, so every anchor fell back to the
browser default — dark blue on `--bg:#12181c`, which is what the owner reported as
unreadable on the live unified-roadmap page. The lint PAIRS table already classifies the
pair: ("--accent", "--bg", 4.5, "the eyebrow and links are text") — the rule below is the
declaration that table was written for.

The rule lives in `_COMPONENT_STYLE` (every non-plain template), NOT in `_STYLE_TPL`:
`plain` output is frozen byte-for-byte by `test_byte_identity`'s AC5 contract, so plain
deliberately keeps the gap and this file pins that too.
"""
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render as render_artifact  # noqa: E402

TEMPLATES = ("analysis", "roadmap", "report", "design",
             "dashboard", "review", "spec", "workflow", "uat")

_MD = "# Doc\n\n## Section\n\nA [link](https://example.com) in body prose.\n"

_RULE = "a{color:var(--accent)}"


def _render(style):
    return render_artifact.render_artifact(_MD, title="T", style=style,
                                           generated_at="2026-08-01 12:00 MDT")


@pytest.mark.parametrize("style", TEMPLATES)
def test_every_nonplain_style_colors_links_with_the_accent(style):
    html = _render(style)
    assert _RULE in html, (
        f"{style}: no anchor color rule — links render browser-default dark blue "
        f"on the dark ground"
    )


def test_plain_stays_frozen_without_the_rule():
    # Not an endorsement of the gap — the freeze contract wins for plain.
    assert _RULE not in _render("plain")
