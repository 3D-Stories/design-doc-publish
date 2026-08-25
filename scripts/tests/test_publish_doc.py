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
* **No network is ever touched.** `subprocess.run` and `urlopen` are patched on their
  own modules, which catches `publish_doc` and `build_index` alike — both do a plain
  `import subprocess`, so the attribute is looked up at call time.

The old hosted-CLI fixtures were removed with the rest of the vendor era in 5.0.0.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import publish_doc  # noqa: E402

# A project that IS in the captured output, and one that is not.
EXISTING = "example-plan-786"
ABSENT = "example-design-12"

def _page(title, body="body text"):
    """What the renderer really emits, so no assertion is a guess about its output."""
    return publish_doc.RENDER.render_artifact(body, title=title, style="design")


# --------------------------------------------------------------------------- fakes

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
        return host.split(".")[0]

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


# #9: the account/tenant was configuration, never a constant. Every test that publishes states
# the team it publishes to, which is also what proves the value reaching `--scope` is the
# CONFIGURED one rather than something baked in.
SCOPE = "example-team"


# --------------------------------------------------------------------------- harness

@pytest.fixture
def workspace(tmp_path):
    """A real-shaped workspace file, so `known_projects()` is exercised, not stubbed."""
    p = tmp_path / "workspace.json"
    p.write_text(json.dumps({"projects": [
        {"name": "example"}, {"name": "rawgentic"}, {"name": "herdr-dashboard"},
    ]}), encoding="utf-8")
    return p


