"""#42 PR 0 — the cross-style guard's own guards.

`crossstyle.sh` is the check that a template PR moved its target style and NOTHING else. It has
produced a false green twice in this epic's design review, both times because a mode reported OK
without having proved anything:

* its own header records a version that printed OK unconditionally under `--foundation`;
* the ten-style roster was hard-coded (`:25`), so a PR adding an eleventh style could not be
  checked at all, and an intersection-only redesign printed OK while an existing style had been
  DELETED from HEAD.

So the guard now needs guards. These tests drive the script against synthetic trees with a stubbed
renderer — no real rendering, so they are fast and can assert the decision logic directly. Each
test names the false green it prevents.
"""
import json
import os
import shutil
import subprocess
import stat
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
CROSSSTYLE = SCRIPTS / "tests" / "crossstyle.sh"
REL = "."

TEN = ["plain", "analysis", "roadmap", "report", "design",
       "dashboard", "review", "spec", "uat", "workflow"]

STUB = '''#!/usr/bin/env python3
"""Stand-in for render-doc: same --help shape, deterministic output, no engine."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
styles = json.load(open(os.path.join(HERE, "STYLES.json")))
if "--help" in sys.argv:
    # argparse prints the choice list TWICE — usage line and option description. The parser
    # under test must take the first match only.
    line = "[--style {%s}]" % ",".join(styles)
    print("usage: render-doc [-h] --md MD --out OUT --title TITLE\\n                  %s" % line)
    print("options:")
    print("  --style {%s}   the template" % ",".join(styles))
    sys.exit(0)
a = dict(zip(sys.argv[1::2], sys.argv[2::2]))
style = a.get("--style")
if style not in styles:
    sys.stderr.write("unknown style %r\\n" % style); sys.exit(2)
over = json.load(open(os.path.join(HERE, "OVERRIDES.json")))
if style in over and over[style] == "__crash__":
    sys.stderr.write("boom\\n"); sys.exit(1)
if style in over and over[style] == "__empty__":
    open(a["--out"], "w").close(); sys.exit(0)
open(a["--out"], "w").write("%s-%s\\n" % (style, over.get(style, "base")))
'''


def _tree(root: Path, styles, overrides=None, fixture=True):
    d = root / REL / "scripts"
    (d / "tests" / "fixtures").mkdir(parents=True, exist_ok=True)
    (d / "render-doc").write_text(STUB, encoding="utf-8")
    (d / "render-doc").chmod(0o755)
    (d / "STYLES.json").write_text(json.dumps(styles), encoding="utf-8")
    (d / "OVERRIDES.json").write_text(json.dumps(overrides or {}), encoding="utf-8")
    if fixture:
        (d / "tests" / "fixtures" / "crossstyle.md").write_text("# probe\n", encoding="utf-8")
    return root


