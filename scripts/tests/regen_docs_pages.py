#!/usr/bin/env python3
"""Regenerate every committed `docs/` page from its own markdown (#56).

Run from anywhere:

    python3 scripts/tests/regen_docs_pages.py

Then commit the result. `test_docs_pages_current.py` fails until you do.

**This module owns the recipe** — the manifest below, and how a page is rendered from it. The
guard imports both from here. The dependency runs this way round for a mechanical reason,
the same one `regen_rendered_styles.py` records: `pytest` is not importable under a bare
`python3` on this host, so a regenerator that imported the test could not run at all. One
source either way; only this direction actually executes.

## Why this exists

`docs/planning/campaign-log.html` was committed missing a whole section of its own markdown,
and re-rendering it with `--project design-doc-publish` also changed the page's accent from
teal to green. Neither was caught, because **not one byte-identity guard in this repository
rendered with a project pack**: `test_byte_identity.py` and `regen_rendered_styles.py` both
omit `vdl`, so the per-project accent layer was invisible to every gate. And nothing at all
covered `docs/examples/gallery/` or `docs/planning/`. A census at the time found **13 of 18
committed pairs stale** — twelve gallery pages missing a link-colour rule, and the campaign log
missing a section.

## Two decisions in here that are load-bearing

**Packs resolve with `workspace_file=None`, always.** Not with the machine's configured
workspace. `pack_for` walks declared → seed → hash, and only the first of those reads disk; a
`None` workspace makes `_project_config` return immediately, so resolution runs over committed
in-module tables only. That is what makes this guard's verdict a property of the repository
rather than of somebody's `~/.config`. A guard whose answer depended on unversioned state
could pass on one clone and fail on another, which is the defect it exists to refuse.

**The stamp is pinned here, not read from the page.** Taking the stamp out of the artifact
under test would be circular — the same circularity that rules out reading the title from it.
The cost is real and is documented rather than hidden: `publish_doc.py` re-renders with the
current wall clock and has no `--generated-at`, and it writes the file before its `--dry-run`
check, so publishing a covered page rewrites the stamp and turns this guard red. That is the
guard telling the truth. The authoring flow is:

    1. edit the markdown
    2. bump that page's `stamp` below
    3. python3 scripts/tests/regen_docs_pages.py
    4. commit the markdown, this file and the regenerated HTML together

## What this does NOT prove

The regenerator and the guard call the same renderer, so together they pin "the committed pages
match what the renderer currently emits" — never "the renderer is correct". Rerun this after
breaking the renderer and the round-trip goes green again. That is inherent to any golden-file
guard. Renderer correctness is pinned independently and elsewhere:
`test_furniture_context.py`'s per-style SHA oracle, `test_byte_identity.py`'s committed
exemplar, and the cross-style guards. Two different failures; this one only ever claimed the
second.

**And the sentinels are NARROWER than an earlier draft of this docstring claimed.** They reject a
short stub and a page missing its doctype, pinned title or pinned stamp — gross truncation and
missing wrapper metadata. A renderer that dropped a section, corrupted markup, or lost a
stylesheet while keeping 2,000 bytes and that metadata would pass every sentinel after
regeneration. The can-it-fail test only proves that appending to the source changes the output,
so it does not close that path either. Corrected after the Step 11 cross-model review named the
overclaim: this guard catches a page that stopped matching the renderer, plus gross truncation,
and nothing more. The failure classes it does not cover are covered elsewhere —
`test_furniture_context.py`'s per-style SHA oracle and the cross-style guards.
"""
import pathlib
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
ROOT = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import render  # noqa: E402
# Direct import, matching `test_vdl_packs.py` and `test_design_system_template.py`. The three
# guarded importlib load sites in `publish_doc.py`, `render/__init__.py` and
# `index/build_index.py` are PRODUCTION paths that must refuse a symlinked target; test-tree
# code reaching the module by sys.path is the established pattern here and adds no fourth
# production load site.
import vdl_packs  # noqa: E402

