The Halyard interface palette, type scale and component states. One page, so nobody has to guess
which amber is the right amber.

## State colours

```chips statebar
delivered | done
in transit | wip
delayed | warn
exception | crit
label created | note
```

```legend
done | terminal and successful; the parcel arrived
wip | moving, nothing wrong
warn | late against its promise, still moving
crit | stopped and needs a human
note | known but not yet moving
```

## Type scale

```stats
16px | body | | | note
14px | secondary and table cells | | | note
28px | section heading | | | note
44px | page title | | | note
```

## Rules that are not negotiable

Colour never carries meaning alone. Every state chip pairs its colour with its word, because eight
percent of men cannot separate our amber from our green, and a parcel status nobody can read is
worse than an ugly one.

Contrast holds at 4.5:1 for body text and 3:1 for the chips, measured against both the light and
dark surfaces, not just the one the designer had open.

## Spacing

An 8px base unit, and only multiples of it. Where a design calls for 6px, it is wrong about the
6px, not about the base.

```provenance
Measured | contrast ratios computed against both surface tokens, 2026-03-02
Method | WCAG 2.2 relative luminance; every pairing in the chip set, not a sample
```
