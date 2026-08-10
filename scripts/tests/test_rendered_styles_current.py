"""The committed per-style pages are CURRENT, and every style has one (#114).

Thirteen pages were generated into `docs/rendered-styles/` during #42 and **never committed**. From
the repository's point of view the answer to "where are the per-style pages?" was still "none exist",
while the copy on one machine had gone stale enough that even `plain` — the frozen style — differed.
That dated the snapshot to before the whole lane-A/lane-B rebuild, and two styles added since were
missing outright. A stale page that presents itself as current is worse than a missing one; it is the
same defect family as #22 and #113.

The issue offered two options and the **owner chose A**: commit them and guard them. This is the
guard, and the pattern is `test_byte_identity.py`'s — applied, not invented: render the committed
fixture at a pinned stamp and require the committed bytes back.

Three additions that file does not need:

* **Completeness.** The set of committed pages must equal the style registry EXACTLY, so a newly
  added style cannot silently skip the guard and a deleted style cannot leave a page behind. That is
  the same rule `test_furniture_context.py` applies to its SHA pins, and #114's AC2 asks for it by
  name. Without it, this guard would have passed on the very snapshot that was missing `module-map`
  and `slide-deck`.
* **A can-it-fail test.** A byte-identity guard whose regeneration and whose assertion share one
  code path passes even on a broken renderer, so long as both were run together.
* **Sentinels the regenerator cannot rewrite** — minimum size, a doctype, the pinned title and
  stamp, and fixture content. Every comparison against a fresh render is satisfied by regenerating,
  so a renderer that began emitting a stub for one style would go green the moment someone did.
  These expectations do not come from `render_style()`, so regeneration cannot manufacture them.
  Added after review pointed out that the can-it-fail test alone left that lockstep failure open.

The recipe lives in `regen_rendered_styles.py` and is imported from there rather than restated here.
That direction is forced: `pytest` is not importable under a bare `python3` on this host, so the
regenerator cannot import this module. One source of truth either way; only that direction runs.

**What this guard does NOT prove, stated so nobody mistakes its scope.** The regenerator and the
assertions below call the same `render_style()`, so this pins "the committed pages match what the
renderer currently emits" — never "the renderer is correct". Rerun the regenerator after breaking the
renderer and these tests go green again. That is inherent to any golden-file guard and is fine here,
because renderer correctness is pinned INDEPENDENTLY and elsewhere: `test_furniture_context.py`'s
per-style SHA oracle, `test_byte_identity.py`'s committed exemplar, and `crossstyle.sh`'s
base-versus-head comparison. Those catch an unintended renderer change; this one catches a page that
stopped matching the renderer. Two different failures, and this file only ever claimed the second.

Render output is deterministic across processes and under a randomised `PYTHONHASHSEED` — measured,
because a golden-file guard over non-deterministic output would fail at random.
"""
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))

from regen_rendered_styles import (  # noqa: E402
    CANONICAL_README_CLAIM, FIXTURE, PAGES, STAMP, STYLES, TITLE, render_bytes,
)

import render  # noqa: E402


def test_every_style_in_the_registry_has_a_committed_page():
    """AC2's completeness half, and AC3 — `module-map` and `slide-deck` were the absent two."""
    committed = {p.stem for p in PAGES.glob("*.html")}
    assert committed == set(STYLES), (
        f"committed pages {sorted(committed)} != registry {sorted(STYLES)}")


@pytest.mark.parametrize("style", STYLES)
def test_each_committed_page_is_byte_identical_to_a_fresh_render(style):
    """BYTES, not text.

    This compared `read_text()` against a `str` until review caught it. Python normalises line
    endings on a text read, so a CRLF-committed page compared EQUAL to an LF render while the bytes
    differed — a "byte-identity" guard that was not one, and which would have blessed
    platform-dependent committed output. Reproduced before fixing.
    """
    page = PAGES / f"{style}.html"
    assert page.exists(), f"no committed page for {style}"
    assert page.read_bytes() == render_bytes(style), (
        f"{style}.html is stale — regenerate with "
        f"scripts/tests/regen_rendered_styles.py and commit the result")


@pytest.mark.parametrize("style", STYLES)
def test_each_committed_page_is_substantive_not_merely_consistent(style):
    """Expectations the regenerator CANNOT rewrite.

    Every other assertion here compares a page against a fresh render, so a renderer that started
    emitting a stub for one style would go green the moment someone regenerated. These sentinels do
    not come from `render_style()`, so regeneration cannot satisfy them: the page must be a real
    document, carry the pinned stamp, and contain content from the fixture.
    """
    page = (PAGES / f"{style}.html").read_bytes().decode("utf-8")
    assert len(page) > 3000, f"{style}.html is {len(page)} bytes — too small to be a real page"
    assert "<!doctype html>" in page.lower()
    assert TITLE in page
    assert STAMP in page, "the pinned stamp is missing, so this was not rendered by the recipe"
    assert "First section" in page, "fixture content is missing — the page is not the fixture"


