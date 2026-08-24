#!/usr/bin/env python3
"""Backfill the existing Vercel-hosted doc pages into the doc-harness registry (#37).

Five subcommands over one append-only run directory:

    inventory   walk the Vercel listing, bounded, until two walks agree or the bound is hit
    map         identify each document by hashing its LIVE bytes against git history, then
                record the publish TARGET at the remote tip
    stage       compare the target bytes to Vercel, then publish under a staging label and
                verify what the harness serves
    activate    re-validate, then CAS-publish the production name and verify it
    report      assert every row ended live or flagged, then write the report

Design: `docs/planning/2026-08-24-37-vercel-backfill.md`.

**Provenance and target are DIFFERENT questions, and conflating them defeats the feature.** The
hash match against history answers "which document is this page" — it necessarily matches the live
Vercel bytes, so comparing that same blob back against Vercel is a tautology and would migrate the
stale version of every drifted document. The publish TARGET is the document's current committed
page at the remote tip, and the compare is target-versus-Vercel, which is a real question.

**`--execute` gates REGISTRY mutations, and only those.** Every command writes local artifacts
under its own run directory — that is what a resumable campaign is made of, and `inventory` could
not otherwise start, since it is the command that produces the first digest. No `POST` reaches the
control API without an explicit `--execute` carrying the digest of the exact plan being executed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time

# The publication purposes of the `{project}-{purpose}-{ref}` convention, which is what the old
# Vercel project names carry. Copied deliberately rather than imported: `publish_doc.py` is out of
# scope for this child, and a drift here is caught by a test that compares the two lists.
PURPOSES = ("design", "plan", "uat", "audit", "report", "runbook", "analysis", "spec",
            "tokens", "map", "deck")

# Row outcomes. Exactly two, because the acceptance criterion says "activated or flagged" — a
# third bucket for drift would satisfy neither.
LIVE = "live"
FLAGGED = "flagged"

# Every flag reason. A closed vocabulary, so a report cannot invent a state, and a transport
# failure can never be recorded as a content verdict.
REASONS = (
    "mapping_not_found",
    "mapping_ambiguous",
    "mapping_invalid",
    "uncommitted_or_unreachable",
    "source_unavailable",
    "vercel_changed",
    "byte_mismatch",
    "target_name_collision",
    "stage_publish_failed",
    "target_occupied",
    "cas_conflict",
    "final_verification_failed",
    "skipped_by_reviewer",
)

# Campaign-level, NOT a row outcome: a truncated or invalid listing is not a property of any one
# project, and reporting a partial walk as a complete campaign would be a lie.
INVENTORY_FAILED = "inventory_failed"


class Refused(Exception):
    """A gate refused. Never a bug — the refusal IS the feature."""


class CampaignFailed(Exception):
    """The whole campaign stops. NOT a row outcome.

    A truncated or invalid listing is not a property of any one project, so recording it against a
    row — or worse, continuing with a partial walk — would report an incomplete campaign as a
    complete one.
    """

    def __init__(self, outcome: str, detail: str = ""):
        super().__init__(f"{outcome}: {detail}" if detail else outcome)
        self.outcome = outcome
        self.detail = detail


class RowError(Exception):
    """One row failed. Carries its reason so the journal records a vocabulary term, not prose."""

    def __init__(self, reason: str, detail: str = ""):
        if reason not in REASONS:
            raise AssertionError(f"{reason!r} is not one of the closed flag reasons")
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def digest(obj) -> str:
    """sha256 over canonical JSON: key order cannot change it, value order can.

    The plan digests are what stop a stale human review being replayed against a file that has
    since changed, so this must be stable for the same content and different for different
    content — including a reordered list, which IS different content.
    """
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def require_execute(*, execute: str | None, expected: str, what: str) -> None:
    """Refuse unless the caller passed `--execute <the exact digest>`.

    Two separate refusals on purpose. A missing flag means "you did not ask to write"; a wrong
    digest means "what you reviewed is not what is on disk", and telling those apart is the
    difference between a typo and a stale plan.
    """
    if not execute:
        raise Refused(
            f"refusing to write: {what} would be executed, so pass --execute {expected} "
            f"(read-only is the default, and no registry is touched without it)")
    if execute != expected:
        raise Refused(
            f"refusing to write: --execute {execute} does not match the current {what} digest "
            f"{expected}. Something changed since it was reviewed — re-read it, do not re-run.")


class RunDir:
    """One run's directory: an append-only journal, plus whatever the phases persist.

    An existing directory is REUSED, never clobbered. A resumable campaign whose ledger a re-run
    silently truncated would be worse than one that never resumed.
    """

    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.journal_path = self.path / "journal.jsonl"

    def journal(self, row: str, record: dict) -> None:
        """Append one entry. Never rewrites, never seeks — evidence only accumulates."""
        entry = {"row": row, "at": int(time.time()), "record": record}
        with open(self.journal_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")

    def journal_entries(self) -> list:
        if not self.journal_path.exists():
            return []
        out = []
        for line in self.journal_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def write_json(self, name: str, obj) -> pathlib.Path:
        target = self.path / name
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                       encoding="utf-8")
        os.replace(tmp, target)
        return target

    def read_json(self, name: str):
        target = self.path / name
        if not target.exists():
            raise Refused(f"{target} does not exist — run the earlier phase first")
        return json.loads(target.read_text(encoding="utf-8"))


def _default_cli(argv):
    """The real subprocess seam. Returns (returncode, stdout, stderr) and never raises for a
    non-zero exit — the caller decides what a failure means."""
    proc = subprocess.run(argv, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def _one_walk(runner) -> list:
    """One complete walk of the Vercel listing, following `pagination.next` to exhaustion.

    Every failure here is `inventory_failed`, never an empty list. A partial walk that read as
    "there are no projects" would activate nothing and report success, which is the worst possible
    way for this to break.
    """
    rows, nxt = [], None
    while True:
        argv = ["vercel", "project", "list", "-F", "json", "--limit", "100"]
        if nxt:
            argv += ["--next", str(nxt)]
        code, out, err = runner(argv)
        if code != 0:
            raise CampaignFailed(INVENTORY_FAILED,
                                 f"`vercel project list` exited {code}: {(err or '').strip()}")
        try:
            payload = json.loads(out)
        except (ValueError, TypeError) as exc:
            raise CampaignFailed(INVENTORY_FAILED,
                                 f"the listing was not JSON: {exc}") from None
        projects = payload.get("projects") if isinstance(payload, dict) else None
        if not isinstance(projects, list):
            raise CampaignFailed(INVENTORY_FAILED,
                                 "the listing carries no `projects` array, so it cannot be read "
                                 "as an inventory")
        for item in projects:
            rows.append({"id": item.get("id"), "name": item.get("name"),
                         "latestProductionUrl": item.get("latestProductionUrl"),
                         "updatedAt": item.get("updatedAt")})
        nxt = (payload.get("pagination") or {}).get("next")
        if not nxt:
            break
    # Sorted, because the listing's own order may vary between walks and convergence has to mean
    # "the same set", not "the same order the server happened to answer in".
    return sorted(rows, key=lambda r: (str(r.get("name")), str(r.get("id"))))


def inventory(run: RunDir, *, runner=None, max_walks: int = 3) -> dict:
    """Walk the listing until two consecutive walks agree, or the bound is hit.

    A paginated walk cannot establish an atomic set at an instant, so a converged snapshot is the
    strongest claim available and a non-converged one is recorded as a CUTOFF bounded by two
    instants — never as a moment. Sessions in this workspace publish continuously, so this is the
    normal case, not a corner.
    """
    runner = runner or _default_cli
    started = int(time.time())
    previous, walks = None, 0
    while walks < max(1, int(max_walks)):
        rows = _one_walk(runner)
        walks += 1
        if previous is not None and digest(previous) == digest(rows):
            snapshot = {"rows": rows, "walks": walks, "converged": True, "cutoff": False,
                        "started_at": started, "completed_at": int(time.time())}
            snapshot["digest"] = digest(rows)
            run.write_json("inventory.json", snapshot)
            run.journal("_campaign", {"phase": "inventory", "converged": True,
                                      "rows": len(rows), "walks": walks})
            return snapshot
        previous = rows
    snapshot = {"rows": previous or [], "walks": walks, "converged": False, "cutoff": True,
                "started_at": started, "completed_at": int(time.time())}
    snapshot["digest"] = digest(snapshot["rows"])
    run.write_json("inventory.json", snapshot)
    run.journal("_campaign", {"phase": "inventory", "converged": False, "cutoff": True,
                              "rows": len(snapshot["rows"]), "walks": walks})
    return snapshot


def _cmd_inventory(args, run) -> int:
    snapshot = inventory(run, max_walks=args.max_walks)
    kind = "converged" if snapshot["converged"] else "CUTOFF (walks never agreed)"
    print(f"inventory: {len(snapshot['rows'])} rows, {snapshot['walks']} walk(s), {kind}")
    print(f"inventory digest: {snapshot['digest']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backfill_vercel.py",
        description="Backfill Vercel-hosted doc pages into the harness registry (#37). "
                    "Read-only unless --execute carries the digest of the plan.")
    parser.add_argument("--run-dir", required=True, help="the run directory (reused if present)")
    sub = parser.add_subparsers(dest="command", required=True)

    inv = sub.add_parser("inventory", help="walk the Vercel listing, bounded")
    inv.add_argument("--max-walks", type=int, default=3,
                     help="how many walks may be attempted before a cutoff is recorded")

    mp = sub.add_parser("map", help="identify each document, and record its publish target")
    mp.add_argument("--history-cap", type=int, default=2000,
                    help="commits examined per candidate path; hitting it is RECORDED on the row")
    mp.add_argument("--workspace-file", default=None, help="the rawgentic workspace file")

    st = sub.add_parser("stage", help="compare, then publish under a staging label and verify")
    st.add_argument("--execute", default=None, help="the mapping digest, required to write")
    st.add_argument("--control-base", default=None, help="http://<ip>:<port> of the control API")
    st.add_argument("--zone", default="3dstories.ca")
    st.add_argument("--limit", type=int, default=None, help="bound one pass")

    act = sub.add_parser("activate", help="CAS-publish the production name and verify it")
    act.add_argument("--execute", default=None, help="the activation-plan digest")
    act.add_argument("--control-base", default=None)
    act.add_argument("--zone", default="3dstories.ca")
    act.add_argument("--limit", type=int, default=None)

    sub.add_parser("report", help="assert every row ended live or flagged, and write the report")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    run = RunDir(args.run_dir)
    try:
        handler = COMMANDS[args.command]
    except KeyError:  # pragma: no cover - argparse already constrains this
        raise AssertionError(f"no handler for {args.command!r}")
    try:
        return handler(args, run)
    except Refused as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return 2


def _not_yet(args, run):  # pragma: no cover - replaced per task
    raise Refused(f"{args.command} is not implemented yet")


COMMANDS = {
    "inventory": _cmd_inventory,
    "map": _not_yet,
    "stage": _not_yet,
    "activate": _not_yet,
    "report": _not_yet,
}


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
