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
import importlib.util
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parent
FIXTURES = TESTS / "fixtures"
LS_JSON = (FIXTURES / "vercel_project_ls.json").read_text(encoding="utf-8")

# The retired table capture, still on disk, still real. It is the single most likely thing to
# arrive on stdout if a CLI upgrade drops `--format json`, so it is what the no-fallback and
# not-JSON tests feed.
LS_TABLE = (FIXTURES / "vercel_project_ls.txt").read_text(encoding="utf-8")

# #9: the team is configuration now, not a constant, so every test states the one it means.
# The recorded fixtures carry the same neutral value — code and fixture pin each other, and
# #4 measured 80 failures from moving one of them alone.
SCOPE = "example-team"

EXPECTED = ["example-alpha-spike", "example-analysis-412",
            "example-plan-786", "example-design-templates",
            "example-uat-checklist"]


def _index_module():
    """Load `index/build_index.py` the way the rest of this suite does."""
    path = SCRIPTS.parent / "index" / "build_index.py"
    spec = importlib.util.spec_from_file_location("_test_build_index", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeCLI:
    """Stands in for `subprocess.run`, recording argv and the child environment."""

    def __init__(self, stdout="", stderr="", rc=0, raises=None, pages=None):
        self.stdout, self.stderr, self.rc, self.raises = stdout, stderr, rc, raises
        self.cmd = None
        self.kw = None
        # #171: `pages` serves a different payload per call, so the pagination loop can be
        # driven. Additive — every existing test passes `stdout` and sees the old behaviour,
        # and `cmd`/`kw` still hold the LAST call exactly as before.
        self.pages = list(pages) if pages else None
        self.cmds = []

    def __call__(self, cmd, **kw):
        self.cmd, self.kw = list(cmd), kw
        self.cmds.append(list(cmd))
        if self.raises:
            raise self.raises
        out = self.pages.pop(0) if self.pages else self.stdout
        return subprocess.CompletedProcess(self.cmd, self.rc, out, self.stderr)


@pytest.fixture
def index():
    return _index_module()


@pytest.fixture
def cli(monkeypatch):
    def install(**kw):
        fake = FakeCLI(**kw)
        monkeypatch.setattr(subprocess, "run", fake)
        return fake
    return install


def _payload(projects, **envelope):
    """A CLI-shaped response document carrying `projects`."""
    doc = {"projects": projects,
           "pagination": {"count": len(projects), "next": None, "prev": 1},
           "contextName": SCOPE, "elapsed": "12ms"}
    doc.update(envelope)
    return json.dumps(doc)


def _row(name, updated=1785613860253, **extra):
    row = {"name": name, "id": "prj_x",
           "latestProductionUrl": f"https://{name}.vercel.app",
           "updatedAt": updated, "nodeVersion": "24.x", "deprecated": False}
    row.update(extra)
    return row


# --------------------------------------------------------------- the happy path (AC1/AC2)

class TestTheCapturedListingParsesCleanly:
    def test_the_names_are_exactly_the_real_ones_minus_the_index_itself(self, index, cli):
        cli(stdout=LS_JSON)
        assert [p["name"] for p in index.vercel_projects(scope=SCOPE)] == EXPECTED

    def test_no_name_carries_a_control_byte(self, index, cli):
        """The #125 symptom, stated as an invariant rather than a strip: a project name is a
        project name. `\\x1b[1mthewanderinginn-design-11\\x1b[22m` was never one."""
        cli(stdout=LS_JSON)
        for p in index.vercel_projects(scope=SCOPE):
            assert not any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in p["name"]), p

    def test_the_self_project_is_filtered(self, index, cli):
        cli(stdout=LS_JSON)
        assert "docs-index" not in [p["name"] for p in index.vercel_projects(scope=SCOPE)]
        assert index.SELF_PROJECT == "docs-index"

    def test_updated_at_becomes_an_absolute_timezone_aware_instant(self, index, cli):
        cli(stdout=LS_JSON)
        got = {p["name"]: p["deployed"] for p in index.vercel_projects(scope=SCOPE)}
        one = got["example-plan-786"]
        assert one.tzinfo is not None
        # 1785567949474 ms, read from the fixture's own row.
        assert one == datetime.fromtimestamp(1785567949474 / 1000, tz=timezone.utc).astimezone(
            one.tzinfo)

    def test_the_same_listing_yields_the_same_instants_every_build(self, index, cli):
        """`_parse_age` derived `now - "3h"`, so the value moved on every build and had to be
        excluded from the change signature. An absolute `updatedAt` does not move."""
        cli(stdout=LS_JSON)
        first = [p["deployed"] for p in index.vercel_projects(scope=SCOPE)]
        cli(stdout=LS_JSON)
        assert [p["deployed"] for p in index.vercel_projects(scope=SCOPE)] == first

    def test_the_row_signature_is_stable_across_builds(self, index, cli, tmp_path):
        ws = tmp_path / "workspace.json"
        ws.write_text(json.dumps({"projects": [{"name": "example"}]}), encoding="utf-8")
        cli(stdout=LS_JSON)
        a = index.signature(index.build_rows(index.vercel_projects(scope=SCOPE), ["example"], False))
        cli(stdout=LS_JSON)
        b = index.signature(index.build_rows(index.vercel_projects(scope=SCOPE), ["example"], False))
        assert a == b


