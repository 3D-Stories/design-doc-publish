"""The workflow template — a runbook someone follows under pressure (#41).

`workflow` was the one style with no body: on a PROSE-ONLY source it was tag-for-tag identical
to `plain` (measured 30 tags each), because it declared markers but no `SECTIONS` and no
furniture, and markers only attach to typed blocks. On a source WITH typed blocks the two
already differed (102 vs 273 tags) purely because `plain` renders a fence as a code listing —
so a test that compares the two using the repo's block-carrying fixture is born vacuous. Every
structural test here uses prose.

The design gate ran five passes over this issue and rejected two drafts. Three of the traps it
caught are pinned below, because each would have shipped green:

* a CSS counter whose `counter-increment` is deleted still reports
  `content: counter(wf-stage)` from `getComputedStyle`, while every stage renders `0`;
* the open step "differs" from a closed one in padding and margin whatever the cascade does, so
  a generic computed-style inequality proves nothing about the current-position affordance;
* `BEFORE_BODY` is prepended independently of sectioning, so `workflow != plain` stays true
  after `SECTIONS` is removed.
"""
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render as render_artifact  # noqa: E402

# Four stages, so a per-stage assertion cannot pass by counting globally.
PROSE = """lede paragraph

## Drain the queue

Stop the consumer.

## Restart

Bring it back.

## Verify

Watch the lag.

## Roll back

Only if verify fails.
"""
STAGES = 4

RAIL = """## Execute

```steprail
1 | Stop the writer | systemctl stop writer | action
2 | Confirm the lag is zero | it must read 0 | check
```
"""


def _render(md=PROSE, style="workflow", **kw):
    kw.setdefault("title", "Runbook")
    kw.setdefault("generated_at", "2026-08-02 12:00 MDT")
    return render_artifact.render_artifact(md, style=style, **kw)


def _body(h):
    return h.split("<body", 1)[1]


def _css(style="workflow"):
    """Template CSS with comments stripped. Four checks in this epic were defeated by a
    comment containing the very token they searched for."""
    from render import templates
    return re.sub(r"/\*.*?\*/", "", templates.CSS[style], flags=re.S)


def _rules(css, needle):
    return [r for r in css.split("}") if needle in r.split("{")[0]]


class TestItHasABodyAtAll:
    """AC1. The defect was structural identity with `plain`, so the guard is structural."""

    def test_every_authored_h2_becomes_a_stage_section(self):
        """Wrappers only — this fixture is rail-free, so its stages are deliberately NOT
        numbered (numbering is gated on `:has(.wf-rail)`). Counting wrappers rather than
        asserting "some difference" is what makes removing `SECTIONS` fail."""
        h = _body(_render())
        assert len(re.findall(r'<section class="wf-stage"', h)) == STAGES, h[:400]

    def test_a_stage_keeps_its_h2_and_does_not_get_demoted(self):
        """`render_sections` defaults `heading_tag` to h3, and six other styles take that
        default. A runbook stage is a major division and the shared sizing already says so, so
        workflow passes `heading_tag: "h2"` explicitly. This also keeps the authored heading
        LEVEL unchanged, which is the half of test_template_bodies.py's contract that must not
        move: sectioning is deliberate, demotion would not be."""
        h = _body(_render())
        assert re.search(r'<section class="wf-stage"[^>]*><h2>Drain the queue</h2>', h), h[:400]
        assert "<h3>Drain the queue</h3>" not in h

    def test_a_prose_runbook_is_no_longer_structurally_identical_to_plain(self):
        """The original defect, stated directly. Weaker than the two above — `BEFORE_BODY`
        alone would satisfy it — so it is the corroboration, never the guard."""
        def tags(style):
            return re.findall(r"<(/?[a-zA-Z][\w-]*)", _body(_render(style=style)))
        assert tags("workflow") != tags("plain")


