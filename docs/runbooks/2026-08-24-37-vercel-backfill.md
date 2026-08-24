# Runbook — backfilling the Vercel doc projects, and the window where both hosts serve

Issue #37. Every step has an undo, or says plainly that it has none. **Secrets appear by NAME
only.** If you find a value in this file, that is a defect — remove it and rotate the credential.

> **WARNING — read before running `activate`.** The control API has **no deactivate and no delete**.
> Activating a name that was previously absent cannot be undone to absent: the only repair is to
> publish different bytes over it. So `activate` is the one command in this child that you cannot
> take back, and every gate in front of it exists for that reason. Run `stage` first, read its
> report, and only then activate.

## What you are doing

Moving documents that Vercel serves today onto the self-hosted harness, one row at a time, without
deleting anything from Vercel. A row that moves is **live** on both hosts — that is the parallel-run
window, and it stays open, because teardown is a separate owner decision.

## Before you start

1. The harness must be reachable and healthy:
   ```bash
   docker ps --filter name=design-doc-publish --format '{{.Names}} {{.Status}}'
   docker inspect --format '{{.State.Health.Status}}' design-doc-publish-harness-1
   ```
   Undo: nothing — this is a read.
2. Two credentials in the environment, by name, never by value:
   `DOC_HARNESS_PUBLISH_TOKEN` (the bearer the control API requires) and a logged-in `vercel` CLI.
   Check the CLI without printing anything sensitive:
   ```bash
   vercel project list -F json --limit 1 >/dev/null && echo "vercel CLI: ok"
   ```
3. The control address. On this host the harness publishes no port of its own by design, so a local
   override supplies one; the script requires an **IP literal** whose peer is loopback and refuses a
   DNS name, a redirect or a proxy before it attaches the bearer.

## The order, and why it is this order

```bash
# 1. Inventory. Read-only. Walks the listing twice and refuses to call a partial walk complete.
python3 scripts/backfill_vercel.py --run-dir <run> inventory

# 2. Map. Read-only. Identifies each document by hashing its LIVE bytes against git history,
#    then records the publish target at the remote tip. Writes mapping.json.
python3 scripts/backfill_vercel.py --run-dir <run> map

# 3. REVIEW mapping.json by hand. This is the point of the whole design.
#    Correct a wrong guess, delete a row (it becomes a skipped_by_reviewer tombstone), add one.

# 4. Stage. Compares first and publishes NOTHING for a row whose bytes differ from Vercel.
python3 scripts/backfill_vercel.py --run-dir <run> stage --execute <mapping-digest>

# 5. Activate. The only command that touches a production name.
python3 scripts/backfill_vercel.py --run-dir <run> activate --execute <activation-digest>

# 6. Report. Asserts every row ended live or flagged, and fails if one did not.
python3 scripts/backfill_vercel.py --run-dir <run> report
```

Steps 1, 2 and 6 are read-only and safe to repeat. Steps 4 and 5 refuse to run without the digest
of the exact plan they are executing, so a stale review cannot be replayed against a file that has
since changed.

## Reading the outcomes

Every row ends `live` or `flagged`, and a flagged row carries exactly one reason.

| Reason | What it means | What to do |
| --- | --- | --- |
| `byte_mismatch` | The live Vercel page differs from the current committed page. **This is the normal case, not an error** — the document was edited after its last Vercel deploy. | Decide per document: redeploy Vercel to match, or accept that Vercel is stale and activate deliberately in a later run. |
| `vercel_changed` | The page moved between `map` and `stage`. | Re-run `map` for that row. |
| `mapping_not_found` | No committed blob anywhere matches the live bytes. | Map it by hand if you know the source, or leave it flagged. |
| `mapping_ambiguous` | Several commits or repositories hold identical bytes. | Choose one by hand in `mapping.json`. |
| `mapping_invalid` | A hand-edited row does not survive re-validation. | Fix the row; the report names the field. |
| `uncommitted_or_unreachable` | The target is not committed, or not pushed. | Commit and push it yourself. The script never does this for you. |
| `source_unavailable` | Vercel could not be read for that row after its retries. | Transport, not content. Re-run later. |
| `target_name_collision` | Two rows resolve to one harness name. | Rename or drop one in `mapping.json`. |
| `target_occupied` | The harness name is already active and is not this row's. | Deliberate refusal. Decide who owns the name. |
| `cas_conflict` | Another publisher moved the row mid-flight. | Re-run; the 409 body names the current deployment. |
| `stage_publish_failed` | The staging label already existed. | Use a new run id. |
| `final_verification_failed` | The served bytes did not match after a publish. | **The campaign halts here.** See below. |

`inventory_failed` is a campaign-level outcome, not a row: the listing was truncated or malformed
and the run stopped rather than reporting a partial walk as complete.

## When `final_verification_failed` fires after a production publish

The production name has already changed, so this is the one failure that stops everything rather
than flagging one row. In order:

1. Read the journal entry — it carries the deployment id that was returned.
2. Look at what is actually served: `curl -s -H 'Host: <name>.<zone>' <control-address>/ | sha256sum`
   against the target file's own sha256.
3. **Forward repair**, which is the only undo that exists: re-publish a previously journaled good
   manifest with the CURRENT `active_deployment_id` as `expected_active`. Measured behaviour: a
   matching id advances the deployment, and a stale id returns 409 without changing what is served.
4. If the name was absent before this run, there is no earlier good manifest and no "absent" to
   return to. Publish the correct target bytes and verify them. Say so in the report.
5. Only then resume `activate`.

## Leftover staging rows

`stage` publishes under `bf<run>-<name>`, and those are **real registry rows**: `index_snapshot`
selects every active row with no filter, so they appear on the derived index page. The control API
has no delete, so they persist until somebody replaces or removes them at the registry level. Every
staging label and deployment id is listed in the report. Treat cleaning them as a deliberate task,
not an afterthought.

## The parallel-run window

For every `live` row, both hosts now serve the same document:

- Vercel serves whatever was last deployed there. Nothing in this child changes or deletes it.
- The harness serves the committed bytes at the pinned commit, verified byte-for-byte at activation.

The window **opens at activation and does not close** on its own. The report records, per row, the
last instant byte identity was verified — which is the only honest statement available, because
either side can move afterwards.

**It is not a PUBLIC window yet.** No `*.3dstories.ca` hostname resolves and Cloudflare Access is
not in front of the harness, so today the harness half is reachable only from this host. Making it
public is #35's remaining work and needs an owner decision.

## Retiring a Vercel project, when somebody decides to

Out of scope for #37, and deliberately not automated. When the time comes, the order that keeps a
document reachable throughout:

1. Confirm the harness row is `live` and re-verify the bytes on the day.
2. Confirm the public harness hostname resolves and serves it (this needs #35 finished).
3. Update anything that links to the `.vercel.app` URL.
4. Only then remove the Vercel project. That is irreversible on Vercel's side too.

Undo for steps 1–3: nothing to undo, they are reads and link edits. Step 4 has no undo.
