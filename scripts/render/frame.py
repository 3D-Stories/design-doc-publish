"""The page frame a template owns (#69).

Before this module the frame was hardcoded once, in `_STYLE`, and a template could only ever
write `.tpl-<style> .some-widget{…}`. Of 233 `.tpl-` rules in the registry exactly one was
frame-level, and it was a counter — which is the whole reason ten styles with 40–67% of their
own page's CSS still looked like one page.

The literals now live here as named slots and are substituted back into `_STYLE` through the
same `string.Template` mechanism #42's PR 0 proved on the radius scale. Substituting the
defaults is required to be byte-for-byte inert, which is what keeps `plain` frozen; a template
that wants different values declares them as `FRAME = {...}` in its own module and the engine
emits them, scoped to that template's body class.

**Declaration, never hand-written CSS.** A template supplies values; only this module writes
selectors. If each template invented its own selector shape there would be nothing decidable for
#45's machine gate to measure, and "does this style own its frame?" would be a reading exercise
again.

## What a template may own, and what is withheld

Owned — the five things that make two pages look like different documents:

* `ground` — what the page sits on. A flat colour or a wash composited over `--bg`.
* `measure` + `gutter` — how wide the content is and how it is inset.
* `header_pad` / `header_rule` / `header_gap` — the masthead's weight and whether it is ruled off.
* `h1_size` / `h2_size` — the type scale's top two steps.
* `h2_rhythm` — the vertical spacing between sections.

Withheld, each for a reason rather than an oversight:

* **The body font family.** Output must stay self-contained (`test_no_external_hosts`), and both
  frozen targets reach their look with system fonts. A per-style family invites the first webfont.
* **The ink and line colours.** `lint.theme_tokens()` scores contrast by reading the two
  `[data-theme]` blocks only. A per-style ink would be invisible to that gate — a style could
  ship unreadable text and the lint would still pass. Colour stays token-level, where it is
  measured.
* **The shell's structure** — `body > .wrap > header/main/footer`. Templates declare; they do not
  restructure. Every typed block composes against that shape, and `uat`'s script addresses it.

`ground` is the one owned slot the contrast gate cannot see, because it is a background value
rather than a token. A wash must therefore stay close enough to `--bg` that the scored pairs
still hold — noted here because the guard cannot say it.
"""

# The exact literals `_STYLE` carried before #69. Substituting these back must not move a byte:
# `test_frame_ownership.py::test_the_substitution_is_byte_inert` pins it to #73's SHA.
DEFAULTS = {
    "ground": "var(--bg)",
    "measure": "900px",
    "gutter": "0 20px 72px",
    "header_pad": "40px 0 18px",
    "header_rule": "1px solid var(--line)",
    "header_gap": "20px",
    "h1_size": "clamp(22px,4vw,30px)",
    "h2_size": "19px",
    "h2_rhythm": "1.4em 0 .4em",
}

SLOTS = tuple(DEFAULTS)

# Which rule each slot lands in, so `slot_appears()` and the emitter cannot drift apart.
_IN_BODY = ("ground",)
_IN_WRAP = ("measure", "gutter")
_IN_HEADER = ("header_pad", "header_rule", "header_gap")
_IN_H1 = ("h1_size",)
_IN_H2 = ("h2_size", "h2_rhythm")

_SELECTOR = {
    **{s: "body.tpl-{name}" for s in _IN_BODY},
    **{s: ".tpl-{name} .wrap" for s in _IN_WRAP},
    **{s: ".tpl-{name} header" for s in _IN_HEADER},
    **{s: ".tpl-{name} h1" for s in _IN_H1},
    **{s: ".tpl-{name} h2" for s in _IN_H2},
}


def resolve(declared: dict | None) -> dict:
    """A template's declaration over the defaults. Unknown slots are ignored, not fatal:
    a typo must not take the renderer down mid-render, and the test suite already fails on one."""
    out = dict(DEFAULTS)
    for slot, value in (declared or {}).items():
        if slot in DEFAULTS and isinstance(value, str) and value:
            out[slot] = value
    return out


def css_layer(name: str, declared: dict | None = None) -> str:
    """Every slot, always emitted, scoped to `.tpl-<name>`.

    Emitted even when a style keeps every default. Two reasons: the cross-style byte guard's
    `--foundation` mode requires every rich style to move on the commit that introduces a
    foundation, and #45's gate reads the emitted frame — a style that silently emitted nothing
    would be indistinguishable from one that has not been rebuilt yet.

    Specificity does the work, so nothing here needs `!important`: `body.tpl-x` (0,1,1) beats
    `body`, `.tpl-x .wrap` (0,2,0) beats `.wrap`, and `.tpl-x header|h1|h2` (0,1,1) beats the bare
    element. This layer is emitted BEFORE the template's own stylesheet, so a hand-written rule at
    equal specificity still wins on source order — the frame is what a template decorates.
    """
    f = resolve(declared)
    return (
        f"\nbody.tpl-{name}{{background:{f['ground']}}}"
        f"\n.tpl-{name} .wrap{{max-width:{f['measure']};padding:{f['gutter']}}}"
        f"\n.tpl-{name} header{{padding:{f['header_pad']};"
        f"border-bottom:{f['header_rule']};margin-bottom:{f['header_gap']}}}"
        f"\n.tpl-{name} h1{{font-size:{f['h1_size']}}}"
        f"\n.tpl-{name} h2{{font-size:{f['h2_size']};margin:{f['h2_rhythm']}}}\n"
    )


