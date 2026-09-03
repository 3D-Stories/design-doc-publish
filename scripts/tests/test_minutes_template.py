"""#59 — the `minutes` style, the fourteenth template.

A minutes document is not a restyled `analysis`. Robert's Rules of Order says minutes record what
was **done**, not what was said, and calls summarizing discussion "improper" — so the two styles
answer different questions and this is a different document rather than a new stylesheet over the
same content.

The design decisions these tests pin, and where each came from:

**The four regions are DISTINCT (AC6), and their order is asserted here rather than inferred from
the policy maps.** `DOC_TYPE_TAGS` and `FIRST_READ_DEVICES` are sets. A set proves presence and
nothing else — not document order, not distinct headings, not honest content. The Step 3 peer
consult named that limitation and the Step 4 cross-model review proved it concretely: "Meeting
facts" and "Attendees" are both the `chips` TAG, differing only by fence role, so the publish gate
cannot tell them apart and a page dropping the attendee region still publishes. Probed and
confirmed. That is why `TestAC6RegionsAreDistinctAndOrdered` exists: role-level structure is
guarded HERE, by this repository's own tests, and not by the publish gate.

**A meeting that decided nothing still renders (AC8), and its decided register is present but
empty.** `verdict` is in this style's first-read set on purpose, so every minutes page must carry
a decided register. A meeting that chose no course of action carries one holding a single neutral
row. That satisfies AC6's four regions and AC8's honest emptiness at the same time, which an
ABSENT register cannot do. An earlier design draft left `verdict` out of the set, reasoning that
including it would make AC8 unsatisfiable; that reasoning was wrong, because
`lint.check_style_devices` proves PRESENCE, never content.

**One word for one thing (AC7).** `agreed` is a premise the room accepted as true. `decided` is a
course of action it chose. `action` is a thing one named person will do, by a date or an explicit
completion condition. `open` is a question the room did not answer. The word `settle` is never used
for an agreement, because it reads as a decision. `resolved` appears only when reproducing the
exact wording of a formal resolution, never as this template's generic decision marker.
"""
import re
import struct
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import render as render_artifact  # noqa: E402
from render import blocks, frame as render_frame  # noqa: E402

STYLE = "minutes"

# A meeting that agreed premises and chose NO course of action — the kickoff's real shape, and
# the AC8 case. Every region the template declares appears, and nothing here uses a block the
# type rejects.
DOC = """\
The room agreed two premises and chose no course of action.

## Meeting

```chips meetingbar
2026-09-01, 14:00 MDT | note
quorum met | ok
previous minutes approved | ok
```

```chips attendees
A. Rivera - chair | ok
B. Osei - secretary | ok
```

```stats
2 | premises agreed | | | accent
0 | courses decided | | |
2 | action items | | |
1 | question left open | | |
```

## Agreed

```findings
agreed | Data literacy is a skills problem | It was the consensus that the gap is a skills gap. | trace 22:32, segments 381 to 393
agreed | The audience is analysts | Each person present expressed agreement. | trace 31:07, segment 502
```

## Decided

```verdict
none | No course of action was decided at this meeting.
```

## Alternatives considered

```options
Run a workshop first | reaches people quickly | needs a facilitator |
Write a guide first | cheap to revise | fewer people read it |
```

## Actions

```steps
A1 | Draft the premise list | A. Rivera, by 2026-09-08.
A2 | Price a facilitator | B. Osei, before the next meeting.
```

## Open

```callout open
note | One question the room did not answer
Who owns the budget.
```

```provenance
Source | kickoff recording, 2026-09-01
Method | transcript traces, 120 total, 90 ranged
```
"""

# A meeting that DID decide something, so the empty-state row is not the only shape exercised.
DECIDED_DOC = DOC.replace(
    "```verdict\nnone | No course of action was decided at this meeting.\n```",
    "```verdict\ndecided | Ship the written guide first, then price a workshop.\n```",
).replace("0 | courses decided", "1 | courses decided")


def _render(md=DOC, style=STYLE):
    return render_artifact.render_artifact(md, title="Kickoff minutes", style=style,
                                           generated_at="2026-09-02 15:00 MDT")


def _module():
    from render.templates import minutes
    return minutes


