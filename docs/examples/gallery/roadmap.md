Delivery plan for Halyard's webhook ingestion work. Four phases, sequenced so each one is
independently shippable and independently revertable.

```meter
Phases complete | 1 | 4
```

```chips statebar
main at 7c41e02 | done
phase 2 | wip
carrier contracts | blocked
```

## Phases

```phases
Phase 1 — Ingest | 5 of 5 done | done
  H-101 | Accept and verify carrier signatures | done
  H-102 | Persist raw events, unparsed | done
  H-103 | Replay tooling for a dropped window | done
Phase 2 — Write through | 2 of 4 done | wip
  H-110 | Map carrier scan codes to our vocabulary | done
  H-111 | Write to the replica on receipt | wip
  H-112 | Freshness check against the carrier API | planned
Phase 3 — Retire polling | not started | note
  H-120 | Drop the 90s poller to 15 minutes | planned
  H-121 | Delete it once miss rate holds | planned
Phase 4 — Carrier two | blocked | blocked
  H-130 | Contract signed | blocked
```

```stats
6.2% | miss rate today | | 8,7.4,6.9,6.2
0.4% | target | | | ok
2 | carriers live | | | note
```

## Sequencing, and why it is this order

Phase 3 cannot start before phase 2 finishes, because dropping the poller while the write-through
path is half-built removes the only thing covering it. Phase 4 waits on a signature we do not
control, so it is parked rather than staffed.
