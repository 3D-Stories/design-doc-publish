"""Every phase state a document may write is a state some template actually draws (#166).

**The defect this pins, in the owner's words: "DONE should be green not grey" and "the pills
don't make any sense."** Both were one root cause. `_phase_item` derived the CSS class from the
author's own word through `_token`, which validates a slug's SHAPE and nothing else — so `done`
became `.is-done`, no template carried a `.is-done` rule, and the chip fell through to the
neutral grey while still reading DONE. Nothing warned. The page looked finished and was wrong.

Three live pages proved it was not a one-off:

* `rawgentic-next-plan-95` — 12 grey DONE chips, the reported symptom.
* `rawgentic-plan-backlog-audit` — `ok`/`warn`/`crit`, severity words on a status rail.
* `rawgentic-plan-756` — the same severity words, 32 of them.

One document said DONE and two said OK for the same thing, because nothing documented what a
status rail accepts and nothing objected when an author guessed.

**So membership alone would not have caught this, and neither would a colour alone.** A declared
token set (`blocks._PHASE_STATES`) stops `banana`; it cannot know whether a template drew
`done`. A CSS rule draws `done`; it cannot stop `dnoe`. The gap between the two is exactly where
this defect lived, so this file asserts the JOIN: every declared token has a rule, every rule
serves a declared token, and a page rendered with the whole vocabulary contains no class that
falls through to the default by accident.

The neutral half is asserted as an ABSENCE, deliberately. `note` and `planned` are grey ON
PURPOSE — "not started" is a real state — and grey only reads as a choice while it is the sole
grey chip. Requiring that no template colours them is what keeps "deliberately grey" and
"nobody styled it" from looking identical again.
"""
import re
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render  # noqa: E402
from render import blocks  # noqa: E402

# `phases` is a roadmap block: `DOC_TYPE_TAGS` accepts it there and nowhere else, so roadmap is
# the one template that has to carry the vocabulary. A second style that opts in later will fail
# `test_every_style_that_accepts_phases_carries_the_vocabulary` below rather than ship grey.
PHASE_STYLES = sorted(s for s, tags in blocks.DOC_TYPE_TAGS.items() if "phases" in tags)

# The four elements that take the state token. Each is a place the reader sees the state, so a
# token missing from any one of them is a state the page renders as something it is not.
STATE_ELEMENTS = ("blk-ph-chip", "blk-ph-badge", "blk-comp-seg", "blk-ph")

# One row per group, written so the fixture below exercises the whole set. `_PHASE_STATES` is the
# oracle for completeness — `test_the_fixture_exercises_every_declared_token` fails if a token is
# added to the code and not to this document, which is how this file stays honest as the
# vocabulary grows.
DOC = """# Phase state vocabulary

```phases
Finished work | all four | done
  A-1 | a done item | done
  A-2 | a shipped item | shipped
  A-3 | a merged item | merged
  A-4 | a legacy ok item | ok
Moving work | four more | active
  B-1 | an active item | active
  B-2 | a wip item | wip
  B-3 | a pending item | pending
  B-4 | a legacy warn item | warn
Stuck work | three | blocked
  C-1 | a blocked item | blocked
  C-2 | a failed item | failed
  C-3 | a legacy crit item | crit
Not started | two | planned
  D-1 | a note item | note
  D-2 | a planned item | planned
```
"""


def _page(md=DOC, style="roadmap"):
    return render.render_artifact(md, title="T", style=style, generated_at="x")


def _css(page: str) -> str:
    """Every `<style>` body in the page, whitespace collapsed to single spaces.

    Collapsed rather than STRIPPED: removing whitespace entirely would turn `.a .b` into `.a.b`
    and make a descendant rule indistinguishable from a compound one, which is the difference
    between "an item that is blocked" and "an element that is both". The emitted CSS breaks long
    selector lists across lines, so collapsing is what makes them findable at all.
    """
    return re.sub(r"\s+", " ", "\n".join(
        re.findall(r"<style[^>]*>(.*?)</style>", page, re.S)))


