"""Phases as ordered containers (#68, PR 2 of lane B5 — the PR that closes it).

PR 1 shipped the *device*: a segmented bar that says what a total is made of. It did not give
the document any way to say **what the phases are, which order they come in, or what work sits
inside each one**. Issue #68 names all three, and its title names the first: *"phases, tracks
and composition meters"*.

Read off the reference page the owner liked (`saystory-hardware-milestones.vercel.app`), the
three missing capabilities were: tracks as first-class containers each with its own state badge;
a segmented bar per track; and work items **nested inside** their track rather than laid out
flat and related only by document order.

Grammar — indentation is containment, exactly as `nodes` already does it, because pipes-as-depth
was tried in wave 2 and rejected as unreadable:

    Windows + GPU      | 3 of 12 done | warn      <- a phase: title | badge | state
      FA-1 | Fan curve stalls above 60C | crit    <- an item:  id | text | state

**Order is the grammar.** Phases render in document order and the renderer numbers them, so the
sequence is visible rather than implied — that is the "no way to say phases in order" gap.

**The per-phase bar is DERIVED, never authored twice.** Its segments come from the states of the
phase's own items, reusing PR 1's `.blk-comp-*` markup. An author who has already written the
items has already written the bar; asking for it again would let the two disagree.
"""
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render  # noqa: E402
from render import blocks  # noqa: E402

DOC = """# T

```phases
Windows + GPU | 3 of 12 done | warn
  FA-1 | Fan curve stalls above 60C | crit
  FA-2 | Telemetry lands in the ring buffer | ok
  FA-3 | Driver reload is flaky | crit
Mac parity | not started | note
  MP-1 | Metal backend | note
```
"""


def _page(style="roadmap", md=DOC):
    return render.render_artifact(md, title="T", style=style, generated_at="x")


class TestAPhaseIsAContainer:
    def test_each_phase_is_its_own_band(self):
        assert _page().count('class="blk-ph ') == 2

    def test_a_phase_carries_its_title(self):
        page = _page()
        assert "Windows + GPU" in page
        assert "Mac parity" in page

    def test_a_phase_carries_its_own_state_badge(self):
        """The badge is the author's own words; the state is what colours it."""
        page = _page()
        assert "3 of 12 done" in page
        assert 'class="blk-ph-badge is-warn"' in page
        assert 'class="blk-ph-badge is-note"' in page

    def test_a_phase_with_no_state_is_neutral_not_dropped(self):
        md = "# T\n\n```phases\nJust a title\n```\n"
        page = _page(md=md)
        assert "Just a title" in page
        assert "is-note" in page


class TestOrderIsPartOfTheGrammar:
    def test_phases_are_numbered_in_document_order(self):
        page = _page()
        assert '<span class="blk-ph-ord">01</span>' in page
        assert '<span class="blk-ph-ord">02</span>' in page

    def test_the_first_phase_written_is_the_first_phase_rendered(self):
        page = _page()
        assert page.index("Windows + GPU") < page.index("Mac parity")

    def test_the_tenth_phase_keeps_two_digits(self):
        md = "# T\n\n```phases\n" + "".join(f"P{n} | x | ok\n" for n in range(1, 12)) + "```\n"
        page = _page(md=md)
        assert '<span class="blk-ph-ord">10</span>' in page
        assert '<span class="blk-ph-ord">11</span>' in page


class TestItemsAreNestedInsideTheirPhase:
    def test_every_item_renders(self):
        # The trailing space matters: `blk-ph-items`, the container, is a prefix of
        # `blk-ph-item` and counting without it scores each container as an item.
        assert _page().count('<div class="blk-ph-item ') == 4

    def test_an_item_sits_inside_its_own_phase_and_not_the_next_one(self):
        page = _page()
        first = page.index("Windows + GPU")
        second = page.index("Mac parity")
        assert first < page.index("FA-3") < second, "FA-3 belongs to the first phase"
        assert second < page.index("MP-1"), "MP-1 belongs to the second"

    def test_an_item_carries_its_id_and_its_prose(self):
        page = _page()
        assert '<span class="blk-ph-id">FA-1</span>' in page
        assert "Fan curve stalls above 60C" in page

    def test_an_item_carries_its_state_as_a_chip(self):
        assert 'class="blk-ph-chip is-crit"' in _page()

    def test_a_phase_with_no_items_still_renders(self):
        md = "# T\n\n```phases\nEmpty phase | nothing yet | note\n```\n"
        assert "Empty phase" in _page(md=md)


