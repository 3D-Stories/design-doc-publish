"""The eight non-interactive template bodies (#13, wave 3).

The contract this file pins is AC2: **every component carries a marker, and every marker is
present under its own doc type and ABSENT under the other seven.** The absence half is what
makes the markers worth having — a class that leaks into every template distinguishes nothing.

`MARKERS` below is the single source of truth for that pairing. Each entry names the markdown
that produces the marker, so a presence failure points at the construct rather than at a
selector. `plain` is never in this table: it is frozen, and its own guard lives in
`test_byte_identity.py`.
"""
import re
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render as render_artifact  # noqa: E402


TEMPLATES = ("analysis", "roadmap", "report", "design",
             "dashboard", "review", "spec", "workflow", "uat")

# A doc that exercises the shared spine, reused as the base for every fixture.
_SPINE = "# Doc\n\n## First section\n\nSome body text.\n"


def _render(md, style):
    return render_artifact.render_artifact(md, title="T", style=style,
                                           generated_at="2026-08-01 12:00 MDT")


def _fence(tag, body, role=""):
    info = f"{tag} {role}".strip()
    return f"```{info}\n{body}\n```\n"


# marker -> (owning template, markdown that must produce it)
MARKERS = {
    # #39 — the component vocabulary. Every one of these markers' CSS lives in the
    # feature-keyed OPTIONAL layer, so a page that does not use the component is unchanged.
    # That is why `dz-options` can ship here despite `design` being the byte-identity
    # exemplar's style: no options block, no rule, no byte change.
    #
    # #134 CORRECTS THE LAST SENTENCE, which was true of the SHARED rule only. The
    # feature-keyed layer is indeed absent from a page with no options block — but the
    # TEMPLATE layer is not feature-keyed, and `design.py`'s own `.dz-options` rules ship
    # in every `design` page whether or not one is used. Measured: they are in the committed
    # exemplar. So editing `design.py`'s options CSS DOES move the exemplar's bytes, which is
    # why #134 regenerated it. "No options block, no rule" holds for `OPTIONAL_BLOCK_CSS`;
    # it never held for the template module.
    "db-spark":    ("dashboard", "```stats\n1 | a |  | 1,2,3\n```\n"),
    "rp-timeline": ("report", "```timeline\n09:14 | Alert | detail | past\n```\n"),
    "rm-timeline": ("roadmap", "```timeline\n09:14 | Alert | detail | past\n```\n"),
    "wf-rail":     ("workflow", "```steprail\n1 | Fetch | detail | action\n```\n"),
    "dz-options":  ("design", "```options\nA | for | against | chosen\n```\n"),
    # analysis — structural, from the section renderer
    "an-q":        ("analysis", _SPINE),
    "an-answer":   ("analysis", _SPINE),
    "an-conf":     ("analysis", "## Is it measured?\n\nYes — measured on 2026-08-01.\n"),
    "an-index":    ("analysis", _SPINE),
    "an-figure":   ("analysis", _fence("steps", "1 | Split the batch | The hub divides the "
                                                "incoming tasks into roughly equal chunks.")),
    "an-measure":  ("analysis", _fence("callout", "note | Measured on 82 sessions\n"
                                                  "Median fell from 4m12s to 2m48s.",
                                       role="measure")),
    # roadmap
    "rm-epic":     ("roadmap", _SPINE),
    "rm-meter":    ("roadmap", _fence("meter", "Children merged | 3 | 9")),
    "rm-child":    ("roadmap", _fence("chips", "wave 3 | wip")),
    "rm-risk":     ("roadmap", _fence("findings", "high | Sampler drift | Blocks wave 4.")),
    "rm-flow":     ("roadmap", _fence("nodes", "ingest\n  parse | normalises rows | queue",
                                      role="flow")),
    # #68 PR 2 — the phase band: an ordered container with its items nested inside it.
    "rm-phase":    ("roadmap", _fence("phases", "Windows + GPU | 3 of 12 | warn\n"
                                                "  FA-1 | Fan curve stalls | crit")),
    # report
    "rp-section":  ("report", _SPINE),
    "rp-kpi":      ("report", _fence("stats", "82 | sessions read")),
    "rp-bar":      ("report", _fence("stats", "28/44 | highs confirmed")),
    "rp-caveat":   ("report", _fence("callout", "warn | Sampling caveat\nOnly 82 of 155.",
                                     role="caveat")),
    "rp-summary":  ("report", _fence("callout", "note | At a glance\nOne page, three numbers.",
                                     role="summary")),
    "rp-followup": ("report", _fence("steps", "1 | Re-run the sampler | Owner: platform.",
                                     role="followup")),
    # design
    "dz-lead":     ("design", "Lede paragraph before any section.\n\n## Section\n\nbody\n"),
    "dz-compare":  ("design", _fence("nodes", "today\n  one | the current shape",
                                     role="compare")),
    "dz-decision": ("design", _fence("callout", "note | We chose B\nBecause A costs more.",
                                     role="decision")),
    # dashboard
    "db-tldr":     ("dashboard", "Lede paragraph before any section.\n\n## Section\n\nbody\n"),
    "db-statebar": ("dashboard", _fence("chips", "main at 3a85cc5 | done", role="statebar")),
    "db-attention": ("dashboard", _fence("findings", "high | A thing | It broke.")),
    "db-prov":     ("dashboard", _fence("findings",
                                        "high | A thing | It broke. | gh api, PR #15")),
    "db-kpi":      ("dashboard", _fence("stats", "42 | PRs merged | +18% | 40,55,70,100")),
    "db-highlight": ("dashboard", _fence("callout", "note | Search rollout complete\n"
                                                    "Live for 100% of users.", role="highlight")),
    "db-columns":  ("dashboard", _fence("nodes", "Shipped\n  Search ranking v2 | Live for all "
                                                 "users | #PR-2210", role="columns")),
    # review
    "rv-section":  ("review", _SPINE),
    "rv-hypo":     ("review", _fence("chips", "H1 refuted | done", role="hypo")),
    "rv-sev":      ("review", _fence("findings", "high | A thing | It broke.")),
    "rv-weakest":  ("review", _fence("callout", "warn | The claim most likely to be wrong\nThis one.",
                                     role="weakest")),
    "rv-riskmap":  ("review", _fence("findings", "high | src/hooks/useOptimisticTasks.ts | "
                                                 "worth opening first | +52 -0",
                                     role="riskmap")),
    # spec
    "sp-section":  ("spec", _SPINE),
    "sp-req":      ("spec", _fence("steps", "R1 | The client MUST retry | Once, with backoff.",
                                   role="req")),
    "sp-ac":       ("spec", _fence("steps", "1 | Suite green | Whole gate, exit 0.", role="ac")),
    "sp-gate":     ("spec", _fence("chips", "tests | done", role="gate")),
    "sp-index":    ("spec", _SPINE),
    # workflow
    "wf-node":     ("workflow", _fence("nodes", "router\n  host-a | 2x Xeon | 10G Cat6a")),
    "wf-edge":     ("workflow", _fence("nodes", "router\n  host-a | 2x Xeon | 10G Cat6a")),
    "wf-legend":   ("workflow", _fence("legend", "solid | an existing link")),
    "wf-inset":    ("workflow", _fence("callout", "note | What this means\nOne uplink only.",
                                       role="inset")),
    # uat (#18) — the only interactive template
    "ut-step":     ("uat", _SPINE),
    "ut-item":     ("uat", _fence("steps", "install.clone | Clone the repo | git clone ...")),
    "ut-note":     ("uat", _fence("steps", "install.clone | Clone the repo | git clone ...")),
    "ut-stop":     ("uat", _fence("callout", "stop | Do not continue\nA broken install "
                                             "invalidates the run.", role="stop")),
    "ut-meter":    ("uat", _SPINE),
    "ut-export":   ("uat", _SPINE),
    "ut-filter":   ("uat", _SPINE),
    "ut-board":    ("uat", _fence("steps", "install.clone | Clone the repo | git clone ...")),
}


