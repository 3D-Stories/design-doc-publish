"""A roadmap item that names a GitHub issue links to it, and shows the issue's severity.

**Links were hit and miss** (owner report, 2026-10-20). Measured on the live roadmaps that day:
`3dstories-fleet`'s runner-pool roadmap hand-wrote a markdown link into every item's TEXT cell;
`rawgentic-suite`'s and `benchstory`'s roadmaps wrote the bare `#256` in the id cell and linked
nothing. The id cell was escaped and printed verbatim, so a link existed only when an author
remembered to type one. The fix moves the link out of the author's memory: the id cell `#N`
becomes a link whenever the render knows the repository, and the publisher already knows it —
`--project` names a project whose `.rawgentic.json` declares `repo.fullName`.

**Severity** rides in an optional FOURTH item cell, `id | text | state | severity`, drawn as a
pill beside the type pill. GitHub's label is `severity:<level>`, so that spelling is accepted
verbatim as well as the bare level. The render never asks GitHub: rendering needs no network,
and two renders of one source match byte for byte.
"""
import json
import re
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render  # noqa: E402
import vdl_packs  # noqa: E402

REPO = "3D-Stories/rawgentic-suite"
URL = "https://github.com/3D-Stories/rawgentic-suite/issues/"


def _md(rows: str) -> str:
    return f"# T\n\n```phases\nBacklog | 3 open | active\n{rows}```\n"


def _page(md, repo=REPO, style="roadmap"):
    return render.render_artifact(md, title="T", style=style, generated_at="x",
                                  issue_repo=repo)


class TestAnIssueIdLinks:
    def test_a_hash_number_id_links_to_the_issue_in_the_declared_repo(self):
        page = _page(_md("  #256 | The handoff is built at start | bug:must\n"))
        assert f'<a class="blk-ph-id" href="{URL}256">#256</a>' in page

    def test_an_explicit_repo_in_the_id_wins_and_needs_no_declared_repo(self):
        page = _page(_md("  3D-Stories/benchstory#289 | Commit the inputs | planned\n"),
                     repo=None)
        assert ('<a class="blk-ph-id" href="https://github.com/3D-Stories/benchstory/issues/289">'
                '3D-Stories/benchstory#289</a>') in page

    def test_an_id_that_is_not_an_issue_is_untouched(self, capsys):
        page = _page(_md("  FA-1 | Fan curve | crit\n  D1 | A decision | done\n"))
        assert '<span class="blk-ph-id">FA-1</span>' in page
        assert '<span class="blk-ph-id">D1</span>' in page
        assert "issue" not in capsys.readouterr().err.lower()

    def test_an_issue_id_with_no_known_repo_renders_plain_and_says_why_once(self, capsys):
        page = _page(_md("  #1 | a | planned\n  #2 | b | planned\n"), repo=None)
        assert '<span class="blk-ph-id">#1</span>' in page
        err = capsys.readouterr().err
        assert err.count("no GitHub repository") == 1, err
        assert "--project" in err

    def test_a_malformed_repo_never_reaches_an_href(self, capsys):
        page = _page(_md("  #7 | a | planned\n"), repo='x/y" onmouseover="alert(1)')
        assert "onmouseover" not in page
        assert '<span class="blk-ph-id">#7</span>' in page
        assert "repository" in capsys.readouterr().err

    def test_a_stuck_item_keeps_its_red_id_when_it_is_a_link(self):
        page = _page(_md("  #9 | a | blocked\n"))
        assert '<div class="blk-ph-item is-blocked"><a class="blk-ph-id"' in page

    def test_the_link_is_styled_as_the_id_not_as_a_bare_anchor(self):
        css = _page(_md("  #9 | a | planned\n"))
        assert ".tpl-roadmap a.blk-ph-id:hover" in css