class TestStageNumbering:
    """A runbook is ordered and someone is working down it."""

    # EXACT selectors, not "a rule mentioning the class". A Step-11 reviewer retargeted each
    # of these three at `.no-such` and every substring assertion stayed green while the page
    # rendered `0` for every stage. Pinning the literal selector is the only version that
    # survives that, and widening it is then a deliberate edit.
    RESET = ".tpl-workflow"
    INCREMENT = ".tpl-workflow .wf-stage"
    CONSUMER = ".tpl-workflow:has(.wf-rail) .wf-stage>h2::before"

    def _decls(self, selector):
        for r in _css().split("}"):
            if r.split("{")[0].strip() == selector:
                return r.split("{", 1)[1]
        return None

    def test_the_counter_is_reset_incremented_and_consumed(self):
        """All THREE declarations, on the exact selectors that carry them. A re-gate pass
        measured that deleting `counter-increment` leaves
        `getComputedStyle(h2, "::before").content` reporting `counter(wf-stage)` unchanged
        while every stage renders `0` — so asserting the consumer alone admits a counter that
        counts nothing. T8 shipped the mirror image: a counter incremented and never read."""
        reset = self._decls(self.RESET)
        assert reset and "counter-reset:wf-stage" in reset, reset
        inc = self._decls(self.INCREMENT)
        assert inc and "counter-increment:wf-stage" in inc, inc
        con = self._decls(self.CONSUMER)
        assert con and "content:counter(wf-stage)" in con, con

    def test_the_number_is_separated_from_the_title(self):
        """Bare `content:counter(...)` renders `1Drain the queue`. A design pass named that
        exact string, and a Step-11 reviewer then set the gap to zero and stayed green."""
        con = self._decls(self.CONSUMER)
        m = re.search(r"margin-right:(\d+(?:\.\d+)?)px", con or "")
        assert m and float(m.group(1)) > 0, con


class TestTheKeyOnlyAppearsWhenThereIsARail:
    """`workflow` legitimately renders rail-free pages — it accepts `nodes`, `legend`,
    `callout`, `chips`, `provenance`, and its own docstring calls topology a first-class use.
    An unconditional do/check key above a network diagram is misleading furniture. `uat`'s
    always-on meter is not a precedent: every uat page owns its meter."""

    def test_the_key_is_furniture_the_author_never_writes(self):
        assert _body(_render(RAIL)).count('class="wf-key"') == 1

    def test_the_key_is_hidden_by_default_and_revealed_by_a_rail(self):
        """The reveal must actually restore layout. A Step-11 reviewer swapped the reveal's
        `display:flex` for `color:inherit`, leaving the key permanently hidden, and the old
        "a rule exists without display:none" assertion passed."""
        css = _css()
        hidden = [r for r in _rules(css, ".wf-key") if "display:none" in r]
        assert hidden, "the key must start hidden"
        shown = [r for r in css.split("}")
                 if r.split("{")[0].strip() == ".tpl-workflow:has(.wf-rail) .wf-key"]
        assert shown, "nothing reveals the key when a rail is present"
        assert re.search(r"display:\s*(flex|block|inline-flex)", shown[0].split("{", 1)[1]), \
            shown[0]

    def test_the_key_names_both_kinds_the_rail_can_emit(self):
        """`_SEMANTIC_SETS["step kind"]` is exactly {action, check}, rendered as `do`/`check`
        by shared CSS. A key that explains only one of them is worse than none.

        Word-boundary, not substring: a reviewer changed the visible `do` to `undo` and the
        old `"do" in key` assertion stayed green."""
        from render import blocks
        assert blocks._SEMANTIC_SETS["step kind"] == {"action", "check"}
        key = _body(_render(RAIL)).split('class="wf-key"', 1)[1].split("</div>", 1)[0]
        for word in ("do", "check"):
            assert re.search(rf">\s*{word}\s*<", key), (word, key)