def _body(html):
    """The rendered BODY only. Every absence assertion must go through this: BLOCK_CSS
    names `.blk-bar` and `.blk-prov`, so "not in the page" is true of neither."""
    return html.split("<body", 1)[1]


def _emitted(html):
    """Every class token that appears in a class="…" attribute of the BODY.

    Scoped to the body so a CSS rule mentioning a marker cannot masquerade as an emitted
    element — the absence half of AC2 is worthless if a stylesheet satisfies it.
    """
    body = _body(html)
    tokens = set()
    for attr in re.findall(r'class="([^"]*)"', body):
        tokens.update(attr.split())
    return tokens


class TestMarkerPresence:
    @pytest.mark.parametrize("marker", sorted(MARKERS))
    def test_marker_is_emitted_by_its_own_template(self, marker):
        owner, md = MARKERS[marker]
        assert marker in _emitted(_render(md, owner)), (
            f"{marker} is not emitted by --style {owner} for:\n{md}")

    @pytest.mark.parametrize("marker", sorted(MARKERS))
    def test_marker_is_absent_from_every_other_template(self, marker):
        owner, md = MARKERS[marker]
        for other in TEMPLATES:
            if other == owner:
                continue
            assert marker not in _emitted(_render(md, other)), (
                f"{marker} leaked into --style {other}; it belongs to {owner} alone")

    @pytest.mark.parametrize("marker", sorted(MARKERS))
    def test_marker_never_reaches_plain(self, marker):
        _owner, md = MARKERS[marker]
        assert marker not in _render(md, "plain")


def _selectors_containing(css, marker):
    """Every individual SELECTOR mentioning `marker`, split out of its rule and its
    comma-separated selector list.

    A prefix-window heuristic is not enough: `.tpl-design .dz-options,.dz-options{…}`
    puts a scoped selector within 60 characters of an unscoped one, so a windowed check
    passes while the second selector still applies to every template.
    """
    out = []
    for rule in css.split("}"):
        head = rule.split("{")[0]
        if marker not in head:
            continue
        out.extend(sel.strip() for sel in head.split(",") if marker in sel)
    return out


def _shared_css_layers():
    """Every CSS string that is NOT owned by one template.

    `OPTIONAL_BLOCK_CSS` is the obvious one, but not the only one: `_COMPONENT_STYLE` and
    `BLOCK_CSS` go into every rich template and `_STYLE` into every page including `plain`
    (`render/__init__.py`), so a `.tpl-*` rule parked in any of them would escape a check
    scoped to the optional layer.
    """
    from render import blocks
    layers = {f"OPTIONAL_BLOCK_CSS[{f!r}]": c
              for f, c in blocks.OPTIONAL_BLOCK_CSS.items()}
    layers["BLOCK_CSS"] = blocks.BLOCK_CSS
    layers["_STYLE"] = render_artifact._STYLE
    layers["_COMPONENT_STYLE"] = render_artifact._COMPONENT_STYLE
    layers["_ROADMAP_STYLE"] = render_artifact._ROADMAP_STYLE
    return layers