def _has_rule(css: str, selector: str) -> bool:
    """True when `selector` heads a rule — followed by `,` (more selectors) or `{` (its body).

    The trailing character matters. A bare substring test would let `.is-done` match inside
    `.is-done-later`, and a guard that reports a rule nobody wrote is worse than no guard.
    """
    return re.search(re.escape(selector) + r"\s*[,{]", css) is not None


PAGE = _page()
CSS = _css(PAGE)


# --- the vocabulary is complete on both sides ----------------------------------------

@pytest.mark.parametrize("token", sorted(blocks._PHASE_STATE_COLOURED))
@pytest.mark.parametrize("element", STATE_ELEMENTS)
def test_every_coloured_token_has_a_rule_on_every_element_that_carries_it(element, token):
    """The half that was missing. `done` failed exactly this, on all four elements."""
    assert _has_rule(CSS, f".{element}.is-{token}"), (
        f"`{token}` is declared a coloured phase state but `.{element}.is-{token}` has no rule, "
        f"so it renders as the neutral default — the #166 defect, on {element}")


@pytest.mark.parametrize("token", sorted(blocks._PHASE_STATE_NEUTRAL))
@pytest.mark.parametrize("element", STATE_ELEMENTS)
def test_every_neutral_token_is_left_alone_on_purpose(element, token):
    """Asserted as an absence, so "deliberately grey" cannot decay back into "unstyled"."""
    assert not _has_rule(CSS, f".{element}.is-{token}"), (
        f"`{token}` is declared NEUTRAL — grey is its meaning, not a fallthrough. A rule for "
        f"`.{element}.is-{token}` means somebody coloured it; move it to a coloured group "
        f"in blocks.py instead of styling it here")


@pytest.mark.parametrize("token", sorted(blocks._PHASE_STATE_STUCK))
def test_a_stuck_item_gets_the_trouble_accent_on_its_id(token):
    assert _has_rule(CSS, f".blk-ph-item.is-{token} .blk-ph-id"), (
        f"`{token}` means the work is stuck, so its item id takes the trouble accent that "
        f"`crit` has always taken")


@pytest.mark.parametrize(
    "token", sorted(blocks._PHASE_STATE_COLOURED - blocks._PHASE_STATE_STUCK))
def test_only_a_stuck_item_gets_the_trouble_accent(token):
    """If every state coloured the id, none of them would stand out — which is not an accent."""
    assert not _has_rule(CSS, f".blk-ph-item.is-{token} .blk-ph-id"), (
        f"`{token}` is not a stuck state, so it must not take the trouble accent")


def test_no_rule_serves_a_token_the_code_does_not_declare():
    """The other direction: CSS naming a state `blocks.py` never blesses is dead or a typo."""
    styled = {m.group(1) for m in re.finditer(
        r"\.blk-(?:ph|ph-chip|ph-badge|comp-seg|ph-item)\.is-([a-z0-9-]+)", CSS)}
    # `composition` shares `.blk-comp-seg` and validates against its own field, so its states are
    # legitimately here too; the assertion is about the phase elements it does not share.
    phase_only = {m.group(1) for m in re.finditer(
        r"\.blk-(?:ph|ph-chip|ph-badge|ph-item)\.is-([a-z0-9-]+)", CSS)}
    assert phase_only <= blocks._PHASE_STATES, (
        f"the roadmap template styles phase states the code does not declare: "
        f"{sorted(phase_only - blocks._PHASE_STATES)} — add them to a group in blocks.py or "
        f"delete the rule, because a class no renderer emits is dead CSS")
    assert styled, "the selector probe found nothing, so it is not testing what it claims"


# --- the end-to-end check the owner asked for -----------------------------------------

