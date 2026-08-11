Halyard tracking: where the latency goes, and the one change that fixes it.

## The problem in one number

```stats
912 | ms on a cache miss | +18% | 700,780,850,912 | accent
6.2% | of lookups miss | | | warn
```

## Misses are not a cache problem

```composition
single-lookup parcels | 41 | warn
repeat lookups | 59 | ok
```

Forty-one percent of lookups are for a parcel nobody checks twice. No cache can help a request
that has never been made before.

## The change

```meter
Phases complete | 1 | 4
```

Consume the carrier webhooks we already receive and throw away. Write through to the replica on
receipt. The parcel is warm before anyone asks for it.

## Where we are

```phases
Ingest | done | done
Write through | in progress | wip
Retire polling | not started | note
Second carrier | waiting on a signature | blocked
```

## What we are asking for

Nothing new. The work is staffed and phase one shipped. This is a status update, not a request.