class TestCssLivesInItsOwnTemplate:
    """A rule naming one template belongs in that template's module, where its blast radius
    is what it looks like.

    #39 put per-template marker rules in the SHARED feature layer, and `optional_css` appends
    each whole feature string to every page using that feature. So
    `OPTIONAL_BLOCK_CSS["timeline"]` carried report's rule AND roadmap's rule together: editing
    report's margin moved every roadmap page with a timeline, and *deleting* it moved all nine
    rich styles at once.

    Measured before this migration: an `analysis` page shipped four rules it can never match
    (`.tpl-dashboard`, `.tpl-design`, `.tpl-report`, `.tpl-roadmap`) — inert, because a rich
    page carries exactly one body class, but still bytes. This moved them home.
    """

    def test_no_template_rule_is_left_in_a_shared_layer(self):
        """A RAW SUBSTRING check, deliberately, and deliberately the only one.

        A selector-level version using `_selectors_containing` was written first and then
        deleted: it reads only the text before the first `{` of each `}`-split chunk, so a rule
        inside `@media(min-width:720px){…}` is invisible to it — and `design.py` already uses a
        nested `@media`, so that form is realistic here. It also could not add the
        unscoped-sibling detection it was supposed to: `_selectors_containing` keeps only
        selectors CONTAINING the marker it is passed, and passing `.tpl-<name>` therefore
        returns the scoped selector and never its bare sibling. Against the `.tpl-` marker it
        found strictly less than this line does.

        The unscoped-sibling case is real and IS covered — by
        `test_template_css_is_absent_from_the_other_templates`, which passes the MARKER
        (`.dz-options`) rather than `.tpl-*`. That is where the comma-splitting earns its keep.
        """
        offenders = {}
        for where, css in _shared_css_layers().items():
            for name in TEMPLATES:
                if f".tpl-{name}" in css:
                    offenders.setdefault(name, []).append(where)
        assert not offenders, (
            "template-specific CSS found in a shared layer — move it into the template's "
            f"own module: {offenders}")


class TestEveryTemplateIsReal:
    @pytest.mark.parametrize("name", TEMPLATES)
    def test_template_is_registered_and_stamps_its_body_class(self, name):
        assert name in render_artifact._TEMPLATES
        assert f'class="tpl-{name}"' in _render(_SPINE, name)

    @pytest.mark.parametrize("name", TEMPLATES)
    def test_template_ships_css_for_every_marker_it_owns(self, name):
        """A marker with no rule is a class nobody styled — the #17 gap, repeated."""
        for marker, (owner, md) in MARKERS.items():
            if owner != name:
                continue
            # #39: render the marker's OWN source, not a blockless spine. A component whose
            # CSS is conditional (emitted only when it renders) can never satisfy a spine
            # render — and demanding a spine render is what silently forces every marker's
            # CSS to be unconditional, which changes pages that do not use the component.
            css = _render(md, name).split("<style>")[1].split("</style>")[0]
            # Comments stripped first: a rule can be deleted and a `/* .ut-board … */` note
            # left behind, and this assertion would stay green. That is the FOURTH time this
            # issue has shipped a check defeated by a comment containing its own search token
            # (the analysis table test, the spec <details> count, the uat filter guard, here),
            # so it is stripped at the source rather than patched per test.
            css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
            assert f".{marker}" in css, f"{name} emits .{marker} but ships no CSS rule for it"

    @pytest.mark.parametrize("name", TEMPLATES)
    def test_template_css_is_absent_from_the_other_templates(self, name):
        mine = {m for m, (o, _) in MARKERS.items() if o == name}
        for other in TEMPLATES:
            if other == name:
                continue
            for marker in mine:
                md = MARKERS[marker][1]
                css = _render(md, other).split("<style>")[1].split("</style>")[0]
                # #39: a component's marker rules now ship in the SHARED feature-keyed
                # optional layer, so the rule TEXT is present on any page using that
                # component, whatever its style. What must never happen is the rule
                # APPLYING elsewhere — so require every occurrence to be scoped by its
                # owner's `.tpl-` selector, which makes it inert on another template.
                for sel in _selectors_containing(css, f".{marker}"):
                    assert f".tpl-{name}" in sel, (
                        f"{name}'s .{marker} is unscoped in {other}: {sel!r}")


class TestBlockStylesheet:
    """#17 shipped the block engine with NO stylesheet — every component rendered as
    unstyled stacked text. That gap is this wave's, and this is its guard."""

    BLOCK_CLASSES = ("blk-stats", "blk-verdict", "blk-chips", "blk-callout", "blk-legend",
                     "blk-meter", "blk-findings", "blk-steps", "blk-nodes", "blk-provenance")

    @pytest.mark.parametrize("cls", BLOCK_CLASSES)
    def test_every_block_component_has_a_rule(self, cls):
        css = _render(_SPINE, "design").split("<style>")[1].split("</style>")[0]
        assert f".{cls}" in css

    def test_plain_ships_no_block_css(self):
        css = _render(_SPINE, "plain").split("<style>")[1].split("</style>")[0]
        assert ".blk" not in css


class TestFenceRoleCompatibility:
    """The role is a SECOND word on a fence info string. Before #13 every word after the
    first was silently discarded, so the compatibility boundary needs pinning in all four
    directions — a template with no role map must not start warning."""

    def test_no_role_map_ignores_a_suffix_silently(self, capsys):
        from render import blocks
        out = blocks.render_block("chips", "a | done", markers=None, role="statebar")
        assert 'class="blk blk-chips"' in out
        assert capsys.readouterr().err == ""

    def test_unlisted_role_warns_but_still_renders_the_block(self, capsys):
        from render import blocks
        out = blocks.render_block("chips", "a | done",
                                  markers={"chips": "rm-child"}, role="nonsense")
        assert "blk-chips" in out and ">a<" in out       # content survives
        assert "rm-child" not in out                      # the no-role slot is NOT used
        assert "nonsense" in capsys.readouterr().err

    def test_a_third_word_warns_on_a_block_but_not_on_a_language_fence(self, capsys):
        from render import blocks
        blocks.render_fence("chips extra words", "a | done", markers={"chips": "x"})
        assert "only the" in capsys.readouterr().err
        blocks.render_fence('js title="x" more', "const a = 1", markers={"chips": "x"})
        assert capsys.readouterr().err == ""

    def test_plain_never_invokes_the_block_engine(self, monkeypatch):
        """Asserting the OUTPUT lacks a marker would also pass if the engine ran and
        found no map. Assert the engine was not called at all."""
        from render import blocks
        called = []
        monkeypatch.setattr(blocks, "render_fence",
                            lambda *a, **k: called.append(a) or None)
        _render(_fence("stats", "1 | one"), "plain")
        assert called == []
        _render(_fence("stats", "1 | one"), "report")
        assert called, "a rich template must still reach the block engine"