class TestSeverityIsAPill:
    @pytest.mark.parametrize("cell,level", [
        ("severity:high", "high"), ("high", "high"), ("Severity:Critical", "critical"),
        ("medium", "medium"), ("severity:low", "low")])
    def test_the_severity_pill_sits_beside_the_type_pill(self, cell, level):
        page = _page(_md(f"  #256 | The handoff | bug:must | {cell}\n"))
        assert re.search(r'<span class="blk-ph-chip is-crit"[^>]*>bug</span>'
                         rf'<span class="blk-ph-sev is-{level}">{level}</span>', page)

    def test_no_severity_cell_means_no_pill_and_the_row_is_unchanged(self):
        three = _page(_md("  #256 | The handoff | bug:must\n"))
        blank = _page(_md("  #256 | The handoff | bug:must |\n"))
        assert "blk-ph-sev" not in three.split("<style>")[0] + three.split("</style>")[-1]
        assert three == blank

    def test_an_unknown_severity_warns_and_shows_the_authors_word_uncoloured(self, capsys):
        page = _page(_md("  #256 | The handoff | bug:must | severity:urgent\n"))
        assert '<span class="blk-ph-sev">severity:urgent</span>' in page
        assert "severity" in capsys.readouterr().err

    def test_author_text_in_the_severity_cell_cannot_reach_a_class(self):
        page = _page(_md('  #1 | a | planned | high"><script>x</script>\n'))
        assert "<script>x" not in page

    @pytest.mark.parametrize("level", ["critical", "high", "medium", "low"])
    def test_every_level_has_a_colour_rule(self, level):
        page = _page(_md("  #1 | a | planned | high\n"))
        assert f".tpl-roadmap .blk-ph-sev.is-{level}{{" in page

    def test_a_fifth_item_cell_still_warns(self, capsys):
        _page(_md("  #1 | a | planned | high | surplus\n"))
        assert "5 fields" in capsys.readouterr().err

    def test_a_phase_row_still_takes_three_cells(self, capsys):
        _page("# T\n\n```phases\nA | b | ok | high\n  #1 | a | done\n```\n")
        assert "4 fields" in capsys.readouterr().err

    def test_a_severity_word_does_not_vote_on_status_drift(self):
        from render import source_lint
        md = "```phases\nA | all in | done\n  #1 | a | done | severity:critical\n```\n"
        assert source_lint._phase_child_drift(md) == []


class TestTheRepoComesFromTheProject:
    def _workspace(self, tmp_path, repo):
        proj = tmp_path / "projects" / "demo"
        proj.mkdir(parents=True)
        (proj / ".rawgentic.json").write_text(json.dumps(
            {"project": {"name": "demo"}, "repo": {"provider": "github", "fullName": repo}}))
        ws = tmp_path / ".rawgentic_workspace.json"
        ws.write_text(json.dumps({"projects": [{"name": "demo", "path": "./projects/demo"}]}))
        return ws

    def test_repo_for_reads_the_projects_declared_repo(self, tmp_path):
        assert vdl_packs.repo_for("demo", self._workspace(tmp_path, REPO)) == REPO

    def test_repo_for_is_none_without_a_workspace_or_a_declaration(self, tmp_path):
        assert vdl_packs.repo_for("demo", None) is None
        assert vdl_packs.repo_for("nobody", self._workspace(tmp_path, REPO)) is None

    def test_repo_for_refuses_a_malformed_name(self, tmp_path, capsys):
        ws = self._workspace(tmp_path, "not a repo")
        assert vdl_packs.repo_for("demo", ws) is None
        assert "fullName" in capsys.readouterr().err

    def test_render_doc_with_project_links_the_ids(self, tmp_path):
        ws = self._workspace(tmp_path, REPO)
        md = tmp_path / "r.md"
        md.write_text(_md("  #256 | The handoff | bug:must | high\n"))
        out = tmp_path / "r.html"
        rc = render.main(["--md", str(md), "--out", str(out), "--title", "T",
                          "--style", "roadmap", "--project", "demo",
                          "--workspace-file", str(ws), "--generated-at", "x"])
        assert rc == 0
        assert f'href="{URL}256"' in out.read_text()

    def test_the_publisher_dry_run_links_the_ids(self, tmp_path):
        """The entry path agents actually use: `publish_doc.py --project ... --dry-run`."""
        import subprocess
        ws = self._workspace(tmp_path, REPO)
        home = tmp_path / "home"
        (home / ".config").mkdir(parents=True)
        md = tmp_path / "r.md"
        md.write_text("# T\n\n## Backlog\n\n" + _md("  #256 | The handoff | bug:must | high\n")
                      .split("\n", 2)[2])
        out = tmp_path / "r.html"
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "publish_doc.py"), "--md", str(md), "--out", str(out),
             "--project", "demo", "--workspace-file", str(ws), "--type", "plan", "--ref", "1",
             "--title", "Backlog roadmap", "--dry-run", "--skip-component-checks"],
            capture_output=True, text=True, cwd=str(tmp_path), check=False,
            env={"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
                 "PATH": "/usr/bin:/bin", "LC_ALL": "C.UTF-8"})
        assert proc.returncode == 0, proc.stdout + proc.stderr
        page = out.read_text()
        assert f'<a class="blk-ph-id" href="{URL}256">#256</a>' in page
        assert '<span class="blk-ph-sev is-high">high</span>' in page


