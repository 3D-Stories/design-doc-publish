"""The uat template — the only interactive page the engine renders (#18, wave 4).

Every test here starts from a KNOWN NON-EMPTY fixture and asserts a count against the source
row count. That is deliberate: the wave-3 review found a marker test that passed while the
thing it claimed to check was absent, and the same shape is available here — `.ut-item` present
but carrying no checkbox, `.ut-note` present once rather than once per item, a forbidden-API
grep passing because no script was emitted at all.
"""
import re
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render as render_artifact  # noqa: E402

# three rows, so a per-item assertion cannot pass by counting globally
ITEMS = """```steps
install.clone | Clone the repo | git clone git@example:x
install.run | Run the installer | bash install.sh
verify.boot | Boot it once | it must reach the main screen
```
"""
ROWS = 3


def _render(md=ITEMS, **kw):
    kw.setdefault("title", "UAT")
    kw.setdefault("style", "uat")
    kw.setdefault("generated_at", "2026-08-01 12:00 MDT")
    return render_artifact.render_artifact(md, **kw)


def _body(h):
    return h.split("<body", 1)[1]


def _items(h):
    """Each `.ut-item` element's inner HTML — the unit every AC1 claim is made about."""
    return re.findall(r'<li class="ut-item">(.*?)</li>', _body(h), re.S)


class TestAC1CheckboxAndCommentPerItem:
    def test_one_item_per_source_row(self):
        assert len(_items(_render())) == ROWS

    def test_every_item_has_exactly_one_checkbox_and_one_note(self):
        items = _items(_render())
        assert len(items) == ROWS, "fixture did not render; the rest would pass vacuously"
        for n, item in enumerate(items):
            assert item.count('type="checkbox"') == 1, f"item {n}: {item[:120]}"
            assert item.count('class="ut-note"') == 1, f"item {n}: {item[:120]}"

    def test_the_counts_are_equal_which_is_the_defect_the_issue_names(self):
        """The target has 25 items and 16 comment boxes. Equal counts is the whole point."""
        h = _body(_render())
        assert h.count('type="checkbox"') == h.count('class="ut-note"') == ROWS

    def test_the_label_wraps_the_checkbox_so_the_row_is_clickable(self):
        """Reproduced from the target: no `for` attribute is needed, and none is emitted —
        a generated id paired by `for` was the collision risk the design gate flagged."""
        items = _items(_render())
        assert len(items) == ROWS, "a zero-length loop would prove nothing"
        for item in items:
            assert re.search(r'<label class="ut-row">\s*<input type="checkbox"', item)
        assert 'for="' not in _body(_render())


