"""`minutes` — the record of a meeting (#59, the fourteenth template).

First-read element: the ledger. How many premises the room agreed, how many courses of action it
decided, how many actions it assigned, how many questions it left open — before any of the detail.

**A minutes document is not a restyled `analysis`.** Robert's Rules of Order says minutes record
what was **done**, not what was said, and calls summarizing discussion "improper" (confirmed from
two fetched sources, one of them `robertsrules.com`). The `analysis` style is largely a record of
what was said, so this is a different document rather than a new stylesheet over the same content.

## The vocabulary, and why it is documented here rather than merely used

One word for one thing:

* **agreed** — a premise the room accepted as true. Never a course of action.
* **decided** — a course of action the room chose. Never a premise. `chose` is its prose verb.
* **action** — a thing one named person will do, by a date or an explicit completion condition.
* **open** — a question the room did not answer.

**The word `settle` is never used for an agreement**, because it reads as a decision. And
`resolved` appears only when reproducing the exact wording of a formal resolution — never as this
template's generic decision marker, because borrowing it would imply this template follows a
convention it diverges from.

Why the two registers are worded differently while no FIELD encodes the difference: research found
no practitioner vocabulary separating an agreed premise from a decided course of action. Two lanes
looked; neither found one. Practice makes the distinction by WORDING — an unvoted consensus takes
a hedge phrase ("it was the consensus that", "each director present expressed his/her approval
of", "doubt was expressed as to"), while a vote takes a full motion record ("the exact wording of
the resolution, the names of proposers and seconders, and the names of those voting in favor of or
contrary to the resolution"). A stylesheet cannot enforce wording, so this template does the one
thing it can: it gives the two a separate region each, and documents the convention here.

## No committed-artifact precedent exists for this shape, and that is the point

Two currently-used governance minutes formats answer "how do you mark a decision" in opposite
ways, and both were fetched and read in full:

* `openui/open-ui` and `json-ld/minutes` tag a decision inline with `RESOLVED:` inside a
  per-line-timestamped transcript. These two are **one witness, not two** — both are driven by the
  same W3C bot pair, Zakim and RRSAgent.
* `nodejs/TSC` tags nothing at all. A reader infers a decision from prose dialogue. It uses
  neither bot and is the genuinely independent second witness, and the more recent page.

**Neither puts a synthesized answer above the record.** In both, a reader must scan the transcript
line by line to find a decision. The second was read specifically to try to falsify that, which
failed. So a summary-first minutes page has **no committed-artifact precedent**, and this template
diverges from both on purpose: `docs/design-language.md` says the first-read column "is the
question each type answers in its opening screenful", so a minutes style that made a reader scan
would contradict the engine it ships in. The divergence fixes the exact defect the precedent
carries.

On the sharper disagreement underneath — Robert's Rules says record what was DONE, the W3C
convention keeps the full record of what was SAID — Robert's Rules wins on what the document IS.
The goal the W3C convention serves, recoverable reasoning, is met by CITATIONS instead of by a
transcript. A third, independent source sits between them and is why this is a real middle path: a
nonprofit-law guide says minutes "should not be a transcript of all that was said at the meeting"
but SHOULD carry "a summary of key points from any reports given to the board" and should document
"alternatives considered for important decisions". Hence the `options` region, and no transcript
region at all.

**What that exclusion does and does NOT achieve.** `timeline` is deliberately absent from this
type's `DOC_TYPE_TAGS` entry — but that is advisory, not enforcing: `blocks.render_fence` prints a
`not accepted by doc type ... rendering it anyway` **warning** and renders the block regardless,
and no strict mode exists. Transcript-like PROSE inside an accepted block is not detectable at
all. The one place the exclusion really bites is this repository's own documents:
`test_template_bodies.py` fails on any fixture that uses a block its type rejects. An earlier
draft of this docstring claimed the transcript shape was enforced. It is not, and saying so was
the defect.

## The trace citation is this template's own convention

The one published placement convention found handles a **single** timecode and says in its own
words "Pick a house style, write it down, and reuse it" — so it is one vendor's house style, not
an authority. Meanwhile 90 of the first real document's 120 traces carry a distinct end segment.

So `_(trace: 22:32, segments 381 to 393)_` follows nobody. It rides in the `findings` block's
fourth field, the provenance tail, styled by the `findings.tail` marker. End placement is a house
convention here too. And a trace identifier is not called a timecode unless it is one: `22:32` is
a timecode, while `segments 381 to 393` are transcript segment indices and are not.

## A meeting that decided nothing

`verdict` is in this style's `FIRST_READ_DEVICES` entry on purpose, so **every** minutes page
carries a decided register. A meeting that chose no course of action carries one holding a single
neutral row, which `.mn-decided .blk-row.is-none` styles quietly rather than as a warning. That
satisfies four distinct regions and an honestly empty decided register at the same time — which an
ABSENT register cannot do. The ledger says `0` beside it in the opening screenful, because an
absence rendered as a printed zero is a statement somebody made.

No `BEFORE_BODY`: a minutes page's content is per-meeting, so there is no constant furniture to
emit, and this template therefore puts no unescaped bytes on the page at all. No script — `uat`
remains the only interactive template.
"""