class TestItIsARegisteredStyle:
    def test_it_is_in_the_registry(self):
        assert STYLE in render_artifact._TEMPLATES

    def test_it_carries_its_body_class(self):
        assert 'class="tpl-minutes"' in _render()

    def test_the_module_resolves_through_the_roster(self):
        from render import templates
        assert templates.TEMPLATES[STYLE] is _module()

    def test_it_declares_nothing_it_should_not(self):
        """A minutes page's content is per-meeting, so there is no constant furniture to emit,
        and `uat` stays the only interactive template."""
        mod = _module()
        assert not getattr(mod, "BEFORE_BODY", ()), "minutes declares no furniture"
        assert not getattr(mod, "AFTER_BODY", ()), "minutes declares no furniture"
        assert not getattr(mod, "BLOCK_VARIANTS", {}), "minutes declares no block variant"
        assert "<script" not in _render(), "uat is the only interactive template"


class TestTheFrameIsItsOwn:
    def test_the_measure_is_owned_and_unique(self):
        owned = render_frame.owned_slots(_module())
        assert "measure" in owned, "minutes would inherit plain's measure"
        from render import templates
        others = {n: (getattr(m, "FRAME", {}) or {}).get("measure")
                  for n, m in templates.TEMPLATES.items() if n != STYLE}
        mine = _module().FRAME["measure"]
        assert mine not in others.values(), (
            f"{mine} is already used by "
            f"{[n for n, v in others.items() if v == mine]}")

    def test_the_ground_is_a_decision(self):
        """It need not DIFFER from the default — a page whose subject is an archival record
        must not be tinted — but it must be NAMED, so somebody decided."""
        assert "ground" in (getattr(_module(), "FRAME", None) or {})

    def test_it_owns_enough_live_slots(self):
        assert len(render_frame.owned_slots(_module())) >= 3


class TestAC6RegionsAreDistinctAndOrdered:
    """The criterion the policy maps CANNOT prove. See the module docstring."""

    REGIONS = ("mn-attendees", "mn-agreed", "mn-decided", "mn-actions")

    def test_all_four_regions_are_present(self):
        html = _render()
        missing = [r for r in self.REGIONS if r not in html]
        assert not missing, f"AC6 regions absent from the rendered page: {missing}"

    def test_the_attendee_region_is_its_own_marker(self):
        """The gate cannot distinguish `chips attendees` from `chips meetingbar` — both are the
        `chips` tag. So a page can drop the attendee region and still publish. Confirmed by
        probe. This assertion is the only thing standing between that and a silent regression."""
        html = _render()
        assert "mn-attendees" in html, "the attendee region lost its own marker"
        assert "mn-meetingbar" in html, "the meeting-facts region lost its own marker"
        assert html.index("mn-meetingbar") < html.index("mn-attendees"), (
            "meeting facts come before attendees")

    def test_the_regions_appear_in_document_order(self):
        html = _render()
        at = [html.index(r) for r in self.REGIONS]
        assert at == sorted(at), (
            f"AC6 regions are out of order: "
            f"{sorted(zip(at, self.REGIONS))}")

    def test_the_ledger_leads_the_registers(self):
        """Summary-first. The ledger answers "what did this meeting do?" in the opening
        screenful, which is what this engine's design language requires of every style."""
        html = _render()
        assert html.index("mn-ledger") < html.index("mn-agreed")