def test_every_class_the_page_emits_is_matched_by_a_rule_in_the_same_page():
    """"Render a fixture using every documented token; grep the output for each `is-<token>` and
    confirm a matching CSS rule exists in the same file." That check IS the defect.

    Neutral tokens are the one exception and are checked the other way round: they must resolve
    to the element's BASE rule, which the page must therefore also carry.
    """
    emitted = {(m.group(1), m.group(2)) for m in re.finditer(
        r'class="blk-(ph|ph-chip|ph-badge|comp-seg|ph-item)[^"]* is-([a-z0-9-]+)"', PAGE)}
    assert emitted, "the fixture rendered no phase state at all"
    unmatched = []
    for element, token in sorted(emitted):
        if token in blocks._PHASE_STATE_NEUTRAL:
            assert _has_rule(CSS, f".blk-{element}"), (
                f"`{token}` relies on the base `.blk-{element}` rule, which is missing")
            continue
        if element == "ph-item":
            continue          # the item wrapper carries the token for its id accent only
        if not _has_rule(CSS, f".blk-{element}.is-{token}"):
            unmatched.append(f".blk-{element}.is-{token}")
    assert not unmatched, (
        f"the page emits classes nothing styles: {unmatched} — each renders as the neutral "
        f"default while saying something else, which is the #166 defect verbatim")


def test_the_fixture_exercises_every_declared_token():
    """A guard that stops covering the vocabulary is not a guard."""
    seen = {m.group(1) for m in re.finditer(r'class="blk-ph-chip is-([a-z0-9-]+)"', PAGE)}
    assert seen == blocks._PHASE_STATES, (
        f"the fixture in this file no longer exercises every declared token; missing "
        f"{sorted(blocks._PHASE_STATES - seen)}, unexpected {sorted(seen - blocks._PHASE_STATES)}")


def test_the_reported_symptom_is_gone():
    """The owner's complaint, asserted directly: DONE is not drawn as the neutral chip."""
    assert 'class="blk-ph-chip is-done"' in PAGE
    neutral = re.search(r"\.blk-ph-chip\{([^}]*)\}", CSS)
    assert neutral, "the base chip rule vanished; this test can no longer tell grey from green"
    done = re.search(r"\.blk-ph-chip\.is-done[^{]*\{([^}]*)\}", CSS)
    assert done, "`.is-done` has no rule — the reported defect is back"
    assert "var(--chip-c)" in done.group(1), "DONE must carry the finished-state green"
    assert done.group(1) != neutral.group(1), "DONE still renders as the neutral grey chip"


def test_every_style_that_accepts_phases_carries_the_vocabulary():
    """One style accepts `phases` today. A second that opts in must bring the rules with it."""
    for style in PHASE_STYLES:
        css = _css(_page(style=style))
        missing = [t for t in sorted(blocks._PHASE_STATE_COLOURED)
                   if not _has_rule(css, f".blk-ph-chip.is-{t}")]
        assert not missing, (
            f"style {style!r} accepts `phases` but does not colour {missing} — it would ship "
            f"the same grey chip this issue fixed")


# --- an unknown token is now LOUD, which is the deeper half of the fix ------------------

def test_an_unknown_state_warns_instead_of_rendering_a_silent_grey_chip(capsys):
    """`banana` used to sail through `_token` and render grey with nothing said."""
    out = _page("# T\n\n```phases\nP | b | banana\n  X-1 | an item | banana\n```\n")
    err = capsys.readouterr().err
    assert "banana" in err, "an unstyled state must say so; silence is how #166 shipped"
    assert "phase item state" in err or "phase state" in err
    assert 'is-banana' not in out, "an unvalidated word must never reach a class attribute"
    assert 'class="blk-ph-chip is-note"' in out, "the fallback is the declared neutral"
    assert ">banana<" in out, "the author's own word is still shown; nothing is discarded"


def test_a_near_miss_typo_is_caught_rather_than_rendered(capsys):
    """The case that motivated membership: a typo of a REAL token, which shape-checking passes."""
    _page("# T\n\n```phases\nP | b | ok\n  X-1 | an item | doen\n```\n")
    err = capsys.readouterr().err
    assert "doen" in err and "is not one of" in err


