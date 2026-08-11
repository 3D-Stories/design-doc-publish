#!/usr/bin/env python3
"""First-run setup: report what is missing, and record where your configuration lives (#9).

Design: `docs/planning/2026-08-10-9-first-run-setup-flow.md` (revision 3).

    python3 setup.py                    report every check, then what to run next
    python3 setup.py --check            silent when ready; one actionable line otherwise
    python3 setup.py --json             the same state as a JSON object
    python3 setup.py --init-workspace   create a workspace file this tool owns
    python3 setup.py --set-workspace P  adopt an existing one
    python3 setup.py --set-scope TEAM   record a Vercel team, after proving you can use it
    python3 setup.py --add-project NAME register a project name

Modelled on the `watch` plugin's own setup script, and the shape worth copying from it is
that `status` and `can_proceed` answer DIFFERENT questions. `status` describes the ideal
state. `can_proceed` is the operational gate. Someone with a configured team and an empty
project list can publish to the literal `workspace` bucket, so they get
`ready_no_projects` with `can_proceed: true` — a first run missing only an optional thing
is not reported as broken.

Three refusals here are deliberate and each was a review finding:

* **This never runs `vercel login`.** It is interactive and mutates machine-global
  authentication state, so an unattended run must never trigger it. Setup prints the exact
  command and re-checks afterwards.
* **This never parses `vercel teams ls`.** Its slug sits in a human table, and this package's
  rule (`index/build_index.py`) is that the JSON surface is read from stdout with no fallback
  to the table. Setup shows you your teams and you pass the one you want.
* **`--add-project` only writes to a workspace file this tool CREATED.** The resolved file
  may belong to another tool and be read by other sessions on this machine.

Module level stays parseable by an older interpreter on purpose: the version check below is
the first thing that runs, so a too-old Python gets a sentence instead of a SyntaxError.
"""
import sys

#: Declared, not measured. There is no enforced floor anywhere in this repository and no
#: interpreter below this one on the machine that wrote it, so this is the README's stated
#: requirement made checkable rather than a verified capability. The design says so plainly.
MINIMUM_PYTHON = (3, 12)


def check_python_version(version=None):
    """True when this interpreter is new enough, else False after printing one line.

    Takes the version as an argument so the guard itself is testable: no interpreter below
    the floor exists on the machine this was written on, so calling it with a faked version
    is the only honest way to prove it fires.
    """
    actual = tuple(version or sys.version_info[:3])
    if actual[:2] >= MINIMUM_PYTHON:
        return True
    want = ".".join(str(p) for p in MINIMUM_PYTHON)
    got = ".".join(str(p) for p in actual[:3])
    sys.stderr.write(
        "design-doc-publish needs Python %s or newer, and this is Python %s. "
        "Install a newer Python and run this again.\n" % (want, got))
    return False


if not check_python_version() and __name__ == "__main__":
    raise SystemExit(2)

import argparse  # noqa: E402
import contextlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import stat  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

#: POSIX only, and imported here rather than at the top so the failure is a SENTENCE.
#: `fcntl` does not exist on Windows, and an ImportError at module level would fire before
#: argument parsing — so the one command a stranger runs first would traceback instead of
#: telling them anything. The README states the platform; this makes the statement true at
#: runtime as well.
try:
    import fcntl  # noqa: E402
except ImportError:                                          # pragma: no cover - POSIX host
    fcntl = None


def _user_config():
    """`user_config.py`, resolved from THIS file's directory rather than `sys.path`.

    Same reasoning as the three existing load sites in this package: a foreign module
    earlier on the path is selected and executed before any check can reject it, and
    `render-doc` records that the hazard was observed live rather than imagined.
    """
    import importlib.util
    here = Path(__file__).resolve().parent
    path = here / "user_config.py"
    real = path.resolve()
    if not real.is_file() or not real.is_relative_to(here):
        raise RuntimeError("refusing to load %s: resolves to %s, outside %s"
                           % (path, real, here))
    spec = importlib.util.spec_from_file_location("_setup_user_config", real)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CONFIG = _user_config()

#: status -> (can_proceed, exit code). Order matters: `status` is the FIRST actionable
#: fault, so coexisting problems have one defined answer instead of two implementations
#: disagreeing.
_STATES = (
    ("config_version_unsupported", False, 4),
    ("needs_vercel_cli",           False, 2),
    ("needs_login",                False, 3),
    ("needs_config",               False, 4),
    ("vercel_probe_failed",        False, 5),
    ("scope_denied",               False, 3),
    ("workspace_missing",          False, 4),
    ("workspace_unreadable",       False, 4),
    ("workspace_malformed",        False, 4),
    ("ready_no_projects",          True,  0),
    ("ready",                      True,  0),
)
_BY_NAME = {name: (ok, code) for name, ok, code in _STATES}