class TestCurrentPositionIsVisible:
    """The design gate's sharpest finding. `workflow.py` used to paint the whole rail spine
    `var(--accent)` — the same colour the shared rule uses to mark the OPEN step — so the
    marker was invisible against its own rail. Two passes measured `2px rgb(15,118,110)` for
    both. The scope-reduction argument that #39 had already delivered this was wrong for
    `workflow` specifically."""

    def test_the_rail_spine_is_not_painted_the_accent(self):
        """ANY border property, not just `border-left-color`. A Step-11 reviewer restored the
        masking with the `border-color` shorthand and the narrower check stayed green."""
        for r in _css().split("}"):
            sel = r.split("{")[0]
            if ".blk-rail" not in sel or "blk-rail-step" in sel:
                continue
            for prop, val in re.findall(r"(border[\w-]*)\s*:\s*([^;]*)", r.split("{", 1)[1]):
                assert "var(--accent)" not in val, (
                    "the spine is painted the same colour the shared rule uses for the OPEN "
                    f"step, which hides it: {sel.strip()} {prop}:{val}")

    def test_the_open_step_carries_a_visible_fill_not_only_a_border(self):
        """A 2px colour change is too subtle to find under pressure, and padding/margin
        already differ between open and closed whatever the cascade does — so a generic
        'they differ' assertion proves nothing. A reviewer set the fill to `transparent` and
        the old `"background:" in decls` check stayed green, so the VALUE is pinned: a real
        token, not a keyword that paints nothing."""
        open_rules = [r for r in _css().split("}")
                      if "details[open]" in r.split("{")[0] and ".tpl-workflow" in r.split("{")[0]]
        assert open_rules, "workflow adds no open-step treatment of its own"
        fills = [m for r in open_rules
                 for m in re.findall(r"background:\s*([^;]+)", r.split("{", 1)[1])]
        assert fills, f"the open step needs a fill, not only a border: {open_rules!r}"
        assert any(f.strip().startswith("var(--") for f in fills), (
            f"the fill must be a real token; transparent/none paints nothing: {fills}")


class TestMarkerScoping:
    """AC2, read literally: a `.tpl-workflow` presence test AND an absence test on other
    styles. The shared MARKERS table covers `wf-rail`, which is a different contract — three
    design passes said so independently."""

    OTHERS = ("plain", "design", "roadmap", "report", "dashboard", "review", "spec",
              "analysis", "uat")

    def _body_classes(self, h):
        m = re.search(r"<body([^>]*)>", h)
        return re.findall(r'class="([^"]*)"', m.group(1) or "")

    def test_a_rail_page_is_scoped_by_tpl_workflow(self):
        """Token-wise on both. A reviewer renamed the marker to `wf-rail-x` — which disables
        the key, the numbering and the open-step treatment, since all three are gated on
        `.wf-rail` — and a substring check happily matched it inside the new name."""
        h = _render(RAIL)
        assert "tpl-workflow" in " ".join(self._body_classes(h)).split()
        classes = set()
        for attr in re.findall(r'class="([^"]*)"', _body(h)):
            classes.update(attr.split())
        assert "wf-rail" in classes, sorted(c for c in classes if c.startswith("wf-"))

    def test_no_other_style_claims_tpl_workflow(self):
        """Token-wise on the body class, not a raw page substring: workflow's own CSS text
        legitimately contains `.tpl-workflow` on every page that ships it."""
        for style in self.OTHERS:
            classes = " ".join(self._body_classes(_render(RAIL, style=style))).split()
            assert "tpl-workflow" not in classes, style


class TestNoScriptAndSelfContained:
    """AC3. The reference builds its entire pipeline in script from an empty
    `<main class="flow">`, and uses `innerHTML` twice — so its construction is rejected
    outright, not adapted. Reveal-on-click here is native `<details>`, which is why this
    template ships no script at all and the engine's inline-script carve-out stays uat-only."""

    def test_workflow_emits_no_script(self):
        """Case-insensitive, and over the WHOLE page rather than the body: HTML tag names are
        case-insensitive, so `<SCRIPT>` executes exactly as `<script>` does, and a Step-11
        reviewer injected one into the head past both the old check and the lint gate (which
        rejects external requests, not scripts, because `uat` needs its carve-out)."""
        assert not re.search(r"<\s*script", _render(RAIL), re.I)

    def test_the_detail_is_in_the_markup_not_built_by_script(self):
        h = _body(_render(RAIL))
        assert "<details" in h
        assert "systemctl stop writer" in h, "step detail must be present with JS disabled"

    def test_no_external_request(self):
        """Either quote style, and protocol-relative too. A reviewer used a single-quoted
        `src` and the double-quote-only pattern missed it."""
        h = _render(RAIL)
        assert not re.search(r"""(?:src|href)\s*=\s*['"]\s*(?:https?:)?//""", h, re.I)
