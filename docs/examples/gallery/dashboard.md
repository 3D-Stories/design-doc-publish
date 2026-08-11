Halyard delivery programme, at a glance. One rolling page, refreshed each Monday.

```meter
Phases complete | 1 | 4
```

```stats
6.2% | miss rate | | 8,7.4,6.9,6.2 | warn
0.4% | target | | | ok
2 | carriers live | | | note
41 | days to carrier B GA | | | note
```

```chips statebar
main at 7c41e02 | done
phase 2 | wip
carrier contracts | blocked
```

## Workstreams

```phases
Webhook ingestion | 7 of 12 done | wip
  H-111 | Write to the replica on receipt | wip
  H-112 | Freshness check | planned
  H-120 | Drop the poller to 15 minutes | planned
Carrier onboarding | 1 of 3 done | warn
  C-201 | Carrier A live | done
  C-202 | Carrier B contract | blocked
Observability | 2 of 2 done | done
  O-301 | Distinct handshake-failure logging | done
  O-302 | Certificate expiry alarm | done
```

```composition
on track | 5 | ok
at risk | 2 | warn
blocked | 1 | crit
```

## What is actually blocked

One thing: the carrier B contract. Everything downstream of it is parked rather than staffed, so
the blockage costs us calendar time and no engineering time.

```provenance
Refreshed | every Monday, from the issue tracker
Method | counts are issue states, not estimates
```