# --------------------------------------------------------------- how it is invoked (AC5)

class TestTheInvocation:
    def test_it_asks_for_json_pins_the_scope_and_disables_colour(self, index, cli):
        fake = cli(stdout=LS_JSON)
        index.vercel_projects(100, scope=SCOPE)
        assert fake.cmd[:3] == ["vercel", "project", "ls"]
        assert "--format" in fake.cmd and fake.cmd[fake.cmd.index("--format") + 1] == "json"
        assert fake.cmd[fake.cmd.index("--limit") + 1] == "100"
        assert fake.cmd[fake.cmd.index("--scope") + 1] == SCOPE
        assert "--no-color" in fake.cmd

    def test_the_child_environment_is_scrubbed_of_forced_colour(self, index, cli, monkeypatch):
        """Hygiene, not the guarantee — but `FORCE_COLOR` in the environment is what made the
        original defect reproducible, so it must not reach the child."""
        monkeypatch.setenv("FORCE_COLOR", "1")
        fake = cli(stdout=LS_JSON)
        index.vercel_projects(scope=SCOPE)
        env = fake.kw["env"]
        assert "FORCE_COLOR" not in env
        assert env["NO_COLOR"] == "1"
        # The rest of the environment survives, or the CLI loses its PATH and its credentials.
        assert env.get("PATH") == os.environ.get("PATH")


# --------------------------------------------------------------- fail closed