class TestAC8DecidedNothing:
    """A meeting that decided nothing must not look like a defect."""

    def test_the_page_renders(self):
        assert _render(), "the decided-nothing page did not render"

    @staticmethod
    def _decided_region(md=DOC):
        """The decided register's own markup, sliced out of the BODY.

        Sliced rather than searched whole, for the reason recorded on the AC7 test: this
        template's CSS names `mn-decided` and `is-none` inside the <style> block, so any
        assertion against the complete page can be satisfied by the stylesheet.
        """
        body = re.search(r"<body[^>]*>(.*)</body>", _render(md), re.S).group(1)
        start = body.index("mn-decided")
        return body[start:body.index("mn-alternatives", start)]

    def test_the_decided_register_is_present_but_holds_no_decision(self):
        """Step 8a hardened this. The first cut asserted `mn-decided` present and the
        string `>decided<` absent, and MEASURED, a page whose verdict key was `confirmed`
        satisfied both — so the pair proved the register existed and proved nothing about
        what it said. These assertions pin the row itself."""
        region = self._decided_region()
        rows = re.findall(r'<div class="blk-row([^"]*)"', region)
        assert len(rows) == 1, f"the decided register holds {len(rows)} rows, expected exactly 1"
        assert "is-none" in rows[0], (
            f"the single row is not the empty state: class was 'blk-row{rows[0]}'")
        keys = re.findall(r'<span class="blk-key">([^<]*)</span>', region)
        assert keys == ["none"], (
            f"the empty state's key is {keys}, and only `none` is the honest one — a key "
            "like `confirmed` would pass a mere absence check while saying something else")
        assert "No course of action was decided at this meeting." in region, (
            "the empty state carries no sentence saying so, which is the whole point of "
            "rendering the register rather than omitting it")

    def test_the_empty_state_has_its_own_state_class(self):
        """So the template can style it neutrally rather than as a warning."""
        assert "is-none" in self._decided_region()

    def test_the_ledger_prints_the_zero_rather_than_omitting_it(self):
        """An absence rendered as a printed zero is a statement somebody made.

        Step 8a removed this assertion's `or "0" in html` escape clause, which made it pass
        on any page containing the character 0 anywhere — including inside a hex colour in
        the stylesheet. The value and its label are now required to be adjacent."""
        body = re.search(r"<body[^>]*>(.*)</body>", _render(), re.S).group(1)
        ledger = body[body.index("mn-ledger"):body.index("mn-agreed")]
        pair = re.search(r'<span class="blk-value">([^<]*)</span>'
                         r'<span class="blk-label">courses decided</span>', ledger)
        assert pair, "the ledger has no `courses decided` entry at all"
        assert pair.group(1) == "0", (
            f"the ledger reports {pair.group(1)!r} courses decided on a page whose register "
            "is empty")

    def test_a_page_that_DID_decide_still_works(self):
        """The empty state must not be the only shape the template can render."""
        html = _render(DECIDED_DOC)
        assert "mn-decided" in html
        assert ">decided<" in html, "a real decision did not reach the page"


class TestAC7Vocabulary:
    WORDS = ("agreed", "decided", "action", "open")

    def test_the_docstring_names_every_word_it_uses(self):
        doc = _module().__doc__ or ""
        missing = [w for w in self.WORDS if w not in doc]
        assert not missing, f"the docstring does not define: {missing}"

    def test_settle_is_never_a_register_label(self):
        mod = _module()
        for slot, cls in mod.MARKERS.items():
            assert "settle" not in cls, f"marker {slot} uses 'settle': {cls}"
        assert "settle" not in _render().lower().replace("settled", ""), (
            "'settle' reached a rendered minutes page")

    def test_the_docstring_forbids_settle_explicitly(self):
        """AC7 asks the template to DOCUMENT which words it uses. A vocabulary that omits its
        own prohibition has not documented it."""
        doc = (_module().__doc__ or "").lower()
        assert "settle" in doc, "the docstring never mentions the word it bans"

    def test_each_word_reaches_its_own_region_on_the_rendered_page(self):
        """AC7 says the template USES one word for one thing, and "uses" means the OUTPUT.

        A docstring assertion alone would pass while the rendered page misused every word,
        which a cross-model review of the plan named. So this checks the page: each register's
        key word must appear INSIDE that register's own region and not somewhere else.
        """
        # The BODY, never the whole page. The first cut of this test sliced the full
        # document, so every region started inside the <style> block — where this
        # template's own CSS names `mn-agreed` and `mn-decided` within a few rules of each
        # other, and its comments use both words. Every region therefore "contained" every
        # word and the test failed for a reason having nothing to do with the page.
        html = re.search(r"<body[^>]*>(.*)</body>", _render(), re.S).group(1)

        # Slice the body at each region marker, so "inside this region" is a real claim
        # rather than "somewhere on the page".
        def region(cls, *following):
            start = html.index(cls)
            ends = [html.index(f) for f in following if f in html and html.index(f) > start]
            return html[start:min(ends)] if ends else html[start:]

        agreed = region("mn-agreed", "mn-decided")
        decided = region("mn-decided", "mn-alternatives", "mn-actions")
        actions = region("mn-actions", "mn-open")
        assert "agreed" in agreed, "the agreed register does not carry the word `agreed`"
        assert "decided" not in agreed, (
            "`decided` leaked into the agreed register — one word for one thing")
        assert "none" in decided or "decided" in decided, (
            "the decided register carries neither its key word nor its empty-state key")
        assert "agreed" not in decided, (
            "`agreed` leaked into the decided register — one word for one thing")
        assert "A1" in actions and "A2" in actions, (
            "the action rows did not reach the actions region")