class TestChipResolvers:
    """`status_chip` takes one argument; the heading-versus-body precedence always lived
    in the caller. `roadmap_status_chip` is where it moved, so it carries the tests."""

    def test_definitive_heading_wins(self):
        assert render_artifact.roadmap_status_chip("Slot 1 — DONE", "still planning") \
            == ("c-conf", "DONE")

    def test_definitive_body_beats_a_neutral_heading(self):
        # the "Next.js" trap: an incidental neutral keyword must not suppress a real state
        cls, _label = render_artifact.roadmap_status_chip("Next.js migration", "it shipped")
        assert cls == "c-conf"

    def test_neutral_heading_and_neutral_body_keep_the_heading_label(self):
        assert render_artifact.roadmap_status_chip("Some work", "some prose") \
            == ("c-plan", "—")

    def test_confidence_is_unstated_rather_than_inferred_when_absent(self):
        """A missing confidence claim is not an inferred one — saying so would put words
        in the author's mouth on a page whose whole point is confirmed-vs-inferred."""
        assert render_artifact.confidence_chip("A question", "an answer")[0] == "c-unstated"


class TestGrammarExtensions:
    def test_nodes_third_field_is_the_edge_and_tilde_marks_it_proposed(self):
        h = _render(_fence("nodes", "router\n  host-a | 2x Xeon | 25G DAC ~"), "workflow")
        assert 'class="blk-edge wf-edge is-proposed"' in h
        assert ">25G DAC<" in h, "the ~ marks state; it must not survive as visible text"

    def test_existing_one_and_two_field_nodes_are_unchanged(self):
        h = _body(_render(_fence("nodes", "render\n  markdown | the parser"), "workflow"))
        assert "blk-edge" not in h
        assert ">markdown<" in h and ">the parser<" in h

    def test_findings_fourth_field_is_the_provenance_tail(self):
        h = _render(_fence("findings", "high | A thing | It broke. | gh api"), "dashboard")
        assert 'class="blk-prov db-prov"' in h and ">gh api<" in h

    def test_findings_without_a_tail_renders_as_before(self):
        assert "blk-prov" not in _body(
            _render(_fence("findings", "high | A | B."), "dashboard"))

    def test_stats_bar_only_for_proportional_values(self):
        assert "blk-bar" in _body(_render(_fence("stats", "28/44 | confirmed"), "report"))
        assert "blk-bar" not in _body(_render(_fence("stats", "82 | sessions"), "report"))

    def test_stats_bar_width_is_the_proportion(self):
        assert "width:50.0%" in _render(_fence("stats", "22/44 | half"), "report")

    def test_a_zero_denominator_draws_no_bar_rather_than_dividing(self):
        assert "blk-bar" not in _body(
            _render(_fence("stats", "5/0 | impossible"), "report"))


class TestMarkerValuesAreTrusted:
    def test_marker_values_are_slugs(self):
        """Defence in depth: a marker value goes straight into a class attribute, so the
        static maps may only ever hold slugs. Author text reaches a ROLE, never a value."""
        from render import templates
        for name, markers in templates.MARKERS.items():
            for slot, cls in markers.items():
                assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", cls), (name, slot, cls)

    def test_no_two_templates_claim_the_same_marker(self):
        from render import templates
        seen = {}
        for name, markers in templates.MARKERS.items():
            for cls in markers.values():
                assert cls not in seen, f"{cls} claimed by both {seen[cls]} and {name}"
                seen[cls] = name


class TestDocTypeContract:
    """`DOC_TYPE_TAGS` and the component-set table in `design-language.md` are two
    statements of the same contract, so they are compared rather than both trusted.
    Wave 2's map had drifted from the spec in BOTH directions and nobody noticed until a
    real page of each type was rendered."""

    DOC = (SCRIPTS.parent / "docs" / "design-language.md")

    def test_doc_type_tags_match_the_documented_sets(self):
        from render import blocks
        doc = self.DOC.read_text(encoding="utf-8")
        # The choose-it table only — the markers table below it also starts its rows with
        # a template name, and its last column holds ROLE words, not component names.
        table = doc.split("## Doc types")[1].split("### Markers")[0]
        row = re.compile(r"^\| `(" + "|".join(TEMPLATES) + r")` \|.*\|([^|]*)\|\s*$", re.M)
        found = {}
        for m in row.finditer(table):
            found[m.group(1)] = set(re.findall(r"`(\w+)`", m.group(2)))
        assert set(found) == set(TEMPLATES), (
            f"design-language.md documents component sets for {sorted(found)}, "
            f"not {sorted(TEMPLATES)}")
        for name, documented in found.items():
            assert blocks.DOC_TYPE_TAGS[name] == documented, (
                f"{name}: code accepts {sorted(blocks.DOC_TYPE_TAGS[name])}, "
                f"design-language.md documents {sorted(documented)}")

    @pytest.mark.parametrize("marker", sorted(MARKERS))
    def test_no_marker_fixture_uses_a_block_its_type_rejects(self, marker, capsys):
        """A fixture that trips the not-accepted warning is testing a page no author
        should write — which would hide a genuine contract error behind noise."""
        owner, md = MARKERS[marker]
        _render(md, owner)
        assert "is not accepted by doc type" not in capsys.readouterr().err


