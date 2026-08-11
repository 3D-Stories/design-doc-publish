Acceptance pass for Halyard webhook ingestion, phase 2. Walk this in order on staging. Tick each
box as you go — the page remembers your ticks locally.

```steps ac
1 | A signed webhook is accepted | POST a carrier-signed payload to /hooks/carrier-a. Expect 202 and a row in raw_events within one second.
2 | An unsigned webhook is refused | Send the same payload with the signature header removed. Expect 401 and NO row in raw_events.
3 | A replayed webhook is idempotent | POST the same signed payload twice. Expect 202 both times and exactly one row.
4 | The replica reflects the move | Fetch the parcel. Its scan point must be the one in the webhook, not the older cached one.
5 | A dropped window self-heals | Stop the consumer for two minutes, restart it, run replay. Every skipped event lands, in order.
6 | Stale reads never appear | Move a parcel twice inside ten seconds. The second read must never return the first scan point.
```

```verdict
confirmed | Steps 1 through 4 pass on staging build 4192.
```

## Notes for whoever runs this

```faq
Do I need carrier credentials? | No. Staging accepts a test signing key; it is in the shared vault under halyard/staging.
What if step 5 hangs? | The replay tool waits for a lock. Check whether another pass is already running before assuming it is broken.
Can I run these out of order? | Steps 1 to 3 are independent. Steps 4 to 6 all assume step 1 passed.
```