class TestAC2Identity:
    def test_storage_keys_are_the_authored_ids_not_positions(self):
        h = _body(_render())
        for logical in ("install.clone", "install.run", "verify.boot"):
            assert f'data-k="{logical}"' in h
            assert f'data-note="{logical}"' in h

    def test_no_id_or_for_is_emitted_at_all(self):
        """The label wraps its checkbox, so the pairing needs neither — and a generated
        id was a second identifier that would also have had to be unique page-wide."""
        h = _body(_render())
        assert h.count('type="checkbox"') == ROWS, "fixture did not render"
        assert not re.search(r"<input[^>]*\sid=", h)
        assert 'for="' not in h

    def test_ids_are_unique_ACROSS_fences_not_merely_within_one(self):
        """A page has many parts, so a fence-local `seen` set is no guarantee at all.
        Both fences below rendered items keyed `a` until a Step 11 review caught it, and
        `save()` then wrote both rows to one key with the later one winning."""
        dup = _body(_render("```steps\na | One | x\n```\n\n```steps\na | Two | y\n```\n"))
        assert dup.count('<li class="ut-item">') == 1, "the second fence must not render"
        assert dup.count("<pre><code>") == 1, "its content must survive as a listing"
        ok = _body(_render("```steps\na | One | x\n```\n\n```steps\nb | Two | y\n```\n"))
        assert ok.count('<li class="ut-item">') == 2
        assert re.findall(r'data-k="([^"]+)"', ok) == ["a", "b"]

    def test_two_documents_do_not_share_the_uniqueness_state(self):
        """The context is per-render. If it leaked, the second page would reject every id
        the first used."""
        for _ in range(2):
            assert _body(_render()).count('<li class="ut-item">') == ROWS

    def test_a_duplicate_id_degrades_the_fence_instead_of_merging_two_items(self, capsys):
        h = _render("```steps\na | One | x\na | Two | y\n```\n")
        assert "ut-item" not in _body(h), "duplicate ids must not both render"
        assert "<pre><code>" in _body(h), "the author's content must survive as a listing"
        assert "duplicate" in capsys.readouterr().err.lower()

    def test_an_empty_id_degrades_the_fence_rather_than_collapsing_to_a_sentinel(self, capsys):
        h = _render("```steps\n | One | x\nb | Two | y\n```\n")
        assert "ut-item" not in _body(h)
        assert capsys.readouterr().err != ""

    def test_distinct_doc_ids_do_not_collide(self):
        """`_slug` collapsed case and every punctuation run, so `repo/a`, `repo:a` and
        `REPO-A` were ONE key — three documents silently sharing state on one origin. An
        explicit doc_id is used verbatim; a localStorage key needs no slug syntax."""
        keys = {re.search(r'data-uat-key="([^"]*)"', _render(doc_id=d)).group(1)
                for d in ("repo/a", "repo:a", "REPO-A", "repo-a")}
        assert len(keys) == 4, keys

    def test_the_page_key_uses_doc_id_and_warns_without_one(self, capsys):
        assert "uat:saystory-0287:v1" in _render(doc_id="saystory-0287")
        h = _render()
        assert "uat:uat:v1" in h  # falls back to the title slug
        assert "doc_id" in capsys.readouterr().err


class TestAC4NoInnerHtmlAndOneScript:
    FORBIDDEN = ("innerHTML", "outerHTML", "document.write", "eval(")

    def test_uat_emits_exactly_one_non_empty_inline_script(self):
        scripts = re.findall(r"<script>(.*?)</script>", _render(), re.S)
        assert len(scripts) == 1
        assert len(scripts[0].strip()) > 200, "an empty script would pass every grep below"

    @pytest.mark.parametrize("api", FORBIDDEN)
    def test_the_script_uses_no_forbidden_dom_api(self, api):
        script = re.findall(r"<script>(.*?)</script>", _render(), re.S)[0]
        assert api not in script

    def test_the_script_is_inline_never_fetched(self):
        assert not re.search(r"<script[^>]+src=", _render(), re.I)

    def test_no_other_template_emits_a_script(self):
        for style in ("plain", "analysis", "roadmap", "report", "design",
                      "dashboard", "review", "spec", "workflow"):
            assert "<script" not in render_artifact.render_artifact(
                ITEMS, title="T", style=style, generated_at="x"), style


