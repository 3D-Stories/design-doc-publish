"""One project, one colour, one place to read it from (#14, wave 6).

Every hosted page in this account wore the same teal, so a reader could not tell a
chorestory doc from a saystory doc without reading it. This module owns the per-project
accent — declared by the project itself where it has a design system, seeded here where it
does not — and BOTH consumers read it here: the renderer that draws the page and the index
that lists it. That is what makes them agree; nothing else does.

Design: `docs/planning/2026-08-01-14-vdl-packs.md` (revision 2, after a Step 4 gate).

Two things this module exists to get right, both of which a first draft got wrong and the
design gate caught:

* **`pack_for()` never returns `None`.** A source of truth that abstains for unknown
  projects is not one: the renderer would keep its default accent while the index picked
  its own colour, so the two would provably disagree on a supported path.
* **"AA compliant" is a claim about a PAIR, never about a colour.** chorestory's brand blue
  is annotated AA-compliant in its own token file and is — against its own background. It
  fails against this renderer's, in both themes. A pack carrying a colour from one system
  into another cannot inherit the claim, which is why every pack here is measured against
  the surfaces it will actually sit on (`test_vdl_packs.py`), not trusted.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

VERSION = 1
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_THEMES = ("light", "dark")
_ALLOWED = {"version", "accent", "tint", "source", "note"}
_REQUIRED = ("accent", "source", "note")
MAX_FIELD = 400

# Seed packs for projects that have not declared one. These are the colours the docs index
# has always shown, so adopting them is what keeps the index and the pages agreeing rather
# than being a second guess at the same thing.
#
# THREE WERE DARKENED. Not because they were wrong — the index uses them as dots and
# badges, decorative graphics where WCAG 1.4.11's 3:1 applies, and every one clears that.
# They fail only under the promotion this module performs, from decoration to TEXT at
# 4.5:1. Each variant is the same hue walked down in lightness, so the index keeps its
# visual identity. Ratios are against the renderer's light --bg (#f6f7f8).
SEEDS = {
    # chorestory HAS a design system, so this entry is a stand-in, not a verdict: it
    # carries the exact values derived from that repo's own tokens file, so the real
    # resolution path is chorestory blue TODAY rather than a hashed fallback. The
    # declaration in chorestory's own `.rawgentic.json` supersedes it automatically the
    # moment it lands (declared beats seed), and the values are identical, so the
    # handover is invisible. Without this the page shipped green while the suite passed
    # on a fixture — which is what Step 11 called, correctly, a scope dodge.
    "chorestory":       {"light": "#1e5f7a", "dark": "#4da7c4",
                         "note": "src/styles/design-tokens.css --brand-blue-500/-300; "
                                 "pending declaration in chorestory's own repo"},
    "herdr-dashboard":  {"light": "#0e78a7", "dark": "#5ec8f2",
                         "note": "darkened from #0f7fb0 (4.18:1 -> 4.59:1)"},
    "rawgentic":        {"light": "#a26211", "dark": "#f2a65e",
                         "note": "darkened from #b06a12 (3.98:1 -> 4.56:1)"},
    "3dstories-studio": {"light": "#816e0e", "dark": "#f2d95e",
                         "note": "darkened from #8f7a10 (3.95:1 -> 4.69:1)"},
    "saystory":         {"light": "#3d7c31", "dark": "#8fd483", "note": "index colour, 4.75:1"},
    "lumenquire":       {"light": "#7b4fb3", "dark": "#c99df5", "note": "index colour, 5.42:1"},
    "workspace":        {"light": "#5a657c", "dark": "#a8b2c2", "note": "index colour, 5.46:1"},
    "sysop":            {"light": "#0e7d6d", "dark": "#7fe0cf", "note": "index colour, 4.69:1"},
    "3dstories-bench":  {"light": "#b3325d", "dark": "#f27e9d", "note": "index colour, 5.54:1"},
    "thewanderinginn":  {"light": "#a84f2e", "dark": "#e0876b", "note": "index colour, 5.12:1"},
    # THIS repository, added by #56, and the values are not a new choice: they are
    # PALETTE[2], the colour the name hash was already handing out. Three committed planning
    # documents shipped wearing it before anyone declared it, which is the whole defect —
    # the accent was resolved through `~/.config/design-doc-publish/workspace.json`, whose
    # entry for this project carries no `path`, so `_project_config` returned None silently
    # and the hash decided the branding of public pages. Seeding it here makes the fallback
    # unreachable for this project and the answer a property of the repository. Same two
    # colours land in this repo's own `.rawgentic.json` `vdl` block, so the `declared` path
    # agrees rather than being overridden — `test_vdl_packs.py` pins the two to each other.
    "design-doc-publish": {"light": "#4f7d15", "dark": "#b7e87f",
                           "note": "PALETTE[2], adopted as-declared in #56 — already worn by "
                                   "three committed planning docs before it was declared"},
}

# For a project in neither list. All five clear AA in both themes (light 4.58-8.65, dark
# 6.55-12.67), so they are safe to use as text and not only as a dot.
PALETTE = [("#0d6f88", "#7fd4e8"), ("#8a5a12", "#e8b87f"), ("#4f7d15", "#b7e87f"),
           ("#8a1d75", "#e87fd4"), ("#1f3f9e", "#7f9ae8")]


def _warn(project: str, path, detail: str) -> None:
    """One line, naming the project, the path and what failed — so a permissions fault and
    a typo'd hex are distinguishable in a log, which is the whole point of warning."""
    print(f"vdl_packs: ignoring the vdl block for {project!r} ({path}): {detail}",
          file=sys.stderr)