def test_the_guard_can_actually_fail():
    """A gate that cannot fail is not a gate.

    Feed the renderer a mutated fixture and require the comparison to break. Without this, every
    assertion above would still pass if the pages and the renderer were broken in step.
    """
    mutated = FIXTURE.read_text(encoding="utf-8") + "\n\nnot in the committed pages\n"
    got = render.render_artifact(mutated, title=TITLE, generated_at=STAMP,
                                 style="roadmap", doc_id="crossstyle-probe")
    assert got != (PAGES / "roadmap.html").read_text(encoding="utf-8")


def test_the_readme_states_what_the_guard_actually_does():
    """AC5 — the README's description has to match what these files now are.

    An earlier version of this test only rejected two historical phrases and required the guard's
    filename to appear. Review pointed out that it was semantically vacuous: a README saying
    "`test_rendered_styles_current.py` does NOT guard these pages" satisfied all three assertions,
    so AC5 could regress while its own guard passed. A positive canonical claim cannot be negated
    and still match.
    """
    readme = (PAGES / "README.md").read_text(encoding="utf-8")
    # Whitespace-normalised, because the README is hard-wrapped and the claim spans lines. Comparing
    # raw substrings would make the guard fail on a reflow, which teaches people to delete it.
    flat = " ".join(readme.split())
    assert " ".join(CANONICAL_README_CLAIM.split()) in flat, (
        "the README must carry the canonical guard description; it is defined in "
        "regen_rendered_styles.py so there is exactly one wording to keep true")
    # The historical false claims, kept as explicit regressions rather than relying on the above.
    assert "no test guards them" not in readme
    assert "is a follow-up" not in readme


def test_the_documented_manual_recipe_matches_the_pinned_one():
    """The README says `crossstyle.sh` produces the same pages. Now checked, not asserted.

    Review's point: two independently encoded copies of a stamp drift, and the README would then be
    documenting a command that generates different output from the guarded one. That is exactly how
    the previous snapshot came to disagree with its own documented recipe.
    """
    sh = (TESTS / "crossstyle.sh").read_text(encoding="utf-8")
    for label, value in (("STAMP", STAMP), ("--title", TITLE), ("--doc-id", "crossstyle-probe")):
        assert value in sh, (
            f"{label} {value!r} is not in crossstyle.sh — the two recipes have drifted, so either "
            f"reconcile them or drop the README's equivalence claim")


def test_every_block_tag_is_exercised_by_at_least_one_committed_page():
    """#148 AC4. The fixture is the only thing that decides which components these pages
    contain, and it was missing FOUR of seventeen tags — `phases`, `flow`, `composition` and
    `faq`. Two of those are first-read devices, so `roadmap.html` and `workflow.html` would
    have failed #130's gate had anyone published them: a snapshot that claims to exercise the
    component vocabulary while missing the devices two styles OPEN with.

    Asserted against the registry rather than a hand-kept list, so adding a tag turns this red
    until the fixture covers it. That is the whole point — the previous gap was invisible
    precisely because nothing compared the two.
    """
    import re
    from render import blocks

    seen: set[str] = set()
    for style in STYLES:
        html = (PAGES / f"{style}.html").read_text(encoding="utf-8")
        markup = re.sub(r"<(style|script)\b[^>]*>.*?</\1>", "", html, flags=re.S | re.I)
        for m in re.finditer(r'class="([^"]*)"', markup):
            for token in m.group(1).split():
                if token.startswith("blk-") and token[4:] in blocks.BLOCK_TAGS:
                    seen.add(token[4:])

    missing = sorted(set(blocks.BLOCK_TAGS) - seen)
    assert not missing, (
        f"no committed page carries {missing} — add a fence for each to "
        f"{FIXTURE.name} and re-run regen_rendered_styles.py, or these tags ship unexercised")


def test_the_two_first_read_devices_that_were_missing_are_present():
    """The specific regression #148 was filed for, named rather than left implicit: the two
    pages whose own style requires a device the fixture never produced."""
    import re
    from render import blocks, lint

    for style in ("roadmap", "workflow"):
        html = (PAGES / f"{style}.html").read_text(encoding="utf-8")
        markup = re.sub(r"<(style|script)\b[^>]*>.*?</\1>", "", html, flags=re.S | re.I)
        present = lint._block_tags_present(markup, blocks.BLOCK_TAGS)
        missing = sorted(blocks.FIRST_READ_DEVICES[style] - present)
        assert not missing, f"{style}.html still lacks its own first-read device(s): {missing}"
