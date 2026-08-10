# Typed fenced blocks — the grammar, written out by hand first

Wave 2 (#17). **This page was authored BEFORE the renderer**, because the issue named the
risk plainly: nobody had written a real document in this grammar, and `nodes` especially
might prove more awkward than the HTML it replaces. Writing one real example per type is
how that risk gets tested rather than assumed. What the authoring exercise found is
recorded at the bottom — including the two tags it changed.

A typed block is an ordinary fence whose info string names a **block type** instead of a
language. Any other markdown viewer degrades it to a code listing rather than mangling it,
and the author never writes a colour — which is what keeps the per-project visual design
language enforceable.

Every block is **line-oriented and pipe-delimited**. A field that needs a literal pipe
escapes it as `\|` (#39) — without that, `must | Preserve A | B | Needed by callers`
silently shifts every later field along and drops the last. Blank lines inside a block are skipped.
A trailing `| accent` marks emphasis in the block types that support it; the author names
*emphasis*, never a colour.

## Inline markdown inside a block — yes, in prose cells (#67)

**`**bold**`, `*italic*`, `` `code` `` and links work inside the prose cells of a typed block**,
exactly as they do in an ordinary paragraph. Write them by reflex; the file is markdown
everywhere else.

Until #67 they did not, and nothing said so either way. A published page showed its readers
`**two epic premises have gone stale**`, asterisks and all, in its most prominent callout — the
first thing on the page. Four rounds of structural measurement had called that page healthy.

Two limits, both deliberate:

- **A prose cell only.** A cell whose value becomes a class token — a callout's tone, a
  finding's severity — is never processed, because markup where a slug is expected would put
  author text into a class attribute. That is the same rule the decorators already followed.
- **Never inside fenced code.** Code stays verbatim and is only HTML-escaped.

Escaping is unchanged and is not weakened by this. The inline pass runs on text that has
**already** been `html.escape`d and only wraps it in a fixed set of tags — it is the identical
function prose has always used. `<script>` in a cell still renders as visible text.

## stats

`value | label | delta | sparkline | accent`. Everything after the label is optional
(#39). A value written as a proportion also draws a proportional bar; a sparkline is a
comma-separated number list rendered as inline SVG, needing at least two finite values —
anything undrawable keeps the numbers and drops only the graphic.

```stats
82 | sessions read
155 | findings mined | +12 | 3,5,4,8,9,11
28/44 | highs confirmed | accent
```

The third row is the LEGACY three-cell form and still means "accent", not "a delta of
`accent`". In a widened row the accent flag is field 5 and nothing else:
`155 | findings | +12 | 3,5,4 | accent`.

## verdict

```verdict
ship | The extraction is sound and the byte-identity contract held.
risk | Plain keeps its corruption by design; that is a stated limitation.
```

## chips

```chips
merged | done
review pending | wip
upstream fix required | blocked
```

## callout

```callout
warn | Do not fix `plain`
Byte-identity is an acceptance criterion. The corruption in `plain` is deliberate and
is asserted by a test.
```

## legend

```legend
done | shipped and verified on main
wip | in flight, not yet merged
blocked | waiting on a dependency outside this repo
```

## meter

```meter
Suite growth | 194 | 250
Children merged | 3 | 9 | accent
```

## findings

```findings
high | Emphasis ran over generated markup | A tag landed inside an href attribute.
medium | Nested list was a sibling | Invalid list structure, not merely cosmetic.
low | Ordered list lost its start number | `7.` rendered as item 1.
```

## steps

`id | title | text | level`. The fourth field is optional (#39) and is an RFC-2119 level —
one of `must`, `must-not`, `should`, `should-not`, `may`. Anything else warns and falls
back; blank means no level. `spec` composes this tag as `steps req` for requirement rows,
which is why the level lives here rather than in a second requirement component.

```steps
1 | Author the grammar | One real page per type, before any renderer work.
2 | Build the block engine | Unknown tags warn and degrade.
3 | Wire the templates | Wave 3, not this one.
```

```steps
R1 | Reject an unterminated header comment | Aborting beats guessing at a shape. | must
R2 | Name the offending file in the message | | should
```

The `uat` checklist variant has nowhere to show a level and warns rather than dropping it.

## nodes

```nodes
render
  markdown | the block and inline parser
  blocks | typed fenced blocks
  templates | per-doc-type CSS
scripts
  render-doc | the launcher
```

**Depth is indentation. Fields are `label | description | edge`, and both the
description and the edge are optional.** The third field, added by wave 3 (#13), names
the edge reaching this node from its parent, and a trailing `~` marks that edge proposed
rather than existing:

```nodes
router
  host-a | 2x Xeon, 126G RAM | 10G Cat6a
  host-b | no RJ45 port | 25G DAC ~
```

That is what a `workflow` diagram needs and what the arrow syntax in the specs doc was
reaching for. What wave 2 rejected was **pipes encoding hierarchy** — the edge label is
not hierarchy, so it comes back as a plain field while indentation keeps doing the
structural work. Two `nodes` blocks side by side are a before/after pair.

## timeline

Wave 5 (#39). A dated rail for `report` and `roadmap`. `time | title | detail | state`,
where state is one of `past`, `now`, `next` — anything else warns and falls back.

```timeline
09:14 | Alert fires | Checkout error rate crosses 2% | past
09:31 | Rollback begins | Previous image redeployed | past
10:02 | Recovery confirmed | Error rate back under 0.1% | now
```

## options

Wave 5 (#39). Side-by-side trade-offs for `design`. `title | for | against | stance`,
where stance is `chosen`, `rejected`, or blank for neutral — most options in a real
comparison are neither, so blank is meaningful and does not warn.

```options
Debounce in the component | Smallest diff, no new module | Re-implemented per call site | chosen
Shared hook | One implementation, testable | New public surface to maintain |
Server-side throttle | No client work at all | Round-trip on every keystroke | rejected
```

## steprail

Wave 5 (#39). A runbook rail for `workflow` — someone is following it under pressure and
needs to see where they are. `n | title | detail | kind`, where kind is `action` or
`check`, because a step you DO and a step you VERIFY are different things.

A DISTINCT TAG rather than a `steps` role: the second info-string word becomes a marker
`role` and is never consulted when choosing a renderer, so ```steps rail``` could not
work; and a template-selected variant would collide with `uat`'s checklist.

Every step and its detail are in the markup, before any script runs — a runbook that needs
JavaScript to be legible is worse than a plain one.

The current position is `details[open]`, styled by CSS. **Corrected by #57:** this paragraph
used to claim "exactly one step carries `aria-current`". It does not, and has not since #61 —
a static `aria-current` was tried, and native disclosure never moved it, so opening step two
left the highlight on the closed step one. `blocks.py` records that reversal; this page had
kept the abandoned claim. Measured: `aria-current` appears nowhere in the renderer except the
comment explaining its removal.

**What `steprail` is NOT for.** Disclosures a reader should be able to open together. One
`name` per document makes the items exclusive, and a one-row fence emits `open`, so neither
shape reaches "independent and closed by default". That is the `faq` block below.

```steprail
1 | Fetch at the pinned SHA | Never a branch name — a moving ref is a provenance race. | action
2 | Confirm twenty files landed | Abort if the count differs. | check
3 | Regenerate the manifest | Then review its diff by hand. | action
```

## faq

#57. `question | answer` — independent, closed-by-default disclosures. `spec` only.

Two attributes it deliberately does NOT emit, and they are the whole reason it exists:
**no `name`**, so opening one item leaves the others alone, and **no `open`**, so every item
starts closed. `steprail` is the only other block emitting `<details>` and it can produce
neither combination — its grouping is correct for a runbook rail, where there is a current
step, and wrong for a FAQ, where a reader compares two answers.

Native `<details>` with no script. The browser's own disclosure triangle is kept rather than
suppressed: `steprail` hides it because it supplies a rail indicator, a FAQ has none, and the
triangle is then the only thing telling a reader the row opens.

Both cells are required. A disclosure with no answer is an empty box; one with no question has
nothing to click.

```faq
Does it need a script? | No. Native `<details>`, so it works with JavaScript disabled.
Can two be open at once? | Yes. Each item is independent — that is the difference from `steprail`.
```

## composition

Lane B (#68, PR 1). `label | count | state` — a bar showing what a total is MADE OF, which the
single-value `meter` above cannot say: `meter` answers "how far along", this answers "made of
what". Segments are proportional to their counts; the legend carries the numbers. `roadmap` only.

State is an open word, not a closed set — `crit`, `warn` and `ok` are the three the roadmap
palette colours, and anything else keeps the neutral grey rather than being silently recoloured.
A non-numeric count drops the bar and warns; the legend still renders, because a wrong picture of
a measurement is worse than none.

```composition
critical | 1 | crit
unresolved | 2 | warn
ready | 4 | ok
```

## phases

Lane B (#68, PR 2). **Depth is indentation, as in `nodes`** — an unindented row is a phase, an
indented row is a work item inside it:

```phases
Windows + GPU | 3 of 12 done | warn
  FA-1 | Fan curve stalls above 60C | crit
  FA-2 | Telemetry lands in the ring buffer | ok
Mac parity | not started | note
  MP-1 | Metal backend | note
```

A phase is `title | badge | state`; an item is `id | text | state`. The badge is the author's own
words and the state is what colours it.

**The state is a CLOSED vocabulary (#166).** It used to be described here as open, and that
sentence is what caused the defect: authors reached for whatever word fit, `done` matched no CSS
rule, and the chip rendered grey while reading DONE. A word outside this table now prints a
warning and falls back to `note` — the text you wrote still renders, but the colour will not
pretend to be a state nobody defined.

| Write | Colour | Means |
| --- | --- | --- |
| `done`, `shipped`, `merged`, `ok` | green | The work is finished. |
| `active`, `wip`, `pending`, `warn` | amber | The work is moving. |
| `blocked`, `failed`, `crit` | red | The work is stuck. The item's id turns red too. |
| `planned`, `note` | grey | The work has not started. Grey here is a CHOICE, not a gap. |

**Prefer the status word to the severity word.** `ok`, `warn` and `crit` are kept because pages
already published use them, and repainting those pages is not a fix. On a rail whose job is to
report status, `done` says what `ok` only implies — write the status word in new documents.

**One vocabulary, three consumers.** These words also drive the phase badge, the derived bar and
`source_lint`'s stale-child check, which reads a row as finished or open. That is why the set is
closed: a word one of the three cannot see is a hole in the other two.

**A typed chip: `<label>:<level>` (#167).** A bare token says one thing. Write a compound one
and the chip says two — the **label** becomes the word, the **level** picks the colour:

```phases
Backlog | | epic:could
  #347 | Fetching stalls above 60C | bug:must
  #348 | Add the export button     | feature:should
  #349 | Tidy the imports          | chore:could
  #350 | Ship the thing            | task:done
```

That renders BUG in red, FEATURE in amber, CHORE in grey and TASK in green.

| Level | Colour | Labels |
| --- | --- | --- |
| `must` | red | `bug`, `feature`, `chore`, `hardening`, |
| `should` | amber | `epic`, `action`, `note`, `task` |
| `could` | grey | |
| `done` | green | |

Bare tokens keep working unchanged — the colon is the only switch. An unknown label or level
warns and falls back to `note`, and shows your whole original text rather than the half that
parsed. Full rules: `design-language.md`.

**Order is the grammar.** Phases render in the order they are written and the renderer numbers
them `01`, `02`, … — that number is the only reason a reader can see sequence rather than infer
it, and it is the gap #68's title names.

**The bar is derived, never written twice.** Each phase gets one segment per item, coloured by
that item's state. An author who wrote the items has already written the bar; asking for it again
would let the two disagree.

## flow

Lane B (#76). A real flow chart for `workflow` — boxes joined by arrows. `nodes` is an
indentation TREE and answers "what contains what"; this answers "what happens next", which is a
different question and so a different type.

`kind | label | branch`, one row per node, in order:

```flow
term | A request arrives
proc | Validate the token
dec | Is the token valid?
proc | Serve the content | yes
term | Return 401 | no
```

`kind` is one of `term` (a start or an end, drawn as a pill), `proc` (a step, a rectangle) or
`dec` (a decision, a diamond). Anything else warns and falls back.

The optional third field labels **the arrow arriving at that node**, which is where a flow chart
writes "yes" and "no" — on the arrow, never inside the box. On the first row nothing arrives, so
a branch there is dropped with a warning.

`n` nodes draw `n-1` connectors. Only the label is required: a bare `proc` renders an empty step
rather than dropping the row.

## provenance

```provenance
source | docs/planning/2026-08-01-publish-engine-extraction-plan.md
issue | #17
measured | 2026-08-01
```

## What authoring this actually found

Three things, and they changed the design rather than being written around:

1. **`nodes` was the awkward one, exactly as predicted — so its grammar changed.** The first
   attempt used pipes for hierarchy (`render | markdown | the parser`), which becomes
   unreadable at two levels and impossible at three: the pipe count encodes depth, so the
   author has to count separators to see structure. It now uses **indentation for depth**,
   which reads as a tree in the source. That is the whole point of authoring first.
   (Wave 2 shipped one pipe, splitting label from description. Wave 3 added the optional
   third field for the edge label — see the section above. Depth is still indentation;
   what was rejected here was pipes-as-hierarchy, not pipes.)

2. **`callout` needs its first line to be a header, not a row.** Every other type is uniform
   rows. A callout is a tone plus a title plus prose, so its first line is `tone | title` and
   everything after is body text. Forcing it into uniform rows produced unreadable source.

3. **`meter` needs an explicit maximum.** Writing `Children merged | 3` and expecting the
   renderer to infer a scale was tempting and wrong — the scale is the author's intent, not
   the renderer's guess. `label | value | max` is explicit and cannot be misread.

One deliberate non-finding: `stats`, `chips`, `legend`, `findings`, `steps` and `provenance`
were all comfortable to write as uniform pipe-delimited rows on the first attempt, and are
unchanged from the issue's sketch.
