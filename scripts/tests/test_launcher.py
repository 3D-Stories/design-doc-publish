"""The CLI entry points, and the module-collision risk they exist to close (#15).

`python3 -m render` resolves by sys.path order. From an unexpected working directory Python can
import a different installed package named `render` — observed live during design, not
hypothesised: under a PYTHONPATH containing a foreign `render`, a bare `-m render` picked the
stranger.

`render-doc` is the guard. Its first version imported by name and checked provenance afterwards,
which three independent reviewers flagged: by then the foreign package's top-level code had
already run. These tests pin the properties that fix requires, and each hostile package here
prints from `__init__.py` — at IMPORT time — precisely so a check-after-import cannot pass them.
"""
import os
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
LAUNCHER = SCRIPTS / "render-doc"

IMPORT_MARKER = "FOREIGN_IMPORT_EXECUTED"
MAIN_MARKER = "FOREIGN_MAIN_EXECUTED"


def _foreign_render(tmp_path, name="hostile"):
    """A package named `render` that is not ours, which shouts when merely IMPORTED."""
    d = tmp_path / name
    (d / "render").mkdir(parents=True)
    (d / "render" / "__init__.py").write_text(
        f"print({IMPORT_MARKER!r})\n"
        f"def main(argv=None):\n"
        f"    print({MAIN_MARKER!r})\n"
        f"    return 99\n")
    return d


def _run(args, cwd, env=None, launcher=None):
    return subprocess.run([str(launcher or LAUNCHER)] + args,
                          cwd=str(cwd), capture_output=True, text=True, env=env)


def _doc_args(tmp_path):
    md = tmp_path / "in.md"
    md.write_text("# Title\n\nbody\n")
    out = tmp_path / "out.html"
    return ["--md", str(md), "--out", str(out), "--title", "T",
            "--generated-at", "2026-07-04 17:05 MST"], out


def test_importing_dunder_main_does_not_exit():
    """`import render.__main__` must not run the CLI — the `if __name__` guard.

    Out-of-process: without the guard this raises SystemExit during import.
    """
    rc = subprocess.run([sys.executable, "-c", "import render.__main__; print('IMPORT_OK')"],
                        cwd=str(SCRIPTS), capture_output=True, text=True)
    assert rc.returncode == 0, rc.stderr
    assert "IMPORT_OK" in rc.stdout


def test_launcher_renders_from_an_unrelated_cwd(tmp_path):
    args, out = _doc_args(tmp_path)
    rc = _run(args, cwd=tmp_path)
    assert rc.returncode == 0, rc.stderr
    assert "<h1>Title</h1>" in out.read_text(encoding="utf-8")


def test_foreign_package_never_executes_even_at_import_time(tmp_path):
    """The finding that sank v1: provenance was checked AFTER `import render`.

    The hostile package prints at import, so if the launcher imports by name at all, the marker
    appears — no matter what it does next.
    """
    args, out = _doc_args(tmp_path)
    env = dict(os.environ, PYTHONPATH=str(_foreign_render(tmp_path)))
    rc = _run(args, cwd=tmp_path, env=env)
    assert rc.returncode == 0, rc.stderr
    assert IMPORT_MARKER not in rc.stdout, "foreign package executed at import time"
    assert MAIN_MARKER not in rc.stdout
    assert out.is_file()


def test_precached_sys_modules_render_cannot_hijack(tmp_path):
    """A pre-populated sys.modules['render'] bypasses sys.path ordering entirely.

    Drive the launcher through a wrapper that seeds sys.modules first, then execs it.
    """
    args, out = _doc_args(tmp_path)
    wrapper = tmp_path / "wrapper.py"
    wrapper.write_text(textwrap_dedent := (
        "import sys, types, runpy\n"
        "fake = types.ModuleType('render')\n"
        f"fake.main = lambda argv=None: (print({MAIN_MARKER!r}), 99)[1]\n"
        "fake.__file__ = '/nowhere/render/__init__.py'\n"
        "sys.modules['render'] = fake\n"
        f"sys.argv = [{str(LAUNCHER)!r}] + {args!r}\n"
        f"runpy.run_path({str(LAUNCHER)!r}, run_name='__main__')\n"))
    rc = subprocess.run([sys.executable, str(wrapper)], cwd=str(tmp_path),
                        capture_output=True, text=True)
    assert MAIN_MARKER not in rc.stdout, "a pre-cached sys.modules['render'] was executed"
    assert out.is_file(), rc.stderr


def test_symlink_escape_is_refused(tmp_path):
    """A `render` symlinked out of the launcher's directory must be refused, not run.

    A lexical startswith() check passes this; realpath containment does not.
    """
    outside = tmp_path / "outside"
    (outside / "render").mkdir(parents=True)
    (outside / "render" / "__init__.py").write_text(
        f"print({IMPORT_MARKER!r})\ndef main(argv=None):\n    return 0\n")
    fake_scripts = tmp_path / "fake_scripts"
    fake_scripts.mkdir()
    (fake_scripts / "render-doc").write_text(LAUNCHER.read_text(encoding="utf-8"))
    (fake_scripts / "render-doc").chmod(0o755)
    (fake_scripts / "render").symlink_to(outside / "render", target_is_directory=True)

    rc = _run(["--md", "x", "--out", "y", "--title", "T"], cwd=tmp_path,
              launcher=fake_scripts / "render-doc")
    assert rc.returncode != 0
    assert "refusing to run" in (rc.stderr + rc.stdout)
    assert IMPORT_MARKER not in rc.stdout, "the symlinked package executed before refusal"


def test_missing_package_is_refused(tmp_path):
    """The launcher alone, with no render beside it, refuses rather than falling back."""
    lonely = tmp_path / "lonely"
    lonely.mkdir()
    copy = lonely / "render-doc"
    copy.write_text(LAUNCHER.read_text(encoding="utf-8"))
    copy.chmod(0o755)
    env = dict(os.environ, PYTHONPATH=str(_foreign_render(tmp_path)))
    rc = _run(["--md", "x", "--out", "y", "--title", "T"], cwd=tmp_path, env=env, launcher=copy)
    assert rc.returncode != 0
    assert "refusing to run" in (rc.stderr + rc.stdout)
    assert IMPORT_MARKER not in rc.stdout, "the foreign package executed before refusal"