class TestAC5NoUnoverridableColour:
    """A bare `#hex` grep passes on an empty stylesheet, and misses rgb()/hsl()/named.

    The eight-name list this started with was beaten twice in one review round: `orange` and
    `rebeccapurple` are not in it, and the function check was case-sensitive so `RGB(1 2 3)`
    and the modern `lab()`/`oklch()` spellings walked through. It is now the FULL CSS named
    set and every colour-function spelling, matched case-insensitively.
    """

    # The complete CSS named colours. `transparent` and `currentColor` are deliberately absent:
    # they are keywords that inherit whatever the tokens supply, so they are overridable.
    NAMED = (
        "aliceblue", "antiquewhite", "aqua", "aquamarine", "azure", "beige", "bisque", "black",
        "blanchedalmond", "blue", "blueviolet", "brown", "burlywood", "cadetblue", "chartreuse",
        "chocolate", "coral", "cornflowerblue", "cornsilk", "crimson", "cyan", "darkblue",
        "darkcyan", "darkgoldenrod", "darkgray", "darkgreen", "darkgrey", "darkkhaki",
        "darkmagenta", "darkolivegreen", "darkorange", "darkorchid", "darkred", "darksalmon",
        "darkseagreen", "darkslateblue", "darkslategray", "darkslategrey", "darkturquoise",
        "darkviolet", "deeppink", "deepskyblue", "dimgray", "dimgrey", "dodgerblue",
        "firebrick", "floralwhite", "forestgreen", "fuchsia", "gainsboro", "ghostwhite", "gold",
        "goldenrod", "gray", "green", "greenyellow", "grey", "honeydew", "hotpink",
        "indianred", "indigo", "ivory", "khaki", "lavender", "lavenderblush", "lawngreen",
        "lemonchiffon", "lightblue", "lightcoral", "lightcyan", "lightgoldenrodyellow",
        "lightgray", "lightgreen", "lightgrey", "lightpink", "lightsalmon", "lightseagreen",
        "lightskyblue", "lightslategray", "lightslategrey", "lightsteelblue", "lightyellow",
        "lime", "limegreen", "linen", "magenta", "maroon", "mediumaquamarine", "mediumblue",
        "mediumorchid", "mediumpurple", "mediumseagreen", "mediumslateblue",
        "mediumspringgreen", "mediumturquoise", "mediumvioletred", "midnightblue", "mintcream",
        "mistyrose", "moccasin", "navajowhite", "navy", "oldlace", "olive", "olivedrab",
        "orange", "orangered", "orchid", "palegoldenrod", "palegreen", "paleturquoise",
        "palevioletred", "papayawhip", "peachpuff", "peru", "pink", "plum", "powderblue",
        "purple", "rebeccapurple", "red", "rosybrown", "royalblue", "saddlebrown", "salmon",
        "sandybrown", "seagreen", "seashell", "sienna", "silver", "skyblue", "slateblue",
        "slategray", "slategrey", "snow", "springgreen", "steelblue", "tan", "teal", "thistle",
        "tomato", "turquoise", "violet", "wheat", "white", "whitesmoke", "yellow",
        "yellowgreen",
    )

    FUNCTIONS = ("rgb(", "rgba(", "hsl(", "hsla(", "hwb(", "lab(", "lch(", "oklab(",
                 "oklch(", "color(", "color-mix(")

    def _uat_css(self):
        from render import templates
        return templates.CSS["uat"]

    def test_the_uat_stylesheet_is_not_empty(self):
        assert len(self._uat_css().strip()) > 200

    def test_it_declares_no_literal_colour_of_any_form(self):
        css = self._uat_css()
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css)
        for fn in self.FUNCTIONS:
            # Case-insensitive: `RGB(1 2 3)` is as valid to a browser as `rgb(1 2 3)`, and the
            # case-sensitive check let a reviewer ship exactly that.
            assert fn not in css.lower(), fn
        low = css.lower()
        for name in self.NAMED:
            # `:\s*<name>` only caught a colour sitting immediately after the colon, so
            # `border:1px solid red` walked straight through. Match the bare word anywhere,
            # excluding hyphenated identifiers so `white-space` and a `--grey-…` custom
            # property are not false positives. Comments are searched too: AC5 says
            # "anywhere", and comments ship inside the emitted stylesheet.
            assert not re.search(rf"(?<![-\w]){name}(?![-\w])", low), name

    def test_the_colour_guard_catches_what_review_slipped_past_it(self):
        """Each string below shipped past an earlier version of the guard."""
        for hostile in ("border:1px solid orange", "color:rebeccapurple", "color:RGB(1 2 3)",
                        "background:lab(50% 20 -30)", "outline:2px solid red", "color:#abc"):
            probe = ".x{" + hostile + "}"
            hit = (re.search(r"#[0-9a-fA-F]{3,8}\b", probe)
                   or any(f in probe.lower() for f in self.FUNCTIONS)
                   or any(re.search(rf"(?<![-\w]){n}(?![-\w])", probe.lower())
                          for n in self.NAMED))
            assert hit, f"the guard would let this through: {hostile}"


