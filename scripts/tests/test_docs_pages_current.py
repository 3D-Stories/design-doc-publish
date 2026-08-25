"""Every committed `docs/` page is current against its own markdown (#56).

`docs/planning/campaign-log.html` was committed missing a whole section of its own source, and
re-rendering it with `--project design-doc-publish` also flipped the page accent from teal to
green. A census found **13 of 18** committed md+html pairs stale. Nothing caught any of it,
for two reasons worth stating because they shaped this file:

* **No byte-identity guard in this repository rendered with a project pack.**
  `test_byte_identity.py` and `regen_rendered_styles.py` both omit `vdl`, so the per-project
  accent layer was invisible to every existing gate.
* **Nothing covered `docs/examples/gallery/` or `docs/planning/` at all.**

The pattern here is `test_rendered_styles_current.py`'s, applied rather than invented: render
the committed source at a pinned stamp and require the committed bytes back, plus completeness,
plus a can-it-fail test, plus sentinels the regenerator cannot rewrite. The recipe and the
manifest live in `regen_docs_pages.py` and are imported from there — `pytest` is not importable
under a bare `python3` on this host, so the regenerator could not import this module.

**What this guard does NOT prove.** It and the regenerator call the same renderer, so this pins
"the committed pages match what the renderer currently emits", never "the renderer is correct".
Renderer correctness is pinned independently by `test_furniture_context.py`'s per-style SHA
oracle, `test_byte_identity.py`'s committed exemplar, and the cross-style guards. The
can-it-fail test and the sentinels below are what stop a page regenerated from a broken engine
passing silently.
"""
import json
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))

from regen_docs_pages import (  # noqa: E402
    PAGES, ROOT, pairs_on_disk, render_bytes, render_page, resolve_pack,
)

sys.path.insert(0, str(TESTS.parent))
import render  # noqa: E402
import vdl_packs  # noqa: E402

KEYS = sorted(PAGES)

# Committed `docs/**/*.html` with no sibling markdown. A pair is this guard's unit because the
# guarantee is about re-rendering a page FROM its markdown, which a sourceless page cannot
# satisfy either way. Pinned so the gap cannot quietly grow.
#
# The `docs/rendered-styles/` half is DERIVED from the same style list its own guard uses, not
# retyped here. A second hardcoded copy of thirteen filenames is how two lists drift: adding a
# style would leave this one short and turn a correct state red, which teaches people to delete
# the assertion. `example-roadmap` is named literally because it is a one-off with no
# registry to derive it from — and it is the page guarded by nothing.
from regen_rendered_styles import STYLES as _RENDERED_STYLES  # noqa: E402

KNOWN_SOURCELESS = {
    'docs/examples/example-roadmap',
    *(f'docs/rendered-styles/{style}' for style in _RENDERED_STYLES),
}


def test_the_manifest_and_the_committed_pairs_agree_exactly():
    """Both directions. A new document must not skip the guard, and a deleted one must not
    leave an entry behind claiming coverage."""
    on_disk = pairs_on_disk()
    declared = set(PAGES)
    assert declared == on_disk, (
        f"declared but not on disk: {sorted(declared - on_disk)}\n"
        f"on disk but not declared: {sorted(on_disk - declared)}\n"
        f"add or remove the entry in regen_docs_pages.py — an undeclared pair ships unguarded")


@pytest.mark.parametrize("key", KEYS)
def test_each_committed_page_is_byte_identical_to_a_fresh_render(key):
    """BYTES, not text.

    Python normalises line endings on a text read, so `read_text()` would report a
    CRLF-committed page equal to an LF render and this would not be a byte-identity guard at
    all. `regen_rendered_styles.py` records having reproduced exactly that.
    """
    page = ROOT / f'{key}.html'
    assert page.exists(), f"no committed page for {key}"
    assert page.read_bytes() == render_bytes(key), (
        f"{key}.html is stale against its own markdown — regenerate with "
        f"scripts/tests/regen_docs_pages.py and commit the result. If the page was just "
        f"published, bump its `stamp` in regen_docs_pages.py first: publish_doc.py re-renders "
        f"with the current wall clock and has no --generated-at flag.")


@pytest.mark.parametrize("key", KEYS)
def test_each_committed_page_is_substantive_not_merely_consistent(key):
    """Expectations the regenerator CANNOT satisfy by regenerating.

    Every comparison above is against a fresh render, so a renderer that began emitting a stub
    would go green the moment someone ran the regenerator. These do not come from
    `render_page()`, so regeneration cannot manufacture them.
    """
    recipe = PAGES[key]
    page = (ROOT / f'{key}.html').read_bytes().decode('utf-8')
    assert len(page) > 2000, f"{key}.html is {len(page)} bytes — too small to be a real page"
    assert '<!doctype html>' in page.lower()
    assert recipe['stamp'] in page, (
        "the manifest's pinned stamp is missing, so this page was not rendered by the recipe")
    # The title reaches the page HTML-escaped, so compare against the escaped form.
    import html as _html
    assert _html.escape(recipe['title']) in page, "the manifest's pinned title is missing"


