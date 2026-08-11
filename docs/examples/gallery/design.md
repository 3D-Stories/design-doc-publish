Halyard's tracking API answers "where is my parcel" in 40ms at the edge, and in 900ms when the
edge misses. This proposes closing that gap without adding a second datastore.

## The problem

Every miss walks the same path: edge cache, regional read replica, then the carrier's own API. The
third hop is the one that hurts, and it is the one we do not control.

```stats
40 | ms at the edge | | 38,41,39,40,42,40
912 | ms on a miss | +18% | 700,780,850,912 | accent
6.2% | miss rate | | | warn
```

## Two shapes we considered

```options
Write-through cache | one datastore, no new failure mode | carrier webhooks are unreliable | chosen
Second read store | fast, isolated | a second thing to keep consistent | rejected
```

```callout decision
note | Write-through, not a second store
A second store buys latency and costs correctness. Carrier webhooks already tell us when a
parcel moves; we simply throw that away today. Consuming them is strictly less machinery.
```

## Before and after

```nodes compare
today
  edge | 40ms hit, 6.2% miss | HIT
  replica | 120ms, always warm | READ
  carrier | 750ms, rate limited | SLOW
proposed
  edge | 40ms hit, 0.4% miss | HIT
  replica | 120ms, written on webhook | WRITE
```

## What has to be true before we ship

```steps ac
1 | Miss rate below 1% | Measured over a full week, not a quiet Sunday.
2 | No stale reads | A parcel that moved is never reported at its old scan point.
3 | Webhook loss survivable | A dropped webhook self-heals within one polling interval.
```

## Risks we are accepting

A carrier that stops sending webhooks degrades us to today's behavior, which is survivable. A
carrier that sends *wrong* webhooks does not, and we have no way to detect that beyond the
freshness check in criterion 2.