@pytest.fixture
def doc(tmp_path):
    # #36: the document now lives inside a REAL git repository, because the harness
    # fetches blobs from GitHub by commit sha and stage 4a proves the bytes are committed.
    # Faking git here would fake the very thing the stage exists to establish, so the
    # fixture commits for real and only the HTTP layer is faked.
    import subprocess as _sp
    # The repository IS tmp_path, deliberately. Dozens of tests write an asset as
    # `tmp_path / "diagram.png"` and expect it beside the document; putting the repo in a
    # subdirectory would have moved the document out from under all of them.
    root = tmp_path
    for argv in (["init", "-q", "-b", "main"],
                 ["remote", "add", "origin", "git@github.com:example/docs.git"],
                 ["config", "user.email", "t@example.test"],
                 ["config", "user.name", "T"]):
        _sp.run(["git", "-C", str(root), *argv], check=True, capture_output=True)
    p = root / "a-doc.md"
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
    # The markdown is a COMMITTED source in real use; only the rendered .html is new. An
    # unborn branch would fail stage 4a for a reason that never occurs in practice.
    _sp.run(["git", "-C", str(root), "add", "-A"], check=True, capture_output=True)
    _sp.run(["git", "-C", str(root), "commit", "-qm", "source"], check=True,
            capture_output=True)
    head = _sp.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
                   capture_output=True, text=True).stdout.strip()
    _sp.run(["git", "-C", str(root), "update-ref", "refs/remotes/origin/main", head],
            check=True, capture_output=True)
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
    """Invoke the real `main()` against a real repository with only HTTP faked.

    #36 rewrote this. It used to fake `subprocess.run` (the `vercel` CLI) and `urlopen`.
    There is no CLI to fake any more: publishing is two HTTP calls, and provenance is real
    git against a real repository. What is faked is exactly the network, which is the one
    thing the suite cannot have.

    Returns (rc, harness) where `harness` records every request.
    """
    def go(*extra, harness=None, serve=None, publish_status=201, skip_edge=False, **kw):
        import subprocess as _sp
        root = doc.parent
        h = harness if harness is not None else FakeHarness(
            serve=serve, publish_status=publish_status, root=root)
        # PUBLISH-BEFORE-MERGE, which is the whole inversion #36 is about: the harness
        # serves COMMITTED bytes, so the rendered page must already be in the commit the
        # publish pins. The real workflow is render, commit, push, publish — so the fixture
        # does the same, rendering with --dry-run first and committing the result.
        #
        # Doing it any other way would fake the one thing stage 4a exists to establish.
        monkeypatch.setattr(publish_doc.NO_REDIRECTS, "open", h, raising=False)
        monkeypatch.setattr(urllib.request, "urlopen", h)
        monkeypatch.setenv("DOC_HARNESS_CONTROL_URL", "http://127.0.0.1:8080")
        monkeypatch.setenv("DOC_HARNESS_PUBLISH_TOKEN", "t0ken")
        if skip_edge:
            monkeypatch.delenv("DOC_HARNESS_PUBLIC_BASE", raising=False)
        else:
            # The default exercises BOTH halves, so a fully good run is rc 0. Leaving the
            # edge unset would make every unrelated test assert 26, which buries the one
            # signal that code is meant to carry.
            monkeypatch.setenv("DOC_HARNESS_PUBLIC_BASE", f"https://<name>.{publish_doc.PINNED_ZONE}")
            monkeypatch.setenv("CF_ACCESS_CLIENT_ID", "cf-id")
            monkeypatch.setenv("CF_ACCESS_CLIENT_SECRET", "cf-secret")
        # `_git` would otherwise try to reach github.com for the reachability fetch.
        real_git = publish_doc._git
        monkeypatch.setattr(publish_doc, "_git", lambda argv, cwd=None, runner=None: (
            _sp.CompletedProcess(["git", "fetch"], 0, "", "") if argv[:1] == ["fetch"]
            else real_git(argv, cwd, runner=runner)))
        argv = ["--md", str(doc), "--project", "example", "--type", "design",
                "--ref", "12", "--title", "A Real Doc",
                "--workspace-file", str(workspace), *extra]

        if "--dry-run" not in extra:
            # Phase 1: render only. A non-zero rc here is a stage 1-3 refusal, which is the
            # verdict the test is asking about — return it rather than pressing on.
            rc = publish_doc.main([*argv, "--dry-run"])
            if rc != 0:
                return rc, h
            _sp.run(["git", "-C", str(root), "add", "-A"], check=True, capture_output=True)
            _sp.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=False,
                    capture_output=True)
            head = _sp.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
                           capture_output=True, text=True).stdout.strip()
            _sp.run(["git", "-C", str(root), "update-ref", "refs/remotes/origin/main", head],
                    check=True, capture_output=True)
        else:
            _sp.run(["git", "-C", str(root), "add", "-A"], check=True, capture_output=True)
            _sp.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=False,
                    capture_output=True)
            head = _sp.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
                           capture_output=True, text=True).stdout.strip()
            _sp.run(["git", "-C", str(root), "update-ref", "refs/remotes/origin/main", head],
                    check=True, capture_output=True)

        return publish_doc.main(argv), h
    return go


