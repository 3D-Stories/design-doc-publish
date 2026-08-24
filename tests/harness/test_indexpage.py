"""`harness.indexpage` — the server-rendered index, reusing `index/build_index.py`.

Two things here are the reason the module exists rather than being inlined.

The renderer is loaded BY PATH with importlib, because `index/` is not a package and making
it one would change pytest collection for 53 existing test files.

`generated_at` is pinned to the generation. `render()` emits relative ages, so letting `now`
follow the wall clock while the ETag derived only from the generation would make the ETag
WRONG — the body would change while the validator did not.
"""
import pytest

from harness.indexpage import EYEBROW, build_index_module, render_index
from harness.manifest import Asset, Manifest
from harness.registry import Registry


def manifest(name, project, title="A doc", commit="c" * 40, expected_active=None):
    a = Asset("/index.html", "docs/i.html", "a" * 40, 5, "b" * 64, "text/html; charset=utf-8")
    return Manifest(name=name, repo="owner/repo", commit_sha=commit, entry_path="/index.html",
                    assets=(a,), title=title, project=project, purpose="design",
                    published_at="2026-08-24T00:00:00Z", expected_active=expected_active,
                    total_bytes=5)


@pytest.fixture()
def reg(tmp_path):
    r = Registry(str(tmp_path / "r.db"))
    r.initialize()
    yield r
    r.close()


def test_the_renderer_loads_by_path_with_no_side_effect():
    mod = build_index_module()
    for name in ("render", "signature", "classify", "group_colors"):
        assert hasattr(mod, name)


def test_the_page_lists_each_active_deployment_by_title(reg):
    reg.publish(manifest("alpha-design-1", "alpha", title="Alpha doc"))
    reg.publish(manifest("beta-design-1", "beta", title="Beta doc"))
    page = render_index(reg).body.decode()
    assert "Alpha doc" in page and "Beta doc" in page


def test_a_title_containing_markup_is_escaped(reg):
    reg.publish(manifest("evil-design-1", "evil", title="<script>alert(1)</script>"))
    page = render_index(reg).body.decode()
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_the_eyebrow_is_the_harness_one_and_not_vercel(reg):
    reg.publish(manifest("alpha-design-1", "alpha"))
    page = render_index(reg).body.decode()
    assert EYEBROW in page
    assert "vercel · living documentation" not in page


class TestEtag:
    def test_the_etag_is_the_generation(self, reg):
        reg.publish(manifest("alpha-design-1", "alpha"))
        assert render_index(reg).headers["ETag"] == '"gen-1"'

    def test_a_matching_if_none_match_is_304(self, reg):
        reg.publish(manifest("alpha-design-1", "alpha"))
        r = render_index(reg, if_none_match='"gen-1"')
        assert r.status == 304 and r.body == b""

    def test_the_body_is_byte_identical_at_the_same_generation(self, reg):
        # This is what pinning generated_at buys: the body cannot drift under a validator
        # that only tracks the generation.
        reg.publish(manifest("alpha-design-1", "alpha"))
        first = render_index(reg).body
        second = render_index(reg).body
        assert first == second

    def test_the_etag_and_the_body_both_move_after_a_publish(self, reg):
        dep = reg.publish(manifest("alpha-design-1", "alpha"))
        before = render_index(reg)
        # Republishing the SAME name must carry the previous id, or the compare-and-swap
        # refuses it — which is the CAS working, not a defect.
        reg.publish(manifest("alpha-design-1", "alpha", commit="d" * 40, expected_active=dep))
        after = render_index(reg)
        assert after.headers["ETag"] != before.headers["ETag"]


class TestGrouping:
    def test_two_projects_land_in_different_groups_with_no_workspace_file(self, reg):
        # Finding S10: `known_projects()` sources its list from a workspace file the
        # container does not have, and returns [] there, so every row would fall into the
        # `other` bucket and the grouping — most of the index's value — would vanish
        # silently.
        reg.publish(manifest("alpha-design-1", "alpha"))
        reg.publish(manifest("beta-design-1", "beta"))
        assert set(reg.index_projects()) == {"alpha", "beta"}
        page = render_index(reg).body.decode()
        assert "alpha" in page and "beta" in page

    def test_an_active_row_with_no_project_does_not_raise(self, reg):
        # Finding C3: `project` is nullable, and a NULL reaching a length comparison raises
        # while rendering.
        reg.publish(manifest("alpha-design-1", "alpha"))
        c = reg._conn()
        c.execute("INSERT INTO deployment(name,repo,commit_sha,entry_path,published_at,project,"
                  "title,sealed) VALUES('nul-design-1','o/r','c'*40,'/i.html','now',NULL,'N',0)")
        rid = c.execute("SELECT id FROM deployment WHERE name='nul-design-1'").fetchone()[0]
        c.execute("INSERT INTO active(name,deployment_id) VALUES('nul-design-1',?)", (rid,))
        page = render_index(reg).body.decode()
        assert "N" in page

    def test_a_retired_project_does_not_classify_a_live_row(self, reg):
        reg.publish(manifest("alpha-design-1", "alpha"))
        c = reg._conn()
        c.execute("INSERT INTO deployment(name,repo,commit_sha,entry_path,published_at,project,"
                  "sealed) VALUES('ghost-design-1','o/r','c'*40,'/i.html','now','retired',1)")
        assert "retired" not in reg.index_projects()