class TestStep11Fixes:
    """Seven defects the pre-PR review found, each reproduced before it was fixed.
    Every test here failed on commit a481dfb."""

    def test_decorators_reach_typed_block_cells(self):
        """F1 (High): typed fences bypass `inline_fn`, so a `steps req` row promising a
        MUST chip rendered bare text. The marker test passed vacuously — it only asked
        for `.sp-req`, never for the chip the template's own docstring promises."""
        assert 'class="req req-must"' in _render(
            _fence("steps", "R1 | The client MUST retry | Once.", role="req"), "spec")
        assert 'class="sev sev-high"' in _render(
            _fence("findings", "high | X | Severity: High here."), "review")
        # `stats` is deliberately NOT decorated: its cells are a numeral and a label,
        # and the numeral is what the proportional-bar parser reads.
        assert "score" not in _body(_render(_fence("stats", "3/5 | fidelity"), "report"))

    def test_a_decorator_never_reaches_a_cell_that_becomes_a_class_token(self):
        """The other half of F1: decorating a severity or tone would put markup where
        `_token` expects a slug."""
        h = _body(_render(_fence("findings", "high | MUST ship | body."), "spec"))
        assert 'class="blk-finding is-high"' in h

    def test_a_before_after_pair_grids_from_one_block(self):
        """F2 (High): the grid was on the block wrapper, which has exactly one child, so
        two `nodes` fences could never sit side by side. The pair is two ROOTS in one
        block, so the grid belongs on the top-level list."""
        for style, marker in (("design", ".dz-compare>ul"), ("workflow", ".wf-node>ul")):
            css = _render(_SPINE, style).split("<style>")[1].split("</style>")[0]
            assert f"{marker}{{grid-template-columns:1fr 1fr}}" in css, style
        assert ".blk-nodes>ul{display:grid" in _render(_SPINE, "design")

    @pytest.mark.parametrize("style,marker", [
        ("design", "dz-decision"), ("report", "rp-caveat"),
        ("review", "rv-weakest"), ("workflow", "wf-inset"),
    ])
    def test_role_callout_rules_target_the_element_that_carries_the_border(self, style, marker):
        """F3 (Medium): the marker lands on the OUTER wrapper, but the bordered, filled
        element is the nested `.blk-callout`. Every role-callout rule styled a node with
        no border, behind a child that covered its background."""
        css = _render(_SPINE, style).split("<style>")[1].split("</style>")[0]
        assert f".{marker}>.blk-callout{{" in css

    def test_one_block_serves_two_review_components_without_colliding(self, capsys):
        """#40 T4: `review` maps `findings` TWICE — bare for the ranked cards, role
        `riskmap` for the risk map. The whole design rests on a bare tag key and a role
        key coexisting in one marker map, so it is pinned rather than assumed: each fence
        must get its OWN marker, neither may get the other's, and neither may warn.

        This replaced the risk map's first mapping onto `nodes`, which needed a new
        accepted tag; both pre-PR reviewers blocked that and `findings` carries a field
        more (the counts) with the severity tokenised.
        """
        h = _render(_fence("findings", "high | src/a.ts | worth opening | +52 -0",
                           role="riskmap")
                    + _fence("findings", "critical | A real finding | It broke."), "review")
        assert 'class="blk blk-findings rv-riskmap"' in h
        assert 'class="blk blk-findings rv-sev"' in h
        assert "rv-riskmap rv-sev" not in h and "rv-sev rv-riskmap" not in h
        assert capsys.readouterr().err == ""

    def test_every_documented_severity_colours_the_finding_card_border(self):
        """The card's left border is the reference's severity signal, so a level the
        grammar documents may not fall through to the neutral line colour — `low` did."""
        css = _render(_SPINE, "review").split("<style>")[1].split("</style>")[0]
        for level in ("critical", "high", "medium", "low"):
            assert f".tpl-review .rv-sev .is-{level}{{border-left-color:" in css, level

    def test_every_kpi_tile_child_is_ordered_including_the_proportional_bar(self):
        """#40 T5. `db-kpi` makes the tile a flex COLUMN and hand-orders its children, so
        any child left without an `order` falls to the default 0 and jumps ahead of all of
        them. `.blk-bar` — emitted only for a proportional value like `28/44` — was missed,
        which put the bar above the label on a `dashboard` stats form that already worked.
        Found in review, reproduced, then fixed. Every child the renderer can emit into a
        tile is pinned here, so the next added one cannot repeat it silently."""
        css = _render(_fence("stats", "28/44 | highs confirmed | +2 | 1,2,3"),
                      "dashboard").split("<style>")[1].split("</style>")[0]
        orders = {}
        for child in ("blk-label", "blk-value", "blk-delta", "blk-bar", "blk-spark"):
            m = re.search(rf"\.tpl-dashboard \.db-kpi \.{child}\{{([^}}]*)\}}", css)
            assert m, f"{child} has no .db-kpi rule, so it defaults to order 0"
            o = re.search(r"order:(\d+)", m.group(1))
            assert o, f"{child} has a .db-kpi rule but no explicit order"
            orders[child] = int(o.group(1))
        assert orders["blk-label"] < orders["blk-value"] < orders["blk-delta"], orders
        assert orders["blk-bar"] > orders["blk-delta"], (
            f"the proportional bar must follow the text fields, not lead them: {orders}")
        assert len(set(orders.values())) == len(orders), f"duplicate orders: {orders}"

    def test_the_analysis_comparison_table_is_styled_and_stays_in_its_template(self):
        """#40 T6. `analysis`'s comparison table is a plain markdown table — the renderer
        emits no wrapper for one, so it has no marker class and cannot ride the MARKERS
        table like every other component. AC1 still applies, so its presence-and-absence
        pair is asserted directly: the rule exists, it is scoped to `.tpl-analysis`, and
        it does not leak into another style. Inventing a wrapper instead would be a
        renderer change moving every style's bytes.
        """
        md = ("| Dimension | Single worker | Fan-out |\n| --- | --- | --- |\n"
              "| Wall-clock | Grows with the batch | Falls toward O(N/W) |\n")
        html = _render(md, "analysis")
        body = _body(html)
        assert "<table>" in body, "a markdown table must still render"
        css = html.split("<style>")[1].split("</style>")[0]

        # Assert against the DOM the renderer really emits, not just selector text. The
        # first version of this test checked only that selector STRINGS were present, and
        # blessed `.tpl-analysis tbody th` — dead, because markdown emits every body cell
        # as `<td>`. Both reviewers caught it.
        tbody = re.search(r"<tbody>.*?</tbody>", body, re.S).group(0)
        assert "<th" not in tbody, (
            "markdown now emits <th> in tbody; the row-header selector should be revisited")
        assert re.search(r"<thead>.*?<th[ >]", body, re.S), "no header cell to style"

        # Comments are STRIPPED before any selector is parsed. Without that, prose inside
        # a `/* … */` block counts as selector text — this template's own comment mentions
        # `thead`, which silently defeated the "styles the table element itself" check.
        bare = re.sub(r"/\*.*?\*/", "", css, flags=re.S)

        # EVERY shipped rule, not a sample: a fourth (`tbody tr:nth-child(even)`) was
        # missing from the first version and could be deleted with the test still green.
        shipped = [r.split("{")[0].strip() for r in bare.split("}")
                   if ".tpl-analysis" in r.split("{")[0] and "table" in r.split("{")[0]]
        for fragment in ("thead th", "tbody td:first-child", "tbody tr:nth-child(even)"):
            assert any(fragment in sel for sel in shipped), (
                f"analysis ships no comparison-table rule for `{fragment}`")
        assert any("thead" not in sel and "tbody" not in sel for sel in shipped), (
            "no rule styles the table element itself")

        # The renderer appends its OWN tables (`table.gates`, `table.telemetry`) inside
        # <main>, so every comparison rule must exclude them or it restyles unrelated
        # furniture — a leak the cross-style gate cannot see, because it stays in-style.
        for sel in shipped:
            assert ":not(.telemetry)" in sel and ":not(.gates)" in sel, (
                f"this rule also matches the renderer's own tables: {sel!r}")

        # Absence: the presentation must not be reachable under another template. The
        # previous form searched for selectors CONTAINING `.tpl-analysis table` and then
        # asserted they contained `.tpl-analysis` — tautological, with no failure path.
        for other in TEMPLATES:
            if other == "analysis":
                continue
            other_css = _render(md, other).split("<style>")[1].split("</style>")[0]
            other_bare = re.sub(r"/\*.*?\*/", "", other_css, flags=re.S)
            for sel in (s for r in other_bare.split("}") for s in r.split("{")[0].split(",")):
                if "table" in sel and ":not(.telemetry)" in sel:
                    assert ".tpl-analysis" in sel, (
                        f"analysis's comparison-table presentation reaches {other}: {sel!r}")

    def test_requirement_cards_share_one_gutter_width_whatever_the_level(self):
        """#40 T7. The ID and the RFC-2119 level pill share column one of a requirement
        card. On `auto` that column is sized by the pill's WORD — measured 44px for MUST,
        60px for SHOULD, 36px for MAY — so every card's title started at a different x.
        A fixed gutter is the fix; this pins it so `auto` cannot creep back."""
        # ALL FIVE accepted levels, not a sample. `_SEMANTIC_SETS["requirement level"]` is
        # the authority, so it is read rather than restated — a level added there without a
        # wider gutter should fail here.
        from render import blocks
        levels = sorted(blocks._SEMANTIC_SETS["requirement level"])
        md = _fence("steps", "\n".join(
            f"R{i} | The client {lv.upper()} do it | Detail. | {lv}"
            for i, lv in enumerate(levels, 1)), role="req")
        html = _render(md, "spec")
        assert len(re.findall(r'class="blk-level', html)) == len(levels), (
            "every accepted level must render a pill")
        css = html.split("<style>")[1].split("</style>")[0]
        bare = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        rule = next((r for r in bare.split("}")
                     if ".sp-req .blk-step" in r.split("{")[0]), None)
        assert rule, "no requirement-card rule"
        cols = re.search(r"grid-template-columns:\s*(\d+)px", rule)
        assert cols, (
            "the gutter must be a fixed px track; `auto` is sized by the level word, and a "
            "keyword like `min-content` reintroduces the same raggedness")
        # 88.6px is the widest accepted pill (`should-not`), browser-measured. A track
        # narrower than that wraps it and the alignment argument collapses.
        assert int(cols.group(1)) >= 90, (
            f"gutter {cols.group(1)}px is narrower than the widest accepted level pill")
        assert "border-bottom:0" not in rule, (
            "a card with its bottom edge removed is not the reference's card")
        # The card stack's gap belongs on the <ol>: `.sp-req` has a single child, so
        # gridding it spaces nothing.
        assert any("sp-req ol" in r.split("{")[0] and "gap:" in r
                   for r in bare.split("}")), "the card gap must sit on the list, not its wrapper"

    def test_sectioned_templates_emit_h3_so_their_css_matches(self):
        """F4 (Medium): `_bind` calls `render_sections` directly, so the `heading_tag`
        DEFAULT is what roadmap and dashboard get — not the `h3` the `_render_roadmap`
        adapter asks for. A default of `h2` silently changed legacy card markup and left
        `.mstone h3`, `.an-q h3` and `.rp-section h3` matching nothing."""
        for style, sec in (("roadmap", "mstone"), ("dashboard", "mstone"),
                           ("analysis", "an-q"), ("report", "rp-section"),
                           ("review", "rv-section"), ("spec", "sp-section")):
            h = _render("## Slot 1 — DONE\n\nbody", style)
            assert re.search(rf'<section class="{sec}[^"]*"[^>]*><h3>', h), (style, sec)

    def test_unsectioned_templates_leave_heading_levels_alone(self):
        """The other half of F4: `design` is NOT sectioned, so its h2s stay h2 and
        `.tpl-design h2` still applies.

        #41 removed `workflow` from this list — it is sectioned now. What that contract was
        written to catch is the silent DEMOTION that sectioning brings by default, and that
        is still caught, for workflow, by the test below.
        """
        assert "<h2>Section</h2>" in _render("lede\n\n## Section\n\nbody", "design")

    def test_workflow_is_sectioned_but_deliberately_keeps_its_h2(self):
        """#41. `workflow` opts into sectioning for its runbook stages, and passes
        `heading_tag: "h2"` so the authored heading level survives — a stage is a major
        division and the shared sizing already says so. Both halves are asserted: the
        wrapper must appear AND the heading must not be demoted, so dropping either the
        `section_class` or the `heading_tag` fails."""
        h = _render("lede\n\n## Section\n\nbody", "workflow")
        assert re.search(r'<section class="wf-stage"[^>]*><h2>Section</h2>', h), h[:400]
        assert "<h3>Section</h3>" not in h

    def test_a_title_carrying_markdown_is_not_stripped(self):
        """F5 (Medium): the dedup moved from rendered HTML to source, which made it match
        titles the old one did not. With inline markup the header (escape-only) and the
        body heading (inline-rendered) genuinely differ, so both are kept — exactly what
        happened before #13."""
        h = render_artifact.render_artifact("# Doc *Title*\n\nBody.\n", title="Doc *Title*",
                                            style="design", generated_at="x")
        assert h.count("<h1>") == 2
        plain = render_artifact.render_artifact("# Plain Title\n\nB.\n", title="Plain Title",
                                                style="design", generated_at="x")
        assert plain.count("<h1>") == 1

    def test_the_analysis_confidence_chip_has_the_shared_chip_shape(self):
        """F6 (Low): `.chip`'s base shape lives in `_ROADMAP_STYLE`, injected only for
        roadmap and dashboard, so analysis shipped a colour with no chip around it."""
        css = _render(_SPINE, "analysis").split("<style>")[1].split("</style>")[0]
        rule = css.split(".tpl-analysis .an-conf{")[1].split("}")[0]
        for prop in ("border-radius:999px", "padding:", "text-transform:uppercase"):
            assert prop in rule, prop

    def test_a_linked_heading_does_not_nest_anchors_in_the_jump_index(self):
        """F7 (Low): the index ran `inline_fn` over the heading, so a heading containing
        a link produced `<a>` inside `<a>` — invalid, and it breaks the entry."""
        h = _render("## Is [src](https://e.com) measured?\n\nyes", "analysis")
        nav = re.search(r'<nav class="an-index">.*?</nav>', h, re.S).group(0)
        assert nav.count("<a ") == 1
        assert 'href="https://e.com"' not in nav   # a link, not just the text


