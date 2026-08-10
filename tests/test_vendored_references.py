"""Guards for the vendored reference art (#38).

The material under `references/` is third-party HTML and CSS, committed as data. Two things
have to stay true about it, and neither is self-evident from reading the files:

1. No template leaks its header comment onto the rendered page. Upstream writes headers like
   `Replace everything marked <!-- REPLACE: ... --> and the obvious placeholder text`; HTML
   comments do not nest, so the inner `-->` closes the outer comment early and the remainder
   renders as visible text. Nine of the twenty templates did this upstream. The vendoring
   strips the header; these tests stop a refresh putting it back.

2. The set of vendored files is exactly what `manifest.json` says it is. A bare file count
   would pass twenty renamed or substituted templates.

`manifest.json` is a change-detector and an identity record, NOT a proof of upstream fidelity:
it is generated from the same bytes it describes, so a blind regeneration turns these tests
green. The control on that is review of the committed diff. The two correctness invariants
below are deliberately re-derived from the bytes on every run instead of being read out of the
manifest, so they cannot be regenerated away.

Stdlib only, by the same rule as the rest of this skill.
"""

from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

REFERENCES = Path(__file__).resolve().parent.parent / "references"
MANIFEST = REFERENCES / "manifest.json"

DOCTYPE_RE = re.compile(r"\A\s*<!doctype[^>]*>", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<html[\s>]", re.IGNORECASE)


class _VisibleText(HTMLParser):
    """Collect text nodes that a browser would render, skipping script/style content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._suppressed = 0
        self.chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in ("script", "style"):
            self._suppressed += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._suppressed:
            self._suppressed -= 1

    def handle_data(self, data: str) -> None:
        if not self._suppressed and data.strip():
            self.chunks.append(data.strip())


def visible_text(source: str) -> list[str]:
    parser = _VisibleText()
    parser.feed(source)
    return parser.chunks


def leaked_comment_fragments(source: str) -> list[str]:
    """Visible text carrying a stray `-->` — the signature of a comment that closed early."""
    return [chunk for chunk in visible_text(source) if "-->" in chunk]


def head_region(source: str) -> str:
    """The bytes between the doctype and the document's `<html>` tag."""
    doctype = DOCTYPE_RE.search(source)
    assert doctype, "no doctype"
    rest = source[doctype.end():]
    html_tag = HTML_TAG_RE.search(rest)
    assert html_tag, "no <html> tag"
    return rest[: html_tag.start()]


def _load_manifest() -> dict:
    assert MANIFEST.is_file(), f"missing manifest: {MANIFEST}"
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _templates() -> list[Path]:
    """Empty since #2 removed the unlicensed set. Kept so the header-leak guards below
    stay wired: if a future refresh vendors HTML templates again, they are covered the
    moment the directory reappears, with no test needing to be rewritten."""
    directory = REFERENCES / "nsmith-html"
    return sorted(directory.glob("*.html")) if directory.is_dir() else []


def _themes() -> list[Path]:
    return sorted((REFERENCES / "artifact-organizer").glob("*.css"))


# --------------------------------------------------------------------------------------
# Non-vacuity. A guard that cannot fail is not a guard, so prove the detector fires before
# trusting the twenty green assertions below it.
# --------------------------------------------------------------------------------------

NESTED_DEFECT = (
    "<!DOCTYPE html>\n<!--\n  Replace everything marked <!-- REPLACE: x --> and the\n"
    "  obvious placeholder text.\n-->\n<html><body><p>Real</p></body></html>"
)
# Leakage does NOT require a nested opener; a comment that simply closes early leaks too.
UNNESTED_DEFECT = "<html><body><!-- header mentions -->LEAKED TEXT --></body></html>"
CLEAN = (
    '<!DOCTYPE html>\n<!--\n  Search for "REPLACE:" comments.\n-->\n'
    "<html><body><p>Real</p></body></html>"
)


@pytest.mark.parametrize("source", [NESTED_DEFECT, UNNESTED_DEFECT], ids=["nested", "unnested"])
def test_the_leak_detector_actually_fires(source: str) -> None:
    assert leaked_comment_fragments(source), "detector missed a known leak"


def test_the_leak_detector_does_not_cry_wolf() -> None:
    assert leaked_comment_fragments(CLEAN) == []


def test_the_head_check_actually_fires() -> None:
    assert head_region(NESTED_DEFECT).strip(), "head check missed an unstripped header"


# --------------------------------------------------------------------------------------
# The vendored corpus.
# --------------------------------------------------------------------------------------


# Files under references/ that are ours, not vendored payload, and so carry no manifest entry.
METADATA = {"README.md", "manifest.json", "LICENSE-upstream.txt"}


def test_manifest_has_no_duplicate_entries() -> None:
    paths = [entry["path"] for entry in _load_manifest()["files"]]
    assert len(paths) == len(set(paths)), (
        f"duplicate manifest entries: {sorted({p for p in paths if paths.count(p) > 1})}"
    )


def test_manifest_and_disk_agree() -> None:
    """Every vendored file is listed, and nothing unlisted is hiding in the tree.

    Deliberately globs EVERY file rather than just `*.html`/`*.css`: scoping the sweep to the
    extensions we expect is how a stray `notes.js` or `flowchart.html.bak` stays invisible.
    """
    recorded = {entry["path"] for entry in _load_manifest()["files"]}
    on_disk = {
        str(path.relative_to(REFERENCES))
        for path in REFERENCES.rglob("*")
        if path.is_file() and path.name not in METADATA
    }
    assert recorded == on_disk, (
        f"manifest/disk mismatch — only in manifest: {sorted(recorded - on_disk)}; "
        f"only on disk: {sorted(on_disk - recorded)}"
    )


def test_manifest_hashes_match_the_bytes() -> None:
    manifest = _load_manifest()
    for entry in manifest["files"]:
        blob = (REFERENCES / entry["path"]).read_bytes()
        actual = hashlib.sha256(blob).hexdigest()
        assert actual == entry["sha256"], f"{entry['path']} changed since vendoring"


def test_the_expected_counts_are_present() -> None:
    assert len(_themes()) == 7, "expected exactly 7 artifact-organizer themes"
    assert not (REFERENCES / "nsmith-html").exists(), (
        "the nsmith set was removed in #2 for want of an upstream licence grant — see\n"
        "docs/third-party-notices.md before vendoring it again")


@pytest.mark.parametrize("path", _templates(), ids=lambda p: p.stem)
def test_no_template_leaks_its_header(path: Path) -> None:
    leaks = leaked_comment_fragments(path.read_text(encoding="utf-8"))
    assert not leaks, f"{path.name} leaks comment text onto the page: {leaks[:2]}"


@pytest.mark.parametrize("path", _templates(), ids=lambda p: p.stem)
def test_template_head_is_stripped(path: Path) -> None:
    """AC2's discharge: whitespace only between the doctype and <html> proves the header
    bytes are gone, independent of any tokenizer's comment semantics."""
    region = head_region(path.read_text(encoding="utf-8"))
    assert not region.strip(), f"{path.name} still carries a header comment"


# --------------------------------------------------------------------------------------
# Provenance. AC1 requires these facts to be recorded, so make their absence fail.
# --------------------------------------------------------------------------------------

NSMITH_SHA = "eece610140a08ebbfdd96938ee1610b19793d1ec"
ORGANIZER_SHA = "3e5bc0ef00de784dab48b411b3493c7d72d856ca"


def test_provenance_records_the_required_facts() -> None:
    readme = (REFERENCES / "README.md").read_text(encoding="utf-8")
    for needle in (
        "keepYaoung/artifact-organizer",
        ORGANIZER_SHA,
        "MIT",
    ):
        assert needle in readme, f"README.md does not record {needle!r}"
    assert re.search(r"\b20\d{2}-\d{2}-\d{2}\b", readme), "README.md records no ISO vendoring date"


@pytest.mark.parametrize("relative", ["artifact-organizer/LICENSE-upstream.txt"])
def test_licence_evidence_is_retained(relative: str) -> None:
    path = REFERENCES / relative
    assert path.is_file(), f"missing licence evidence: {relative}"
    assert path.read_text(encoding="utf-8").strip(), f"empty licence evidence: {relative}"


def test_the_manifest_records_the_removal_and_its_pin() -> None:
    """#2 removed the nsmith set because no upstream grant exists. The manifest keeps the
    record — including the commit it was pinned at — so restoring it is one command if a
    grant is ever established, and so a silent re-vendoring is visible in the diff."""
    manifest = _load_manifest()
    assert not any(e["upstream_repo"] == "nsmith/html" for e in manifest["files"]), (
        "nsmith files are back in the manifest — see docs/third-party-notices.md")
    removed = manifest.get("removed") or []
    record = [r for r in removed if r["upstream_repo"] == "nsmith/html"]
    assert len(record) == 1, "the manifest must record what was removed and why"
    assert record[0]["upstream_commit"] == NSMITH_SHA, (
        "the removal record must pin the commit the set was vendored at, or it cannot be "
        "restored from it")


# --------------------------------------------------------------------------------------
# External references. The vendored material is NOT free of outbound requests — every theme
# pulls Google Fonts. That is recorded rather than assumed, so a refresh that introduces a
# new external reference fails here instead of being discovered by someone's browser.
# --------------------------------------------------------------------------------------

EXTERNAL_IN_CSS = re.compile(r"@import\s+url\(|url\(\s*['\"]?https?://", re.IGNORECASE)
EXTERNAL_RESOURCE_IN_HTML = re.compile(
    r"""(?:src|href)\s*=\s*['"]https?://[^'"]+\.(?:css|js|png|jpe?g|gif|svg|woff2?)"""
    r"""|@import\s+url\(|url\(\s*['"]?https?://""",
    re.IGNORECASE,
)

# Measured at the pinned commits. Every theme imports Google Fonts; no template loads anything.
THEMES_WITH_FONT_IMPORT = {
    "apple.css", "linear.css", "notion.css", "stripe.css",
    "supabase.css", "tailwind.css", "vercel.css",
}


def test_theme_external_imports_are_exactly_the_recorded_set() -> None:
    found = {path.name for path in _themes() if EXTERNAL_IN_CSS.search(path.read_text("utf-8"))}
    assert found == THEMES_WITH_FONT_IMPORT, (
        "the vendored themes' external-import inventory changed — re-review it, then update "
        f"THEMES_WITH_FONT_IMPORT. Newly importing: {sorted(found - THEMES_WITH_FONT_IMPORT)}; "
        f"no longer importing: {sorted(THEMES_WITH_FONT_IMPORT - found)}"
    )


@pytest.mark.parametrize("path", _templates(), ids=lambda p: p.stem)
def test_no_template_loads_an_external_resource(path: Path) -> None:
    hit = EXTERNAL_RESOURCE_IN_HTML.search(path.read_text(encoding="utf-8"))
    assert not hit, f"{path.name} loads an external resource: {hit.group(0)!r}"
