---
name: setup
description: Check what design-doc-publish needs before it can publish, and record the answers. Use when publishing fails with a configuration complaint, when the user says "set up design-doc-publish", "configure the doc publisher", "why can't I publish", or when a doc render worked but the publish did not. Use it on a machine that has never published before, and use it to diagnose one that used to work. Rendering needs no setup at all — reach for this only when a page has to reach the doc harness.
---

# design-doc-publish setup

## Read this before running anything

**Never install software or store a credential as part of this skill.** Setup reads the
environment and probes the harness read-only; it never writes a token anywhere. Where the
harness credentials live is the operator's business, and every refusal below names the variable
to set, not a value to paste.

**Tell the user what this will do before it does it.** Setup can write to exactly two places,
both under their home directory, and both only when they ask for it:

| Path | Written by | Holds |
| --- | --- | --- |
| `~/.config/design-doc-publish/config.json` | `--init-workspace`, `--set-workspace` | which workspace file to use |
| `~/.config/design-doc-publish/workspace.json` | `--init-workspace`, `--add-project` | the list of project names you may publish under |

Nothing else on the machine is touched. **No credential is stored in either file.** The harness
endpoint and its tokens are read from the environment on every run:

| Variable | Needed for | Meaning |
| --- | --- | --- |
| `DOC_HARNESS_CONTROL_URL` | publishing | where the harness control API answers. On the harness host that is a loopback or bridge address; anywhere else it is `https://docs-control.<zone>`, which puts Cloudflare Access in front of it |
| `DOC_HARNESS_PUBLISH_TOKEN` | publishing | the publish bearer |
| `DOC_HARNESS_PUBLIC_BASE` | optional | enables the public-edge verification half |
| `CF_ACCESS_CLIENT_ID` / `CF_ACCESS_CLIENT_SECRET` | with a public base, **or** whenever `DOC_HARNESS_CONTROL_URL` is the public control host | the Cloudflare Access service-token pair. Both or neither — half a pair is refused locally, by name, before anything is sent |

**Undo, at any time:** delete those two files. That returns the machine to never-configured.

## Reading the state changes nothing

These two only read. Run them freely:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" --check
```

Silent with exit 0 means publishing will work. Anything else prints the single next action.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py"
```

The full picture — config file, workspace file, project count, which harness variables are set,
whether the harness answers, status, and whether it can publish.

`--json` prints the same object and **always exits 0**, so read the `status` and `can_proceed`
fields, never the exit code.

The harness probe is READ-ONLY: it asks the control API to read back one deployment name, which
proves the URL and the bearer together and publishes nothing.

## What the exit code means

`--check` returns the code for the state it found.

| Code | State | What it means |
| --- | --- | --- |
| 0 | `ready`, `ready_no_projects` | Publishing works. |
| 2 | `needs_harness_env` | `DOC_HARNESS_CONTROL_URL` or `DOC_HARNESS_PUBLISH_TOKEN` is unset. |
| 2 | `edge_env_incomplete` | A public base is set but the Access pair is not. Set both halves, or unset the base to skip the edge check. |
| 3 | `harness_denied` | The harness refused the bearer. Check `DOC_HARNESS_PUBLISH_TOKEN`. |
| 4 | `needs_config` | No workspace file recorded yet. |
| 4 | `workspace_missing`, `workspace_unreadable`, `workspace_malformed` | Fix or re-create the workspace file. |
| 4 | `config_version_unsupported` | Move the config file aside and run setup again. |
| 5 | `harness_unreachable` | The harness did not answer, or did not answer in a form this understands. Access could **not** be checked. This is not a refusal — do not go hunting for a credential you already hold. |

The probe is bounded by a timeout. A harness that stops answering produces
`harness_unreachable`, never `harness_denied` — a hung call says nothing about a credential.

The checks run in a fixed order, and that order is the contract. A machine with no workspace
file **and** no harness variables is told about the workspace file, because the rows above it
in the state table win.

## First run on a new machine

Say what each step will change, then do it. Stop at the first step that fails.

1. Create the workspace file. **This writes `workspace.json` and records it in `config.json`:**
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" --init-workspace`
2. Register a project name. **This writes `workspace.json`:**
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/setup.py" --add-project <name>`
3. Export the harness variables in the shell that will publish — at minimum
   `DOC_HARNESS_CONTROL_URL` and `DOC_HARNESS_PUBLISH_TOKEN`. Setup never records them.
4. Confirm: `--check` must be silent.

Step 2 is optional. Without it the state is `ready_no_projects`, and you publish with
`--project workspace`.

## Two refusals that are deliberate, not bugs

**`--add-project` refuses a workspace file this tool did not create.** Ownership is a stored
path, not a flag. The file may belong to something else that reads it, and writing into a
stranger's file is not this tool's business. Run `--init-workspace` to get one of your own.

**`--init-workspace` refuses to overwrite an existing file.** Use `--set-workspace <path>` to
adopt it instead. Adopting deliberately clears ownership, so adopting a file does not grant
permission to write into it later.

## What this never does

It stores no credential, it never signs in to anything, and it installs nothing. It records
which workspace file to use. Everything else it reports is derived fresh on each run, so
nothing here goes stale between calls.

`--config <path>` points at a different config file if the default location does not suit. The
path in use is printed in the full report.
