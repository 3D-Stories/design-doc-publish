"""`SOURCE_DATE_EPOCH` makes the renderer reproducible (#72, defect 3).

The renderer stamped every page from the wall clock, so rendering the same markdown twice
a minute apart produced different bytes. Measured 2026-09-21: the only difference between
two real renders was `08:50` versus `08:52`, and that was enough for `publish_doc.py`
stage 4 to refuse, because it compares git blob ids and a blob id cannot be normalized.

`SOURCE_DATE_EPOCH` is the reproducible-builds convention
(https://reproducible-builds.org/specs/source-date-epoch/): a build that would otherwise
read the clock uses this value instead, so the same input yields the same output. It is the
EXPLICIT half of the fix. The implicit half — reusing the stamp already in the output file —
lives in the publisher, and is pinned by `test_stamp_continuity.py`.

Precedence, and each rung is pinned below: an explicit `generated_at` wins, then
`SOURCE_DATE_EPOCH`, then the clock.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render  # noqa: E402

DOC = "# A page\n\nSome body text.\n\n## A section\n\nMore prose.\n"

# Two instants a minute apart, which is what the defect needed to show itself. Fixed rather
# than relative to now(), so the test reads the same in every season.
T0 = datetime(2026, 9, 21, 8, 50, 30, tzinfo=timezone.utc)
T1 = datetime(2026, 9, 21, 8, 52, 10, tzinfo=timezone.utc)

# 2026-09-21 08:50 MDT as a Unix epoch. MDT is UTC-6, so this is 14:50 UTC.
EPOCH = int(datetime(2026, 9, 21, 14, 50, 0, tzinfo=timezone.utc).timestamp())


class _FrozenDatetime(datetime):
    """`datetime` with `now()` pinned. Subclassed rather than mocked so every other
    `datetime` method the renderer might reach keeps working."""
    _pinned = T0

    @classmethod
    def now(cls, tz=None):
        return cls._pinned.astimezone(tz) if tz is not None else cls._pinned


@pytest.fixture
def frozen(monkeypatch):
    """Pin the renderer's clock, and return a setter for it."""
    monkeypatch.setattr(render, "datetime", _FrozenDatetime)

    def at(when):
        monkeypatch.setattr(_FrozenDatetime, "_pinned", when)
    at(T0)
    return at


def _render():
    return render.render_artifact(DOC, title="A page", style="design")


# --- the defect, and the fix ----------------------------------------------------------

def test_the_clock_alone_makes_two_renders_differ(frozen):
    """The defect itself, pinned so the fix cannot be claimed without it.

    This is the CONTROL. Without `SOURCE_DATE_EPOCH` the renderer still reads the clock,
    which is deliberate — a page with no reproducibility request still wants a real stamp.
    """
    frozen(T0)
    first = _render()
    frozen(T1)
    second = _render()
    assert first != second, "the control is broken: the clock no longer affects the render"


def test_source_date_epoch_makes_two_renders_byte_identical(frozen, monkeypatch):
    """AC2. The same markdown, rendered a minute apart, must produce identical bytes."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", str(EPOCH))
    frozen(T0)
    first = _render()
    frozen(T1)
    second = _render()
    assert first == second, "SOURCE_DATE_EPOCH must remove the clock from the render"
    assert "2026-09-21 08:50" in first, (
        "the epoch must be formatted in mountain time, the same as the clock path")


def test_an_explicit_generated_at_still_wins(frozen, monkeypatch):
    """Precedence rung 1. Every existing caller passes `generated_at`, and a stray exported
    variable must never silently override a stamp the caller named."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", str(EPOCH))
    page = render.render_artifact(DOC, title="A page", style="design",
                                  generated_at="2026-07-10 12:00 MDT")
    assert "2026-07-10 12:00 MDT" in page
    assert "08:50" not in page


def test_a_malformed_source_date_epoch_refuses_loudly(frozen, monkeypatch):
    """A silent fallback to the clock is the worst outcome available here.

    The caller asked for reproducibility. Ignoring a junk value would hand back a page that
    LOOKS reproducible and is not, and the next stage-4 refusal would name a timestamp
    nobody could explain. The reproducible-builds spec says a consumer SHOULD exit non-zero,
    and that is the right reading for a renderer whose output is compared byte for byte.
    """
    for bad in ("not-a-number", "", "  ", "12.5", "0x10"):
        monkeypatch.setenv("SOURCE_DATE_EPOCH", bad)
        with pytest.raises(ValueError) as e:
            _render()
        assert "SOURCE_DATE_EPOCH" in str(e.value), (
            "the refusal must name the variable, or nobody can act on it")


def test_an_out_of_range_source_date_epoch_refuses_rather_than_crashing(frozen, monkeypatch):
    """A number the platform cannot turn into a date is malformed too, not a traceback."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "99999999999999999999")
    with pytest.raises(ValueError) as e:
        _render()
    assert "SOURCE_DATE_EPOCH" in str(e.value)


def test_the_stamp_still_satisfies_the_lint_gate(frozen, monkeypatch):
    """AC5, the half a reproducibility change could break without anyone noticing.

    `render/lint.py:check_stamp` requires an America/Edmonton stamp in the page furniture.
    A stamp formatted any other way would pass this file's own assertions and fail the gate.
    """
    monkeypatch.setenv("SOURCE_DATE_EPOCH", str(EPOCH))
    assert render.lint.check_stamp(_render()) == []
