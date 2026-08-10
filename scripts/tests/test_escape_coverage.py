"""Direct injection coverage for the five escape sites the moved suite never exercised (#15).

The moved suite (`test_render_artifact.py`) covers paragraphs, fenced code, table cells, the
roadmap heading, telemetry and the title. It does NOT directly exercise:

    :174  plain heading      (the roadmap test uses style="roadmap" and hits :303 instead)
    :184  list item
    :192  blockquote
    :570  subtitle
    :592/:600  the generated_at stamp

The engine already escapes all five; these tests exist so a future wave cannot silently remove
that escaping. Each one is written so it FAILS against an unescaped renderer — see
`test_probes_are_not_vacuous` at the bottom, which proves exactly that.

New file, deliberately: the moved suite must stay byte-faithful to its rawgentic original.
"""
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render as render_artifact  # noqa: E402

PAYLOAD = "<script>alert(1)</script>"
FIXED_TS = "2026-07-04 17:05 MST"


def _render(md="body", **kw):
    kw.setdefault("title", "T")
    kw.setdefault("generated_at", FIXED_TS)
    return render_artifact.render_artifact(md, **kw)


ESCAPED = html_mod_escape = __import__("html").escape(PAYLOAD)


def _assert_neutralized(rendered, occurrences=1):
    """The payload must appear FULLY escaped, and not survive as live markup.

    Checking only for `&lt;script&gt;` plus absence of the raw payload was too weak: output like
    `&lt;script&gt;alert(1)</script>` satisfied both while leaving a live closing tag. Requiring
    the complete `html.escape(PAYLOAD)` closes that.
    """
    assert PAYLOAD not in rendered, "raw payload survived"
    assert "</script>" not in rendered, "a live closing tag survived (partial escaping)"
    assert rendered.count(ESCAPED) >= occurrences, (
        f"expected the fully-escaped payload at least {occurrences}x, "
        f"found {rendered.count(ESCAPED)}")


def test_plain_heading_escapes_injection():
    # style defaults to plain -> exercises the :174 heading branch, NOT the roadmap :303 one.
    _assert_neutralized(_render(f"# {PAYLOAD}"))


def test_list_item_escapes_injection():
    _assert_neutralized(_render(f"- {PAYLOAD}"))


def test_blockquote_escapes_injection():
    _assert_neutralized(_render(f"> {PAYLOAD}"))


def test_subtitle_escapes_injection():
    _assert_neutralized(_render("body", subtitle=PAYLOAD))


def test_generated_at_stamp_escapes_injection():
    # The stamp is interpolated at BOTH the eyebrow (:592) and the footer (:600), so require
    # two escaped occurrences — one escaped and one leaked would otherwise pass.
    _assert_neutralized(_render("body", generated_at=PAYLOAD), occurrences=2)


def test_probes_are_not_vacuous():
    """A test that cannot fail is not coverage.

    Two ways the assertion could be hollow, both checked:
      1. fully unescaped output must be rejected;
      2. PARTIALLY escaped output must be rejected too — the case the original assertion let
         through, where the opening tag is escaped but a live `</script>` survives.
    """
    fully_unescaped = f"<h1>{PAYLOAD}</h1><li>{PAYLOAD}</li>"
    partially_escaped = "&lt;script&gt;alert(1)</script>"
    for sample, what in ((fully_unescaped, "unescaped"), (partially_escaped, "partially escaped")):
        try:
            _assert_neutralized(sample)
        except AssertionError:
            continue
        raise AssertionError(f"the injection assertion passed on {what} markup — it proves nothing")
