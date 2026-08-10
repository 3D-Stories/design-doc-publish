"""Named values the `design-system` style documents (#42).

Issue #42 asks that style to show "brand colours, type scale, spacing and radius tokens". Brand
colour already has a real source (`vdl.py` — `--accent` plus optional `--bg`). This module supplies
the radius scale, and is deliberately honest about what does not exist.

**Radii ARE a scale, and this module is their source.** The base stylesheet uses exactly three —
small, medium, large — and `_STYLE` is a `string.Template` that substitutes these values in. So the
names here DRIVE the CSS rather than mirroring it, and there is no second copy to drift. The
substitution is required to be byte-for-byte inert: `test_tokens.py` pins the resulting stylesheet
to its exact pre-#42 SHA-256, which is what keeps AC5's frozen `plain` output frozen.

**Spacing is NOT a scale, and no vocabulary is invented for it.** Measured on `_STYLE`: twelve
distinct pixel values (1, 4, 5, 8, 12, 14, 16, 18, 20, 24, 40, 72), eight used exactly once.
Naming those would be transcription wearing the word "token" — `--space-18` documents nothing a
reader can reuse. The design-system page therefore reports what the stylesheet actually uses and
says plainly that there is no named spacing scale yet. Establishing one means changing the
stylesheet's VALUES, which moves `plain`'s bytes and is blocked by #42's AC5; that needs its own
issue and its own answer to byte identity.

`string.Template` rather than an f-string or %-formatting: the CSS is full of braces and contains
`%`, but contains no `$` at all.
"""

# name -> the literal substituted into `_STYLE`. Changing a value here changes the stylesheet,
# which is the point — and `test_tokens.py` will fail on the SHA oracle, which is also the point:
# a radius change is a deliberate, visible act, not a silent one.
RADII = {
    "sm": "4px",    # inline code
    "md": "8px",    # code blocks
    "lg": "12px",   # panels, cards, milestones
}

# There is no named spacing scale. Recorded as data so the design-system page can state the fact
# without re-deriving it, and so a future issue that introduces one has an obvious place to land.
SPACING_SCALE = None