# --- the publisher checks each severity cell against GitHub (owner decision 2026-10-20) ----
#
# The render stays offline, so it cannot see a label. The publisher can, so stage 3 reads each
# `#N` item's labels through `gh` and refuses a row whose severity cell disagrees with them. An
# issue with no severity label is fine, and its row must then draw no pill. `--ack-severity`
# overrides; a `gh` that cannot answer prints "severity NOT checked" and the publish goes on.

from render import source_lint  # noqa: E402

ROWS = ("```phases\nBacklog | 4 open | active\n"
        "  #1 | Labelled high, cell matches | bug:must | severity:high\n"
        "  #2 | Labelled critical, cell blank | bug:must\n"
        "  #3 | No label, cell blank | chore:could\n"
        "  #4 | No label, cell says low | chore:could | low\n"
        "  FA-1 | Not an issue | planned | high\n"
        "```\n")
LABELS = {1: ["bug", "severity:high"], 2: ["severity:critical"], 3: ["bug"], 4: []}


def _fetch(repo, numbers):
    assert repo == REPO
    return {n: LABELS[n] for n in numbers if n in LABELS}


class TestThePublisherChecksSeverityAgainstGitHub:
    def test_a_matching_cell_and_an_unlabelled_blank_row_pass(self):
        md = ("```phases\nB | 2 | active\n  #1 | a | bug:must | high\n"
              "  #3 | b | chore:could\n```\n")
        findings, notes = source_lint.check_severity(md, REPO, fetch=_fetch)
        assert findings == [] and notes == []

    def test_a_blank_cell_on_a_labelled_issue_refuses_with_the_fixed_row(self):
        findings, _ = source_lint.check_severity(_md_doc(), REPO, fetch=_fetch)
        hit = [f for f in findings if "#2" in f]
        assert len(hit) == 1, findings
        assert "severity:critical" in hit[0]
        assert "#2 | Labelled critical, cell blank | bug:must | severity:critical" in hit[0]

    def test_a_cell_on_an_unlabelled_issue_refuses_and_the_fix_drops_the_cell(self):
        findings, _ = source_lint.check_severity(_md_doc(), REPO, fetch=_fetch)
        hit = [f for f in findings if "#4" in f]
        assert len(hit) == 1, findings
        assert "no severity label" in hit[0]
        assert hit[0].rstrip().endswith("#4 | No label, cell says low | chore:could")

    def test_a_wrong_level_refuses(self):
        md = "```phases\nB | 1 | active\n  #1 | a | bug:must | low\n```\n"
        findings, _ = source_lint.check_severity(md, REPO, fetch=_fetch)
        assert len(findings) == 1 and "severity:high" in findings[0]

    def test_exactly_the_two_bad_rows_are_reported_with_their_line_numbers(self):
        findings, _ = source_lint.check_severity(_md_doc(), REPO, fetch=_fetch)
        assert len(findings) == 2, findings
        assert findings[0].startswith("line 8:") and findings[1].startswith("line 10:")

    def test_an_explicit_repo_id_is_checked_against_its_own_repo(self):
        seen = []

        def fetch(repo, numbers):
            seen.append((repo, sorted(numbers)))
            return {n: [] for n in numbers}

        md = "```phases\nB | 1 | active\n  3D-Stories/benchstory#9 | a | planned\n```\n"
        source_lint.check_severity(md, None, fetch=fetch)
        assert seen == [("3D-Stories/benchstory", [9])]

    def test_no_issue_ids_means_no_github_call_at_all(self):
        def fetch(repo, numbers):
            raise AssertionError("a doc with no issue ids must not reach GitHub")

        md = "```phases\nB | 1 | active\n  FA-1 | a | planned | high\n```\n"
        assert source_lint.check_severity(md, REPO, fetch=fetch) == ([], [])

    def test_a_bare_id_with_no_repo_is_not_checked(self):
        def fetch(repo, numbers):
            raise AssertionError("no repo, nothing to ask")

        md = "```phases\nB | 1 | active\n  #1 | a | planned | high\n```\n"
        assert source_lint.check_severity(md, None, fetch=fetch) == ([], [])

    def test_github_unreachable_is_a_loud_note_never_a_silent_pass(self):
        def fetch(repo, numbers):
            raise source_lint.SeverityUnavailable("gh: not logged in")

        findings, notes = source_lint.check_severity(_md_doc(), REPO, fetch=fetch)
        assert findings == []
        assert len(notes) == 1 and "severity NOT checked" in notes[0]
        assert "not logged in" in notes[0]

    def test_an_issue_github_does_not_know_is_a_note(self):
        def fetch(repo, numbers):
            return {}

        md = "```phases\nB | 1 | active\n  #99 | a | planned\n```\n"
        findings, notes = source_lint.check_severity(md, REPO, fetch=fetch)
        assert findings == []
        assert any("#99" in n and "not found" in n for n in notes)

    def test_two_severity_labels_expect_the_more_severe(self):
        def fetch(repo, numbers):
            return {1: ["severity:low", "severity:critical"]}

        md = "```phases\nB | 1 | active\n  #1 | a | planned | critical\n```\n"
        assert source_lint.check_severity(md, REPO, fetch=fetch) == ([], [])

    def test_rows_inside_an_ordinary_code_fence_are_ignored(self):
        def fetch(repo, numbers):
            raise AssertionError("a code sample is not a roadmap")

        md = "```text\n  #1 | a | planned | high\n```\n"
        assert source_lint.check_severity(md, REPO, fetch=fetch) == ([], [])