# The manifest. One entry per committed `docs/**` md+html pair, keyed by the pair's path with
# no extension. `subtitle` defaults to "", `doc_id` and `project` to None.
#
# `project=None` means the page renders in the default palette and carries NO accent layer.
# Template demonstrations are deliberately pack-free: the gallery shows what a STYLE looks
# like, not what this project's documents look like, which is also why
# `docs/design-language-example` and `docs/rendered-styles/*` carry no pack.
PAGES = {
    'docs/design-language-example': dict(
        title='Design-language exemplar',
        style='design', stamp='2026-07-10 12:00 MDT'),

    # --- the README gallery: one realistic document per style, all pack-free ---
    'docs/examples/gallery/analysis': dict(
        title="Why Halyard's miss rate doubled",
        style='analysis', stamp='2026-03-02 09:00 MST'),
    'docs/examples/gallery/dashboard': dict(
        title='Halyard delivery programme',
        style='dashboard', stamp='2026-03-02 09:00 MST'),
    'docs/examples/gallery/design': dict(
        title='Halyard: write-through parcel cache',
        style='design', stamp='2026-03-02 09:00 MST'),
    'docs/examples/gallery/design-system': dict(
        title='Halyard design tokens',
        style='design-system', stamp='2026-03-02 09:00 MST'),
    'docs/examples/gallery/module-map': dict(
        title='Halyard tracking path',
        style='module-map', stamp='2026-03-02 09:00 MST'),
    'docs/examples/gallery/plain': dict(
        title='Why we keep carrier timestamps verbatim',
        style='plain', stamp='2026-03-02 09:00 MST'),
    'docs/examples/gallery/report': dict(
        title='Halyard tracking outage, 14 March',
        style='report', stamp='2026-03-02 09:00 MST'),
    'docs/examples/gallery/review': dict(
        title='Review: Halyard webhook ingestion branch',
        style='review', stamp='2026-03-02 09:00 MST'),
    'docs/examples/gallery/roadmap': dict(
        title='Halyard webhook ingestion plan',
        style='roadmap', stamp='2026-03-02 09:00 MST'),
    'docs/examples/gallery/slide-deck': dict(
        title='Halyard tracking: latency and the fix',
        style='slide-deck', stamp='2026-03-02 09:00 MST'),
    'docs/examples/gallery/spec': dict(
        title='Halyard webhook endpoint specification',
        style='spec', stamp='2026-03-02 09:00 MST'),
    # `uat` persists tester answers in localStorage, so its doc_id is its state namespace and
    # is NOT derived from the title — renaming the title would abandon every saved answer.
    # Recovered from the committed page by comparing data-uat-key against slug(title).
    'docs/examples/gallery/uat': dict(
        title='Halyard webhook ingestion — acceptance pass',
        style='uat', stamp='2026-03-02 09:00 MST', doc_id='halyard-uat'),
    'docs/examples/gallery/workflow': dict(
        title='Runbook: carrier certificate failover',
        style='workflow', stamp='2026-03-02 09:00 MST'),

    # --- this project's own planning documents ---
    'docs/planning/2026-08-23-github-doc-harness-spec': dict(
        title='GitHub-doc harness',
        subtitle='Self-hosted replacement for the Vercel deploy target',
        style='spec', stamp='2026-08-23 23:14 MDT', project='design-doc-publish'),
    # project=None, and this is the "explained and intended" branch rather than an oversight:
    # this page is committed WITHOUT a pack while its two dated siblings carry one. Recording
    # it as it is keeps the page byte-identical. Normalizing every planning document onto the
    # pack is a deliberate visual change and is the owner's call, not this guard's.
    'docs/planning/2026-08-24-37-vercel-backfill': dict(
        title='#37 — Backfill the existing Vercel doc projects into the harness registry',
        style='design', stamp='2026-08-24 12:52 MDT'),
    'docs/planning/2026-08-25-access-architecture-consult': dict(
        title='Zone Access architecture — catch-all with exceptions',
        style='analysis', stamp='2026-08-25 11:21 MDT', project='design-doc-publish'),
    'docs/planning/2026-08-25-56-impl-plan': dict(
        title='Issue #56 — implementation plan',
        style='roadmap', stamp='2026-08-25 14:26 MDT', project='design-doc-publish'),
    'docs/planning/2026-08-25-56-render-determinism': dict(
        title='Issue #56 — a committed page must re-render to itself',
        style='design', stamp='2026-08-25 14:26 MDT', project='design-doc-publish'),
    # Re-rendered by #56 WITH the pack, joining its two dated siblings. Its previous committed
    # copy predated the #52 markdown entry entirely.
    'docs/planning/campaign-log': dict(
        title='design-doc-publish — campaign log',
        style='roadmap', stamp='2026-08-25 14:26 MDT', project='design-doc-publish'),
}


