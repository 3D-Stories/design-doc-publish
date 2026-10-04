#!/usr/bin/env python3
"""Install a self-contained Codex skill without the nested Claude entrypoints.

An existing destination is never replaced. Updates require moving the previous
installation aside first, which also gives the owner a rollback copy.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parent.parent
FILES = ("SKILL.md", "README.md", "LICENSE")
DIRECTORIES = ("scripts", "index", "harness", "docs", "references")


def ignored(directory, names):
    return {name for name in names if name in {"__pycache__", ".pytest_cache", "tests"}
            or name.endswith((".pyc", ".pyo"))}


def install(source: Path, destination: Path) -> None:
    """Copy the runtime and references, preserving relative package imports."""
    if source.resolve() == destination.parent.resolve() or source.resolve() in destination.parent.resolve().parents:
        raise ValueError("destination must be outside the source package")
    # Validate the input before creating anything. A checkout modified to contain
    # an escaping link must not copy some other file into the installed package.
    for name in FILES + DIRECTORIES:
        path = source / name
        if path.is_symlink() or not path.exists():
            raise ValueError(f"missing or symlinked package resource: {name}")
        if path.is_dir():
            for base, dirs, files in os.walk(path, followlinks=False):
                omitted = ignored(base, dirs + files)
                dirs[:] = [item for item in dirs if item not in omitted]
                for item in dirs + [item for item in files if item not in omitted]:
                    if (Path(base) / item).is_symlink():
                        raise ValueError(f"symlinked package resource: {Path(base) / item}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    # mkdir is the exclusive claim: even an existing empty directory or dangling
    # symlink is a conflict. There is deliberately no --force option.
    destination.mkdir()
    try:
        for name in FILES:
            shutil.copy2(source / name, destination / name)
        for name in DIRECTORIES:
            shutil.copytree(source / name, destination / name, ignore=ignored)
    except BaseException:
        shutil.rmtree(destination)
        raise


def main(argv=None):
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, default=home / "skills" / "design-doc-publish",
                        help="new skill directory (default: $CODEX_HOME/skills/design-doc-publish)")
    args = parser.parse_args(argv)
    # Do not resolve the final component: a dangling symlink must remain a conflict.
    destination = Path(os.path.abspath(args.dest.expanduser()))
    try:
        install(ROOT, destination)
    except (OSError, ValueError) as exc:
        print(f"Codex install refused: {exc}", file=sys.stderr)
        return 1
    print(f"Installed design-doc-publish to {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