class TestItFailsClosedRatherThanGuessing:
    def test_a_table_on_stdout_is_refused_and_the_diagnostic_names_an_upgrade(self, index, cli):
        cli(stdout=LS_TABLE)
        with pytest.raises(SystemExit) as e:
            index.vercel_projects(scope=SCOPE)
        msg = str(e.value)
        assert "json" in msg.lower()
        assert "upgrade" in msg.lower()

    def test_a_perfectly_good_table_on_stderr_is_not_a_fallback(self, index, cli):
        """The owner's decision, pinned: a fallback duplicates the fragile parsing and would
        mask exactly the upgrade regression that should stop publication."""
        cli(stdout="", stderr=LS_TABLE)
        with pytest.raises(SystemExit):
            index.vercel_projects(scope=SCOPE)

    def test_an_ansi_wrapped_payload_is_refused(self, index, cli):
        """Colour around the whole document is not JSON at all."""
        cli(stdout="\x1b[1m" + LS_JSON + "\x1b[22m")
        with pytest.raises(SystemExit):
            index.vercel_projects(scope=SCOPE)

    def test_a_coloured_name_inside_valid_json_is_refused_not_accepted(self, index, cli):
        """The nastier shape, and the reason the name check is not merely a JSON parse: escape
        bytes inside a JSON *string* keep the document valid, so `json.loads` alone would hand
        back `\\x1b[1mexample-plan-786\\x1b[22m` as a project name and reproduce #125 in
        JSON clothing."""
        cli(stdout=_payload([_row("\x1b[1mexample-plan-786\x1b[22m")]))
        with pytest.raises(SystemExit):
            index.vercel_projects(scope=SCOPE)

    def test_a_bare_array_is_refused(self, index, cli):
        cli(stdout=json.dumps([_row("a-project")]))
        with pytest.raises(SystemExit):
            index.vercel_projects(scope=SCOPE)

    def test_a_missing_projects_key_is_refused(self, index, cli):
        cli(stdout=json.dumps({"pagination": {"count": 0}, "contextName": "3d-stories"}))
        with pytest.raises(SystemExit):
            index.vercel_projects(scope=SCOPE)

    def test_a_row_that_is_not_an_object_is_refused(self, index, cli):
        cli(stdout=_payload(["example-plan-786"]))
        with pytest.raises(SystemExit):
            index.vercel_projects(scope=SCOPE)

    @pytest.mark.parametrize("bad", [{}, {"name": ""}, {"name": None}, {"name": 7}])
    def test_a_row_without_a_usable_name_is_refused(self, index, cli, bad):
        row = _row("fine")
        row.pop("name")
        row.update(bad)
        cli(stdout=_payload([row]))
        with pytest.raises(SystemExit):
            index.vercel_projects(scope=SCOPE)

    @pytest.mark.parametrize("name", [
        "[1mexample-plan-786",      # C1 CSI: one codepoint, same effect as ESC-[
        "example​plan-786",          # zero-width space, a format character
        "   ",                                  # printable, but not a name
        " example-plan-786 ",             # padded: would not match the real project
    ])
    def test_a_name_that_is_not_plainly_printable_is_refused(self, index, cli, name):
        """A hand-rolled `ord(ch) < 0x20 or == 0x7F` check covered only C0 and DEL and let all
        four of these through. Cross-model review caught it; `str.isprintable()` plus a strip
        comparison is both shorter and correct."""
        cli(stdout=_payload([_row(name)]))
        with pytest.raises(SystemExit):
            index.vercel_projects(scope=SCOPE)

    def test_a_listing_answered_for_another_tenant_is_refused(self, index, cli):
        """`--scope` only ASKS for an account. The payload says which one it answered for, and
        checking it is what turns the pin into a guarantee — a listing for the wrong account
        would present every genuinely live project as absent."""
        cli(stdout=_payload([_row("example-plan-786")], contextName="someone-else"))
        with pytest.raises(SystemExit) as e:
            index.vercel_projects(scope=SCOPE)
        assert "someone-else" in str(e.value) and SCOPE in str(e.value)

    def test_a_listing_with_no_tenant_named_is_refused(self, index, cli):
        doc = json.loads(_payload([_row("example-plan-786")]))
        doc.pop("contextName")
        cli(stdout=json.dumps(doc))
        with pytest.raises(SystemExit):
            index.vercel_projects(scope=SCOPE)

    def test_a_further_page_is_followed_rather_than_refused(self, index, cli):
        """**This assertion was inverted by #171, deliberately — read why before changing it.**

        It used to require a SystemExit whenever `pagination.next` was set, and that was correct
        while there was no loop: a partial listing makes live projects look absent, which is
        #125's failure, and stage 4 answers an absent project by minting a duplicate under a new
        URL. Refusing was the safe half of a choice with no good option.

        It became the bug on 2026-08-10, when the account crossed 100 projects. Stage 7 of every
        publish in every project began failing, and the diagnostic told the operator to "re-run
        with a higher --limit" — advice the hardcoded `limit=100` default made impossible to
        take. The index could not be rebuilt at all.

        The guarantee is unchanged and now held exactly rather than approximately: no partial
        listing is ever returned. A cursor followed to exhaustion IS the complete account.
        """
        first = json.loads(_payload([_row("example-plan-786")]))
        first["pagination"]["next"] = 1785866993550
        got = None
        fake = cli(pages=[json.dumps(first), _payload([_row("second-page-project")])])
        got = index.vercel_projects(100, scope=SCOPE)
        assert [p["name"] for p in got] == ["example-plan-786", "second-page-project"], \
            "both pages must appear; the second one used to be invisible"
        assert len(fake.cmds) == 2, "the cursor must be followed, not refused"
        assert "--next" in fake.cmds[1], "the second call must carry the cursor"
        assert fake.cmds[1][fake.cmds[1].index("--next") + 1] == "1785866993550"
        assert "--next" not in fake.cmds[0], "the first call has no cursor to pass"

    def test_pages_are_followed_until_the_cursor_clears(self, index, cli):
        a = json.loads(_payload([_row("p1")])); a["pagination"]["next"] = 11
        b = json.loads(_payload([_row("p2")])); b["pagination"]["next"] = 22
        fake = cli(pages=[json.dumps(a), json.dumps(b), _payload([_row("p3")])])
        assert [p["name"] for p in index.vercel_projects(100, scope=SCOPE)] == ["p1", "p2", "p3"]
        assert len(fake.cmds) == 3

    def test_a_row_repeated_across_a_page_boundary_is_counted_once(self, index, cli):
        """A boundary that shifts while paging can repeat a row. That is not corruption, but
        counting it twice would put the same project in the index twice."""
        a = json.loads(_payload([_row("p1"), _row("dupe")])); a["pagination"]["next"] = 11
        got = index.vercel_projects(100, scope=SCOPE) if cli(
            pages=[json.dumps(a), _payload([_row("dupe"), _row("p2")])]) else None
        assert [p["name"] for p in got] == ["p1", "dupe", "p2"]

    def test_a_cursor_that_never_clears_fails_loudly_instead_of_looping_forever(self, index, cli):
        """The backstop. Not reachable through the CLI as it behaves today, which is exactly
        why it is asserted: the failure it prevents is unbounded subprocess spawning."""
        stuck = json.loads(_payload([_row("p1")]))
        stuck["pagination"]["next"] = 99
        cli(pages=[json.dumps(stuck)] * (index._MAX_PAGES + 2))
        with pytest.raises(SystemExit) as e:
            index.vercel_projects(100, scope=SCOPE)
        assert "paginating" in str(e.value)

    def test_a_payload_with_no_pagination_cursor_is_refused(self, index, cli):
        doc = json.loads(_payload([_row("example-plan-786")]))
        doc.pop("pagination")
        cli(stdout=json.dumps(doc))
        with pytest.raises(SystemExit):
            index.vercel_projects(scope=SCOPE)

    def test_zero_projects_is_refused_rather_than_rendering_an_empty_index(self, index, cli):
        cli(stdout=_payload([]))
        with pytest.raises(SystemExit) as e:
            index.vercel_projects(scope=SCOPE)
        assert "empty index" in str(e.value)

    def test_a_full_page_with_no_cursor_is_complete_not_truncated(self, index, cli):
        """**The length heuristic was REMOVED by #171. This test replaces it, inverted.**

        It used to require a SystemExit when the row count reached `--limit`, because a full page
        was the only evidence of truncation available without a loop. Under the loop a full page
        is the ordinary case — it means "fetch the next one" — so keeping that check would refuse
        every account at or over 100 projects, which is precisely the outage being fixed.

        What replaces it is not a weaker check but a stronger one. This file already called
        `pagination.next` authoritative "where a row count is only a heuristic", and completeness
        is now proven by exhausting that cursor rather than by counting rows. The fixture holds
        six rows and a null cursor, so six rows at `--limit 6` is a COMPLETE account.
        """
        cli(stdout=LS_JSON)
        got = index.vercel_projects(6, scope=SCOPE)
        assert got, "a full final page is a complete listing, not a truncated one"
        assert "docs-index" not in [p["name"] for p in got]

    def test_a_short_page_with_a_cursor_is_still_followed(self, index, cli):
        """The hole the old row count could never see: a server-side cap BELOW the requested
        limit. One row at `--limit 100` used to read as the whole account. It is now followed."""
        short = json.loads(_payload([_row("p1")]))
        short["pagination"]["next"] = 77
        fake = cli(pages=[json.dumps(short), _payload([_row("p2")])])
        assert [p["name"] for p in index.vercel_projects(100, scope=SCOPE)] == ["p1", "p2"]
        assert len(fake.cmds) == 2

    def test_a_cli_failure_is_a_loud_exit_carrying_both_streams(self, index, cli):
        cli(stdout="partial", stderr="Error: not authorised", rc=1)
        with pytest.raises(SystemExit) as e:
            index.vercel_projects(scope=SCOPE)
        assert "not authorised" in str(e.value)


