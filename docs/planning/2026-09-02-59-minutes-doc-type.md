# Issue #59 — a `minutes` doc type and style for meeting minutes

Design for the fourteenth template. It is a stylesheet change: a new declaration-only module, its
registration, its documentation surfaces, and its two generated pages. The renderer is not
touched.

## The fork this design settles, and the evidence it settles it on

Issue #59 left one question open on purpose: **how is a decision marked?** Two fetched, in-use
governance formats answer it in opposite ways.

- W3C's bot convention (`openui/open-ui`, `json-ld/minutes`) tags a decision inline with
  `RESOLVED:`. These are **one witness, not two** — both run the same Zakim/RRSAgent bot pair.
- The Node.js TSC (`nodejs/TSC`) tags nothing. A reader infers a decision from prose. It is the
  genuinely independent second witness, and the more recent page.

**Decision: tag explicitly. A decision gets its own typed region.**

The tiebreaker is mechanical rather than aesthetic, which is why it is decisive here. This engine
refuses a styled page that omits the blocks its style opens with (`check_style_devices`, #130,
reading `blocks.FIRST_READ_DEVICES`), and every region on a page is a TYPED block. An untagged
prose shape is not a thing this engine can render under a style at all — it needs
`--skip-component-checks`, whose meaning is "this document really is prose". Choosing the Node.js
shape would make every minutes page take the escape hatch. So the W3C side wins on this platform,
and the reason is the platform, not the vote count.

## The sharper disagreement, and how this template serves both sides

Robert's Rules says minutes record what was **done**, and that summarizing what was said is
"improper". The W3C convention keeps the **full timestamped record of what was said** and tags
outcomes inside it. The two most-cited precedents disagree about what a minutes document IS.

**Decision: Robert's Rules wins on what the document IS. The goal the W3C convention serves —
recoverable reasoning — is met by CITATIONS, not by a transcript.**

A third, independent fetched source sits between them, and it is the reason this is a real middle
path rather than a compromise. A nonprofit-law guide (`charitylawyerblog.com`, fetched 2026-09-02
for this design, which upgrades research item I1 from inferred to confirmed) says minutes "should
not be a transcript of all that was said at the meeting", but SHOULD carry "a summary of key
points from any reports given to the board" and should document "alternatives considered for
important decisions".

So the template provides an **alternatives-considered** region and **no transcript region at
all**, and `timeline` is deliberately **excluded** from `DOC_TYPE_TAGS["minutes"]`.

**An earlier draft of this paragraph called that "enforced rather than advised". It is not, and the
overstatement was caught twice — by this design's own self-review and by the cross-model review.**
`blocks.py:1296-1298` prints a warning and renders a rejected block **anyway**, and no strict mode
exists. Measured with `/tmp/wf2-59-probe3.py`: rendering the 19-block cross-style fixture as
`minutes` puts all nine rejected tags on the page, each with a
`block type 'timeline' is not accepted by doc type 'minutes' — rendering it anyway` warning.
`design-system` behaves identically, accepting 4 tags while its committed page carries 17, so this
is the repository's normal advisory behaviour rather than a defect.

The honest statement, which the AC13 docstring carries in the same words: **the template provides
no dedicated transcript region and its type policy warns on `timeline`. Avoiding transcript-like
prose inside an accepted block stays an authoring rule, and nothing checks it semantically.**

There is exactly one place the exclusion really bites, and it is worth having:
`test_template_bodies.py:463` asserts the ABSENCE of that warning, so any fixture in this
repository that uses a block its type rejects turns the suite red. The policy is enforced against
this project's own documents, never against a user's.

**Summary-first has no committed-artifact precedent, and that is the point.** Both W3C artifacts
were read in full — the second specifically in an attempt to falsify this, which failed. In both,
a reader must scan the transcript line by line to find a decision. This repository's own design
language requires the opposite: `docs/design-language.md` says the first-read column "is the
question each type answers in its opening screenful". A minutes style that made a reader scan
would contradict the engine it ships in. So the divergence is forced by local convention and it
fixes the exact defect the precedent carries. AC13 requires the module docstring to say so, name
both precedents, and say why it diverges from each.

## Vocabulary — one word for one thing (AC7)

