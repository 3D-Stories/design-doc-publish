"""A real flow chart, not a wired tree (#76, `workflow`).

Owner, on the first rebuilt `workflow` page: *"dont you think a workflow diagram should have a
workflow diagram?"* The `nodes` block was an indented list. Wiring it with connectors and
arrowheads helped and was still not a flow chart — owner again, on that second attempt: it needs
**real boxes-and-arrows**, laid out the way the vendored `flowchart.html` does it.

Measured off that reference rather than imagined:

* `.flow` is a **flex column with `gap:0`** — the spacing is the connectors, not margins.
* `.node` is a centred box, `max-width:460px`.
* `.connector` is a `2px x 28px` rule BETWEEN nodes.
* Nodes come in kinds — `.proc`, `.dec`, `.term` — and branches are labelled `.ok` / `.no`.

Grammar: `kind | label | branch`, one row per node.

* `kind` is one of `term` (start or end), `proc` (a step), `dec` (a decision). Anything else warns
  and falls back, through the same `_semantic` path every other closed-set field uses.
* `branch` is optional and belongs to the connector arriving AT this node, which is where a flow
  chart writes "yes" / "no" — on the arrow, not in the box.

`n` nodes produce `n-1` connectors. That is the invariant most of these tests are pinning, because
an off-by-one there draws a line into nothing.
"""
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render  # noqa: E402
from render import blocks  # noqa: E402

DOC = """# T

```flow
term | A request arrives
proc | Validate the token
dec | Is the token valid?
proc | Serve the content | yes
term | Return 401 | no
```
"""


def _page(style="workflow", md=DOC):
    return render.render_artifact(md, title="T", style=style, generated_at="x")


class TestItDrawsBoxesAndArrows:
    def test_one_box_per_row(self):
        assert _page().count('<div class="blk-flow-node') == 5

    def test_connectors_sit_between_boxes_never_after_the_last(self):
        """`n` nodes, `n-1` connectors. A trailing connector draws an arrow into nothing."""
        assert _page().count('<div class="blk-flow-link') == 4

    # NOTE on every absence assertion below: they match the emitted MARKUP, not a bare class
    # name. The workflow stylesheet ships these class names on every page, so
    # `assert "blk-flow-link" not in page` can never fail and proves nothing. #68 documented
    # that trap and this file walked into it anyway on the first run.
    def test_a_single_node_has_no_connector_at_all(self):
        md = "# T\n\n```flow\nterm | Only one\n```\n"
        page = _page(md=md)
        assert page.count('<div class="blk-flow-node') == 1
        assert '<div class="blk-flow-link' not in page

    def test_each_kind_reaches_the_markup(self):
        page = _page()
        for kind in ("is-term", "is-proc", "is-dec"):
            assert kind in page, kind

    def test_every_label_renders(self):
        page = _page()
        for label in ("A request arrives", "Validate the token", "Is the token valid?",
                      "Serve the content", "Return 401"):
            assert label in page, label


class TestTheBranchLabelRidesOnTheArrow:
    def test_a_branch_label_lands_on_the_connector_not_in_the_box(self):
        page = _page()
        i = page.index("yes")
        # the label must fall inside a connector, so the nearest opening tag before it is a link
        before = page[:i]
        assert before.rfind("blk-flow-link") > before.rfind("blk-flow-node")

    def test_both_branches_render(self):
        page = _page()
        assert ">yes<" in page and ">no<" in page

    def test_a_row_with_no_branch_gets_a_bare_connector(self):
        md = "# T\n\n```flow\nterm | A\nproc | B\n```\n"
        page = _page(md=md)
        assert page.count('<div class="blk-flow-link') == 1
        assert '<span class="blk-flow-when' not in page

    def test_a_branch_on_the_FIRST_row_is_dropped_and_warned(self, capsys):
        """Nothing arrives at the first node, so there is no arrow to label."""
        md = "# T\n\n```flow\nterm | A | yes\nproc | B\n```\n"
        page = _page(md=md)
        assert '<span class="blk-flow-when' not in page
        assert "flow" in capsys.readouterr().err.lower()


class TestItFailsSafely:
    def test_an_unknown_kind_warns_and_falls_back(self, capsys):
        md = "# T\n\n```flow\nbanana | A\nproc | B\n```\n"
        page = _page(md=md)
        assert "A" in page, "the author's text still renders"
        assert "banana" in capsys.readouterr().err.lower()

    def test_an_empty_block_degrades_to_a_code_listing(self, capsys):
        md = "# T\n\n```flow\n\n```\n"
        page = _page(md=md)
        assert '<div class="blk-flow-node' not in page
        assert "flow" in capsys.readouterr().err.lower()

    def test_author_text_cannot_reach_a_class_attribute(self):
        md = '# T\n\n```flow\nproc"><b> | <script>x</script>\nproc | B | z"><i>\n```\n'
        page = _page(md=md)
        assert "<script>" not in page
        assert '"><b>' not in page and '"><i>' not in page

    def test_a_row_with_only_a_kind_still_renders_a_box(self):
        md = "# T\n\n```flow\nproc\nproc | B\n```\n"
        assert _page(md=md).count('<div class="blk-flow-node') == 2


class TestItIsScopedToWorkflow:
    def test_workflow_accepts_it(self):
        assert "flow" in blocks.DOC_TYPE_TAGS["workflow"]

    def test_it_is_registered(self):
        assert "flow" in blocks.BLOCK_TAGS and "flow" in blocks._RENDERERS

    def test_workflow_marks_it(self):
        assert "wf-flow" in _page()

    def test_a_style_that_does_not_accept_it_warns(self, capsys):
        _page(style="spec")
        assert "not accepted" in capsys.readouterr().err.lower()

    def test_plain_leaves_it_as_a_code_listing(self):
        page = _page(style="plain")
        assert '<div class="blk-flow-node' not in page
        assert "A request arrives" in page