def test_the_lint_copy_of_the_issue_pattern_matches_the_renderer():
    from render import blocks
    assert source_lint._ISSUE_ID.pattern == blocks._ISSUE_ID.pattern
    assert source_lint._SEVERITIES == blocks._PHASE_SEVERITIES


class TestTheGhReader:
    def test_one_list_call_per_repo_then_a_single_lookup_for_a_pr(self):
        import subprocess
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            if argv[:3] == ["gh", "issue", "list"]:
                out = json.dumps([{"number": 1, "labels": [{"name": "severity:high"}]}])
            else:
                out = json.dumps(["severity:low"])
            return subprocess.CompletedProcess(argv, 0, out, "")

        got = source_lint.gh_labels(REPO, {1, 7}, run=run)
        assert got == {1: ["severity:high"], 7: ["severity:low"]}
        assert calls[0][:3] == ["gh", "issue", "list"] and "--repo" in calls[0]
        assert calls[1][:2] == ["gh", "api"] and calls[1][2] == f"repos/{REPO}/issues/7"
        assert len(calls) == 2

    def test_a_failed_list_call_is_unavailable(self):
        import subprocess

        def run(argv, **kw):
            return subprocess.CompletedProcess(argv, 4, "", "gh: To get started, gh auth login")

        with pytest.raises(source_lint.SeverityUnavailable, match="auth login"):
            source_lint.gh_labels(REPO, {1}, run=run)

    def test_no_gh_binary_is_unavailable(self):
        def run(argv, **kw):
            raise FileNotFoundError("gh")

        with pytest.raises(source_lint.SeverityUnavailable, match="gh"):
            source_lint.gh_labels(REPO, {1}, run=run)


def _md_doc():
    return "# T\n\n## Backlog\n\n" + ROWS