def pairs_on_disk() -> set:
    """Every ALREADY-RENDERED `docs/**` md+html pair, as manifest keys.

    A PAIR is the unit because the guarantee is about re-rendering a page from its own
    markdown, which a page with no markdown cannot satisfy either way. The sourceless
    committed pages are `docs/rendered-styles/*.html`, already guarded by
    `test_rendered_styles_current.py`, and `docs/examples/example-roadmap.html`, which is
    guarded by nothing — stated so it is a known gap rather than an unnoticed one.

    Keyed on the HTML, so this answers "what is already rendered". That is the question the
    undeclared-page check needs, and it is deliberately NOT the whole completeness answer —
    see `missing_sources()`.
    """
    return {str(h.relative_to(ROOT).with_suffix(''))
            for h in ROOT.glob('docs/**/*.html') if h.with_suffix('.md').is_file()}


DOCS = ROOT / 'docs'


def validate_key(key: str) -> None:
    """Refuse a manifest key that could read or write outside `docs/`.

    Added after the Step 8a cross-model review pointed out that keys were joined straight onto
    `ROOT` and then read from and written to. No committed key escapes today — that was checked
    — but "no key does" is not the same as "no key can", and this module's own docstring, and
    the design note's security section, both CLAIM the writes stay under `docs/`. A published
    claim that nothing enforces is the defect; this makes it true rather than asserted.

    The symlink clause is the half worth spelling out, because it is the one the first review
    of this file missed: `write_bytes` FOLLOWS a symlink, so a `docs/foo.html` pointing outside
    the tree would silently take the write with it. `resolve()` collapses the link before the
    containment test, so the check sees where the byte would actually land.
    """
    if not key or key != key.strip():
        raise ValueError(f"manifest key {key!r} is empty or padded")
    if key.startswith('/') or (len(key) > 1 and key[1] == ':'):
        raise ValueError(f"manifest key {key!r} is an absolute path")
    parts = pathlib.PurePosixPath(key).parts
    if '..' in parts:
        raise ValueError(f"manifest key {key!r} contains a '..' component")
    if parts[:1] != ('docs',):
        raise ValueError(f"manifest key {key!r} does not start with 'docs/'")
    for suffix in ('.md', '.html'):
        target = (ROOT / f'{key}{suffix}').resolve()
        if not target.is_relative_to(DOCS.resolve()):
            raise ValueError(
                f"manifest key {key!r} resolves to {target} for {suffix}, outside "
                f"{DOCS} — a symlinked page would take the write out of the tree")


def missing_sources() -> set:
    """Declared pages whose MARKDOWN is absent — the only real authoring error.

    Split out from `pairs_on_disk()` after this regenerator refused to create a page that did
    not exist yet. Requiring the `.html` to be present before writing it is backwards: the
    HTML is this script's OUTPUT, so treating it as a precondition made adding a document
    impossible. The two questions are genuinely different, and conflating them cost a
    self-inflicted refusal:

    * a declared entry with no `.md` is a mistake — nothing can be rendered from nothing;
    * a declared entry with no `.html` is a NEW page, which is how one is normally added.
    """
    return {key for key in PAGES if not (ROOT / f'{key}.md').is_file()}


def undeclared_pairs() -> set:
    """Rendered pairs with no manifest entry. Each one ships unguarded, which is the gap this
    module exists to close, so this direction stays a hard error."""
    return pairs_on_disk() - set(PAGES)


