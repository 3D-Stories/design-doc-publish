"""One resolution, threaded — the Vercel account a public page reaches (#9).

Design: `docs/planning/2026-08-10-9-first-run-setup-flow.md` (revision 3).

Retiring the hardcoded team is the easy half. The half that can go wrong silently is what
happens afterwards, and these are the properties that would fail quietly rather than loudly:

* **Every account-targeting call still carries exactly one `--scope`.** Dropping it when no
  team is configured would target whichever account `vercel switch` last selected. The pin
  was never the defect; the hardcoding was.
* **The stage-7 CHILD PROCESS is handed the resolved values.** Left to look them up again it
  reads its own environment and config file, so one publish could render its page under one
  account and its index under another, with nothing in either output saying so.
* **The team reaches generated HTML, so it is escaped.** While it was a constant nothing
  needed escaping, and nothing did.
* **The module that decides all of this is not importable by name.** This package loads its
  own modules by exact path because a `sys.path` hijack was, in `render-doc`'s own words,
  "observed live, not theoretical".
"""
import html
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parent
sys.path.insert(0, str(SCRIPTS))

import publish_doc  # noqa: E402
import user_config  # noqa: E402

SCOPE = "example-team"


def _index_module():
    path = SCRIPTS.parent / "index" / "build_index.py"
    spec = importlib.util.spec_from_file_location("_test_scope_index", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _one_row(index):
    """`render` reads `order[0]` for its own accent CSS, so an index of nothing has never
    been renderable. That predates #9 and is not what these tests are about."""
    return index.build_rows(
        [{"name": "example-plan-1", "deployed": None}], ["example"], fetch_titles=False)


class TestEveryAccountTargetingCallIsPinned:
    """The invariant, asserted over the argv this code really builds."""

    def _capture(self, monkeypatch):
        seen = []

        def fake_run(cmd, **kw):
            seen.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        return seen

    def test_the_link_and_deploy_of_a_page_both_carry_the_configured_team(
            self, monkeypatch, tmp_path):
        seen = self._capture(monkeypatch)
        monkeypatch.setattr(publish_doc, "deployed_hosts", lambda log, name: ["x.vercel.app"])
        publish_doc.deploy("a-doc", "<html></html>", tmp_path, SCOPE)

        kinds = [c[1] for c in seen]
        assert "link" in kinds and "deploy" in kinds, (
            f"expected both command kinds to be observed, got {kinds}")
        for cmd in seen:
            assert cmd.count("--scope") == 1, f"{cmd} does not carry exactly one --scope"
            assert cmd[cmd.index("--scope") + 1] == SCOPE

    def test_the_project_listing_carries_it_too(self, monkeypatch):
        index = _index_module()
        payload = json.dumps({
            "projects": [{"name": "example-plan-1", "id": "prj_EXAMPLE",
                          "latestProductionUrl": "https://example-plan-1.vercel.app",
                          "updatedAt": 1785613860253}],
            "pagination": {"next": None}, "contextName": SCOPE})
        seen = []

        def fake_run(cmd, **kw):
            seen.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, payload, "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        index.vercel_projects(10, scope=SCOPE)
        assert len(seen) == 1
        assert seen[0].count("--scope") == 1
        assert seen[0][seen[0].index("--scope") + 1] == SCOPE

    def test_the_scope_is_never_conditionally_omitted(self):
        """`_vercel` takes the team as a REQUIRED argument. A default would let a caller with
        nothing configured build an unpinned command, which is the whole hazard."""
        import inspect
        signature = inspect.signature(publish_doc._vercel)
        assert signature.parameters["scope"].default is inspect.Parameter.empty


class TestTheIndexChildIsHandedTheResolvedValues:
    def test_it_is_told_the_team_rather_than_left_to_resolve_one(self, monkeypatch, tmp_path):
        """The hazard this closes: a child that re-resolves reads its own environment, so a
        single publish could answer for two different accounts."""
        seen = []

        def fake_run(cmd, **kw):
            seen.append(list(cmd))
            if str(cmd[1]).endswith("build_index.py"):
                out = Path(cmd[cmd.index("--out") + 1])
                out.parent.mkdir(parents=True, exist_ok=True)
                # One row, matching the one-project listing stubbed below: stage 7 compares
                # the rendered count against the live one to catch an interleaved publisher.
                out.write_text(
                    '<html><li><a href="https://example-plan-1.vercel.app">p</a></li></html>',
                    encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(publish_doc, "deployed_hosts", lambda log, name: ["x.vercel.app"])
        monkeypatch.setattr(publish_doc, "verify_live", lambda *a, **kw: None)
        # A believable listing: stage 7 now refuses an empty one, because moments after a
        # successful deploy an account cannot truthfully hold nothing.
        monkeypatch.setattr(publish_doc.INDEX, "vercel_projects",
                            lambda *a, **kw: [{"name": "example-plan-1"}])

        publish_doc.refresh_index(tmp_path, tmp_path / "ws.json", SCOPE)

        child = next(c for c in seen if str(c[1]).endswith("build_index.py"))
        assert "--vercel-scope" in child, (
            "the index child must be TOLD the team; left to resolve one it can answer for a "
            f"different account than the page it is indexing: {child}")
        assert child[child.index("--vercel-scope") + 1] == SCOPE
        assert child[child.index("--workspace-file") + 1] == str(tmp_path / "ws.json")


class TestAnUnconfiguredTeamRefusesRatherThanDeploying:
    def test_publish_stops_at_stage_four_with_a_legible_sentence(self, tmp_path, monkeypatch,
                                                                 capsys):
        for name in ("DESIGN_DOC_PUBLISH_VERCEL_SCOPE", "DESIGN_DOC_PUBLISH_CONFIG",
                     "XDG_CONFIG_HOME"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir()

        ws = tmp_path / "ws.json"
        ws.write_text(json.dumps({"projects": [{"name": "widget"}]}), encoding="utf-8")
        doc = tmp_path / "d.md"
        doc.write_text(
            "## Heading\n\nSome body text.\n\n"
            "```callout\nwarn | Read this first\nOne real component.\n```\n\n"
            "```options\nDebounce | Smallest diff | Re-done per call site | chosen\n```\n",
            encoding="utf-8")

        called = []
        monkeypatch.setattr(subprocess, "run",
                            lambda *a, **kw: called.append(a) or subprocess.CompletedProcess(
                                a[0] if a else [], 0, "", ""))

        rc = publish_doc.main(["--md", str(doc), "--out", str(tmp_path / "d.html"),
                               "--project", "widget", "--type", "design", "--ref", "1",
                               "--title", "Widget rollout design",
                               "--workspace-file", str(ws)])

        assert rc == publish_doc.EXIT_BASE + 4, "an unconfigured team must fail at stage 4"
        err = capsys.readouterr().err
        assert "setup.py" in err, "the refusal must name what to run"
        assert "Traceback" not in err
        # Scoped to `vercel` deliberately. Stage 3's staleness check shells out to `git`,
        # which is local and reaches no account — asserting on every subprocess would make
        # this test about the wrong thing.
        vercel_calls = [c for c in called if c and c[0] and c[0][0] == "vercel"]
        assert not vercel_calls, (
            f"no account may be touched before the team is known, but ran: {vercel_calls}")


class TestTheTeamIsEscapedWhereItReachesThePage:
    def test_a_crafted_team_cannot_break_out_of_the_title(self):
        """While the team was a constant nothing needed escaping and nothing did. It is
        user-supplied now, and this page is deployed PUBLICLY."""
        index = _index_module()
        now = datetime.now(timezone.utc)
        page = index.render(_one_row(index), "2026-08-10 00:00 UTC", now, "sig", None,
                            "</title><script>alert(1)</script>")
        assert "<script>alert(1)</script>" not in page
        assert html.escape("</title><script>alert(1)</script>") in page

    def test_the_validator_would_have_refused_it_long_before(self):
        """Defence in depth, and this is the layer that actually holds: a slug cannot
        contain a `<` at all."""
        with pytest.raises(user_config.ConfigError):
            user_config.validate_scope("</title><script>alert(1)</script>")

    def test_a_page_with_no_team_still_renders(self):
        index = _index_module()
        now = datetime.now(timezone.utc)
        page = index.render(_one_row(index), "2026-08-10 00:00 UTC", now, "sig")
        assert "<title>" in page and "docs index" in page


class TestTheResolverIsNotImportableByName:
    """`render-doc` records that a foreign module earlier on `sys.path` being selected AND
    executed was "observed live, not theoretical". This package therefore loads its own
    modules by exact path, and #9 adds a fourth such module — the one that decides which
    account a public page reaches."""

    def test_publish_doc_loads_it_by_path_under_a_private_name(self):
        assert publish_doc.CONFIG.__name__ == "_publish_doc_user_config"
        assert Path(publish_doc.CONFIG.__file__) == SCRIPTS / "user_config.py"

    def test_a_hostile_module_earlier_on_the_path_is_not_the_one_used(self, tmp_path,
                                                                      monkeypatch):
        hostile = tmp_path / "hostile"
        hostile.mkdir()
        (hostile / "user_config.py").write_text(
            "SETUP_COMMAND = 'pwned'\n", encoding="utf-8")
        monkeypatch.syspath_prepend(str(hostile))
        index = _index_module()
        assert index._user_config().SETUP_COMMAND != "pwned"
        assert "setup.py" in index._user_config().SETUP_COMMAND

    def test_the_index_loader_refuses_a_target_outside_its_own_tree(self, monkeypatch):
        """The containment check, which is what makes the exact-path load safe rather than
        merely specific: a symlinked target is EXECUTED before any check can reject it, so
        the check has to precede the load."""
        index = _index_module()
        source = (SCRIPTS.parent / "index" / "build_index.py").read_text(encoding="utf-8")
        loader = source.split("def _user_config():")[1].split("\ndef ")[0]
        assert "is_relative_to(root)" in loader
        assert "spec_from_file_location" in loader
        assert "import user_config" not in source


class TestStageFourAsksAboutTHISPROJECT:
    """The Step-11 Critical, and then the re-review of its first fix.

    The first fix let stage 4 read absence out of an EMPTY LISTING. Re-review was right to
    call that Critical: a truncated or erroneous CLI response can carry the requested tenant,
    an empty `projects` array and `pagination.next: null`, which is indistinguishable from a
    genuinely empty account — and stage 4 answers absence by minting a duplicate project under
    a new URL, which is the #125 failure and changes a published document's URL.

    So stage 4 no longer infers absence from a list at all. It asks about the ONE project it
    cares about and accepts only an EXPLICIT not-found. Probed live against Vercel CLI 56.5.0:
    `vercel project inspect <name> --scope <team>` exits 0 when the project exists, and exits
    1 with `Error: There is no project for "<name>"` when it does not.

    This is strictly stronger than the listing ever was: it needs no completeness proof,
    because it never enumerates anything.
    """

    def _cli(self, monkeypatch, rc, out="", err=""):
        seen = []

        def fake_run(cmd, **kw):
            seen.append(list(cmd))
            return subprocess.CompletedProcess(cmd, rc, out, err)

        monkeypatch.setattr(subprocess, "run", fake_run)
        return seen

    def test_an_explicit_not_found_is_absence_so_new_project_may_proceed(self, monkeypatch):
        seen = self._cli(monkeypatch, 1,
                         err='Error: There is no project for "payments-api-design-1"')
        assert publish_doc.resolve_project("payments-api-design-1", new_project=True,
                                           scope=SCOPE) is False
        assert seen[0][:3] == ["vercel", "project", "inspect"]
        assert seen[0][seen[0].index("--scope") + 1] == SCOPE

    def test_a_project_that_exists_is_reused(self, monkeypatch):
        self._cli(monkeypatch, 0, out="> Found Project example/payments-api-design-1")
        assert publish_doc.resolve_project("payments-api-design-1", new_project=False,
                                           scope=SCOPE) is True

    def test_an_UNEXPLAINED_failure_is_never_read_as_absence(self, monkeypatch):
        """The property the whole change turns on. A network error, a rate limit, a changed
        CLI — none of them means the project is absent, and treating them as absence is what
        mints a duplicate under a new URL."""
        for rc, err in ((1, "Error: connect ETIMEDOUT"),
                        (1, "Error: rate limited"),
                        (2, ""),
                        (1, "some unrecognised failure")):
            self._cli(monkeypatch, rc, err=err)
            with pytest.raises(publish_doc.StageError) as excinfo:
                publish_doc.resolve_project("payments-api-design-1", new_project=True,
                                            scope=SCOPE)
            assert excinfo.value.stage == 4

    def test_absence_without_new_project_still_refuses_with_the_usual_advice(self, monkeypatch):
        self._cli(monkeypatch, 1, err='Error: There is no project for "x-design-1"')
        with pytest.raises(publish_doc.StageError) as excinfo:
            publish_doc.resolve_project("x-design-1", new_project=False, scope=SCOPE)
        assert excinfo.value.stage == 4
        assert "--new-project" in excinfo.value.message

    def test_an_existing_project_with_new_project_still_refuses(self, monkeypatch):
        self._cli(monkeypatch, 0, out="> Found Project example/x-design-1")
        with pytest.raises(publish_doc.StageError) as excinfo:
            publish_doc.resolve_project("x-design-1", new_project=True, scope=SCOPE)
        assert excinfo.value.stage == 4
        assert "already exists" in excinfo.value.message

    def test_stage_four_no_longer_enumerates_the_account_at_all(self, monkeypatch):
        """It used to list every project and test membership, which is why a listing it could
        not trust was able to decide the answer."""
        seen = self._cli(monkeypatch, 1, err='Error: There is no project for "x-design-1"')
        publish_doc.resolve_project("x-design-1", new_project=True, scope=SCOPE)
        assert not any("ls" in cmd for cmd in seen), (
            f"stage 4 must not enumerate the account: {seen}")


class TestAbsenceMustNameTHISProject:
    """Third-pass review. The absence branch used a bare substring test over stdout AND
    stderr, so any failure whose text happened to contain the phrase counted as absence —
    including a message about a DIFFERENT project. Absence is the reading that mints a
    duplicate under a new URL, so it has to be the narrowest branch in the function.
    """

    def _cli(self, monkeypatch, rc, out="", err=""):
        monkeypatch.setattr(
            subprocess, "run",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, rc, out, err))

    def test_a_not_found_about_ANOTHER_project_is_not_absence(self, monkeypatch):
        self._cli(monkeypatch, 1, err='Error: There is no project for "something-else"')
        with pytest.raises(publish_doc.StageError) as excinfo:
            publish_doc.resolve_project("payments-api-design-1", new_project=True, scope=SCOPE)
        assert excinfo.value.stage == 4

    def test_the_phrase_appearing_in_STDOUT_is_not_absence(self, monkeypatch):
        """The authoritative message is the CLI's error, on stderr. Accepting it from stdout
        widens the surface that can trigger the branch for no gain."""
        self._cli(monkeypatch, 1,
                  out='There is no project for "payments-api-design-1"', err="")
        with pytest.raises(publish_doc.StageError):
            publish_doc.resolve_project("payments-api-design-1", new_project=True, scope=SCOPE)

    def test_a_merely_similar_message_is_not_absence(self, monkeypatch):
        self._cli(monkeypatch, 1, err="Error: no project format recognised")
        with pytest.raises(publish_doc.StageError):
            publish_doc.resolve_project("payments-api-design-1", new_project=True, scope=SCOPE)

    def test_the_real_message_for_THIS_project_still_reads_as_absence(self, monkeypatch):
        self._cli(monkeypatch, 1,
                  err='Error: There is no project for "payments-api-design-1"\n')
        assert publish_doc.resolve_project("payments-api-design-1", new_project=True,
                                           scope=SCOPE) is False

    def test_a_missing_cli_is_a_stage_four_error_not_a_traceback(self, monkeypatch):
        """`_vercel` shells out; if the binary is gone that raises rather than returning."""
        def boom(cmd, **kw):
            raise FileNotFoundError(2, "No such file or directory", "vercel")
        monkeypatch.setattr(subprocess, "run", boom)
        with pytest.raises(publish_doc.StageError) as excinfo:
            publish_doc.resolve_project("payments-api-design-1", new_project=True, scope=SCOPE)
        assert excinfo.value.stage == 4
        assert "vercel" in excinfo.value.message.lower()


class TestStageSevenDoesNotBelieveAnEmptyListing:
    """Re-review, Medium. Stage 7 compares the rendered row count against a live listing to
    catch a publisher that interleaved with this one. With a live count of zero the comparison
    `shown < 0` is never true, so the check passed VACUOUSLY — disabled by exactly the
    untruthful-empty-listing case that the stage-4 rewrite stopped trusting elsewhere.

    An empty listing here cannot mean an empty account: a deploy has just succeeded, so at
    minimum that project exists.
    """

    def test_an_empty_live_listing_after_a_deploy_is_refused(self, monkeypatch, tmp_path):
        monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _index_written(cmd, tmp_path))
        monkeypatch.setattr(publish_doc, "deployed_hosts", lambda log, name: ["x.vercel.app"])
        monkeypatch.setattr(publish_doc, "verify_live", lambda *a, **kw: None)
        monkeypatch.setattr(publish_doc.INDEX, "vercel_projects", lambda *a, **kw: [])
        with pytest.raises(publish_doc.StageError) as excinfo:
            publish_doc.refresh_index(tmp_path, tmp_path / "ws.json", SCOPE)
        assert excinfo.value.stage == 7

    def test_a_believable_listing_still_passes(self, monkeypatch, tmp_path):
        monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _index_written(cmd, tmp_path))
        monkeypatch.setattr(publish_doc, "deployed_hosts", lambda log, name: ["x.vercel.app"])
        monkeypatch.setattr(publish_doc, "verify_live", lambda *a, **kw: None)
        monkeypatch.setattr(publish_doc.INDEX, "vercel_projects",
                            lambda *a, **kw: [{"name": "one"}])
        publish_doc.refresh_index(tmp_path, tmp_path / "ws.json", SCOPE)


def _index_written(cmd, tmp_path):
    """The index child, faked: it writes a one-row page so stage 7 has something to compare."""
    cmd = list(cmd)
    if str(cmd[1]).endswith("build_index.py"):
        out = Path(cmd[cmd.index("--out") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text('<html><li><a href="https://one.vercel.app">one</a></li></html>',
                       encoding="utf-8")
    return subprocess.CompletedProcess(cmd, 0, "", "")
