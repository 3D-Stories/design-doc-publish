"""The permanent byte-identity regression gate (#15, AC2).

This is NOT the migration proof. The migration proof — issue #15's AC1 obligation 4 — renders the
same input through the OLD rawgentic engine and this package in one process and compares bytes;
it ran once, at implementation time, and its output is recorded in the PR. It cannot live here,
because rawgentic#807 deletes the old module and a permanent test must not depend on a sibling
repository's working tree.

What this file does instead is pin the exemplar forever: render the committed fixture with the
pinned stamp/title/style and require the committed HTML back, byte for byte. Any future wave that
changes rendered output has to change this fixture deliberately.
"""
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render  # noqa: E402

DOCS = SCRIPTS.parent / "docs"
FIXTURE = DOCS / "design-language-example.md"
EXPECTED_HTML = DOCS / "design-language-example.html"

# Pinned by the exemplar's own regeneration contract — must match _EXEMPLAR_TS in the moved suite.
EXEMPLAR_TS = "2026-07-10 12:00 MDT"
EXEMPLAR_TITLE = "Design-language exemplar"
EXEMPLAR_STYLE = "design"


def _render_exemplar(markdown):
    return render.render_artifact(
        markdown, title=EXEMPLAR_TITLE, generated_at=EXEMPLAR_TS, style=EXEMPLAR_STYLE)


def test_exemplar_round_trips_byte_for_byte():
    assert _render_exemplar(FIXTURE.read_text(encoding="utf-8")) == \
        EXPECTED_HTML.read_text(encoding="utf-8")


def test_gate_detects_drift():
    """A gate that cannot fail is not a gate.

    Feed the renderer a mutated fixture and require the comparison to break. Without this, the
    test above would still pass if the fixture and the expected HTML were regenerated together
    from a broken engine.
    """
    mutated = FIXTURE.read_text(encoding="utf-8") + "\n\nan extra paragraph that is not in the oracle\n"
    assert _render_exemplar(mutated) != EXPECTED_HTML.read_text(encoding="utf-8")