class TestTheBarIsDerivedFromTheItems:
    def test_one_segment_per_item_in_the_phase(self):
        """Three items in phase 1, one in phase 2 — four segments, not one bar of four."""
        assert _page().count('<span class="blk-comp-seg') == 4

    def test_segments_take_their_colour_from_the_items_states(self):
        page = _page()
        assert 'class="blk-comp-seg is-crit"' in page
        assert 'class="blk-comp-seg is-ok"' in page

    def test_a_phase_with_no_items_emits_no_bar(self):
        # Assert on the MARKUP, never the bare class name — the stylesheet ships on every
        # roadmap page, so `"blk-comp-seg" not in page` can never fail and proves nothing.
        md = "# T\n\n```phases\nEmpty | nothing yet | note\n```\n"
        assert '<span class="blk-comp-seg' not in _page(md=md)

    def test_the_bar_reuses_the_composition_markup_it_does_not_reinvent_it(self):
        """PR 1's device, applied per phase. A second segment class would be a second
        stylesheet to keep in step with the first."""
        assert '<span class="blk-comp-bar">' in _page()


class TestItFailsSafely:
    def test_an_item_before_any_phase_warns_and_is_promoted_not_dropped(self, capsys):
        md = "# T\n\n```phases\n  orphan | no parent | ok\n```\n"
        page = _page(md=md)
        assert "orphan" in page, "author content is never lost"
        assert "phases" in capsys.readouterr().err.lower()

    def test_extra_fields_warn_rather_than_vanishing(self, capsys):
        md = "# T\n\n```phases\nA | b | ok | surplus\n```\n"
        _page(md=md)
        assert "surplus" in capsys.readouterr().err or "4 fields" in capsys.readouterr().err

    def test_an_empty_block_degrades_to_a_code_listing(self, capsys):
        md = "# T\n\n```phases\n\n```\n"
        page = _page(md=md)
        assert '<div class="blk-ph ' not in page
        assert "phases" in capsys.readouterr().err.lower()

    def test_author_text_cannot_reach_a_class_attribute(self):
        md = ('# T\n\n```phases\n<script>x</script> | b | ok"><b>\n'
              '  <img src=x> | t | z"><i>\n```\n')
        page = _page(md=md)
        assert "<script>" not in page
        assert "<img src=x>" not in page
        assert '"><b>' not in page
        assert '"><i>' not in page

    def test_tabs_indent_the_same_as_spaces(self):
        """Visually-equal indentation must compare equal — the trap `_nodes` documents."""
        md = "# T\n\n```phases\nP | b | ok\n\titem | t | ok\n```\n"
        assert 'class="blk-ph-item' in _page(md=md)


class TestItIsScopedToTheStyleThatOwnsIt:
    def test_roadmap_accepts_it(self):
        assert "phases" in blocks.DOC_TYPE_TAGS["roadmap"]

    def test_it_is_registered_as_a_block_type(self):
        assert "phases" in blocks.BLOCK_TAGS and "phases" in blocks._RENDERERS

    def test_roadmap_marks_it(self):
        assert "rm-phase" in _page()

    def test_a_style_that_does_not_accept_it_warns(self, capsys):
        _page(style="spec")
        assert "not accepted" in capsys.readouterr().err.lower()

    def test_plain_leaves_it_as_a_code_listing(self):
        page = _page(style="plain")
        assert '<div class="blk-ph ' not in page
        assert "Windows + GPU" in page, "the author's text survives as a listing"


# --- #167: the compound `<label>:<level>` chip ------------------------------------------
#
# One chip, two facts. Before this, the state cell said EITHER what the work is OR how urgent it
# is, never both: `crit` hid the kind, `bug` hid the priority (and, before #166, rendered grey).
# The label becomes the word, the level borrows a colour a template already draws.

COMPOUND = """# T

```phases
Backlog | | epic:could
  #347 | Fetching stalls above 60C | bug:must
  #348 | Add the export button | feature:should
  #349 | Tidy the imports | chore:could
  #350 | Ship the thing | task:done
  #351 | a legacy bare token | crit
```
"""


def _chips(page):
    """`{word: colour class}` for every item chip on the page.

    The optional `[^>]*` absorbs the `title=` attribute #173 added. Written as "anything up to
    the closing bracket" rather than a literal title match, so this helper does not need editing
    again the next time a chip gains an attribute.
    """
    import re
    return {m.group(2): m.group(1) for m in
            re.finditer(r'<span class="blk-ph-chip is-([a-z0-9-]+)"[^>]*>([^<]*)</span>', page)}