class TestFurnitureAndPolicy:
    def test_the_meter_and_export_are_furniture_the_author_never_writes(self):
        h = _body(_render())
        assert h.count('class="ut-meter"') == 1
        assert h.count('class="ut-export"') == 1

    def test_the_meter_actually_counts_rather_than_merely_naming_its_elements(self):
        """Asserting the two element ids appear would pass with no arithmetic at all."""
        script = re.findall(r"<script>(.*?)</script>", _render(), re.S)[0]
        assert "boxes.filter" in script and "b.checked" in script
        assert "100 * n / boxes.length" in script
        assert "n + ' / ' + boxes.length" in script

    def test_uat_declares_its_accepted_blocks(self):
        from render import blocks
        assert blocks.DOC_TYPE_TAGS["uat"] == {"steps", "callout", "chips", "meter"}

    def test_a_stop_callout_renders_with_its_marker(self):
        h = _body(_render("```callout stop\nstop | Halt\nDo not proceed.\n```\n"))
        assert "ut-stop" in h and "Halt" in h

    def test_the_storage_READ_and_the_storage_WRITE_are_each_guarded(self):
        """Counting any two `try` blocks does not tie them to the two calls that throw."""
        script = re.findall(r"<script>(.*?)</script>", _render(), re.S)[0]
        assert re.search(r"try\s*\{[^}]*localStorage\.getItem", script)
        assert re.search(r"try\s*\{[^}]*localStorage\.setItem", script)

    def test_a_corrupt_but_parseable_blob_cannot_falsify_a_result(self):
        """`"false"` is a TRUTHY string, so truthiness-based restore marks it checked."""
        script = re.findall(r"<script>(.*?)</script>", _render(), re.S)[0]
        assert "=== true" in script, "checkbox restore must compare by type"
        assert "typeof v === 'string'" in script, "a note must only restore from a string"

    def test_the_export_label_lookup_cannot_be_injected(self):
        """An id of `x\"]` interpolated into querySelector threw inside build(), killing
        the export outright — clipboard and fallback both."""
        script = re.findall(r"<script>(.*?)</script>", _render(), re.S)[0]
        assert "querySelector('input[data-k=" not in script
        assert "hasOwnProperty.call(titles" in script

    def test_the_export_declares_exactly_the_sections_it_can_honestly_produce(self):
        """A checkbox and a note cannot express pass-versus-fail, so there are THREE
        UNCONDITIONAL sections and the instruction carries the distinction. Pinning the exact
        set stops both a silently-dropped section and a fourth that the UI cannot populate.

        #59 added a FOURTH, and it is deliberately conditional: orphaned answers exist only
        when storage holds a key this page has no item for. The rule the original test was
        protecting is unchanged and now stated directly — a section may only be emitted when
        it has something real to say — so this asserts the three that always print AND that
        the orphan heading is reachable only inside a non-empty guard.
        """
        script = re.findall(r"<script>(.*?)</script>", _render(), re.S)[0]
        headings = re.findall(r"L\.push\('(## [^']+)'\)", script)
        assert headings[:3] == ["## Executed", "## Not executed", "## Observations"], headings
        for phrase in ("records EXECUTED", "not failed", "a checked one is not a",
                       "only ever stated in an observation"):
            assert phrase in script, phrase

        orphan_heads = [h for h in headings if "no matching item" in h]
        assert len(orphan_heads) == 1, headings
        assert len(headings) == 4, f"a fifth section appeared unreviewed: {headings}"
        # It must sit INSIDE `if (orph.length) {`, never at the top level — an empty
        # "Answers with no matching item" heading on every export is noise that trains the
        # reader to skip the one section that means a human's work nearly vanished.
        guard = re.search(r"if \(orph\.length\) \{(.*?)\n    \}", script, re.S)
        assert guard, "the orphan section is not wrapped in a non-empty guard"
        assert "no matching item" in guard.group(1), (
            "the orphan heading is emitted outside its guard, so it prints when empty")

    def test_the_clipboard_has_a_textarea_fallback(self):
        script = re.findall(r"<script>(.*?)</script>", _render(), re.S)[0]
        # The fallback textarea is SERVER-RENDERED and revealed, not created at runtime:
        # one less DOM-building path, and it exists even if the script never runs.
        assert "navigator.clipboard" in script
        assert 'id="ut-out"' in _body(_render()) and "ta.hidden = false" in script