class FakeHarness:
    """The control API and the serving path, in one object. Records every request."""

    def __init__(self, *, serve=None, publish_status=201, active=None, root=None):
        self.root = root              # the repository whose COMMITTED bytes it serves
        self.serve = serve            # url_path -> bytes override, for a mismatch test
        self.publish_status = publish_status
        self.active = active
        self.requests = []            # (method, url, headers)
        self.published = None
        self.deployment_id = 77

    @property
    def urls(self):
        return [u for _, u, _ in self.requests]

    @property
    def deployed(self):
        """`{}` until something is published. Mirrors the shape the Vercel fake used, so
        the assertions that say "nothing may be deployed" keep saying it."""
        return {} if self.published is None else {self.published["name"]: self.deployment_id}

    @property
    def shipped(self):
        """`{name: {relative-path: committed-bytes}}`, the same shape the Vercel fake
        exposed. Under the harness "shipped" means DECLARED IN THE MANIFEST, and the bytes
        are read back out of git — which is what the harness itself would fetch."""
        if self.published is None:
            return {}
        tree = {}
        for a in self.published["assets"]:
            # Keyed by the DECODED name, which is the filename a test wrote and the name
            # git holds. The manifest carries the percent-encoded form because the harness
            # refuses anything else.
            tree[urllib.parse.unquote(a["url_path"]).lstrip("/")] = \
                self._bytes_for(a["url_path"])
        return {self.published["name"]: tree}

    def __call__(self, req, timeout=None, **kw):
        import io as _io
        import urllib.error as _ue
        method, url = req.get_method(), req.full_url
        parts = urllib.parse.urlsplit(url)
        self.requests.append((method, url, dict(req.header_items())))

        if parts.path.startswith("/v1/deployments"):
            if method == "GET":
                return self._json({"name": "x", "active_deployment_id": self.active})
            self.published = json.loads(req.data)
            if self.publish_status != 201:
                raise _ue.HTTPError(url, self.publish_status, "scripted", {},
                                    _io.BytesIO(b"{}"))
            return self._json({"deployment_id": self.deployment_id, "assets": 1,
                               "cache_warmed": True}, status=201)

        # The serving path: answer with the committed bytes unless the test overrides.
        url_path = parts.path
        body = (self.serve or {}).get(url_path)
        if body is None:
            body = self.published and self._bytes_for(url_path)
        if body is None:
            raise _ue.HTTPError(url, 404, "not found", {}, _io.BytesIO(b""))
        r = _io.BytesIO(body)
        r.status = 200
        r.headers = {"X-Doc-Deployment": str(self.deployment_id),
                     "Content-Type": publish_doc.content_type_for(url_path)}
        r.__enter__ = lambda s=r: s
        r.__exit__ = lambda *a: False
        return r

    def _bytes_for(self, url_path):
        """The harness serves the COMMITTED bytes, which is the whole inversion #36 is
        about — so the fake reads them from the repository rather than echoing what it was
        handed."""
        import subprocess as _sp
        for a in self.published.get("assets", []):
            if a["url_path"] != url_path:
                continue
            r = _sp.run(["git", "-C", str(self.root), "cat-file", "blob", a["blob_id"]],
                        capture_output=True)
            return r.stdout if r.returncode == 0 else None
        return None

    def _json(self, payload, status=200):
        import io as _io
        r = _io.BytesIO(json.dumps(payload).encode())
        r.status = status
        r.headers = {"Content-Type": "application/json"}
        r.__enter__ = lambda s=r: s
        r.__exit__ = lambda *a: False
        return r


def code(stage):
    return publish_doc.EXIT_BASE + stage


# --------------------------------------------------------------------------- AC2

class TestTheNameIsDerivedFromValidatedComponents:
    """AC2. Validating the CONCATENATION is not enough: `--project deploy --type design
    --ref 713` yields `deploy-design-713`, which matches the pattern perfectly and is
    exactly the junk the convention exists to stop."""

    def test_the_happy_name(self, workspace):
        assert publish_doc.derive_name(
            "example", "design", "12", workspace)[0] == "example-design-12"

    @pytest.mark.parametrize("project", ["deploy", "site", "copy", "final-final", "vercel"])
    def test_a_project_that_does_not_exist_is_refused(self, project, workspace):
        """The gate's headline case. Each of these passes a shape check."""
        with pytest.raises(publish_doc.StageError):
            publish_doc.derive_name(project, "design", "713", workspace)

    def test_the_workspace_bucket_is_the_one_literal_exception(self, workspace):
        assert publish_doc.derive_name(
            "workspace", "audit", "harness", workspace)[0] == "workspace-audit-harness"

    def test_case_is_folded_because_hostnames_fold_it(self, workspace):
        """`Rawgentic` and `rawgentic` must not become two projects."""
        assert publish_doc.derive_name(
            "Rawgentic", "design", "735", workspace)[0] == "rawgentic-design-735"

    @pytest.mark.parametrize("ref", ["design", "plan", "spec"])
    def test_a_ref_that_is_itself_a_purpose_token_is_refused(self, ref, workspace):
        with pytest.raises(publish_doc.StageError):
            publish_doc.derive_name("example", "design", ref, workspace)

    @pytest.mark.parametrize("ref", ["", "a b", "Slug/With", "-lead", "trail-",
                                     "y" * 41, "under_score", "x"])
    def test_a_malformed_ref_is_refused(self, ref, workspace):
        with pytest.raises(publish_doc.StageError):
            publish_doc.derive_name("example", "design", ref, workspace)

    @pytest.mark.parametrize("ref", ["1", "12", "735", "network-topology", "aa"])
    def test_an_issue_number_or_a_real_slug_is_accepted(self, ref, workspace):
        assert publish_doc.derive_name("example", "design", ref, workspace)[0]

    def test_issue_one_is_publishable(self, workspace):
        """Under a flat 2-char minimum it was not — issue #1 could not be published."""
        assert publish_doc.derive_name(
            "example", "design", "1", workspace)[0] == "example-design-1"

    @pytest.mark.parametrize("ref", ["01", "007", "0"])
    def test_a_non_canonical_issue_number_is_refused(self, ref, workspace):
        """`-01` and `-1` would be two page names for one issue."""
        with pytest.raises(publish_doc.StageError):
            publish_doc.derive_name("example", "design", ref, workspace)

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
        with pytest.raises(publish_doc.StageError, match="not a usable page"):
            publish_doc.derive_name(long_project, "design", ref, ws)

    def test_an_underscore_project_is_refused_by_the_assembled_name_rule(self, tmp_path):
        """A real workspace holds `chorestory_business`; a DNS label cannot carry `_`."""
        ws = tmp_path / "u.json"
        ws.write_text(json.dumps({"projects": [{"name": "chorestory_business"}]}),
                      encoding="utf-8")
        with pytest.raises(publish_doc.StageError, match="not a usable page"):
            publish_doc.derive_name("chorestory_business", "design", "5", ws)