class TestTheCompoundChipCarriesTypeAndPriority:
    def test_the_word_is_the_label_never_the_level(self):
        chips = _chips(_page(md=COMPOUND))
        assert "bug" in chips, "the chip must read BUG, the type — not MUST, the priority"
        assert "must" not in chips

    def test_must_borrows_the_red_that_crit_uses(self):
        chips = _chips(_page(md=COMPOUND))
        assert chips["bug"] == "crit", "must is red, and it borrows rather than mints a class"
        assert chips["crit"] == "crit", "the legacy bare token still resolves to the same red"

    def test_should_is_amber_could_is_grey_done_is_green(self):
        chips = _chips(_page(md=COMPOUND))
        assert chips["feature"] == "warn"
        assert chips["chore"] == "note"
        assert chips["task"] == "ok"

    def test_a_bare_token_is_completely_unchanged(self):
        """The whole legacy vocabulary keeps working. The colon is the only switch.

        Matched on class-and-word rather than the exact span since #173, which inserts a `title`
        between them. What this test guarantees is the class and the word, and it still does.
        """
        for token in sorted(blocks._PHASE_STATES):
            md = f"# T\n\n```phases\nP | b | ok\n  X-1 | an item | {token}\n```\n"
            assert _chips(_page(md=md)).get(token) == token

    def test_the_bar_segment_takes_the_borrowed_colour_too(self):
        """The bar is derived from the items, so it must agree with the chips above it."""
        page = _page(md=COMPOUND)
        assert '<span class="blk-comp-seg is-crit"></span>' in page
        assert '<span class="blk-comp-seg is-ok"></span>' in page

    def test_no_author_text_reaches_a_class_on_the_compound_path(self):
        md = '# T\n\n```phases\nP | b | ok\n  X-1 | t | bug" onload="x:must\n```\n'
        page = _page(md=md)
        assert "onload" not in page.split("<style")[0] or 'class="blk-ph-chip is-note"' in page
        assert 'is-bug" onload' not in page


class TestAPhaseHeaderCanCarryOneToo:
    def test_the_level_colours_the_badge(self):
        assert 'class="blk-ph-badge is-note"' in _page(md=COMPOUND)

    def _badge(self, page):
        """`(colour class, word)` of the first phase badge, tolerant of added attributes."""
        import re
        m = re.search(r'<span class="blk-ph-badge is-([a-z0-9-]+)"[^>]*>([^<]*)</span>', page)
        return (m.group(1), m.group(2)) if m else (None, None)

    def test_an_empty_badge_falls_back_to_the_label(self):
        """`Backlog | | epic:could` would otherwise render no chip and lose the author's word."""
        assert self._badge(_page(md=COMPOUND)) == ("note", "epic")

    def test_an_authored_badge_still_wins(self):
        """The badge cell is the phase's own word. #167 does not take it over."""
        md = "# T\n\n```phases\nP | 3 of 12 | bug:must\n  X-1 | t | ok\n```\n"
        assert self._badge(_page(md=md)) == ("crit", "3 of 12")


class TestAnUnknownLabelOrLevelIsLoud:
    def test_an_unknown_label_warns_and_falls_back(self, capsys):
        page = _page(md="# T\n\n```phases\nP | b | ok\n  X-1 | t | wibble:must\n```\n")
        err = capsys.readouterr().err
        assert "wibble" in err and "not one of" in err
        assert 'class="blk-ph-chip is-note"' in page
        assert 'is-wibble' not in page

    def test_an_unknown_level_warns_and_falls_back(self, capsys):
        page = _page(md="# T\n\n```phases\nP | b | ok\n  X-1 | t | bug:urgnet\n```\n")
        err = capsys.readouterr().err
        assert "urgnet" in err and "not one of" in err
        assert 'class="blk-ph-chip is-note"' in page

    def test_a_rejected_compound_shows_the_WHOLE_original_not_the_half_that_parsed(self):
        """`bug:urgnet` must not render as a confident `bug` chip — that hides the typo."""
        page = _page(md="# T\n\n```phases\nP | b | ok\n  X-1 | t | bug:urgnet\n```\n")
        assert ">bug:urgnet<" in page
        assert '<span class="blk-ph-chip is-note">bug</span>' not in page

    def test_the_x_placeholder_in_the_spec_is_not_a_real_label(self, capsys):
        """The spec wrote `x:done` for "any label"; the label set is closed, so `x` warns."""
        _page(md="# T\n\n```phases\nP | b | ok\n  X-1 | t | x:done\n```\n")
        assert "not one of" in capsys.readouterr().err


