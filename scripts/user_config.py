"""Where a user's own configuration lives, and how the two settings resolve (#9).

Design: `docs/planning/2026-08-10-9-first-run-setup-flow.md` (revision 3, after a Step-4
gate that ran three cross-model passes and closed budget-exhausted).

The workspace file that stage 2 validates ``--project`` against used to be this package
author's machine written into the source, so a stranger installing the plugin stopped at
stage 2 of 7. This module replaces that constant with a resolution order, and — just as
importantly — with a refusal that names what to run when nothing is configured. (It once
resolved a second setting, the deploy account for the retired hosting vendor; that setting
died with the vendor.)

Four properties are load-bearing, and each of them was a review finding rather than foresight:

* **Resolution happens at CALL time, never at import.** A module-level ``Path.home()`` would
  make every test depend on the developer's real home directory, and would defeat the
  subprocess isolation the first-run test needs. A test greps this file to keep it so.
* **The resolvers take their CLI value as a parameter.** A zero-argument resolver cannot see a
  parsed flag, so it would need a hidden ``sys.argv`` dependency or the callers would really
  own precedence — which would make the claim that this module owns resolution false.
* **``UNSET`` is not ``None`` and neither is ``""``.** An absent flag falls through. An
  explicitly empty one is an error: the user tried to set something, and silently resolving a
  different value is how a public page reaches the wrong account.
Stdlib only, like the rest of this package.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

#: The one config-file version this build understands.
CONFIG_VERSION = 1

#: The shape a project name must have. It reaches page hostnames and the generated index
#: page, so a second, subtly different rule anywhere else would be a hole. A leading `-`
#: cannot match, which is what makes an option-like value impossible.
_SLUG = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?")
MAX_NAME = 100

#: Distinct from `None` (which argparse supplies for an absent flag) and from `""` (which the
#: user typed on purpose).
UNSET = object()

_HERE = Path(__file__).resolve().parent

#: Printed in every refusal. A stranger cannot expand `${CLAUDE_PLUGIN_ROOT}` in their shell —
#: the README says so — so the path has to be real.
SETUP_COMMAND = f"python3 {_HERE / 'setup.py'}"

ENV_CONFIG = "DESIGN_DOC_PUBLISH_CONFIG"
ENV_WORKSPACE = "DESIGN_DOC_PUBLISH_WORKSPACE_FILE"


class ConfigError(Exception):
    """A refusal a stranger is meant to be able to act on.

    Every message names either what to run or what to fix. Callers render it as one line;
    nothing here raises a traceback at a user.
    """


def _selected(cli_value, env_name: str, label: str) -> str | None:
    """The CLI value, else the environment value, else ``None``.

    An explicitly empty value at either rung raises rather than falling through. That
    distinction is the whole reason `UNSET` exists: `None` means argparse saw no flag.
    """
    if cli_value is not UNSET and cli_value is not None:
        if not str(cli_value).strip():
            raise ConfigError(
                f"{label} was given as an empty value. Either pass a real one or omit the "
                f"flag — resolving something else would silently target the wrong place.")
        return str(cli_value)
    raw = os.environ.get(env_name)
    if raw is not None:
        if not raw.strip():
            raise ConfigError(
                f"{env_name} is set but empty. Either give it a real value or unset it — "
                f"an empty value is not the same as an absent one.")
        return raw
    return None


def config_file(*, cli_value=UNSET) -> Path:
    """Which config file this run reads: ``--config``, then the environment, then XDG.

    Every entry point calls this ONCE and passes the result to both resolvers, so a single
    run cannot read two different config files.
    """
    chosen = _selected(cli_value, ENV_CONFIG, "--config")
    if chosen is not None:
        return Path(chosen).expanduser().resolve()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg and xdg.strip() else Path.home() / ".config"
    return base / "design-doc-publish" / "config.json"


def load(config_path: Path) -> dict:
    """The config as a mapping, or ``{}``.

    Absence is silent, because a user who has never run setup is the normal first case.
    Everything else warns to stderr and reads as absent — except an unrecognised ``version``,
    which is an explicit error: reading half of a format this build does not know would
    resolve values it cannot vouch for.
    """
    path = Path(config_path)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as e:
        print(f"user_config: ignoring {path} ({e.__class__.__name__})", file=sys.stderr)
        return {}
    try:
        data = json.loads(raw)
    except ValueError as e:
        print(f"user_config: ignoring {path} — not valid JSON ({e})", file=sys.stderr)
        return {}
    if not isinstance(data, dict):
        print(f"user_config: ignoring {path} — root is {type(data).__name__}, not an object",
              file=sys.stderr)
        return {}
    version = data.get("version", CONFIG_VERSION)
    if version != CONFIG_VERSION:
        raise ConfigError(
            f"{path} declares version {version!r}, and this build understands "
            f"{CONFIG_VERSION!r}. Refusing to read it rather than guessing at half a format.")
    return data


def load_for_update(config_path: Path) -> dict:
    """The config, or a REFUSAL — the loader a mutation must use.

    `load()` is deliberately lenient: it reads a malformed config as absent so that STATUS
    can still report on a broken machine. A setter that merged into that empty mapping and
    replaced the file atomically would destroy whatever was recoverable in it, which is the
    opposite of helpful when the file is the only copy. So writing gets a strict loader and
    reading keeps the lenient one.
    """
    path = Path(config_path)
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(
            f"{path} exists but cannot be read ({e.__class__.__name__}). Refusing to replace "
            f"a file whose contents are unknown.") from e
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise ConfigError(
            f"{path} is not valid JSON ({e}). Refusing to overwrite it — fix it or move it "
            f"aside, because this is the only copy of whatever is in it.") from e
    if not isinstance(data, dict):
        raise ConfigError(
            f"{path} holds {type(data).__name__}, not an object. Refusing to overwrite it.")
    version = data.get("version", CONFIG_VERSION)
    if version != CONFIG_VERSION:
        raise ConfigError(
            f"{path} declares version {version!r}, and this build understands "
            f"{CONFIG_VERSION!r}. Refusing to read it rather than guessing at half a format.")
    return data


def validate_name(value) -> str:
    """A project name, or a refusal.

    One DNS-label-shaped slug: the name reaches page hostnames and the generated index, so
    anything else is refused before it reaches either. A leading `-` cannot match, which is
    what makes an option-like value impossible.
    """
    if not isinstance(value, str):
        raise ConfigError(
            f"a project name must be a string, not {type(value).__name__}")
    if len(value) > MAX_NAME:
        raise ConfigError(
            f"the name {value[:20]!r}… is longer than {MAX_NAME} characters")
    if not _SLUG.fullmatch(value):
        raise ConfigError(
            f"{value!r} is not a usable project name. Use lowercase letters, digits and "
            f"inner hyphens only.")
    return value


def workspace_file(*, cli_value=UNSET, config_path=None) -> Path | None:
    """Where the workspace file is, or ``None`` when nothing is configured.

    There is deliberately NO implicit fallback to `~/rawgentic/.rawgentic_workspace.json`.
    An earlier revision kept it "only when the file exists", which reads as harmless and is
    not: a machine that happens to have a file at that path would silently adopt it, without
    the setup run, and then validate project names and group the index against a file its
    owner never pointed this tool at. AC4 says the hardcoded default is RETIRED and the
    location setup recorded is used instead, and a conditional default is still a default.
    Existing users run setup once, which is one command and says so.
    """
    chosen = _selected(cli_value, ENV_WORKSPACE, "--workspace-file")
    if chosen is not None:
        return Path(chosen).expanduser().resolve()
    if config_path is None:
        config_path = config_file()
    declared = load(config_path).get("workspace_file")
    if isinstance(declared, str) and declared.strip():
        return Path(declared).expanduser().resolve()
    return None


def require_workspace_file(*, cli_value=UNSET, config_path=None) -> Path:
    """The workspace file, or a refusal naming exactly what to run.

    Four faults, kept apart on purpose. A stale unreadable file must never degrade into an
    empty allowlist that refuses every project name for the wrong reason, and "never
    configured" is a different thing to fix than "configured, and gone".
    """
    resolved = workspace_file(cli_value=cli_value, config_path=config_path)
    if resolved is None:
        raise ConfigError(
            "no workspace file is configured, so --project cannot be checked against a "
            f"known set. Run: {SETUP_COMMAND}")
    if not resolved.exists():
        raise ConfigError(
            f"the configured workspace file {resolved} does not exist. Either restore it or "
            f"point somewhere else. Run: {SETUP_COMMAND}")
    try:
        raw = resolved.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(
            f"the configured workspace file {resolved} cannot be read "
            f"({e.__class__.__name__}). Run: {SETUP_COMMAND}") from e
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise ConfigError(
            f"the configured workspace file {resolved} is malformed and cannot be parsed "
            f"({e}). Run: {SETUP_COMMAND}") from e
    # `projects` must be PRESENT and a list. Defaulting an absent key to `[]` read `{}` as a
    # valid-but-empty workspace, so setup reported ready while every --project was refused.
    if (not isinstance(data, dict) or "projects" not in data
            or not isinstance(data["projects"], list)):
        raise ConfigError(
            f"the configured workspace file {resolved} is malformed — it must be an object "
            f"whose `projects` is a list. Run: {SETUP_COMMAND}")
    return resolved


def write_config(data: dict, config_path: Path) -> None:
    """Write the config atomically, creating its directory first.

    The `mkdir` is not a detail. On a genuine first run the package's config directory does
    not exist, so asking for a same-directory temporary file inside it raises before anything
    is written — a first-run crash inside the code written to fix first-run crashes.
    """
    path = Path(config_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ConfigError(
            f"could not create {path.parent} ({e.__class__.__name__}: {e})") from e
    payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
    handle = None
    try:
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".config-", suffix=".tmp")
        handle = os.fdopen(fd, "w", encoding="utf-8")
        handle.write(payload)
        handle.close()
        handle = None
        os.replace(tmp_name, path)
    except OSError as e:
        if handle is not None:
            handle.close()
        raise ConfigError(f"could not write {path} ({e.__class__.__name__}: {e})") from e