class TestThePublisherDryRunRefusesAStaleSeverity:
    """The real entry path, with a fake `gh` first on PATH so no test reaches GitHub."""

    def _run(self, tmp_path, rows, *extra, gh_body=None):
        import subprocess
        ws = TestTheRepoComesFromTheProject()._workspace(tmp_path, REPO)
        home = tmp_path / "home"
        (home / ".config").mkdir(parents=True)
        bin_ = tmp_path / "bin"
        bin_.mkdir()
        gh = bin_ / "gh"
        gh.write_text(gh_body or (
            "#!/bin/sh\n"
            "if [ \"$2\" = list ]; then\n"
            "  echo '[{\"number\":256,\"labels\":[{\"name\":\"severity:high\"}]},"
            "{\"number\":431,\"labels\":[]}]'\n"
            "else echo '[]'; fi\n"))
        gh.chmod(0o755)
        md = tmp_path / "r.md"
        md.write_text("# Backlog roadmap\n\n## Backlog\n\n```phases\nB | 2 open | active\n"
                      + rows + "```\n")
        out = tmp_path / "r.html"
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "publish_doc.py"), "--md", str(md), "--out", str(out),
             "--project", "demo", "--workspace-file", str(ws), "--type", "plan", "--ref", "1",
             "--title", "Backlog roadmap", "--dry-run", "--skip-component-checks", *extra],
            capture_output=True, text=True, cwd=str(tmp_path), check=False,
            env={"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
                 "PATH": f"{bin_}:/usr/bin:/bin", "LC_ALL": "C.UTF-8"})
        return proc

    def test_rows_that_agree_with_github_pass(self, tmp_path):
        proc = self._run(tmp_path, "  #256 | a | bug:must | severity:high\n  #431 | b | planned\n")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "severity NOT checked" not in proc.stdout + proc.stderr

    def test_a_missing_severity_refuses_at_stage_three(self, tmp_path):
        proc = self._run(tmp_path, "  #256 | a | bug:must\n  #431 | b | planned\n")
        assert proc.returncode == 13, proc.stdout + proc.stderr
        assert "stage 3" in proc.stderr
        assert "#256 | a | bug:must | severity:high" in proc.stderr
        assert "--ack-severity" in proc.stderr

    def test_ack_severity_overrides_and_says_so(self, tmp_path):
        proc = self._run(tmp_path, "  #256 | a | bug:must\n", "--ack-severity")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "--ack-severity" in proc.stdout

    def test_a_gh_that_fails_prints_not_checked_and_goes_on(self, tmp_path):
        proc = self._run(tmp_path, "  #256 | a | bug:must\n",
                         gh_body="#!/bin/sh\necho 'gh: not logged in' >&2\nexit 4\n")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "severity NOT checked" in proc.stdout


# --- an id that holds an issue number inside richer text ------------------------------------
#
# Measured on 2026-10-20 across every workspace doc: 752 phase item ids linked and 139 that
# named an issue did not, because only the exact `#N` and `owner/repo#N` forms linked. Most
# misses were local ids with the number inside (`FF01 / #10`, `0.1 · #65 — …`, `epic #350`,
# `PR #1`). Owner decision the same day: link those; refuse at stage 3 where another WORD sits
# right before `#N` (`herdr-utils #67`), because that word may be a repository and a guessed
# link would open the wrong issue; warn, and link nothing, for two numbers or a suffix.

class TestARicherIdLinks:
    @pytest.mark.parametrize("ident,n", [
        ("FF01 / #10", 10), ("0.1 · #65 — free disk", 65), ("epic #350", 350),
        ("PR #1", 1), ("Issue #7", 7), ("(#12)", 12), ("#118 AC5", 118)])
    def test_one_number_after_nothing_punctuation_or_a_kind_word_links(self, ident, n):
        page = _page(_md(f"  {ident} | a | planned\n"))
        esc = ident.replace("&", "&amp;")
        assert f'<a class="blk-ph-id" href="{URL}{n}">{esc}</a>' in page, page[-900:]

    def test_an_owner_repo_inside_richer_text_links_to_that_repo(self):
        page = _page(_md("  epic 3D-Stories/benchstory#289 | a | planned\n"), repo=None)
        assert 'href="https://github.com/3D-Stories/benchstory/issues/289"' in page

    @pytest.mark.parametrize("ident", ["herdr-utils #67", "herdr-utils#67", "Core-C #118"])
    def test_another_word_before_the_number_links_nothing(self, ident):
        page = _page(_md(f"  {ident} | a | planned\n"))
        assert f'<span class="blk-ph-id">{ident}</span>' in page

    @pytest.mark.parametrize("ident", ["#229 #231", "#147a"])
    def test_two_numbers_or_a_suffix_link_nothing_and_warn_once(self, ident, capsys):
        page = _page(_md(f"  {ident} | a | planned\n  {ident} | b | planned\n"))
        assert f'<span class="blk-ph-id">{ident}</span>' in page
        assert capsys.readouterr().err.count("not linked") == 1

    def test_a_plain_local_id_is_still_untouched_and_silent(self, capsys):
        page = _page(_md("  FA-1 | a | planned\n  D1 | b | done\n"))
        assert '<span class="blk-ph-id">FA-1</span>' in page
        assert "linked" not in capsys.readouterr().err