NAME = "minutes"

# 960px is unused by any other style, which the frame gate requires: its clash dict is pinned to
# exactly {"1240px": ["dashboard", "uat"]}, so a third collision fails by design. The width came
# from the Step 3 peer consult and its reason is the better one — the `findings` provenance tail
# carries a ranged trace citation, the longest inline element on the page, and 60px over the
# default buys it a line it would otherwise wrap.
#
# **The ground is the flat default, DECLARED.** A minutes page is an archival record, and a
# decorative wash on a record is wrong. The gate asks that a ground be DECIDED, not that it
# differ (owner decision 2026-08-02), and this is precisely the case that rule was written for.
#
# `header_rule` at 3px double is the masthead of a record, and it is the one slot here doing real
# visual work. `h2_size` and `h2_rhythm` are deliberately NOT declared: this is a sectioned style,
# so `render_sections` re-emits every `##` as `h3` and both slots would be inert (D70).
FRAME = {
    "ground": "var(--bg)",
    "measure": "960px",
    "gutter": "0 22px 80px",
    "header_pad": "34px 0 16px",
    "header_rule": "3px double var(--line)",
    "header_gap": "16px",
    "h1_size": "clamp(21px,2.9vw,27px)",
}

SECTIONS = {"section_class": "mn-section"}

# Slots, not class names. A fence role only ever selects a KEY here, so no author text can reach
# a class attribute — `test_marker_values_are_slugs` pins the values.
MARKERS = {
    "chips:meetingbar": "mn-meetingbar",
    "chips:attendees": "mn-attendees",
    "stats": "mn-ledger",
    "findings": "mn-agreed",
    "findings.tail": "mn-trace",
    "verdict": "mn-decided",
    "options": "mn-alternatives",
    "steps": "mn-actions",
    "callout:open": "mn-open",
}