def test_every_declared_token_renders_without_a_warning(capsys):
    """The whole vocabulary must be quiet, or authors learn to ignore the warnings.

    Re-aimed by #172, twice, and both moves are worth recording because the first was wrong.

    The old spelling was `"phase" not in err`. That caught #172's advisory nudge, which contains
    the word `phases` and is deliberately NOT a warning — the document it fires on is valid, and
    printing WARNING at a valid document is how a warning stream becomes noise.

    Broadening it to "no line contains WARNING" then failed on something real but unrelated: the
    fixture's h1 is `Phase state vocabulary` while `_page()` passes `title="T"`, so the renderer
    correctly warns about two h1 elements. The old spelling had never seen that warning only
    because it matched lowercase `phase` and the heading is capitalised. An accident, not a rule.

    So the assertion names the two FIELDS this test is actually about. It still guarantees
    exactly what it always claimed — no blessed token warns — without adopting every unrelated
    warning the fixture happens to produce.
    """
    _page()
    err = capsys.readouterr().err
    warnings = [ln for ln in err.splitlines()
                if "WARNING" in ln and ("phase state" in ln or "phase item state" in ln)]
    assert not warnings, f"a blessed token warned: {warnings!r}"


# --- the vocabulary is ONE vocabulary ---------------------------------------------------

def test_the_source_linter_recognises_every_state_this_engine_blesses():
    """`source_lint` decides whether a phase row reads done or open. A token it cannot see is a
    hole in `_phase_child_drift`: a phase marked `merged` used to read as NOT done, so a done
    phase with a stale open child passed. One vocabulary, or the checks disagree in silence."""
    from render import source_lint
    for token in sorted(blocks._PHASE_STATE_FINISHED):
        assert source_lint._DONE.search(token), f"`{token}` means finished; the linter cannot see it"
    for token in sorted(blocks._PHASE_STATE_MOVING | blocks._PHASE_STATE_STUCK
                        | blocks._PHASE_STATE_NEUTRAL):
        assert source_lint._OPEN.search(token), f"`{token}` means not finished; the linter cannot see it"


def test_no_token_reads_as_both_finished_and_open():
    from render import source_lint
    for token in sorted(blocks._PHASE_STATES):
        both = bool(source_lint._DONE.search(token)) and bool(source_lint._OPEN.search(token))
        assert not both, f"`{token}` reads as finished AND open, so drift detection is undefined"


# --- the negative control ---------------------------------------------------------------

def test_the_guard_can_actually_fail():
    """A guard nobody has watched fail is a guard nobody has tested.

    Both halves: a coloured token whose rule is deleted must be caught, and a neutral token that
    someone colours must be caught. The second is the one that decays quietly.
    """
    without_done = CSS.replace(".blk-ph-chip.is-done,", ".blk-ph-chip.is-nothing,")
    assert not _has_rule(without_done, ".blk-ph-chip.is-done")
    coloured_note = CSS + " .blk-ph-chip.is-note{color:var(--sev-crit)}"
    assert _has_rule(coloured_note, ".blk-ph-chip.is-note")


# --- #167: the compound chip borrows a colour rather than minting one --------------------
#
# `<label>:<level>` puts the TYPE in the chip's word and the PRIORITY in its colour. The reason
# it is safe under the guard above is that a level resolves to a colour token this file ALREADY
# pins a rule for. Mint an `is-must` class instead and every template that draws phases owes a
# new rule, and the first one to forget ships the grey chip #166 fixed.

@pytest.mark.parametrize("level,borrowed", sorted(blocks._PHASE_LEVELS.items()))
def test_every_level_borrows_a_colour_this_file_already_pins(level, borrowed):
    assert borrowed in blocks._PHASE_STATES, (
        f"level {level!r} borrows {borrowed!r}, which is not a declared phase state — the "
        f"guard above cannot pin a rule for it, so it would render as the neutral default")