class TestTheLintRefusesAnIdThatMayNameAnotherRepo:
    def test_a_word_before_the_number_is_a_finding_with_both_fixes(self):
        md = "```phases\nB | 1 | active\n  herdr-utils #67 | a | bug:done\n```\n"
        findings, notes = source_lint.check_issue_links(md, REPO)
        assert len(findings) == 1 and notes == [], findings
        assert findings[0].startswith("line 3:")
        assert "3D-Stories/herdr-utils#67 | a | bug:done" in findings[0]
        assert "herdr-utils · #67 | a | bug:done" in findings[0]

    def test_with_no_declared_repo_the_owner_is_a_placeholder(self):
        md = "```phases\nB | 1 | active\n  herdr-utils #67 | a\n```\n"
        findings, _ = source_lint.check_issue_links(md, None)
        assert "<owner>/herdr-utils#67 | a" in findings[0]

    def test_two_numbers_or_a_suffix_are_notes_not_findings(self):
        md = "```phases\nB | 1 | active\n  #229 #231 | a\n  #147a | b\n```\n"
        findings, notes = source_lint.check_issue_links(md, REPO)
        assert findings == [] and len(notes) == 2, notes

    def test_ids_that_link_are_not_reported(self):
        md = ("```phases\nB | 1 | active\n  #1 | a\n  FF01 / #10 | b\n  epic #350 | c\n"
              "  3D-Stories/x#2 | d\n  FA-1 | e\n```\n")
        assert source_lint.check_issue_links(md, REPO) == ([], [])

    def test_a_richer_id_gets_its_severity_checked_too(self):
        md = "```phases\nB | 1 | active\n  FF01 / #1 | a | bug:must\n```\n"
        findings, _ = source_lint.check_severity(md, REPO, fetch=_fetch)
        assert len(findings) == 1 and "severity:high" in findings[0]
        assert "FF01 / #1 | a | bug:must | severity:high" in findings[0]


def test_the_lint_copy_of_the_resolver_matches_the_renderer():
    for ident in ("#1", "x/y#2", "FF01 / #10", "epic #3", "herdr-utils #67", "a#5",
                  "#229 #231", "#147a", "FA-1", "0.1 · #65 — t", "by #364, and"):
        for repo in (REPO, None):
            assert (source_lint.resolve_issue_id(ident, repo)
                    == render.blocks.resolve_issue_id(ident, repo)), (ident, repo)


class TestThePublisherRefusesAnUnlinkedId:
    def test_stage_three_refuses_and_names_the_ack(self, tmp_path):
        proc = TestThePublisherDryRunRefusesAStaleSeverity()._run(
            tmp_path, "  herdr-utils #67 | a | bug:done\n")
        assert proc.returncode == 13, proc.stdout + proc.stderr
        assert "3D-Stories/herdr-utils#67 | a | bug:done" in proc.stderr
        assert "--ack-unlinked" in proc.stderr

    def test_ack_unlinked_overrides_and_says_so(self, tmp_path):
        proc = TestThePublisherDryRunRefusesAStaleSeverity()._run(
            tmp_path, "  herdr-utils #67 | a | bug:done\n", "--ack-unlinked")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "--ack-unlinked" in proc.stdout