class TestFilterCannotEraseAnswers:
    """#40 T8. `boxes`/`notes` are SNAPSHOT arrays taken once at load, and `save()` rebuilds
    the entire stored blob from them. Measured in Chromium rather than assumed:

    * detaching a row is survivable — the arrays keep the reference, so the detached item's
      tick and note are still written on the next save;
    * replacing the rows is not. After an `innerHTML` rebuild both arrays hold orphans, so a
      tick on a rebuilt row reaches no listener and no storage while the screen shows it
      ticked (meter 3/6 against four visible ticks);
    * reassigning either array to a filtered subset does the same damage with no DOM edit at
      all — which is why the guard below covers reassignment, not just DOM APIs.

    An earlier version of this docstring, of the two source comments and of the planning note
    all said detachment erases answers. It does not; both Step-8a reviewers and a browser run
    caught it. Hiding must still be presentational only — the reason is the snapshot arrays,
    not detachment.

    The four-step browser check (two partitions given distinct answers, filter one away,
    mutate while filtered, reload, unfilter, compare all six) passes. These are the static
    guards that keep it true, because nobody re-runs a manual check on every commit.
    """

    def test_the_filter_hides_with_css_and_keeps_every_input_in_the_document(self):
        h = _render("```steps\na.one | One | d | must\nb.two | Two | d | should\n```\n")
        css = h.split("<style>")[1].split("</style>")[0]
        # COMMENTS STRIPPED FIRST. Without this the prose above these rules — which
        # explains why hiding must be `display:none` — lands in the same `}`-split chunk
        # and satisfies the assertion on its own. That exact mistake has now been made
        # three times in this issue (the analysis table test, the spec details count, and
        # here), so it is called out rather than quietly fixed.
        bare = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        rules = [r for r in bare.split("}")
                 if "data-ut-state" in r.split("{")[0] or "data-ut-level" in r.split("{")[0]]
        assert len(rules) >= 4, f"expected a rule per filter option, got {len(rules)}"
        # Counting rules and grepping for `display:none` is not enough, and both Step-8a
        # reviewers demonstrated why: repoint a rule at `.ut-filter` and clicking "Not
        # executed" hides the toolbar itself with no way back to All; repoint it at bare `li`
        # and a level filter hides ordinary prose list items; swap `.is-must` for a class the
        # renderer never emits and the filter silently does nothing. Each mutation keeps four
        # `display:none` rules. So pin the exact predicate set, not the shape.
        selectors = {r.split("{")[0].strip() for r in rules}
        expected = {
            '.tpl-uat[data-ut-state="todo"] .ut-item:has(input[type=checkbox]:checked)',
            '.tpl-uat[data-ut-state="done"] .ut-item:not(:has(input[type=checkbox]:checked))',
            '.tpl-uat[data-ut-level="must"] .ut-item:not(:has(.blk-level.is-must))',
            '.tpl-uat[data-ut-level="should"] .ut-item:not(:has(.blk-level.is-should))',
        }
        assert selectors == expected, (
            f"filter selectors changed.\nmissing: {expected - selectors}\n"
            f"unexpected: {selectors - expected}")
        for r in rules:
            body = r.split("{", 1)[1] if "{" in r else ""
            assert body.strip() == "display:none", (
                f"a filter rule that does more than hide: {r!r}")
        # Both items are in the markup regardless of any filter state.
        assert h.count('type="checkbox" data-k=') == 2
        # `data-note`, not every <textarea>: the export section ships one too.
        assert h.count('<textarea class="ut-note" data-note=') == 2

    def test_the_filter_script_never_rebuilds_the_dom(self):
        """The dangerous edit is someone later 'optimising' the filter into a DOM rebuild."""
        from render.templates import uat
        # `replaceWith` and `replaceChild` were added after a Step-11 reviewer replaced a row
        # with `replaceWith(...)` and the list did not notice.
        for banned in ("removeChild", ".remove(", "innerHTML", "outerHTML",
                       "replaceChildren", "replaceChild", "replaceWith",
                       "insertAdjacentHTML"):
            assert banned not in uat._SCRIPT, (
                f"{banned} in the uat script; a rebuild leaves boxes/notes holding orphans, "
                "so ticks on rebuilt rows reach neither a listener nor storage")

    # Only these may appear after `boxes`/`notes`. A WHITELIST on purpose: the first version of
    # this guard banned reassignment, and the Step-11 reviewers walked straight past it with
    # `boxes.splice(0, 1)` — in-place narrowing needs no assignment at all. Every blacklist here
    # has been beaten by the next reviewer, so the question is inverted: anything not known to
    # be read-only fails, and widening the list is a deliberate edit with this comment attached.
    _READ_ONLY_USES = (r"\.forEach\(", r"\.filter\(", r"\.map\(", r"\.slice\(",
                       r"\.indexOf\(", r"\.length(?!\s*=)")

    def test_the_snapshot_arrays_are_only_ever_read(self):
        """`save()` writes the blob from `boxes`/`notes`, so anything that shortens either one
        drops the missing items' answers on the next save — no DOM edit required. Narrowing is
        the cheap way to cause exactly the loss this class exists to prevent."""
        from render.templates import uat
        # Scan CODE only. Two things in this script mention the arrays without touching them:
        # the prose above `applyFilter` explaining why they must not be narrowed, and the
        # export's user-facing sentence about what notes do not support. Both are text. The
        # comment trap has now caught four checks in this issue, so both comments AND string
        # literals come out before the scan, at the top of the guard rather than by rewording
        # the English. (Checked: no `//` appears inside a string literal here, so stripping
        # line comments first cannot eat real code.)
        _src = re.sub(r"/\*.*?\*/", "", uat._SCRIPT, flags=re.S)
        _src = re.sub(r"//[^\n]*", "", _src)
        body = re.sub(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"", "''", _src)
        allowed = "|".join(self._READ_ONLY_USES)
        for name in ("boxes", "notes"):
            assert body.count(f"var {name} =") == 1, f"{name} must be declared exactly once"
            for m in re.finditer(rf"(?<![\w$.]){name}(?![\w$])", body):
                before = body[:m.start()].rstrip()
                if before.endswith("var"):
                    continue                      # the single capture
                tail = body[m.end():]
                assert re.match(allowed, tail), (
                    f"{name} is used in a way this guard cannot prove is read-only: "
                    f"{body[m.start():m.end() + 24]!r}. If it really is safe, add it to "
                    "_READ_ONLY_USES deliberately.")

    def test_the_guard_above_is_not_vacuous(self):
        """A whitelist that matched everything would be silently useless."""
        allowed = "|".join(self._READ_ONLY_USES)
        for hostile in (".splice(0, 1)", ".pop()", ".shift()", ".length = 0",
                        " = boxes.filter(function(){})", ".reverse()"):
            assert not re.match(allowed, hostile), hostile

    def test_the_filter_reads_state_the_renderer_actually_emits(self):
        """A filter keyed on a class the checklist never emits is a no-op that still
        looks right in review. Both dimensions are checked against real output."""
        h = _body(_render("```steps\na.one | One | d | must\n```\n"))
        assert 'type="checkbox"' in h, "state filter needs a checkbox to key on"
        assert "blk-level is-must" in h, "level filter needs the level class to key on"

    def test_emptying_the_view_is_announced_and_not_merely_drawn(self):
        """Hiding every item leaves a checklist that looks like it lost its content. Sighted
        users get the message; without a status role nobody else does."""
        h = _body(_render())
        m = re.search(r'<span class="ut-fnone"[^>]*>', h)
        assert m, "no empty-state message in the toolbar"
        assert 'role="status"' in m.group(0), m.group(0)
        assert "hidden" in m.group(0), "the message must start hidden"

    def test_each_filter_dimension_is_its_own_labelled_group(self):
        """One `role="group"` around both dimensions announces "Any" with nothing to say
        which dimension it belongs to — a Step-8a finding."""
        h = _body(_render())
        groups = re.findall(r'<div class="ut-fgroup"[^>]*>', h)
        assert len(groups) == 2, groups
        for g in groups:
            ref = re.search(r'aria-labelledby="([^"]+)"', g)
            assert ref, f"group without a programmatic label: {g}"
            assert f'id="{ref.group(1)}"' in h, f"{ref.group(1)} labels nothing that exists"


