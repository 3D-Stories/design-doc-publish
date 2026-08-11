Why Halyard's miss rate rose from 3.1% to 6.2% over eleven weeks, when nothing in the cache layer
changed.

```stats
3.1% | miss rate, week 1 | | 3.1,3.4,3.9,4.4,5.1,5.8,6.2
6.2% | miss rate, week 11 | +100% | | warn
0 | cache-layer deploys | | | ok
```

## The short answer

The cache did not get worse. The traffic did. Long-tail parcels — ones nobody looks up twice — grew
from 19% of lookups to 41%, and a parcel looked up once can never be served from a cache populated
by a previous lookup.

```composition
looked up once | 41 | warn
looked up 2-5 times | 34 | note
looked up 6+ times | 25 | ok
```

## How the shape changed

```timeline
Week 1 | Baseline | 19% single-lookup traffic. Cache doing what it was built for. | past
Week 4 | Carrier B onboarded | Their volume is overwhelmingly single-lookup consumer parcels. | past
Week 8 | Marketing campaign | Drove one-off tracking links; single-lookup share crossed 35%. | past
Week 11 | Today | 41% single-lookup. Miss rate tracks it almost exactly. | now
```

## The part that is inference, not measurement

Single-lookup share and miss rate move together with a correlation of 0.94 across the eleven weeks.
That is strong, and it is still correlation. I did not run the counterfactual — holding traffic mix
fixed and replaying — because we do not retain enough request detail to reconstruct it.

```provenance
Measured | edge logs, weeks 1 to 11, sampled at 1 in 100
Method | lookup counts per parcel id, bucketed weekly; miss rate from the same series
Not measured | the counterfactual replay; request detail is retained for 14 days, not 11 weeks
```

## What follows from it

Tuning the cache will not help, because the misses are unrepeated lookups. The lever that would
help is prefetching on carrier webhook — which is exactly what the ingestion work already does for
a different reason.