class TestAC13ThePrecedentIsRecorded:
    def test_the_docstring_names_both_precedents_and_the_divergence(self):
        doc = _module().__doc__ or ""
        for cite in ("openui/open-ui", "json-ld/minutes", "nodejs/TSC"):
            assert cite in doc, f"the docstring does not name the precedent {cite}"
        assert "precedent" in doc.lower(), (
            "the docstring must record that summary-first minutes have no committed-artifact "
            "precedent")

    def test_the_docstring_records_that_the_type_policy_only_WARNS(self):
        """`DOC_TYPE_TAGS` is advisory: `blocks.py` prints a warning and renders a rejected
        block anyway. A docstring claiming the transcript shape is *enforced* would be false,
        and an earlier design draft said exactly that."""
        doc = (_module().__doc__ or "").lower()
        assert "warn" in doc, "the docstring overstates what excluding `timeline` achieves"


class TestMarkers:
    EXPECTED = {"mn-meetingbar", "mn-attendees", "mn-ledger", "mn-agreed", "mn-trace",
                "mn-decided", "mn-alternatives", "mn-actions", "mn-open"}

    def test_every_declared_marker_reaches_the_page(self):
        html = _render()
        missing = sorted(c for c in _module().MARKERS.values() if c not in html)
        assert not missing, f"declared but never emitted: {missing}"

    def test_the_expected_set_is_what_the_module_declares(self):
        assert set(_module().MARKERS.values()) == self.EXPECTED

    def test_every_marker_value_is_a_strict_slug(self):
        slug = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
        bad = [v for v in _module().MARKERS.values() if not slug.match(v)]
        assert not bad, f"not slugs: {bad}"

    def test_the_markers_are_absent_from_every_other_style(self):
        for style in render_artifact._TEMPLATES:
            if style == STYLE:
                continue
            html = render_artifact.render_artifact(
                DOC, title="T", style=style, generated_at="x")
            leaked = sorted(c for c in self.EXPECTED if c in html)
            assert not leaked, f"{style} emits minutes markers: {leaked}"


class TestPolicy:
    def test_it_declares_its_accepted_tags(self):
        assert blocks.DOC_TYPE_TAGS[STYLE] == {
            "chips", "stats", "findings", "verdict", "options", "steps",
            "callout", "provenance"}

    def test_timeline_is_excluded_on_purpose(self):
        """The one block that would make this a transcript. Excluding it is advisory rather
        than enforcing — see the docstring — but it is the strongest signal available, and
        `test_template_bodies.py` fails on any fixture that uses a rejected block."""
        assert "timeline" not in blocks.DOC_TYPE_TAGS[STYLE]

    def test_its_first_read_devices_are_satisfiable(self):
        required = blocks.FIRST_READ_DEVICES[STYLE]
        assert required, "an empty requirement is a vacuous gate"
        assert required <= blocks.DOC_TYPE_TAGS[STYLE], (
            f"unsatisfiable: {sorted(required - blocks.DOC_TYPE_TAGS[STYLE])}")

    def test_the_decided_register_is_mandatory_on_every_page(self):
        """AC8's mechanism. `verdict` in the set is what makes the empty register a present
        register rather than an absent one."""
        assert "verdict" in blocks.FIRST_READ_DEVICES[STYLE]

    def test_the_gate_accepts_the_decided_nothing_page(self):
        from render import lint
        assert lint.check_style_devices(_render()) == []

    def test_the_gate_refuses_a_page_missing_its_decided_register(self):
        """An absence assertion that cannot fail is not a gate."""
        from render import lint
        stripped = DOC.replace(
            "```verdict\nnone | No course of action was decided at this meeting.\n```", "")
        out = lint.check_style_devices(_render(stripped))
        assert out and "verdict" in out[0], f"the gate did not fire: {out}"


