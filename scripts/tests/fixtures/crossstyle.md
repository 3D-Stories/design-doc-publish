Lede paragraph before any section, so preamble wrappers engage.

## First section

Body text with `code`, **bold**, and a MUST that decorators may chip.

```stats
1240 | requests | +12% | 3,5,4,8,7,9
28/44 | highs confirmed | | | accent
```

```timeline
09:14 | Alert fired | Pager went out. | past
09:31 | Mitigated | Rolled back. | now
```

```options
Inline hook | fewest files | re-runs on every render | chosen
External lib | battle-tested | a new dependency | rejected
```

```steprail
1 | Fetch the tree | git fetch origin | action
2 | Verify the base | git log -1 origin/main | check
```

```findings
high | A thing broke | It broke in the obvious way. | gh api, PR #15
medium | A smaller thing | Less obvious. |
```

```steps req
R1 | The client MUST retry | Once, with backoff.
R2 | The client SHOULD log | At debug level.
```

```steps ac
1 | Suite green | Whole gate, exit 0.
```

```nodes compare
today
  one | the current shape | WAN
proposed
  two | the new shape | LAN
```

```callout decision
note | We chose B
Because A costs more.
```

```chips statebar
main at 3a85cc5 | done
wave 3 | wip
```

```verdict
confirmed | The claim holds.
```

```legend
solid | an existing link
```

```meter
Children merged | 3 | 9
```

```provenance
Measured | 2026-08-02 on main
Method | whole gate, exit 0
```

## Second section

| Column | Other |
|---|---|
| a | b |

> A quoted line.

## Third section — the four tags this probe used to miss (#148)

Added because a fixture that claims to exercise the component vocabulary was missing four of
seventeen tags, and two of those (`phases`, `flow`) are first-read devices — so `roadmap.html` and
`workflow.html` would have failed the #130 gate had anyone published them.

```phases
Windows + GPU | 3 of 12 done | warn
  FA-1 | Fan curve stalls above 60C | crit
  FA-2 | Telemetry lands in the ring buffer | ok
Mac parity | not started | note
  MP-1 | Metal backend | note
```

```flow
term | A request arrives
proc | Validate the token
dec | Is the token valid?
proc | Serve the content | yes
term | Return 401 | no
```

```composition
critical | 1 | crit
unresolved | 2 | warn
ready | 4 | ok
```

```faq
Does it need a script? | No. Native `<details>`, so it works with JavaScript disabled.
Can two be open at once? | Yes. Each item is independent — that is the difference from `steprail`.
```
