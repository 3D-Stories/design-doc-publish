"""One module per doc type — the nine bodies (waves 3 and 4, #13 + #18).

Each module is DECLARATION ONLY: a name, the `render_sections` config for its structure,
the marker map its blocks are hung with, and its stylesheet. No module here renders
anything or imports a renderer, so the layering runs one way — `templates` declares,
`markdown` structures, `blocks` builds components — and nothing imports back upward.

Wave 4 (#18) added `uat.py` beside these; it is the only interactive template, and the
only one that declares `BLOCK_VARIANTS` or `AFTER_BODY`. #41 gave `workflow` a
`BEFORE_BODY` too — a static step-kind key — so furniture is no longer uat's alone.
`uat` remains the only template that ships a SCRIPT.

`MARKERS` keys are slots, not class names:

* `"chips"` — the wrapper of a `chips` block written with NO role.
* `"chips:statebar"` — the wrapper of one written as a `chips` fence with role `statebar`.
* `"stats.bar"` — a sub-element inside a `stats` block.

Values are fixed class names written HERE, never by a document author. A role only ever
selects a key, which is what keeps author text out of a class attribute;
`test_marker_values_are_slugs` pins it.
"""
from ..markdown import roadmap_status_chip
from . import (analysis, dashboard, design, design_system, module_map, report, review,
               roadmap, slide_deck, spec, uat, workflow)

# Registry order drives the CLI's `--style` choices, so it is the roster order from
# specs §4c rather than alphabetical.
MODULES = (analysis, roadmap, report, design, dashboard, review, spec, uat,
           workflow, design_system, module_map, slide_deck)

TEMPLATES = {m.NAME: m for m in MODULES}


def sections_config(module) -> dict:
    """The module's `render_sections` kwargs, with the `"status"` shorthand resolved.

    Roadmap and dashboard both want the completion chip but must NOT share a config —
    they share one renderer, so a single `section_class` would leak roadmap's `.rm-epic`
    into dashboard. Declaring the resolver by name keeps these modules free of renderer
    imports while still binding the real callable here.
    """
    cfg = dict(module.SECTIONS)
    if cfg.get("chip_resolver") == "status":
        cfg["chip_resolver"] = roadmap_status_chip
    return cfg


CSS = {m.NAME: m.CSS for m in MODULES}
MARKERS = {m.NAME: dict(m.MARKERS) for m in MODULES}

# #18: two more optional declarations. `VARIANTS` names an engine-owned renderer for a
# block; BEFORE/AFTER are trusted CONSTANT furniture strings emitted around the body.
# `uat` uses all three; #41 gave `workflow` a `BEFORE_BODY` key as well. A template that
# declares none renders byte-for-byte as it did before wave 4.
VARIANTS = {m.NAME: dict(getattr(m, "BLOCK_VARIANTS", {})) for m in MODULES}
BEFORE_BODY = {m.NAME: tuple(getattr(m, "BEFORE_BODY", ())) for m in MODULES}
AFTER_BODY = {m.NAME: tuple(getattr(m, "AFTER_BODY", ())) for m in MODULES}
