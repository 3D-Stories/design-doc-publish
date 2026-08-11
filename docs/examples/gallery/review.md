Independent review of the Halyard webhook ingestion branch, at commit `7c41e02`. Report only —
nothing here was changed on the author's behalf.

```composition
critical | 1 | crit
high | 2 | warn
medium | 3 | note
```

```findings
critical | Signature check runs after the body is parsed | A malformed payload reaches the parser before anything verifies it came from the carrier. Reverse the order. | ingest.py:88, ingest.py:140
high | Replay has no upper bound | A replay over a wide window loads every event into memory before writing any. A month-long gap would exhaust the box. | replay.py:52
high | Idempotency key is the carrier's event id alone | Two carriers can and do issue the same id. Key on carrier plus id. | store.py:31
medium | Freshness check compares to local clock | Carrier timestamps are their clock, ours is ours. Drift shows up as false staleness. | freshness.py:19
medium | No metric for dropped webhooks | Loss is invisible until a customer notices. | (absent)
medium | Test fixture reuses one carrier | The multi-carrier path is untested end to end. | tests/test_ingest.py
```

```verdict
refuted | The claim that replay is bounded by the retention window does not hold — retention is 30 days, and replay reads the whole range at once.
```

```provenance
Reviewed | commit 7c41e02, branch feat/webhook-ingest
Method | read every changed file; ran the suite; replayed a 6-hour window on staging
Not checked | carrier-two behavior, because no contract exists yet
```

## What I would fix first

The critical finding, and only that, before this merges. The two highs are cheap but they are not
load-bearing for correctness in the single-carrier case that ships first.