def test_a_compound_chip_emits_no_class_outside_the_declared_vocabulary():
    """The end-to-end version: render every label at every level, then check every class."""
    rows = "\n".join(f"  X-{i} | an item | {label}:{level}"
                     for i, (label, level) in enumerate(
                         (l, v) for l in sorted(blocks._PHASE_LABELS)
                         for v in sorted(blocks._PHASE_LEVELS)))
    page = _page(f"# T\n\n```phases\nP | b | ok\n{rows}\n```\n")
    emitted = {m.group(1) for m in re.finditer(
        r'<span class="blk-ph-chip is-([a-z0-9-]+)"[^>]*>', page)}
    assert emitted <= blocks._PHASE_STATES, (
        f"compound chips emitted undeclared classes: {sorted(emitted - blocks._PHASE_STATES)}")
    assert emitted == set(blocks._PHASE_LEVELS.values()), (
        "every level must be reachable, or one of them is dead grammar")


def test_no_label_collides_with_a_state_in_a_way_that_changes_a_bare_token():
    """`note` is both a label and a state. Bare `note` must still mean the state."""
    assert "note" in blocks._PHASE_LABELS and "note" in blocks._PHASE_STATES
    page = _page("# T\n\n```phases\nP | b | ok\n  X-1 | an item | note\n```\n")
    # `[^>]*` absorbs the `title=` attribute #173 added between the class and the word. The
    # guarantee is the class and the word, and both are still asserted exactly.
    assert re.search(r'<span class="blk-ph-chip is-note"[^>]*>note</span>', page)


# --- #167: one vocabulary, still — the source linter must read a compound the same way ----

def test_a_label_done_child_reads_as_done_not_open():
    """`<label>:done` already matched `_DONE` through `\\bdone\\b`; this pins it deliberately."""
    from render import source_lint
    for label in sorted(blocks._PHASE_LABELS):
        done, still_open = source_lint._status(f"  X-1 | an item | {label}:done")
        assert done, f"{label}:done must read as finished"
        assert not still_open, f"{label}:done must not also read as open"


@pytest.mark.parametrize("level", sorted(set(blocks._PHASE_LEVELS) - {"done"}))
def test_every_other_level_reads_as_open(level):
    """The gap #167 closed: `bug:must` matched NOTHING, so a stale child was invisible."""
    from render import source_lint
    done, still_open = source_lint._status(f"  X-1 | an item | bug:{level}")
    assert still_open, f"bug:{level} must read as open"
    assert not done, f"bug:{level} must not read as finished"


def test_a_stale_compound_child_under_a_done_phase_is_reported():
    from render import source_lint
    md = ("# T\n\n```phases\nShipped work | 3 of 3 | done\n"
          "  #347 | still being fixed | bug:must\n```\n")
    findings = source_lint._phase_child_drift(md)
    assert findings, ("a `bug:must` child under a phase that reads done is the contradiction "
                      "`_phase_child_drift` exists to catch — before #167 it matched nothing")
    assert "#347" in findings[0] or "still being fixed" in findings[0]


def test_a_done_compound_child_under_a_done_phase_is_NOT_reported():
    from render import source_lint
    md = ("# T\n\n```phases\nShipped work | 3 of 3 | done\n"
          "  #347 | landed last week | bug:done\n```\n")
    assert source_lint._phase_child_drift(md) == [], (
        "`bug:done` must behave exactly like the bare `done` it borrows from")


def test_a_compound_child_under_an_OPEN_phase_is_never_reported():
    """The check only fires beneath a phase that claims to be finished."""
    from render import source_lint
    for child in ("bug:must", "bug:done", "chore:could"):
        md = f"# T\n\n```phases\nOpen work | 1 of 3 | wip\n  #347 | an item | {child}\n```\n"
        assert source_lint._phase_child_drift(md) == []


def test_the_linter_and_the_renderer_name_the_same_levels():
    """A drift guard over the one duplicated list: `_COMPOUND_OPEN` hardcodes the level words
    because importing `blocks` into `source_lint` would couple the parser to the renderer."""
    from render import source_lint
    for level in sorted(set(blocks._PHASE_LEVELS) - {"done"}):
        assert source_lint._COMPOUND_OPEN.search(f":{level}"), (
            f"level {level!r} exists in the renderer but the linter cannot see it as open")
    assert source_lint._DONE.search(":done"), "the done level must read as finished"