_ADVICE = {
    "config_version_unsupported": "This build does not understand that config file. Move it aside and run setup again.",
    "needs_vercel_cli": "The `vercel` CLI is not installed. Install it with `npm i -g vercel`, then run this again.",
    "needs_login": "You are not signed in to Vercel. Run `vercel login`, then run this again.",
    "needs_config": "Nothing is configured yet. Run this with --set-scope <team>, and --init-workspace.",
    "vercel_probe_failed": "The Vercel CLI did not answer in a way this understands, so your access could not be checked.",
    "scope_denied": "That Vercel team answered for a different account. Check the team name.",
    "workspace_missing": "The configured workspace file is not there any more. Run --init-workspace or --set-workspace.",
    "workspace_unreadable": "The configured workspace file cannot be read. Check its permissions.",
    "workspace_malformed": "The configured workspace file is not valid JSON. Fix it, or run --init-workspace elsewhere.",
    "ready_no_projects": "Ready. No project names are registered, so publish with --project workspace, or add one with --add-project.",
    "ready": "Ready.",
}


def exit_code(state):
    """The `--check` exit code for a state object."""
    return _BY_NAME[state["status"]][1]


@contextlib.contextmanager
def _locked(target):
    """Hold an exclusive lock beside `target` for the whole read-modify-write.

    Two things this gets right that the obvious version does not.

    **The lock file is opened without following a symlink.** `open(path, "w")` follows one and
    TRUNCATES the destination — before any lock is taken. A pre-created `.lock` symlink in a
    directory another principal can write would therefore let this truncate any file the
    invoking user can write. `O_NOFOLLOW` refuses the symlink, and an `fstat` check refuses
    anything that is not a regular file.

    **It covers the whole operation, not just the write.** Atomic replacement makes each write
    whole; it does not make read-modify-replace atomic.
    """
    lock_path = Path(str(target) + ".lock")
    if fcntl is None:
        raise CONFIG.ConfigError(
            "file locking is not available on this platform, and this tool will not perform "
            "an unserialized read-modify-write on your configuration. design-doc-publish "
            "supports POSIX systems.")
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError as e:
        raise CONFIG.ConfigError(
            "could not take a lock at %s (%s). If that path is a symlink, remove it — this "
            "refuses to write through one." % (lock_path, e.__class__.__name__)) from e
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise CONFIG.ConfigError(
                "%s is not a regular file, so it cannot be used as a lock." % lock_path)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _vercel_installed():
    return shutil.which("vercel") is not None


#: Every Vercel call in this module is a STATUS probe, so it should answer quickly or not
#: at all. Without a bound, a non-responsive CLI stalls `--check` forever, and the one
#: command meant to diagnose a machine becomes the thing that hangs on it.
_VERCEL_TIMEOUT = 60


def _run(args):
    """The single place this module shells out, so the timeout belongs here.

    `TimeoutExpired` is left to PROPAGATE. Both callers catch it and map it to "could not
    check" — never to "not signed in" and never to "refused". A hung call says nothing
    about a credential, and reporting it as one sends someone to fix what is not broken.
    """
    return subprocess.run(["vercel"] + list(args), capture_output=True, text=True,
                          check=False, timeout=_VERCEL_TIMEOUT)


def _authenticated():
    """`vercel whoami`, read from STDOUT — the banner goes to stderr."""
    try:
        proc = _run(["whoami"])
    except subprocess.TimeoutExpired:
        # None, not False. False means "signed out", which is a diagnosis this call did
        # not earn — the CLI never answered.
        return None, None
    except OSError:
        return False, None
    if proc.returncode != 0:
        return False, None
    return True, (proc.stdout or "").strip() or None