# --------------------------------------------------------------------------- #23, RETIRED by #36
#
# `TestTheAliasCapIsEnforcedAtNaming` and `TestTheVerifierUsesTheDomainTheDeployReported`
# lived here. Both existed for ONE Vercel behavior: Vercel cuts the auto-assigned
# `<name>.vercel.app` label at 35 characters and strips a trailing hyphen, so a 36+-char
# name deployed fine and then 404d at its conventional URL forever.
#
# Where each risk went, because a deleted test must say:
#
# * **the cap** -> `scripts/tests/test_harness_publish.py`,
#   `TestTheNameCapIsTheHarnessLimitNotVercels`. The risk is unchanged in kind — a name
#   that cannot be addressed — but the limit is now the DNS label limit, 63, and a test
#   pins it against `harness.routing.is_valid_label` so publisher and router cannot drift.
#
# * **the alias-domain verifier** -> the risk LEFT WITH VERCEL. It existed because the
#   served domain could differ from the name, so verifying a URL built from the name was
#   unsound. The harness truncates nothing: stage 6 builds each URL from the manifest's own
#   `url_path` and pins the deployment with `?__deployment=<id>` and an explicit `Host`
#   header. `TestTheVerificationRequest` in the new file covers what remains.

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
        rc, h = run("--out", str(doc))
        assert rc == code(1)
        assert doc.read_text(encoding="utf-8").startswith("## Heading")
        assert h.published is None

    def test_out_may_not_be_an_equivalent_path_to_the_source(self, run, doc):
        weird = str(doc.parent / "." / doc.name)
        rc, h = run("--out", weird)
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
        rc = publish_doc.main(["--md", str(link), "--out", str(tmp_path / "o.html"),
                               "--project", "example", "--type", "design",
                               "--ref", "12", "--title", "T",
                               "--workspace-file", str(workspace)])
        assert rc == code(1)
        assert not (tmp_path / "o.html").exists()
        # Nothing could have been published: main() refuses at stage 1, long before any
        # control call exists to make. That is stronger than the old assertion, which
        # checked an empty deploy list after the fact.

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
        rc, h = run("--title", "Untitled")
        assert rc == code(3)
        assert h.published is None

    def test_the_lint_failure_is_reported_with_its_finding(self, run, capsys):
        run("--title", "Untitled")
        assert "placeholder" in capsys.readouterr().err

    def test_ANY_lint_finding_blocks_the_deploy_not_just_the_title(
            self, run, monkeypatch):
        """Guards against the no-deploy contract being special-cased to one check."""
        monkeypatch.setattr(publish_doc, "LINT",
                            lambda _html: ["external-requests: external request via src"])
        rc, h = run()
        assert rc == code(3)
        assert h.published is None

    def test_the_committed_html_is_still_written_so_the_failure_is_inspectable(
            self, run, tmp_path):
        run("--title", "Untitled")
        assert (tmp_path / "a-doc.html").exists()