def _run(tmp_path, head_styles, base_styles, target, head_over=None, base_over=None):
    head = _tree(tmp_path / "head", head_styles, head_over)
    base = _tree(tmp_path / "base", base_styles, base_over)
    out = tmp_path / "out"
    p = subprocess.run(
        ["bash", str(CROSSSTYLE), str(head), str(base), str(out), target],
        capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


class TestFalseGreensThatShipped:
    def test_a_style_deleted_from_head_fails(self, tmp_path):
        """The intersection-only design printed OK while `workflow` had vanished."""
        rc, out = _run(tmp_path, [s for s in TEN if s != "workflow"], TEN, "design")
        assert rc != 0, out
        assert "workflow" in out

    def test_an_unexpected_second_new_style_fails(self, tmp_path):
        """HEAD advertises the target AND an accidental extra: OK is not acceptable."""
        rc, out = _run(tmp_path, TEN + ["design-system", "module-map"], TEN, "design-system")
        assert rc != 0, out
        assert "module-map" in out

    def test_a_new_target_that_never_renders_fails(self, tmp_path):
        """Being NEW is not itself the proof — the target must actually render."""
        rc, out = _run(tmp_path, TEN + ["design-system"], TEN, "design-system",
                       head_over={"design-system": "__crash__"})
        assert rc != 0, out

    def test_a_new_target_rendering_an_empty_file_fails(self, tmp_path):
        rc, out = _run(tmp_path, TEN + ["design-system"], TEN, "design-system",
                       head_over={"design-system": "__empty__"})
        assert rc != 0, out


class TestTheHappyPaths:
    def test_a_genuinely_new_style_passes(self, tmp_path):
        rc, out = _run(tmp_path, TEN + ["design-system"], TEN, "design-system")
        assert rc == 0, out

    def test_an_existing_target_moving_alone_passes(self, tmp_path):
        rc, out = _run(tmp_path, TEN, TEN, "design", head_over={"design": "moved"})
        assert rc == 0, out

    def test_another_style_moving_fails(self, tmp_path):
        rc, out = _run(tmp_path, TEN, TEN, "design",
                       head_over={"design": "moved", "review": "leaked"})
        assert rc != 0, out
        assert "review" in out

    def test_a_comma_separated_target_passes_when_exactly_those_moved(self, tmp_path):
        """#90: a fix inside a shared resolver moves every style that shares it."""
        rc, out = _run(tmp_path, TEN, TEN, "roadmap,dashboard,analysis",
                       head_over={"roadmap": "m", "dashboard": "m", "analysis": "m"})
        assert rc == 0, out

    def test_a_fourth_style_moving_still_fails_under_a_list(self, tmp_path):
        """The list must not become a blanket permit — that is what `--foundation` is."""
        rc, out = _run(tmp_path, TEN, TEN, "roadmap,dashboard,analysis",
                       head_over={"roadmap": "m", "dashboard": "m", "analysis": "m",
                                  "review": "leaked"})
        assert rc != 0, out
        assert "review" in out

    def test_a_listed_style_that_did_not_move_fails(self, tmp_path):
        """Every name in the list is a CLAIM that it moved; an inert one is a wrong claim."""
        rc, out = _run(tmp_path, TEN, TEN, "roadmap,dashboard,analysis",
                       head_over={"roadmap": "m", "dashboard": "m"})
        assert rc != 0, out
        assert "analysis" in out and "inert" in out

    def test_plain_cannot_be_smuggled_in_via_the_list(self, tmp_path):
        """`plain` is frozen by contract; naming it must not buy an exemption."""
        rc, out = _run(tmp_path, TEN, TEN, "roadmap,plain",
                       head_over={"roadmap": "m", "plain": "m"})
        assert rc != 0, out
        assert "plain" in out

    def test_an_unknown_name_in_the_list_fails(self, tmp_path):
        rc, out = _run(tmp_path, TEN, TEN, "roadmap,nosuchstyle",
                       head_over={"roadmap": "m"})
        assert rc != 0, out
        assert "nosuchstyle" in out

    def test_plain_moving_always_fails(self, tmp_path):
        rc, out = _run(tmp_path, TEN, TEN, "design",
                       head_over={"design": "moved", "plain": "moved"})
        assert rc != 0, out
        assert "plain" in out


class TestNoStyleChangeMode:
    """PR 0 changes shared tooling and no template, so its proof is that NOTHING moved —
    the one case where that is the correct result rather than the false green the script's
    own header warns about. Ordinary target mode deliberately fails on zero movement, so it
    could not express this."""

    def test_passes_when_absolutely_nothing_moved(self, tmp_path):
        rc, out = _run(tmp_path, TEN, TEN, "--no-style-change")
        assert rc == 0, out

    def test_fails_if_any_style_moved(self, tmp_path):
        rc, out = _run(tmp_path, TEN, TEN, "--no-style-change",
                       head_over={"report": "moved"})
        assert rc != 0, out

    def test_fails_if_a_style_was_added(self, tmp_path):
        rc, out = _run(tmp_path, TEN + ["design-system"], TEN, "--no-style-change")
        assert rc != 0, out

    def test_fails_if_a_style_was_removed(self, tmp_path):
        rc, out = _run(tmp_path, TEN[:-1], TEN, "--no-style-change")
        assert rc != 0, out


class TestRosterParsing:
    def test_an_unreadable_roster_exits_two_rather_than_printing_ok(self, tmp_path):
        """`--help` failing must never degrade to 'nothing moved, OK'."""
        head = _tree(tmp_path / "head", TEN)
        base = _tree(tmp_path / "base", TEN)
        (head / REL / "scripts" / "STYLES.json").write_text("not json", encoding="utf-8")
        p = subprocess.run(["bash", str(CROSSSTYLE), str(head), str(base),
                            str(tmp_path / "out"), "design"],
                           capture_output=True, text=True)
        assert p.returncode == 2, p.stdout + p.stderr

    def test_a_missing_tree_exits_nonzero(self, tmp_path):
        base = _tree(tmp_path / "base", TEN)
        p = subprocess.run(["bash", str(CROSSSTYLE), str(tmp_path / "nope"), str(base),
                            str(tmp_path / "out"), "design"],
                           capture_output=True, text=True)
        assert p.returncode != 0, p.stdout + p.stderr