def test_the_scoped_css_check_rejects_an_unscoped_sibling_selector():
    """The mutation that defeated the first attempt at this guard: a scoped selector and
    an unscoped one in the same comma-separated list. A prefix-window check saw the scoped
    one nearby and passed; the unscoped selector still applied to every template."""
    css = ".tpl-design .dz-options,.dz-options{margin:0}"
    sels = _selectors_containing(css, ".dz-options")
    assert len(sels) == 2
    assert not all(".tpl-design" in s for s in sels), \
        "the guard must see the unscoped sibling"


# --------------------------------------------------------------------------- #130

_BLOCKS_MARKER = "**blocks:**"
_STRUCTURAL = "none (structural)"


def _doc_types_rows(doc):
    """Every row of the "## Doc types" choose-it table, as lists of stripped cells.

    Fails CLOSED at every step, and that is the whole point of writing it this way. A
    parser that returned `{}` when the document moved would make every derived
    requirement empty and `check_style_devices` a gate that can never fail — shipped
    green, useless. That is #114's defect class exactly (a "byte-identical" check that
    compared normalised text), committed by the guard meant to prevent it.
    """
    parts = doc.split("## Doc types")
    assert len(parts) == 2, "design-language.md has no unique '## Doc types' section"
    table = parts[1].split("### Markers")[0]
    rows = []
    for line in table.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if set("".join(cells)) <= set("- :"):
            continue                                   # the ---|--- separator
        rows.append(cells)
    assert rows, "the '## Doc types' table has no rows"
    return rows


