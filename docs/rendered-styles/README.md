# Rendered styles — one page per template, so a human can look

One committed HTML page for every style in the registry. **Open any file directly in a browser.**

Originally generated 2026-08-02 during epic #46 child #42, because the owner asked where the
per-style pages were and the answer was that none existed. #40 and #41 had proved each rebuilt
template with a PNG attached to its PR, never with a viewable page in the repo.

## What these are

Every style in the registry, rendered from the cross-style fixture
(`scripts/tests/fixtures/crossstyle.md`) — one document that exercises every
typed component block, so each page shows its template's full component set.

## These are guarded, and that is new (#114)

**`scripts/tests/test_rendered_styles_current.py` fails when any committed
page differs from a fresh render of the fixture at the pinned stamp, and when the set of pages does
not equal the style registry exactly.** So a stale page cannot survive a test run, a newly added
style cannot silently skip the guard, and a removed style cannot leave a page behind.

That guard exists because the previous drop of this directory had none. Thirteen files were generated
and **never committed**, so the repository still answered "none exist"; by the time anyone looked,
every page was stale — even `plain`, the frozen style — and `module-map` and `slide-deck` were
missing entirely. A page that presents itself as current when it is not is worse than a missing one.

Regenerate after any change that legitimately moves rendered output, then commit the result:

```bash
python3 scripts/tests/regen_rendered_styles.py
```

That script **owns** the recipe — fixture, title, `--generated-at` stamp, `--doc-id`, style list —
and the guard imports it, so there is one place for those values to live. The equivalent by hand is
`crossstyle.sh <head-tree> <base-tree> <outdir> --no-style-change` followed by copying
`<outdir>/head/*.html` here; it uses the same values, which is why they are pinned in one module
rather than restated in each.

## Two honest caveats

- **The content is synthetic.** It is a test fixture, not a real document. Judge the layout and the
  components, not the prose.
- **No VDL pack is applied**, so every page shows the renderer's default teal accent rather than a
  project's own colour. That matters most for `design-system.html`, whose whole point is showing a
  project's real accent; to see one, render that style with `--project <name>`.

Some pages emit "block type X is not accepted by doc type Y — rendering it anyway" warnings during
generation. That is expected and not a defect: the fixture deliberately exercises every block against
every style, and most styles accept only a subset.