class TestTheLevelsCannotOutrunTheStylesheet:
    def test_every_borrowed_colour_is_a_declared_phase_state(self):
        """Asserted at import too; pinned here so the reason survives a refactor."""
        assert set(blocks._PHASE_LEVELS.values()) <= blocks._PHASE_STATES

    def test_the_import_time_assertion_actually_fires(self, monkeypatch):
        monkeypatch.setitem(blocks._PHASE_LEVELS, "must", "banana")
        with __import__("pytest").raises(AssertionError):
            blocks._assert_phase_levels_are_drawable()


# --- #172: the publish-time nudge, for the author who never reads the docs ----------------
#
# #170 put the vocabulary in SKILL.md, which reaches the next author who opens it. This reaches
# the one who does not, at the moment they publish. Measured need: `rawgentic-plan-graph` shipped
# twice with every chip a bare severity word, from a session whose renderer already understood
# the typed grammar.

def _stderr_of(md, capsys):
    _page(md=md)
    return capsys.readouterr().err


class TestTheTypedChipNudge:
    def test_a_block_reporting_status_in_severity_words_is_nudged(self, capsys):
        err = _stderr_of("# T\n\n```phases\nP | b | warn\n  X-1 | t | crit\n```\n", capsys)
        assert "NOTE" in err and "severity words" in err

    def test_it_fires_once_for_the_whole_block_not_once_per_row(self, capsys):
        rows = "\n".join(f"  X-{i} | t | warn" for i in range(20))
        err = _stderr_of(f"# T\n\n```phases\nP | b | crit\n{rows}\n```\n", capsys)
        assert err.count("NOTE this") == 1, "twenty copies of one suggestion is noise, not help"

    def test_a_converted_document_is_left_alone(self, capsys):
        """A nag that keeps firing after you comply is one people learn to filter out."""
        err = _stderr_of("# T\n\n```phases\nP | b | epic:could\n  X-1 | t | bug:must\n```\n",
                         capsys)
        assert "NOTE this" not in err

    def test_one_compound_token_anywhere_silences_it(self, capsys):
        err = _stderr_of("# T\n\n```phases\nP | b | warn\n  X-1 | t | bug:must\n```\n", capsys)
        assert "NOTE this" not in err, "the author has clearly found the grammar already"

    def test_status_words_are_not_nudged(self, capsys):
        """`done`/`wip`/`blocked` already report status. There is nothing to suggest."""
        err = _stderr_of("# T\n\n```phases\nP | b | wip\n  X-1 | t | done\n```\n", capsys)
        assert "NOTE this" not in err

    def test_ok_and_note_alone_are_not_nudged(self, capsys):
        """Both read as status as well as severity, so a rail using only those is not making
        the mistake this exists to catch. Only `crit` and `warn` are urgency-only."""
        err = _stderr_of("# T\n\n```phases\nP | b | note\n  X-1 | t | ok\n```\n", capsys)
        assert "NOTE this" not in err

    def test_it_states_the_level_mapping_so_the_reader_can_act(self, capsys):
        err = _stderr_of("# T\n\n```phases\nP | b | warn\n  X-1 | t | crit\n```\n", capsys)
        for pair in ("crit->must", "warn->should", "note->could", "ok->done"):
            assert pair in err, f"the nudge must state {pair}, or it is not actionable"

    def test_it_says_the_old_spelling_still_works(self, capsys):
        """Without this line it reads as a deprecation, and every published page looks doomed."""
        err = _stderr_of("# T\n\n```phases\nP | b | warn\n  X-1 | t | crit\n```\n", capsys)
        assert "keep working" in err and "not a defect" in err

    def test_it_is_never_the_word_WARNING(self, capsys):
        """The document is valid. Crying WARNING here trains people to ignore real ones."""
        err = _stderr_of("# T\n\n```phases\nP | b | warn\n  X-1 | t | crit\n```\n", capsys)
        line = [ln for ln in err.splitlines() if "NOTE this" in ln][0]
        assert "WARNING" not in line

    def test_the_nudge_changes_no_rendered_byte(self):
        """It is stderr only. If it ever reaches the page, every snapshot pin moves and the
        containment proof this repo relies on becomes a lie."""
        md = "# T\n\n```phases\nP | b | warn\n  X-1 | t | crit\n```\n"
        page = _page(md=md)
        assert "NOTE this" not in page and "severity words" not in page


# --- #173: hover tells you what the colour means ------------------------------------------
#
# A chip is three uppercase letters in a colour, readable only by someone who already knows the
# vocabulary. #170 fixed that in the docs and #172 at publish time. This fixes it on the page.

LEGENDED = """# T

```phases
G0 Decide | licensing | crit
  D | Licensing ruling | crit
  V | Vendor the core | warn
  Q | Pull-forward hotfixes | bug:must
  Z | No legend for this one | chore:could
```

```legend
crit | blocker or owner decision — nothing downstream starts without it
warn | load-bearing engineering, shadow-mode safe
```
"""


