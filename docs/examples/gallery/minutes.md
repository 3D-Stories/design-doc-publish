The change advisory board met after the 14 March tracking outage. It agreed three premises, chose
two courses of action and assigned four items to named people.

## Meeting

```chips meetingbar
change advisory board | note
2026-03-18, 09:30 MDT | note
quorum met, 5 of 7 | ok
minutes of 4 March approved | ok
```

```chips attendees
D. Ferreira - chair | ok
M. Lindqvist - secretary | ok
S. Nakamura - carrier integrations | ok
P. Achterberg - platform | ok
R. Villalobos - support, observer | note
```

```stats
3 | premises agreed | | | accent
2 | courses decided | | |
4 | action items | | |
2 | questions left open | | |
```

## Agreed

```findings
agreed | The gap started in the carrier feed, not in Halyard | It was the consensus that the 14 March gap begins upstream: the carrier's own status page reports the same window, to the minute. | trace 09:41, segments 88 to 104
agreed | Our retries made the gap outlast the outage | Each person present expressed agreement that Halyard's uncapped retry loop held the queue saturated for 40 minutes after the feed came back. | trace 09:58, segments 141 to 166
agreed | Support was working blind for the whole window | Doubt was expressed as to whether a banner would have calmed anyone, but nobody disputed that support had nothing to tell customers. | trace 10:14, segment 203
```

## Decided

```verdict
decided | Cap carrier retries with exponential backoff and a dead-letter queue, before the Easter peak.
decided | Publish a customer-facing status banner driven by the same health check the on-call page reads.
```

## Alternatives considered

```options
Cap retries in Halyard | we own the schedule and can ship it | the carrier still drops the window | chosen
Ask the carrier to widen its replay window | no code from us at all | months of contract work, no date | rejected
Buy a second tracking feed | removes the single carrier | doubles the reconciliation work | rejected
```

## Actions

```steps
A1 | Cap carrier retries and add the dead-letter queue | S. Nakamura - by 2026-04-03, before the Easter peak.
A2 | Wire the status banner to the on-call health check | P. Achterberg - by 2026-04-10.
A3 | Write the support script for a feed outage | R. Villalobos - before the banner ships.
A4 | Put the replay window on the next carrier call | D. Ferreira - at the 8 April carrier review.
```

## Open

```callout open
note | Two questions the room did not answer
Who pays for a second tracking feed if the carrier will not widen its replay window. Whether the
dead-letter queue needs a retention policy of its own or inherits the main queue's 30 days.
```

```provenance
Source | change advisory board recording, 2026-03-18
Method | transcript traces, 214 segments; every agreed premise cites the range it came from
```