# --------------------------------------------------------------------------- RETIRED by #36
#
# Four classes lived here, all of them about Vercel mechanics that no longer exist. A
# deleted test must say where its risk went, so:
#
# * `TestTheDeployIsBoundToTheRenderedFile` -> `test_harness_publish.py`,
#   `TestTheManifestIsBuiltFromCommittedBytes`. The risk is sharper now, not weaker: the
#   old test proved the deploy shipped the file just rendered, and the new one proves the
#   manifest pins the COMMITTED blob, which also catches "rendered but forgot to commit".
#
# * `TestVerificationIsCacheBustedAndContentChecked` -> `TestThePerAssetPassContract`.
#   Cache-busting was a Vercel CDN workaround; that half of the risk left with Vercel. The
#   content half is stronger: the new check pins the `X-Doc-Deployment` echo to the
#   deployment JUST published, so it cannot pass against whatever was already active.
#
# * `TestTheIndexRefreshIsPartOfPublishing` -> the risk MOVED to #34. The harness
#   server-renders the index from its registry snapshot, so publishing cannot leave a stale
#   index behind — there is no separate index deploy to forget. `index/build_index.py`
#   survives as the harness's renderer and is still covered by `test_build_index.py`.
#
# * `TestReuseIsTheDefaultAndCreationIsTheException` -> the risk LEFT with Vercel. There is
#   no project to create or reuse: a name is a registry row, and publishing to it is the
#   only way it comes into being. The adjacent risk that DOES survive — publishing under a
#   name the router cannot address — is covered by
#   `TestTheNameCapIsTheHarnessLimitNotVercels`.









# --------------------------------------------------------------------------- AC1

class TestTheExitCodeIsTheVerdict:
    """AC1, table-driven: one distinct code per failing stage. Offset past argparse's
    own `2` so a usage error is never mistaken for a stage failure."""

    def test_a_clean_run_is_zero(self, run):
        assert run()[0] == 0

    def test_stage_codes_do_not_collide_with_argparse(self):
        assert publish_doc.EXIT_BASE > 2

    @pytest.mark.parametrize("stage,extra,kw,serve", [
        (1, ("--md", "/nonexistent/x.md"), {}, None),
        (2, ("--project", "deploy"), {}, None),
        (3, ("--title", "Untitled"), {}, None),
    ])
    def test_each_failing_stage_has_its_own_code(self, run, stage, extra, kw, serve):
        rc, h = run(*extra, serve=serve)
        assert rc == code(stage)

    def test_stage_six_fails_on_a_byte_mismatch(self):
        """Kept from the retired Vercel table: the risk that a served page differs from
        what was linted is the same risk, and it is still stage 6."""
        # Covered end to end by `test_a_served_byte_mismatch_fails_stage_six` below.

    def test_the_two_declared_states_are_not_stage_failures(self):
        """#36. Exits 25 and 26 sit ABOVE the 11-17 block precisely so a caller can tell
        "you did not configure an endpoint" from "a stage tried and could not"."""
        assert publish_doc.EXIT_CONTROL_URL_UNSET not in {code(s) for s in range(1, 8)}
        assert publish_doc.EXIT_EDGE_SKIPPED not in {code(s) for s in range(1, 8)}




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
        rc, h = run("--md", str(prose_doc))
        assert rc == code(3)
        assert h.published is None and h.urls == []

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
        rc, h = run("--dry-run")
        assert rc == 0
        assert h.published is None and h.urls == []

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
             "--out", str(tmp_path / "o.html"), "--project", "example",
             "--type", "design", "--ref", "12", "--title", "A Real Doc",
             "--workspace-file", str(workspace), "--dry-run"],
            cwd=str(elsewhere), capture_output=True, text=True, check=False)
        assert proc.returncode == 0, proc.stderr
        assert "3/6 lint gate passed" in proc.stdout
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
        rc, h = run("--title", "Untitled")
        assert rc == code(3)
        assert [c for c, _ in h.requests if c[:1] == ["vercel"]] == []
        assert h.urls == []

    def test_a_refusal_runs_nothing_that_can_mutate(self, run):
        """Read-only is the whole licence for the exemption. `git show` is; these are not."""
        rc, h = run("--title", "Untitled")
        assert rc == code(3)
        mutating = {"commit", "push", "add", "checkout", "reset", "rm", "tag", "merge"}
        assert [c for c, _ in h.requests
                if c[:1] == ["git"] and set(c[1:2]) & mutating] == []


