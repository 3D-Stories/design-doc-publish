#!/usr/bin/env python3
"""Regenerate `docs/rendered-styles/` — the committed one-page-per-style set (#114).

Run from anywhere:

    python3 user/design-doc-publish/scripts/tests/regen_rendered_styles.py

Then commit the result. `test_rendered_styles_current.py` fails until you do.

**This module owns the recipe** — fixture, title, stamp, doc id, style list — and the guard imports
it from here. The dependency runs this way round for a mechanical reason: `pytest` is not importable
under a bare `python3` on this host, so a regenerator that imported the test could not run at all.
One source either way; only this direction actually executes.

Two copies of a pinned stamp is how the previous snapshot drifted from the command its own README
documented: the README said to run `crossstyle.sh`, and nothing ever checked that anyone had.
"""
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render  # noqa: E402
from render import templates as render_templates  # noqa: E402

# The pinned recipe. Identical to `crossstyle.sh`'s values, deliberately: the README documents that
# command too, and a second set of numbers here would make one of the two a lie.
PAGES = SCRIPTS.parent / "docs" / "rendered-styles"
FIXTURE = SCRIPTS / "tests" / "fixtures" / "crossstyle.md"
TITLE = "Cross-style probe"
STAMP = "2026-08-02 00:00 MDT"
DOC_ID = "crossstyle-probe"

STYLES = ["plain"] + sorted(render_templates.TEMPLATES)

# The one sentence the README must carry verbatim. Asserted by the guard, so the README cannot
# describe these files as unguarded — or, more subtly, cannot NEGATE the description and still pass.
# An earlier version of that guard only rejected two historical phrases and required the guard's
# filename to appear, which a README saying "…does not guard these pages" would have satisfied.
CANONICAL_README_CLAIM = (
    "fails when any committed page differs from a fresh render of the fixture at the pinned "
    "stamp, and when the set of pages does not equal the style registry exactly"
)


def render_style(style: str) -> str:
    return render.render_artifact(
        FIXTURE.read_text(encoding="utf-8"),
        title=TITLE, generated_at=STAMP, style=style, doc_id=DOC_ID)


def render_bytes(style: str) -> bytes:
    """The page as BYTES, which is what gets committed and what the guard must compare.

    `write_text`/`read_text` would let a CRLF-committed page compare equal to an LF render, because
    Python normalises line endings on text reads — so a "byte-identical" guard built on text I/O is
    not one. Reproduced before fixing: bytes differing while `read_text()` reported equal.
    """
    return render_style(style).encode("utf-8")


def main() -> int:
    PAGES.mkdir(parents=True, exist_ok=True)
    stale = {p.stem for p in PAGES.glob("*.html")} - set(STYLES)
    for style in STYLES:
        out = PAGES / f"{style}.html"
        before = out.read_bytes() if out.exists() else None
        data = render_bytes(style)
        # BYTES, deliberately: `write_text` would emit platform line endings and make the committed
        # pages machine-dependent.
        out.write_bytes(data)
        verb = "unchanged" if before == data else ("created" if before is None else "updated")
        print(f"  {style:14} {verb:9} {len(data):>7} bytes")
    for name in sorted(stale):
        # A style that no longer exists must not leave a page behind — the completeness half of the
        # guard fails on it, so removing it here is part of regenerating, not a courtesy.
        (PAGES / f"{name}.html").unlink()
        print(f"  {name:14} REMOVED   (no longer in the style registry)")
    print(f"\n{len(STYLES)} styles written to {PAGES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