CSS = """
.tpl-minutes .mn-section{margin-top:26px}

/* The masthead facts: kind of meeting, date, quorum, whether the previous minutes were approved
   — the binding RONR 48:4 field list. Small and dense, because nobody reads it twice. */
.tpl-minutes .mn-meetingbar{display:flex;flex-wrap:wrap;gap:6px 10px;margin:2px 0 14px;
font-size:12px}
.tpl-minutes .mn-meetingbar .blk-chip{border-radius:3px;padding:2px 7px}

/* Attendees are a separate region from the facts, and must stay one: both are the `chips` tag,
   so the publish gate cannot tell them apart and a page dropping this one still publishes.
   `test_minutes_template.py` is what guards it. */
.tpl-minutes .mn-attendees{display:flex;flex-wrap:wrap;gap:7px;margin:0 0 22px}
.tpl-minutes .mn-attendees .blk-chip{border:1px solid var(--line);background:var(--surface)}

/* THE FIRST-READ ELEMENT. What this meeting did, in four numbers, before any detail. The zero
   for a meeting that decided nothing is printed here rather than omitted. */
.tpl-minutes .mn-ledger{border-top:1px solid var(--line);border-bottom:1px solid var(--line);
padding:16px 0;margin:0 0 26px}
.tpl-minutes .mn-ledger .blk-stat{border:0;background:none;padding:0 14px 0 0}

/* The agreed register. Left-ruled in the accent, because an agreed premise is the thing a reader
   came for. The `agreed` word itself sits in the severity slot and is shown, not hidden. */
.tpl-minutes .mn-agreed .blk-finding{border-left:3px solid var(--accent);
background:var(--surface);border-radius:0 8px 8px 0;padding:10px 14px;margin:8px 0}
.tpl-minutes .mn-agreed .blk-sev{color:var(--accent);font-size:11px;font-weight:700;
letter-spacing:.07em;text-transform:uppercase}
.tpl-minutes .mn-agreed .blk-title{font-weight:600}

/* The trace citation. Visually secondary, monospace, and it WRAPS rather than overflowing — a
   ranged citation is long. Never hover-only: a citation a reader cannot see in print is not one. */
.tpl-minutes .mn-trace{display:block;margin-top:6px;color:var(--ink-3);font-size:11.5px;
font-family:ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere;white-space:normal}

/* The decided register — mandatory on every minutes page, so this styles BOTH the real case and
   the empty one. `is-none` is the neutral treatment: quiet, not a warning, because a meeting that
   chose nothing is a legitimate meeting and must not read as a defect. */
.tpl-minutes .mn-decided .blk-row{border:1px solid var(--line);border-left:3px solid var(--accent);
background:var(--surface);border-radius:0 8px 8px 0;padding:11px 14px;margin:8px 0}
.tpl-minutes .mn-decided .blk-key{color:var(--accent);font-size:11px;font-weight:700;
letter-spacing:.07em;text-transform:uppercase}
.tpl-minutes .mn-decided .blk-row.is-none{border-left-color:var(--line);background:none}
.tpl-minutes .mn-decided .blk-row.is-none .blk-key{color:var(--ink-3)}
.tpl-minutes .mn-decided .blk-row.is-none .blk-text{color:var(--ink-2)}

/* Alternatives considered — the middle path between "record only what was done" and "keep the
   whole transcript". This is the only two-column element on the page, and the reason for 960px. */
.tpl-minutes .mn-alternatives{display:grid;gap:10px;margin:10px 0}
.tpl-minutes .mn-alternatives .blk-opt{border:1px solid var(--line);border-radius:8px;
padding:11px 14px;background:var(--surface)}
.tpl-minutes .mn-alternatives .blk-lbl{color:var(--ink-3);font-size:10.5px;font-weight:700;
letter-spacing:.08em;text-transform:uppercase;margin-right:5px}

/* Action items. The owner is TEXT in the third field — no block carries an owner field, and
   modelling one properly is a renderer change (`report.py` hit the same wall and declined it).
   The documented display form is `Owner - action - due date or condition`. */
.tpl-minutes .mn-actions{padding-left:0;list-style:none;counter-reset:mn-act}
.tpl-minutes .mn-actions .blk-step{counter-increment:mn-act;display:grid;
grid-template-columns:auto 1fr;gap:4px 12px;border-bottom:1px solid var(--line);padding:10px 0}
.tpl-minutes .mn-actions .blk-n{color:var(--ink-3);font-family:ui-monospace,monospace;
font-size:12px;font-weight:700}
.tpl-minutes .mn-actions .blk-title{font-weight:600}
.tpl-minutes .mn-actions .blk-text{grid-column:2;color:var(--ink-2);font-size:13px}

/* Questions the room did not answer. Named as its own region so an open question cannot be
   mistaken for either register. */
.tpl-minutes .mn-open{border-left:3px dashed var(--line);background:none;padding-left:14px}
.tpl-minutes .mn-open .blk-title{color:var(--ink-3);font-size:11px;font-weight:700;
letter-spacing:.07em;text-transform:uppercase}
"""