def _valid_colours(block: dict, key: str) -> dict | None:
    value = block.get(key)
    if not isinstance(value, dict) or set(value) != set(_THEMES):
        return None
    if not all(isinstance(value[t], str) and _HEX.match(value[t]) for t in _THEMES):
        return None
    return {t: value[t].lower() for t in _THEMES}


def load_pack(project: str, config_path: Path) -> dict | None:
    """The DECLARED pack from a project's own `.rawgentic.json`, or None.

    Fails open, always — a bad block must never break a render. Only one thing is silent:
    there being no block at all, which is the normal path for most projects. Everything
    else warns, including an unreadable file: a permissions or path fault that silently
    shipped default branding would leave the gate green and the page wrong.
    """
    if not config_path.exists():
        return None                                   # silent: nothing to read
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as e:
        _warn(project, config_path, f"unreadable ({e.__class__.__name__})")
        return None
    except ValueError as e:
        # ValueError, not JSONDecodeError: a file of invalid UTF-8 raises
        # UnicodeDecodeError from read_text, which the narrower clause missed — so a
        # corrupt byte aborted the render instead of falling open to a seed.
        _warn(project, config_path, f"undecodable ({e.__class__.__name__}: {e})")
        return None
    if not isinstance(data, dict):
        # A top-level array or string is a corrupt config, not an absence. Only genuine
        # absence is silent.
        _warn(project, config_path, f"config root is {type(data).__name__}, not an object")
        return None
    if "vdl" not in data:
        return None                                   # silent: no block, the normal case

    block = data["vdl"]
    if not isinstance(block, dict):
        _warn(project, config_path, f"vdl is {type(block).__name__}, not an object")
        return None
    if block.get("version", VERSION) != VERSION:
        _warn(project, config_path, f"unknown vdl version {block.get('version')!r}")
        return None
    extra = set(block) - _ALLOWED
    if extra:
        _warn(project, config_path, f"unexpected key(s) {sorted(extra)}")
        return None
    for field in _REQUIRED:
        if field not in block:
            _warn(project, config_path, f"missing required field {field!r}")
            return None
    for field in ("source", "note"):
        if not isinstance(block[field], str) or not 0 < len(block[field]) <= MAX_FIELD:
            _warn(project, config_path, f"{field} must be a string of 1-{MAX_FIELD} chars")
            return None

    accent = _valid_colours(block, "accent")
    if accent is None:
        _warn(project, config_path, "accent must be {light: '#rrggbb', dark: '#rrggbb'}")
        return None
    tint = None
    if "tint" in block:
        tint = _valid_colours(block, "tint")
        if tint is None:
            _warn(project, config_path, "tint must be {light: '#rrggbb', dark: '#rrggbb'}")
            return None

    return {"accent": accent, "tint": tint, "origin": "declared",
            "source": block["source"], "note": block["note"]}


