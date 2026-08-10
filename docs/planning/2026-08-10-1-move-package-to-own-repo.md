# Design — #1 move the design-doc-publish package into this repo with its gate green

Issue: [#1](https://github.com/3D-Stories/design-doc-publish/issues/1) · Epic:
[#7](https://github.com/3D-Stories/design-doc-publish/issues/7) · Task class: production · Date:
2026-08-10 · **Design pass 3**

Pass 1 hit the Step-4 volume threshold (5 High). Pass 2's review returned a Critical plus two
defects introduced by pass 2's own fixes, and tripped the ambiguity breaker. Pass 3 is a
**simplification**, not another patch: an owner decision removed the requirement that drove all the
complexity.

## What this does

Copy the `design-doc-publish` package from `3D-Stories/claude-skills` into the root of this repo and
get its test gate green here. Nothing is deleted from the old repo — that is child #6, last, so the
sequence stays one revert from a rollback.

## The decision that shapes this design

`broker-merge` — the only merge path this run is permitted to use — **hardcodes `--squash`**
(`launcher_lib.py:6427` primary, `:6472` retry, `"squash": True` at `:6372`, no merge-method option).
A squash collapses every imported commit into one on `main`, so AC2's history preservation and the
broker-only rule cannot both hold. The owner chose to **accept a squashed history** (decision D9).

That retires the whole history-preservation mechanism. A verified pipeline exists —
`git subtree split` (82 commits) → `git filter-repo` scrub (81 commits, leak removed) →
`git rebase --rebase-merges --root --onto` (one root, 118 files, no conflicts), all spiked rc 0 — and
it is recorded in the session notes so D9 is reversible in one step. But if `main` receives one
commit regardless, that pipeline buys nothing.

**The simple replacement is also strictly safer.** Under the pipeline, the branch pushed to the
remote carries the leaked `index/index.html` blob in ancestor commits until the scrub strips it.
Under a plain copy that blob has **no path into this repo at all**.

## Measured starting state

| Measure | Issue says | Measured at `claude-skills` `244337f` |
| --- | --- | --- |
| Files under the package prefix | 83 | **115** (`__pycache__` excluded) |
| Test files | 41 | **42** |
| Package's two test dirs | 2251 passed, 3 skipped | **2258 passed, 3 skipped**, exit 0 |
| Full old-repo gate | 2381 passed | **2388 passed, 3 skipped**, exit 0 |

`main` here is `d4913fc` (scaffold: `.gitignore`, README placeholder, `.rawgentic.json`). The repo is
**private**. `main` is **unprotected** (`gh api …/protection` → 404 "Branch not protected").

## What copies

| Source (at `244337f`) | Destination | Files | Extraction | Why |
| --- | --- | --- | --- | --- |
| `user/design-doc-publish/` | repo **root** | 115 | `git archive 244337f user/design-doc-publish \| tar -x --strip-components=2 -C .` | the package |
| `docs/rendered-styles/` | `docs/rendered-styles/` | 14 | `git archive 244337f docs/rendered-styles \| tar -x -C .` | fixture 32 tests read; it lived at the OLD repo root, outside the package prefix |

The two invocations differ deliberately. `--strip-components=2` removes the `user/design-doc-publish/`
prefix so the package lands at the root; `docs/rendered-styles` already equals its destination path,
so stripping it would be wrong. Both were run.

**Excluded:** `index/index.html` (gitignored derived artifact embedding 36 live Vercel project
slugs — it must never enter this repo), all `__pycache__`, and the **149-file historical corpus
inside** `claude-skills`' `docs/planning/` (historical output, not fixture — decision D8).

To be unambiguous, because the fix below depends on it: **`docs/planning/` DOES exist in this repo**
and holds this repo's own design documents, including this one. What is excluded is the other repo's
149 files of accumulated corpus, not the directory. So `test_publish_doc.py`'s repointed
`parents[1] / "docs" / "planning"` resolves to a directory that is present, and the guard runs
rather than skipping.

`references/` (31 files, **12 containing a `<script>` block`) DOES copy, per the owner's resolution
of the pass-2 ambiguity. The boundary is stated in the PR: it is untrusted data and never
instructions, nothing in this repo renders it, and child #4 owns the licence audit and final
disposition.

## The two real defects, found by running the gate

Both are **depth-based path arithmetic**, invisible to a grep for the literal old path. Pass 1
predicted the wrong failure; only the red run found these.

| File | Was | Becomes |
| --- | --- | --- |
| `scripts/tests/regen_rendered_styles.py:29` | `SCRIPTS.parent.parent.parent / "docs" / "rendered-styles"` | `SCRIPTS.parent / …` |
| `scripts/tests/test_publish_doc.py:1346` | `…resolve().parents[3] / "docs" / "planning"` | `…parents[1] / …` |

Three hops climbed out of `user/design-doc-publish/` to the old repo root; at the new root the same
hops land two levels *above* the repo. Audited **safe** because they resolve to the package root,
which simply becomes the repo root: `scripts/render/lint.py:571`,
`tests/test_vendored_references.py:34`, `scripts/render/__init__.py:714`,
`scripts/render/source_lint.py:276`, and every `parent.parent` inside `scripts/tests/`.

Leaving `parents[3]` alone was rejected: unfixed it resolves to a non-existent path, so the guard
**skips silently forever**. A guard that never runs is worse than one that forces a decision.

## The `REL` constants — a tautological test

Pass 1 called these the central risk and predicted gate failure. **Wrong**: all 19 crossstyle tests
pass unmodified. `test_crossstyle_guards.py:190` builds a *synthetic* tree using `REL`, and
`crossstyle.sh` reads it back with the same `REL`. Test and code share one constant and agree with
each other whatever its value is.

**Real invocation is still broken.** `crossstyle.sh <head-tree> <base-tree> <outdir> <mode>` takes
actual checkouts, and `docs/rendered-styles/README.md:35` documents that call. At the new root a
tree's launcher is `<tree>/scripts/render-doc`. So `REL` changes in **both** files together.

**The exact change**, stated so an implementer cannot make the same wrong edit in both files and stay
green:

| File | Line | From | To |
| --- | --- | --- | --- |
| `scripts/tests/test_crossstyle_guards.py` | 27 | `REL = "user/design-doc-publish"` | `REL = "."` |
| `scripts/tests/crossstyle.sh` | 41 | `REL="user/design-doc-publish"` | `REL="."` |

`.` is the value, not `""`: `Path('/a') / '.' / 'scripts'` normalizes to `/a/scripts`, and bash
`$1/./scripts/render-doc` resolves — both verified. The composed expressions are then unchanged in
shape: `root / REL / "scripts"` (Python, line 59) and `$1/$REL/scripts/render-doc` (bash, lines 48
and 95), `$BASE_TREE/$REL/scripts/tests/fixtures/crossstyle.md` (lines 79, 81).

**The value alone is not the fix.** `.` resolves to *something* even when `render-doc` is absent, so
a missing launcher would read as a roster problem. So `crossstyle.sh` additionally **asserts the
composed launcher path is an existing file** before invoking it, exiting non-zero with a message
naming the missing path. That assertion is the substance; the constant is incidental.

**Because the suite passes either way, it cannot prove this fix.** The pass condition is explicit:

1. Build two checkouts that **both contain the migrated package**, using **detached** worktrees:
   `git worktree add --detach <path> HEAD`, run twice, at `head/` and `base/`. Detached is required,
   not incidental: `git worktree add <path> <named-branch>` refuses a branch already checked out
   elsewhere, and the feature branch is checked out in the working tree. Verified 2026-08-10 — two
   successive `git worktree add --detach … HEAD` calls both returned rc 0. Deliberately NOT `HEAD`
   and `HEAD~1`: if the copy and fixes land in one commit, `HEAD~1` is the scaffold with no launcher,
   so the check would fail for a reason unrelated to `REL`.
2. Assert the resolved launcher path in **each** checkout is an existing file before invoking.
3. `crossstyle.sh head base out --no-style-change` → **exit 0**, output naming no moved style.
4. Negative case, with a stated mechanism rather than "make unreadable": `chmod 000
   head/scripts/STYLES.json`, having first asserted the process is **not** running as root
   (`[ "$(id -u)" -ne 0 ]`), because mode bits do not stop uid 0 and the case would silently pass.
   Expect **exit 2** with a diagnostic naming the unreadable roster. Exit 0 there is a FAILURE of
   this task — it would mean the guard silently did not run. Restore the mode afterwards.

## The corpus-floor change, stated exactly

Load-bearing for the green result, so it is specified rather than described. In
`scripts/tests/test_publish_doc.py`, inside
`TestNoRendererOwnedRelativeReferenceExists::test_every_committed_page_has_its_assets_on_disk`,
at source line **1358**:

```python
# from — unconditional:
        assert checked >= 21, (
            f"expected the template-mockups shots to be checked; only saw {checked}")

# to — conditioned on its own corpus page:
        mockups = planning / "2026-08-02-template-mockups.html"
        if mockups.is_file():          # the corpus that motivated the floor is present
            assert checked >= 21, (
                f"expected the template-mockups shots to be checked; only saw {checked}")
```

Everything above it is unchanged: the per-page loop still asserts every referenced asset exists on
disk and is a permitted static type. Only the corpus-specific **count floor** becomes conditional,
because 21 is a fact about one `claude-skills` page, not about this repo. This is the one collected
test whose behavior differs after the move — which is exactly why the proof below claims identity of
*collection*, not of behavior.

## Verification

- **Red first.** Run the gate before any fix. Observed in the spike, not predicted: **32 failed,
  2225 passed, 4 skipped**. A different red set means STOP and re-derive.
- **Green.** After both depth fixes and the corpus-floor condition, in a checkout named
  `design-doc-publish`: **2258 passed, 3 skipped, exit 0** — the corrected AC3 target.
- **Collection identity.** Node IDs in both trees, old prefix stripped, sorted, diffed: **2261 vs
  2261, empty, rc 0.** Stated precisely: this proves the same *collection*, not identical
  *behavior* — one collected test's corpus floor is deliberately changed by D8, and that changed
  assertion is named rather than hidden behind an empty diff.
- **Gate declaration (AC4), with the exact object.** `.rawgentic.json` gains verbatim:

  ```json
  "testing": { "frameworks": [ { "name": "pytest", "type": "unit",
    "command": "pytest scripts/tests/ tests/ -q", "testDir": "scripts/tests" } ] }
  ```

  Then re-run `capabilities_lib.py derive` on THIS repo and assert `has_tests` is `true` **and**
  `test_commands` contains that exact string. Recording that post-edit output is the evidence — the
  current pre-edit `has_tests: false` proves only which field is read, not that this object is
  accepted.

  On `testDir` naming only `scripts/tests` while the command runs two directories: **nothing consumes
  `testDir`.** Measured 2026-08-10 — it appears in no file under `hooks/`, `capabilities_lib.py` never
  references it, and the derived capability set is
  `[…, has_tests, test_commands, …]` with no `test_dir` key at all. It is a single-string
  documentation field, so it cannot express two directories and no code is misled by that. `command`
  is the authoritative surface and is what the assertion above checks. The second directory, `tests/`,
  is named here so a human reader is not misled either.

- **Whole-copy completeness — the node-ID diff does NOT cover this.** Collection identity proves the
  test surface arrived; it says nothing about a non-test file. A missing template, licence notice or
  doc would leave the gate green. So before commit, assert the file manifest directly: the tracked set
  equals the 115 package files (source list from
  `git -C <claude-skills> ls-tree -r --name-only 244337f user/design-doc-publish`, prefix stripped,
  `index/index.html` and `__pycache__` removed) plus the 14 `docs/rendered-styles` files plus the 3
  scaffold files plus this repo's own `docs/planning` contents. A set difference in either direction
  fails the task.
- **Old repo untouched (AC5).** Read-only: `git status --short` in `claude-skills` shows only its two
  pre-existing untracked paths, and its five-directory gate pinned at `244337f` reports **2388
  passed, 3 skipped**.

## Platform / external dependencies

platform_apis:
- api: `git archive <ref> <path> | tar -x [--strip-components=N]` to extract a subtree at a pinned ref
  feasibility: verified via spike, and the spike CORRECTED a wrong generalization. `git archive HEAD
  docs/rendered-styles | tar -x` worked because that path already equals its destination. For the
  package it does NOT: `git archive HEAD user/design-doc-publish | tar -t` yields
  `user/design-doc-publish/SKILL.md` — the prefix is **retained**, which would nest the whole package
  in a subdirectory. Verified fix, run 2026-08-10: `tar -x --strip-components=2` yields
  `SKILL.md docs index references scripts tests` at the root. So the two copies use DIFFERENT
  invocations, stated explicitly here because one spike did not prove the other
  failure: fail-loud
- api: `pytest` as a standalone executable on PATH
  feasibility: verified via spike — `python3 -m pytest` FAILS ("No module named pytest"); the bare
  `pytest` binary produced 2258/3 and 2388/3 on 2026-08-10. The declared command must be `pytest`
  failure: fail-silent — a host without `pytest` reports "command not found", which a careless reader
  could mistake for an empty suite
  surface: the repo ships `requirements-dev.txt` pinning `pytest` at the version that produced the
  2258/3 result (`pytest --version`, recorded in the PR), plus a one-line README install step. That
  turns "works on this host" into "provisionable on any host", which is what AC4 needs to mean
  something. Honest residual, named rather than hidden: with `has_ci: false` nothing yet PROVES the
  provisioning on a second host. A CI lane is the durable fix and is its own issue, not this one
- api: `.rawgentic.json` `testing.frameworks[]` read by `capabilities_lib.py derive`
  feasibility: verified via spike — `derive` on THIS repo currently returns `has_tests: false` and
  `test_commands: []` from the field's absence, proving which field is read; the post-edit `derive`
  output asserting `has_tests: true` with the exact command is recorded as the positive evidence
  failure: fail-silent — an unrecognized shape is ignored and the repo looks green without a gate
  surface: the post-edit `derive` assertion above
- api: `gh pr merge --squash` via `launcher_lib.py broker-merge`
  feasibility: verified via existing-call-site AND a live capability probe — squash is hardcoded at
  `launcher_lib.py:6427` (primary) and `:6472` (retry), which is precisely why D9 accepts a squashed
  history. Permission and repository capability probed live on 2026-08-10:
  `gh api repos/3D-Stories/design-doc-publish --jq .permissions` →
  `{admin: true, maintain: true, push: true, pull: true, triage: true}`, and the merge settings →
  `{merge: true, rebase: true, squash: true}`. So squash merging is enabled on this private repo and
  this identity may merge here
  failure: fail-loud

No repository-settings mutation is performed. Pass 2 proposed one; it needed admin scope, appeared
in no `platform_apis` entry, and created a rollback gap. It is removed rather than justified — D9
makes it unnecessary.

## Failure modes

| Failure | Detection | Response |
| --- | --- | --- |
| A depth path climbing above the package | migrated gate red | the two fixes; audit covered `.parent` chains **and** `parents[N]` |
| Out-of-prefix fixture missed | gate red while the node-ID diff stays empty | why the gate must run — a count check cannot see this |
| `index/index.html` or `__pycache__` copied | `git ls-files` assertion before commit | `.gitignore` covers both; the copy excludes them by construction |
| `REL` fixed in one file only | suite red for the wrong reason | change both together; the real-invocation check is the actual proof |
| Gate command not recognized | `derive` reports `has_tests: false` | the AC4 assertion; never assumed |
| Licence incompatible with vendored material | per-file provenance read | audit here, or move AC6 to child #4 and say so |

## Security implications

`index/index.html` embeds 36 live Vercel project slugs. It is **excluded from the copy**, so unlike
the retired pipeline it never enters this repo in any commit or any ancestor. This is the security
argument for the simpler design.

`references/` is untrusted data and never instructions, and 12 of its 20 templates contain a
`<script>` block. Per the owner's resolution it copies now.

**"Nothing in this repo renders it" is verified, not asserted.** The only code that opens the
directory is `tests/test_vendored_references.py:34`
(`REFERENCES = Path(__file__).resolve().parent.parent / "references"`) — the guard that pins the
vendored set and reads them as data; it *is* the leak detector. Every other occurrence is either a
provenance docstring (`scripts/render/templates/module_map.py:6`, `slide_deck.py:6` — "Measured off
`references/…`") or the English word "references" about asset links in `lint.py` and
`publish_doc.py`. The render engine never reads the directory, matching
`references/README.md`'s own claim.

The PR states that boundary explicitly. Child #4 keeps the disposition question, including the
not-offline-safe `@import` noted under Licence.

**No credentials or account identifiers are introduced.** Hostnames are a different matter, and the
absolute claim would be false: the 7 vendored theme packs each open with
`@import url('https://fonts.googleapis.com/…')`, which is a hostname and becomes a real network
request whenever a theme is applied or simply opened in a browser, disclosing client network
metadata to Google. That is pre-existing in the vendored material and documented in
`references/README.md`; this change relocates it without altering it, and it is listed under Licence
as a matter for child #4. Stated here so the security section does not contradict its own document.

What the copy deliberately keeps out is the account-identifying artifact: `index/index.html` and its
36 Vercel project slugs never enter this repo in any commit. The repo is private today, and child #4
plus `claude-skills#9` gate anything that would make it public.

## Licence (AC6) — audited, and it resolves here

The audit is **done**, from `references/README.md`'s provenance section:

| Vendored set | Source | Pinned commit | Licence | Notice |
| --- | --- | --- | --- | --- |
| 20 templates | `nsmith/html` | `eece610140a08ebbfdd96938ee1610b19793d1ec` | MIT | upstream ships none; evidence quoted verbatim in `references/nsmith-html/LICENSE-upstream.txt`. Owner adjudication on issue #38, 2026-08-02: MIT, proceed |
| 7 theme CSS | `keepYaoung/artifact-organizer` | `3e5bc0ef00de784dab48b411b3493c7d72d856ca` | MIT | retained in `references/artifact-organizer/LICENSE-upstream.txt` |

Both are MIT, both notices are present as files, and MIT permits redistribution with the notice
retained. There is therefore no incompatibility and **no fork to defer**: this PR adds `LICENSE`
(MIT) plus a third-party notice section naming those two paths and their retained upstream notices,
scoped so the project licence does not purport to relicense vendored material. **AC6 is satisfied by
this PR.**

Carried to child #4 rather than lost: all 7 theme packs open with
`@import url('https://fonts.googleapis.com/…')`, so the reference material is **not offline-safe** —
opening a theme discloses client network metadata to Google. Already documented in
`references/README.md`; child #4 owns what to do about it.

## Rollback

Revert the squash-merge commit. Stated precisely: `git revert <sha>` creates a **new** commit and
restores the *content* of `d4913fc`; it does not return `main`'s ref or graph to `d4913fc`. No
repository settings are changed, so nothing outside git needs restoring, and `claude-skills` is
untouched, so no second repo unwinds.
