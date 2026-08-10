"""`publish_doc.py` — the mechanical publish path, end to end (#12, wave 5).

Design: `docs/planning/2026-08-01-12-publish-pipeline.md` (revision 2, gated).

Three rules these tests exist to enforce:

* **Tests drive `main()`, not the helpers.** A suite of green helper tests over a CLI that
  never wires them together is how the prior wave shipped a feature that was absent. So
  every stage assertion goes through the real entry point and asserts WHICH STAGES RAN —
  and one test runs the file as an actual executable, from an unrelated directory.
* **The fake must not be kinder than reality.** The first version of this harness served a
  canned page to the verifier regardless of what had been "deployed", which meant the
  suite could not have caught a stale deployment — the exact defect Step 11 found. The
  fake now serves back the bytes the fake deploy received, keyed by project, and answers
  404 for a project that was never deployed.
* **The Vercel CLI is never invoked.** `subprocess.run` and `urlopen` are patched on their
  own modules, which catches `publish_doc` and `build_index` alike — both do a plain
  `import subprocess`, so the attribute is looked up at call time.

The `vercel project ls` fixture is REAL output captured from this account
(`fixtures/vercel_project_ls.json`, Vercel CLI 56.5.0, 2026-08-04). Since #125 the listing is
read as JSON, which inverts the trap the old fixture pinned: `--format json` puts the payload on
**stdout** and leaves only the banner on stderr, where the human table did the opposite. The
retired table capture stays on disk as `fixtures/vercel_project_ls.txt` — `test_build_index.py`
feeds it as the most likely thing to arrive if a CLI upgrade drops the flag, and documents the
JSON fixture's one deviation from its raw capture (its row set is subset).
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import publish_doc  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
LS_OUTPUT = (FIXTURES / "vercel_project_ls.json").read_text(encoding="utf-8")

# What the CLI leaves on stderr in --format json mode: the banner, and nothing else.
LS_BANNER = "Vercel CLI 56.5.0 (Node.js 22.22.1)\nFetching projects in 3d-stories\n"

# A project that IS in the captured output, and one that is not.
EXISTING = "claude-skills-plan-786"
ABSENT = "claude-skills-design-12"

# RECONSTRUCTED, not captured: recording a real `vercel deploy` transcript would mean
# publishing a page. The shape follows the CLI's documented output, and the parser under
# test scans the whole log for a host belonging to this project rather than anchoring to
# a line, so a layout change degrades to "found it somewhere" instead of a false refusal.
DEPLOY_LOG = """Vercel CLI 56.5.0 (Node.js 22.22.1)
Retrieving project&
Deploying 3d-stories/{name}
Uploading [====================] (1.2KB/1.2KB)
Inspect: https://vercel.com/3d-stories/{name}/8Qk3nR2 [2s]
Production: https://{name}-8qk3nr2-3d-stories.vercel.app [8s]
Aliased to https://{name}.vercel.app
"""


def _page(title, body="body text"):
    """What the renderer really emits, so no assertion is a guess about its output."""
    return publish_doc.RENDER.render_artifact(body, title=title, style="design")


# --------------------------------------------------------------------------- fakes

class FakeRun:
    """Stands in for `subprocess.run`. Records every call, answers from recorded text,
    and — crucially — remembers what each deploy actually shipped."""

    def __init__(self, ls_output=LS_OUTPUT, deploy_rc=0, deploy_log=None,
                 ls_rc=0, index_rc=0, link_rc=0, raises=None, index_rows=None):
        self.calls = []
        self.deployed = {}        # project -> the bytes that deploy received
        self.shipped = {}         # project -> {relative path: bytes} for the whole deploy dir
        self._linked = {}         # cwd -> project last linked there
        self.ls_output, self.ls_rc = ls_output, ls_rc
        self.deploy_rc, self.deploy_log = deploy_rc, deploy_log
        self.index_rc, self.link_rc, self.raises = index_rc, link_rc, raises
        self.index_rows = index_rows

    def deploys(self):
        """Every call that reaches the outside world or changes anything.

        `calls` records every subprocess, and since #163 stage 3 also runs a LOCAL,
        read-only `git show` to diff a republish against its last committed text. That is
        not a deploy and not a network call, so the "nothing deployed" assertions below
        filter it out — they were always about reaching the outside world, as their own
        names say. `test_a_refusal_makes_no_vercel_call_at_all` pins the strict property
        directly, so narrowing these does not lose it.
        """
        return [(c, cwd) for c, cwd in self.calls if c[:1] != ["git"]]

    def cmds(self):
        return [c for c, _ in self.calls]

    def ran(self, *prefix):
        return [(c, cwd) for c, cwd in self.calls if tuple(c[:len(prefix)]) == prefix]

    def sequence(self):
        """A coarse ordered trace, for asserting stage order rather than membership."""
        out = []
        for c, _ in self.calls:
            if c[:3] == ["vercel", "project", "ls"]:
                out.append("ls")
            elif c[:2] == ["vercel", "link"]:
                out.append(f"link:{c[c.index('--project') + 1]}")
            elif c[:2] == ["vercel", "deploy"]:
                out.append("deploy")
            elif "build_index.py" in " ".join(c):
                out.append("build_index")
        return out

    def __call__(self, cmd, **kw):
        cmd = list(cmd)
        cwd = kw.get("cwd")
        self.calls.append((cmd, cwd))
        if self.raises:
            raise self.raises

        if cmd[:3] == ["vercel", "project", "ls"]:
            # The trap, reproduced — and it is the INVERSE of the table mode's: `--format json`
            # puts the payload on STDOUT and leaves only the banner on stderr. A parser that
            # kept reading both streams would concatenate the banner into the JSON.
            return subprocess.CompletedProcess(cmd, self.ls_rc, self.ls_output, LS_BANNER)

        if cmd[:2] == ["vercel", "link"]:
            self._linked[cwd] = cmd[cmd.index("--project") + 1]
            return subprocess.CompletedProcess(cmd, self.link_rc, "Linked\n", "")

        if cmd[:2] == ["vercel", "deploy"]:
            name = self._linked.get(cwd, "unlinked")
            # Reading it here is the point: a deploy ships whatever is in the directory,
            # so the fake must fail loudly if nothing was written.
            self.deployed[name] = (Path(cwd) / "index.html").read_bytes()
            # #121: the page is no longer the only thing in that directory. Snapshot the WHOLE
            # tree, because "the asset never ships" is a claim about what the directory holds at
            # this exact moment — the tempdir is gone by the time a test could look.
            root = Path(cwd)
            self.shipped[name] = {
                p.relative_to(root).as_posix(): p.read_bytes()
                for p in sorted(root.rglob("*")) if p.is_file()
            }
            log = self.deploy_log if self.deploy_log is not None else DEPLOY_LOG.format(name=name)
            return subprocess.CompletedProcess(cmd, self.deploy_rc, log, "")

        if "build_index.py" in " ".join(cmd):
            out = cmd[cmd.index("--out") + 1]
            if self.index_rc == 0:
                # A real index carries one row per project. `index_rows=None` means
                # "however many the CLI currently lists", which is the honest default;
                # a number models a build that raced another publisher.
                n = self.index_rows if self.index_rows is not None else self._ls_count()
                rows = "".join(f'<li><a href="https://p{i}.vercel.app">p{i}</a></li>'
                               for i in range(n))
                Path(out).parent.mkdir(parents=True, exist_ok=True)
                Path(out).write_text(f"<html><title>docs index</title>{rows}</html>",
                                     encoding="utf-8")
            return subprocess.CompletedProcess(cmd, self.index_rc, "wrote it\n", "")

    def _ls_count(self):
        """How many rows a real index would carry, counted the way the code under test counts:
        from the JSON payload, minus the index's own project."""
        try:
            projects = json.loads(self.ls_output)["projects"]
        except (ValueError, KeyError, TypeError):
            return 0
        return len([p for p in projects if p.get("name") != "docs-index"])

        raise AssertionError(f"unexpected subprocess call: {cmd}")


