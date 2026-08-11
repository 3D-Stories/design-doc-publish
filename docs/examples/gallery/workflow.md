How to fail Halyard over to a secondary carrier certificate. Follow this under pressure. Do not
improvise.

```callout decision
warn | Read step 1 before you touch anything
Failing over with a stale secondary is worse than staying degraded. Step 1 is the check that stops
that, and it takes eleven seconds.
```

```steprail
1 | Verify the secondary is valid | halyard cert check --slot secondary | check
2 | Confirm the primary is the fault | halyard probe carrier-a --tls-only | check
3 | Announce in the incident channel | State which carrier and which slot. | action
4 | Swap the slot | halyard cert promote --slot secondary | action
5 | Watch the miss rate | halyard watch miss-rate --window 60s | check
6 | Stand down or escalate | Under 1% within five minutes, or page the carrier liaison. | action
```

## What the swap actually does

```flow
term | Failover requested
proc | Load the secondary certificate
dec | Does it chain to a trusted root?
proc | Promote it to the active slot | yes
term | Refuse and keep the primary | no
proc | Drain connections using the old certificate
term | Miss rate recovers
```

## If step 4 refuses

It refuses for exactly one reason: the secondary does not chain. That is not a bug and it is not
worth debugging mid-incident. Stay on the primary, accept the degradation, and page the carrier
liaison — they can re-trust our existing certificate faster than we can mint a new one.

```legend
solid | a path the tool takes on its own
dashed | a path that needs a human decision
```
