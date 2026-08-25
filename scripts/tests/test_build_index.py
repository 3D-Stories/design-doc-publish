"""`build_index.vercel_projects(scope=SCOPE)` — the strict JSON read of the Vercel project list (#125).

Why this file exists at all: `vercel_projects` had **no direct unit coverage**. It was exercised
only through `publish_doc.main()`, so the one function deciding whether stage 4 reuses a project
or refuses it — and refuses it by pointing the user at `--new-project`, which changes a published
doc's URL — was tested only incidentally.

The fixture `fixtures/vercel_project_ls.json` is REAL output from
`vercel project ls --format json --limit 100 --scope 3d-stories --no-color`
(Vercel CLI 56.5.0, captured on this host 2026-08-04: rc 0, 0 ESC bytes on stdout, banner on
stderr). Two deliberate deviations from the raw capture, both recorded here because a `.json`
fixture cannot carry a comment:

* the `projects` array is SUBSET to the same six names the retired table fixture carried, and
* `pagination` is made consistent with that subset (`count` 6, `prev` the newest row).

The subset is load-bearing, not tidiness. The live account has since gained
`example-design-12`, which `test_publish_doc.py` uses as its ABSENT project; shipping the
full 60-row capture would have made two reuse tests silently assert against a project that now
exists. Every row is otherwise verbatim, key order included.

The CLI is never invoked. `subprocess.run` is patched on its own module, which `build_index`
looks up at call time.
"""
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parent
FIXTURES = TESTS / "fixtures"
def _index_module():
    """Load `index/build_index.py` the way the rest of this suite does."""
    path = SCRIPTS.parent / "index" / "build_index.py"
    spec = importlib.util.spec_from_file_location("_test_build_index", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def index():
    return _index_module()



class TestDocumentLinksOpenInANewTab:
    """Owner request 2026-08-05: index links open a new tab by default.

    The whole correctness of this lives in the DISTINCTION, not the attribute. The page emits
    three kinds of anchor and only two of them are documents:

    * the group nav emits `href="#slug"` — an IN-PAGE jump to a section of this very page.
      Opening that in a new tab would break the index's own navigation and spawn a duplicate
      tab of the index itself, which is why a blanket "add target=_blank to every anchor"
      would be a regression rather than the feature.
    * `row_li()` and the "recent" list emit the document URLs. Those are what should leave.
    """

    STAMP = "2026-08-05 12:00 MDT"

    def _page(self):
        mod = _index_module()
        now = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
        rows = [
            {"name": "example-design-130", "url": "https://example-design-130.vercel.app",
             "title": "First read device", "group": "example", "chip": "design",
             "updated": datetime(2026, 8, 5, 6, 0, tzinfo=timezone.utc), "updated_src": "page"},
            {"name": "example-alpha-spike", "url": "https://example-alpha-spike.vercel.app",
             "title": "Alpha spike", "group": "example-team", "chip": "analysis",
             "updated": datetime(2026, 8, 4, 6, 0, tzinfo=timezone.utc), "updated_src": "deploy"},
        ]
        return mod.render(rows, self.STAMP, now, "sig")

    def _anchors(self, page):
        return re.findall(r"<a\b[^>]*>", page)

    def test_every_document_link_opens_a_new_tab(self):
        page = self._page()
        doc_anchors = [a for a in self._anchors(page) if 'href="https://' in a]
        assert doc_anchors, "no document links were rendered — the fixture is wrong"
        for a in doc_anchors:
            assert 'target="_blank"' in a, f"document link does not open a new tab: {a}"

    def test_every_document_link_carries_rel_noopener(self):
        """`target="_blank"` without it is the tabnabbing shape. Modern browsers imply
        noopener, older ones do not, and stating it costs nothing."""
        page = self._page()
        for a in self._anchors(page):
            if 'href="https://' in a:
                assert "noopener" in a, f"new-tab link without rel=noopener: {a}"

    def test_the_IN_PAGE_jump_links_do_NOT_open_a_new_tab(self):
        """The regression a blanket change would cause. These anchors target a section of
        this same page; a new tab would duplicate the index instead of navigating it."""
        page = self._page()
        jump = [a for a in self._anchors(page) if 'href="#' in a]
        assert jump, "the group nav rendered no in-page anchors — the fixture is wrong"
        for a in jump:
            assert "target=" not in a, f"an in-page jump link would open a new tab: {a}"
            assert "noopener" not in a, f"rel=noopener on an in-page link is meaningless: {a}"

    def test_both_document_lists_are_covered_not_just_one(self):
        """There are two independent emitters — `row_li()` and the "recent" list — and they
        were written separately. Fixing one and not the other is the likely half-done state,
        so the count is asserted rather than "at least one"."""
        page = self._page()
        # 2 rows in the grouped sections + 2 in the recent list = 4 document anchors.
        doc_anchors = [a for a in self._anchors(page) if 'href="https://' in a]
        assert len(doc_anchors) == 4, (
            f"expected 4 document links (2 grouped + 2 recent), got {len(doc_anchors)}")
        assert all('target="_blank"' in a for a in doc_anchors)


_AGE_STAMP = "2026-08-05 12:00 MDT"
_AGE_NOW = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
_AGE_DECLARED = datetime(2026, 8, 5, 6, 0, tzinfo=timezone.utc)    # 12h before _AGE_NOW
_AGE_DEPLOYED = datetime(2026, 8, 4, 6, 0, tzinfo=timezone.utc)    # 1d before _AGE_NOW


def _age_rows():
    return [
        {"name": "example-design-130", "url": "https://example-design-130.vercel.app",
         "title": "First read device", "group": "example", "chip": "design",
         "updated": _AGE_DECLARED, "updated_src": "page"},
        {"name": "example-alpha-spike", "url": "https://example-alpha-spike.vercel.app",
         "title": "Alpha spike", "group": "example-team", "chip": "analysis",
         "updated": _AGE_DEPLOYED, "updated_src": "deploy"},
        {"name": "example-no-stamp", "url": "https://example-no-stamp.vercel.app",
         "title": "No stamp anywhere", "group": "example", "chip": "plan",
         "updated": None, "updated_src": "none"},
    ]


def _age_page(index, now=None):
    return index.render(_age_rows(), _AGE_STAMP, now or _AGE_NOW, "sig")


def _when_spans(page):
    """(attributes, text) for every `when` cell on the page, in document order."""
    return re.findall(r'<span class="when([^"]*)"([^>]*)>([^<]*)</span>', page)


def _epoch_ms(dt):
    return str(int(dt.timestamp() * 1000))


class TestEachRowCarriesItsAbsoluteInstant:
    """AC1 — the machine-readable timestamp, emitted only where there IS one."""

    def test_the_attribute_is_the_rows_own_instant_in_epoch_milliseconds(self, index):
        page = _age_page(index)
        assert f'data-updated="{_epoch_ms(_AGE_DECLARED)}"' in page
        assert f'data-updated="{_epoch_ms(_AGE_DEPLOYED)}"' in page

    def test_both_emitters_carry_it_not_just_one(self, index):
        """`row_li()` and the "recent" strip are two independent `when()` call sites, written
        separately. Fixing one is the likely half-done state, so the count is asserted: 2
        grouped rows with a stamp + the same 2 in the recency strip."""
        page = _age_page(index)
        assert page.count("data-updated=") == 4

    def test_the_row_with_no_timestamp_carries_neither_new_attribute(self, index):
        """There is nothing to render an age from, so an attribute here would be a lie the
        script would then try to read."""
        page = _age_page(index)
        none_spans = [s for s in _when_spans(page) if "none" in s[0]]
        assert none_spans, "the no-timestamp row did not render — the fixture is wrong"
        for cls, attrs, text in none_spans:
            assert "data-updated" not in attrs, attrs
            assert "data-approx" not in attrs, attrs
            assert text == "—"

    def test_only_a_deploy_inferred_row_is_marked_approximate(self, index):
        """The `~` has to survive a client-side re-render, and reading it back out of the
        script's own previous output would be self-referential. So the marker is an attribute."""
        page = _age_page(index)
        assert page.count("data-approx=") == 2
        for cls, attrs, text in _when_spans(page):
            if "data-approx" in attrs:
                assert f'data-updated="{_epoch_ms(_AGE_DEPLOYED)}"' in attrs, attrs

    def test_the_build_time_string_is_still_the_elements_text(self, index):
        """AC4 — the no-JavaScript answer. A viewer with scripting off sees exactly the page
        that shipped before this change."""
        page = _age_page(index)
        texts = sorted({t for _, _, t in _when_spans(page)})
        assert texts == ["12h", "~1d", "—"]

    def test_the_hover_title_is_untouched(self, index):
        """AC3 — preserved, warts included: the exact timestamp and where the time came from."""
        page = _age_page(index)
        assert ('title="2026-08-05 06:00 America/Edmonton — declared by the page"') in page
        assert ('title="2026-08-04 06:00 America/Edmonton — inferred from the deploy '
                'age (coarse)"') in page
        assert 'title="no timestamp found"' in page


# The renderer is JavaScript and this suite is Python, so a test that merely asserted the script's
# source text would pass while the renderer was broken. `node` runs the real shipped bytes
# instead: `_AGE_JS` is fed to it verbatim, under a stub `document`, and its answers are compared
# against `_ago()`'s answers for the same instants. Running the fragment also proves it PARSES,
# which a source-text assertion cannot.
#
# `node` is not in `requirements-dev.txt`, so these skip when it is absent. Everything they cover
# except the JS itself is covered by the markup class above and by the live browser check recorded
# in the PR.

NODE = shutil.which("node")
# The skip reason names the CONSEQUENCE, because a bare "node is absent" understates it: with these
# tests skipped, a syntactically broken script ships and takes the filter and the auto-refresh down
# with the ages (cross-model review finding, 2026-08-14). `requirements-dev.txt` records the same
# thing where the gate's dependencies are declared. Two guards do run without node — the brace-
# artifact check below, and every markup test, which fail loudly on a render-time error.
needs_node = pytest.mark.skipif(
    NODE is None,
    reason="node is absent, so the SHIPPED client-side renderer is not executed by this run — "
           "install node to close that gap (see requirements-dev.txt)")

# A stub `document` is all the fragment touches. `NODES` and `NOW` are defined by each caller.
#
# `Date` is stubbed too, deliberately: the wiring tests below assert the exact text a cell ends up
# with, and reading the real wall clock would make those answers depend on the day the suite runs.
_JS_STUBS = """
var document = {hidden: false,
                querySelectorAll: function(){ return NODES; },
                addEventListener: function(){}};
var setInterval = function(){};
var Date = {now: function(){ return NOW; }};
"""

_JS_ELEMENT = """
function El(updated, approx, text){
  this.a = {};
  if (updated !== null) this.a['data-updated'] = updated;
  if (approx) this.a['data-approx'] = '1';
  this.textContent = text;
}
El.prototype.getAttribute = function(k){ return (k in this.a) ? this.a[k] : null; };
El.prototype.hasAttribute = function(k){ return (k in this.a); };
"""


def _run_node(script):
    done = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, f"node exited {done.returncode}: {done.stderr}"
    return done.stdout


# Every cutoff in `_ago`, both sides of it, plus a future instant (its `max(0, …)` clamp).
_AGE_DELTAS = [0, 59, 60, 61, 3599, 3600, 3601, 2400, 86399, 86400, 86401,
               3 * 86400, 604799, 604800, 604801, 14 * 86400, 60 * 86400, -90]


class TestTheClientRendererMatchesAgo:
    """AC3 — "the client-side format matches `_ago()`'s vocabulary". Proven by running both."""

    @needs_node
    def test_every_cutoff_answers_exactly_what_ago_answers(self, index):
        now = _AGE_NOW
        now_ms = int(now.timestamp() * 1000)
        expected = [index._ago(now - timedelta(seconds=d), now) for d in _AGE_DELTAS]
        cases = json.dumps([now_ms - d * 1000 for d in _AGE_DELTAS])
        out = _run_node(
            f"var NODES = [];\nvar NOW = {now_ms};\n" + _JS_STUBS + index._AGE_JS
            + f"\nvar cases = {cases};\nvar now = {now_ms};\n"
            + "process.stdout.write(JSON.stringify(cases.map(function(t)"
              "{ return ago(t, now); })));")
        assert json.loads(out) == expected

    @needs_node
    def test_the_fragment_parses_and_installs_nothing_when_no_row_has_a_time(self, index):
        """`ages.length === 0` must install no timer at all. The stub counts installations rather
        than trusting that a missing guard would announce itself."""
        out = _run_node("var NODES = [];\nvar NOW = 0;\n" + _JS_STUBS.replace(
            "var setInterval = function(){};",
            "var installed = 0; var setInterval = function(){ installed++; };")
            + index._AGE_JS + "\nprocess.stdout.write(String(installed));")
        assert out == "0"


class TestTheClientRendererRewritesTheCell:
    """AC2 — the cell is re-rendered from the attribute, and the `~` survives it."""

    @needs_node
    def test_each_cell_is_rewritten_from_its_own_attribute(self, index):
        """Exact expected text, computed from `_ago()` against a STUBBED clock two days past the
        fixture. An earlier revision of this test read node's real clock and could only assert
        "something changed", which would have passed while only one of the two cells was being
        rewritten (own review finding, 2026-08-14)."""
        stamped = _AGE_NOW - timedelta(hours=12)
        marked = _AGE_NOW - timedelta(hours=24)
        viewing = _AGE_NOW + timedelta(days=2)                     # the reader arrives 2 days on
        now_ms = int(viewing.timestamp() * 1000)
        nodes = (f"var NODES = [new El('{int(stamped.timestamp() * 1000)}', false, '12h'),"
                 f" new El('{int(marked.timestamp() * 1000)}', true, '~1d'),"
                 f" new El(null, false, '—'),"
                 f" new El('not-a-number', false, '9h')];")
        out = _run_node(
            _JS_ELEMENT + nodes + f"var NOW = {now_ms};" + _JS_STUBS + index._AGE_JS
            + "\nprocess.stdout.write(JSON.stringify(NODES.map(function(n)"
              "{ return n.textContent; })));")
        assert json.loads(out) == [
            index._ago(stamped, viewing),                          # re-rendered, no marker
            "~" + index._ago(marked, viewing),                     # re-rendered, marker kept
            "—",                                                   # no attribute: untouched
            "9h",                                                  # unreadable attribute: untouched
        ]

    @needs_node
    def test_a_page_with_rows_installs_a_sixty_second_timer(self, index):
        """AC2's "~60s timer", pinned by the period actually handed to `setInterval` rather than
        by reading it out of the source. The sibling test above pins the other half: a page with
        no dated row installs nothing at all."""
        now_ms = int(_AGE_NOW.timestamp() * 1000)
        out = _run_node(
            _JS_ELEMENT + f"var NODES = [new El('{now_ms}', false, '1m')];"
            + f"var NOW = {now_ms};"
            + _JS_STUBS.replace("var setInterval = function(){};",
                                "var period = -1;"
                                " var setInterval = function(f, ms){ period = ms; };")
            + index._AGE_JS + "\nprocess.stdout.write(String(period));")
        assert out == "60000"

    @needs_node
    def test_an_attribute_that_is_only_PARTLY_numeric_keeps_the_build_time_text(self, index):
        """`parseInt` takes a numeric PREFIX, so `<epoch>-corrupt` passed the first version of
        this guard and overwrote the fallback with an age — the opposite of what the code claimed
        (cross-model review finding, 2026-08-14). `17e9` is the same class: it became epoch 17ms,
        which renders as an age of decades. A value outside `_instant()`'s bounds goes the same
        way. Every one of these must leave the cell exactly as it shipped."""
        now_ms = int(_AGE_NOW.timestamp() * 1000)
        bad = [f"{now_ms}-corrupt", "17e9", f"  {now_ms}  ", "99999999999999999999",
               "not-a-number", "1786757518797abc", "0"]
        nodes = ("var NODES = ["
                 + ", ".join(f"new El({v!r}, false, 'KEEP')" for v in bad) + "];")
        out = _run_node(
            _JS_ELEMENT + nodes + f"var NOW = {now_ms};" + _JS_STUBS + index._AGE_JS
            + "\nprocess.stdout.write(JSON.stringify(NODES.map(function(n)"
              "{ return n.textContent; })));")
        assert json.loads(out) == ["KEEP"] * len(bad)

    @needs_node
    def test_a_hidden_tab_is_not_re_rendered_until_it_is_looked_at(self, index):
        """It matches the poll beside it, which also returns early on `document.hidden`. The
        `visibilitychange` handler is what makes this safe rather than lossy."""
        now_ms = int(_AGE_NOW.timestamp() * 1000)
        out = _run_node(
            _JS_ELEMENT + f"var NODES = [new El('{now_ms - 9 * 3600 * 1000}', false, 'PRISTINE')];"
            + f"var NOW = {now_ms};"
            + _JS_STUBS.replace("hidden: false", "hidden: true") + index._AGE_JS
            + "\nprocess.stdout.write(NODES[0].textContent);")
        assert out == "PRISTINE"


class TestTheRendererShipsInsideThePage:
    """The constant has to actually reach the page, once, without disturbing the poll."""

    def test_the_renderer_is_interpolated_verbatim_exactly_once(self, index):
        page = _age_page(index)
        assert page.count(index._AGE_JS.strip()) == 1

    def test_the_signature_poll_is_still_there(self, index):
        """The issue named this trap: the new timer must not fight the auto-refresh reload."""
        page = _age_page(index)
        assert "setInterval(check, 90000)" in page
        assert 'meta[name="index-signature"]' in page
        assert page.count("<script>") == 1, "the renderer must extend the existing block"

    @needs_node
    def test_the_whole_shipped_script_still_parses(self, index, tmp_path):
        """The page template is one big f-string, so a single mis-doubled brace anywhere in this
        block ships a page whose script dies on its first statement — and every feature in it,
        the filter and the auto-refresh included, dies with it. `node --check` is the cheap proof,
        and it covers the whole block rather than only the part this change added."""
        page = _age_page(index)
        block = re.search(r"<script>\n(.*?)\n</script>", page, re.S)
        assert block, "no script block was rendered"
        js = tmp_path / "index-script.js"
        js.write_text(block.group(1), encoding="utf-8")
        done = subprocess.run([NODE, "--check", str(js)], capture_output=True, text=True,
                              timeout=30)
        assert done.returncode == 0, done.stderr

    def test_no_f_string_brace_artifact_reaches_the_page(self, index):
        """Runs WITHOUT node, deliberately, and that is the whole point: the `node --check` test
        above SKIPS on a host with no node, and a broken script takes the filter and the
        auto-refresh down with it, not only the ages (cross-model review finding, 2026-08-14).

        The template is an f-string, so its own JS must double every brace. A single missing
        double raises at render time and fails every test in this file. A doubled DOUBLE emits a
        literal `{{` into the page instead, and only a JS parser would notice — so it is checked
        here, in Python. `_AGE_JS` is excluded because it is interpolated verbatim and therefore
        needs no doubling, so a legitimate `}}` inside it is not an artifact."""
        page = _age_page(index)
        block = re.search(r"<script>\n(.*?)\n</script>", page, re.S)
        assert block, "no script block was rendered"
        authored = block.group(1).replace(index._AGE_JS.strip(), "")
        assert "{{" not in authored, "an f-string brace artifact reached the page"
        assert "}}" not in authored, "an f-string brace artifact reached the page"

    def test_the_renderer_makes_no_request_and_writes_no_markup(self, index):
        """AC2's constraint, and the reason `textContent` is used rather than `innerHTML`."""
        js = index._AGE_JS
        for banned in ("http", "fetch(", "XMLHttpRequest", "innerHTML", "import ", "src="):
            assert banned not in js, f"the age renderer must not contain {banned!r}"

    def test_it_stays_in_the_files_es5_idiom(self, index):
        """The rest of this script is deliberately ES5 (`var`, `Array.prototype.slice.call`).
        A page served to unknown browsers is the wrong place to raise the floor casually."""
        js = index._AGE_JS
        for modern in ("Number.isFinite", ".dataset", "=>", "const ", "let "):
            assert modern not in js, f"the age renderer must not use {modern!r}"


class TestTheEpochAttributeDoesNotMoveTheChangeSignature:
    """AC5, and it is a REGRESSION PIN rather than a fix: `signature()` hashes rows and never
    markup, so the new attribute cannot reach it today. The pin matters because
    `refresh_index.sh` diffs that signature to decide whether a redeploy is warranted, and #125
    already lost this once — the coarse age token was derived from `now`, so it moved on every
    single build and made every build look like a change.

    The mistake these tests exist to catch is a future author stamping `data-updated` from `now`
    instead of from the row's own instant. Both halves are asserted: the value must not move when
    only the clock moves, and it must move when something real does.
    """

    def test_the_signature_hashes_rows_only_and_no_part_of_the_markup(self, index):
        """Pinned by VALUE against a canon line rebuilt here from the four fields it is allowed
        to contain. Adding the epoch attribute — or anything else rendered — fails this."""
        rows = _age_rows()
        canon = "\n".join(sorted(
            f'{r["name"]}\t{r["title"]}\t'
            f'{r["updated"].isoformat() if r["updated"] else "-"}\t{r["updated_src"]}'
            for r in rows))
        assert index.signature(rows) == hashlib.sha256(canon.encode()).hexdigest()

    def test_the_attribute_does_not_move_when_only_the_clock_moves(self, index):
        """The teeth. Stamping the attribute from `now` would pass every other test in this file
        and fail this one."""
        early = _age_page(index, now=_AGE_NOW)
        late = _age_page(index, now=_AGE_NOW + timedelta(days=2))
        assert (re.findall(r'data-updated="(\d+)"', early)
                == re.findall(r'data-updated="(\d+)"', late))
        assert early != late, "the age text did not move either, so this proves nothing"

    def test_the_signature_still_moves_when_something_real_changes(self, index):
        """A change-detector that never fires is as useless as one that always does."""
        rows = _age_rows()
        retitled = _age_rows()
        retitled[0]["title"] = "First read device, revised"
        assert index.signature(retitled) != index.signature(rows)


# --- `eyebrow`, added for the doc-harness (#34) -------------------------------------------
#
# The harness serves this same page from its own registry, where "vercel" is simply wrong.
# The parameter is keyword-only and defaults to today's exact string, so every existing
# caller and every existing test above is unaffected — which is the whole reason the
# harness takes a parameter here rather than post-processing the rendered HTML.

def _render_with(**kwargs):
    bi = _load()
    from datetime import datetime, timezone
    now = datetime(2026, 8, 24, 4, 0, 0, tzinfo=timezone.utc)
    rows = [{"name": "proj-design-1", "url": "https://example.test",
             "title": "A doc", "group": "proj", "chip": "design",
             "updated": now, "updated_src": "page"}]
    return bi.render(rows, "2026-08-24", now, bi.signature(rows), **kwargs)


def test_render_without_an_eyebrow_defaults_vendor_free():
    assert "living documentation" in _render_with()
    assert "vercel" not in _render_with().lower()


def test_render_with_a_scope_prefixes_the_tenant():
    assert "acme · living documentation" in _render_with(scope="acme")


def test_an_explicit_eyebrow_replaces_the_default_entirely():
    out = _render_with(eyebrow="3dstories · living documentation")
    assert "3dstories · living documentation" in out
    assert "vercel · living documentation" not in out


def test_an_explicit_eyebrow_is_escaped():
    out = _render_with(eyebrow="<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out


def _load():
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location(
        "build_index_eyebrow", "index/build_index.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_index_eyebrow"] = mod
    spec.loader.exec_module(mod)
    return mod