class TestEveryRuleThisTemplateWritesCanActuallyMatch:
    """A CSS rule naming a class the engine never emits is dead weight that LOOKS like styling.

    Found by the recorded visual inspection of the gallery screenshot, not by any assertion
    here: the ledger rendered as four bordered tiles although this template's own rule sets
    `border:0;background:none` on them. The rule named `.blk-stat`, and the stats block emits
    `.blk-item` — the class appeared nowhere in the render package except in that one rule.
    Every marker test passed the whole time, because a marker test proves the classes this
    template DECLARES reach the page and says nothing about the ones its CSS SELECTS.

    Scoped to this template on purpose. A repository-wide version would be a better guard and
    is a bigger change than #59; this one covers the file it ships with.
    """

    # EVERY class token, not only the shared `blk-` ones. Step 8a caught the first cut
    # matching `blk-` alone, which left this template's OWN vocabulary unguarded: a
    # misspelled `.mn-action` or `.tpl-minute` carries most of the styling and would have
    # been invisible to the very guard added to catch exactly that.
    CLASS = re.compile(r"\.([a-z][a-z0-9]*(?:-[a-z0-9]+)*)")

    def _selected(self):
        """Every class this template's CSS selects, read out of the selectors only.

        The rule bodies are skipped, so a class named inside a `content:` string or a comment
        is not mistaken for a selector.
        """
        css = _module().CSS
        out = set()
        for rule in css.split("}"):
            head = rule.split("{")[0]
            # Strip comments, which sit between rules and mention class names in prose.
            head = re.sub(r"/\*.*?\*/", " ", head, flags=re.S)
            out.update(self.CLASS.findall(head))
        return out

    def _emitted(self):
        """The union of BOTH document shapes, so a class that only the populated page or only
        the decided-nothing page carries still counts as reachable."""
        out = set()
        for md in (DOC, DECIDED_DOC):
            out.update(re.findall(r'class="([^"]+)"', _render(md)))
        return {c for group in out for c in group.split()}

    def test_it_declares_no_counter_it_never_displays(self):
        """The same defect class as a dead selector, and the inline half of the Step 8a wave
        found one: `counter-reset:mn-act` and `counter-increment:mn-act` were declared while
        `counter(mn-act)` appeared nowhere, so nothing ever printed it. The step number comes
        from `.blk-n`, which the engine emits and this template already styles, so the counter
        was two inert declarations on every minutes page and a claim the next reader would
        have believed."""
        css = _module().CSS
        declared = set(re.findall(r"counter-(?:reset|increment):([a-z0-9-]+)", css))
        used = set(re.findall(r"counter\(([a-z0-9-]+)", css))
        dead = sorted(declared - used)
        assert not dead, (
            f"counters declared but never displayed: {dead}. Either print one with "
            "`content:counter(...)` or delete the declarations")

    def test_every_class_its_css_selects_reaches_a_rendered_page(self):
        dead = sorted(self._selected() - self._emitted())
        assert not dead, (
            f"this template styles classes the engine never emits: {dead}. The rule is inert, "
            "so the page does not look like the module says it does")


class TestTheGalleryScreenshot:
    """AC4 requires `test_example_gallery.py` to pass, and that only checks the file EXISTS.
    A blank, stale or wrong-page capture would pass it silently, so decode the thing."""

    PNG = ROOT / "docs" / "examples" / "gallery" / "minutes.png"

    def test_it_decodes_as_a_png(self):
        data = self.PNG.read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"

    def test_it_matches_the_dimensions_every_other_gallery_shot_uses(self):
        data = self.PNG.read_bytes()
        width, height = struct.unpack(">II", data[16:24])
        assert (width, height) == (1280, 1000), (
            f"{width}x{height}; every committed gallery shot is 1280x1000, so this one was "
            "taken with a different viewport")

    def test_it_is_not_a_blank_page(self):
        """A blank 1280x1000 PNG compresses to a few kilobytes.

        The floor is DERIVED from the other committed gallery shots rather than written
        here as a magic number, so it maintains itself as the gallery changes. Half the
        smallest sibling is comfortably above any blank page and comfortably below any
        real one.

        **What this does NOT prove**, stated because the opposite claim would be the
        defect: a byte floor cannot establish that the image depicts the MINUTES page. A
        browser error page is 1280x1000 too and may clear the floor. A reviewed SHA oracle
        was considered and declined — a screenshot sha is brittle across font rendering,
        Chrome versions and GPU flags, so it would go red for reasons unrelated to the
        page and teach people to ignore it. The evidence that the capture is the right
        page is a recorded visual inspection at the commit that creates it.
        """
        siblings = [p.stat().st_size for p in self.PNG.parent.glob("*.png")
                    if p.name != self.PNG.name]
        assert siblings, "no sibling gallery screenshots to derive a floor from"
        floor = min(siblings) // 2
        size = self.PNG.stat().st_size
        assert size > floor, (
            f"{size} bytes is below {floor}, half the smallest sibling shot — too small "
            f"to be a rendered page")


@pytest.mark.parametrize("other", ["design-system", "review", "report"])
def test_it_does_not_move_another_styles_bytes(other):
    """Adding a template must change nothing else. `test_furniture_context.py`'s PRE_74 oracle
    is the real guard over every style; this is a cheap local echo of it on three neighbours."""
    a = render_artifact.render_artifact(DOC, title="T", style=other, generated_at="x")
    b = render_artifact.render_artifact(DOC, title="T", style=other, generated_at="x")
    assert a == b
    assert "tpl-minutes" not in a