def _project_config(project: str, workspace_file: Path | None) -> Path | None:
    """Where `project` keeps its own config, or None.

    Every malformed shape WARNS rather than resolving silently: a workspace that cannot
    be read produces a hashed fallback that lints clean, which is the wrong-branding-
    behind-a-green-gate failure this module exists to remove. Only a valid workspace
    that genuinely has no such project is silent.

    `None` is one of those silent cases, and since #9 it is the ordinary state rather than
    an impossible one: the hardcoded `~/rawgentic/.rawgentic_workspace.json` default is
    retired, so a machine that has never run setup resolves to no workspace at all. The
    renderer must keep working there — it is the README's first command — so this degrades
    to the seed-or-hash answer instead of raising.

    The resolved directory must stay inside the workspace root. An absolute `path`
    discards the prefix entirely and `../` walks out of it, either of which would let a
    workspace entry point the publisher at a foreign config and choose a public page's
    branding from outside the tree that declares it.
    """
    if workspace_file is None or not workspace_file.exists():
        return None                                   # silent: no workspace at all
    try:
        data = json.loads(workspace_file.read_text(encoding="utf-8"))
    except OSError as e:
        _warn(project, workspace_file, f"workspace unreadable ({e.__class__.__name__})")
        return None
    except ValueError as e:
        _warn(project, workspace_file, f"workspace undecodable ({e.__class__.__name__})")
        return None
    if not isinstance(data, dict):
        _warn(project, workspace_file, f"workspace root is {type(data).__name__}")
        return None
    if "projects" not in data:
        return None                                   # silent: nothing declared
    entries = data["projects"]
    if not isinstance(entries, list):
        # Present-but-wrong is a different event from absent — the same distinction the
        # vdl block itself draws. `{"projects": null}` is a corrupt workspace, not an
        # empty one, and silently seeding past it hides the corruption.
        _warn(project, workspace_file, f"projects is {type(entries).__name__}, not a list")
        return None

    root = workspace_file.parent.resolve()
    for entry in entries:
        if not isinstance(entry, dict):
            continue                                  # one bad row must not blind the rest
        if str(entry.get("name", "")).strip().lower() != project.lower():
            continue
        if "path" not in entry:
            # Silent, and this is the #9 case rather than a slip. `setup.py --add-project`
            # writes `{"name": ...}` with no path, because a project registered by name has
            # no config directory to read — that is absence, and absence is the one thing
            # this module does not warn about. Warning here would print on every render.
            return None
        raw = entry.get("path")
        if not isinstance(raw, str):
            _warn(project, workspace_file, f"path is {type(raw).__name__}, not a string")
            return None
        if not raw:
            # Present-but-useless is a different event from absent, and it stays loud.
            _warn(project, workspace_file, "entry has an empty path, so its config cannot "
                                           "be found")
            return None
        try:
            resolved = (root / raw).resolve()
        except OSError as e:
            _warn(project, workspace_file, f"path {raw!r} does not resolve ({e})")
            return None
        if not resolved.is_relative_to(root):
            _warn(project, workspace_file,
                  f"path {raw!r} resolves outside the workspace ({resolved}); refusing "
                  f"to take branding from a foreign tree")
            return None
        return resolved / ".rawgentic.json"
    return None


def _fallback(project: str) -> dict:
    """Deterministic on the NAME, not on position.

    `build_index` used to pick `PALETTE[len(seen) % len(PALETTE)]`, so a project's colour
    depended on how many other groups happened to sort before it — adding one project
    silently recoloured others. Hashing the name removes the coupling entirely.
    """
    digest = hashlib.sha256(project.lower().encode()).digest()
    light, dark = PALETTE[digest[0] % len(PALETTE)]
    return {"accent": {"light": light, "dark": dark}, "tint": None, "origin": "fallback",
            "source": "vdl_packs.PALETTE", "note": f"no declaration or seed for {project}"}


def pack_for(project: str, workspace_file: Path | None) -> dict:
    """The colour for `project`: declared → seed → deterministic fallback.

    NEVER returns None. A single source of truth that abstains is not one — the renderer
    would keep its default accent while the index picked its own, which is precisely the
    divergence this module exists to remove.

    `workspace_file` may be `None` (#9): a machine with no configured workspace resolves
    through the seed table and then the name hash, silently.
    """
    project = (project or "").strip().lower()
    config = _project_config(project, workspace_file)
    if config is not None:
        declared = load_pack(project, config)
        if declared is not None:
            return declared
    seed = SEEDS.get(project)
    if seed is not None:
        return {"accent": {"light": seed["light"], "dark": seed["dark"]}, "tint": None,
                "origin": "seed", "source": "vdl_packs.SEEDS", "note": seed["note"]}
    return _fallback(project)
