"""A grammar nobody is told about is a grammar nobody uses (#170).

**This is `test_style_reachability.py`'s rule applied one layer in.** That file says a template
nobody can select does not exist, and it asks of each style whether a reader could arrive at it.
The same question had never been asked of the state tokens a component's chip accepts.

The answer was no, and it cost a live page. #166 made an unstyled chip loud and #167 added the
compound `<label>:<level>` grammar — both documented in `design-language.md`, and neither
mentioned in `SKILL.md`. `SKILL.md` is the only file that loads when a session publishes.
`design-language.md` is a reference a session opens on demand, which in practice means rarely.

Measured, and this is why the file exists rather than a paragraph: `rawgentic-plan-graph` was
published 61 minutes AFTER the compound grammar merged, by a session running the new renderer,
and every chip on it is a bare severity word. The engine was current. The author was not told.

So the guard asks the same question the reachability guard asks, about vocabulary instead of
templates:

* Does the file a reader actually opens name every token the renderer accepts?
* Does it name the compound grammar, its levels, and its labels?
* Does the renderer accept anything the documentation does not mention?

The last one is the direction that rots. A future token added to `blocks.py` with a colour rule
and no line in `SKILL.md` is exactly this defect returning, and it would pass every other test
in this suite.
"""
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import pytest  # noqa: E402

from render import blocks  # noqa: E402

SKILL_MD = SCRIPTS.parent / "skills" / "design-doc-publish" / "SKILL.md"
DESIGN_LANGUAGE = SCRIPTS.parent / "docs" / "design-language.md"


def _text(path):
    return path.read_text(encoding="utf-8")


def _names(haystack: str, needle: str) -> bool:
    """Word-boundary match, for the reason `test_style_reachability` gives.

    Not a backtick-span parser: a ``` fence makes the backticks in a document stop coming in
    pairs, so span parsing misreads the file. The question that matters is plain — does the doc
    a reader opens contain this word — so ask exactly that.
    """
    return re.search(rf"(?<![\w-]){re.escape(needle)}(?![\w-])", haystack) is not None


# --- the file a session actually loads must carry the vocabulary ------------------------

@pytest.mark.parametrize("token", sorted(blocks._PHASE_STATES))
def test_skill_md_names_every_state_token(token):
    assert _names(_text(SKILL_MD), token), (
        f"the renderer accepts the state {token!r} but SKILL.md never mentions it. SKILL.md is "
        f"the only file that loads when a session publishes, so a token missing here is a token "
        f"authors do not know exists — the #170 defect")


@pytest.mark.parametrize("level", sorted(blocks._PHASE_LEVELS))
def test_skill_md_names_every_compound_level(level):
    assert _names(_text(SKILL_MD), level), (
        f"the compound level {level!r} is accepted but undocumented where authors read")


@pytest.mark.parametrize("label", sorted(blocks._PHASE_LABELS))
def test_skill_md_names_every_compound_label(label):
    assert _names(_text(SKILL_MD), label), (
        f"the compound label {label!r} is accepted but undocumented where authors read")


def test_skill_md_shows_the_compound_grammar_itself_not_only_its_parts():
    """Listing `bug` and `must` separately does not teach anyone to write `bug:must`."""
    text = _text(SKILL_MD)
    assert "<label>:<level>" in text or "label:level" in text, (
        "SKILL.md must show the compound SHAPE, not just the words it is built from")
    assert re.search(r"`[a-z]+:[a-z]+`", text), (
        "SKILL.md must carry at least one worked example, such as `bug:must`")


def test_skill_md_says_the_set_is_closed():
    """An author who thinks the field is free text writes `urgent` and gets a grey chip."""
    text = _text(SKILL_MD).lower()
    assert "closed" in text or "not free text" in text, (
        "SKILL.md must say the state cell is a closed set — that is the fact that stops an "
        "author inventing a word")


def test_skill_md_points_at_the_full_rules():
    assert "design-language.md" in _text(SKILL_MD), (
        "the summary must name the file that carries the full table, or a reader who needs "
        "more has nowhere to go")


# --- the direction that rots: the renderer growing past its own documentation ------------

def test_the_documentation_does_not_invent_tokens_the_renderer_rejects():
    """The other direction. A documented word the renderer refuses is worse than an undocumented
    one: the author follows the instructions and still gets a warning and a grey chip."""
    text = _text(SKILL_MD)
    # Every word in the state table's own rows, taken from the backticked spans on those lines.
    documented = set()
    for line in text.splitlines():
        if "|" not in line or "`" not in line:
            continue
        # Word-boundary, because a bare `"red" in line` also matches "answe-red" and dragged the
        # whole `--type` table in. Found by this test failing on `analysis`, which is a doc type
        # and not a chip state — the probe was wrong, not the assertion.
        if not re.search(r"\b(green|amber|red|grey)\b", line):
            continue
        documented.update(re.findall(r"`([a-z]+)`", line))
    unknown = sorted(documented - blocks._PHASE_STATES - set(blocks._PHASE_LABELS)
                     - set(blocks._PHASE_LEVELS))
    assert not unknown, (
        f"SKILL.md documents state words the renderer does not accept: {unknown} — an author "
        f"following the doc would get a warning and a grey chip")


def test_design_language_and_skill_md_agree_on_the_label_set():
    """Two files carry this list. They drift apart the moment one is edited alone."""
    dl = _text(DESIGN_LANGUAGE)
    for label in sorted(blocks._PHASE_LABELS):
        assert _names(dl, label), f"design-language.md is missing the label {label!r}"


# --- the negative control ---------------------------------------------------------------

def test_the_guard_can_actually_fail():
    """A guard nobody has watched fail is a guard nobody has tested.

    Both halves, because they rot in opposite directions: a token the renderer gains and the doc
    does not, and a token the doc gains and the renderer does not.
    """
    stripped = _text(SKILL_MD).replace("shipped", "")
    assert not _names(stripped, "shipped"), "the probe cannot detect a missing token"
    assert _names(_text(SKILL_MD) + " `banana`", "banana"), "the probe cannot detect a new word"
