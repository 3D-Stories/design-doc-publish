"""Every template is reachable by a documented path (#43, AC2).

**A template nobody can select does not exist.** `dashboard` proved it: no `PURPOSE_STYLE` entry
mapped to it, so no `--type` reached it, and `SKILL.md` did not mention `--style` at all after
PR #34 collapsed the file from 212 lines to 50 and took the `--style` row with it. The template
worked perfectly and was unreachable by any documented path for a day.

Documentation alone would not have caught that, because the way it broke was a doc edit. So this
is a guard rather than a paragraph: it reads the live registry and asks, of each entry, whether a
reader could arrive at it. It is what stops a fourteenth template being added and quietly orphaned.

Two documented paths count, and nothing else does:

* a `--type` maps to it through `PURPOSE_STYLE`, or
* `SKILL.md` names it in prose as an explicit `--style` target.

A style reachable only by reading the source is not reachable.
"""
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import publish_doc  # noqa: E402
import render  # noqa: E402

SKILL_MD = SCRIPTS.parent / "skills" / "design-doc-publish" / "SKILL.md"


def _names_in_skill_md(candidates):
    """Which of `candidates` SKILL.md names, word-boundary matched.

    Deliberately not a backtick-span parser. Two attempts at one failed on this very file:
    a whole-span match missed ``--style dashboard`` because the name is not the whole span, and
    taking each span's last word misread the pairing entirely, because a ``` fence makes the
    backticks in a document stop coming in pairs. The question that actually matters is plain —
    does the doc a reader opens contain this style's name — so ask that.
    """
    text = SKILL_MD.read_text(encoding="utf-8")
    return {c for c in candidates if re.search(rf"\b{re.escape(c)}\b", text)}


class TestEveryTemplateIsReachable:
    def test_no_template_is_orphaned(self):
        by_type = set(publish_doc.PURPOSE_STYLE.values())
        by_doc = _names_in_skill_md(render._TEMPLATES)
        orphans = [name for name in render._TEMPLATES
                   if name not in by_type and name not in by_doc]
        assert not orphans, (
            f"{orphans} exist in the registry but no --type maps to them and SKILL.md never "
            f"names them — unreachable by any documented path, which is how `dashboard` shipped")

    def test_the_guard_would_have_caught_dashboard(self):
        """The failure this file exists for, reconstructed: `dashboard` is in the registry, no
        `--type` reaches it, and SKILL.md does not name it."""
        by_type = set(publish_doc.PURPOSE_STYLE.values())
        assert "dashboard" not in by_type, (
            "if a --type now maps to dashboard, this reconstruction is stale — rewrite it "
            "against whichever style is style-only, or drop it")
        pretend_docs = _names_in_skill_md(render._TEMPLATES) - {"dashboard"}
        assert "dashboard" not in pretend_docs and "dashboard" in render._TEMPLATES

    def test_dashboard_is_reachable_today_only_because_the_doc_says_so(self):
        assert "dashboard" in _names_in_skill_md(render._TEMPLATES)


class TestTheDocumentedMappingMatchesTheCode:
    def test_every_type_row_names_the_template_it_resolves_to(self):
        """SKILL.md's `--type` table carries a Template column. A reader trusting it and getting
        a different template back is worse than no table at all."""
        text = SKILL_MD.read_text(encoding="utf-8")
        for purpose, style in publish_doc.PURPOSE_STYLE.items():
            row = re.search(rf"^\|\s*`{re.escape(purpose)}`\s*\|\s*`([a-z-]+)`\s*\|",
                            text, re.M)
            assert row, f"--type {purpose} has no row with a template column in SKILL.md"
            assert row.group(1) == style, (
                f"SKILL.md says --type {purpose} renders {row.group(1)}; the code says {style}")

    def test_every_documented_type_exists_in_the_code(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        for purpose in re.findall(r"^\|\s*`([a-z-]+)`\s*\|\s*`[a-z-]+`\s*\|", text, re.M):
            assert purpose in publish_doc.PURPOSE_STYLE, (
                f"SKILL.md documents --type {purpose}, which the code does not accept")