def _titles(page):
    """`{chip word: title text}` for every chip and badge that carries one."""
    import re
    return {m.group(3): m.group(2) for m in re.finditer(
        r'<span class="blk-ph-(?:chip|badge) is-[a-z]+"( title="([^"]*)")?>([^<]*)<', page)
        if m.group(1)}


class TestAChipSaysWhatItMeansOnHover:
    def test_the_documents_own_legend_wins(self):
        """An author who wrote `crit | blocker or owner decision` said something more useful
        than the built-in "stuck", and it is what their readers were given."""
        t = _titles(_page(md=LEGENDED))
        assert t["crit"] == "blocker or owner decision — nothing downstream starts without it"
        assert t["warn"] == "load-bearing engineering, shadow-mode safe"

    def test_a_compound_borrows_its_colours_legend_entry(self):
        """`bug:must` draws in `crit`'s colour, so `crit`'s explanation applies to it."""
        assert _titles(_page(md=LEGENDED))["bug"].startswith("bug · blocker or owner decision")

    def test_a_compound_with_no_legend_match_falls_back_to_the_vocabulary(self):
        assert _titles(_page(md=LEGENDED))["chore"] == "chore · could — scheduled, not started"

    def test_the_phase_badge_gets_one_too(self):
        assert _titles(_page(md=LEGENDED))["licensing"].startswith("blocker or owner decision")

    def test_a_document_with_no_legend_still_gets_the_built_in_meaning(self):
        # The states must sit on ITEMS: a phase's chip word is its badge text, not its state.
        t = _titles(_page(md="# T\n\n```phases\nP | b | ok\n"
                             "  X1 | t | done\n  X2 | t | blocked\n```\n"))
        assert t["done"] == "finished" and t["blocked"] == "stuck"

    def test_a_legend_below_the_rail_is_still_found(self):
        """The reason this needs a pre-pass: blocks render in document order, and a legend
        commonly sits BELOW the rail it explains. `_legend` could never have supplied this."""
        assert "```legend" in LEGENDED.split("```phases")[1], "fixture must keep that order"
        assert _titles(_page(md=LEGENDED))["crit"].startswith("blocker or owner decision")

    def test_an_unknown_token_gets_no_tooltip_rather_than_an_empty_one(self, capsys):
        """An empty tooltip looks like a promise the page failed to keep."""
        page = _page(md="# T\n\n```phases\nP | b | ok\n  X | t | wibble\n```\n")
        capsys.readouterr()
        assert 'title=""' not in page


class TestTheTooltipCannotBeUsedToInjectMarkup:
    def test_a_quote_in_legend_text_cannot_break_out_of_the_attribute(self):
        md = ('# T\n\n```phases\nP | b | crit\n  X | t | crit\n```\n\n'
              '```legend\ncrit | evil" onmouseover="alert(1)\n```\n')
        page = _page(md=md)
        assert 'onmouseover="alert' not in page, "the attribute must not break out"
        assert "&quot;" in page, "the quote survives as an escaped character, not as markup"

    def test_the_title_is_escaped_exactly_once(self):
        """Double-escaping would turn an author's `&` into `&amp;amp;` on screen."""
        md = ('# T\n\n```phases\nP | b | crit\n  X | t | crit\n```\n\n'
              '```legend\ncrit | shipped & verified\n```\n')
        assert 'title="shipped &amp; verified"' in _page(md=md)


class TestItIsPlainHTMLByDesign:
    def test_no_script_is_added_for_the_tooltip(self):
        """These pages ship under a strict CSP and their contract is that they fetch and run
        nothing. `title` needs no JavaScript and screen readers announce it."""
        page = _page(md=LEGENDED)
        assert "<script" not in page

    def test_collecting_the_legend_changes_no_byte_on_its_own(self):
        """The pre-pass only fills `ctx`. If it ever emitted markup, every snapshot pin moves."""
        from render import blocks
        ctx = {}
        blocks.collect_legend(LEGENDED, ctx)
        assert ctx[blocks._CTX_LEGEND]["crit"].startswith("blocker or owner")
        assert blocks.collect_legend(LEGENDED, None) is None, "a missing ctx must be harmless"

    def test_the_first_definition_of_a_key_wins(self):
        """Two legends defining one key is an authoring mistake either way. Preferring the first
        keeps the result stable rather than dependent on block order."""
        from render import blocks
        ctx = {}
        blocks.collect_legend("```legend\nok | first\n```\n\n```legend\nok | second\n```\n", ctx)
        assert ctx[blocks._CTX_LEGEND]["ok"] == "first"
