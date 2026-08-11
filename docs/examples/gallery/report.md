What happened during the Halyard tracking outage on 14 March, what we did, and what changed
afterwards.

```stats
41 | minutes degraded | | 0,12,38,41,20,0
2.1M | lookups affected | | | warn
0 | parcels lost | | | ok
1 | carrier involved | | | note
```

```timeline
09:14 | Alert fired | Miss rate crossed 25%. Pager went out to the on-call. | past
09:22 | Cause identified | Carrier A began rejecting our client certificate. | past
09:31 | Mitigated | Failed over to the secondary certificate. | past
09:55 | Fully recovered | Miss rate back under 1%. | past
14:00 | Certificate rotation automated | The permanent fix landed. | now
```

```meter
Action items closed | 4 | 5
```

## What actually broke

Carrier A rotated their trust store without notice. Our client certificate was still valid, but it
was no longer trusted by them. Every call failed at the handshake, so every lookup fell through to
a miss, and the miss path is the slow one.

## Why it took 17 minutes to find

The handshake failure surfaced as a generic timeout in our logs. Nothing distinguished "they hung
up on us" from "the network is slow", and the on-call reasonably chased the network first.

```provenance
Measured | 14 March, from the edge metrics, not from the application logs
Method | miss-rate series at one-minute resolution; incident channel transcript for timings
Caveat | the 2.1M figure counts affected lookups, not affected customers
```

## What changed

Certificate rotation is automated and alarms 30 days before expiry. The handshake failure now logs
distinctly from a timeout. The remaining open item is a synthetic probe against each carrier, which
would have caught this in under a minute.
