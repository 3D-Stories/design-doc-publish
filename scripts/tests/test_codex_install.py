"""Exercise the installed package from an unrelated project, without Claude."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("codex_install", ROOT / "scripts/install_codex_skill.py")
INSTALL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALL)


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    target = tmp_path_factory.mktemp("codex bundle") / "design-doc-publish"
    INSTALL.install(ROOT, target)
    return target


def test_one_discoverable_entrypoint_and_complete_resources(installed):
    assert list(installed.rglob("SKILL.md")) == [installed / "SKILL.md"]
    assert (installed / "harness/manifest.py").is_file()
    assert (installed / "index/build_index.py").is_file()
    assert (installed / "docs/updating-a-living-document.md").is_file()
    assert (installed / "references/artifact-organizer/LICENSE-upstream.txt").is_file()
    assert not (installed / "scripts/tests").exists()


@pytest.mark.parametrize("style", ["design", "minutes"])
def test_installed_publisher_runs_full_local_gate(installed, tmp_path, style):
    md = tmp_path / "local review.md"
    md.write_bytes((ROOT / "docs/examples/gallery" / f"{style}.md").read_bytes())
    workspace = tmp_path / "workspace.json"
    workspace.write_text(json.dumps({"projects": []}))
    proc = subprocess.run(
        [sys.executable, str(installed / "scripts/publish_doc.py"), "--md", str(md),
         "--title", f"Halyard {style}", "--project", "workspace", "--type", style,
         "--ref", "codex-check", "--workspace-file", str(workspace), "--dry-run"],
        cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "lint gate passed" in proc.stdout
    assert "stopping before the first network call" in proc.stdout
    assert md.with_suffix(".html").stat().st_size > 1000
    assert md.read_bytes() == (ROOT / "docs/examples/gallery" / f"{style}.md").read_bytes()


def test_existing_destination_is_preserved(tmp_path):
    destination = tmp_path / "existing"
    destination.mkdir()
    sentinel = destination / "owner.txt"
    sentinel.write_text("keep me")
    with pytest.raises(FileExistsError):
        INSTALL.install(ROOT, destination)
    assert list(destination.iterdir()) == [sentinel]
    assert sentinel.read_text() == "keep me"


def test_dangling_destination_symlink_is_preserved(tmp_path):
    destination = tmp_path / "existing"
    destination.symlink_to(tmp_path / "missing")
    with pytest.raises(FileExistsError):
        INSTALL.install(ROOT, destination)
    assert destination.is_symlink()
    assert not (tmp_path / "missing").exists()


def test_source_symlink_refused_before_destination_creation(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for name in INSTALL.FILES:
        (source / name).write_text("fixture")
    for name in INSTALL.DIRECTORIES:
        (source / name).mkdir()
    (source / "scripts/foreign.py").symlink_to(tmp_path / "outside.py")
    destination = tmp_path / "install"
    with pytest.raises(ValueError, match="symlinked package resource"):
        INSTALL.install(source, destination)
    assert not destination.exists()


def test_recursive_installation_refused(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    destination = source / "scripts/nested-skill"
    with pytest.raises(ValueError, match="outside the source"):
        INSTALL.install(source, destination)
    assert not destination.exists()
