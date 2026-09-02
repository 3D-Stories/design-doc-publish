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
oracle, `test_byte_identity.py`'s committed exemplar, and the cross-style guards.

**The sentinels below are NARROWER than an earlier draft of this docstring claimed.** They catch
gross truncation and missing wrapper metadata — not a dropped section or corrupted markup that
keeps 2,000 bytes, the doctype, the pinned title and the pinned stamp. The can-it-fail test only
proves that appending to the source changes the output. Corrected after the Step 11 cross-model
review named the overclaim; the uncovered failure classes belong to the guards listed above.
"""
import json
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))

from regen_docs_pages import (  # noqa: E402
    PAGES, ROOT, missing_sources, render_bytes, render_page, resolve_pack, undeclared_pairs,
    validate_key,
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


def test_every_declared_page_has_a_markdown_source():
    """A manifest entry whose `.md` is gone is an authoring mistake — nothing can be rendered
    from nothing, and a deleted document must not leave an entry behind claiming coverage.

    Deliberately NOT keyed on the `.html`. The HTML is the regenerator's OUTPUT, so requiring
    it to pre-exist would make adding a document impossible — a conflation that cost a
    self-inflicted refusal before it was split apart.
    """
    absent = missing_sources()
    assert not absent, (
        f"declared with no markdown: {sorted(absent)}\n"
        f"remove the entry in regen_docs_pages.py, or restore the source")


def test_every_rendered_pair_is_declared():
    """The other direction, and the one that matters for coverage: a committed page with a
    markdown sibling that nobody declared ships unguarded, which is the gap this module
    exists to close."""
    undeclared = undeclared_pairs()
    assert not undeclared, (
        f"rendered but not in the manifest: {sorted(undeclared)}\n"
        f"add an entry in regen_docs_pages.py — an undeclared pair ships unguarded")


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

        # The guard's resolution is unmoved by it.
        assert resolve_pack('design-doc-publish')['accent']['light'] != '#111111'
        # And since #56's production fix, so is the PRODUCTION path — which is the stronger
        # claim and the one acceptance criterion 2 actually asks for. This assertion replaces
        # an earlier "sanity check" that asserted the opposite: that a workspace WOULD change
        # the answer if consulted. It would have, before the fix; that was the Critical the
        # cross-model review found, and the guard alone could never see it.
        assert vdl_packs.pack_for('design-doc-publish', ws)['accent']['light'] != '#111111'
        assert (vdl_packs.pack_for('design-doc-publish', ws)['accent']
                == resolve_pack('design-doc-publish')['accent'])

    def test_the_answer_comes_from_a_COMMITTED_source_and_never_the_hash(self):
        """The property that matters is never-the-hash, not which committed table answers.

        Re-asserted after #56's production fix moved the answer from `seed` to `declared`: this
        repository's own committed declaration is now consulted first. Both are committed, both
        carry the same colour (pinned by `test_the_declaration_and_the_seed_carry_THE_SAME_COLOURS`),
        and `fallback` is the defect either way.
        """
        pack = resolve_pack('design-doc-publish')
        assert pack['origin'] in ('declared', 'seed'), (
            f"origin={pack['origin']!r}. A 'fallback' here means both committed sources are "
            f"unreachable and the colour is a name hash again — the #56 defect exactly.")
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


class TestManifestKeysCannotEscapeTheDocsTree:
    """#56, Step 8a cross-model review — a claim this module publishes, now enforced.

    Keys were joined straight onto `ROOT` and then read from and written to. No committed key
    escapes, which was checked — but "none does" is not "none can", and both this module's
    docstring and the design note's security section CLAIM the writes stay under `docs/`. An
    unenforced published claim is the defect.
    """

    def test_every_committed_key_passes(self):
        for key in PAGES:
            validate_key(key)

    @pytest.mark.parametrize("key", [
        '/etc/passwd',                 # absolute
        'C:/Windows/system32/x',       # absolute, drive-letter form
        'docs/../../etc/shadow',       # traversal out through docs
        '../docs/elsewhere',           # traversal before docs
        'notdocs/page',                # outside docs entirely
        'docs',                        # the directory itself, no page
        '',                            # empty
        ' docs/padded',                # padded
        'docs/trailing ',              # padded the other way
    ])
    def test_a_dangerous_key_is_refused(self, key):
        with pytest.raises(ValueError):
            validate_key(key)

    def test_a_symlinked_page_is_refused(self, tmp_path, monkeypatch):
        """The half the first review of this file MISSED.

        `write_bytes` FOLLOWS a symlink, so a `docs/foo.html` pointing outside the tree would
        silently carry the write with it — no traversal in the key at all. `resolve()` collapses
        the link before the containment test, so the check sees where the byte would land rather
        than where the key says it would.
        """
        import regen_docs_pages as rdp
        fake_root = tmp_path / 'repo'
        (fake_root / 'docs' / 'planning').mkdir(parents=True)
        outside = tmp_path / 'outside'
        outside.mkdir()
        (outside / 'stolen.html').write_text('', encoding='utf-8')
        (fake_root / 'docs' / 'planning' / 'trap.md').write_text('# x', encoding='utf-8')
        (fake_root / 'docs' / 'planning' / 'trap.html').symlink_to(outside / 'stolen.html')

        monkeypatch.setattr(rdp, 'ROOT', fake_root)
        monkeypatch.setattr(rdp, 'DOCS', fake_root / 'docs')
        with pytest.raises(ValueError, match='outside'):
            rdp.validate_key('docs/planning/trap')

    def test_a_plain_page_under_a_fake_root_is_accepted(self, tmp_path, monkeypatch):
        """The negative control: the symlink test must fail for the SYMLINK, not merely because
        the root was swapped. Without this, a validator that rejected everything would pass."""
        import regen_docs_pages as rdp
        fake_root = tmp_path / 'repo'
        (fake_root / 'docs' / 'planning').mkdir(parents=True)
        (fake_root / 'docs' / 'planning' / 'ok.md').write_text('# x', encoding='utf-8')
        (fake_root / 'docs' / 'planning' / 'ok.html').write_text('', encoding='utf-8')
        monkeypatch.setattr(rdp, 'ROOT', fake_root)
        monkeypatch.setattr(rdp, 'DOCS', fake_root / 'docs')
        rdp.validate_key('docs/planning/ok')
