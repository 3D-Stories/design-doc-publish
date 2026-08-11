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
                out.write_text("<html></html>", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(publish_doc, "deployed_hosts", lambda log, name: ["x.vercel.app"])
        monkeypatch.setattr(publish_doc, "verify_live", lambda *a, **kw: None)
        monkeypatch.setattr(publish_doc.INDEX, "vercel_projects", lambda *a, **kw: [])

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


class TestAFirstPublishFromAnEmptyAccount:
    """The Step-11 Critical, proved at the PUBLISHER rather than only at the listing.

    The reviewer asked for exactly this: a test showing `--new-project` proceeds from a
    genuinely empty account. Stage 4 is where it used to die, so stage 4 is where it is
    asserted.
    """

    def _listing(self, projects):
        return json.dumps({"projects": projects, "pagination": {"next": None},
                           "contextName": SCOPE})

    def test_stage_four_sees_the_project_as_absent_and_lets_new_project_proceed(
            self, monkeypatch):
        monkeypatch.setattr(
            subprocess, "run",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, self._listing([]), ""))
        # False == "did not already exist", which is what --new-project needs to hear.
        assert publish_doc.resolve_project("payments-api-design-1", new_project=True,
                                           limit=100, scope=SCOPE) is False

    def test_without_new_project_it_still_refuses_with_the_usual_advice(self, monkeypatch):
        """The other half: an empty account does not silently mint anything. Reuse is still
        the default, and the refusal still names the flag."""
        monkeypatch.setattr(
            subprocess, "run",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, self._listing([]), ""))
        with pytest.raises(publish_doc.StageError) as excinfo:
            publish_doc.resolve_project("payments-api-design-1", new_project=False,
                                        limit=100, scope=SCOPE)
        assert excinfo.value.stage == 4
        assert "--new-project" in excinfo.value.message

    def test_a_truncated_listing_still_fails_stage_four_rather_than_looking_empty(
            self, monkeypatch):
        """The guarantee that must survive the fix: a listing that cannot be judged complete
        is refused, so stage 4 never mistakes it for an empty account and mints a duplicate."""
        bad = json.dumps({"projects": [], "pagination": {"count": 0}, "contextName": SCOPE})
        monkeypatch.setattr(
            subprocess, "run",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, bad, ""))
        with pytest.raises(publish_doc.StageError) as excinfo:
            publish_doc.resolve_project("payments-api-design-1", new_project=True,
                                        limit=100, scope=SCOPE)
        assert excinfo.value.stage == 4