def resolve_pack(project):
    """The pack for `project`, resolved from COMMITTED sources only.

    `None` for the workspace file is the whole point, not a convenience: `_project_config`
    returns immediately on it, so `pack_for` runs seed-then-hash over in-module tables and
    reads nothing from `~/.config`. Passing a real workspace here would make this guard's
    verdict depend on unversioned machine state — the defect it exists to refuse.
    """
    return vdl_packs.pack_for(project, None) if project else None


def render_page(key: str) -> str:
    """One page, from its own markdown and its manifest entry.

    `publish_doc.render()` calls this same `render_artifact` (`publish_doc.py:1265`), so a page
    published through the CLI and a page written here are the same bytes for the same inputs.
    It passes two arguments this manifest does not carry, and both are accounted for:

    * `section_chips` — expressible here, defaulting to True as the CLI does.
    * `telemetry` — deliberately NOT expressible. No committed page embeds a run-record, which
      is proven rather than assumed: every page that round-trips does so with `telemetry=None`.
      Should one ever be published with `--telemetry`, this guard's round-trip FAILS on it
      loudly — it cannot silently bless it — and the fix is to extend this manifest. A loud
      failure on an unsupported input is the right behavior; a silent pass would not be.
    """
    recipe = PAGES[key]
    source = (ROOT / f'{key}.md').read_text(encoding='utf-8')
    return render.render_artifact(
        source,
        title=recipe['title'],
        subtitle=recipe.get('subtitle', ''),
        generated_at=recipe['stamp'],
        style=recipe['style'],
        doc_id=recipe.get('doc_id'),
        vdl=resolve_pack(recipe.get('project')),
        section_chips=recipe.get('section_chips', True))


def render_bytes(key: str) -> bytes:
    """The page as BYTES, which is what gets committed and what the guard must compare.

    `write_text`/`read_text` would let a CRLF-committed page compare equal to an LF render,
    because Python normalises line endings on a text read — so a "byte-identical" guard built
    on text I/O is not one. Taken from `regen_rendered_styles.py`, which records having
    reproduced exactly that: bytes differing while `read_text()` reported equal.
    """
    return render_page(key).encode('utf-8')


def main() -> int:
    # REFUSE rather than reconcile. `regen_rendered_styles.py` deletes a page whose style left
    # the registry, and that is right there because its set is DERIVED from the registry. This
    # manifest is hand-maintained, so a mismatch is an authoring mistake, and deleting a
    # committed document on the strength of a mistake is not a courtesy. Name the difference
    # and stop.
    #
    # Two DIFFERENT faults, and only these two. A declared page whose `.html` is simply not
    # written yet is neither: that is a new document, and writing it is this script's job.
    # Containment BEFORE anything is read or written. A bad key must never reach a read or a
    # write, so this runs ahead of every other check.
    for key in sorted(PAGES):
        validate_key(key)

    faults = False
    for key in sorted(missing_sources()):
        print(f"  NO MARKDOWN       {key}.md is absent — nothing can be rendered from it. "
              f"Remove the manifest entry, or restore the source.", file=sys.stderr)
        faults = True
    for key in sorted(undeclared_pairs()):
        print(f"  NOT IN MANIFEST   {key}.md / .html — add an entry, or this page ships "
              f"unguarded", file=sys.stderr)
        faults = True
    if faults:
        print("\nrefusing to write anything: the manifest and the committed sources disagree",
              file=sys.stderr)
        return 1

    changed = 0
    for key in sorted(PAGES):
        out = ROOT / f'{key}.html'
        before = out.read_bytes() if out.exists() else None
        data = render_bytes(key)
        # BYTES, deliberately: `write_text` applies platform newline translation, which would
        # make the committed pages machine-dependent.
        out.write_bytes(data)
        if before == data:
            verb = 'unchanged'
        else:
            verb = 'created' if before is None else 'updated'
            changed += 1
        print(f"  {key:<56} {verb:9} {len(data):>7} bytes")
    print(f"\n{len(PAGES)} pages written, {changed} changed")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