class TestBoardTreatment:
    """#40 T8. The card treatment layers onto a template that already styled `.ut-item` as a
    divider list, and the two idioms collide in ways a green suite did not notice."""

    def _css(self):
        from render import templates
        return re.sub(r"/\*.*?\*/", "", templates.CSS["uat"], flags=re.S)

    def test_the_first_card_in_a_board_keeps_its_top_border(self):
        """`.tpl-uat .ut-item:first-child{border-top:0}` is the pre-existing divider idiom.
        It has the SAME specificity as `.tpl-uat .ut-board .ut-item` and sits later in the
        sheet, so before the fix the first card of every checklist had an open top edge —
        measured in Chromium as 0px top against 1px on the other three sides."""
        rules = [r for r in self._css().split("}")
                 if ".ut-item" in r.split("{")[0] and ":first-child" in r.split("{")[0]]
        assert rules, "the divider idiom vanished; this guard is now vacuous"
        scoped = [r for r in rules if ".ut-board" in r.split("{")[0]]
        assert scoped, ("no board-scoped :first-child rule, so the unscoped divider reset "
                        "zeroes the first card's top edge inside a board")
        assert "border-top:1px" in scoped[-1].split("{", 1)[1], scoped[-1]

    def test_the_board_marker_lands_on_the_steps_wrapper(self):
        """The shared marker suite only proves `ut-board` appears somewhere on the page, so
        moving it onto the static toolbar would keep that suite green while every checklist
        silently lost its cards — a Step-8a finding."""
        h = _body(_render("```steps\na.one | One | d | must\n```\n"))
        wrapper = re.search(r'<div class="blk blk-steps([^"]*)"', h)
        assert wrapper, "no steps fence wrapper rendered"
        assert "ut-board" in wrapper.group(1), wrapper.group(0)

    def test_only_the_sections_own_heading_gets_the_column_dot(self):
        """An authored `### …` is also a direct child of `.ut-step`, so a bare `>h3` gave it
        the dot and the flex layout too — confirmed in Chromium before the fix."""
        css = self._css()
        # EVERY rule reaching the section heading, not just the `::before` that draws the dot.
        # Scoping only the pseudo-element still handed the authored heading the flex layout,
        # and an earlier version of this test checked the `::before` alone and so passed that
        # exact mutation.
        rules = [r for r in css.split("}") if ".ut-step>h3" in r.split("{")[0]]
        assert len(rules) >= 2, f"expected the layout rule and its ::before, got {rules!r}"
        for r in rules:
            assert ":first-of-type" in r.split("{")[0], (
                f"unscoped heading rule decorates authored subheadings too: {r!r}")