def test_the_guard_can_actually_fail():
    """A gate that cannot fail is not a gate.

    Mutate a source and require the comparison to break. Without this, every assertion above
    would still pass if the pages and the renderer were broken in step.
    """
    key = 'docs/planning/campaign-log'
    mutated = (ROOT / f'{key}.md').read_text(encoding='utf-8') + \
        '\n\nnot in the committed page\n'
    recipe = PAGES[key]
    got = render.render_artifact(
        mutated, title=recipe['title'], subtitle=recipe.get('subtitle', ''),
        generated_at=recipe['stamp'], style=recipe['style'],
        doc_id=recipe.get('doc_id'), vdl=resolve_pack(recipe.get('project')),
        section_chips=recipe.get('section_chips', True))
    assert got.encode('utf-8') != (ROOT / f'{key}.html').read_bytes()


def test_the_sourceless_committed_pages_are_the_ones_we_know_about():
    """A page with no markdown cannot be covered by a pairs-based guard, so the set of them is
    pinned. A NEW sourceless page turns this red rather than slipping into a gap nobody
    re-counted."""
    sourceless = {str(h.relative_to(ROOT).with_suffix(''))
                  for h in ROOT.glob('docs/**/*.html')
                  if not h.with_suffix('.md').is_file()}
    assert sourceless == KNOWN_SOURCELESS, (
        f"unexpected sourceless pages: {sorted(sourceless - KNOWN_SOURCELESS)}\n"
        f"no longer present: {sorted(KNOWN_SOURCELESS - sourceless)}\n"
        f"a committed page with no markdown cannot be round-tripped; either give it a source "
        f"and a manifest entry, or add it here deliberately")


class TestTheAccentComesFromCommittedSourcesOnly:
    """The property acceptance criterion 2 asks for, tested as behavior rather than promised.

    The guard resolves every pack with `workspace_file=None`. These pin that this is doing real
    work: a workspace declaring a different colour must not move the answer, and the answer must
    come from the committed seed table.
    """

    def test_the_guard_ignores_a_workspace_that_declares_a_different_colour(self, tmp_path):
        """The whole point of `workspace_file=None`.

        Build a workspace that DOES declare a pack for this project, in a colour nothing else
        uses, and require the guard's resolution to be unmoved by it. Without the `None` this
        would pass on a machine with no workspace and fail on one with a workspace — a guard
        whose verdict depends on unversioned state.
        """
        repo = tmp_path / 'design-doc-publish'
        repo.mkdir()
        (repo / '.rawgentic.json').write_text(json.dumps({'vdl': {
            'accent': {'light': '#111111', 'dark': '#eeeeee'},
            'source': 'a workspace this guard must ignore', 'note': 'not the committed colour'}}),
            encoding='utf-8')
        ws = tmp_path / 'workspace.json'
        ws.write_text(json.dumps(
            {'projects': [{'name': 'design-doc-publish', 'path': 'design-doc-publish'}]}),
            encoding='utf-8')

        # Sanity: the workspace really would change the answer if it were consulted.
        assert vdl_packs.pack_for('design-doc-publish', ws)['accent']['light'] == '#111111'
        # And the guard's own resolution is unmoved by it.
        assert resolve_pack('design-doc-publish')['accent']['light'] != '#111111'

    def test_the_answer_comes_from_the_committed_seed_table(self):
        pack = resolve_pack('design-doc-publish')
        assert pack['origin'] == 'seed', (
            f"expected the committed SEEDS entry, got origin={pack['origin']!r}. A 'fallback' "
            f"here means the seed entry is gone and the colour is a name hash again — the #56 "
            f"defect exactly.")
        seed = vdl_packs.SEEDS['design-doc-publish']
        assert pack['accent'] == {'light': seed['light'], 'dark': seed['dark']}

    @pytest.mark.parametrize(
        "project", sorted({p['project'] for p in PAGES.values() if p.get('project')}))
    def test_every_project_the_manifest_names_resolves_to_a_declared_or_seeded_pack(self, project):
        """A project resolving to `fallback` is branding chosen by a name hash. That is fine for
        a stranger's unknown project and wrong for a page committed in this repository."""
        assert resolve_pack(project)['origin'] in ('declared', 'seed'), (
            f"{project} resolves to a hashed fallback, so its committed pages wear a colour "
            f"nobody declared")

    def test_a_page_with_no_project_carries_no_accent_layer(self):
        """`project=None` must mean the default palette, not a silent pack."""
        assert resolve_pack(None) is None
        key = next(k for k, r in PAGES.items() if not r.get('project'))
        page = render_page(key)
        assert '--accent:#0f766e' in page, "the default light accent is missing"
        # Exactly the two default accent values, in the four places the stylesheet declares
        # them. A third value would mean a pack layer leaked onto a pack-free page.
        import re
        assert set(re.findall(r'--accent:#([0-9a-f]{6})', page)) == {'0f766e', '2dd4bf'}
