"""One current position per PAGE, not one per fence (#61, lane C).

A multi-stage runbook has one `steprail` fence per stage. Each fence was its own exclusive
`<details name=…>` group, so a three-stage page showed **three steps all looking current at
once** — and because closing the last open item in a group is allowed, it could equally show
none.

**Owner decision 2026-08-02: option 3 of the three the issue lists** — one group for the whole
document. It is the only one of the three that is both scriptless and yields a single position
page-wide, which keeps this engine's inline-script exception to `uat` alone and keeps the rail
working with JavaScript disabled. The issue asked for a browser trial before committing to it;
that trial is recorded in the PR.

**What this deliberately does NOT fix, because option 3 cannot.** There is no native "always
exactly one open" mode, so closing the last open step still leaves nothing highlighted. That
limitation is stated in the issue, was stated in the question the owner answered, and is not
quietly papered over here.

**Reversing a previous decision, on purpose.** `_next_id` existed to keep two rails in separate
groups, and its docstring called a shared `name` "exactly the bug a page-global script had".
That conflated two different things: the old bug was a *script* going stale across rails, while
a shared `<details name>` is native exclusive disclosure, where closing a sibling IS the defined
behaviour. The cost is real and the owner accepted it: opening a step in stage 3 collapses the
detail you were reading in stage 1.
"""
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render  # noqa: E402

TWO_STAGES = """# Runbook

## Stage one

```steprail
1 | Fetch the image | Pull from the registry. | action
2 | Verify the digest | Compare against the manifest. | check
```

## Stage two

```steprail
3 | Drain the node | Cordon first. | action
4 | Confirm it is empty | No pods left. | check
```
"""


def _page(md=TWO_STAGES, style="workflow"):
    return render.render_artifact(md, title="T", style=style, generated_at="x")


def _group_names(page):
    import re
    return re.findall(r'<details name="([^"]+)"', page)


class TestOneCurrentPositionPerPage:
    def test_two_rails_in_one_document_share_a_group(self):
        names = _group_names(_page())
        assert len(names) == 4, names
        assert len(set(names)) == 1, f"each stage still has its own group: {set(names)}"

    def test_exactly_one_step_starts_open(self):
        """Before this, EVERY stage opened its own first step — that is the defect the issue
        title names: 'several current rail steps at once'."""
        page = _page()
        assert page.count("<details") == 4
        assert page.count(" open>") == 1

    def test_the_open_one_is_the_first_step_of_the_first_stage(self):
        page = _page()
        assert page.index(" open>") < page.index("Drain the node")

    def test_a_single_rail_is_unchanged_in_behaviour(self):
        md = "# T\n\n```steprail\n1 | A | d | action\n2 | B | d | check\n```\n"
        page = _page(md=md)
        assert len(set(_group_names(page))) == 1
        assert page.count(" open>") == 1


class TestItStaysScriptless:
    def test_the_workflow_page_ships_no_script(self):
        """The engine's inline-script exception is `uat`'s alone, and option 3 was chosen
        precisely because it needs none."""
        assert "<script" not in _page()

    def test_the_rail_still_works_as_native_disclosure(self):
        page = _page()
        assert "<details name=" in page and "<summary>" in page


class TestPlainStaysFrozen:
    def test_plain_does_not_render_a_rail_at_all(self):
        """`plain` leaves a typed fence as a code listing, which is why an engine change to
        the rail cannot move the one style this epic freezes. Measured, not assumed."""
        page = _page(style="plain")
        assert "<details name=" not in page
        assert "Fetch the image" in page, "the author's text still renders"
