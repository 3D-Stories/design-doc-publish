---
name: setup
description: Check what design-doc-publish needs before it can publish, and record the answers. Use when publishing fails with a configuration complaint, when the user says "set up design-doc-publish", "configure the doc publisher", "why can't I publish", "which Vercel team is it using", or when a doc render worked but the deploy did not. Use it on a machine that has never published before, and use it to diagnose one that used to work. Rendering needs no setup at all — reach for this only when a page has to reach Vercel.
---

# design-doc-publish setup

## Read this before running anything

**Never install software on the user's machine as part of this skill.** If the `vercel` CLI is
missing, say so, show the command, and let the user decide. Installing it changes their machine
**globally**, outside any project. Do not run it, do not run it "to save a step", and do not run
it because the state table names it. Ask, and wait for a yes.

The same rule covers `vercel login`. It is interactive and it changes the machine's global
sign-in state. Print it. Never run it.

**Tell the user what this will do before it does it.** Setup can write to exactly two places,
both under their home directory, and both only when they ask for it:

| Path | Written by | Holds |
| --- | --- | --- |
| `~/.config/design-doc-publish/config.json` | `--set-scope`, `--init-workspace`, `--set-workspace` | which Vercel team to use, and which workspace file |
| `~/.config/design-doc-publish/workspace.json` | `--init-workspace`, `--add-project` | the list of project names you may publish under |

Nothing else on the machine is touched. **No credential is stored in either file.** Signing in is
the Vercel CLI's business and stays there.

**Undo, at any time:** delete those two files. That returns the machine to never-configured.
Removing the `vercel` CLI, if it was installed, is `npm rm -g vercel` — separate, and the user's
call.

## Reading the state changes nothing

These two only read. Run them freely:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" --check
```

Silent with exit 0 means publishing will work. Anything else prints the single next action.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py"
```

The full picture — config file, CLI, sign-in, team, workspace file, project count, status, and
whether it can publish.

`--json` prints the same object and **always exits 0**, so read the `status` and `can_proceed`
fields, never the exit code.

## What the exit code means

`--check` returns the code for the state it found.

| Code | State | What it means |
| --- | --- | --- |
| 0 | `ready`, `ready_no_projects` | Publishing works. |
| 2 | `needs_vercel_cli` | The `vercel` CLI is absent. **Ask the user before installing it** — `npm i -g vercel` is a global change. |
| 3 | `needs_login` | Not signed in. Show `vercel login` and let the user run it themselves. |
| 3 | `scope_denied` | The team answered for a different account. Check the team name. |
| 4 | `needs_config` | No team or workspace file recorded yet. |
| 4 | `workspace_missing`, `workspace_unreadable`, `workspace_malformed` | Fix or re-create the workspace file. |
| 4 | `config_version_unsupported` | Move the config file aside and run setup again. |
| 5 | `vercel_probe_failed` | The CLI did not answer, or did not answer in a form this understands. Access could **not** be checked. This is not a refusal — do not go hunting for a permission you already hold. |

Every Vercel call is bounded by a timeout. A CLI that stops answering produces
`vercel_probe_failed`, never `needs_login` and never `scope_denied` — a hung call says nothing
about a credential.

The checks run in a fixed order, and that order is the contract. A machine with no `vercel` CLI
**and** a bad team name is told about the CLI, because that is the one blocking the other.

## First run on a new machine

Say what each step will change, then do it. Stop at the first step that fails.

1. Check the CLI is present. If it is not, tell the user it must be installed globally with
   `npm i -g vercel`, and **wait for them to agree or to run it**.
2. Ask the user to sign in themselves, in their own terminal: `vercel login`.
3. List the teams they belong to: `vercel teams ls`. This only reads.
4. Record the team. **This writes `config.json`:**
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" --set-scope <team>`
5. Create the workspace file. **This writes `workspace.json` and records it in `config.json`:**
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" --init-workspace`
6. Register a project name. **This writes `workspace.json`:**
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" --add-project <name>`
7. Confirm: `--check` must be silent.

Step 6 is optional. Without it the state is `ready_no_projects`, and you publish with
`--project workspace`.

## Three refusals that are deliberate, not bugs

**`--set-scope` proves the team before recording it.** It makes the same call the publisher
makes. If that call is denied or unclear, it writes nothing and says so. A recorded team that
does not work is worse than no team, because the failure surfaces much later.

**`--add-project` refuses a workspace file this tool did not create.** Ownership is a stored
path, not a flag. The file may belong to something else that reads it, and writing into a
stranger's file is not this tool's business. Run `--init-workspace` to get one of your own.

**`--init-workspace` refuses to overwrite an existing file.** Use `--set-workspace <path>` to
adopt it instead. Adopting deliberately clears ownership, so adopting a file does not grant
permission to write into it later.

## What this never does

It stores no credential, it never signs you in, and it installs nothing. It records which team
and which workspace file to use. Everything else it reports is derived fresh on each run, so
nothing here goes stale between calls.

`--config <path>` points at a different config file if the default location does not suit. The
path in use is printed in the full report.
