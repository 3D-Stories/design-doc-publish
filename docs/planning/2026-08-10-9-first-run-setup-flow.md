# First-run setup flow — design

Issue [#9](https://github.com/3D-Stories/design-doc-publish/issues/9). Epic
[#7](https://github.com/3D-Stories/design-doc-publish/issues/7), child 5 of 5 in this run.

## The problem in one sentence

A stranger installs this plugin and stops at stage 2 of 7, because the workspace file and the Vercel
team are the author's own machine written into the source.

## Approach

Two approaches were weighed. The second is chosen.

### Approach A — make the workspace optional and degrade

Drop the known-project check when no workspace is configured, accept any `--project` that matches
the name shape, and print a notice.

**Against it, and it is decisive:** acceptance criterion 5 asks for a *failure* — "every entry point
that needs one **fails** with a message naming what to run". A degradation is the opposite of that.
It also throws away the guard's whole purpose: the check is what refuses `deploy`, `site` and
`final-final`, names that pass a shape check and mean nothing. A stranger deserves that guard as
much as the author does.

### Approach B — configure the location, refuse legibly when it is absent *(chosen)*

The workspace file keeps its meaning and its guard. Only its **location** becomes configurable, and
the same for the Vercel team. When either is unconfigured, the entry point that needs it refuses
with one sentence naming exactly what to run.

**Why this one:** it is literal AC5 and AC6 compliance, it changes no behaviour for a configured
user, and it adds no concept. The cost is that a stranger must run setup before publishing — which
is what a first-run setup flow *is*.

**Effort:** ~7 source files, ~5 test files, 2 manifests, 2 documents. **Risk: M**, and the issue
names the failure mode correctly — a setup flow that works only on the machine that wrote it. AC6
exists to catch that, and it is discharged by a subprocess test with a scrubbed environment, not by
reasoning.

## The scheme

### Where a user's configuration lives

`${XDG_CONFIG_HOME:-~/.config}/design-doc-publish/config.json`.

**Not inside the install.** A plugin is installed into a versioned cache directory
(`~/.claude/plugins/cache/design-doc-publish/design-doc-publish/<version>/`) which is replaced on
upgrade, so configuration written there is lost on the next release.

`--config` and `DESIGN_DOC_PUBLISH_CONFIG` select a different file, which is what makes the whole
scheme testable without touching a real home directory. Their precedence is its own contract, stated
here rather than left for each entry point to guess *(review R3-6)*:

```python
def config_file(*, cli_value=UNSET) -> Path: ...
```

`--config` beats `DESIGN_DOC_PUBLISH_CONFIG`, which beats
`${XDG_CONFIG_HOME:-~/.config}/design-doc-publish/config.json`. An explicitly empty value at either
selector is an error, exactly as it is for the two settings. A relative value is resolved against the
current process's working directory and never stored. **Every entry point calls this once** and
passes the resulting absolute path to both setting resolvers, so a single run cannot read two
different config files.

Shape — every key optional, so a partially-configured state is representable:

```json
{
  "version": 1,
  "workspace_file": "/home/someone/.config/design-doc-publish/workspace.json",
  "owned_workspace_file": "/home/someone/.config/design-doc-publish/workspace.json",
  "vercel_scope": "my-team"
}
```

`owned_workspace_file` records **which exact path** this package created — not a boolean *(review
R3-1, and the bug it names is real)*. A `workspace_owned: true` flag would go stale the moment a
`--workspace-file` flag, an environment variable, or a hand-edited `workspace_file`
selected a different file: the flag would still read `true` while resolution pointed somewhere else,
and `--add-project` would write to a file this package never created. Binding ownership to the
normalized path removes the gap. `--add-project` writes only when the **resolved** path equals
`owned_workspace_file` exactly. Every other origin — flag, environment, adopted through
`--set-workspace` — is unowned by construction.

It holds **no credential**. Authentication stays entirely with the `vercel` CLI (AC3). It is written
**atomically** — `tempfile` in the same directory, then `os.replace` — so an interrupted setup leaves
the previous config intact rather than a truncated one *(peer, gpt-5.6-sol)*. An unrecognised
`version` is an explicit error, not a silent read.

**The parent directory is created first, and this is not a detail** *(review R2-2 — a first-run
crash in the code written to fix first-run crashes)*. On a genuine first run
`${XDG_CONFIG_HOME:-~/.config}/design-doc-publish/` does not exist, so asking for a same-directory
temporary file inside it raises `FileNotFoundError` before anything is written. Every write path runs
`config_path.parent.mkdir(parents=True, exist_ok=True)` first, and a directory-creation or permission
failure produces one actionable line naming the path — never a traceback.

### Resolution order

One new module, `scripts/user_config.py`, owns both settings. Resolution happens **at call time, not
at import**, so a test can scrub the environment in a subprocess and get the unconfigured path
without import-order tricks. The peer independently flagged the same hazard: computing the config
path at import makes every test depend on the developer's real home and defeats subprocess isolation.

**The resolvers take their CLI value as a parameter. They never read `sys.argv`, and they hold no
module state** *(review R2-1, and it was right about my own draft: a zero-argument `workspace_file()`
cannot see a parsed flag, so either a hidden `sys.argv` dependency or the callers would really own
precedence — contradicting the claim that this module owns it)*.

```python
UNSET = object()            # distinct from None and from ""

def workspace_file(*, cli_value=UNSET, config_path=None) -> Path | None: ...
def vercel_scope(*,   cli_value=UNSET, config_path=None) -> str  | None: ...
```

`UNSET` means the flag was not given. `""` means it was given empty, which is an error. `None` from
an argparse default is treated as `UNSET`, which is why the parsers use `default=None` and the entry
points pass what they parsed. `config_path` carries the `--config` override the same way, so nothing
in this module reaches for process state.

**Workspace file** — `workspace_file(cli_value=…, config_path=…)`:

1. `cli_value`, when it is not `UNSET`;
2. `DESIGN_DOC_PUBLISH_WORKSPACE_FILE` in the environment;
3. `workspace_file` in the config file;
4. otherwise `None`, meaning unconfigured.

**There is no legacy rung, and revision 3 was wrong to keep one.** It read
`~/rawgentic/.rawgentic_workspace.json` "only if it already exists", which sounds harmless. The
Step-8a review named it correctly: a machine that happens to have a file there would silently adopt
it, without the setup run, and then validate project names and group the index against a file its
owner never pointed this tool at. AC4 says the hardcoded default is RETIRED and the location setup
recorded is used instead — **a conditional default is still a default**. Existing users run setup
once, which is one command, and which the refusal names.

**Vercel team** — `vercel_scope(cli_value=…, config_path=…)`: `cli_value`, then
`DESIGN_DOC_PUBLISH_VERCEL_SCOPE`, then `vercel_scope` in the config file, then `None`.

**An explicitly supplied EMPTY value is an error, never a fall-through** *(peer)*. `--vercel-scope ''`
or `DESIGN_DOC_PUBLISH_VERCEL_SCOPE=""` means the user tried to set something; silently dropping to a
lower rung would resolve a team they did not ask for.

There is deliberately **no built-in team fallback**. A wrong team is worse than no team: ambient
Vercel scope is whatever the last `vercel switch` left behind, so a deploy that loses its pin can
land in a personal account. `require_vercel_scope()` raises rather than returning anything a caller
could accidentally pass as `--scope`.

**Absent, unreadable, malformed and empty are four different faults** *(peer)*, and project
validation must tell them apart — a stale unreadable workspace must not silently become an empty
allowlist. Colour lookup stays tolerant of all four (it degrades to a hash by design); only the
`--project` check is strict.

### One resolution, threaded — not re-resolved per stage

`publish_doc.refresh_index()` runs `index/build_index.py` as a **child process** at stage 7. If that
child re-resolves configuration from its own environment, a single publish can render its page under
one team and its index under another. So the resolved values are passed to the child explicitly
*(peer — a real hazard my draft missed)*, and every account-targeting `vercel` argv carries exactly
one `--scope`, from that one resolution.

### The refusals a stranger sees

One sentence, naming the exact command. Both are raised through the existing `StageError` machinery,
so the exit code still encodes the stage.

Stage 2, no workspace configured:

```
publish_doc: FAILED at stage 2: no workspace file is configured, so --project 'x' cannot be
checked against a known set. Run: python3 <plugin>/scripts/setup.py
```

Stage 4, no team configured:

```
publish_doc: FAILED at stage 4: no Vercel team is configured, and deploying without one can land
the page in whichever account `vercel switch` last selected. Run: python3 <plugin>/scripts/setup.py
```

`<plugin>` is the real absolute path of the install, computed from `__file__` — not a placeholder,
because a stranger cannot expand `${CLAUDE_PLUGIN_ROOT}` in their shell (the README already says
so).

### The setup entry point

`scripts/setup.py`, modelled on the `watch` plugin's `skills/watch/scripts/setup.py`.

| Invocation | Behaviour |
|---|---|
| `setup.py` | Reports every check, then prints the exact next command. Writes nothing. |
| `setup.py --check` | Silent on success, exit 0. One actionable stderr line otherwise. |
| `setup.py --json` | The status object on stdout, exit 0 always. |
| `setup.py --init-workspace [PATH]` | **Creates** a workspace file this package owns, and records it. Defaults to `<config dir>/workspace.json`. |
| `setup.py --set-workspace PATH` | Adopts an **existing** workspace file. Normalization contract below. |
| `setup.py --set-scope TEAM` | Records the Vercel team, after validating it and proving access. |
| `setup.py --add-project NAME` | Adds a project name to a workspace file **this package owns**. Data contract below. |

`--json` keys, at least: `status`, `can_proceed`, `first_run` (the three AC2 names), plus
`config_file`, `workspace_file`, `vercel_scope`, `vercel_cli`, `authenticated`, `scope_list_accessible`
and `project_count`. Captured CLI output is never included.

#### The state table

`status` is the FIRST actionable fault in the order below, so coexisting faults have one defined
answer *(review R2 — the enum alone left precedence undefined, and two implementations could disagree)*.

| Order | `status` | Condition | `can_proceed` | `project_count` | `--check` exit |
|---|---|---|---|---|---|
| 1 | `config_version_unsupported` | the config file names a `version` this build does not know | false | `null` | 4 |
| 2 | `needs_vercel_cli` | `shutil.which("vercel")` is `None` | false | `null` | 2 |
| 3 | `needs_login` | CLI present, `vercel whoami` non-zero | false | `null` | 3 |
| 4 | `needs_config` | no scope configured, **or** no workspace file resolved | false | `null` | 4 |
| 5 | `vercel_probe_failed` | a scope is configured, but the scoped listing could not be **executed, parsed, or read** for a `contextName` | false | `null` | 5 |
| 6 | `scope_denied` | the scoped listing answered, for a **different** context | false | `null` | 3 |
| 7 | `workspace_missing` | the resolved workspace path does not exist | false | `null` | 4 |
| 8 | `workspace_unreadable` | it exists but cannot be read | false | `null` | 4 |
| 9 | `workspace_malformed` | it reads but is not an object, or `projects` is not a list | false | `null` | 4 |
| 10 | `ready_no_projects` | everything above satisfied, `projects` is a valid **empty** list | **true** | `0` | 0 |
| 11 | `ready` | as row 10 with at least one project | true | `> 0` | 0 |

Rows 1 and 7-9 answer the review's demand for distinct workspace and config-version outcomes
*(review R2-3)*. `workspace_empty` is deliberately **not** a separate row: an empty-but-valid project
list is row 10, where `can_proceed` is already `true`, because the literal `workspace` bucket
publishes without any registered project. Adding a fault row for it would contradict that.

`project_count` is `null` whenever the workspace could not be read as a list, and an integer only
when it could. A count of `0` therefore means "read it, it is empty", never "could not read it".

`first_run` is `true` when no config file exists, independently of every row above.

`scope_denied` shares exit 3 with `needs_login` deliberately: both are fixed by the user acting on
Vercel. **`vercel_probe_failed` does not** *(review R2-5)*. Reporting a network blip, a timeout, an
unsupported flag or a changed JSON shape as an access denial sends the user to fix a permission they
already have. It gets its own code, and its own stderr line naming the command kind and the failure
reason — with the CLI's own output sanitized to one line rather than swallowed, because
`--json` excludes captured output and a cause nobody can see is not a diagnosis.

**`status` and `can_proceed` are deliberately different questions**, which is the shape worth
copying from `watch`. **Row 10** is what proves it *(peer)*: it represents a configured user with an
empty project list, where `status` is `ready_no_projects` and `can_proceed` is **true**, because the
literal `workspace` bucket publishes without any registered project. A first run lacking only an
optional thing is not reported as broken. **Row 5 is `vercel_probe_failed` and always carries
`can_proceed: false`** — an earlier revision pointed this paragraph at row 5 and the row numbers then
moved underneath it, which left two incompatible contracts for the same fields *(review R3-5)*.

#### Proving the team, and why `whoami --scope` is not the check

Authentication and authorization are different questions, and `whoami` answers only the first
*(peer)*. My first revision reached for `vercel whoami --scope <team>`; the cross-model review was
right that this proves nothing about access, and both probes back that up:

- `vercel whoami --scope no-such-team-9xq` → **exit 1**, `Error: The specified scope does not exist`.
  So it rejects a **nonexistent** team. It says nothing about an existing team the user cannot use,
  and that state cannot be constructed on this machine — there is one account.
- `vercel project ls --format json --limit 1 --scope <team>` → **exit 0**, JSON on stdout carrying
  `contextName: "3d-stories"`.

So setup verifies the team with **the same scoped read the publisher itself makes**, and asserts
`contextName == the configured scope`. That is the exact check `index/build_index.py:182-183` already
performs on every listing, so setup proves the thing stage 4 will depend on rather than a proxy for
it.

**That single call answers two different questions, and they must not be collapsed** *(review R2-5)*:

- the call **ran and returned a JSON object carrying a `contextName`** — a capability check on the
  `project ls --format json` surface itself. If it could not be executed, timed out, rejected the
  flags, produced non-JSON, or produced JSON without `contextName`, that is `vercel_probe_failed`.
  Setup names the command kind and one sanitized line of the CLI's own output.
- the `contextName` **equals the configured scope**. Only a mismatch is `scope_denied`.

This is the whole of the CLI-compatibility contract, and it is deliberately not a version range
*(review R2-6, partially declined)*. Pinning a supported `vercel` version range would be a promise
this package cannot keep — it does not install the CLI and cannot police what is on `PATH`. Probing
the exact surface it needs, and reporting a probe failure as a probe failure, is the enforceable
version of the same idea. The observed CLI is recorded in `--json` as `vercel_cli` for diagnosis.

**What this proves is LISTING access, and the field is named for that** *(review R3-3, and the
overclaim was mine)*. A principal may be allowed to list a team's projects and still not be allowed
to deploy to it. There is no non-mutating probe for deployment permission — the only way to prove a
deploy is permitted is to deploy — so setup does not claim it. The JSON key is
`scope_list_accessible`, not `scope_accessible`, and `ready` means "setup found nothing wrong",
never "publishing is authorized". Stage 5 gains its own fail-loud refusal for a deploy rejected on
authorization, naming the team and saying plainly that setup cannot detect this in advance.

#### `--set-scope`: the validation contract

A team slug reaches a subprocess argument **and** generated HTML, so "validated for shape" is not a
rule *(review R1)*. The rule is the package's own existing name pattern,
`scripts/publish_doc.py:260` — `^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$` — with a 100-character ceiling
(`MAX_NAME`, already defined at `publish_doc.py:133`). Reusing it rather than inventing a second
shape is the point.

That pattern already excludes every hazard the review named: a leading `-` cannot match, so an
option-like value is impossible; whitespace, control characters and non-ASCII cannot match. The
validator runs on **every** rung — flag, environment and config file — and on the `--set-scope`
setter, so a hand-edited config cannot smuggle a value past it. Case is not normalized, it is
**rejected**: Vercel lowercases slugs anyway, and silently rewriting a user's input is how `Rawgentic`
and `rawgentic` became two projects (`derive_name`, `publish_doc.py:270`).

#### `--set-workspace`: the path contract

"Records the location" does not say how a path is normalized *(review R3)*. It expands `~`, resolves
a relative argument against setup's own working directory, requires the target to be a readable
regular file, and stores an **absolute, normalized** path. Storing what the user typed would make
resolution depend on whichever directory a later publish ran from, turning a correctly configured
workspace into "configured but missing".

The non-persisted rungs differ, deliberately: `--workspace-file` and the environment variable are
resolved against the **current** process's working directory each time, because they are per-run
overrides and normalizing them into something durable would be a lie.

#### `--init-workspace`: how a stranger gets a workspace at all

Revision 2 had a dead end, and the review found it *(review R2-4)*: `--set-workspace` requires an
already-existing readable file, and `--add-project` may only write to a file this package created —
so nothing could ever create the first one. A new user was stuck.

`--init-workspace [PATH]` closes it. It defaults to `<config dir>/workspace.json`, writes
`{"version": 1, "projects": []}` atomically, stores the normalized absolute path as `workspace_file`,
and sets **`workspace_owned: true`** in the config. If the target already exists it refuses rather
than truncating, and points at `--set-workspace` for adoption. Adopting through `--set-workspace`
sets `workspace_owned: false`, because this package did not create that file.

#### `--add-project`: the data contract, and the file it may not touch

Two rules, and the first is the important one.

**It only ever writes to a workspace file this package created**, which is exactly what
`workspace_owned` records. The resolved workspace file may be the author's real
`~/rawgentic/.rawgentic_workspace.json` — rung 4 selects exactly that on this machine — which belongs
to a different tool and is read by every concurrent rawgentic session on the host *(review R4)*.
Writing there is out of the question. Ownership is a **stored fact, never inferred from the path**:
a path check would call any file under the config directory ours, including one the user pointed
there deliberately. If the resolved workspace is not owned, `--add-project` refuses, names the file,
and offers `--init-workspace`.

**The shape it writes** *(review R5 — "adds a minimal one" defined no data contract)*:

```json
{"version": 1, "projects": [{"name": "payments-api"}]}
```

`name` is validated with the same pattern as a scope. An identical entry is **idempotent**, a
differing entry under an existing name is a refusal rather than a silent overwrite, existing entries
and unknown fields are preserved verbatim, and the write is the same-directory `tempfile` plus
`os.replace` used for the config. The entry carries no `path` key, which is why `vdl_packs`
must treat an absent `path` as silence rather than a warning.

**`vercel login` is never run automatically — printed only.** It is an interactive command that
mutates this machine's global authentication state. A script inside an agent session must not do
that on its own, and an unattended run must never do it at all. Setup prints the exact command and
re-checks afterwards, which is what "walks the user through it" means here.

**`vercel teams ls` is printed, never parsed.** The slug sits in a human-formatted table on stderr,
and `index/build_index.py:201-216` establishes this package's opposite rule in its own words — the
JSON surface is read from stdout and there is "deliberately **no fallback to the table**", because
table parsing masks the one event that should stop a publish *(review R6)*. Setup shows the user
their teams and has them pass `--set-scope <slug>`. No parsing, and the package's own rule stays
intact.

### How the shared module is loaded — not with `import`

`scripts/user_config.py` is loaded by **exact path, under a private name, without consulting
`sys.path`** — the pattern `scripts/publish_doc.py:64-79` defines as `_load()` and applies to five
modules, that `index/build_index.py:58-72` repeats for `vdl_packs`, and that
`scripts/render/__init__.py:710-726` repeats again with a comment saying the duplication is
deliberate because "a shared helper would itself have to be loaded the same way, so the guard cannot
live behind the thing it guards".

`scripts/render-doc:1-19` records why, and records that the hazard was **"observed live, not
theoretical"**: a foreign module earlier on `sys.path` is selected AND has its top-level code executed
before any check can reject it. A plain `import user_config` would reopen exactly that hole *(review
R7)*, on the one module that now decides which Vercel account a public page is deployed to. Each load
site keeps the realpath containment check, and `setup.py` resolves its sibling from
`Path(__file__).resolve().parent` rather than trusting `sys.path[0]`.

### What changes at the four hardcoded sites

| Site | Today | After |
|---|---|---|
| `scripts/publish_doc.py:134` | `DEFAULT_WORKSPACE = Path.home() / …` | constant retired, `user_config.workspace_file()` at use |
| `scripts/publish_doc.py:781` | `default=str(DEFAULT_WORKSPACE)` | `default=None`, resolved after parsing so the flag still wins |
| `index/build_index.py:75` | same constant | same treatment |
| `index/build_index.py:721` | same argparse default | same treatment |
| `scripts/render/__init__.py:744` | the literal inlined as a default | `default=None`; `--project` omitted still renders in the default palette |

And for the team: `VERCEL_SCOPE` retired from `scripts/publish_doc.py:129` and
`index/build_index.py:39`; every `--scope` call site and the `contextName` assertion at
`build_index.py:182` read the resolved value; the two output sites that bake the team into the page
(`build_index.py:516` title, `:607` eyebrow) render the resolved team instead.

**Those two output sites become an injection surface the moment the team is user-supplied, and both
must be HTML-escaped** *(peer — a genuine security gap my draft missed)*. Today they interpolate a
constant, so no escaping was needed and none is there. `build_index.py` already imports `html` and
escapes every other interpolated value; these two must join them, and the scope is validated for
shape before it is ever passed to a CLI.

### One correctness fix this forces, and it is not cosmetic

`scripts/vdl_packs.py` must accept `workspace_file=None` as a real state meaning "no workspace",
returning the seed-or-hash colour silently — exactly what it already does for a workspace file that
does not exist. Without this, `group_colors(group, None)` raises `AttributeError` from
`None.exists()` the moment the constant is retired.

Related: `_project_config` currently warns "entry has no path" for a workspace entry with no `path`
key. A minimal workspace created by `--add-project` has exactly that shape, so every render would
print a warning. An **absent** `path` becomes silent (there is no config to read — that is absence,
which the module's own rule says is the silent case); a **present but wrong** path still warns.

## File changes

**Source**
- `scripts/user_config.py` — new. Resolution, the config file, the refusal messages, `SETUP_COMMAND`.
- `scripts/setup.py` — new. The entry point above.
- `scripts/publish_doc.py` — retire both constants; resolve once; thread the result through stages
  4-7 including the index-refresh child; two legible refusals.
- `index/build_index.py` — same, plus the two escaped output sites and the `contextName` assertion.
- `scripts/render/__init__.py` — argparse default only.
- `scripts/vdl_packs.py` — accept `None`; silence the absent-`path` warning.

**Tests**
- `scripts/tests/test_setup.py` — new. The setup surface, and AC6.
- `scripts/tests/test_user_config.py` — new. Resolution order, malformed input, empty-value refusal,
  unsupported version, and the absent/unreadable/malformed/empty distinction.
- `scripts/tests/test_publish_doc.py`, `test_build_index.py`, `test_vdl_packs.py` — the assertions
  that read the retired constants now assert the resolved value.
- `scripts/tests/test_plugin_packaging.py` — `scripts/setup.py` joins the promised-files list (that
  is AC1's guard); the fixture-name guard follows the rename below.
- `scripts/tests/fixtures/vercel_project_ls.json` / `.txt` — `contextName` and the project name.

**Documents and manifests**
- `README.md` — the "Honest limits" section is false the moment this lands.
- `skills/design-doc-publish/SKILL.md` — the setup command.
- `docs/assets-disposition.md` — it hands three residuals to #9 by name; two of them close here.
- `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` — both descriptions say publishing
  is "not yet available … until #9 lands".

### The two residual names, and why they close here

`docs/assets-disposition.md` promised #9 would untangle them.

- **The team `3d-stories` in the fixtures** is *coupled*: the tests compare the fixture's
  `contextName` against the code's team, so the pair could not move apart. Once the team comes from
  configuration, a test sets it — and the fixture becomes `example-team`.
- **`claude-skills-plan-786`** is *derived* by the tests as `<project>-<type>-<ref>`. Renaming it
  alone desynchronises the fixture from the test that builds it — attempted during #4, 80 failures.
  Renaming **both sides together** is mechanical and safe: `example-plan-786`, with the classifying
  workspace entry becoming `example`.

`docs-index` stays. It is `SELF_PROJECT`, the index's own project name, structural rather than
private, and a stranger's index carries the same name in their own account.

**`3d-stories` as the public GitHub org is not touched** — it appears legitimately in the manifests,
the repository URLs and the README, and `test_plugin_packaging.py:335-337` already refuses to hunt
that string for exactly this reason.

## Failure modes

| Mode | Handling |
|---|---|
| Config file malformed or undecodable | Warn once to stderr, treat as unconfigured. Never a traceback. |
| Config `version` unrecognised | An explicit error naming the file — not a silent partial read *(peer)*. |
| Config file present, `workspace_file` points at a path that does not exist | Refuse naming **both** the configured path and the setup command — "configured but missing" is a different fault from "never configured" and the message must say which. |
| Workspace file unreadable, malformed, or empty | Precisely *(review R3-7 — the earlier wording promised three refusals and defined only two)*: an unreadable file is `workspace_unreadable`; a zero-byte or invalid-JSON file is `workspace_malformed`, because zero bytes is not valid JSON; a valid object whose `projects` is `[]` is `ready_no_projects` and **may proceed**. A stale unreadable file therefore never degrades into an empty allowlist that refuses every name for the wrong reason. |
| An explicitly supplied empty flag or environment value | An error, never a fall-through to a lower rung *(peer)*. |
| `vercel` CLI absent | `shutil.which` returns `None`; setup reports `needs_vercel_cli`. `publish_doc` already wraps the `FileNotFoundError` path. |
| `vercel whoami` writes its banner to stderr | Read **stdout** only. Verified live 2026-08-10. |
| `whoami` succeeds but the team is inaccessible | A separate `scope_denied` state, from a scoped read-only probe *(peer)*. Authentication is not authorization. |
| A resolved scope of `None` reaching a `vercel` call | Impossible by construction: `require_vercel_scope()` raises. `--scope` is never conditionally omitted — that is the personal-account hazard. |
| Stage 7's child process re-resolving to a different team | The resolved values are passed to the child explicitly *(peer)*, so one publish cannot straddle two accounts. |
| A user-supplied team reaching the generated HTML unescaped | Both output sites escape *(peer)*, and the scope is shape-validated before any CLI use. |
| Import-time resolution breaking test isolation | Resolution is a function call, never module-level. |
| `Path.home()` ignoring a scrubbed `HOME` | **Probed live 2026-08-10**: `env -i HOME=/tmp/fake-home-probe python3` returns `Path.home() == /tmp/fake-home-probe`. The AC6 subprocess approach works on this host. |
| Two setups racing | **Locked** *(review R3-2 reversed the earlier decision, correctly)*. Atomic replace keeps each write whole, but it does not make read-modify-write atomic: two `--add-project` runs can both read, both add, and the later replace erases the earlier addition. That is real data loss, not a tidiness point, and the fix is a sibling lock file held across the whole read-validate-modify-replace — stdlib `fcntl.flock`, about ten lines. Documenting a data-loss race as accepted was the wrong call. |
| A setter merging into a config it could not read | Refused. `load()` stays lenient so STATUS can report on a broken machine, and mutations use a strict `load_for_update()` — merging into an empty mapping and replacing the file destroyed the only copy of whatever was in it *(review 8a-1)*. |
| A workspace object with no `projects` key | `workspace_malformed`, in BOTH the setup state table and `require_workspace_file`. Defaulting an absent key to `[]` made setup report ready while the publisher refused every project name *(review 8a-2)*. |
| A truncated listing accepted as proof of access | The probe requires `projects` as a list and `pagination.next`, the same fields the publisher's own parser requires. An empty `projects` stays valid — that is the bootstrap account *(review 8a-5)*. |
| `--init-workspace` creating a file it then cannot record | The file it just created is removed. A created-but-unrecorded workspace is one the user did not ask for and this tool will not use *(review 8a-6)*. |
| Two copies of `user_config` with two `ConfigError` classes | Each entry point catches the class from the copy IT loaded, which holds because each also raises through that copy. Pinned by a test rather than trusted, because it is invisible until it bites. |
| A foreign `user_config.py` earlier on `sys.path` | Cannot be selected: the module is loaded by exact path under a private name, with the realpath containment check the other three load sites use *(review R7)*. |
| `--add-project` pointed at a workspace this package does not own | Refuses, names the file, and points at `--set-workspace` *(review R4)*. It never writes to a file it did not create. |
| A relative `--set-workspace PATH` recorded verbatim | Refused as a class: the setter stores an absolute normalized path, so a later publish from another directory cannot turn a configured workspace into a missing one *(review R3)*. |
| A team slug that is option-like, cased, or carries control characters | Rejected by `^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$` with a 100-character ceiling, on every rung *(review R1)*. A leading `-` cannot match, so an argv injection through the scope is impossible. |
| `--add-project` overwriting an existing entry | Identical entry is idempotent. A differing entry under the same name refuses. Unknown fields and existing entries are preserved *(review R5)*. |
| Coexisting faults reported inconsistently | The state table fixes one precedence order, so `status`, `can_proceed` and the exit code have a single defined answer *(review R2)*. |
| An older `python3` hitting new syntax before setup can report | The floor is **declared** as 3.12 and checked by `sys.version_info` as setup's first action, above a module level an older interpreter can still parse *(reviews R8, R2-7)*. |
| The config directory not existing on a genuine first run | `mkdir(parents=True, exist_ok=True)` precedes every write, and a permission failure names the path *(review R2-2)*. |
| A new user with no workspace file anywhere | `--init-workspace` creates one this package owns. Without it `--set-workspace` and `--add-project` deadlock *(review R2-4)*. |
| A network blip, timeout, rejected flag, or changed JSON shape from the CLI | `vercel_probe_failed`, its own exit code and a one-line sanitized cause — never reported as `scope_denied` *(review R2-5)*. |
| A resolver reading `sys.argv` or holding module state | Impossible by signature: `cli_value` and `config_path` are parameters, and `UNSET` distinguishes "no flag" from "empty flag" *(review R2-1)*. |

## Security implications

- **No credential is ever written.** Setup records a path and a team slug. Authentication lives in
  the `vercel` CLI's own store, untouched.
- **The scope pin is preserved end to end.** The reason it exists — an unpinned deploy landing in
  whichever account `vercel switch` last selected — is unchanged by making the value configurable,
  so the code must refuse rather than fall back. It does.
- **The `contextName` assertion stays.** Asking for a scope and verifying the answer are different
  things; the listing still has to name the team it answered for.
- **The config file is world-readable by default and that is correct** — it holds no secret. Writing
  it 0600 would imply otherwise.
- **`vercel login` is not auto-run**, so no unattended run can mutate machine-global auth state.
- **A dynamic team name is a new injection surface in generated HTML** *(peer)*. Both output sites
  escape, and the scope is shape-validated before it reaches an argv.
- **Tests must never reach the real `vercel` binary.** The AC6 harness puts a fake one first on
  `PATH` and scrubs Vercel environment variables *(peer)* — otherwise a test could touch a live
  account, which would also invalidate the test's own claim.
- AC7 is a property of the shipped tree: the sweep removes the Vercel team and one project name from
  the fixtures and introduces no new account-specific string.

## How AC6 is actually proven

The criterion is "a stranger's path is proven, not assumed", on a development machine that is the
opposite of a stranger's. The peer's warning is the one to design against, verbatim in substance: *a
test that merely hides `~/rawgentic/.rawgentic_workspace.json` while keeping the real XDG config, the
real environment variables and the real Vercel binary is not a first-run test.*

So the harness builds a genuine first-run machine state, in a subprocess:

1. `HOME` and `XDG_CONFIG_HOME` under `tmp_path`. Every `DESIGN_DOC_PUBLISH_*` and `VERCEL_*`
   variable is removed from the child environment.
2. A **fake `vercel` executable first on `PATH`** *(peer)*, driven by a state file so it can fail
   `whoami`, then succeed after a `login`, and answer `project ls --format json` with a chosen
   `contextName`. It appends every argv it receives to a log. It covers the probes **setup itself**
   makes, and nothing more.
3. Assert `setup.py --json` reports `first_run: true`, `authenticated: false`, `can_proceed: false`.
4. Assert `--set-scope` refuses when the fake answers with a different `contextName`, and reports
   `scope_denied`.
5. Run setup against the fake, then assert the config was written **outside the plugin tree**, and
   that the JSON now reports operational truth.
6. Run `publish_doc.py` with an unregistered project. Assert the stage-2 exit code, that stderr names
   the setup command, and that it contains **no traceback**. This case is fully hermetic: stage 2
   precedes every network call, so it needs no `vercel` at all.

**The `--scope` invariant is asserted separately, and this is a corrected design.** The first draft
asserted it from the fake's argv log at the end of the list above — but the list stops at a stage-2
refusal, so that assertion had nothing to observe and would have **passed vacuously**. Both reviews
caught it independently. The remedies differed and the disagreement is recorded as decision D20: the
cross-model review wanted the fake to carry a successful publish through stages 4-7, and I took the
cheaper path that this suite already uses. Its acceptance condition is kept verbatim:

- first assert that each expected account-targeting command **kind** was observed — project listing,
  deploy, and the stage-7 index child;
- then assert each observed argv carries **exactly one** `--scope`, with the configured value;
- and assert the stage-7 child was handed the resolved values rather than left to look them up.

These run in-process against a stubbed `subprocess.run`, which is exactly how
`scripts/tests/test_publish_doc.py:612` and `scripts/tests/test_build_index.py:167` assert the same
property today. A full fake would additionally have to emulate `pagination.next`, a deploy log and a
live URL for the stage-6 verifier — it would become the largest new thing in this change, and it
would pass because the emulator agrees with the code rather than because the code is right.

## Platform / external dependencies

platform_apis:
- api: `vercel whoami` (Vercel CLI 56.5.0) — authentication probe
  feasibility: verified via spike — ran the exact invocation live 2026-08-10 on this host: exit 0,
  `crandrosoff` on **stdout**, the `Vercel CLI 56.5.0 (Node.js 22.22.1)` banner on **stderr**.
  failure: fail-loud
- api: `vercel project ls --format json --limit 1 --scope <team>` — **proves access to a team**
  feasibility: verified via spike — ran live 2026-08-10 with `--scope 3d-stories`: exit 0, JSON on
  stdout carrying `contextName: "3d-stories"` alongside `projects`, `pagination` and `elapsed`. This
  is the exact call `index/build_index.py:244` already makes, and whose `contextName` it already
  asserts at `:182-183` — so setup proves the thing stage 4 depends on, not a proxy for it.
  failure: fail-loud
- api: `vercel whoami --scope <team>` — **NOT used as the authorization check**
  feasibility: verified via spike, and the spike is why it was rejected. `--scope 3d-stories` → exit
  0. `--scope no-such-team-9xq` → **exit 1**, `Error: The specified scope does not exist`. So it
  rejects a NONEXISTENT team and says nothing about an existing team the user cannot use. That second
  state cannot be constructed on this machine, which has one account, so the design does not rest on
  it.
  failure: fail-loud
- api: `vercel teams ls` — **printed for the user to read, never parsed**
  feasibility: verified via spike — ran live 2026-08-10: exit 0, a two-column `id` / `Team name`
  table on stderr with the slug in the `id` column. Parsing it would contradict this package's own
  rule at `index/build_index.py:201-216`, so it is shown and not read.
  failure: fail-loud
- api: `vercel login` — printed, never executed
  feasibility: not exercised, and deliberately so — it is interactive and mutates machine-global
  authentication state. The design takes no dependency on running it.
  failure: fail-loud
- api: `shutil.which`, `os.environ`, `Path.home()`, `os.replace`, `tempfile`, `json` (stdlib)
  feasibility: verified via existing-call-site — each is already used here (`subprocess` and `json`
  at `index/build_index.py:247`, `tempfile` at `scripts/publish_doc.py:834`, `shutil` imported at
  `scripts/publish_doc.py:48`).
  failure: fail-loud
- api: the Python interpreter floor itself — a SEPARATE claim the first draft's citation did not
  support *(review R8, and it was right: an existing call site proves a module is importable, never
  which interpreter version is installed)*
  feasibility: **NOT verified, and this entry says so rather than dressing it up** *(reviews R8,
  R2-7, R3-4 — three rounds, and each caught a different evasion: an existing call site, then the
  absence of a floor, then a capability file I named but never created)*. The measurements are real
  and they are these. There is no floor declared anywhere in the tree — no `pyproject.toml`, no
  `setup.cfg`, no `python_requires` — only README prose naming 3.12. This host has **only** Python
  3.12: `ls /usr/bin/python3.*` returns `python3.12` alone, and none of `python3.8` … `python3.11` is
  on `PATH`. So a pre-3.12 spike **cannot be run here**, and there is no CI in this repository to run
  one elsewhere. Both enforceable contracts the review offered are therefore unavailable, and
  inventing a manifest field no installer consumes would be a capability file in name only.
  **The floor is a DECLARATION, not a verified capability**: Python 3.12, stated in the README, which
  is the version that produced the recorded test count. This is the one claim in this design I would
  most expect to be wrong.
  failure: fail-silent
  surface: `setup.py` keeps its module level parseable by an older interpreter and checks
  `sys.version_info` as its FIRST action, printing one line naming the required version and the
  version in use. Setup is the first thing a stranger runs, so a too-old interpreter yields a
  sentence rather than a `SyntaxError`. The guard is tested by calling its check function with a
  faked `sys.version_info` — which tests the guard honestly, unlike a subprocess test that would
  silently run 3.12 and prove nothing about 3.11.

## Peer consult — what was taken, and what was declined

An independent cross-model peer (`gpt-5.6-sol`, via the review runner, blind both ways — my draft was
on disk before the result was opened) proposed its own design. Both landed on the same core: one
stdlib-only resolution module, XDG config outside the versioned install, `vercel login` delegated
rather than reimplemented, rendering left configuration-free.

**Taken, and each is named at its point of use above:** atomic config writes · the config `version`
check · `--config` / `DESIGN_DOC_PUBLISH_CONFIG` · an explicit empty value being an error · HTML-escaping
the two dynamic output sites · one resolution threaded through the stage-7 child · authentication
versus authorization as separate states · `ready_no_projects` · the absent/unreadable/malformed/empty
distinction · the fake-`vercel`-on-`PATH` AC6 harness with an argv log · the documented concurrency
limit · the fuller `DESIGN_DOC_PUBLISH_*` environment names over my cryptic `DDP_*`.

**Three of those were gaps, not polish** — the unescaped dynamic title, the stage-7 child re-resolving
to a different account, and `whoami` proving authentication but not access.

**Declined, with reasons:**

- **Keeping `DEFAULT_WORKSPACE` and `VERCEL_SCOPE` as `None`-valued compatibility sentinels.** It
  avoids test churn, but AC4 says the default is *retired*, and a surviving name that no longer means
  what it says is a worse legacy than three updated test lines.
- **A `commands/setup.md` slash command.** AC1 asks that setup be reachable from the installed copy;
  `${CLAUDE_PLUGIN_ROOT}/scripts/setup.py` in SKILL.md, plus the README's literal path, is that —
  and `test_the_files_the_skill_promises_are_where_it_says` is already the guard. A new `commands/`
  surface changes the marketplace entry for no criterion.
- **Renaming the concept to a "project registry" with `projects.json`.** The peer kept the existing
  file *shape*, so the rename buys vocabulary, not capability. The workspace file keeps its name and
  meaning; only its location moves.
- **Setup exit codes 0/1/2.** The issue named the `watch` model, and 0/2/3/4 tells the caller which
  of three different things to fix.

## Design gate — revision 2

Revision 1 went through the Step-4 gate: my own review on the security lens, plus an independent
cross-model review of this document (`gpt-5.6-sol`, `review-artifact --type design`). Fourteen
findings, four of them High, none Critical. No volume threshold was reached. The folded loop-back
class was `design`, so one design loop-back was consumed (1 of 2 for this source, 1 of 3 global) and
this is the revised document.

**The four High findings, and what each changed:**

| # | Source | Finding | Change |
|---|---|---|---|
| R7 | mine | A plain `import user_config` reopens the `sys.path` hijack this package hardened against at three separate load sites | New section: the module is loaded by exact path under a private name, with the realpath containment check |
| R4 | mine | `--add-project` would have written to `~/rawgentic/.rawgentic_workspace.json`, a file this package does not own and other sessions read | It refuses on any workspace it did not create, and says so |
| — | cross-model | The AC6 test stopped at stage 2, so its `--scope` assertion had nothing to observe and would have passed vacuously | The invariant moved to a stubbed `subprocess.run`, keeping the reviewer's acceptance condition verbatim (decision D20) |
| — | cross-model | `vercel whoami --scope` proves nothing about access, so `scope_denied` could have called an unusable team usable | Replaced by the scoped listing whose `contextName` must equal the configured slug — probed live both ways |

**The nine Medium and Low findings** produced the state table, the scope-validation contract, the
path-normalization contract, the `--add-project` data contract, the `vercel teams ls` print-don't-parse
rule, and the honest replacement of the interpreter-floor citation. Each is marked at its point of use.

**Four cross-model findings carried `ambiguity_flag: True` and the run did NOT stop.** That is a
judgment recorded as decision D19, with its undo. Each flag's own stated reason is that this
DOCUMENT failed to specify something — "validated for shape names no implementable validation rule" —
rather than that a judgment was needed which the issue does not capture. All four are Medium with no
loop-back class, and each carried a concrete recommendation containing no owner-only decision.
Writing a validator, normalizing a path and drawing a state table are what a design gate is for.

**The residual this section used to accept is gone.** Revision 3 kept the legacy path as a
conditional rung and called the risk contrived. The Step-8a review disagreed at 0.99 confidence, and
was right on the criterion's own words, so the rung was removed rather than argued for.

## Design gate — revision 3

Revision 2 went back through the gate and came out worse than it looked. Seven cross-model findings,
**five of them High** — which is exactly the volume threshold, so this was a volume loop-back rather
than a fold, and the second and last design loop-back was spent (design 2 of 2, global 2 of 3).

Every one of the five was a defect **revision 2 introduced**, and that is the honest summary:
tightening one rule broke another.

| # | Finding | What revision 2 got wrong | Fix |
|---|---|---|---|
| R2-1 | A zero-argument `workspace_file()` cannot see a parsed flag | I listed the flag as rung 1 while giving the resolver no way to receive it. It would have needed a hidden `sys.argv` dependency, or the callers would really have owned precedence | Explicit `cli_value` / `config_path` parameters and an `UNSET` sentinel distinct from `""` |
| R2-2 | The config parent directory is never created | On a real first run that directory is absent, so the same-directory temp file raises before anything is written — **a first-run crash inside the fix for first-run crashes** | `mkdir(parents=True, exist_ok=True)` on every write path, with a named error |
| R2-3 | The state table had no row for four workspace faults or an unknown config version | The failure-modes table demanded distinct refusals the state table could not express | Eleven ordered rows, `project_count` nullable, and `workspace_empty` explicitly folded into `ready_no_projects` |
| R2-4 | **Nothing could create the first workspace** | `--set-workspace` required an existing file and `--add-project` could only write to one this package created. A new user was stuck in a loop with no entry | `--init-workspace`, plus `workspace_owned` as a stored fact |
| R2-5 | `scope_denied` swallowed network, timeout, flag and schema failures | A blip would have told the user to fix a permission they already hold | `vercel_probe_failed` as its own status, exit code and diagnostic |

**Partially declined, with the reason:** R2-6 asked for a supported `vercel` version range. This
package does not install the CLI and cannot police `PATH`, so a range would be a promise it cannot
keep. It probes the exact surface it needs instead, and reports a probe failure as one.

**Fully taken:** R2-7. Revision 2 cited the *absence* of an enforced Python floor as verification of
the floor, which is circular. The floor is now declared as 3.12 and guarded at setup's first line.

**Two findings carried `ambiguity_flag: True` across the two rounds and neither stopped the run** —
recorded as decision D19 with its undo. In both cases the flag's own stated reason was that this
document failed to specify something, and each carried an implementable recommendation with no
owner-only decision in it.

**The design loop-back budget is now spent.** If the next pass returns further Critical or High
findings, the gate closes budget-exhausted under the #798 carve-out rather than escalating — the
global budget still has one, and the escape conditions are checked by command, not by assertion.

## What is deliberately NOT built

- **No configuration framework.** One JSON file, three optional keys, no schema library, no TOML.
- **No credential storage**, in any form, ever.
- **No new concept replacing the rawgentic workspace.** Its meaning and its junk-name guard are
  unchanged; only its location moves and its absence becomes legible.
- **No auto-detection of the team.** Setup lists what `vercel teams ls` returns; the user chooses.
- **No change to the renderer**, which is out of scope by the issue's own words.
- **No fix for the 35-character Vercel alias truncation** (claude-skills#161, surfaced from memory
  during Step 2). Real, and not this issue.

## Multi-PR assessment

One PR. The change is cohesive — retiring the constants, the module that replaces them, and the
entry point that populates it cannot land apart without leaving the tree broken in between. The
mechanical fixture rename is large in occurrence count and small in surface, and splitting it out
would leave `docs/assets-disposition.md` making a claim about #9 that #9 had not yet honoured.
