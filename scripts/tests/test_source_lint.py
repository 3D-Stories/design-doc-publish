"""Source-level checks: syntax the renderer does not implement, and status drift.

Both classes are measured, not hypothetical. On 2026-08-08 a live page shipped
`~~strikethrough~~` as six literal tilde characters, and — twice in a row — a milestone
was marked shipped on one surface while four sub-rows, a narrative section and a
cross-reference kept saying it was open.

Every check in the publish path at the time answered "did the bytes I linted reach the
page?", and every one of them answered correctly. Nobody was asking whether the source
said what its author meant. These tests pin that second question.

The `_UNSUPPORTED` table earns its rows by MEASUREMENT — each construct here was rendered
through the real engine and confirmed to survive as its own source characters. The class
at the bottom re-derives that from the live renderer, so a future release that starts
supporting one of them fails this suite rather than silently keeping a stale warning.
"""
import re
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render as render_artifact  # noqa: E402
from render import source_lint  # noqa: E402

UNSUPPORTED_SAMPLES = {
    "strikethrough": "This was ~~cancelled~~ instead.",
    "task list": "- [ ] an unchecked item",
    "autolink": "See <https://example.com/x> please.",
    "footnote": "A claim.[^1]",
    "highlight": "Marked ==important== here.",
    "subscript/superscript": "Water H~2~O boils.",
    "heading id": "### A heading {#custom-id}",
    "emoji shortcode": "Shipped :rocket: today.",
}


class TestUnsupportedSyntaxIsNamed:
    @pytest.mark.parametrize("name,sample", sorted(UNSUPPORTED_SAMPLES.items()))
    def test_each_construct_is_reported_with_its_line(self, name, sample):
        found = source_lint.check_unsupported_syntax(f"# Doc\n\n{sample}\n")
        assert any(name in f for f in found), f"{name} not reported for {sample!r}"
        assert any("line 3" in f for f in found), "the author's real line number is missing"

    def test_clean_prose_is_silent(self):
        md = ("# Doc\n\nOrdinary **bold**, _italic_, a [link](https://x.test), a list:\n\n"
              "- one\n- two\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
        assert source_lint.check_unsupported_syntax(md) == []

    @pytest.mark.parametrize("sample", sorted(UNSUPPORTED_SAMPLES.values()))
    def test_a_fenced_code_block_may_contain_anything(self, sample):
        # A document ABOUT markdown is the obvious false positive, and the one this
        # project writes constantly. Masking has to survive every construct, not most.
        assert source_lint.check_unsupported_syntax(f"# Doc\n\n```text\n{sample}\n```\n") == []

    @pytest.mark.parametrize("sample", sorted(UNSUPPORTED_SAMPLES.values()))
    def test_inline_code_may_contain_anything(self, sample):
        assert source_lint.check_unsupported_syntax(f"# Doc\n\nSee `{sample}` above.\n") == []

    def test_an_indented_code_block_is_masked(self):
        assert source_lint.check_unsupported_syntax("# Doc\n\n    - [ ] indented\n") == []

    def test_an_html_comment_is_masked(self):
        assert source_lint.check_unsupported_syntax("# Doc\n\n<!-- ~~note~~ -->\n") == []

    def test_masking_preserves_line_numbers(self):
        md = "# Doc\n\n```text\n~~a~~\n~~b~~\n```\n\nreal ~~leak~~ here\n"
        found = source_lint.check_unsupported_syntax(md)
        assert len(found) == 1 and "line 8" in found[0]

    def test_one_report_per_line_not_per_hit(self):
        found = source_lint.check_unsupported_syntax("# D\n\n~~a~~ and ~~b~~ and ~~c~~\n")
        assert len([f for f in found if "strikethrough" in f]) == 1

    def test_the_finding_quotes_the_offending_line(self):
        found = source_lint.check_unsupported_syntax("# D\n\nThis was ~~cancelled~~ ok.\n")
        assert "~~cancelled~~" in found[0]


class TestTheTableMatchesTheRealRenderer:
    """The table is only worth trusting if the engine still behaves this way.

    If a renderer upgrade starts supporting one of these, this test fails and the row
    must go — which is the point. A warning about a construct that now works is noise,
    and noise is what gets a gate switched off.
    """

    @pytest.mark.parametrize("name,sample", sorted(UNSUPPORTED_SAMPLES.items()))
    def test_the_construct_really_does_leak(self, name, sample):
        html = render_artifact.render_artifact(
            f"# Probe\n\n{sample}\n", title="Probe", style="plain", doc_id="d")
        body = html[html.find("<body"):]
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))
        marker = {
            "strikethrough": "~~cancelled~~", "task list": "[ ]",
            "autolink": "https://example.com/x", "footnote": "[^1]",
            "highlight": "==important==", "subscript/superscript": "~2~",
            "heading id": "{#custom-id}", "emoji shortcode": ":rocket:",
        }[name]
        assert marker in text, (
            f"{name} no longer leaks — the renderer may now support it. "
            f"Remove its row from _UNSUPPORTED rather than warning about it.")


class TestStatusDrift:
    PHASES = ("```phases\n"
              "M2.5 records | {phase} | {pstate}\n"
              "  #888 | schema guard | {c1}\n"
              "  #363 | writer path | {c2}\n"
              "```\n")

    def _doc(self, phase="3 of 16", pstate="warn", c1="note", c2="warn"):
        return "# Roadmap\n\n" + self.PHASES.format(
            phase=phase, pstate=pstate, c1=c1, c2=c2)

    def test_first_publication_has_nothing_to_compare(self):
        assert source_lint.check_status_drift("", self._doc()) == []

    def test_a_phase_marked_done_with_open_children_is_reported(self):
        found = source_lint.check_status_drift(
            self._doc(), self._doc(phase="16 of 16", pstate="done"))
        assert len(found) == 2
        assert all("reads as done" in f for f in found)
        assert any("#888" in f for f in found) and any("#363" in f for f in found)

    def test_a_complete_sweep_is_silent(self):
        assert source_lint.check_status_drift(
            self._doc(),
            self._doc(phase="16 of 16", pstate="done", c1="done", c2="done")) == []

    def test_an_open_phase_with_open_children_is_silent(self):
        assert source_lint.check_status_drift(self._doc(), self._doc()) == []

    def test_a_mention_elsewhere_still_reading_open_is_reported(self):
        old = "| #361 | move it | PROPOSED |\nSection M6 calls #361 a PROPOSED move.\n"
        new = "| #361 | move it | MERGED |\nSection M6 calls #361 a PROPOSED move.\n"
        found = source_lint.check_status_drift(old, new)
        assert len(found) == 1 and "#361" in found[0] and "line 2" in found[0]

    def test_an_already_done_subject_is_not_re_reported_forever(self):
        # Without the old-state half of the test, every republish of a finished document
        # would report every finished item, and the gate would be switched off within a
        # week. The subject must have CHANGED to done in this revision.
        done = "| #361 | move it | MERGED |\nSection M6 calls #361 a PROPOSED move.\n"
        assert source_lint.check_status_drift(done, done) == []

    def test_a_status_word_inside_code_is_not_a_status(self):
        old = "| #7 | x | OPEN |\n"
        new = "| #7 | x | SHIPPED |\n\n```bash\ngrep PROPOSED f  # $7 PENDING\n```\n"
        assert source_lint.check_status_drift(old, new) == []

    def test_the_finding_quotes_the_stale_line(self):
        found = source_lint.check_status_drift(
            self._doc(), self._doc(phase="16 of 16", pstate="done"))
        assert any("schema guard" in f for f in found)
