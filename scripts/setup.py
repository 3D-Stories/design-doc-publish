#!/usr/bin/env python3
"""First-run setup: report what is missing, and record where your configuration lives (#9).

Design: `docs/planning/2026-08-10-9-first-run-setup-flow.md` (revision 3).

    python3 setup.py                    report every check, then what to run next
    python3 setup.py --check            silent when ready; one actionable line otherwise
    python3 setup.py --json             the same state as a JSON object
    python3 setup.py --init-workspace   create a workspace file this tool owns
    python3 setup.py --set-workspace P  adopt an existing one
    python3 setup.py --add-project NAME register a project name

Modelled on the `watch` plugin's own setup script, and the shape worth copying from it is
that `status` and `can_proceed` answer DIFFERENT questions. `status` describes the ideal
state. `can_proceed` is the operational gate. Someone with a reachable harness and an empty
project list can publish to the literal `workspace` bucket, so they get
`ready_no_projects` with `can_proceed: true` — a first run missing only an optional thing
is not reported as broken.

What publishing needs, and therefore what this checks: a workspace file (stage 2 validates
``--project`` against it), ``DOC_HARNESS_CONTROL_URL`` and ``DOC_HARNESS_PUBLISH_TOKEN``
(stage 5 publishes through the control API), and the
``CF_ACCESS_CLIENT_ID``/``CF_ACCESS_CLIENT_SECRET`` pair whenever something crosses the
Cloudflare edge — either because ``DOC_HARNESS_PUBLIC_BASE`` requests the edge verify half, or
because ``DOC_HARNESS_CONTROL_URL`` names the public control host, which is how a machine that
is not the harness host publishes at all (#54). Rendering alone needs none of it.

Two refusals here are deliberate:

* **The harness probe is READ-ONLY.** It asks the control API to read back one deployment
  name, which proves the URL and the bearer together and mutates nothing.
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
import stat  # noqa: E402
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
    ("needs_config",               False, 4),
    ("workspace_missing",          False, 4),
    ("workspace_unreadable",       False, 4),
    ("workspace_malformed",        False, 4),
    ("needs_harness_env",          False, 2),
    ("edge_env_incomplete",        False, 2),
    ("harness_unreachable",        False, 5),
    ("harness_denied",             False, 3),
    ("ready_no_projects",          True,  0),
    ("ready",                      True,  0),
)
_BY_NAME = {name: (ok, code) for name, ok, code in _STATES}

_ADVICE = {
    "config_version_unsupported": "This build does not understand that config file. Move it aside and run setup again.",
    "needs_config": "No workspace file is configured yet. Run this with --init-workspace, or --set-workspace <path>.",
    "workspace_missing": "The configured workspace file is not there any more. Run --init-workspace or --set-workspace.",
    "workspace_unreadable": "The configured workspace file cannot be read. Check its permissions.",
    "workspace_malformed": "The configured workspace file is not valid JSON. Fix it, or run --init-workspace elsewhere.",
    "needs_harness_env": "Publishing needs DOC_HARNESS_CONTROL_URL and DOC_HARNESS_PUBLISH_TOKEN in the environment. Rendering alone needs neither.",
    "edge_env_incomplete": "Something here goes through Cloudflare Access, which needs CF_ACCESS_CLIENT_ID and CF_ACCESS_CLIENT_SECRET. Either DOC_HARNESS_PUBLIC_BASE is set (the edge check — unset it to skip that half), or DOC_HARNESS_CONTROL_URL names the public control host (publishing from anywhere but the harness host — there is no skipping that one, set the pair).",
    "harness_unreachable": "The harness at DOC_HARNESS_CONTROL_URL did not answer. Check the URL, and that the harness is running.",
    "harness_denied": "The harness refused the publish bearer. Check DOC_HARNESS_PUBLISH_TOKEN.",
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


#: Every call in this module is a STATUS probe, so it should answer quickly or not at all.
#: Without a bound, a non-responsive harness stalls `--check` forever, and the one command
#: meant to diagnose a machine becomes the thing that hangs on it.
#: Pinned in committed source, never read from the environment — see `_is_edge_control`.
_CONTROL_HOST = "docs-control.3dstories.ca"

_PROBE_TIMEOUT = 10

#: A valid deployment name that no real document is expected to hold. The read-back route
#: answers 200 with a null id for an ABSENT name (contract C9), so probing it proves the URL
#: and the bearer together while reading nothing anybody published.
_PROBE_NAME = "setup-readiness-probe"


def _is_edge_control(control_url):
    """True when the control URL is the public control host over TLS, so Cloudflare Access
    stands in front of it (#54).

    The host is pinned in source here for the same reason it is pinned below: validating a
    destination against a value read from the same environment that supplied the destination
    is not validation. This module deliberately does not import `publish_doc` — it stays
    parseable and runnable on its own — so the one string is duplicated rather than shared,
    and `publish_doc._control_is_edge` is its counterpart.
    """
    import urllib.parse
    parsed = urllib.parse.urlsplit((control_url or "").strip())
    return parsed.scheme == "https" and (parsed.hostname or "").lower() == _CONTROL_HOST


def probe_harness(control_url, token, env=None):
    """(outcome, detail) for the control API, using the read-back the publisher parses.

    Outcome is one of `ok`, `denied`, `failed`. The split is the point: a call that could
    not connect, timed out, or answered garbage is a FAILED probe, not a denial. Telling
    someone their token was refused when the network blipped sends them to rotate a
    credential they already hold. READ-ONLY by construction: GET, never POST.

    #54: this is a CONTROL CALL, so it obeys the same two rules the publisher's control calls
    obey. It carries the Cloudflare Access service-token pair when the destination is behind
    Access, and it never follows a redirect.
    """
    import os
    import urllib.error
    import urllib.request
    if env is None:
        env = os.environ
    url = control_url.rstrip("/") + "/v1/deployments/" + _PROBE_NAME
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    # The harness routes on the HOST header, so a loopback control URL needs the control
    # host named explicitly — the same rule `publish_doc._control_request` applies, against
    # the same pinned zone. Pinned in source, deliberately not read from the environment.
    if url.startswith("http://"):
        req.add_header("Host", _CONTROL_HOST)
    elif _is_edge_control(control_url):
        # Through the edge, Access answers before the harness does. Without the pair the reply
        # is a 302 to the login, which the opener below refuses — so the probe would report an
        # unreachable harness when the real problem is two unset variables. `status` already
        # refuses this combination earlier; the check is repeated here because a guard a caller
        # must remember is not a guard. No message renders a VALUE, only a variable name.
        cid = (env.get("CF_ACCESS_CLIENT_ID") or "").strip()
        secret = (env.get("CF_ACCESS_CLIENT_SECRET") or "").strip()
        if not (cid and secret):
            return "failed", ("this control URL is behind Cloudflare Access and needs "
                              "CF_ACCESS_CLIENT_ID and CF_ACCESS_CLIENT_SECRET; nothing was sent")
        req.add_header("CF-Access-Client-Id", cid)
        req.add_header("CF-Access-Client-Secret", secret)

    # `urlopen` follows a 302 silently. MEASURED on CPython 3.12.3, 2026-08-25: a cross-host
    # redirect delivered both `Authorization` and `CF-Access-Client-Id` to the redirect target.
    # An Access login IS such a redirect, so following one hands the publish bearer to the login
    # host. `publish_doc.NO_REDIRECTS` is the same construction, for the same reason.
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **kw):
            return None

    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(req, timeout=_PROBE_TIMEOUT) as resp:
            body = resp.read(4096)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return "denied", "the harness answered %d" % e.code
        if 300 <= e.code < 400:
            return "failed", ("the harness answered %d, a redirect, which is not followed "
                              "because the request carries the publish bearer. Through "
                              "Cloudflare Access that is the login page, so check "
                              "CF_ACCESS_CLIENT_ID and CF_ACCESS_CLIENT_SECRET." % e.code)
        return "failed", "the harness answered %d" % e.code
    except OSError as e:
        return "failed", "the harness could not be reached (%s)" % e.__class__.__name__
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return "failed", "the read-back did not return JSON, so this is not the control API"
    if not isinstance(payload, dict) or "active_deployment_id" not in payload:
        return "failed", "the read-back answered without the contract's fields"
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


def status(config_path=None, *, env=None, **_ignored):
    """The whole state of this machine, as one object.

    Every field here is derived; nothing is remembered between calls. Captured probe output
    is deliberately absent — a status object is something people paste. `env` is injectable
    so tests never depend on the developer's real environment.
    """
    if env is None:
        env = os.environ
    if config_path is None:
        config_path = CONFIG.config_file()
    config_path = Path(config_path)

    control = (env.get("DOC_HARNESS_CONTROL_URL") or "").strip()
    token = (env.get("DOC_HARNESS_PUBLISH_TOKEN") or "").strip()
    public_base = (env.get("DOC_HARNESS_PUBLIC_BASE") or "").strip()
    edge_pair = bool((env.get("CF_ACCESS_CLIENT_ID") or "").strip()
                     and (env.get("CF_ACCESS_CLIENT_SECRET") or "").strip())

    state = {
        "config_file": str(config_path),
        "first_run": not config_path.exists(),
        "harness_control_url": control or None,
        "publish_token_set": bool(token),
        "public_base_set": bool(public_base),
        "edge_credentials_set": edge_pair,
        "harness_reachable": None,
        "workspace_file": None,
        "project_count": None,
        "detail": None,
    }

    # The rows are checked in the order `_STATES` declares them. That order IS the contract —
    # it is what gives coexisting faults one defined answer instead of two implementations
    # disagreeing about which to report first.
    try:
        CONFIG.load(config_path)
    except CONFIG.ConfigError as e:
        return _finish(state, "config_version_unsupported", str(e))

    try:
        workspace = CONFIG.workspace_file(config_path=config_path)
    except CONFIG.ConfigError as e:
        return _finish(state, "needs_config", str(e))
    state["workspace_file"] = str(workspace) if workspace else None
    if workspace is None:
        return _finish(state, "needs_config", None)

    problem, count = _read_workspace(workspace)
    if problem:
        return _finish(state, problem, None)
    state["project_count"] = count

    if not control or not token:
        return _finish(state, "needs_harness_env", None)
    # #54: two different things put a Cloudflare Access door in front of a publish. The edge
    # VERIFY half, requested by DOC_HARNESS_PUBLIC_BASE, and — new — a control URL that is
    # itself the public control host. Either one needs the pair, so reporting `ready` without
    # it sends someone to a publish that can only come back as a login redirect.
    if (public_base or _is_edge_control(control)) and not edge_pair:
        return _finish(state, "edge_env_incomplete", None)

    outcome, detail = probe_harness(control, token, env=env)
    state["harness_reachable"] = outcome == "ok"
    if outcome == "failed":
        return _finish(state, "harness_unreachable", detail)
    if outcome == "denied":
        return _finish(state, "harness_denied", detail)

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


def cmd_add_project(config_path, name):
    try:
        name = CONFIG.validate_name(name)
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
    print("  workspace file   %s" % (state["workspace_file"] or "not set"))
    print("  projects         %s" % ("not readable" if state["project_count"] is None
                                     else state["project_count"]))
    print("  control URL      %s" % (state["harness_control_url"] or "not set"))
    print("  publish token    %s" % ("set" if state["publish_token_set"] else "not set"))
    print("  public base      %s" % ("set" if state["public_base_set"] else "not set"))
    print("  edge credentials %s" % ("set" if state["edge_credentials_set"] else "not set"))
    if state["harness_reachable"] is not None:
        print("  harness answers  %s" % ("yes" if state["harness_reachable"] else "NO"))
    print("")
    print("  status           %s" % state["status"])
    print("  can publish      %s" % ("yes" if state["can_proceed"] else "no"))
    if state["detail"]:
        print("  detail           %s" % state["detail"])
    print("")
    print("  " + _ADVICE[state["status"]])


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
