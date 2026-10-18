"""A long inline code span wraps instead of widening a phone-width page.

The base `code` rule had no wrap setting, so an unbreakable path in a paragraph ran past the
screen: a real design page was 447 px wide on a 390 px screen, from two file paths in list items.
Every style carries that rule, so every style had the bug.

`break-word`, not `anywhere`, measured in a real browser on that page: both bring it to 390 px,
but `anywhere` also changes the min-content width, so at 1440 px it broke 18 code spans inside
table cells that fit before, while `break-word` changed none. Code blocks are untouched either
way: `pre` keeps `white-space:pre` and its own `overflow-x:auto`, and the same blocks still
scrolled inside themselves. A DOM-free pytest cannot lay out a page, so it pins the rule.

The rule lives in `_COMPONENT_STYLE`, beside the phone table rule, and not in `_STYLE`, which
AC5 freezes: `plain` keeps its exact bytes, and its pins in `test_tokens.py` do not move.
"""
import re
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render  # noqa: E402
from render.templates import TEMPLATES  # noqa: E402


def _decl(style, selector, prop):
    page = render.render_artifact("# Probe\n\nBody with `code`.\n", title="Probe", style=style,
                                  generated_at="2026-01-01 00:00 MST")
    css = re.sub(r"/\*.*?\*/", "", page.split("<style>")[1].split("</style>")[0], flags=re.S)
    for rule in css.split("}"):
        if "{" not in rule:
            continue
        sel, body = rule.split("{", 1)
        if selector in [s.strip() for s in sel.split(",")]:
            m = re.search(re.escape(prop) + r"\s*:\s*([^;]+)", body)
            if m:
                return m.group(1).strip()
    return None


@pytest.mark.parametrize("style", sorted(TEMPLATES))
def test_inline_code_may_wrap_in_every_style(style):
    assert _decl(style, "code", "overflow-wrap") == "break-word", style


def test_plain_keeps_its_frozen_stylesheet():
    """AC5 freezes `_STYLE`, and `plain` carries it with no layer on top."""
    assert "overflow-wrap" not in render._STYLE
