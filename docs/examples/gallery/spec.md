Behavior of the Halyard webhook endpoint, pinned precisely enough to build and test against.

## Requirements

```steps req
R1 | The endpoint MUST verify the signature before parsing the body | An unverified payload is untrusted input and must not reach the parser.
R2 | The endpoint MUST return 202 for an accepted event | Acceptance means persisted, not processed.
R3 | The endpoint MUST return 401 for a bad or absent signature | The body is discarded unread.
R4 | The endpoint MUST be idempotent on (carrier, event_id) | A carrier may redeliver any event any number of times.
R5 | The endpoint SHOULD respond within 200ms | Carriers retry aggressively past that.
R6 | The endpoint MUST NOT call the carrier API synchronously | That couples our availability to theirs on the write path.
```

## Acceptance criteria

```steps ac
1 | Signature precedes parse | Proven by a malformed body with a valid signature returning 400, and a malformed body with an invalid signature returning 401.
2 | Redelivery is safe | The same event delivered five times yields one row and five 202s.
3 | Cross-carrier ids do not collide | Two carriers sending event_id "1" yield two rows.
4 | Latency holds | p99 under 200ms at 500 events per second.
```

## Vocabulary

```legend
MUST | a conformance requirement; a build that fails it is not this spec
SHOULD | strongly expected; deviation needs a stated reason
event_id | the carrier's own identifier, unique only within that carrier
```

## Out of scope

Ordering. Carriers do not promise it and this endpoint does not impose it. Consumers that need
ordering must sort by the carrier's scan timestamp, and must tolerate ties.