# --------------------------------------------------------------- the degrade, deliberately

class TestOnlyTheAgeDegrades:
    """A wrong NAME makes stage 4 refuse a live project and steers the user to
    `--new-project`, which changes a published doc's URL. A missing age renders one `—` cell.
    The old table parser kept its age group optional for exactly this reason; that contract
    survives the move to JSON, and it is the one field that does not fail closed."""

    @pytest.mark.parametrize("bad", [None, "3h", "", -1, 0, True, {}, [], float("nan")])
    def test_an_unusable_updated_at_keeps_the_row_and_drops_the_age(self, index, cli, bad):
        cli(stdout=_payload([_row("example-plan-786", updated=bad)]))
        rows = index.vercel_projects(scope=SCOPE)
        assert [p["name"] for p in rows] == ["example-plan-786"]
        assert rows[0]["deployed"] is None

    def test_a_missing_updated_at_key_keeps_the_row(self, index, cli):
        row = _row("example-plan-786")
        row.pop("updatedAt")
        cli(stdout=_payload([row]))
        rows = index.vercel_projects(scope=SCOPE)
        assert rows[0]["deployed"] is None

    def test_a_timestamp_in_the_wrong_unit_degrades_instead_of_reading_as_1970(self, index, cli):
        """Epoch SECONDS divided by 1000 lands in January 1970 and would then be both displayed
        and hashed into the change signature as though it were real. A magnitude window turns a
        unit change into a missing age rather than a confident wrong date."""
        cli(stdout=_payload([_row("example-plan-786", updated=1785613860)]))
        rows = index.vercel_projects(scope=SCOPE)
        assert [p["name"] for p in rows] == ["example-plan-786"]
        assert rows[0]["deployed"] is None

    def test_a_row_with_no_age_renders_an_em_dash_rather_than_vanishing(self, index, cli):
        row = _row("example-plan-786")
        row.pop("updatedAt")
        cli(stdout=_payload([row]))
        built = index.build_rows(index.vercel_projects(scope=SCOPE), ["example"], False)
        assert built[0]["updated_src"] == "none"