class TestEscapeFirstStillHolds:
    HOSTILE = ("```steps\n"
               "x | <script>alert(1)</script> | \" onerror=alert(1)\n"
               "```\n")

    def test_a_hostile_item_is_inert(self):
        h = _body(_render(self.HOSTILE))
        # the template's OWN script is legitimate; the author's must be escaped.
        assert "<script>alert(1)</script>" not in h
        assert "&lt;script&gt;" in h

    def test_a_hostile_id_cannot_break_out_of_its_attribute(self):
        """The id is NOT slug-validated — `install.clone` must stay legal — so escaping is
        the whole protection. It is sufficient: the quote becomes an entity, so the value
        cannot terminate early and `onmouseover` never becomes an attribute."""
        h = _body(_render('```steps\na" onmouseover="x | One | y\n```\n'))
        assert 'data-k="a&quot; onmouseover=&quot;x"' in h
        # A regex over raw text CANNOT settle this — `[^>]*` reads straight through
        # `&quot;`, so it sees `onmouseover=` inside the value and calls it an attribute.
        # Parse it the way a browser does and ask for the real attribute set.
        from html.parser import HTMLParser

        class _Attrs(HTMLParser):
            found = None

            def handle_starttag(self, tag, attrs):
                # The AUTHOR-DERIVED input, identified by `data-k`, not simply the first
                # <input> on the page. #40 T8 added a template-owned filter toolbar of
                # radios ahead of the checklist, and those carry no author text at all —
                # taking the first input would have tested the wrong element. The guard
                # itself is unchanged: it still parses the real DOM and still demands an
                # EXACT attribute set on the input built from the hostile id.
                d = dict(attrs)
                if tag == "input" and self.found is None and "data-k" in d:
                    self.found = d

        p = _Attrs()
        p.feed(h)
        assert p.found is not None, "no author-derived <input> parsed; the rest would be vacuous"
        assert set(p.found) == {"type", "data-k"}, p.found
        assert p.found["data-k"] == 'a" onmouseover="x'   # inert text, one attribute