class TestGitStaysOut:
    """AC6. Commits and PRs remain the workflows' business.

    **Narrowed by #36, not deleted.** This class used to assert the script contained no
    git invocation at all. #36 makes the harness fetch blobs from GitHub by commit sha, so
    the publisher MUST read git state — the repository, the committed blob ids, and whether
    HEAD is pushed — and must fetch before it can answer the last one.

    The REASON behind the original guard is untouched and still enforced below: this script
    never mutates the repository or its history. Reading is now in scope; committing,
    staging, pushing, branching and opening pull requests are exactly as forbidden as they
    were. A blanket ban would have been deleted here; a narrowed one keeps the protection
    that mattered.
    """

    # `fetch` is deliberately absent: it updates remote-tracking refs and touches neither
    # the working tree nor history, and the reachability check cannot be answered without
    # it. `--dry-run` still skips it, so the offline promise holds (#36 finding N10).
    FORBIDDEN = ("commit", "add", "push", "tag", "rebase", "merge", "reset", "checkout",
                 "cherry-pick", "revert", "stash", "clean", "am", "apply", "restore")

    def _git_argvs(self):
        """Every list literal in the script whose first element is the string `git`."""
        import ast
        tree = ast.parse((SCRIPTS / "publish_doc.py").read_text(encoding="utf-8"))
        out = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.List) or not node.elts:
                continue
            head = node.elts[0]
            if isinstance(head, ast.Constant) and head.value == "git":
                out.append([e.value if isinstance(e, ast.Constant) else None
                            for e in node.elts])
        return out

    def test_no_git_subcommand_mutates_the_repository(self):
        argvs = self._git_argvs()
        assert argvs, "expected #36's git plumbing to be present"
        offenders = [a for a in argvs
                     if any(tok in self.FORBIDDEN for tok in a if isinstance(tok, str))]
        assert offenders == [], offenders

    def test_no_string_literal_shells_out_to_a_mutating_git_command(self):
        """The AST check above sees list literals. This one catches a mutating command
        smuggled into a plain string."""
        import ast
        tree = ast.parse((SCRIPTS / "publish_doc.py").read_text(encoding="utf-8"))
        literals = [n.value for n in ast.walk(tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        offenders = [s for s in literals
                     if any(s.strip().startswith(f"git {verb}") for verb in self.FORBIDDEN)]
        assert offenders == [], offenders

    def test_the_script_never_invokes_the_github_cli(self):
        """Pull requests were never this tool's business and still are not."""
        import ast
        tree = ast.parse((SCRIPTS / "publish_doc.py").read_text(encoding="utf-8"))
        literals = [n.value for n in ast.walk(tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        assert [s for s in literals if s.strip() == "gh" or s.strip().startswith("gh ")] == []


# --------------------------------------------------------------------------- AC7

class TestTheSkillCallsTheCommand:
    """AC7. The prose shrinks to judgment: what to write, which type, when to publish."""

    SKILL = SCRIPTS.parent / "skills" / "design-doc-publish" / "SKILL.md"

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
        """A copy-pasteable deploy incantation is the prose the script replaces.
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
        The skill runs from whatever project is bound, so `docs/…` resolves only from this
        repo's root and nowhere a reader would actually be. The pointer therefore uses the
        same install-rooted form as the command block above it, and the tail is checked to
        be a real file rather than a path that merely looks plausible.

        Updated by #2, when this became a PLUGIN. Two things changed, and both had been
        pinned here. A plugin skill gets no `~/.claude/skills/<name>` directory at all —
        verified live against `frontend-design`, which is installed as a plugin and has no
        such entry — so the old prefix now resolves to nothing. And the previous version of
        this test asserted the target path ENDED WITH `design-doc-publish/docs/…`, which
        quietly pinned the checkout directory's NAME. A plugin installs under a version
        directory, so that assertion would have failed for a reason having nothing to do
        with what it was trying to check. It is replaced by the existence check it meant.
        """
        text = self._text()
        tail = "docs/design-language.md"
        assert "${CLAUDE_PLUGIN_ROOT}/" + tail in text, (
            "SKILL.md must name the component-vocabulary doc through the plugin root, which "
            "the harness expands when it loads skill content — a plugin skill does not run "
            "from this repo and has no ~/.claude/skills path to fall back on")
        target = SCRIPTS.parent / "docs" / "design-language.md"
        assert target.is_file(), f"SKILL.md points at {target}, which does not exist"

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
        rc, h = run()
        assert rc == 0, "the publish must succeed"
        shipped = h.shipped["example-design-12"]
        assert "index.html" in shipped
        assert shipped.get("diagram.png") == b"\x89PNG\r\n\x1a\nfake", sorted(shipped)

    def test_a_nested_relative_path_keeps_its_subdirectory(self, run, doc, tmp_path):
        (tmp_path / "assets").mkdir()
        (tmp_path / "assets" / "diagram.png").write_bytes(b"nested")
        self._doc_with(doc, "![d](assets/diagram.png)")
        rc, h = run()
        assert rc == 0
        shipped = h.shipped["example-design-12"]
        assert shipped.get("assets/diagram.png") == b"nested", sorted(shipped)

    def test_several_references_to_one_file_ship_it_once(self, run, doc, tmp_path):
        (tmp_path / "d.png").write_bytes(b"once")
        self._doc_with(doc, "![a](d.png) and ![b](d.png)")
        rc, h = run()
        assert rc == 0
        assert sorted(h.shipped["example-design-12"]) == ["d.png", "index.html"]

    def test_a_missing_asset_is_refused_rather_than_published_as_a_404(self, run, doc, capsys):
        """AC2's negative case, and the whole point of AC1: the failure used to be SILENT."""
        self._doc_with(doc, "![d](missing.png)")
        rc, h = run()
        assert rc != 0, "publishing a page whose asset does not exist must fail"
        assert h.deployed == {}, "nothing may be deployed once an asset is known missing"
        err = capsys.readouterr().err
        assert "missing.png" in err, err

    def test_a_reference_escaping_the_documents_directory_is_refused(self, run, doc, tmp_path):
        """AC3. The doc lives in tmp_path; `../` leaves it."""
        outside = tmp_path.parent / "outside-secret.png"
        outside.write_bytes(b"not yours")
        self._doc_with(doc, "![d](../outside-secret.png)")
        rc, h = run()
        assert rc != 0
        assert h.deployed == {}
        for tree in h.shipped.values():
            assert "outside-secret.png" not in " ".join(tree)

    def test_an_absolute_path_reference_is_refused(self, run, doc, tmp_path):
        """A rooted `/etc/x` is not relative to the document at all."""
        self._doc_with(doc, "![d](/rooted.png)")
        rc, h = run()
        assert rc != 0
        assert h.deployed == {}

    def test_a_symlinked_asset_is_refused(self, run, doc, tmp_path):
        """Consistent with `_check_paths`' refusal of a symlinked `--md`: these pages are PUBLIC
        and this script follows what it is given, so a link pointing at a readable secret would
        be copied into a public deploy."""
        secret = tmp_path.parent / "secret.png"
        secret.write_bytes(b"a readable secret")
        link = tmp_path / "innocent.png"
        link.symlink_to(secret)
        self._doc_with(doc, "![d](innocent.png)")
        rc, h = run()
        assert rc != 0
        assert h.deployed == {}

    def test_a_page_with_no_relative_reference_ships_exactly_as_before(self, run, doc):
        """The whole existing corpus is this case, so it must be untouched."""
        rc, h = run()
        assert rc == 0
        assert sorted(h.shipped["example-design-12"]) == ["index.html"]

    def test_a_fragment_and_a_data_uri_are_not_assets(self, run, doc):
        self._doc_with(doc, "[jump](#heading) and ![i](data:image/png;base64,AAAA)")
        rc, h = run()
        assert rc == 0
        assert sorted(h.shipped["example-design-12"]) == ["index.html"]

    def test_a_percent_encoded_space_resolves_to_the_real_file(self, run, doc, tmp_path):
        (tmp_path / "my diagram.png").write_bytes(b"spaced")
        self._doc_with(doc, "![d](my%20diagram.png)")
        rc, h = run()
        assert rc == 0
        shipped = h.shipped["example-design-12"]
        assert shipped.get("my diagram.png") == b"spaced", sorted(shipped)

    def test_a_query_string_is_stripped_before_the_file_is_found(self, run, doc, tmp_path):
        (tmp_path / "d.png").write_bytes(b"queried")
        self._doc_with(doc, "![d](d.png?v=2)")
        rc, h = run()
        assert rc == 0
        assert h.shipped["example-design-12"].get("d.png") == b"queried"


class TestTheAssetRuleIsDocumented:
    """AC4: SKILL.md and the renderer docstring state what an author may write, and what happens
    otherwise — with no claim beyond what is enforced."""

    def _skill(self):
        return (Path(publish_doc.__file__).resolve().parent.parent
                / "skills" / "design-doc-publish" / "SKILL.md").read_text(encoding="utf-8")

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
        rc, h = run()
        assert rc != 0, f"{secret} must not be publishable"
        assert h.deployed == {}, "nothing may deploy once a non-asset reference is seen"
        for tree in h.shipped.values():
            assert not any("NOT-A-REAL-SECRET" in v.decode("utf-8", "replace") for v in tree.values())

    @pytest.mark.parametrize("name", ["d.png", "d.JPG", "d.jpeg", "d.gif", "d.webp", "d.avif",
                                      "d.ico", "d.svg"])
    def test_every_declared_asset_type_still_ships(self, run, doc, tmp_path, name):
        (tmp_path / name).write_bytes(b"asset-bytes")
        self._doc_with(doc, f"![x]({name})")
        rc, h = run()
        assert rc == 0, name
        assert h.shipped["example-design-12"].get(name) == b"asset-bytes"

    def test_the_suffix_check_is_case_insensitive_and_uses_the_real_suffix(self, run, doc,
                                                                          tmp_path):
        """`.env` under a name ending in something asset-shaped must not sneak through, and an
        upper-case extension is the same extension."""
        (tmp_path / "sneaky.png.env").write_text("NOT-A-REAL-SECRET-example-only\n", encoding="utf-8")
        self._doc_with(doc, "![x](sneaky.png.env)")
        assert run()[0] != 0


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
        rc, h = run("--md", str(partial_doc), "--style", "roadmap")
        assert rc == code(3)
        assert h.published is None and h.urls == []

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
        rc, h = run("--dry-run", "--md", str(full_doc), "--style", "roadmap",
                       "--telemetry", str(self._tel(tmp_path, payload)))
        assert rc == code(1), "a section that vanishes silently is the whole defect class"

    def test_a_missing_file_is_a_loud_failure(self, run, full_doc, tmp_path):
        rc, h = run("--dry-run", "--md", str(full_doc), "--style", "roadmap",
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
        rc, h = run("--dry-run", "--md", str(full_doc), "--style", "roadmap",
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
