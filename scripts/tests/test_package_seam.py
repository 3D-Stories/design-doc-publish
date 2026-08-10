"""The package seam is real and the per-wave stubs are still empty (#15, wave 0a).

Wave 0a's whole job is to create destinations that later waves fill in. These tests pin two
things: every named module actually IMPORTS (not merely parses), and each stub's body is empty
once its docstring is removed. The second half matters more than it looks — it means a later wave
cannot half-fill a module without this test going red and forcing the inventory to be updated
deliberately.

The emptiness check compares the whole module body rather than looking for specific node types.
An earlier version enumerated defs/imports/assignments, which silently accepted top-level
expressions, `raise`, and anything nested under `if`/`try`.
"""
import ast
import importlib
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

RENDER = SCRIPTS / "render"

# (module name for import, path relative to render/)
# #16 (wave 1) FILLED render.markdown and #13 (wave 3) FILLED render.templates —
# both move to FILLED below. The remaining entries are still awaiting their waves.
# Wave 6 (#14) FILLED render.vdl, the last stub wave 0a created. The list is now
# empty: every destination this package reserved has been built.
STUBS = []


# Modules a wave has already filled in. They must still IMPORT and still name their
# owning wave, but they are expected to declare things — asserting emptiness here
# would fail the moment the wave lands, which is the wrong signal.
FILLED = [
    ("render.markdown", "markdown.py"),           # wave 1, #16
    ("render.blocks", "blocks.py"),               # wave 2, #17
    ("render.templates", "templates/__init__.py"),  # wave 3, #13
    ("render.lint", "lint.py"),                     # wave 5, #12
    ("render.vdl", "vdl.py"),                       # wave 6, #14
]


def _body_without_docstring(path):
    """Every top-level statement except a leading docstring."""
    body = ast.parse(path.read_text(encoding="utf-8")).body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    return body


def test_package_imports():
    import render  # noqa: F401


def test_every_reserved_destination_has_been_built():
    """Wave 0a created five empty modules for later waves to fill. #14 filled the last of
    them, so `STUBS` is empty and the two stub-parametrised tests below skip on an empty
    set — which reads as "not run" rather than "nothing left to do". This says it
    positively. A future wave that reserves a new stub re-populates STUBS and those tests
    come back to life on their own."""
    assert STUBS == [], f"still awaiting a wave: {[m for m, _ in STUBS]}"
    assert len(FILLED) == 5


@pytest.mark.parametrize("module_name,rel", STUBS, ids=[m for m, _ in STUBS])
def test_stub_imports_and_is_empty(module_name, rel):
    importlib.import_module(module_name)          # must actually import, not just parse
    remaining = _body_without_docstring(RENDER / rel)
    assert remaining == [], (
        f"{rel} is no longer an empty stub — it declares "
        f"{[type(n).__name__ for n in remaining]}. If a wave is filling it in, update the "
        f"expected node counts in the plan and this test together.")


@pytest.mark.parametrize("module_name,rel", STUBS, ids=[m for m, _ in STUBS])
def test_stub_names_its_owning_wave(module_name, rel):
    """A stub with no docstring is an orphan — the next wave would not know it owned it."""
    doc = ast.get_docstring(ast.parse((RENDER / rel).read_text(encoding="utf-8"))) or ""
    assert "wave" in doc.lower(), f"{rel} does not name its owning wave"
    assert "#" in doc, f"{rel} does not cite an issue number"


@pytest.mark.parametrize("module_name,rel", FILLED, ids=[m for m, _ in FILLED])
def test_filled_module_imports_and_declares_something(module_name, rel):
    """#16: render.markdown now holds the parser. It must import and be non-empty —
    the inverse of the stub guard, so the seam is still checked after a wave lands."""
    importlib.import_module(module_name)
    assert _body_without_docstring(RENDER / rel) != [], (
        f"{rel} is listed as FILLED but is empty — did a wave get reverted?")


@pytest.mark.parametrize("module_name,rel", FILLED, ids=[m for m, _ in FILLED])
def test_filled_module_still_names_its_owning_wave(module_name, rel):
    doc = ast.get_docstring(ast.parse((RENDER / rel).read_text(encoding="utf-8"))) or ""
    assert "wave" in doc.lower() and "#" in doc, f"{rel} lost its wave provenance"