# --- #75: a decorative accent palette a template may own -----------------------------
#
# The frozen `uat` target cycles four accents across its parts — the panel's left border, its
# PART pill, and its checkbox borders all take the part's own colour. That device is not
# expressible in the `uat` stylesheet, and the reason is worth writing down because it looks like
# an oversight until you check:
#
# * The shared token layer has exactly ONE accent hue. `--accent`, `--chip-c` and `--req-c` are
#   all `#2dd4bf`; the only other hues are `--sev-*`, which MEAN severity. Spending a severity
#   token on a decorative accent breaks the approved spec's rule 3 — "the accent identifies the
#   section; it never signals state".
# * Adding hues to the shared `:root` block moves EVERY style's bytes, `plain` included, which
#   AC2 forbids outright.
# * The style cannot declare them itself: `test_it_declares_no_literal_colour_of_any_form` bans
#   every hex, every named colour and every colour function in a template's CSS — `color-mix()`
#   explicitly included, so deriving hues from existing tokens is closed too. Checked before
#   building on it.
#
# So the engine emits them, scoped, exactly as it emits the frame: the template DECLARES and this
# module writes the selector. A style that declares nothing emits nothing, so the other nine are
# byte-inert.
#
# WHY ACCENTS ARE OWNABLE WHERE INK AND LINE ARE WITHHELD, since the docstring above withholds
# colour on principle. The reason there is measurement: `lint.theme_tokens()` scores contrast by
# reading the two `[data-theme]` blocks, so a per-style INK would let a style ship unreadable body
# text with the gate still green. These accents carry no body text. They are borders, rules and
# one large mono uppercase pill — and that pill is the single place an accent carries any text at
# all, on a dark tint, at 10px/700 with wide tracking.
#
# **The gate cannot see them, and that is stated rather than assumed** — the same caveat `ground`
# already carries above, for the same reason. A palette entry that is not legible against
# `--surface` will not fail a test; it has to be looked at.


def palette_layer(name: str, accents=None) -> str:
    """`--tpl-a1…n`, scoped to `.tpl-<name>`. Empty string when a template declares none.

    Unlike `css_layer`, this is emitted ONLY when declared. The frame is emitted always because
    #45's gate reads it to tell a rebuilt style from an untouched one; a palette is optional
    decoration, and emitting an empty rule for nine styles would move nine styles' bytes to say
    nothing.
    """
    values = [a for a in (accents or ()) if isinstance(a, str) and a]
    if not values:
        return ""
    decls = ";".join(f"--tpl-a{i}:{v}" for i, v in enumerate(values, 1))
    return f"\nbody.tpl-{name}{{{decls}}}\n"


def slot_appears(css: str, name: str, slot: str) -> bool:
    """Whether `css` carries a frame declaration for this style's slot. Used by the suite and
    available to #45's gate, so both ask the question the same way."""
    return _SELECTOR[slot].format(name=name) + "{" in css

# --- #45: the machine gate's observable ------------------------------------------------
#
# "Does this style own its frame?" has to be DECIDABLE, or the gate is a reading exercise again.
# Two findings from #76 shape what it may ask:
#
# * **D70** — `h2_size` and `h2_rhythm` reach nothing on a SECTIONED style, because
#   `render_sections` re-emits every `##` as the template's `heading_tag` (default `h3`). Only a
#   style that is unsectioned, or that sets `heading_tag: "h2"`, has live h2 slots.
# * **D78** — an assertion that a slot merely DIFFERS FROM THE DEFAULT passed for weeks while two
#   of the slots it checked did nothing. Declaration is not effect.
#
# So the gate counts slots that are BOTH declared away from the default AND able to reach a
# rendered page. A style could otherwise satisfy it by declaring two inert values, which is
# exactly the emptiness this epic exists to end.

_H2_SLOTS = ("h2_size", "h2_rhythm")


def live_slots(module) -> tuple:
    """The slots that can affect a rendered page for this template.

    Everything except the two h2 slots, which are live only when the template's own section
    headings are `h2` — i.e. it is unsectioned, or it asks for `heading_tag: "h2"`.
    """
    sections = getattr(module, "SECTIONS", None) or {}
    sectioned = any(sections.get(k) for k in
                    ("section_class", "chip_resolver", "lead_class", "index_class"))
    h2_live = (not sectioned) or sections.get("heading_tag") == "h2"
    return SLOTS if h2_live else tuple(s for s in SLOTS if s not in _H2_SLOTS)


def owned_slots(module) -> tuple:
    """Live slots this template declares AWAY from the default. The gate's observable."""
    declared = getattr(module, "FRAME", None) or {}
    return tuple(s for s in live_slots(module)
                 if s in declared and declared[s] != DEFAULTS[s])

