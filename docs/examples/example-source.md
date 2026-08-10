# Migrating the billing service to the new ledger

A worked example, written to be rendered. It is deliberately ordinary markdown — no styling, no
HTML — so that what you see in the rendered page comes from the renderer and not from the source.

## Why this is happening

The billing service writes to two places that disagree. Reconciliation runs nightly and papers over
the difference, which means every disagreement is invisible for up to a day, and the fix is always
retrospective.

The new ledger makes one of those two places authoritative. That is the whole change. Everything
below is the sequencing needed to do it without a night where money is unaccounted for.

## Phases

| Phase | State | Detail |
| --- | --- | --- |
| Shadow writes | done | Write to both, compare, alert on drift. No behaviour change. |
| Drift burn-down | active | Fix every mismatch the comparison finds, until a week reads clean. |
| Cutover | planned | Ledger becomes authoritative. The old table becomes a mirror. |
| Remove the mirror | planned | Only after a full billing cycle with no reconciliation delta. |

## What could go wrong

| Risk | Level | Mitigation |
| --- | --- | --- |
| A drift class we have not seen yet | bug:must | Burn-down does not end on a timer, it ends on a clean week. |
| Cutover during a billing run | crit | Cutover is gated to the quiet window, and refuses outside it. |
| The mirror is removed too early | warn | One full cycle, measured, not estimated. |
| Reporting queries still read the old table | feature:should | Inventory every reader before cutover. |

## The one thing to get right

**The cutover is reversible for exactly as long as the mirror exists.** That is why removing the
mirror is its own phase, after a full cycle, rather than a tidy-up at the end of the cutover. A
rollback after the mirror is gone is a restore from backup, which is a different and much worse
conversation.

## Open questions

1. Does the nightly reconciliation job need to keep running during burn-down, or does the comparison
   already cover it? Leaning yes to keeping it, because it is cheap and it is the thing that would
   catch a mistake in the comparison itself.
2. Who owns the quiet-window definition? It is currently a constant in two services.
