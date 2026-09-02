# Issue #56 — a committed page must re-render to itself

*Design note. WF2 small-standard lane, so this is a brief note rather than a
multi-approach design: the cause was reproduced live before any of it was written.*

## The problem, as measured

Two independent defects wear one symptom.

**Defect A — content staleness.** `docs/planning/campaign-log.md` gained the
"2026-08-24 — the Vercel era ends (5.0.0)" section in `3503719` (#52, 2026-08-24
20:23:28 -0600). `docs/planning/campaign-log.html` was last written in `37482cf`
(2026-08-24 13:46:11 -0600). Nobody re-rendered it, so the committed page is missing a
whole section.

**Defect B — the accent is resolved from unversioned state.**
`pack_for("design-doc-publish", <workspace file>)` returns
`origin: fallback`, `#4f7d15` / `#b7e87f`. All three doors are shut, in order:

1. the configured workspace entry is literally `{"name": "design-doc-publish"}` with **no
   `path` key**, so `_project_config` returns `None` — silently, and deliberately
   (`scripts/vdl_packs.py:207-211`, the #9 case);
2. `design-doc-publish` is **absent from `SEEDS`** (`scripts/vdl_packs.py:47-70`);
3. so `_fallback` hashes the name into `PALETTE` (`scripts/vdl_packs.py:235-244`).

Step 1 reads `~/.config/design-doc-publish/workspace.json`, which is not in git. That is
the dependency acceptance criterion 2 names.

**Why no test saw either.** Every byte-identity guard in this repository renders with **no
project pack** — `test_byte_identity.py:32` and `regen_rendered_styles.py:48` both omit
`vdl`. The accent layer is therefore invisible to all of them. And nothing at all guards
`docs/examples/gallery/*.html` or `docs/planning/*.html` for render currency.

**The blast radius is 13 pages, not one.** A census of all 18 committed `docs/**` md+html
pairs (re-render at the committed stamp, diff) found:

| pages | what the committed HTML is missing |
| --- | --- |
| 11 gallery pages | the CSS rule `a{color:var(--accent)}` |
| gallery `roadmap` | that rule, plus `.blk-ph-badge{flex:none;…}` → `{flex:0 1 auto;min-width:0;max-width:100%;white-space:normal;overflow-wrap:anywhere;…}` |
| `docs/planning/campaign-log` | the #52 section (defect A) |

Five pages already round-trip clean: `docs/design-language-example`,
`docs/examples/gallery/plain`, `docs/planning/2026-08-24-37-vercel-backfill` (all three
with no pack), and `docs/planning/2026-08-23-github-doc-harness-spec` plus
`docs/planning/2026-08-25-access-architecture-consult` (both **with** the pack — so the
green fallback is already shipping on two committed planning docs).

Owner decision, 2026-08-25: honor acceptance criterion 1 literally and cover all 18 pairs,
re-rendering the 13 stale ones in this PR.

## The approach

Six changes, none of which reorders the resolution chain. The fourth (1b) was not in the
original design — it was forced by the Step 8a cross-model review, which proved the first three
left acceptance criterion 2 only partly met.

### 1. Make the chain converge (acceptance criterion 2)

`pack_for` walks **declared → seed → fallback**, and that order is deliberate: a project
that declares its own colour must supersede a seed
(`scripts/vdl_packs.py:48-54` says so explicitly for chorestory). Reordering it would break
that intent, so this design does not.

Instead it makes the two reachable answers **identical**:

- add `design-doc-publish` to `SEEDS` with `#4f7d15` / `#b7e87f`, which makes the fallback
  hash unreachable for this project;
- add a `vdl` block carrying the **same** two colours to this repository's own committed
  `.rawgentic.json`, which makes the `declared` path resolve to the same answer whenever a
  workspace does name a path here;
- pin the two to each other with a test, so they cannot drift apart later.

After that the answer is the same whether the workspace names a path *to this tree*, names the
project bare, or does not exist at all.

**That is not yet enough, and §1b is why.** It leaves the case where the workspace names a path
to a DIFFERENT tree — which the first draft of this note dismissed and the review did not.

**Why `#4f7d15` / `#b7e87f` and not a new colour.** It is what two committed planning docs
already wear, so adopting it re-renders one page instead of three and turns an accident into
a declaration. It is a `PALETTE` entry, and `PALETTE`'s own contract is that all five clear
WCAG AA in both themes against this renderer's surfaces
(`scripts/vdl_packs.py:72-75`), which `test_vdl_packs.py` measures rather than trusts.
Reversible in one line each if the owner wants a different colour.

### 1b. The residual I first dismissed, and then had to fix

The paragraph that used to sit here said a workspace pointing the *name* `design-doc-publish`
at some *other* repository was "a misconfigured workspace, not renderer non-determinism", and
left it at that. **That dismissal was wrong**, and the Step 8a cross-model review said so at
Critical. Acceptance criterion 2 has no misconfiguration exemption: it asks for the accent to be
deterministic given `--project` and the committed sources, full stop.

Worse, the new guard could not see the violation, because it passes `workspace_file=None` by
design. So the gate would have stayed green while production emitted a different colour — a
guard that passes exactly what it exists to refuse.

**Measured, not argued.** With a workspace pointing the name at another tree declaring
`#111111` / `#eeeeee`:

```
GUARD  (workspace_file=None)   : seed      {'light': '#4f7d15', 'dark': '#b7e87f'}
PROD   (workspace -> other)    : declared  {'light': '#111111', 'dark': '#eeeeee'}
css_layer byte-identical?      : False
  guard emits: :root{--accent:#b7e87f;}
  prod  emits: :root{--accent:#eeeeee;}
```

**The fix, decided by the owner after that measurement.** One question is now asked BEFORE the
chain: *is this project the repository the module is executing inside?* If so, that tree's own
committed declaration wins — `_own_repository_config` in `scripts/vdl_packs.py`, consulted
first, because by the time `_project_config` has followed the workspace pointer the wrong tree
is already chosen.

It is still **not a reordering** of `declared → seed → fallback`. It is a narrower question
asked ahead of it, and it fires only when the requested name is this tree's own — verified for
every seeded project: `_own_repository_config` returns `None` for `chorestory`, `saystory`,
`rawgentic`, `sysop` and an invented `payments-api`, and a path only for `design-doc-publish`.
So the chorestory intent at `scripts/vdl_packs.py:48-54` is untouched, and it generalizes: any
repository vendoring this module now gets the same guarantee about its own pages.

Three properties held deliberately, each with its own test:

- **The early answer is still VALIDATED.** It goes through `load_pack`, so a malformed
  own-declaration warns and falls through to the seed. Answering early must not mean answering
  unvalidated, or this would be a new route for an unchecked hex to reach the `<style>` sink.
- **The seed is not now dead code — it is the floor.** A checkout whose own `.rawgentic.json` is
  missing or corrupt still reaches the seed, never the name hash. Without that test, this fix
  would have quietly made the seed unreachable and restored the original defect on exactly the
  broken-config machine that can least afford a surprise.
- **Byte-identical across all four workspace states** — absent, bare name, own repository,
  another repository — asserted on `css_layer`'s output, because that is what a reader sees.

Two existing tests changed as a consequence, and neither was weakened.
`TestEveryPackClearsAA::test_every_seed_lints_clean` now expects `declared` for this one project
and `seed` for every other, with a separate test pinning that the carve-out fires for this
project ALONE — rather than loosening the assertion to "either", which would have stopped it
noticing if some other project's seed quietly stopped being reached. And a test of mine that
asserted `origin == "seed"` with no workspace now asserts `declared`, plus explicitly that it is
never `fallback`, since never-the-hash was always the property that mattered.

### 2. A permanent gate over every committed pair (acceptance criterion 1)

New `scripts/tests/regen_docs_pages.py` + `scripts/tests/test_docs_pages_current.py`,
following the established pattern in `regen_rendered_styles.py` /
`test_rendered_styles_current.py` rather than inventing one. Import direction is forced the
same way: the recipe lives in the regenerator and the test imports it, because `pytest` is
not importable under a bare `python3` on this host.

What is new versus that precedent, and why:

- **It renders WITH the project pack.** This is the whole point. Every existing guard omits
  `vdl` — `test_byte_identity.py:32` and `regen_rendered_styles.py:48` both do — which is
  exactly why this class of drift was invisible.
- **And it resolves every pack with `workspace_file=None`, never a machine's configured
  workspace.** Amended after the Step 4 self-review raised this as Critical, because the
  first draft said "with the project pack" and never named the source. Passing the live
  `~/.config/design-doc-publish/workspace.json` would make the gate's own verdict depend on
  unversioned machine state — precisely what acceptance criterion 2 forbids — so a gate
  written to refuse render drift could itself pass it silently on a different clone. With
  `None`, `_project_config` (`scripts/vdl_packs.py:158`) returns on its first executable line
  (`:178`), so resolution runs **seed → hash over committed tables only**. That is
  committed-sources-by-construction rather than by promise.

  Measured, not assumed: `pack_for("design-doc-publish", None)` and
  `pack_for("design-doc-publish", <the live workspace>)` return the *same* accent today
  (both `origin: fallback`, `#4f7d15` / `#b7e87f`), and with the new `SEEDS` entry the
  answer becomes `origin: seed` with **byte-identical `css_layer` output** — confirmed by
  comparing the two layer strings directly. `css_layer` (`scripts/render/vdl.py:53-83`) reads
  the pack only through `_colour` (`:39-50`) and `pack.get("tint")`; it never emits `origin`,
  `source`, or `note`, so the origin change moves no bytes and the two already-green planning
  docs stay byte-identical.
- **A committed manifest supplies each page's render inputs** — title, subtitle, style,
  stamp, `doc_id`, and `project`. It must be committed rather than extracted from the
  committed HTML: the HTML is the artifact under test, so deriving the inputs from it is
  circular, and a hand-edited title would re-render happily and pass.
- **Completeness.** The manifest's key set must equal the set of committed `docs/**` md+html
  pairs exactly, so a new document cannot silently skip the gate and a deleted one cannot
  leave a stale entry behind. Same rule `test_rendered_styles_current.py` applies to its
  style set.
- **A can-it-fail test**, because a golden-file guard whose regenerator and assertion share
  one code path passes even on a broken renderer.
- **Sentinels the regenerator cannot rewrite** — a doctype, a minimum size, and the manifest's
  own pinned title and stamp present in the page.

#### What links the gate to production, and how far that link reaches

`publish_doc.py` passes a real workspace (`scripts/publish_doc.py:1680`), so the gate alone
would be testing a different resolution from the shipped one. The convergence test in change 1
is what closes that: it pins the `SEEDS` entry to this repository's own `.rawgentic.json` `vdl`
block, so the declared path and the seed path give one answer, and the gate's `None` answer
equals production's.

**That equivalence is scoped, and the scope is stated rather than assumed.** Revised after the
Step 4 verifier flagged the unconditional claim. The convergence test pins exactly one project,
`design-doc-publish`, so the guarantee reaches only pages whose manifest entry names that
project or no project at all — which today is every page the gate covers. A page manifested
under some *other* project would need its own convergence pin before the guarantee extended to
it, because nothing would then tie that project's `SEEDS` value to its own declared block
reached through a real workspace path. Two things narrow the exposure rather than leave it open:
the guard asserts, over **every** project the manifest names, that resolution lands on
`declared` or `seed` and never a hashed `fallback`; and the manifest itself is committed, so
adding such a page is a reviewable act, not a silent one.

### 1c. And the fix in 1b had a hole of its own, on its own fallback path

The Step 11 cross-model review found it, and I confirmed it before accepting it. §1b established
ownership and then, if our own declaration turned out to be *unusable*, fell through to
`_project_config` — so a workspace could point the name at another tree whose **valid**
declaration won:

```
malformed own vdl block + a workspace pointing at another tree
  -> declared {'light': '#111111', 'dark': '#eeeeee'}
```

Criterion 2 re-opened on exactly the broken-config path §1b advertises as safe. My own tests
missed it because every one of them passed `workspace_file=None`, so none exercised the
fallback at all — the hole was in the test design, not just the code.

**Ownership and pack validity are now separate questions.** Once the requested project is
identified as the executing repository, the workspace is not consulted for it *at all* — a
rejected declaration goes straight to that project's committed seed, and the seed-or-hash tail
is factored into `_seed_or_fallback` so `pack_for`'s two exits cannot drift apart. Both
counterexamples now measure byte-identical.

**The honest limit, asserted rather than glossed.** When our own config cannot be *parsed*,
ownership is genuinely undeterminable: the file that would name the project is unreadable.
Claiming ownership anyway would skip the workspace for **every** project and break
`index/build_index.py`, which asks `pack_for` about all of them. So in that one case the
workspace still answers — and what makes that defensible is that it **warns loudly**, by the
change in §1d. There is a test asserting exactly this limit, so it is a recorded decision rather
than an untested gap, and it names itself as the test to change if someone finds a signal that
settles ownership without parsing the file.

### 1d. A silent swallow, found in my own review

`_own_repository_config` swallowed parse errors silently, and its own justifying comment claimed
a warning would print on the ordinary path. **The justification was checkable and false**: the
`exists()` check above it already returns for a repository with no config, so the branch is
reached only by a config that exists and is broken. It now warns. That warning is what makes
§1c's limit acceptable rather than a hole.

#### The gate's unit is a PAIR, and that leaves committed pages it cannot cover

Amended after the Step 4 self-review, which called this out as a Medium. Criterion 1 asks for a
page to re-render "from its unchanged markdown", so a page with no markdown cannot satisfy it
either way and a pair is the only unit the criterion defines. Of 32 committed `docs/**/*.html`,
18 pair with a sibling markdown and 14 do not:

- `docs/rendered-styles/*.html` (13) — **already guarded** by
  `test_rendered_styles_current.py`, which renders them from one cross-style fixture.
- `docs/examples/example-roadmap.html` (1) — guarded by **nothing**. It stays uncovered by this
  PR. Named here rather than left to be discovered.

The guard pins that set, so a *new* sourceless page turns it red instead of slipping into a gap
nobody re-counted.

Scope this gate does **not** claim, stated so nobody mistakes it: the regenerator and the
test call the same renderer, so this pins "the committed pages match what the renderer
currently emits", never "the renderer is correct". Renderer correctness is pinned
independently by `test_furniture_context.py`'s per-style SHA oracle,
`test_byte_identity.py`'s exemplar, and the cross-style guards.

#### The stamp, and the friction it buys — a DEFERRED High, named here

The manifest **pins each page's stamp**. That is the non-circular choice: taking the stamp
out of the page under test is the same circularity finding S4-1 rejected for the title. The
consequence is real and must be stated rather than discovered.

`publish_doc.py` re-renders with `_mountain_now()` and has **no `--generated-at` flag**, and
`render()` writes `out_path` at `scripts/publish_doc.py:1289` — **before** the `--dry-run`
check. So even a dry-run publish rewrites a committed page with a fresh stamp, which turns
this gate red on a page nobody meant to change.

Recorded as deferred finding **S4-3, High**, with the rationale that this is friction rather
than incorrectness, and re-presented at Step 11. It is High rather than Critical because it is
bounded and recoverable: the failure message names the file and the regenerator, and one
manifest line fixes it. The proper fix — a `--generated-at` flag, or having `publish_doc` read
the manifest stamp for a page the manifest covers — changes a CLI surface this design promised
not to change, so it is a separate change with its own review.

**Authoring flow for a covered page, so nobody has to work this out from a red test:**

1. edit the markdown;
2. bump that page's `stamp` in the manifest;
3. run `python3 scripts/tests/regen_docs_pages.py`;
4. commit the markdown, the manifest and the regenerated HTML together.

**Related platform behavior.** `publish_doc.py:1289` uses `write_text`, which applies platform
newline translation, so a publish from Windows would commit CRLF. That behavior predates this
change and has no effect on this Linux host. This gate compares **bytes**, following
`regen_rendered_styles.py`, whose docstring records that a text-I/O "byte-identity" guard is
not one — so a CRLF-committed page would turn the gate red rather than compare equal.

*(Reworded after the Step 8a cross-model review flagged the previous phrasing, "a related
observation, not a finding", as verdict-suppression language. It was: `<review-severity>`
forbids telling a reviewer what verdict to reach, and #840 measured that such phrasing works —
reviewers duly look elsewhere. The sentence has been reduced to the behavior and its
consequence, with no classification attached. Recorded rather than quietly edited, because the
rule I broke is one this repository's own process is bound by.)*

### 3. Re-render the 13 stale pages (acceptance criterion 3)

`campaign-log.html` is re-rendered **with** the pack, so it joins its two siblings at
`#4f7d15` / `#b7e87f`, and with a new stamp — this PR appends a campaign-log entry, so the
document genuinely changed. The 12 gallery pages keep their existing committed stamps: only
the renderer moved, and bumping their stamps would falsely claim the documents were updated.

The gallery pages stay **pack-free** (`project: null` in the manifest). They are template
demonstrations, not project documents, and that matches `docs/design-language-example` and
`docs/rendered-styles/*`. Their diff is then the single CSS line and nothing else.

## File changes

| file | change |
| --- | --- |
| `scripts/vdl_packs.py` | one `SEEDS` entry for `design-doc-publish` |
| `.rawgentic.json` | one `vdl` block, same two colours |
| `scripts/tests/regen_docs_pages.py` | **new** — the manifest and the render recipe |
| `scripts/tests/test_docs_pages_current.py` | **new** — round-trip, completeness, can-it-fail, sentinels |
| `scripts/tests/test_vdl_packs.py` | one test pinning `SEEDS` to the `.rawgentic.json` block |
| `docs/planning/campaign-log.md` | one appended entry (the `designArtifact` shared doc) |
| `docs/planning/campaign-log.html` | re-rendered, with the pack, new stamp |
| `docs/examples/gallery/*.html` (12) | re-rendered, pack-free, stamps unchanged |
| `docs/planning/2026-08-25-56-render-determinism.md` + `.html` | this note |

No configuration changes beyond the `vdl` block. No new dependency. No migration. No
architecture change: the resolution chain keeps its shape and its order.

## Script interface changes

None. `publish_doc.py` and `render` keep every flag they have. `regen_docs_pages.py` is a new
developer-facing regenerator, run by hand exactly as `regen_rendered_styles.py` is.

## Failure modes

| mode | behavior | why that is right |
| --- | --- | --- |
| a new `docs/**` md+html pair is committed with no manifest entry | the completeness test **fails** | otherwise a new document silently skips the gate — the failure `test_rendered_styles_current.py` was written to prevent |
| a manifest entry names a pair that no longer exists | the completeness test **fails** | a deleted document must not leave a stale entry claiming coverage |
| the renderer changes deliberately | every affected round-trip **fails** until the regenerator is run | that is the gate working; the regeneration is the deliberate act criterion 1 asks for |
| the renderer breaks, and someone regenerates | the can-it-fail test and the sentinels **fail** | a golden file regenerated from a broken engine is the one failure a round-trip alone cannot catch |
| the `SEEDS` entry and the `.rawgentic.json` block are edited apart | the convergence test **fails** | the two agreeing is the whole mechanism of criterion 2 |
| no workspace file exists at all | `pack_for` reaches the new `SEEDS` entry | the README's first command must keep working on a machine that has never run setup (#9) |
| a workspace names the project bare, with no `path` | same seed answer | this is today's real state, and it is now deterministic |

## Security implications

None material, and specifically:

- **No new input is trusted.** The `SEEDS` entry and the `vdl` block are repository
  configuration, which is the trust class `vdl_packs` already documents for pack values
  (`scripts/render/__init__.py:629`, `scripts/render/vdl.py:39-50`). Neither is author text, and
  neither reaches a page except through `css_layer`, whose hex validation is unchanged.
- **The colour still passes validation.** `_valid_colours` enforces `^#[0-9a-f]{6}$` on both
  themes; the new block satisfies it, and a malformed one would warn and fall open exactly as
  today.
- **The three containment guards are untouched.** `publish_doc.py:120`,
  `render/__init__.py:715-727` and `index/build_index.py:41-52` each refuse to load a
  `vdl_packs.py` that resolves outside its root, and the escape check on a workspace `path`
  (`vdl_packs.py:226-230`) is unchanged. This design adds no fourth load site.
- **The new test reads only committed repository files** and writes nothing outside the
  regenerator's explicit output paths under `docs/`.

## Platform / external dependencies

platform_apis: none

Every change is in-repo Python plus file reads and writes through `pathlib`, already
precedented at the exact call sites this touches (`regen_rendered_styles.py` does the same
reads and writes against the same `docs/` tree). No platform, framework, or external API is
introduced, so there is nothing whose feasibility could be assumed.

## Multi-PR assessment

Single PR. The diff is large in bytes — 13 regenerated pages — but it is one logical change,
and the gate and the re-render **must** land together: the gate is red until the pages are
current, and the pages have no protection until the gate exists.

## Known follow-up, flagged not fixed

The 14 gallery `.png` screenshots become subtly stale once link colour changes. No test
breaks — `test_example_gallery.py` asserts the file exists, never that it is current — and
regenerating them needs a real browser. It goes in the PR body as a follow-up.

Separately: `docs/planning/2026-08-24-37-vercel-backfill.html` is committed **without** the
pack while its two dated siblings carry it. This design records that as `project: null` and
leaves it byte-identical, which is criterion 1's "explained and intended" branch rather than
a silent inconsistency. Normalizing every planning doc onto the pack is the owner's call and
is not in this PR.