def probe_scope(scope):
    """(outcome, detail) for a Vercel team, using the SAME call the publisher makes.

    Outcome is one of `ok`, `denied`, `failed`. The split is the point: a call that could
    not run, could not be parsed, or named no tenant is a FAILED probe, not a denial.
    Telling someone their access was refused when the network blipped sends them to fix a
    permission they already hold.
    """
    try:
        proc = _run(["project", "ls", "--format", "json", "--limit", "1",
                     "--scope", scope, "--no-color"])
    except subprocess.TimeoutExpired:
        return "failed", ("the vercel CLI did not answer within %d seconds"
                          % _VERCEL_TIMEOUT)
    except OSError as e:
        return "failed", "the vercel CLI could not be run (%s)" % e.__class__.__name__
    if proc.returncode != 0:
        first = ((proc.stderr or proc.stdout or "").strip().splitlines() or [""])[0]
        lowered = first.lower()
        if "not authorized" in lowered or "not a member" in lowered or "forbidden" in lowered:
            return "denied", first[:200]
        return "failed", first[:200] or "exit %d with no message" % proc.returncode
    try:
        payload = json.loads(proc.stdout or "")
    except ValueError:
        return "failed", "`project ls --format json` did not return JSON"
    if not isinstance(payload, dict) or "contextName" not in payload:
        return "failed", "the listing named no tenant, so access cannot be judged"
    # The publisher's own parser requires these too, so accepting a thinner payload here
    # would report ready and then fail at stage 4 on the same CLI surface. An EMPTY projects
    # list stays valid: an account with nothing in it yet is the bootstrap case.
    if not isinstance(payload.get("projects"), list):
        return "failed", "the listing carried no `projects` array"
    pagination = payload.get("pagination")
    if not isinstance(pagination, dict) or "next" not in pagination:
        return "failed", ("the listing carried no `pagination.next`, so it cannot be "
                          "judged complete")
    if payload["contextName"] != scope:
        return "denied", "the listing answered for %r" % payload["contextName"]
    return "ok", None


def _read_workspace(path):
    """(status_or_None, project_count_or_None) for a resolved workspace path."""
    if not path.exists():
        return "workspace_missing", None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return "workspace_unreadable", None
    try:
        data = json.loads(raw)
    except ValueError:
        return "workspace_malformed", None
    # `projects` must be PRESENT. Treating `{}` as an empty list reported can_proceed while
    # the publisher refused every project name — the two must not disagree.
    if (not isinstance(data, dict) or "projects" not in data
            or not isinstance(data["projects"], list)):
        return "workspace_malformed", None
    return None, len(data["projects"])


def status(config_path=None, **_ignored):
    """The whole state of this machine, as one object.

    Every field here is derived; nothing is remembered between calls. Captured CLI output
    is deliberately absent — it can carry account detail, and a status object is something
    people paste.
    """
    if config_path is None:
        config_path = CONFIG.config_file()
    config_path = Path(config_path)

    state = {
        "config_file": str(config_path),
        "first_run": not config_path.exists(),
        "vercel_cli": _vercel_installed(),
        "authenticated": False,
        "scope_list_accessible": None,
        "vercel_scope": None,
        "workspace_file": None,
        "project_count": None,
        "detail": None,
    }

    # The rows are checked in the order `_STATES` declares them. That order IS the contract —
    # it is what gives coexisting faults one defined answer — so resolution cannot run ahead
    # of it. An earlier version resolved configuration first, and a machine with no `vercel`
    # AND an invalid configured team was told about the team (row 4) instead of the missing
    # CLI (row 2).
    try:
        CONFIG.load(config_path)
    except CONFIG.ConfigError as e:
        return _finish(state, "config_version_unsupported", str(e))

    if not state["vercel_cli"]:
        return _finish(state, "needs_vercel_cli", None)

    authed, who = _authenticated()
    if authed is None:
        return _finish(state, "vercel_probe_failed",
                       "the vercel CLI did not answer within %d seconds"
                       % _VERCEL_TIMEOUT)
    state["authenticated"] = authed
    if not authed:
        return _finish(state, "needs_login", None)

    try:
        scope = CONFIG.vercel_scope(config_path=config_path)
        workspace = CONFIG.workspace_file(config_path=config_path)
    except CONFIG.ConfigError as e:
        return _finish(state, "needs_config", str(e))
    state["vercel_scope"] = scope
    state["workspace_file"] = str(workspace) if workspace else None

    if scope is None or workspace is None:
        return _finish(state, "needs_config", None)

    outcome, detail = probe_scope(scope)
    state["scope_list_accessible"] = outcome == "ok"
    if outcome == "failed":
        return _finish(state, "vercel_probe_failed", detail)
    if outcome == "denied":
        return _finish(state, "scope_denied", detail)

    problem, count = _read_workspace(workspace)
    if problem:
        return _finish(state, problem, None)
    state["project_count"] = count
    return _finish(state, "ready" if count else "ready_no_projects", None)


def _finish(state, name, detail):
    state["status"] = name
    state["can_proceed"] = _BY_NAME[name][0]
    state["detail"] = detail
    return state


# ------------------------------------------------------------------ recording your choices