def parse_first_read(doc, known_tags):
    """`{style: frozenset(tags)}` read from the **First-read element** column.

    The column is NAMED in the header and checked here. The neighbouring precedent
    (`test_doc_type_tags_match_the_documented_sets`) takes the table's LAST column with a
    positional regex; this one needs the THIRD of four, so a reordered or renamed column
    would silently hand it "Choose it when" prose instead. Asserting the header makes that
    fail loudly, naming the actual cause.
    """
    rows = _doc_types_rows(doc)
    header, data = rows[0], rows[1:]
    assert len(header) >= 3 and header[2] == "First-read element", (
        f"the third column of the '## Doc types' table is {header[2]!r}, not "
        f"'First-read element' — the table was reordered or renamed")

    found = {}
    for cells in data:
        m = re.fullmatch(r"`([a-z-]+)`", cells[0])
        if not m:
            continue
        style, cell = m.group(1), cells[2]
        # Cross-model review: a duplicated row silently overwrote the earlier one, so the
        # LAST row became the policy. If the code map were then updated to match it, both
        # the equality and non-empty assertions would pass while the earlier row still
        # documented additional required devices — the doc and the gate quietly disagreeing,
        # which is the one outcome this whole contract exists to prevent.
        assert style not in found, f"duplicate '## Doc types' row for {style}"
        assert cell.count(_BLOCKS_MARKER) == 1, (
            f"{style}: its First-read element cell must carry exactly one "
            f"'{_BLOCKS_MARKER}' annotation. That annotation IS the source of truth for "
            f"blocks.FIRST_READ_DEVICES; a cell without one would silently become an "
            f"empty requirement, which is indistinguishable from a passing gate")
        tail = cell.split(_BLOCKS_MARKER, 1)[1].strip()
        if tail == _STRUCTURAL:
            found[style] = frozenset()
            continue
        tags = re.findall(r"`(\w+)`", tail)
        assert tags, (
            f"{style}: {tail!r} names no block. An empty requirement must be spelled "
            f"exactly '{_STRUCTURAL}', so that 'this style has no block device' can never "
            f"be confused with 'the parser matched nothing'")
        unknown = sorted(set(tags) - set(known_tags))
        assert not unknown, f"{style}: {unknown} are not block tags"
        found[style] = frozenset(tags)
    return found


