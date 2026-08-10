# Updating a living document

A first publication is a rendering problem. An **update** is a different problem, and the publish
path did not use to know the difference. This file is what the failure messages point at.

Measured on 2026-08-08, two classes of defect reached live pages in one session:

1. A milestone was marked shipped on one surface while four sub-rows, a narrative section and a
   cross-reference kept saying it was open. Twice in a row.
2. `~~strikethrough~~` reached a live page as six literal tilde characters.

Every check in the pipeline passed both times, and every one of them was correct: they all answer
*"did the bytes I linted reach the page?"* Nobody was asking whether the source said what its
author meant.

## Why one edit is never enough

**These templates denormalize on purpose.** One fact deliberately appears in several typed blocks,
because each block serves a different reading: a count in the `stats` strip, the same count as a
`meter` numerator, the thing it counts as rows in `phases`, its history in `timeline`, its
consequence in a `callout`, and the argument for it in prose. That is what makes the page readable
in one screen.

It is also what makes an update a **multi-site edit, every time**. The natural move — find the
section this change is *about*, edit it, report the document updated — is wrong, and it is wrong
quietly.

Measured on `rawgentic`'s rolling campaign log: **3,364 lines, 57 sections, and a single issue
number appearing 13 times.** Editing the one section that owns it leaves twelve stale mentions and
a page that now contradicts itself.

## A vocabulary change is a sweep too, and it reaches other people's documents

Everything below is about one document going stale against the facts. A **renderer vocabulary**
change goes stale in the opposite direction: the document is untouched and correct, and the words
it uses stop being the best ones available.

Measured, 2026-08-10. `rawgentic-plan-graph` was published twice by a session running a renderer
that already understood the typed `<label>:<level>` chip, and every chip on the page was a bare
severity word. Nothing was broken. The engine was current, the document was valid, and the author
had no way to know the grammar existed.

**So when you change what the renderer accepts, three things move, and only the first is automatic:**

1. **The skill's own docs.** `SKILL.md`, `design-language.md`, `typed-blocks-grammar.md`. This one
   is enforced — `test_chip_vocabulary_is_documented.py` fails when the renderer accepts a token
   `SKILL.md` does not name. It exists because a vocabulary documented only where nobody reads it
   is not documented.
2. **A publish-time nudge**, if the old spelling is still valid. The renderer prints one advisory
   per block naming the new grammar. It is an advisory and never a failure: the old spelling must
   keep working, or you have broken every page already published.
3. **Consuming documents**, by hand, one at a time. There is no sweep command for this, and
   pretending otherwise is the trap.

**Why (3) cannot be automated, stated plainly because it looks automatable.** `warn` carries
urgency and no work type. Nothing in a row that reads `warn` says whether the work is a chore or
a feature, so a migration would have to invent that answer and would state it with the same
confidence as a fact the author actually wrote. Convert the half that is derivable — the level —
and leave the label to a person:

| Old bare token | Level | Label |
| --- | --- | --- |
| `crit` | `:must` | you choose |
| `warn` | `:should` | you choose |
| `note` | `:could` | you choose |
| `ok` | green | you choose |

**Never convert a document whose tokens are deliberate.** Check for a `legend` block first. A
document that defines its own key meanings has an author who chose those words, and the two
schemes may not measure the same thing — a readiness axis is not a priority axis. Ask before
rewriting one.

## The sweep

### 1. Inventory before you touch anything

List every site that mentions what you are about to change — the issue number, the symbol, the
version, the date, the count:

```bash
grep -nE '#906|whisper_batch|0\.2\.76' docs/planning/campaign-log.md
```

**That hit count is how many edit sites you have.** Write it down before you start, because after
you start you will be tempted to stop at the first section that looks right.

### 2. Move the numbers that are derived, not written

A body change silently invalidates every number computed from the body:

| Surface | What breaks |
|---|---|
| `stats` values | a count that no longer matches what it counts |
| `meter` numerator and denominator | progress that did not move when the thing moved |
| `legend` descriptions carrying counts | "12 issues" when there are now 13 |
| the number of rows in a `phases` block | the rail disagrees with the tally above it |
| any two blocks stating the same figure | they now disagree, and a reader cannot tell which is right |

When the same figure appears twice, check it with a script rather than by eye. A contradiction
between two tables destroys trust in every other number on the page.

### 3. Change a fact; re-date a record

Not every mention should move. A `timeline` row, a dated decision, or an "as of `<date>`" note is a
record of what was true then, and rewriting it erases the reason a decision looks the way it does.
Update the live claim, leave the historical one, and let its date do the work. If an old claim is
now actively misleading, mark it superseded beside its date rather than deleting it.

### 4. Re-run the inventory, then say both numbers

Every remaining hit is either updated or deliberately historical. There is no third category.

Then state how many sites the grep found and how many you changed. If they differ, say why in one
line. **"Updated" with no site count is the claim that has been wrong before**, and a reader has no
way to check it.

## What the publisher now refuses, so you do not have to remember it

Two of the three misses are mechanical, so `publish_doc.py` catches them and **refuses to deploy**.

| Refused | How it is detected |
|---|---|
| a phase that reads done while its own child rows still read open | a `phases` block states parent and child by indentation, so a `done` phase above a `note` child is the document contradicting itself — no previous version needed |
| a subject marked done in this revision, still called open elsewhere | it diffs against the last committed version and matches the identifier against the status vocabulary on every other line |
| markdown this renderer passes through literally | eight constructs, each confirmed by rendering it — see below |

`--ack-stale` publishes past the first two, for lines that are deliberately historical. It prints
how many stale lines went out. `--allow-unsupported-markdown` publishes past the third.

### The third miss is yours, and no flag helps

A narrative paragraph that still opens as a to-do list — *"records must be trustworthy: #888 …
#363 …"* — contains **no status word at all**, so nothing mechanical can tell it from a sentence
that is still true. The same goes for a summary count written in prose, a forward-looking sentence
that should now be past tense, and a cross-reference phrased as an intention.

The grep sweep above is what finds those. That is why the sweep stays a discipline instead of
becoming a flag.

## Markdown this renderer does not implement

Each of these was confirmed to survive into the page as its own source characters, by rendering it
and reading the result. Publishing refuses on all eight by name and quotes the offending line.

| You write | What reaches the page | Write instead |
|---|---|---|
| `~~text~~` | literal tildes | the words, or "superseded" in prose |
| `- [ ] item` | literal `[ ]`, and the bullet is consumed | a `steps` or `chips` block |
| `<https://x>` | literal angle brackets, and it is not a link | `[text](url)` |
| `[^1]` | the marker and its definition, both literal | inline the note |
| `==text==` | literal equals signs | `**bold**` or a `callout` |
| `H~2~O`, `X^2^` | literal tildes and carets | spell it out |
| `### H {#id}` | the braces become part of the heading | nothing — the renderer assigns ids |
| `:rocket:` | literal colons | paste the character |

A construct that merely renders imperfectly does **not** belong on that list. The test is whether
the author's own keystrokes appear on the page. `scripts/tests/test_source_lint.py` re-derives
every row from the live renderer, so a release that starts supporting one of them fails the suite
rather than leaving a stale warning in place — a warning about a construct that now works is noise,
and noise is what gets a gate switched off.