def _store(config_path, **updates):
    """Merge `updates` into the config, under a lock, atomically.

    Two separate hazards, and the second was missed the first time round.

    The STRICT loader: a setter must never merge into a config it could not read and then
    replace the file, because that destroys the only copy of whatever was in it.

    The LOCK: atomic replacement makes each write whole, but read-modify-replace is not
    atomic. `--set-scope` and `--init-workspace` are two commands the documentation tells
    people to run one after another, and run concurrently they could both read the old object
    and the later writer would erase the other's setting.

    A key set to `None` is REMOVED rather than stored, which is how ownership is cleared.
    """
    config_path = Path(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with _locked(config_path):
        data = CONFIG.load_for_update(config_path)
        data["version"] = CONFIG.CONFIG_VERSION
        for key, value in updates.items():
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
        CONFIG.write_config(data, config_path)
    return data


def cmd_init_workspace(config_path, raw):
    target = (Path(raw).expanduser().resolve() if raw
              else config_path.parent / "workspace.json")
    if target.exists():
        sys.stderr.write(
            "%s already exists, and overwriting it would discard whatever is in it. "
            "Use --set-workspace %s to adopt it instead.\n" % (target, target))
        return 2
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_config({"version": 1, "projects": []}, target)
    except CONFIG.ConfigError as e:
        sys.stderr.write("could not create %s: %s\n" % (target, e))
        return 2
    try:
        _store(config_path, workspace_file=str(target), owned_workspace_file=str(target))
    except CONFIG.ConfigError:
        # Roll back the file we just made. A created-but-unrecorded workspace is one the
        # user did not ask for and this tool will not use, so leaving it is litter.
        try:
            target.unlink()
        except OSError:
            pass
        raise
    print("Created %s and recorded it. Add a project with --add-project <name>." % target)
    return 0


def cmd_set_workspace(config_path, raw):
    target = Path(raw).expanduser()
    if not target.is_absolute():
        target = Path.cwd() / target
    target = target.resolve()
    if not target.is_file():
        sys.stderr.write(
            "%s is not a readable file. Use --init-workspace to create one instead.\n"
            % target)
        return 2
    # Adopting is not owning, and LEAVING the old record is not the same as clearing it.
    # A previously owned path stays authorized: init A, adopt B, then adopt A again after A
    # has been deleted and replaced by someone else's file, and --add-project would write to
    # it. Ownership is cleared on every adoption.
    _store(config_path, workspace_file=str(target), owned_workspace_file=None)
    print("Recorded %s as your workspace file." % target)
    return 0


def cmd_set_scope(config_path, raw):
    try:
        scope = CONFIG.validate_scope(raw)
    except CONFIG.ConfigError as e:
        sys.stderr.write("%s\n" % e)
        return 2
    if not _vercel_installed():
        sys.stderr.write("the `vercel` CLI is not installed, so %r cannot be checked. "
                         "Install it with `npm i -g vercel`.\n" % scope)
        return 2
    outcome, detail = probe_scope(scope)
    if outcome != "ok":
        sys.stderr.write(
            "refusing to record %r: %s. Nothing was written.\n"
            % (scope, detail or "the team could not be reached"))
        return 2 if outcome == "failed" else 3
    _store(config_path, vercel_scope=scope)
    print("Recorded %s, and confirmed you can list it." % scope)
    return 0


def cmd_add_project(config_path, name):
    try:
        name = CONFIG.validate_scope(name)
    except CONFIG.ConfigError as e:
        sys.stderr.write("%s\n" % e)
        return 2

    data = CONFIG.load(config_path)
    owned = data.get("owned_workspace_file")
    resolved = CONFIG.workspace_file(config_path=config_path)
    if resolved is None:
        sys.stderr.write("no workspace file is configured. Run --init-workspace first.\n")
        return 2
    # Ownership is a stored PATH, not a boolean. A boolean would go stale the moment a flag
    # or environment override selected a different file: it would still read true while
    # resolution pointed somewhere else, and this would write to a stranger's file.
    if not owned or str(resolved) != str(owned):
        sys.stderr.write(
            "refusing to write to %s — this tool did not create it, and it may belong to "
            "something else that reads it. Run --init-workspace to make one of your own.\n"
            % resolved)
        return 2

    # Atomic replacement keeps each write whole, but it does NOT make read-modify-write
    # atomic: two runs can both read, both add, and the later replace erases the earlier
    # addition. That is data loss, so the whole operation is serialized.
    try:
        with _locked(resolved):
            try:
                body = json.loads(resolved.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                sys.stderr.write("could not read %s: %s\n" % (resolved, e))
                return 2
            if (not isinstance(body, dict) or "projects" not in body
                    or not isinstance(body["projects"], list)):
                sys.stderr.write("%s is not shaped like a workspace file.\n" % resolved)
                return 2
            projects = body["projects"]
            for entry in projects:
                if isinstance(entry, dict) and entry.get("name") == name:
                    if set(entry) - {"name"}:
                        sys.stderr.write(
                            "%s already lists %r with other fields; refusing to change it.\n"
                            % (resolved, name))
                        return 2
                    print("%s already lists %s." % (resolved, name))
                    return 0
            projects.append({"name": name})
            CONFIG.write_config(body, resolved)
    except CONFIG.ConfigError as e:
        sys.stderr.write("%s\n" % e)
        return 2
    print("Added %s to %s." % (name, resolved))
    return 0


# ------------------------------------------------------------------------------ reporting

def _report(state):
    print("design-doc-publish setup")
    print("  config file      %s%s" % (state["config_file"],
                                       "  (not created yet)" if state["first_run"] else ""))
    print("  vercel CLI       %s" % ("installed" if state["vercel_cli"] else "NOT installed"))
    print("  signed in        %s" % ("yes" if state["authenticated"] else "no"))
    print("  vercel team      %s" % (state["vercel_scope"] or "not set"))
    print("  workspace file   %s" % (state["workspace_file"] or "not set"))
    print("  projects         %s" % ("not readable" if state["project_count"] is None
                                     else state["project_count"]))
    print("")
    print("  status           %s" % state["status"])
    print("  can publish      %s" % ("yes" if state["can_proceed"] else "no"))
    if state["detail"]:
        print("  detail           %s" % state["detail"])
    print("")
    print("  " + _ADVICE[state["status"]])

    if not state["authenticated"] and state["vercel_cli"]:
        # Printed, never run: it is interactive and changes this machine's global sign-in
        # state, which nothing running unattended should ever do on someone's behalf.
        print("")
        print("  Run this yourself, in your own terminal:")
        print("      vercel login")
    if state["authenticated"] and not state["vercel_scope"]:
        print("")
        print("  Your teams are listed by:")
        print("      vercel teams ls")
        print("  Then record the one you want:")
        print("      python3 %s --set-scope <team>" % Path(__file__).resolve())


def build_parser():
    ap = argparse.ArgumentParser(
        description="Check what design-doc-publish needs, and record where your "
                    "configuration lives.")
    ap.add_argument("--check", action="store_true",
                    help="silent when ready; one actionable line and a non-zero exit "
                         "otherwise")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="print the same state as a JSON object, and always exit 0")
    ap.add_argument("--config", default=None,
                    help="use this config file instead of the default location")
    ap.add_argument("--init-workspace", nargs="?", const="", default=None,
                    metavar="PATH", help="create a workspace file this tool owns")
    ap.add_argument("--set-workspace", default=None, metavar="PATH",
                    help="adopt an existing workspace file")
    ap.add_argument("--set-scope", default=None, metavar="TEAM",
                    help="record a Vercel team, after proving you can list it")
    ap.add_argument("--add-project", default=None, metavar="NAME",
                    help="register a project name in the workspace file this tool owns")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        config_path = CONFIG.config_file(cli_value=args.config)
    except CONFIG.ConfigError as e:
        sys.stderr.write("%s\n" % e)
        return 2

    # Every setter reads the existing config before writing, so every setter can meet a
    # config this build cannot read. Unguarded, that surfaced as a raw traceback from the one
    # command meant to help someone out of exactly that state. A legible sentence is the
    # whole contract here, and it has no carve-out for the setters.
    try:
        if args.init_workspace is not None:
            return cmd_init_workspace(config_path, args.init_workspace)
        if args.set_workspace is not None:
            return cmd_set_workspace(config_path, args.set_workspace)
        if args.set_scope is not None:
            return cmd_set_scope(config_path, args.set_scope)
        if args.add_project is not None:
            return cmd_add_project(config_path, args.add_project)
    except CONFIG.ConfigError as e:
        sys.stderr.write("%s\n" % e)
        return 2

    state = status(config_path=config_path)

    if args.as_json:
        # `detail` can quote the CLI, so it is dropped here rather than shipped in something
        # people paste. The status itself carries the meaning.
        public = {k: v for k, v in state.items() if k != "detail"}
        json.dump(public, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    if args.check:
        if state["can_proceed"]:
            return 0
        sys.stderr.write("design-doc-publish: %s\n" % _ADVICE[state["status"]])
        return exit_code(state)

    _report(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
