"""The README gallery has one realistic example per style, and none of it is stale.

`docs/rendered-styles/` already renders every style, but from ONE cross-style fixture that crams
every typed block onto every page. That proves the component set. It does not show what a plan
reads like next to an audit, because the content is identical in all thirteen.

The gallery under `docs/examples/gallery/` is the other half: a different fictional document per
style, written to suit that style's purpose. All of it is invented — a made-up parcel carrier —
so nothing in the repository's own history or anyone's real documents ends up in the README.

These guards keep three things from rotting apart: the style registry, the files on disk, and the
README that links them. A style added without an example, an example whose source stops rendering,
and a README that links a file nobody committed are each a broken promise to a reader.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
GALLERY = ROOT / "docs" / "examples" / "gallery"
README = ROOT / "README.md"

sys.path.insert(0, str(ROOT / "scripts"))
from render import templates as render_templates  # noqa: E402

STYLES = ["plain"] + sorted(render_templates.TEMPLATES)


class TestEveryStyleHasAnExample:
    def test_the_source_markdown_exists(self):
        missing = [s for s in STYLES if not (GALLERY / f"{s}.md").is_file()]
        assert not missing, (
            f"styles with no gallery source: {missing}. Add one, or the README promises a "
            "page that does not exist")

    def test_the_rendered_page_exists(self):
        missing = [s for s in STYLES if not (GALLERY / f"{s}.html").is_file()]
        assert not missing, f"styles with no rendered gallery page: {missing}"

    def test_the_screenshot_exists(self):
        """GitHub shows raw source for a committed `.html`, so the PNG is what a reader sees."""
        missing = [s for s in STYLES if not (GALLERY / f"{s}.png").is_file()]
        assert not missing, f"styles with no gallery screenshot: {missing}"

    def test_nothing_extra_lingers(self):
        """A removed style must not leave a page behind, claiming to be current."""
        stale = {p.stem for p in GALLERY.glob("*.md")} - set(STYLES)
        assert not stale, (
            f"gallery sources for styles that are not in the registry: {sorted(stale)}")


class TestTheExamplesAreDistinct:
    def test_no_two_sources_are_the_same_document(self):
        """The whole point is that a plan does not read like an audit. Identical sources would
        make the gallery a second copy of the cross-style fixture."""
        seen = {}
        for style in STYLES:
            text = (GALLERY / f"{style}.md").read_text(encoding="utf-8").strip()
            assert text not in seen, (
                f"{style}.md is byte-identical to {seen[text]}.md — the gallery exists to show "
                "different documents, not one document thirteen times")
            seen[text] = style

    def test_each_source_still_renders(self, tmp_path):
        """A source that no longer renders makes its committed page a fossil."""
        for style in STYLES:
            out = tmp_path / f"{style}.html"
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "render-doc"),
                 "--md", str(GALLERY / f"{style}.md"), "--out", str(out),
                 "--title", "gallery check", "--style", style],
                capture_output=True, text=True)
            assert proc.returncode == 0, (
                f"{style}.md no longer renders: {proc.stderr.strip()[:300]}")
            assert out.is_file() and out.stat().st_size > 0


class TestTheReadmeLinksThem:
    def test_every_style_is_linked_in_the_readme(self):
        body = README.read_text(encoding="utf-8")
        missing = [s for s in STYLES
                   if f"docs/examples/gallery/{s}.md" not in body]
        assert not missing, (
            f"the README gallery does not link these styles: {missing}")

    def test_every_linked_gallery_file_exists(self):
        """A link to a file nobody committed is worse than no link."""
        body = README.read_text(encoding="utf-8")
        broken = [ref for ref in re.findall(r"docs/examples/gallery/[\w.-]+", body)
                  if not (ROOT / ref).is_file()]
        assert not broken, f"README links files that are not on disk: {sorted(set(broken))}"
