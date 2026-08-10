# Package design-doc-publish as an installable Claude Code plugin

Issue [#2](https://github.com/3D-Stories/design-doc-publish/issues/2) ·
Epic [#7](https://github.com/3D-Stories/design-doc-publish/issues/7) · Task class: production ·
Date: 2026-08-10 · Base: `e733007`

## The problem

The package installs today by one hand-made symlink:

```
~/.claude/skills/design-doc-publish -> ~/rawgentic/projects/claude-skills/user/design-doc-publish
```

That works on one machine and is invisible to everybody else. A plugin is the supported
distribution path. This change makes the repo installable with `claude plugin install`.

## What the live probe settled, before any of this was designed

Two throwaway plugins were installed and uninstalled under distinct names so nothing could
collide with the live skill. Both results are load-bearing here.

- **A `.skillignore` file excludes nothing from an installed plugin.** With `source: "./"`, the
  install copied the entire source tree into the cache — the probe's `references/` and
  `scripts/tests/` directories included. The Step-2 plan assumed otherwise and was wrong.
- **The marketplace entry's `source` is the only lever on what ships.** With `source: "./dist"`,
  only that subtree was copied; a sibling `references/` was not installed.
- `${CLAUDE_PLUGIN_ROOT}` is the install-root variable (live use: ponytail, watch, i-have-adhd,
  security-guidance). Plugin skills live at `skills/<name>/SKILL.md` — verified against
  frontend-design, superpowers, watch and rawgentic in the local cache.
- A real plugin skill gets **no entry under `~/.claude/skills/`** at all (frontend-design has
  none), so every `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/design-doc-publish/...` path in
  `SKILL.md` is categorically wrong once this ships as a plugin.

```yaml
platform_apis:
  - api: "claude plugin install <plugin>@<marketplace>"
    claim: "copies the marketplace entry's `source` subtree verbatim into
            ~/.claude/plugins/cache/<market>/<plugin>/<version>/"
    evidence: "verified via live probe of the exact shipped invocation, 2026-08-10 —
               ddp-probe (source './') copied all 7 files including references/ and
               scripts/tests/; ddp-probe2 (source './dist') copied only the 3 files under dist/."
  - api: ".skillignore"
    claim: "does NOT exclude paths from the installed plugin bundle"
    evidence: "live probe — .skillignore listed references/ and scripts/tests/ and both
               installed anyway. This falsified the Step-2 inference and forced the design below."
  - api: "${CLAUDE_PLUGIN_ROOT}"
    claim: "resolves to the plugin install root and is the supported replacement for the
            ${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/<name> prefix"
    evidence: "precedent, read at file:line in four installed plugins' hooks
               (ponytail hooks/claude-codex-hooks.json:9, watch hooks/scripts/check-setup.sh:53,
               i-have-adhd hooks/hooks.json, security-guidance hooks/sg-python.sh)."
  - api: "claude plugin uninstall <plugin>"
    claim: "removes the plugin from settings but LEAVES the version directory on disk,
            marked with a .orphaned_at file"
    evidence: "live probe — after uninstall, ~/.claude/plugins/cache/ddp-probe-market/
               ddp-probe/0.0.1/ still held every file plus .orphaned_at, and needed an
               explicit rm -rf. AC6 is written against this real behavior, not the assumed one."
```

## The design

**The shipped tree is the repo root** (`source: "./"`), and everything in it is licensed. That
is achieved by removing the one unlicensed set rather than by a manifest rule that could rot.

1. **`.claude-plugin/plugin.json`** — the eight fields AC1 names, modelled on
   `projects/rawgentic/.claude-plugin/plugin.json`, which carries exactly those eight.
2. **`.claude-plugin/marketplace.json`** — the repo is its own marketplace, as rawgentic's is:
   `source: "./"`, `strict: true`, `skills: ["./skills/design-doc-publish"]`.
3. **`SKILL.md` moves to `skills/design-doc-publish/SKILL.md`**, and its three absolute paths
   (lines 12, 42, 81) change from `${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills/design-doc-publish/`
   to `${CLAUDE_PLUGIN_ROOT}/`.
4. **`references/nsmith-html/` is deleted** (20 templates + `LICENSE-upstream.txt`) — owner
   decision D12. It has no upstream grant, and `docs/third-party-notices.md` already marks it
   excluded from distribution. `references/artifact-organizer/` **stays**: it is MIT, granted by
   upstream, and redistribution is permitted provided its notice travels with it.
5. **Four test files that locate `SKILL.md` at the repo root are repointed** —
   `test_style_reachability.py:29`, `test_chip_vocabulary_is_documented.py:38`,
   `test_publish_doc.py:927` and `:1230`.
6. **The three assertions pinning the old install shape are rewritten** —
   `test_publish_doc.py:1084`, `:1088`, `:1092`. The last one asserted an absolute path *ends
   with* `design-doc-publish/docs/design-language.md`, which pinned the checkout directory's
   name; the replacement asserts the file exists relative to the package root, which is what it
   was actually trying to check.
7. **`tests/test_vendored_references.py`** drops its `nsmith-html` coverage and keeps
   `artifact-organizer`.
8. **`docs/third-party-notices.md`** records the removal, with the pinned upstream commit so the
   set can be restored if a grant is ever established.
9. **A new guard test** pins what this change is for: the manifest carries all eight fields, the
   marketplace lists the skill, `SKILL.md` uses `${CLAUDE_PLUGIN_ROOT}`, no
   `~/.claude/skills/`-rooted path survives anywhere, and no unlicensed vendored set is present.
10. **`README.md`** gains a short install section. The full stranger-facing rewrite is #3's, and
    this change must not pre-empt it.

## Why not the alternatives

- **A committed `dist/` build tree.** Works (probe 2 proves it), but a remote install reads the
  repo, so `dist/` must be committed — about 115 files existing twice in a repo whose own
  `.gitignore` already argues against committed derived artifacts. Rejected as the larger,
  driftier change.
- **Moving the runtime into a packaged subdirectory.** Same effect, but moves ~120 files and
  rewrites every test path. Rejected on size.
- **Shipping the unlicensed set anyway.** Contradicts `docs/third-party-notices.md` and D11.

## Risk

**M, and it is mostly a path risk.** The render engine itself is root-name-portable — every
self-path site is structure-relative (`scripts/publish_doc.py:60-61`, `index/build_index.py:60`,
`scripts/render/lint.py:571,627`, `scripts/render/__init__.py:714`, `scripts/render-doc:24-25`),
so moving the package root does not break rendering. The risk is concentrated in `SKILL.md`'s
prose paths and the tests that pin them, which is why item 9 adds a guard rather than trusting
the edit.

The failure mode AC4 exists to catch: a plugin that installs cleanly and cannot render, because a
path that resolved under the symlink does not resolve under the install root. AC3 requires a
genuinely fresh session because a live session holds already-resolved paths.

## Acceptance criteria mapping

| AC | Covered by |
| --- | --- |
| 1 — manifest with 8 fields | Item 11, guard test in item 9 |
| 2 — description a stranger can act on | Item 1 |
| 3 — installs, invocable in a fresh session | Verified by install + a genuinely new session |
| 4 — installed copy renders end to end, 7 stages OK | **PARTIAL — not verified.** Stages 1/7, 2/7 and 3/7 passed from the installed copy, and a lint message resolved a path inside the install root. Stages 4-7 deploy publicly and were NOT run, so the seven-stage claim is UNSUBSTANTIATED and recorded as a deferral |
| 5 — stated version, tagged release | **PARTIAL.** The manifest states `1.0.0`. NO tag is created by this change: the cross-model review showed the plugin cannot complete its advertised work for anyone but the author until #9 lands, so tagging a release would publish a claim that is not true yet. #9 is a release prerequisite |
| 6 — uninstall is clean, no dangling symlink or stale path | Verified against the REAL uninstall
  behavior probed above: the version directory is left behind marked `.orphaned_at`, so "clean"
  is asserted about settings and the skill's availability, and the residue is documented rather
  than claimed absent |

---

## Amendments after the Step 4 design gate

The cross-model review (reviewer `gpt-5.6-sol`) returned seven findings. Two were Critical, one was
refuted with evidence, and one changed a decision the owner had already made. The design above
stands except where amended here.

### 11. The manifest, concretely (finding 5)

The design named a count instead of the fields, which is not implementable from the artifact alone.
`.claude-plugin/plugin.json` ships exactly:

```json
{
  "name": "design-doc-publish",
  "version": "1.0.0",
  "description": "Render a design or architecture document from markdown to a standalone HTML page and deploy it to Vercel. One command renders, lints, deploys and verifies.",
  "author": {"name": "3D-Stories", "url": "https://github.com/3D-Stories"},
  "homepage": "https://github.com/3D-Stories/design-doc-publish",
  "repository": "https://github.com/3D-Stories/design-doc-publish",
  "license": "MIT",
  "keywords": ["design-docs", "architecture", "markdown", "html", "vercel", "documentation", "rendering", "publishing"]
}
```

### 12. Prove WHICH copy the verification exercised (finding 1, Critical)

`~/.claude/skills/design-doc-publish` still exists as a hand-made symlink, and issue #2's own Scope
forbids removing it — that is child #6, deliberately last. So a fresh session could resolve the
symlink rather than the plugin, and AC3/AC4 would silently test the old copy.

The symlink is NOT removed here. Instead AC3 and AC4 must assert the resolved root. The skill that
answers must report a path under `~/.claude/plugins/cache/`, and evidence is captured verbatim. A
verification that cannot name its own root is treated as a failure, not a pass.

### 13. AC6 says what uninstall really does (finding 2, Critical)

The design contradicted itself: it recorded that uninstall leaves the version directory behind
marked `.orphaned_at`, while AC6 demands no stale path. Probed behavior wins. The AC6 check now
removes that exact orphaned directory and asserts BOTH that the plugin is absent from settings and
that the cache path is gone. The residue is cleaned, not excused. A comment on #2 records that
`claude plugin uninstall` does not do this by itself.

### 14. `${CLAUDE_PLUGIN_ROOT}` — refuted, with one real remainder (finding 3)

The reviewer doubted the variable resolves in a `SKILL.md` context. Measured: it is not a shell
variable at all. `printenv CLAUDE_PLUGIN_ROOT` in a tool shell returns nothing. It is a token the
harness expands when it loads skill content. Proof from this session: `skills/switch/SKILL.md:86`
on disk reads `${CLAUDE_PLUGIN_ROOT}/hooks/post_update_reconcile.py`, and the copy delivered into
this session's context carried the fully expanded absolute path.

So item 3 stands for `SKILL.md`. The real remainder: a HUMAN copying that command into a terminal
gets a broken path, because their shell does not expand it. The README therefore must not use the
variable in a copy-pasteable command.

### 15. Document the marketplace step (finding 4)

`claude plugin install` cannot resolve `design-doc-publish@design-doc-publish` until the marketplace
is registered. Both commands are documented, in order:

```
claude plugin marketplace add 3D-Stories/design-doc-publish
claude plugin install design-doc-publish@design-doc-publish
```

### 16. Referential integrity after the deletion (finding 6)

Deleting `references/nsmith-html/` leaves dangling mentions. Confirmed by grep: nine template
modules under `scripts/render/templates/` name those files in comments, plus `references/README.md`,
`references/manifest.json` and `tests/test_vendored_references.py`. Every one is updated, and the
item-9 guard asserts zero surviving references outside the third-party notices, where the record of
the removal deliberately remains.

### 17. What must not ship, and a setup flow for people who are not the owner (finding 7 + owner decision D13)

Finding 7 measured the bundle rather than assuming it. `source: "./"` ships all 137 tracked files,
including `docs/vercel-account.md`. That file documented one account's deployment-protection
posture, which is a disclosure to every stranger who installs the plugin. The specifics are
deliberately NOT restated here: the Step-8a review pointed out that this document ships too, so
repeating them would reproduce the very leak that deleting the file was meant to close. Escalated
to the owner, who had not had this in front of them when D12 was decided.

**Owner decision D13, then D14.** Two things follow, and only the first belongs to this change.

**Stays in #2, because it is about what ships:** `docs/vercel-account.md` is removed from this
repo. It documents one account, not the tool.

**Moved OUT of #2 into its own child, [#9](https://github.com/3D-Stories/design-doc-publish/issues/9)
(owner decision D14):** the first-run setup flow. A stranger who installs this plugin still cannot
use it, because `DEFAULT_WORKSPACE = Path.home() / "rawgentic" / ".rawgentic_workspace.json"` is
hardcoded at `scripts/publish_doc.py:134` and `index/build_index.py:75`, and nobody else has that
file. #9 carries the setup entry point — modelled on the `watch` plugin's
`skills/watch/scripts/setup.py`, with `--check` and `--json` modes and a `can_proceed` gate kept
separate from an ideal `status` — and the retirement of that default. #9 depends on #2 and sits in
this run's queue, ahead of #5.

**So #2 stays inside its six original acceptance criteria.** The design gate widened this child,
and the owner narrowed it back by splitting the work out rather than by dropping it.