class FakeResponse:
    def __init__(self, body: bytes, status=200, final=None):
        self.body, self.status, self._final = body, status, final

    def read(self, n=None):
        return self.body[:n] if n else self.body

    def geturl(self):
        return self._final

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeUrlopen:
    """Serves back what the paired `FakeRun` deployed, keyed by project.

    `serve` overrides one project's body — that is how a STALE deployment is modelled.
    A project that was never deployed answers 404, like the real thing. `cold` models the
    alias swap not being instant: the first N fetches of a project 404 before it settles,
    which is what the first real run of this pipeline actually hit.
    """

    def __init__(self, runner=None, serve=None, status=200, error=None, redirect_to=None,
                 cold=0):
        self.runner, self.serve = runner, dict(serve or {})
        self.status, self.error, self.redirect_to = status, error, redirect_to
        self.cold = cold
        self.urls = []

    def _project(self, url):
        host = url.split("//", 1)[-1].split("/", 1)[0]
        return host.split(".vercel.app")[0]

    def __call__(self, req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        self.urls.append(url)
        if self.error:
            raise self.error
        project = self._project(url)
        if self.cold > 0:
            self.cold -= 1
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        if project in self.serve:
            body = self.serve[project]
        elif self.runner is not None and project in self.runner.deployed:
            body = self.runner.deployed[project]
        else:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        if isinstance(body, str):
            body = body.encode()
        return FakeResponse(body, self.status, final=self.redirect_to or url)


# --------------------------------------------------------------------------- harness

@pytest.fixture
def workspace(tmp_path):
    """A real-shaped workspace file, so `known_projects()` is exercised, not stubbed."""
    p = tmp_path / "workspace.json"
    p.write_text(json.dumps({"projects": [
        {"name": "claude-skills"}, {"name": "rawgentic"}, {"name": "herdr-dashboard"},
    ]}), encoding="utf-8")
    return p


@pytest.fixture
def doc(tmp_path):
    p = tmp_path / "a-doc.md"
    # The callout is load-bearing as of #127, not decoration: stage 3 now refuses a styled
    # page carrying none of its style's components, and this fixture publishes at
    # `--type design`. Without a component it is exactly the document the new gate exists
    # to stop, so every test built on it would assert against a page that cannot ship.
    #
    # The `options` block is load-bearing for the same reason as of #130, which raised the
    # bar from "any component" to "every device this style OPENS with". `design`'s
    # first-read element is its numbered option cards, so a publishable design doc now has
    # to carry them. 61 tests in this file publish through this fixture and every one of
    # them failed the moment the check landed — a fair measure of the change's real reach.
    p.write_text("## Heading\n\nSome body text.\n\n"
                 "```callout\nwarn | Read this first\nOne real component.\n```\n\n"
                 "```options\nDebounce | Smallest diff | Re-done per call site | chosen\n```\n",
                 encoding="utf-8")
    return p


@pytest.fixture
def plan_doc(doc):
    """The same document, rewritten for `--type plan`.

    `plan` renders the `roadmap` style, and #130 requires each style's OWN first-read
    devices — roadmap opens with a stat strip, a READ THIS FIRST callout stack and the
    phase rail, which is a different set from `design`'s option cards. A test that
    publishes a plan therefore needs a plan-shaped document; reusing the design fixture
    would assert against a page that cannot ship.
    """
    doc.write_text(
        "## Heading\n\nSome body text.\n\n"
        "```stats\n82 | children merged\n```\n\n"
        "```callout\nwarn | Read this first\nOne real component.\n```\n\n"
        "```phases\nWave 1 | 3 of 12 done | warn\n  FA-1 | Fan curve stalls | crit\n```\n",
        encoding="utf-8")
    return doc


@pytest.fixture
def run(monkeypatch, workspace, doc):
    """Invoke the real `main()` with both boundaries faked. Returns (rc, fake_run, fake_url)."""
    def go(*extra, fake_run=None, fake_url=None, serve=None, **kw):
        fr = fake_run if fake_run is not None else FakeRun(**kw)
        fu = fake_url if fake_url is not None else FakeUrlopen(runner=fr, serve=serve)
        monkeypatch.setattr(subprocess, "run", fr)
        monkeypatch.setattr(urllib.request, "urlopen", fu)
        monkeypatch.setattr(publish_doc, "VERIFY_DELAY", 0)   # the suite does not wait
        argv = ["--md", str(doc), "--project", "claude-skills", "--type", "design",
                "--ref", "12", "--title", "A Real Doc",
                "--workspace-file", str(workspace), *extra]
        return publish_doc.main(argv), fr, fu
    return go


def code(stage):
    return publish_doc.EXIT_BASE + stage


# --------------------------------------------------------------------------- AC2

class TestTheNameIsDerivedFromValidatedComponents:
    """AC2. Validating the CONCATENATION is not enough: `--project deploy --type design
    --ref 713` yields `deploy-design-713`, which matches the pattern perfectly and is
    exactly the junk the convention exists to stop."""

    def test_the_happy_name(self, workspace):
        assert publish_doc.derive_name(
            "claude-skills", "design", "12", workspace) == "claude-skills-design-12"

    @pytest.mark.parametrize("project", ["deploy", "site", "copy", "final-final", "vercel"])
    def test_a_project_that_does_not_exist_is_refused(self, project, workspace):
        """The gate's headline case. Each of these passes a shape check."""
        with pytest.raises(publish_doc.StageError):
            publish_doc.derive_name(project, "design", "713", workspace)

    def test_the_workspace_bucket_is_the_one_literal_exception(self, workspace):
        assert publish_doc.derive_name(
            "workspace", "audit", "harness", workspace) == "workspace-audit-harness"

    def test_case_is_folded_because_vercel_folds_it(self, workspace):
        """`Rawgentic` and `rawgentic` must not become two projects."""
        assert publish_doc.derive_name(
            "Rawgentic", "design", "735", workspace) == "rawgentic-design-735"

    @pytest.mark.parametrize("ref", ["design", "plan", "spec"])
    def test_a_ref_that_is_itself_a_purpose_token_is_refused(self, ref, workspace):
        with pytest.raises(publish_doc.StageError):
            publish_doc.derive_name("claude-skills", "design", ref, workspace)

    @pytest.mark.parametrize("ref", ["", "a b", "Slug/With", "-lead", "trail-",
                                     "y" * 41, "under_score", "x"])
    def test_a_malformed_ref_is_refused(self, ref, workspace):
        with pytest.raises(publish_doc.StageError):
            publish_doc.derive_name("claude-skills", "design", ref, workspace)

    @pytest.mark.parametrize("ref", ["1", "12", "735", "network-topology", "aa"])
    def test_an_issue_number_or_a_real_slug_is_accepted(self, ref, workspace):
        assert publish_doc.derive_name("claude-skills", "design", ref, workspace)

    def test_issue_one_is_publishable(self, workspace):
        """Under a flat 2-char minimum it was not — issue #1 could not be published."""
        assert publish_doc.derive_name(
            "claude-skills", "design", "1", workspace) == "claude-skills-design-1"

    @pytest.mark.parametrize("ref", ["01", "007", "0"])
    def test_a_non_canonical_issue_number_is_refused(self, ref, workspace):
        """`-01` and `-1` would be two Vercel projects for one issue."""
        with pytest.raises(publish_doc.StageError):
            publish_doc.derive_name("claude-skills", "design", ref, workspace)

    def test_there_is_no_flag_that_accepts_a_name(self):
        parser = publish_doc.build_parser()
        flags = {a.option_strings[0] for a in parser._actions if a.option_strings}
        assert "--name" not in flags and "--project-name" not in flags

    def test_an_over_long_assembled_name_is_refused(self, tmp_path):
        """Only the assembled-name limit can reject this: the project component is long
        but legal, and the ref is a valid 40-char slug."""
        long_project = "a" * 70
        ws = tmp_path / "long.json"
        ws.write_text(json.dumps({"projects": [{"name": long_project}]}), encoding="utf-8")
        ref = "b" * 40
        assert len(f"{long_project}-design-{ref}") > publish_doc.MAX_NAME
        with pytest.raises(publish_doc.StageError, match="not a usable Vercel"):
            publish_doc.derive_name(long_project, "design", ref, ws)

    def test_an_underscore_project_is_refused_by_the_assembled_name_rule(self, tmp_path):
        """A real workspace holds `chorestory_business`; Vercel names cannot carry `_`."""
        ws = tmp_path / "u.json"
        ws.write_text(json.dumps({"projects": [{"name": "chorestory_business"}]}),
                      encoding="utf-8")
        with pytest.raises(publish_doc.StageError, match="not a usable Vercel"):
            publish_doc.derive_name("chorestory_business", "design", "5", ws)


# --------------------------------------------------------------------------- §2b

class TestPurposeAndStyleAreDifferentVocabularies:
    """§2b. Revision 1 conflated them. `plan`/`audit`/`runbook` are not styles;
    `roadmap`/`dashboard`/`workflow` are not purposes."""

    def test_every_purpose_maps_to_a_real_registry_entry(self):
        registry = publish_doc.RENDER._TEMPLATES
        for purpose in publish_doc.PURPOSES:
            assert publish_doc.PURPOSE_STYLE[purpose] in registry, purpose

    def test_every_purpose_has_a_default_style(self):
        assert set(publish_doc.PURPOSE_STYLE) == set(publish_doc.PURPOSES)

    @pytest.mark.parametrize("style_only", ["roadmap", "dashboard", "workflow", "plain"])
    def test_a_style_is_not_accepted_as_a_type(self, style_only):
        with pytest.raises(SystemExit):
            publish_doc.build_parser().parse_args(
                ["--md", "x.md", "--project", "p", "--type", style_only,
                 "--ref", "1", "--title", "T"])

    @pytest.mark.parametrize("purpose_only", ["plan", "audit", "runbook"])
    def test_a_purpose_is_not_accepted_as_a_style(self, purpose_only):
        with pytest.raises(SystemExit):
            publish_doc.build_parser().parse_args(
                ["--md", "x.md", "--project", "p", "--type", "design", "--ref", "1",
                 "--title", "T", "--style", purpose_only])

    def test_title_is_required(self):
        with pytest.raises(SystemExit):
            publish_doc.build_parser().parse_args(
                ["--md", "x.md", "--project", "p", "--type", "design", "--ref", "1"])

    def test_out_defaults_to_the_md_path_with_an_html_suffix(self):
        args = publish_doc.build_parser().parse_args(
            ["--md", "docs/planning/x.md", "--project", "p", "--type", "design",
             "--ref", "1", "--title", "T"])
        assert publish_doc.default_out(args) == Path("docs/planning/x.html")


# --------------------------------------------------------------------------- paths

class TestThePathsItRefuses:
    """A local file becomes a PUBLIC page here, so `--md` and `--out` are a trust
    boundary, not conveniences."""

    def test_out_may_not_be_the_markdown_source(self, run, doc):
        """It would read the source and overwrite it with its own rendering."""
        rc, fr, _ = run("--out", str(doc))
        assert rc == code(1)
        assert doc.read_text(encoding="utf-8").startswith("## Heading")
        assert fr.deploys() == []

    def test_out_may_not_be_an_equivalent_path_to_the_source(self, run, doc):
        weird = str(doc.parent / "." / doc.name)
        rc, _, _ = run("--out", weird)
        assert rc == code(1)

    def test_out_must_be_html(self, run, tmp_path):
        assert run("--out", str(tmp_path / "x.txt"))[0] == code(1)

    def test_a_symlinked_md_is_refused(self, run, tmp_path, monkeypatch, workspace):
        """A tracked doc symlinked at a readable secret would render, pass the mechanical
        gate — the renderer supplies title and stamp and escapes the body — and deploy
        publicly."""
        secret = tmp_path / "secret.txt"
        secret.write_text("token-shaped-content\n", encoding="utf-8")
        link = tmp_path / "innocent.md"
        link.symlink_to(secret)
        fr = FakeRun()
        monkeypatch.setattr(subprocess, "run", fr)
        rc = publish_doc.main(["--md", str(link), "--out", str(tmp_path / "o.html"),
                               "--project", "claude-skills", "--type", "design",
                               "--ref", "12", "--title", "T",
                               "--workspace-file", str(workspace)])
        assert rc == code(1)
        assert not (tmp_path / "o.html").exists()
        assert fr.deploys() == []

    def test_a_symlinked_out_is_refused(self, run, tmp_path):
        target = tmp_path / "victim.html"
        target.write_text("do not clobber", encoding="utf-8")
        link = tmp_path / "out.html"
        link.symlink_to(target)
        assert run("--out", str(link))[0] == code(1)
        assert target.read_text(encoding="utf-8") == "do not clobber"

    def test_a_missing_md_is_stage_one(self, run):
        assert run("--md", "/nonexistent/x.md")[0] == code(1)


# --------------------------------------------------------------------------- AC4

class TestTheLintGateRunsBeforeAnyDeploy:
    """AC4. The issue's own order says deploy-then-lint; AC4 says a lint failure leaves
    nothing deployed. Those cannot both hold."""

    def test_a_placeholder_title_fails_the_gate_and_nothing_deploys(self, run):
        rc, fr, _ = run("--title", "Untitled")
        assert rc == code(3)
        assert fr.deploys() == []

    def test_the_lint_failure_is_reported_with_its_finding(self, run, capsys):
        run("--title", "Untitled")
        assert "placeholder" in capsys.readouterr().err

    def test_ANY_lint_finding_blocks_the_deploy_not_just_the_title(
            self, run, monkeypatch):
        """Guards against the no-deploy contract being special-cased to one check."""
        monkeypatch.setattr(publish_doc, "LINT",
                            lambda _html: ["external-requests: external request via src"])
        rc, fr, _ = run()
        assert rc == code(3)
        assert fr.deploys() == []

    def test_the_committed_html_is_still_written_so_the_failure_is_inspectable(
            self, run, tmp_path):
        run("--title", "Untitled")
        assert (tmp_path / "a-doc.html").exists()


# --------------------------------------------------------------------------- AC3

class TestReuseIsTheDefaultAndCreationIsTheException:
    """AC3, against the real captured project list."""

    def test_an_existing_project_is_reused_without_a_flag(self, run, plan_doc):
        rc, fr, _ = run("--ref", "786", "--type", "plan")
        assert rc == 0
        assert EXISTING in fr.ran("vercel", "link")[0][0]

    def test_an_unknown_project_is_refused_without_the_override(self, run):
        rc, fr, _ = run()
        assert rc == code(4)
        assert fr.ran("vercel", "deploy") == []

    def test_the_override_mints_it(self, run):
        rc, fr, _ = run("--new-project")
        assert rc == 0
        assert ABSENT in fr.ran("vercel", "link")[0][0]

    def test_the_override_on_an_existing_project_is_itself_an_error(self, run, plan_doc):
        """Otherwise the flag becomes the thing people paste to make the error go away."""
        rc, fr, _ = run("--ref", "786", "--type", "plan", "--new-project")
        assert rc == code(4)
        assert fr.ran("vercel", "deploy") == []

    def test_a_project_ls_failure_is_a_staged_verdict_not_a_crash(self, run):
        """`vercel_projects()` calls sys.exit() — uncaught, the pipeline dies with the
        index builder's message instead of a stage verdict."""
        assert run(fake_run=FakeRun(ls_rc=1, ls_output="boom"))[0] == code(4)

    def test_unparseable_ls_output_is_also_a_staged_verdict(self, run):
        assert run(fake_run=FakeRun(ls_output="Vercel CLI 56.5.0\nnothing here\n"))[0] == code(4)

    def test_a_missing_vercel_binary_is_a_staged_verdict_not_a_traceback(self, run):
        """FileNotFoundError is not SystemExit; without the catch-all this exited 1 with
        a traceback and no stage — the one thing the exit-code contract forbids."""
        assert run(fake_run=FakeRun(raises=FileNotFoundError("vercel")))[0] == code(4)

    def test_the_ls_call_defeats_the_pagination_trap(self, run):
        _, fr, _ = run("--new-project")
        assert "--limit" in fr.ran("vercel", "project", "ls")[0][0]


# --------------------------------------------------------------------------- §2a

class TestTheDeployIsBoundToTheRenderedFile:
    """§2a. `vercel deploy --prod` from the wrong directory deploys the repository, or
    whatever project was last linked."""

    def test_link_and_deploy_run_in_the_same_temp_dir(self, run):
        """[0] is the doc's own pair; the index refresh links and deploys again after."""
        _, fr, _ = run("--new-project")
        _, link_cwd = fr.ran("vercel", "link")[0]
        _, dep_cwd = fr.ran("vercel", "deploy")[0]
        assert link_cwd is not None and link_cwd == dep_cwd

    def test_the_index_refresh_uses_a_different_dir(self, run):
        """Deploying the index from the doc's dir would publish the doc as the index."""
        _, fr, _ = run("--new-project")
        assert fr.ran("vercel", "deploy")[0][1] != fr.ran("vercel", "deploy")[-1][1]

    def test_what_deploys_is_what_was_linted(self, run, tmp_path):
        _, fr, _ = run("--new-project")
        assert fr.deployed[ABSENT] == (tmp_path / "a-doc.html").read_bytes()

    def test_a_rewrite_of_out_after_the_gate_cannot_reach_the_deploy(
            self, run, tmp_path, doc):
        """The gate reads an in-memory string; re-reading `--out` at deploy time reopened
        it. Concurrent sessions share these trees, so this is a live race, not a theory."""
        out = tmp_path / "a-doc.html"
        inner = FakeRun()

        def spy(cmd, **kw):
            if list(cmd)[:3] == ["vercel", "project", "ls"]:      # stage 4: after lint
                out.write_text("<html>UNLINTED</html>", encoding="utf-8")
            return inner(cmd, **kw)

        rc, _, _ = run("--new-project", fake_run=spy,
                       fake_url=FakeUrlopen(runner=inner))
        assert rc == 0
        assert b"UNLINTED" not in inner.deployed[ABSENT]
        assert b"A Real Doc" in inner.deployed[ABSENT]

    def test_the_link_binds_the_derived_name(self, run):
        _, fr, _ = run("--new-project")
        link, _ = fr.ran("vercel", "link")[0]
        assert link[link.index("--project") + 1] == ABSENT
        assert "--yes" in link

    def test_the_deploy_is_public_production(self, run):
        """Public production is the convention here — no deployment protection."""
        _, fr, _ = run("--new-project")
        dep, _ = fr.ran("vercel", "deploy")[0]
        assert "--prod" in dep and "--yes" in dep

    def test_every_vercel_call_pins_the_team_scope(self, run):
        """Ambient scope is whatever the last `vercel switch` left behind — an unpinned
        deploy can land in a personal account."""
        _, fr, _ = run("--new-project")
        vercel_calls = [c for c in fr.cmds() if c[0] == "vercel"]
        assert vercel_calls
        for cmd in vercel_calls:
            assert "--scope" in cmd, cmd
            assert cmd[cmd.index("--scope") + 1] == publish_doc.VERCEL_SCOPE

    def test_a_failed_deploy_is_stage_five(self, run):
        assert run("--new-project", fake_run=FakeRun(deploy_rc=1))[0] == code(5)

    def test_a_deploy_log_with_no_url_is_refused(self, run):
        rc, _, fu = run("--new-project",
                        fake_run=FakeRun(deploy_log="Vercel CLI 56.5.0\nDone.\n"))
        assert rc == code(5)
        assert fu.urls == []       # and nothing was verified against a guessed URL

    def test_a_log_naming_only_ANOTHER_project_is_refused(self, run):
        """What a deploy bound to ambient link state looks like: it succeeded, elsewhere."""
        rc, _, fu = run("--new-project", fake_run=FakeRun(
            deploy_log="Production: https://someone-elses-page.vercel.app [8s]\n"))
        assert rc == code(5)
        assert fu.urls == []

    @pytest.mark.parametrize("junk", [
        "Production: https://old.vercel.app.evil/x [8s]\n",
        "see https://claude-skills-design-12.vercel.app.attacker.test/ [8s]\n",
    ])
    def test_a_host_that_merely_contains_vercel_app_is_not_a_url(self, run, junk):
        assert run("--new-project", fake_run=FakeRun(deploy_log=junk))[0] == code(5)

    def test_deployed_hosts_accepts_the_real_shapes(self):
        log = DEPLOY_LOG.format(name=ABSENT)
        hosts = publish_doc.deployed_hosts(log, ABSENT)
        assert f"{ABSENT}.vercel.app" in hosts
        assert f"{ABSENT}-8qk3nr2-3d-stories.vercel.app" in hosts
        # the Inspect line is vercel.com, not a deployment host
        assert not any("vercel.com" in h for h in hosts)


# --------------------------------------------------------------------------- AC5

class TestVerificationIsCacheBustedAndContentChecked:
    """AC5. `page_meta()` in build_index.py cannot do this: no cache-buster, no status
    code, and every failure collapses to `(name, None)` — a dead page and a live one are
    indistinguishable."""

    def test_the_fetch_carries_a_cache_buster(self, run):
        _, _, fu = run("--new-project")
        assert fu.urls and "cb=" in fu.urls[0]

    def test_it_fetches_the_stable_project_alias(self, run):
        _, _, fu = run("--new-project")
        assert fu.urls[0].startswith(f"https://{ABSENT}.vercel.app/")

    def test_the_page_that_was_deployed_passes(self, run):
        assert run("--new-project")[0] == 0

    def test_a_bare_200_with_the_wrong_page_is_not_live(self, run):
        assert run("--new-project", serve={ABSENT: _page("Some Other Page")})[0] == code(6)

    def test_a_STALE_deployment_with_the_SAME_title_is_not_live(self, run, capsys):
        """The one a title check cannot catch, and the common case: an updated doc keeps
        its title, so the previous version answers 200 and reads as success."""
        stale = _page("A Real Doc", body="the PREVIOUS version of this document")
        rc, _, _ = run("--new-project", serve={ABSENT: stale})
        assert rc == code(6)
        assert "stale deployment" in capsys.readouterr().err

    def test_a_redirect_is_refused_even_when_it_ends_in_200(self, run, monkeypatch):
        """urlopen follows 30x silently, and the documented SSO wall is a 302 to a login
        page that answers 200."""
        fr = FakeRun()
        fu = FakeUrlopen(runner=fr, redirect_to="https://vercel.com/login")
        rc, _, _ = run("--new-project", fake_run=fr, fake_url=fu)
        assert rc == code(6)

    def test_a_404_is_not_live(self, run):
        err = urllib.error.HTTPError("u", 404, "Not Found", {}, None)
        assert run("--new-project", fake_url=FakeUrlopen(error=err))[0] == code(6)

    def test_the_alias_swap_is_waited_out(self, run):
        """Found by the first REAL run, not by this suite: `vercel deploy` prints
        "Aliased" as its last line, and the fetch that followed it immediately refused a
        perfect deploy. The fakes answered instantly and could not have caught it."""
        fr = FakeRun()
        fu = FakeUrlopen(runner=fr, cold=2)
        rc, _, _ = run("--new-project", fake_run=fr, fake_url=fu)
        assert rc == 0
        doc_fetches = [u for u in fu.urls if ABSENT in u]
        assert len(doc_fetches) == 3
        assert len(set(doc_fetches)) == 3, "each retry needs a fresh cache-buster"

    def test_the_wait_is_bounded(self, run):
        """An alias that never updates is what this stage exists to catch; waiting
        forever would turn the check back into the reassurance it replaced."""
        rc, _, fu = run("--new-project", serve={ABSENT: "<html>never updates</html>"})
        assert rc == code(6)
        assert len([u for u in fu.urls if ABSENT in u]) == publish_doc.VERIFY_ATTEMPTS

    def test_an_unreachable_host_is_not_live(self, run):
        err = urllib.error.URLError("no route")
        assert run("--new-project", fake_url=FakeUrlopen(error=err))[0] == code(6)

    def test_an_escaped_title_still_publishes(self, monkeypatch, workspace, doc):
        """`render_artifact` escapes the title; nothing downstream may assume otherwise."""
        fr = FakeRun()
        monkeypatch.setattr(subprocess, "run", fr)
        monkeypatch.setattr(urllib.request, "urlopen", FakeUrlopen(runner=fr))
        rc = publish_doc.main(["--md", str(doc), "--project", "claude-skills",
                               "--type", "design", "--ref", "12",
                               "--title", "Design & Build <now>",
                               "--workspace-file", str(workspace), "--new-project"])
        assert rc == 0


# --------------------------------------------------------------------------- stage 7

class TestTheIndexRefreshIsPartOfPublishing:
    def test_the_full_stage_order(self, run):
        """Membership is not order. Asserting the whole sequence is what stops the index
        being built after it is deployed."""
        _, fr, _ = run("--new-project")
        assert fr.sequence() == [
            "ls", f"link:{ABSENT}", "deploy", "build_index",
            f"link:{publish_doc.INDEX_PROJECT}", "deploy",
            "ls",     # stage 7 re-lists to prove the index is CURRENT, not merely live
        ]

    def test_an_index_that_raced_another_publisher_is_refused(self, run):
        """Byte identity proves the live page is the page we built; it does NOT prove the
        page is current. A builds N rows, B publishes and refreshes to N+1, A deploys
        last — A's stale index passes its own byte check. The count is what catches it."""
        rc, _, _ = run("--new-project", fake_run=FakeRun(index_rows=1))
        assert rc == code(7)

    def test_an_index_with_every_row_passes(self, run):
        assert run("--new-project")[0] == 0

    def test_a_failed_index_build_is_stage_seven(self, run):
        assert run("--new-project", fake_run=FakeRun(index_rc=1))[0] == code(7)

    def test_the_index_is_verified_live_too(self, run):
        """A return code is not proof the index went live — that was stage 6's lesson."""
        _, _, fu = run("--new-project")
        assert any(u.startswith(f"https://{publish_doc.INDEX_PROJECT}.vercel.app/")
                   and "cb=" in u for u in fu.urls)

    def test_a_STALE_index_fails_the_publish(self, run):
        """The failure the index exists to prevent: the doc is live, the index is not."""
        rc, _, _ = run("--new-project",
                       serve={publish_doc.INDEX_PROJECT: "<html>yesterday</html>"})
        assert rc == code(7)

    def test_the_index_is_never_written_into_the_repo(self, run):
        """It is a gitignored build artifact; publishing must not resurrect it."""
        _, fr, _ = run("--new-project")
        outs = [c[c.index("--out") + 1] for c in fr.cmds() if "--out" in c]
        assert outs and not any(str(SCRIPTS.parent) in o for o in outs)


# --------------------------------------------------------------------------- AC1

class TestTheExitCodeIsTheVerdict:
    """AC1, table-driven: one distinct code per failing stage. Offset past argparse's
    own `2` so a usage error is never mistaken for a stage failure."""

    def test_a_clean_run_is_zero(self, run):
        assert run("--new-project")[0] == 0

    def test_stage_codes_do_not_collide_with_argparse(self):
        assert publish_doc.EXIT_BASE > 2

    @pytest.mark.parametrize("stage,extra,kw,serve", [
        (1, ("--md", "/nonexistent/x.md"), {}, None),
        (2, ("--project", "deploy"), {}, None),
        (3, ("--title", "Untitled"), {}, None),
        (4, (), {}, None),                                   # unknown project, no override
        (5, ("--new-project",), {"deploy_rc": 1}, None),
        (6, ("--new-project",), {}, {ABSENT: "<html>wrong</html>"}),
        (7, ("--new-project",), {"index_rc": 1}, None),
    ])
    def test_each_failing_stage_has_its_own_code(self, run, stage, extra, kw, serve):
        fr = FakeRun(**kw)
        rc, _, _ = run(*extra, fake_run=fr, fake_url=FakeUrlopen(runner=fr, serve=serve))
        assert rc == code(stage)


class TestAComponentFreePageIsRefused:
    """#127, at the boundary the author actually meets: stage 3, before any deploy.

    `rawgentic-plan-756` published as a roadmap with no roadmap — `class="tpl-roadmap"`,
    zero components — and every gate was green. These tests are that page.
    """

    @pytest.fixture
    def prose_doc(self, tmp_path):
        p = tmp_path / "prose-only.md"
        p.write_text("## Heading\n\nProse and two tables, no components.\n",
                     encoding="utf-8")
        return p

    def test_a_dry_run_refuses_it(self, run, prose_doc):
        assert run("--dry-run", "--md", str(prose_doc))[0] == code(3)

    def test_a_real_run_refuses_it_before_deploying_anything(self, run, prose_doc):
        """AC2. The gate runs BEFORE the deploy, so a refused page never reaches a public
        URL — the whole reason stage 3 precedes stage 5."""
        rc, fr, fu = run("--md", str(prose_doc))
        assert rc == code(3)
        assert fr.deploys() == [] and fu.urls == []

    def test_allow_prose_permits_it(self, run, prose_doc):
        assert run("--dry-run", "--md", str(prose_doc), "--allow-prose")[0] == 0

    def test_allow_prose_says_so_in_the_output(self, run, prose_doc, capsys):
        """Cross-model review, first pass (gpt-5.6-sol): the exit code was asserted and the
        message was not, so removing the suffix would have left the suite green while a
        bypassed publish reported a plain "lint gate passed". A skipped check that reports
        nothing is how a component-free page reaches a public URL looking like it passed.
        """
        run("--dry-run", "--md", str(prose_doc), "--allow-prose")
        # #130 widened the flag to BOTH component checks, so the wording moved with it.
        assert "BOTH component checks were SKIPPED" in capsys.readouterr().out

    def test_allow_prose_does_not_disable_the_other_checks(self, run, prose_doc):
        """The escape hatch is scoped to ONE check. A flag that quietly turned the whole
        lint gate off would be a far worse defect than the one it exists to work around."""
        assert run("--dry-run", "--md", str(prose_doc), "--allow-prose",
                   "--title", "Untitled")[0] == code(3)


class TestDryRun:
    """Stages 1–3 and stop, so the lint gate is reachable in CI with no network."""

    def test_it_lints_and_stops(self, run):
        rc, fr, fu = run("--dry-run")
        assert rc == 0
        assert fr.deploys() == [] and fu.urls == []

    def test_it_still_fails_on_a_lint_finding(self, run):
        assert run("--dry-run", "--title", "Untitled")[0] == code(3)

    def test_it_still_validates_the_name(self, run):
        assert run("--dry-run", "--project", "deploy")[0] == code(2)


class TestItRunsAsAnExecutable:
    """Everything else calls `main()` in-process. Deleting the `__main__` block would
    leave the documented command doing nothing, and every other test would still pass."""

    def test_the_script_runs_from_an_unrelated_cwd(self, tmp_path, workspace, doc):
        elsewhere = tmp_path / "unrelated"
        elsewhere.mkdir()
        proc = subprocess.run(
            [str(SCRIPTS / "publish_doc.py"), "--md", str(doc),
             "--out", str(tmp_path / "o.html"), "--project", "claude-skills",
             "--type", "design", "--ref", "12", "--title", "A Real Doc",
             "--workspace-file", str(workspace), "--dry-run"],
            cwd=str(elsewhere), capture_output=True, text=True, check=False)
        assert proc.returncode == 0, proc.stderr
        assert "3/7 lint gate passed" in proc.stdout
        assert (tmp_path / "o.html").exists()

    def test_it_is_executable(self):
        assert os.access(SCRIPTS / "publish_doc.py", os.X_OK)

    def test_a_refusal_exits_non_zero_for_the_shell(self, tmp_path, workspace, doc):
        proc = subprocess.run(
            [str(SCRIPTS / "publish_doc.py"), "--md", str(doc),
             "--out", str(tmp_path / "o.html"), "--project", "deploy",
             "--type", "design", "--ref", "713", "--title", "T",
             "--workspace-file", str(workspace), "--dry-run"],
            cwd=str(tmp_path), capture_output=True, text=True, check=False)
        assert proc.returncode == code(2)


# --------------------------------------------------------------------------- AC6

class TestARefusalReachesNothing:
    """The property the "nothing deployed" assertions are actually about.

    Those assertions filter out stage 3's local read-only `git show` (see
    `FakeRun.deploys`). This pins the strict version directly and by name, so the
    filtering cannot quietly become a hole: a refused run makes NO vercel call and NO
    network request, whatever else it does locally.
    """

    def test_a_refusal_makes_no_vercel_call_at_all(self, run):
        rc, fr, fu = run("--title", "Untitled")
        assert rc == code(3)
        assert [c for c, _ in fr.calls if c[:1] == ["vercel"]] == []
        assert fu.urls == []

    def test_a_refusal_runs_nothing_that_can_mutate(self, run):
        """Read-only is the whole licence for the exemption. `git show` is; these are not."""
        rc, fr, _ = run("--title", "Untitled")
        assert rc == code(3)
        mutating = {"commit", "push", "add", "checkout", "reset", "rm", "tag", "merge"}
        assert [c for c, _ in fr.calls
                if c[:1] == ["git"] and set(c[1:2]) & mutating] == []


class TestGitStaysOut:
    """AC6. Commits and PRs remain the workflows' business."""

    def test_the_script_contains_no_version_control_invocation(self):
        import ast
        tree = ast.parse((SCRIPTS / "publish_doc.py").read_text(encoding="utf-8"))
        literals = [n.value for n in ast.walk(tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        offenders = [s for s in literals
                     if s.strip() == "git" or s.strip().startswith("git ")]
        assert offenders == [], offenders


# --------------------------------------------------------------------------- AC7

class TestTheSkillCallsTheCommand:
    """AC7. The prose shrinks to judgment: what to write, which type, when to publish."""

    SKILL = SCRIPTS.parent / "SKILL.md"

    def _text(self):
        return self.SKILL.read_text(encoding="utf-8")

    def _fences(self):
        out, cur = [], None
        for line in self._text().splitlines():
            if line.startswith("```"):
                if cur is None:
                    cur = []
                else:
                    out.append("\n".join(cur))
                    cur = None
            elif cur is not None:
                cur.append(line)
        return out

    def test_a_runnable_block_invokes_the_script_with_every_required_flag(self):
        """A prose mention is not wiring: the copy-pasteable block must be the command."""
        blocks = [b for b in self._fences() if "publish_doc.py" in b]
        assert blocks, "no fenced block invokes publish_doc.py"
        for flag in ("--md", "--project", "--type", "--ref", "--title"):
            assert any(flag in b for b in blocks), flag

    def test_it_no_longer_carries_the_manual_recipe(self):
        """A copy-pasteable `vercel link`/`deploy` is the prose the script replaces.
        Naming the commands is fine; a runnable line is not."""
        bad = [ln for ln in self._text().splitlines()
               if ln.strip().startswith(("vercel link", "vercel deploy"))]
        assert bad == [], bad

    def test_every_purpose_carries_real_selection_guidance(self):
        """Shrinking the prose must not delete WHICH type to choose. A bare token list
        would satisfy a `purpose in text` check while saying nothing.

        Guidance is the LAST cell, not the second. #43 added a Template column between them, and
        reading by index silently started asserting that `design` was 12 characters of advice.
        """
        rows = {}
        for line in self._text().splitlines():
            if line.startswith("| `") and line.count("|") >= 3:
                cells = [c.strip() for c in line.strip("|").split("|")]
                rows[cells[0].strip("`")] = cells[-1]
        for purpose in publish_doc.PURPOSES:
            assert purpose in rows, f"{purpose} has no row in the type table"
            assert len(rows[purpose]) > 12, f"{purpose} has no real guidance: {rows[purpose]!r}"

    def test_skill_md_documents_the_dashboard_style(self):
        """#40/D12. `dashboard` has no `PURPOSE_STYLE` entry, so it is reachable ONLY via
        `--style` — and SKILL.md never mentioned `--style` at all, which made a whole
        template invisible to any session following the documented path. A dry run proves
        the parser accepts the route; it cannot prove the route is discoverable, so the
        sentence is asserted here.

        Deliberately NOT fixed by adding a `status` purpose: every entry in `PURPOSES`
        needs its own SKILL.md guidance row (`test_every_purpose_carries_real_selection
        _guidance`), so that spends a line either way, and a new purpose additionally
        forbids `--ref status` forever.
        """
        text = self._text()
        assert "--style dashboard" in text, (
            "SKILL.md must name the only route to the dashboard template")
        # VALUES, not keys: the claim is that no `--type` maps TO the dashboard style.
        # Keys are purpose names, so `"dashboard" not in PURPOSE_STYLE` was trivially true
        # and would have stayed green under a `{"report": "dashboard"}` mapping that
        # contradicts SKILL.md outright. Caught in review.
        assert "dashboard" not in publish_doc.PURPOSE_STYLE.values(), (
            "a --type now maps to the dashboard style; SKILL.md and D12 both need revisiting")

    def test_it_is_fifty_lines_of_prose_or_fewer(self):
        """#19 AC1. A budget nobody measures is a budget that creeps back: this file was
        205 lines, and every line of it was a rule a model had to re-read and re-perform
        correctly, forever. The number is the deliverable, so it is asserted.

        #42 WIDENED THE MEASUREMENT, not the budget, and the distinction is the whole point.
        The `--type` table carries one row per publication purpose. Adding a style adds a row,
        so a flat line count would make "ship a new style" and "let a recipe creep back" fail
        the same test — and the second is what #19 was defending against. Table rows are DATA:
        they are looked up, never performed. Prose is what a model has to re-read and re-obey.

        So rows in that table do not count, and the prose budget stays at fifty, exactly where
        #19 put it. The two guards that actually encode #19's intent — exactly ONE runnable
        block, and no step assembled by hand — are untouched and still count everything.

        This was written the same day a careless edit to this file put `main` red (D80); it is
        a reasoned widening with the intent preserved, not a number moved to make a test pass.

        #121 WIDENED THE MEASUREMENT ONCE MORE, on the same principle and for the same reason:
        a table's SEPARATOR line (`|---|---|`) is pure markdown syntax. It carries no rule for a
        model to re-read and re-obey, so counting it charged the budget for punctuation. The
        header row still counts, deliberately — it is the one table line where prose can hide, so
        exempting it would be the loophole #42 was careful not to open. **The budget is still
        fifty**, and it was NOT raised to fit #121's image section: that section is a heading plus
        data rows, and the two lines this exemption returns are the two separators already in the
        file.

        #170 RAISED THE BUDGET, 50 -> 58, and it is the first time the NUMBER moved rather than
        the measurement. That deserves more justification than a widening, so:

        The file was at exactly 50 of 50 — full — and the omission that filled it was load-bearing.
        SKILL.md named no state token at all, so no author learned that a chip's state cell is a
        closed set, or that `<label>:<level>` exists. Measured cost: `rawgentic-plan-graph` was
        published 61 minutes AFTER the compound grammar shipped, by a session running the new
        renderer, with every chip a bare severity word. The engine was current and the author was
        never told. A vocabulary documented only in a file nobody opens is not documented.

        The eight lines are a heading, ONE table header, three sentences and three blanks. The
        vocabulary itself costs nothing, because its rows are already exempt as data — which is
        #42's principle working exactly as intended, not a hole in it.

        **The intent is untouched, and that is what makes this safe.** #19 defended against
        command RECIPES creeping back into a file a model must re-read and re-obey. Nothing added
        here is a recipe: it is a lookup table plus the sentence saying the set is closed. The two
        guards that actually encode #19's intent — exactly ONE runnable block, and no step
        assembled by hand — are untouched and still count everything.

        Owner decision 2026-08-10, asked and answered before the number moved.
        """
        lines = self._text().splitlines()
        prose = [ln for ln in lines
                 if not (ln.startswith("| `") and ln.count("|") >= 3)
                 and not re.fullmatch(r"\|[\s:|-]+\|", ln.strip())]
        assert len(prose) <= 58, (
            f"SKILL.md is {len(prose)} lines of prose ({len(lines)} total); the budget is 58")

    def test_the_separator_exemption_cannot_hide_prose(self):
        """#121's own guard. Only punctuation is exempt: a header row, and any line with words
        in it, still counts — otherwise the widening becomes the loophole it must not be."""
        lines = self._text().splitlines()
        exempt = [ln for ln in lines if re.fullmatch(r"\|[\s:|-]+\|", ln.strip())]
        assert exempt, "there is at least one table separator to exempt"
        for ln in exempt:
            assert not re.search(r"[A-Za-z0-9]", ln), f"exempted a line with content: {ln!r}"

    def test_the_widened_measurement_still_counts_prose(self):
        """The widening's own guard: a row-shaped line is exempt, an ordinary line is not."""
        assert self._text().count("| `") >= 8, "the --type table is what the exemption is for"

    def test_it_points_at_the_component_vocabulary(self):
        """#127. The gap that let a roadmap publish with no roadmap: SKILL.md named none
        of the engine's 16 block types, and `docs/design-language.md` — where the per-style
        component sets actually live — was referenced by TEST FILES ONLY. No reading path
        led an author there, so an author wrote ordinary markdown and got prose wearing a
        template's CSS.

        Both halves are asserted, because a pointer to a moved or renamed file is worse
        than none: it reads as an answer and delivers nothing.

        Cross-model review, first pass (gpt-5.6-sol): a repo-relative path was wrong here.
        This is a USER skill — it installs at `~/.claude/skills/<name>` and runs from
        whatever project is bound, so `user/design-doc-publish/docs/…` resolves only from
        this repo's root and nowhere a reader would actually be. The pointer therefore uses
        the same install-rooted form as the command block above it, and the tail is checked
        to be a real file rather than a path that merely looks plausible.
        """
        text = self._text()
        tail = "skills/design-doc-publish/docs/design-language.md"
        assert tail in text, (
            "SKILL.md must name the component-vocabulary doc install-rooted, not "
            "repo-relative — a user skill does not run from this repo")
        assert "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/" + tail in text, (
            "use the same install root as the runnable command, so one convention holds")
        target = self.SKILL.parent / "docs" / "design-language.md"
        assert target.is_file(), f"SKILL.md points at {target}, which does not exist"
        assert str(target).endswith("design-doc-publish/docs/design-language.md"), (
            "the file that exists must be the one the pointer's tail names")

    def test_it_contains_exactly_one_runnable_block(self):
        """#19 AC2: zero mechanical steps. One invocation is not a mechanical step — it
        is the thing that replaced them. A SECOND block would mean a recipe came back."""
        assert self._text().count("```") == 2, "expected exactly one fenced block"

    def test_no_step_must_be_assembled_by_hand(self):
        """#19 AC2, the specific shapes that used to live here: a `vercel` incantation, a
        `curl` verify, a mktemp-and-cd index refresh."""
        bad = [ln for ln in self._text().splitlines()
               if ln.strip().startswith(("vercel ", "curl ", "cd ", "D=$(mktemp",
                                         "python3 "))]
        assert bad == [], bad

    def test_it_keeps_the_safety_rules_a_script_cannot_enforce(self):
        text = self._text()
        assert "public" in text.lower() and "secret" in text.lower()
        assert "no blanket" in text.lower() or "No blanket" in text


# --------------------------------------------------------------------------- #121

class TestRelativeAssetsShipWithThePage:
    """#121. A relative image rendered, passed the lint gate — `_is_external` correctly calls a
    relative path internal — and then the publisher shipped ONLY the page, so the reference 404d
    on a public URL. Nothing in render, lint or deploy reported it, and the author saw a working
    image locally. Owner chose option 1: package the assets."""

    @staticmethod
    def _doc_with(doc, body):
        doc.write_text("## Heading\n\nSome body text.\n\n"
                       "```callout\nwarn | Read this first\nOne real component.\n```\n\n"
                       "```options\nDebounce | Smallest diff | Re-done per call site | chosen\n"
                       "```\n\n"
                       f"{body}\n", encoding="utf-8")

    def test_a_relative_image_ships_beside_the_page(self, run, doc, tmp_path):
        """AC1 + AC2, the positive case."""
        (tmp_path / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
        self._doc_with(doc, "![d](diagram.png)")
        rc, fr, _ = run("--new-project")
        assert rc == 0, "the publish must succeed"
        shipped = fr.shipped["claude-skills-design-12"]
        assert "index.html" in shipped
        assert shipped.get("diagram.png") == b"\x89PNG\r\n\x1a\nfake", sorted(shipped)

    def test_a_nested_relative_path_keeps_its_subdirectory(self, run, doc, tmp_path):
        (tmp_path / "assets").mkdir()
        (tmp_path / "assets" / "diagram.png").write_bytes(b"nested")
        self._doc_with(doc, "![d](assets/diagram.png)")
        rc, fr, _ = run("--new-project")
        assert rc == 0
        shipped = fr.shipped["claude-skills-design-12"]
        assert shipped.get("assets/diagram.png") == b"nested", sorted(shipped)

    def test_several_references_to_one_file_ship_it_once(self, run, doc, tmp_path):
        (tmp_path / "d.png").write_bytes(b"once")
        self._doc_with(doc, "![a](d.png) and ![b](d.png)")
        rc, fr, _ = run("--new-project")
        assert rc == 0
        assert sorted(fr.shipped["claude-skills-design-12"]) == ["d.png", "index.html"]

    def test_a_missing_asset_is_refused_rather_than_published_as_a_404(self, run, doc, capsys):
        """AC2's negative case, and the whole point of AC1: the failure used to be SILENT."""
        self._doc_with(doc, "![d](missing.png)")
        rc, fr, _ = run("--new-project")
        assert rc != 0, "publishing a page whose asset does not exist must fail"
        assert fr.deployed == {}, "nothing may be deployed once an asset is known missing"
        err = capsys.readouterr().err
        assert "missing.png" in err, err

    def test_a_reference_escaping_the_documents_directory_is_refused(self, run, doc, tmp_path):
        """AC3. The doc lives in tmp_path; `../` leaves it."""
        outside = tmp_path.parent / "outside-secret.png"
        outside.write_bytes(b"not yours")
        self._doc_with(doc, "![d](../outside-secret.png)")
        rc, fr, _ = run("--new-project")
        assert rc != 0
        assert fr.deployed == {}
        for tree in fr.shipped.values():
            assert "outside-secret.png" not in " ".join(tree)

    def test_an_absolute_path_reference_is_refused(self, run, doc, tmp_path):
        """A rooted `/etc/x` is not relative to the document at all."""
        self._doc_with(doc, "![d](/rooted.png)")
        rc, fr, _ = run("--new-project")
        assert rc != 0
        assert fr.deployed == {}

    def test_a_symlinked_asset_is_refused(self, run, doc, tmp_path):
        """Consistent with `_check_paths`' refusal of a symlinked `--md`: these pages are PUBLIC
        and this script follows what it is given, so a link pointing at a readable secret would
        be copied into a public deploy."""
        secret = tmp_path.parent / "secret.png"
        secret.write_bytes(b"a readable secret")
        link = tmp_path / "innocent.png"
        link.symlink_to(secret)
        self._doc_with(doc, "![d](innocent.png)")
        rc, fr, _ = run("--new-project")
        assert rc != 0
        assert fr.deployed == {}

    def test_a_page_with_no_relative_reference_ships_exactly_as_before(self, run, doc):
        """The whole existing corpus is this case, so it must be untouched."""
        rc, fr, _ = run("--new-project")
        assert rc == 0
        assert sorted(fr.shipped["claude-skills-design-12"]) == ["index.html"]

    def test_a_fragment_and_a_data_uri_are_not_assets(self, run, doc):
        self._doc_with(doc, "[jump](#heading) and ![i](data:image/png;base64,AAAA)")
        rc, fr, _ = run("--new-project")
        assert rc == 0
        assert sorted(fr.shipped["claude-skills-design-12"]) == ["index.html"]

    def test_a_percent_encoded_space_resolves_to_the_real_file(self, run, doc, tmp_path):
        (tmp_path / "my diagram.png").write_bytes(b"spaced")
        self._doc_with(doc, "![d](my%20diagram.png)")
        rc, fr, _ = run("--new-project")
        assert rc == 0
        shipped = fr.shipped["claude-skills-design-12"]
        assert shipped.get("my diagram.png") == b"spaced", sorted(shipped)

    def test_a_query_string_is_stripped_before_the_file_is_found(self, run, doc, tmp_path):
        (tmp_path / "d.png").write_bytes(b"queried")
        self._doc_with(doc, "![d](d.png?v=2)")
        rc, fr, _ = run("--new-project")
        assert rc == 0
        assert fr.shipped["claude-skills-design-12"].get("d.png") == b"queried"


class TestTheAssetRuleIsDocumented:
    """AC4: SKILL.md and the renderer docstring state what an author may write, and what happens
    otherwise — with no claim beyond what is enforced."""

    def _skill(self):
        return (Path(publish_doc.__file__).resolve().parent.parent
                / "SKILL.md").read_text(encoding="utf-8")

    def test_skill_md_states_the_rule_and_the_failure(self):
        text = self._skill()
        assert "relative" in text.lower()
        assert "assets/diagram.png" in text or "diagram.png" in text
        for claim in ("ships", "refus"):
            assert claim in text.lower(), claim

    def test_skill_md_does_not_promise_an_absolute_image_works(self):
        """#23 refuses a cross-host image; the docs must not imply otherwise."""
        text = self._skill().lower()
        assert "cross-host" in text or "another host" in text or "external" in text


class TestOnlyDeclaredAssetTypesTravel:
    """Step 11 (High, security). Containment stops a reference LEAVING the document's directory
    and says nothing about what sits INSIDE it. With `is_file()` as the only content gate, a
    document — and these are routinely generated, not hand-written — could name a guessed local
    file and publish its bytes to a public URL. Measured before the fix: `.env` shipped its bytes
    verbatim."""

    @staticmethod
    def _doc_with(doc, body):
        doc.write_text("## Heading\n\nSome body text.\n\n"
                       "```callout\nwarn | Read this first\nOne real component.\n```\n\n"
                       "```options\nDebounce | Smallest diff | Re-done per call site | chosen\n"
                       "```\n\n"
                       f"{body}\n", encoding="utf-8")

    @pytest.mark.parametrize("secret", [".env", "credentials.json", "id_rsa", "notes.md",
                                        "config.yaml", "dump.sql", "app.py"])
    def test_a_non_asset_file_in_the_directory_is_refused(self, run, doc, tmp_path, secret):
        (tmp_path / secret).write_text("NOT-A-REAL-SECRET-example-only\n", encoding="utf-8")
        self._doc_with(doc, f"![x]({secret})")
        rc, fr, _ = run("--new-project")
        assert rc != 0, f"{secret} must not be publishable"
        assert fr.deployed == {}, "nothing may deploy once a non-asset reference is seen"
        for tree in fr.shipped.values():
            assert not any("NOT-A-REAL-SECRET" in v.decode("utf-8", "replace") for v in tree.values())

    @pytest.mark.parametrize("name", ["d.png", "d.JPG", "d.jpeg", "d.gif", "d.webp", "d.avif",
                                      "d.ico", "d.svg"])
    def test_every_declared_asset_type_still_ships(self, run, doc, tmp_path, name):
        (tmp_path / name).write_bytes(b"asset-bytes")
        self._doc_with(doc, f"![x]({name})")
        rc, fr, _ = run("--new-project")
        assert rc == 0, name
        assert fr.shipped["claude-skills-design-12"].get(name) == b"asset-bytes"

    def test_the_suffix_check_is_case_insensitive_and_uses_the_real_suffix(self, run, doc,
                                                                          tmp_path):
        """`.env` under a name ending in something asset-shaped must not sneak through, and an
        upper-case extension is the same extension."""
        (tmp_path / "sneaky.png.env").write_text("NOT-A-REAL-SECRET-example-only\n", encoding="utf-8")
        self._doc_with(doc, "![x](sneaky.png.env)")
        assert run("--new-project")[0] != 0


class TestTheAssetIsOpenedOnceNotCheckedThenReopened:
    """Step 11 (High, security). Path-based checks followed by `copyfile` reopening BY NAME is a
    race: between them the final component can become a symlink and the copy would follow it into
    a public deploy. The file is now opened once with `O_NOFOLLOW` and copied from that
    descriptor."""

    def test_a_symlink_swapped_in_after_the_check_is_not_followed(self, tmp_path):
        """The race, made deterministic. `stage_assets` is called directly because the swap has to
        happen between its own two steps, which no CLI-level test can straddle."""
        secret = tmp_path / "outside.png"
        secret.write_bytes(b"a readable secret")
        base = tmp_path / "doc"
        base.mkdir()
        real = base / "d.png"
        real.write_bytes(b"the real asset")

        page = '<html><head><title>T</title></head><body><img src="d.png"></body></html>'
        original_open = os.open

        def swap_then_open(path, flags, *a, **kw):
            # Fire once, on the asset itself: replace it with a symlink out of the directory at
            # the instant the publisher opens it.
            if str(path) == str(real) and real.exists() and not real.is_symlink():
                real.unlink()
                real.symlink_to(secret)
            return original_open(path, flags, *a, **kw)

        with tempfile.TemporaryDirectory() as tmp:
            try:
                publish_doc.os.open = swap_then_open
                with pytest.raises(publish_doc.StageError):
                    publish_doc.stage_assets(page, base, Path(tmp))
            finally:
                publish_doc.os.open = original_open
            shipped = {p.name: p.read_bytes() for p in Path(tmp).rglob("*") if p.is_file()}
            assert b"a readable secret" not in b"".join(shipped.values()), shipped


class TestNoRendererOwnedRelativeReferenceExists:
    """Step 11 (Medium, ambiguity_flag). The single default-fixture test asserted a claim about the
    whole corpus that it could not establish: if any template or VDL pack emitted its own relative
    url, every existing document would start failing at stage 5. The reviewer could not check that
    from the diff. This makes the claim a permanent guard instead of a one-off measurement."""

    BODY = "## H\n\nbody\n\n```callout\nwarn | x\ny\n```\n"

    @pytest.mark.parametrize("style", sorted(publish_doc.RENDER._TEMPLATES))
    def test_no_style_emits_a_relative_reference_of_its_own(self, style):
        page = publish_doc.RENDER.render_artifact(self.BODY, title="T", style=style,
                                                  doc_id="guard")
        assert publish_doc._LINT.internal_references(page) == [], style

    def test_every_committed_page_has_its_assets_on_disk(self):
        """The other half: a committed doc whose asset is missing would now fail to publish, so
        the repo itself is checked. This is what proves #121 fixes rather than breaks the corpus —
        `2026-08-02-template-mockups.html` carries 21 `./shots/*.png` references that were 404ing
        on the published page before this change."""
        planning = (Path(publish_doc.__file__).resolve().parents[1] / "docs" / "planning")
        if not planning.is_dir():          # a checkout without the docs tree is not a failure
            pytest.skip("no docs/planning in this tree")
        checked = 0
        for page in sorted(planning.glob("*.html")):
            for ref in publish_doc._LINT.internal_references(
                    page.read_text(encoding="utf-8", errors="replace")):
                target = planning / publish_doc._asset_target(ref)
                assert target.is_file(), f"{page.name} references {ref}, which is not on disk"
                assert target.suffix.lower() in publish_doc._ASSET_SUFFIXES, (
                    f"{page.name} references {ref}, which this publisher would refuse")
                checked += 1
        mockups = planning / "2026-08-02-template-mockups.html"
        if mockups.is_file():          # the corpus that motivated the floor is present
            assert checked >= 21, (
                f"expected the template-mockups shots to be checked; only saw {checked}")
        elif checked == 0:
            # Neither the original corpus page nor any other published page is here, so the
            # loop above asserted nothing. Say so instead of reporting a silent pass: a
            # dormant guard that looks green is worse than one that admits it did not run.
            pytest.skip("no published pages in docs/planning yet, so nothing was checked")


class TestAPageMissingItsStyleDevicesIsRefused:
    """#130, at the same boundary as #127's check: stage 3, before any deploy.

    This is the page `check_blocks` cannot see — it carries a real component, so the floor
    is satisfied, and it still opens with none of the furniture its own style is built
    around. The campaign log in this repo was exactly that page.
    """

    @pytest.fixture
    def partial_doc(self, tmp_path):
        """A `roadmap` with a `chips` block and none of `stats`/`callout`/`phases`."""
        p = tmp_path / "partial-roadmap.md"
        p.write_text("## Heading\n\nSome prose.\n\n```chips\nmerged | done\n```\n",
                     encoding="utf-8")
        return p

    @pytest.fixture
    def full_doc(self, tmp_path):
        p = tmp_path / "full-roadmap.md"
        p.write_text(
            "## Heading\n\nSome prose.\n\n"
            "```stats\n82 | children merged\n```\n\n"
            "```callout\nwarn | Read this first\nThe one thing to know.\n```\n\n"
            "```phases\nWave 1 | 3 of 12 done | warn\n  FA-1 | Fan curve stalls | crit\n```\n",
            encoding="utf-8")
        return p

    def test_a_dry_run_refuses_it(self, run, partial_doc):
        assert run("--dry-run", "--md", str(partial_doc), "--style", "roadmap")[0] == code(3)

    def test_the_zero_block_check_does_NOT_catch_this_page(self, run, partial_doc):
        """The reason #130 exists as a separate issue: one component of any kind clears
        `check_blocks`, so without this check the page publishes green."""
        page = publish_doc.RENDER.render_artifact(
            partial_doc.read_text(encoding="utf-8"), title="T", style="roadmap")
        assert publish_doc.CHECK_BLOCKS(page) == []
        assert publish_doc.CHECK_STYLE_DEVICES(page) != []

    def test_a_real_run_refuses_it_before_deploying_anything(self, run, partial_doc):
        rc, fr, fu = run("--md", str(partial_doc), "--style", "roadmap")
        assert rc == code(3)
        assert fr.deploys() == [] and fu.urls == []

    def test_carrying_every_device_passes(self, run, full_doc):
        assert run("--dry-run", "--md", str(full_doc), "--style", "roadmap")[0] == 0

    def test_allow_prose_permits_it(self, run, partial_doc):
        assert run("--dry-run", "--md", str(partial_doc), "--style", "roadmap",
                   "--allow-prose")[0] == 0

    def test_allow_prose_says_BOTH_checks_were_skipped(self, run, partial_doc, capsys):
        """The flag now covers two checks, so its report must say so. A message naming only
        the component check would understate what was disabled — and a flag whose output
        understates what it turned off is its own defect."""
        run("--dry-run", "--md", str(partial_doc), "--style", "roadmap", "--allow-prose")
        out = capsys.readouterr().out
        assert "component checks were SKIPPED" in out

    def test_allow_prose_does_not_disable_the_other_checks(self, run, partial_doc):
        assert run("--dry-run", "--md", str(partial_doc), "--style", "roadmap",
                   "--allow-prose", "--title", "Untitled")[0] == code(3)


class TestAllowProseDoesNotReachTheStructuralCheck:
    """Cross-model review of the high-risk commits, and the reasoning is the whole point of
    the split.

    `--allow-prose` means "this document really is all prose". An unknown template class and
    two `<body>` tags are not statements about prose — they are structural corruption, a
    renderer defect or a hand-edited page, which is exactly what the design says must fail
    closed. While those findings lived inside the flag, the flag waved through precisely the
    inputs the fail-closed rule exists to stop.

    A REAL rendered page is used and its class swapped, so `lint()` itself stays clean and
    the refusal can only be the classification check — a hand-built page would fail on stamp
    and contrast and the test would pass for the wrong reason.
    """

    def _rendered(self, body, style="roadmap"):
        return publish_doc.RENDER.render_artifact(
            body, title="Real Title", style=style, doc_id="d",
            generated_at="2026-08-01 12:00 MDT")

    ALL_DEVICES = ("intro\n\n"
                   "```stats\n82 | children merged\n```\n\n"
                   "```callout\nwarn | Read this first\nOne real component.\n```\n\n"
                   "```phases\nWave 1 | 3 of 12 done | warn\n  FA-1 | Stalls | crit\n```\n")

    def test_the_baseline_page_passes_the_gate_outright(self):
        """Otherwise the assertions below could pass on an unrelated defect."""
        publish_doc.gate(self._rendered(self.ALL_DEVICES))

    def test_an_unknown_class_is_refused_even_with_allow_prose(self):
        page = self._rendered(self.ALL_DEVICES).replace("tpl-roadmap", "tpl-nosuchstyle")
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.gate(page, skip_component_checks=True)
        assert "tpl-nosuchstyle" in str(e.value)

    def test_two_body_classes_are_refused_even_with_allow_prose(self):
        page = self._rendered(self.ALL_DEVICES).replace(
            "</body>", '<body class="tpl-spec"></body></body>')
        with pytest.raises(publish_doc.StageError) as e:
            publish_doc.gate(page, skip_component_checks=True)
        assert "elements with a template class" in str(e.value)

    def test_allow_prose_still_forgives_a_missing_device(self):
        """The flag keeps doing its actual job — only the structural pair left its reach."""
        publish_doc.gate(self._rendered("intro\n\n```chips\nmerged | done\n```\n"),
                         skip_component_checks=True)


class TestTheFlagHasAnHonestNameAndTheOldOneStillWorks:
    """#151. `--allow-prose` named ONE check honestly until #130 put a second behind it —
    "carries components, but not the ones its style opens with" is not a statement about
    prose. The old name is kept as a working ALIAS rather than deprecated, because it
    appears in committed docs and in this repo's own history: breaking it costs something
    and buys nothing.
    """

    @pytest.fixture
    def partial_doc(self, tmp_path):
        p = tmp_path / "partial-roadmap.md"
        p.write_text("## Heading\n\nProse.\n\n```chips\nmerged | done\n```\n", encoding="utf-8")
        return p

    def test_the_new_name_skips_the_component_checks(self, run, partial_doc):
        assert run("--dry-run", "--md", str(partial_doc), "--style", "roadmap",
                   "--skip-component-checks")[0] == 0

    def test_the_old_name_still_works(self, run, partial_doc):
        assert run("--dry-run", "--md", str(partial_doc), "--style", "roadmap",
                   "--allow-prose")[0] == 0

    def test_without_either_name_the_page_is_refused(self, run, partial_doc):
        assert run("--dry-run", "--md", str(partial_doc), "--style", "roadmap")[0] == code(3)

    def test_the_output_line_names_the_new_flag(self, run, partial_doc, capsys):
        run("--dry-run", "--md", str(partial_doc), "--style", "roadmap", "--allow-prose")
        out = capsys.readouterr().out
        assert "--skip-component-checks: BOTH component checks were SKIPPED" in out, \
            "the alias must report under the canonical name, not the one that was typed"

    def test_neither_name_disables_the_other_lint_checks(self, run, partial_doc):
        assert run("--dry-run", "--md", str(partial_doc), "--style", "roadmap",
                   "--skip-component-checks", "--title", "Untitled")[0] == code(3)


class TestTelemetryCanReachThePublishPath:
    """#152. `render_artifact` has always taken a `telemetry` mapping and rendered a
    **Run telemetry** section from it, and the WF2 design-artifact step passes one. This
    script could not, so a page created by that step and re-published HERE silently lost
    the whole section — measured on `docs/planning/campaign-log.html` during #130, where
    the only copy lived in the generated file and the records behind it sit in an untracked
    store. A silently dropped section is the defect class; malformed input fails loud.
    """

    # A real run-record shape, not arbitrary pairs. `_telemetry_html` reads the
    # `work_summary.py` run-record structure and renders a visible "telemetry unavailable"
    # placeholder for anything it does not recognise — so a test using invented keys would
    # have asserted against the placeholder and proved nothing.
    TELEMETRY = {"issue": {"number": 152, "type": "chore", "complexity": "standard"},
                 "lane": "full",
                 "tests": {"added": 3, "passing": 1997, "total": 2000},
                 "security_scan": {"ran": True, "blocking_resolved": 0, "advisory": 0,
                                   "skipped": ["iac", "sca"]}}

    @pytest.fixture
    def full_doc(self, tmp_path):
        p = tmp_path / "full-roadmap.md"
        p.write_text(
            "## Heading\n\nProse.\n\n```stats\n82 | children\n```\n\n"
            "```callout\nwarn | Read this first\nOne real component.\n```\n\n"
            "```phases\nWave 1 | 3 of 12 | warn\n  FA-1 | Stalls | crit\n```\n",
            encoding="utf-8")
        return p

    def _tel(self, tmp_path, payload):
        f = tmp_path / "telemetry.json"
        f.write_text(payload if isinstance(payload, str) else json.dumps(payload),
                     encoding="utf-8")
        return f

    def test_omitting_it_changes_nothing(self, run, full_doc, tmp_path):
        out = tmp_path / "a.html"
        assert run("--dry-run", "--md", str(full_doc), "--style", "roadmap",
                   "--out", str(out))[0] == 0
        assert "Run telemetry" not in out.read_text(encoding="utf-8")

    def test_passing_it_renders_the_section(self, run, full_doc, tmp_path):
        out = tmp_path / "b.html"
        assert run("--dry-run", "--md", str(full_doc), "--style", "roadmap",
                   "--out", str(out),
                   "--telemetry", str(self._tel(tmp_path, self.TELEMETRY)))[0] == 0
        page = out.read_text(encoding="utf-8")
        assert "Run telemetry" in page
        assert "1997/2000 passing" in page
        assert "#152" in page
        assert "telemetry unavailable" not in page, \
            "an unrecognised record renders a placeholder — that would prove nothing"

    def test_it_matches_what_the_design_artifact_step_produces(self, full_doc, tmp_path):
        """The point of the issue: the two render paths must agree, asserted rather than
        eyeballed."""
        direct = publish_doc.RENDER.render_artifact(
            full_doc.read_text(encoding="utf-8"), title="T", style="roadmap", doc_id="d",
            generated_at="2026-08-01 12:00 MDT", telemetry=self.TELEMETRY)
        viaflag = publish_doc.render(
            full_doc, tmp_path / "c.html", title="T", subtitle="", style="roadmap",
            doc_id="d", telemetry=publish_doc.load_telemetry(
                self._tel(tmp_path, self.TELEMETRY)))
        keep = lambda s: re.sub(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} M[DS]T", "STAMP", s)
        assert keep(direct) == keep(viaflag)

    @pytest.mark.parametrize("payload,fragment", [
        ("{not json", "not valid JSON"),
        ("[1, 2, 3]", "must hold a JSON object"),
    ])
    def test_unusable_input_is_a_loud_failure_not_a_dropped_section(
            self, run, full_doc, tmp_path, payload, fragment):
        rc, _, _ = run("--dry-run", "--md", str(full_doc), "--style", "roadmap",
                       "--telemetry", str(self._tel(tmp_path, payload)))
        assert rc == code(1), "a section that vanishes silently is the whole defect class"

    def test_a_missing_file_is_a_loud_failure(self, run, full_doc, tmp_path):
        rc, _, _ = run("--dry-run", "--md", str(full_doc), "--style", "roadmap",
                       "--telemetry", str(tmp_path / "nope.json"))
        assert rc == code(1)

    def test_an_EMPTY_object_is_allowed_and_renders_the_placeholder(self, run, full_doc, tmp_path):
        """The obvious validation would reject this, and it would be wrong. `render_artifact`
        branches on `telemetry is not None`, and `_telemetry_html` renders `{}` as a visible
        "telemetry unavailable" placeholder — "a record present but empty", which its own
        comment distinguishes from `None`. Rejecting it would make this flag unable to express
        a state the renderer supports deliberately."""
        out = tmp_path / "d.html"
        assert run("--dry-run", "--md", str(full_doc), "--style", "roadmap",
                   "--out", str(out), "--telemetry", str(self._tel(tmp_path, {})))[0] == 0
        page = out.read_text(encoding="utf-8")
        assert "Run telemetry" in page and "telemetry unavailable" in page

    @pytest.mark.parametrize("payload", [
        {"tsets": {"passing": 1997}},                 # typo for `tests`
        {"nothing": "recognisable"},
        {"issue": "not-an-object"},
    ])
    def test_a_record_the_renderer_cannot_read_is_a_LOUD_failure(
            self, run, full_doc, tmp_path, payload):
        """Cross-model review caught my claim being overstated: `load_telemetry` validated only
        JSON shape, so a typoed record published happily and rendered "telemetry unavailable" —
        a successful exit whose figures were discarded.

        Validated by asking the RENDERER rather than re-implementing its field predicate, because
        a second copy of that judgement is the drift this codebase keeps paying for."""
        rc, _, _ = run("--dry-run", "--md", str(full_doc), "--style", "roadmap",
                       "--telemetry", str(self._tel(tmp_path, payload)))
        assert rc == code(1)

    def test_hostile_telemetry_values_are_escaped_on_the_published_page(self, run, full_doc,
                                                                        tmp_path):
        """Caller-controlled telemetry reaches generated HTML, so the escaping is asserted on
        the PUBLISH path rather than trusted.

        Note the assertion shape: `onerror=alert(1)` survives as visible TEXT once `<` and `"`
        are escaped, so grepping for that substring proves nothing — the same false alarm a
        crude detector raised during #57. The real property is that the tag characters are
        escaped and the page carries no script."""
        payload = {"lane": "<script>alert(1)</script>",
                   "issue": {"number": '"><img src=x onerror=alert(1)>', "type": "x",
                             "complexity": "y"},
                   "tests": {"added": 1, "passing": 1, "total": 1}}
        out = tmp_path / "hostile.html"
        assert run("--dry-run", "--md", str(full_doc), "--style", "roadmap",
                   "--out", str(out), "--telemetry", str(self._tel(tmp_path, payload)))[0] == 0
        page = out.read_text(encoding="utf-8")
        assert "<script>alert(1)</script>" not in page
        assert "&lt;script&gt;" in page
        assert '"><img' not in page
        assert page.count("<script") == 0