class TestSaveMergesRatherThanReplaces:
    """#59. `save()` rebuilt the whole blob from this page's inputs, so every stored key
    whose item was not on the page was deleted on the next keystroke — measured 12 keys to
    6 after unticking one box, with nothing on screen to say a note had gone.

    These are text guards over the emitted script, which is what this suite can run; the
    behavioural proof is a headless-Chromium run recorded in the pull request. Written to
    fail on the SHAPE of the old bug rather than on a phrase, so a refactor that reverts to
    replace-semantics still trips them.
    """

    def _script(self):
        return re.findall(r"<script>(.*?)</script>", _render(), re.S)[0]

    def test_save_seeds_from_stored_state_before_writing(self):
        body = re.search(r"function save\(\)\{(.*?)\n  \}", self._script(), re.S)
        assert body, "save() not found"
        body = body.group(1)
        assert "getItem(KEY)" in body, (
            "save() never reads existing storage, so it cannot merge — this is the #59 bug")
        # Ordering is the actual contract: the read must precede the writes, or the merge is
        # a no-op that still clobbers.
        assert body.index("getItem(KEY)") < body.index("boxes.forEach"), (
            "save() reads storage AFTER rebuilding from the page — that still replaces")

    def test_save_does_not_start_from_an_empty_object_it_then_writes(self):
        """The literal shape of the defect: `var st = {}` followed by a write with nothing
        merged in between."""
        body = re.search(r"function save\(\)\{(.*?)\n  \}", self._script(), re.S).group(1)
        between = body[body.index("var st = {}"):body.index("boxes.forEach")]
        assert "getItem" in between, (
            "nothing is merged between initialising st and rebuilding it from the page")

    def test_a_concurrent_tab_is_not_clobbered(self):
        """Re-reading at save time rather than reusing the load-time snapshot is what makes
        two tabs on one doc-id survive each other."""
        body = re.search(r"function save\(\)\{(.*?)\n  \}", self._script(), re.S).group(1)
        assert "saved[" not in body, (
            "save() merges from the load-time snapshot, so a second tab's writes are lost")

    def test_orphaned_answers_are_reported_not_discarded(self):
        script = self._script()
        assert "function orphans()" in script
        assert "no matching item" in script
        # A blank note is not an orphaned ANSWER — reporting it would bury the real ones.
        assert "trim() !== ''" in script, "an empty stored note must not be reported"

    def test_orphan_ids_are_read_from_storage_not_from_the_page(self):
        """An orphan is by definition a key with no element, so deriving the list from the
        page's own inputs could only ever return nothing."""
        body = re.search(r"function orphans\(\)\{(.*?)\n  \}", self._script(), re.S)
        assert body, "orphans() not found"
        assert "getItem(KEY)" in body.group(1)
