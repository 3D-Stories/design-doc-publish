How Halyard's tracking path fits together, and which hops we control.

```nodes compare
request path
  edge | Cloudflare worker, 40ms | OURS
  api | tracking service, 3 pods | OURS
  replica | Postgres read replica | OURS
  carrier | carrier A and B APIs | THEIRS
ingestion path
  hooks | webhook endpoint, 2 pods | OURS
  queue | durable event log, 7 day retention | OURS
  writer | replica writer | OURS
```

```legend
solid | a call we make and can retry
dashed | a call made to us, on their schedule
OURS | we deploy it, we page for it
THEIRS | we can only observe and retry
```

## The one hop that matters

```flow
term | Lookup arrives at the edge
dec | Is the parcel cached?
term | Serve in 40ms | yes
proc | Read the replica | no
dec | Is the replica fresh?
term | Serve in 120ms | yes
proc | Call the carrier | no
term | Serve in 750ms, or fail
```

Everything expensive is downstream of that second decision. The ingestion path exists purely to
keep the replica fresh enough that the third hop is never reached.

## What is not shown

The billing and notification services both read from the same replica. They are omitted here
because they never trigger a carrier call, so they cannot affect the latency this map is about.