class TestFirstReadDeviceContract:
    """#130. `check_blocks` is a floor: one component of any kind satisfies it. This is the
    strict version — a page must carry the devices its own style OPENS with.

    The per-style table is the entire design risk the issue names, and AC1 is what contains
    it: the table is DERIVED from the first-read column that already existed, never
    invented, so there is one source of truth and this test is what holds the two together.
    Same shape, and the same reason, as `TestDocTypeContract` directly above.
    """

    DOC = (SCRIPTS.parent / "docs" / "design-language.md")

    # The two styles whose first-read element is built by the RENDERER, not declared by an
    # author, so there is nothing for a gate to require. `plain`'s cell is its <h1>;
    # `analysis`'s "headline answer" is `.an-answer`, which the markers table two sections
    # below classifies as structural — an opening paragraph. Named here rather than derived
    # so that "empty" is always a statement someone made.
    STRUCTURAL = {"plain", "analysis"}

    def _parsed(self):
        from render import blocks
        return parse_first_read(self.DOC.read_text(encoding="utf-8"), blocks.BLOCK_TAGS)

    def test_first_read_devices_match_the_documented_column(self):
        from render import blocks
        documented = self._parsed()
        assert documented == dict(blocks.FIRST_READ_DEVICES), (
            f"code requires {sorted(blocks.FIRST_READ_DEVICES.items())}, "
            f"design-language.md documents {sorted(documented.items())}")

    def test_every_documented_style_states_a_policy(self):
        """Non-empty for every style except the two explicitly structural ones.

        Stated as an exception list rather than "everything except plain", which was wrong
        twice over in the design draft and caught by cross-model review: `analysis` is also
        deliberately empty, and the three undocumented styles are not in this map at all.
        """
        for style, required in self._parsed().items():
            if style in self.STRUCTURAL:
                assert required == frozenset(), f"{style} is documented structural"
            else:
                assert required, f"{style} parsed to an EMPTY requirement — vacuous gate"

    def test_every_required_device_is_a_tag_that_style_accepts(self):
        """An unsatisfiable gate is worse than no gate: a page could never comply."""
        from render import blocks
        for style, required in blocks.FIRST_READ_DEVICES.items():
            if not required:
                continue
            assert required <= blocks.DOC_TYPE_TAGS[style], (
                f"{style} would be required to carry "
                f"{sorted(required - blocks.DOC_TYPE_TAGS[style])}, which "
                f"DOC_TYPE_TAGS does not let it accept")

    def test_every_template_is_classified_exactly_once(self):
        """A new template must not silently inherit the no-opinion exemption."""
        from render import blocks, templates
        documented = set(blocks.FIRST_READ_DEVICES)
        undocumented = set(blocks.UNDOCUMENTED_FIRST_READ)
        assert not (documented & undocumented), \
            f"classified twice: {sorted(documented & undocumented)}"
        assert documented | undocumented == set(templates.TEMPLATES) | {"plain"}, (
            "every style must be classified: add the new template to the '## Doc types' "
            "table (and FIRST_READ_DEVICES) or to UNDOCUMENTED_FIRST_READ")

    # --- the parser's own can-it-fail set ------------------------------------------
    #
    # The guard above is only worth its bytes if it can go red. #114 shipped a guard whose
    # central claim was FALSE and every test passed, so the parser is now driven with
    # deliberately broken input.

    _HEAD = ("## Doc types\n\n"
             "| Type | Choose it when | First-read element | Component set |\n"
             "| --- | --- | --- | --- |\n")
    _TAIL = "\n### Markers\n"

    def _doc(self, row):
        return self._HEAD + row + self._TAIL

    def test_a_row_with_no_marker_raises(self):
        doc = self._doc("| `roadmap` | when | stat strip, then the phase rail | `stats` |")
        with pytest.raises(AssertionError, match="must carry exactly one"):
            parse_first_read(doc, ("stats",))

    def test_a_marker_naming_nothing_raises(self):
        doc = self._doc(f"| `roadmap` | when | stat strip — {_BLOCKS_MARKER} | `stats` |")
        with pytest.raises(AssertionError, match="names no block"):
            parse_first_read(doc, ("stats",))

    def test_an_unknown_tag_raises(self):
        doc = self._doc(f"| `roadmap` | when | x — {_BLOCKS_MARKER} `nope` | `stats` |")
        with pytest.raises(AssertionError, match="are not block tags"):
            parse_first_read(doc, ("stats",))

    def test_a_renamed_or_reordered_column_raises(self):
        doc = ("## Doc types\n\n"
               "| Type | Choose it when | Component set | First-read element |\n"
               "| --- | --- | --- | --- |\n"
               f"| `roadmap` | when | `stats` | x — {_BLOCKS_MARKER} `stats` |" + self._TAIL)
        with pytest.raises(AssertionError, match="not 'First-read element'"):
            parse_first_read(doc, ("stats",))

    def test_a_missing_section_raises(self):
        with pytest.raises(AssertionError, match="no unique '## Doc types' section"):
            parse_first_read("# nothing here\n", ("stats",))

    def test_the_structural_spelling_is_exact(self):
        """`none (structural)` is the ONLY way to say "no requirement". A near-miss must
        raise rather than quietly parse to an empty set."""
        doc = self._doc(f"| `plain` | never | its h1 — {_BLOCKS_MARKER} none |")
        with pytest.raises(AssertionError, match="names no block"):
            parse_first_read(doc, ("stats",))

    def test_the_parser_detects_a_drifted_tag(self):
        """The equality assertion above can actually catch drift."""
        doc = self._doc(f"| `roadmap` | when | x — {_BLOCKS_MARKER} `callout` | `stats` |")
        assert parse_first_read(doc, ("stats", "callout")) == {"roadmap": frozenset({"callout"})}

    def test_a_duplicate_row_raises(self):
        """Silently, the last row won. If the code map were then updated to match it, every
        assertion here would pass while the earlier row still documented more devices."""
        doc = (self._HEAD
               + f"| `roadmap` | when | a — {_BLOCKS_MARKER} `stats`, `callout` | x |\n"
               + f"| `roadmap` | when | b — {_BLOCKS_MARKER} `stats` | x |\n"
               + self._TAIL)
        with pytest.raises(AssertionError, match="duplicate '## Doc types' row"):
            parse_first_read(doc, ("stats", "callout"))