| Word | Means | Never used for |
|---|---|---|
| **agreed** | a premise the room accepted as true | a course of action |
| **decided** | a course of action the room chose | a premise |
| **action** | a thing one named person will do, by a date or an explicit completion condition | a decision |
| **open** | a question the room did not answer | either register |

`settle` is not used for an agreement, per AC7 — it reads as a decision. `chose` appears only as a
synonym inside prose, never as a register label.

**`resolved` is not this template's decision marker.** Borrowing it would imply this template
follows a convention it diverges from. The peer consult sharpened the rule and it is adopted
verbatim in effect: `resolved` appears **only** when reproducing the exact wording of a formal
resolution, never as the generic marker. That keeps the word available for the one job Robert's
Rules actually needs it for — recording a motion's exact wording — without claiming the W3C
convention.

**Why the two registers are worded differently, and why no field encodes it.** Research item C6:
two lanes looked for a practitioner vocabulary separating an agreed premise from a decided course
of action, and neither found one. Practice makes the distinction by WORDING — an unvoted consensus
takes a hedge phrase ("it was the consensus that", "each director present expressed his/her
approval of", "doubt was expressed as to"), a vote takes a full motion record ("the exact wording
of the resolution, the names of proposers and seconders, and the names of those voting in favor of
or contrary to the resolution"). Both quotations are from the fetched nonprofit-law source. A
stylesheet cannot enforce wording, so the template does the one thing it can: it gives the two a
**separate region each**, and documents the wording convention in its own docstring. That is what
the AC7 clause "documents which words it uses" buys.

## Regions, in document order

Each is an existing block. No new block tag, per the scope in the issue.

| # | Region | Block | Grammar | Why this block |
|---|---|---|---|---|
| 1 | Meeting facts | `chips` role `meetingbar` | label, tone | the binding RONR 48:4 field list — kind of meeting, date, quorum, whether the previous minutes were approved |
| 2 | **Attendees** | `chips` role `attendees` | name and role, tone | AC6. A row of short labels is exactly a chip row |
| 3 | **The ledger** | `stats` | n, label, blank, blank, accent | the summary-first answer. See AC8 below — this is the region that carries the zero |
| 4 | **Agreed premises** | `findings` | agreed, premise, why, trace tail | the only 4-field block, and its fourth field is a provenance tail — so a premise carries its citation in the markup rather than in prose |
| 5 | **Decided courses** | `verdict` | decided, the course chosen | a key word plus text, one row per decision. That key word IS the inline marker this design chose. **Gate-mandatory** — see AC8 below |
| 6 | Alternatives considered | `options` | title, for, against, stance | the words of the middle-path source, and its stance field marks the chosen one |
| 7 | Action items | `steps` | id, what, who and by when | owner as TEXT, per the out-of-scope decision in the issue and the precedent recorded at `report.py` lines 17 to 19. Documented display form, from the peer consult: `Owner — action — due date or condition` |
| 8 | Open questions | `callout` role `open` | tone, title, then prose | what the room did not answer |
| 9 | Provenance | `provenance` | label, value | where these minutes came from |

## AC8 — the meeting that decided nothing

This is the criterion most likely to be got wrong, so it is designed for directly rather than
tested for afterwards.

**The mechanism: `FIRST_READ_DEVICES["minutes"]` is `{"chips", "stats", "verdict"}` — so the
decided register is MANDATORY on every minutes page, and a meeting that decided nothing carries it
holding one neutral row.**

**This reverses an earlier draft of this design, and the peer consult is why.** That draft set
`{"chips", "stats"}` and left `verdict` out, on the reasoning that everything in the set becomes
mandatory, so a page whose meeting decided nothing could not carry it. **That reasoning was
wrong.** `lint.check_style_devices` says so in its own docstring at `lint.py:670` — "What it
proves is PRESENCE, never quality or position". The gate asks whether the block is on the page,
not whether it holds a decision. So a `verdict` block with one row reading
`none | No course of action was decided at this meeting.` satisfies the gate while recording that
nothing was decided.

Measured, not argued — `/tmp/wf2-59-probe2.py`, exit 0, 7 checks passed:

| Probe | Result |
|---|---|
| AC8 page carrying a neutral `verdict` row, with `verdict` in the set | publishes, `check_style_devices` returns `[]` |
| the same page with the region OMITTED | **refused**: "the page is styled `minutes` ... `verdict` is missing" |
| decisions fabricated on the AC8 page | none — zero `decided` keys emitted |
| the neutral row's own state class | `is-none`, so the template styles it separately |

Two things this buys that the earlier draft did not:

1. **AC6 holds on every page.** The earlier draft's decided-nothing page carried no decided region
   at all, which is not "a register honestly empty" — it is no register. AC6 asks for four
   distinct regions and AC8 asks for one of them to be empty; only a present-but-empty register
   satisfies both at once.
2. **The gate can fire.** With `verdict` in the set, omitting the decided register is refused by
   name. An absence assertion that cannot fail is not a gate.

**Why the empty register reads as deliberate rather than broken**, in two places at once: the
ledger prints `0 | courses decided` as a NUMBER in the opening screenful beside
`2 | premises agreed`, and the register itself states the absence in words. An absence rendered as
a printed zero and a written sentence is a statement somebody made. That is the principle the
repository already applies to `FIRST_READ_DEVICES` itself — `docs/design-language.md` says "an
empty requirement must always be a statement someone made, never the residue of a parser that
matched nothing." The template's CSS gives `.mn-decided .blk-row.is-none` a neutral treatment
rather than a warning colour, so the empty state does not read as a fault.

**`findings` and `steps` are deliberately NOT in the set, and the peer proposal wanted them
there.** Its reason was the same four-region contract, and its own risk list names the cost: an
empty-state `steps` "without rendering that sentence as step 1" needs a new engine-owned block
variant, because `_steps` always emits `<ol><li>`. `BLOCK_VARIANTS` only lets a template SELECT a
renderer the engine already owns, so adding an empty-state renderer is a renderer change — which
this issue puts out of scope. `findings` is excluded for the symmetric reason: a meeting can agree
nothing, and AC8 guarantees the agreed register is populated only on that one page, not on all
pages. So the line is: a register is gate-mandatory when EVERY minutes page must state something
about it, and only the decided register meets that bar — Robert's Rules makes minutes the record
of what was DONE, so the done-ness must always be stated, even when the answer is "nothing".
Agreed premises and action items stay required regions of a NORMAL minutes page, exercised by the
gallery page and asserted by the template test rather than by the publish gate.

## The ranged trace citation

Research item C5: the one published placement convention found handles a **single** timecode, and
says in its own words "Pick a house style, write it down, and reuse it" — so it is explicitly one
vendor's house style, not an authority. Meanwhile 90 of the first real document's 120 traces carry
a distinct end segment.

**Decision: the citation lives in the `findings` fourth field (the provenance tail), styled by the
`findings.tail` marker as `mn-trace`, and the docstring declares the form as this template's own
convention rather than as anybody's standard.** The form is `trace 22:32, segments 381 to 393`.
No borrowed `RESOLVED:`-style token, and no claim of precedent — because there is none for a
range.

Two constraints on the wording, the second from the peer consult:

- The citation is placed at the END of the statement it supports, which is the one thing the
  vendor convention and this template agree on. The docstring says that end placement is a house
  convention, not a rule anybody published.
- **A trace identifier is not called a timecode unless it is one.** `22:32` is a timecode;
  `segments 381 to 393` are transcript segment indices and are not. Conflating them would be the
  kind of false precision this whole document is trying to avoid.

The citation is styled visually secondary and must wrap rather than overflow. It is never
hover-only content: a citation a reader cannot see in print is not a citation.

## File changes

| Path | Change |
|---|---|
| `scripts/render/templates/minutes.py` | **new**, declaration only: `NAME`, `FRAME`, `SECTIONS`, `MARKERS`, `CSS`. No `BEFORE_BODY` (a minutes page's content is per-meeting, so there is no constant furniture), no `BLOCK_VARIANTS`, no script — `uat` stays the only interactive template |
| `scripts/render/templates/__init__.py` | add `minutes` to the `from . import (...)` list and to `MODULES`, appended last in roster order |
| `scripts/render/blocks.py` | `DOC_TYPE_TAGS["minutes"]` and `FIRST_READ_DEVICES["minutes"]` |
| `scripts/publish_doc.py` | add `"minutes"` to `PURPOSES` and map `PURPOSE_STYLE["minutes"]` to `"minutes"` |
| `docs/design-language.md` | one `minutes` row in `## Doc types`, both pinned columns |
| `README.md` | TWO surfaces: a row in `## Choosing a --type`, and a gallery cell — which fills the empty cell now sitting beside `plain`, making that table exactly 7 full rows |
| `skills/design-doc-publish/SKILL.md` | a `--type` table row naming the template, plus selection guidance longer than 12 characters |
| `scripts/tests/test_minutes_template.py` | **new**, shaped after `test_design_system_template.py` |
| `scripts/tests/test_furniture_context.py` | a CAPTURED `PRE_74` sha entry — there is no "before" for a style that did not exist, exactly as that file already records for `design-system` |
| `scripts/tests/regen_docs_pages.py` | `PAGES` entries for the gallery pair, for this design doc, and for the Step-5 plan |
| `docs/examples/gallery/minutes.md`, `.html`, `.png` | **new triple** — the `.png` is required by `test_example_gallery.py::test_the_screenshot_exists`, which AC4 requires to pass |
| `docs/rendered-styles/minutes.html` | **new**, produced by `regen_rendered_styles.py`, which derives its style list from the registry |
| `docs/planning/campaign-log.md`, `.html` | the inherited uncommitted pair, shipped in this PR |

## FRAME values, and the reason for the width

```
ground        var(--bg)                measure      960px
gutter        0 22px 80px              header_pad   34px 0 16px
header_rule   3px double var(--line)   header_gap   16px
h1_size       clamp(21px,2.9vw,27px)
```

Six owned live slots, measured by `frame.owned_slots` in the probe cited below. The floor the gate
sets is 3.

**`ground` is the flat default, DECLARED.** A minutes page is an archival record, and a decorative
wash on a record is wrong. This is the case the owner decision of 2026-08-02 was written for: the
gate asks that a ground be DECIDED, not that it differ, and naming the default because it is right
is the sanctioned answer.

**`measure` is 960px**, which is unused — the gate requires that, because the clash dict is pinned
to exactly `{"1240px": ["dashboard", "uat"]}` and a third collision fails by design. Taken today:
760 `spec`, 820 `report`, 880 `analysis`, 900 the default, 920 `review`, 980 `module-map`,
1000 `workflow`, 1040 `slide-deck`, 1080 `design`, 1120 `roadmap`, 1160 `design-system`,
1240 `dashboard` and `uat`. The width is the peer consult's, and its reason is better than the
940px this design first picked: 960 "accommodates register metadata and long trace ranges" — the
`findings` provenance tail carries a ranged citation, which is the longest inline element on the
page, and 40px over the default buys it a line it would otherwise wrap. `header_rule` at 3px
double is the masthead of a record, and it is the one slot here doing real visual work.

## Failure modes

| Failure | Loud or silent | What surfaces it |
|---|---|---|
| A minutes page omits **both** chip regions, or its ledger, or its decided register | **loud** — publish refuses at stage 3, naming the missing block | `check_style_devices`, already in place |
| A minutes page omits **only** the attendee region, keeping the meeting-facts chips | **SILENT — it publishes** | nothing at publish time. See the note below |
| A minutes page puts its regions in the wrong order | **SILENT** | nothing at publish time. See the note below |
| The doc table and the code disagree | **loud** — two exact-equality tests | `test_first_read_devices_match_the_documented_column` and `test_doc_type_tags_match_the_documented_sets` |
| A future style introduces an unapproved duplicate measure, including reuse of 960px | **loud** | the pinned dict in `test_every_style_has_a_distinct_measure`, whose only sanctioned collision stays `{"1240px": ["dashboard", "uat"]}` |
| Adding this style moves some OTHER style's bytes | **loud** | `test_furniture_context.py`'s `PRE_74` oracle, which asserts every existing style is byte-identical to its captured sha. Adding a template must move nothing else, and that oracle is the check |
| The new gallery pair ships unguarded | **loud** — the regenerator refuses to write anything | `regen_docs_pages.undeclared_pairs()` |
| An author writes an action owner and expects a real field | **silent** | out of scope by the issue; the docstring states owners are text, and `report.py` lines 17 to 19 record the same ceiling |
| An author uses `settle` for an agreement | **silent** | prose, and unenforceable by a stylesheet. The docstring names the vocabulary, which is what AC7 asks for |
| A synthesized `agreed` row upgrades ordinary discussion into a consensus nobody reached | **silent** | the peer consult's first risk, and it is real. Requiring a hedge phrase and a trace mitigates it; stylesheet-only work cannot check the claim semantically |
| The registers and the alternatives region drift apart during editing | **silent** | the registers are declared canonical in the docstring; `options` supplies context, never a restatement of an outcome |

### The two silent rows above, and why they stay silent

**The publish gate cannot tell two fence roles of one tag apart.** Meeting facts and Attendees are
both the `chips` TAG, differing only by their fence role, and `FIRST_READ_DEVICES` is a set of
TAGS. An earlier draft of the table above claimed a page omitting its attendee region is refused
loudly. The cross-model review said that was false, and a probe confirmed the reviewer rather than
the design — `/tmp/wf2-59-probe4.py`:

| Page | `check_style_devices` |
|---|---|
| both chip regions present | publishes |
| **attendees dropped, meeting facts kept** | **publishes** |
| meeting facts dropped, attendees kept | publishes |
| both chip regions dropped | REFUSED |

Region order is unchecked at publish time for the same reason: the gate reads a set, and a set has
no order.

**Owner decision, 2026-09-02: fix this in scope and state the residual, rather than widen the
issue.** The reviewer's remedy was a minutes-specific publish-time validator requiring the two
chip roles separately and checking region order on every page. That means editing
`scripts/render/lint.py`, which this issue's scope excludes — it admits only composition from the
existing block vocabulary — and which every style shares. So:

- the table above now states what really happens, in both directions;
- `test_minutes_template.py` asserts the attendee region is present and the four AC6 regions
  appear in document ORDER, against a rendered fixture;
- the PR body states the residual plainly: role-level and order-level structure is guarded by this
  repository's own tests, not by the publish gate, so a page written outside this repository can
  still omit its attendee region and publish.

That residual is **noted, not filed**. Under the workspace issue throttle a review finding becomes
a GitHub issue only when the owner opens one, and on 2026-09-02 the owner chose the note.

**What the policy maps do NOT prove, named by the peer consult and worth recording because two
acceptance criteria read as though they do.** Set membership in `DOC_TYPE_TAGS` and
`FIRST_READ_DEVICES` cannot verify document ORDER, distinct headings, correct vocabulary, or
honest content — and the golden SHA detects a rendering change, not a semantic one. AC3 and AC6
are satisfied by presence, so the region ORDER and DISTINCTNESS that AC6 actually asks for must be
asserted directly by `test_minutes_template.py` against a rendered fixture, never inferred from
the maps. That is a real requirement on the test, and it goes into the Step 5 plan.

## Security implications

Nothing in this change accepts author text into a class attribute. Every `MARKERS` value is a
fixed slug written in the module, and `_token()` already validates every author-supplied semantic
token against `^[a-z0-9]+(?:-[a-z0-9]+)*$`, falling back to `note` with a warning. There is **no
`BEFORE_BODY`**, so this template emits no unescaped furniture at all — the one place a template
can put bytes on a page without escaping is simply not used. `CSS` is a constant containing no
author input and no colour literal.

## Platform / external dependencies

```
platform_apis:
- api: render_artifact(style="minutes") on the in-repo render registry
  feasibility: verified via spike — /tmp/wf2-59-probe.py, run 2026-09-02, exit 0, 22 checks
    passed and 0 failed. It injected this exact declaration into render._templates.TEMPLATES,
    .CSS and .MARKERS, bound it with render._bind plus render._css_for exactly as
    render/__init__.py does, then rendered both the full page (17488 bytes, all nine region
    markers emitted, body class tpl-minutes, no script tag) and the AC8 decided-nothing page
    (13133 bytes, carrying no mn-decided region). frame.owned_slots returned 6 slots including
    measure, and the measure clash dict came back unchanged.
  failure: fail-loud
- api: headless Chrome --screenshot for docs/examples/gallery/minutes.png
  feasibility: verified via spike — run 2026-09-02 on Google Chrome 152.0.7977.64. The exact
    shipped invocation reproduced THREE committed gallery PNGs byte for byte: design.png
    (sha256 b7914e2f1c8b083025fa6371c900ac22e58c273700f266a5e4fef147a1702362, 125553 bytes,
    matching the committed file's own sha256 exactly), review.png and slide-deck.png. Every
    committed gallery PNG is exactly 1280 x 1000, so this is a viewport shot rather than a
    full-page one. Command:
      google-chrome --headless --no-sandbox --disable-gpu --hide-scrollbars
        --force-device-scale-factor=1 --window-size=1280,1000
        --screenshot=<out.png> "file://$PWD/<page>.html"
  failure: fail-loud
  surface: test_example_gallery.py::test_the_screenshot_exists names a missing file, AND the
    minutes template test decodes the new PNG and asserts 1280 x 1000 with a non-trivial byte
    size — existence alone cannot detect a blank, stale or wrong-page capture.
```

**An earlier draft of the block above cited `existing-call-site` on the ground that the Playwright
MCP tools were loaded in this session. Both reviews rejected that, correctly** — loaded tool names
are tool discovery, not an exercised call site, and #226 treats that as no better than `docs`. The
correction went further than either review asked, because the first attempt failed usefully: the
Playwright MCP browser refused with "Browser is already in use ... use --isolated", since another
session holds it. **That browser was not killed.** A headless-Chrome route was found instead, and
it is the better evidence — reproducing three committed artifacts byte for byte proves not merely
that a screenshot is possible but that this command is the recipe those files were made with.

The repository has no committed screenshot recipe, which is why the existing 14 PNGs went stale
after #58 with no test catching it. The command above is therefore recorded beside the gallery's
manifest entry, as a two-line comment.

A second spike, `/tmp/wf2-59-probe2.py` (2026-09-02, exit 0, 7 checks passed), settled the
first-read divergence against the REAL gate: it imported `render.lint.check_style_devices` and
called it on rendered pages, confirming that the AC8 page publishes with a neutral `verdict` row
and is refused by name without one. The first spike had called that function through a wrong
attribute and got `None`, which proved nothing; that is corrected rather than smoothed.

What no spike proves, and Step 8 must therefore measure for real: AC1's end-to-end claim. The
spikes exercise the renderer and the lint function, never the CLI's own argument parsing, stamping
and staging.

**AC1 needs TWO runs, not one, and the cross-model review is why.** AC1's own text names
`--type minutes --style minutes`, which passes the style by hand — so that command may never
exercise `PURPOSE_STYLE["minutes"]` at all, and a broken default mapping would sail through it.
Reading the exit code alone also proves nothing about the page. So Step 8 runs:

1. `--type minutes` with **no** style override, then asserts the rendered page carries
   `class="tpl-minutes"`, lands at the expected output path, and carries the mandatory first-read
   blocks. This is the run that actually tests the type-to-style mapping.
2. `--type minutes --style minutes`, the literal AC1 command, for explicit-argument handling.

Both exit codes are recorded verbatim before AC1 is called met.

## Multi-PR assessment

**One PR.** The issue estimates 500 to 800 inserted lines and the change has no separable phase: a
registration without its documentation row turns two exact-equality tests red, so the surfaces
must land together or the suite is red in between.

**Why the two campaign-log files belong in THIS issue, stated because the cross-model review asked
and the earlier draft never answered.** They are not incidental inherited work. That diff ADDS the
section `## #59 — A minutes doc type and style, for meeting minutes` and rewrites the log's stats
strip to `59 | newest: filed, a minutes doc type and style`. **The campaign log is issue #59's own
status surface**, and the workspace manual requires a status surface to update inside its own
issue's PR and never in a trailing docs PR. The reviewer proposed splitting them out on the ground
that no dependency was established — the dependency is real, and the defect was this document not
stating it. Verified by reading `git diff docs/planning/campaign-log.md`, which names #59 twice.

The `.html` travels with the `.md` for a second, independent reason: committing the markdown alone
reproduces the exact defect that issue #56 existed to fix, and leaves
`test_docs_pages_current.py` red.

## Approaches weighed

**A. Compose from existing blocks, summary-first, decision tagged (CHOSEN).** No renderer change
and no new block tag: nine regions from eight existing tags. Effort: the estimated 500 to 800
lines, almost all of it CSS and documentation. Risk: medium, concentrated in the exact-equality
doc pins and the new currency gate, both named above with the test that catches each.

**B. Copy the W3C shape — a timestamped transcript with inline `RESOLVED:` tags.** Rejected. It
needs a per-line chronology, which means `timeline` in the accepted set; it puts the decision
below the record, which contradicts the first-read design language of this engine; and Robert's
Rules calls it improper for an ordinary society's minutes. It would also make the four distinct
regions of AC6 impossible, because the whole document would be one region.

**C. Widen the `steps` block with a fifth field for an action owner, then build on it.** Rejected,
and the issue rejected it first: it is a renderer change that reaches `spec` and `report` too, so
it belongs in its own issue. The optional fourth field added by #39 is the precedent for how that
would be done later.

## Peer consult — provenance

One independent proposal was obtained through `review_runner.py consult`, backend **`gpt`**,
reviewer model **`gpt-5.6-sol`**, author model `claude-opus-5[1m]`, status `success`,
`backend_switched: false`, `input_sha256` verified against the problem file. A consult is always
`diagnostic: true`, so it authorizes no fix round and no loop-back was charged. The proposal was
written blind: the problem file carried the issue, the codebase analysis and the research, and
this design's own draft was on disk before the result was read.

**Where it converged** — independent agreement, which is the useful signal:

- Summary-first, with the four regions as distinct typed regions rather than a transcript.
- Do NOT adopt `RESOLVED:` as the generic decision marker.
- Vocabulary `agreed` / `decided` / `chose` / `action` / `open`, with `settle` forbidden.
- Action owners as text in the `steps` text field, because no block carries an owner field.
- The ranged trace form is a local convention with no published precedent, and must say so.
- Capture the new per-style golden SHA.

**What was adopted from it, and it changed the design:**

| Adopted | What it replaced |
|---|---|
| `verdict` in `FIRST_READ_DEVICES`, with a neutral empty row | this design's `{chips, stats}`, whose reasoning about AC8 was measurably wrong — see the AC8 section |
| `measure: 960px` | 940px. The peer's reason (register metadata and long trace ranges) is the better one |
| `resolved` reserved for reproducing a motion's exact wording | a blanket ban on the word |
| The owner display form `Owner — action — due date or condition` | an unspecified "owner as text" |
| "A trace identifier must not be described as a timecode unless it actually is one" | nothing — this distinction was missing |
| The warning that set membership proves nothing about order, vocabulary or honesty | nothing. It became a requirement on the template test |

**Where it was declined, with the reason:**

- **`timeline` in the accepted set**, for "a concise chronological record ... not dialogue". Declined.
  A stylesheet's only real power is what it refuses, and `timeline` IS the chronology block — so
  admitting it while claiming no transcript region would be a policy enforced by prose alone. The
  peer's own eighth risk names the failure mode ("recording alternatives can slide into discussion
  summaries"). This is a genuine judgment call and the disagreement is recorded rather than
  resolved: if authors turn out to need a chronology, adding `timeline` later is a one-line
  stylesheet change.
- **`findings` and `steps` in `FIRST_READ_DEVICES`.** Declined for the reason the peer itself
  identified: the empty-state `steps` it requires needs a new engine-owned block variant, which is
  a renderer change and out of scope.
- **`header_rule: 2px solid currentColor`, `h1_size: clamp(2.25rem, 6vw, 4rem)` and a single-value
  `gutter` clamp.** Declined on family consistency. `currentColor` is not one of this engine's
  tokens (`var(--line)` is), a 4rem h1 would be roughly double every other style's ceiling, and
  `gutter` is a three-value shorthand whose middle value is the side gutter — a single clamp would
  silently change the top and bottom too.
- **Marker names like `agreed-register` and `empty-state`.** Declined: every existing template
  prefixes its markers (`ds-`, `an-`, `rm-`, `dz-`), so `mn-` keeps the family readable.