# --------------------------------------------------------------- a declined "fix", pinned

class TestTheBootstrapAccountStillPublishes:
    """Two independent cross-model reviewers recommended moving the empty-list refusal to AFTER
    the `SELF_PROJECT` filter, on the grounds that a payload of only `docs-index` returns an
    empty list while the diagnostic says an empty index is refused.

    That recommendation was declined, because it breaks the bootstrap. An account holding only
    `docs-index` is the state of a brand-new account: `resolve_project` must be able to see "no
    such project yet" so `--new-project` can mint the very first doc. Refusing there turns the
    first publish into a stage-4 failure. The refusal that DOES exist is about rendering an index
    from nothing, which is a different question from what this function returns.
    """

    def test_a_listing_of_only_the_index_itself_returns_empty_rather_than_refusing(
            self, index, cli):
        cli(stdout=_payload([_row("docs-index")]))
        assert index.vercel_projects(scope=SCOPE) == []

    def test_and_so_a_first_ever_publish_sees_the_project_as_absent(self, index, cli):
        """The membership test publish stage 4 performs, on a bootstrap account: absent, which
        is what lets `--new-project` proceed."""
        cli(stdout=_payload([_row("docs-index")]))
        existing = {p["name"] for p in index.vercel_projects(scope=SCOPE)}
        assert "example-design-12" not in existing


# --------------------------------------------------------------- no quiet relapse

class TestTheTableParserIsGone:
    def test_the_table_regex_does_not_survive_anywhere_in_the_module(self):
        """A fallback creeping back in is the failure mode the no-fallback decision exists to
        prevent, and it would reintroduce the silent-wrong-name class wholesale."""
        src = (SCRIPTS.parent / "index" / "build_index.py").read_text(encoding="utf-8")
        assert r"https://\S+" not in src
        assert r"^\s{2}" not in src

    def test_the_coarse_relative_age_parser_is_gone(self, index):
        """`updatedAt` replaces it outright; a second, coarser source of the same fact is how
        the two drift apart."""
        assert not hasattr(index, "_parse_age")
        assert not hasattr(index, "_AGE_UNITS")

    def test_no_docstring_in_the_module_carries_an_escape_byte(self, index):
        """Caught in review of this very change: a docstring DESCRIBING the escape-byte defect
        was written non-raw, so `\\x1b` became a real escape byte in the module's help text. An
        escape sequence belongs in this module only as the literal four characters."""
        offenders = []
        for name in dir(index):
            doc = getattr(getattr(index, name), "__doc__", None)
            if isinstance(doc, str) and any(
                    ord(c) < 0x20 and c not in "\n\t" or ord(c) == 0x7F for c in doc):
                offenders.append(name)
        assert not offenders, f"control bytes in the docstrings of: {offenders}"


# --------------------------------------------------------------------- new-tab links

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
