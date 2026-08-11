---
name: setup
description: Check what design-doc-publish needs before it can publish, and record the answers. Use when publishing fails with a configuration complaint, when the user says "set up design-doc-publish", "configure the doc publisher", "why can't I publish", "which Vercel team is it using", or when a doc render worked but the deploy did not. Use it on a machine that has never published before, and use it to diagnose one that used to work. Rendering needs no setup at all — reach for this only when a page has to reach Vercel.
---

# design-doc-publish setup

Ask the machine what it needs. The answer is one line and an exit code:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" --check
```

Silent with exit 0 means publishing will work. Anything else prints the single next action.

Run it with no flags for the full picture instead — config file, CLI, sign-in, team, workspace
file, project count, status, and whether it can publish:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py"
```

Use `--json` when a script or another skill needs the state. It prints the same object and
**always exits 0**, so read the `status` and `can_proceed` fields, never the exit code.

## What the exit code means

`--check` returns the code for the state it found. Each one has exactly one remedy.

| Code | State | What to do |
| --- | --- | --- |
| 0 | `ready`, `ready_no_projects` | Nothing. Publishing works. |
| 2 | `needs_vercel_cli` | Install the CLI: `npm i -g vercel`. |
| 3 | `needs_login` | Sign in: `vercel login`. |
| 3 | `scope_denied` | The team answered for a different account. Check the team name. |
| 4 | `needs_config` | Record a team and a workspace file. See below. |
| 4 | `workspace_missing`, `workspace_unreadable`, `workspace_malformed` | Fix or re-create the workspace file. |
| 4 | `config_version_unsupported` | Move the config file aside and run setup again. |
| 5 | `vercel_probe_failed` | The CLI did not answer in a form this understands, so access could NOT be checked. This is not a refusal — do not go hunting for a permission you already hold. |

The checks run in a fixed order, and that order is the contract. A machine with no `vercel` CLI
**and** a bad team name is told about the CLI, because that is the one blocking the other.

## First run on a new machine

Do these in order. Stop at the first one that fails.

1. Sign in yourself, in your own terminal: `vercel login`. **This skill will never run that for
   you** — it is interactive and it changes the machine's global sign-in state.
2. List the teams you belong to: `vercel teams ls`.
3. Record the one you want:
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" --set-scope <team>`.
4. Create a workspace file:
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" --init-workspace`.
5. Register a project name:
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" --add-project <name>`.
6. Confirm: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" --check` must be silent.

Step 5 is optional. Without it the state is `ready_no_projects`, and you publish with
`--project workspace`.

## Three refusals that are deliberate, not bugs

**`--set-scope` proves the team before recording it.** It makes the same call the publisher
makes. If that call is denied or unclear, it writes nothing and says so. A recorded team that
does not work is worse than no team, because the failure then surfaces much later.

**`--add-project` refuses a workspace file this tool did not create.** Ownership is a stored
path, not a flag. The file may belong to something else that reads it, and writing a project
into a stranger's file is not this tool's business. Run `--init-workspace` to get one of your own.

**`--init-workspace` refuses to overwrite an existing file.** Use `--set-workspace <path>` to
adopt it instead. Adopting deliberately clears ownership, so adopting a file does not grant
permission to write into it later.

## What this never does

It stores no credential and it never runs `vercel login`. It only records which team and which
workspace file to use. Everything else it reports is derived fresh on each run, so nothing here
goes stale between calls.

The config file lives at `~/.config/design-doc-publish/config.json` unless `--config` names
another. Its path is printed in the full report.
