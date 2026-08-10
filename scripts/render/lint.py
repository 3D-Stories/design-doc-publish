"""Pre-publish lint gate: stamp, title, external requests, contrast (wave 5, #12).

The gate `publish_doc.py` runs BEFORE a page is allowed to deploy. The issue's own
pipeline sketch put it after the deploy, but AC4 requires a failure to leave "nothing
deployed" — those cannot both hold, so it runs on the rendered file and a failure means
the deploy never happens.

FOUR MECHANICAL CHECKS, NO JUDGMENT. Each returns findings; the caller decides. "Does it
look right" is deliberately not automated and stays a human call.

Two distinctions this module exists to get right, both of which a first draft got wrong
and a design gate caught:

* **A link is not a request.** An `<a href>` to an external site is a citation and is
  ALLOWED. Only things the browser *fetches* are barred. Conflating them fails every page
  that cites a source.
* **A date is not a stamp.** The Edmonton timestamp must sit in the page furniture — the
  footer or the eyebrow — not anywhere in the document. Unanchored, any date quoted in
  body prose satisfies the check and a page with no stamp passes.
"""
from __future__ import annotations

import html as _html          # aliased: `html` is this module's parameter name for page text
import re
from html.parser import HTMLParser as _HTMLParser
from pathlib import Path

# --- 1. the Edmonton stamp ----------------------------------------------------------

STAMP = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} (?:MDT|MST)")

# The page furniture the renderer emits. A stamp anywhere else is prose, not a stamp.
_FURNITURE = (
    re.compile(r"<footer\b.*?</footer>", re.S | re.I),
    re.compile(r'<div class="eyebrow">.*?</div>', re.S | re.I),
)


def check_stamp(html: str) -> list[str]:
    for region in _FURNITURE:
        for m in region.finditer(html):
            if STAMP.search(m.group(0)):
                return []
    if STAMP.search(html):
        return ["an America/Edmonton stamp appears in the body but not in the footer or "
                "eyebrow — a date quoted in prose is not a page stamp"]
    return ["no America/Edmonton timestamp (YYYY-MM-DD HH:MM MDT/MST) in the footer or eyebrow"]


# --- 2. the title -------------------------------------------------------------------

_TITLE = re.compile(r"<title>(.*?)</title>", re.S | re.I)
_PLACEHOLDERS = {"", "untitled", "document", "title", "t", "x"}


def check_title(html: str) -> list[str]:
    m = _TITLE.search(html)
    if not m:
        return ["no <title> element"]
    title = m.group(1).strip()
    if title.lower() in _PLACEHOLDERS:
        return [f"<title> is a placeholder ({title!r})"]
    return []


# --- 3. zero external requests -------------------------------------------------------

# Anything the browser FETCHES. `<a href>` is deliberately absent — see the module
# docstring. `href` is checked only on <link> and inside SVG, both of which do fetch.
_FETCHING_ATTRS = (
    (re.compile(r"""<link\b[^>]*?\bhref\s*=\s*["']([^"']+)["']""", re.I), "<link href>"),
    (re.compile(r"""\bsrc\s*=\s*["']([^"']+)["']""", re.I), "src"),
    (re.compile(r"""\bsrcset\s*=\s*["']([^"']+)["']""", re.I), "srcset"),
    (re.compile(r"""\bposter\s*=\s*["']([^"']+)["']""", re.I), "poster"),
    (re.compile(r"""<object\b[^>]*?\bdata\s*=\s*["']([^"']+)["']""", re.I), "<object data>"),
    (re.compile(r"""\bxlink:href\s*=\s*["']([^"']+)["']""", re.I), "xlink:href"),
    (re.compile(r"""<(?:use|image)\b[^>]*?\bhref\s*=\s*["']([^"']+)["']""", re.I), "svg href"),
    # The url runs to the END of `content`, and must NOT stop at `;` — every character
    # reference ends in one, so a `;`-terminated capture truncated `&#47;&#47;host` to `&#47`
    # and read it as a single slash, i.e. internal (#123). The `;` in `content="0; url=…"`
    # separates the delay from the url and is already consumed before the capture starts.
    (re.compile(r"""<meta\b[^>]*?http-equiv\s*=\s*["']refresh["'][^>]*?"""
                r"""content\s*=\s*["'][^"']*?url\s*=\s*([^"']+)""", re.I), "meta refresh"),
)

# CSS is matched only where a browser actually PARSES CSS — see `_css_regions`. Scanning the
# whole document for `url()` classified prose as CSS: a page documenting `url(https://host/x)`
# inside a `<code>` span was refused although nothing fetches it, and this repo's own campaign
# log tripped it (#123). Text is not a stylesheet.
_CSS_FETCHERS = (
    (re.compile(r"""@import\s+(?:url\()?["']?([^"')\s;]+)""", re.I), "@import"),
    (re.compile(r"""\burl\(\s*["']?([^"')]+)["']?\s*\)""", re.I), "css url()"),
)

class _CssRegions(_HTMLParser):
    """Every stretch of text a browser hands to the CSS parser.

    A REGEX CANNOT DO THIS, and the first attempt proved it by opening two fail-open holes that
    the old whole-document scan had covered: `style=background:url(//host/x)` (unquoted, so no
    quote to match), `style="background:url('//host/x')"` (the capture stopped at the inner
    single quote), and `</style >` (an end tag may carry whitespace before `>`, so the raw-text
    element never appeared to close). Each was a published external request. The stdlib
    tokeniser already implements the real HTML rules, so it decides what is CSS.

    It also gets the #123 asymmetry right for free, which is the whole reason context matters:
    a `<style>` element's content is RAW TEXT, so `url(&#47;&#47;host)` there stays those
    literal characters and fetches nothing, while an attribute value IS decoded before CSS sees
    it — so the same bytes in `style="…"` really do resolve to `//host`. Attribute values
    arrive here already HTML-decoded; do NOT decode them a second time.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.regions: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == "style":
            self._depth += 1
        for name, value in attrs:
            if name.lower() == "style" and value:
                self.regions.append(value)

    def handle_endtag(self, tag):
        if tag == "style" and self._depth:
            self._depth -= 1

    def handle_data(self, data):
        if self._depth:
            self.regions.append(data)


def _css_regions(html: str) -> list[str]:
    parser = _CssRegions()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # Fail CLOSED. A page this gate cannot tokenise gets the old whole-document scan, which
        # over-refuses (prose reads as CSS) rather than admitting an unexamined stylesheet.
        return [html]
    return parser.regions

# A scheme (`https:`, `javascript:` …) or a protocol-relative `//host`. Protocol-relative
# is the one a first draft missed entirely — `//evil.example/x.js` fetches just fine.
_PROTOCOL_RELATIVE = re.compile(r"^\s*//")
_SCHEME = re.compile(r"^\s*(?!data:)[a-z][a-z0-9+.-]*:", re.I)


def _is_external(url: str) -> bool:
    """True when fetching this URL would leave the page's own origin.

    Note what this does NOT do: it never compares hosts, because a renderer has no idea what
    origin its output will be served from. It refuses ANY url that carries a scheme (other
    than `data:`, which is inline) or is protocol-relative — so an ABSOLUTE url is refused
    even when it happens to name the page's own future host. That is deliberately stricter
    than an off-host test, and it is the only rule that can be enforced at render time.
    """
    # A browser treats `\` as `/` while resolving a URL with a special scheme, so `/\host/x`
    # and `\/host/x` fetch `host` exactly as `//host/x` does. Measured in Chrome: a page
    # carrying `<img src="/\evil.example/x.png">` reported its DOM src as
    # http://evil.example/x.png, and this check used to call that URL internal — so the gate
    # passed the page as clean (#23). Classify on a NORMALISED COPY; nothing here rewrites
    # the URL that was emitted, and a backslash inside a genuinely relative path
    # (`dir\file.png`) still classifies as internal.
    url = url.replace("\\", "/")
    if url.startswith("#"):
        return False
    return bool(_PROTOCOL_RELATIVE.match(url) or _SCHEME.match(url))


# The URL Standard's two cleanup steps, in its order: strip any leading/trailing C0 control
# OR space, then remove every TAB, LF and CR anywhere. Python's own `.strip()` is NOT this
# set — it leaves U+0001 in place, which is enough to hide a `//host` prefix from the
# classifier while a browser discards it and fetches (#23).
_URL_TRIM = "".join(chr(c) for c in range(0x21))
_URL_REMOVE = str.maketrans("", "", "\t\n\r")


def _url_value(raw: str) -> str:
    return raw.strip(_URL_TRIM).translate(_URL_REMOVE)


def _clip(s: str, limit: int = 80) -> str:
    """Readable and host-preserving. A plain `[:80]` can cut before the host — after a long
    `user:pass@` the truncated text looks harmless — so keep both ends when clipping."""
    s = s.replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")
    if len(s) <= limit:
        return s
    return f"{s[:limit // 2]}…{s[-(limit // 2 - 1):]}"


# ASCII whitespace, as the HTML spec defines it for splitting attribute values.
_ASCII_WS = " \t\n\r\f"

# The CSS escape: a reverse solidus followed by 1–6 hex digits and ONE optional trailing
# whitespace, or by any other single character (which then stands for itself).
_CSS_ESCAPE = re.compile(r"\\(?:([0-9a-fA-F]{1,6})[ \t\n\r\f]?|([^\n\r\f0-9a-fA-F]))")


def _css_decode(value: str) -> str:
    """CSS consumes escaped code points BEFORE the URL is resolved, so `\\2f\\2f host` is
    `//host` by the time anything fetches it (#123)."""
    def one(m: re.Match) -> str:
        if m.group(1) is None:
            return m.group(2)
        cp = int(m.group(1), 16)
        # The spec maps NULL, surrogates and out-of-range values to U+FFFD.
        if cp == 0 or 0xD800 <= cp <= 0xDFFF or cp > 0x10FFFF:
            return "�"
        return chr(cp)
    return _CSS_ESCAPE.sub(one, value)


def _srcset_candidates(value: str) -> list[str]:
    """`srcset` per the HTML candidate-scanning algorithm, NOT a comma split (#123).

    A browser collects each URL up to ASCII WHITESPACE, so a comma can belong to the URL
    itself — `srcset="/asset,//host/x.png 1x"` is ONE same-origin url, and a `data:` uri's
    mandatory comma splits its own payload. A comma only separates candidates when it either
    trails the collected url or follows that candidate's descriptors.
    """
    out: list[str] = []
    i, n = 0, len(value)
    while i < n:
        while i < n and (value[i] in _ASCII_WS or value[i] == ","):
            i += 1
        if i >= n:
            break
        start = i
        while i < n and value[i] not in _ASCII_WS:
            i += 1
        url = value[start:i]
        if url.endswith(","):
            url = url.rstrip(",")          # those commas were separators, not url bytes
        else:
            while i < n and value[i] != ",":   # skip this candidate's descriptors
                i += 1
        if url:
            out.append(url)
    return out


def _candidates(value: str, what: str) -> list[str]:
    """The URL(s) one fetching attribute carries.

    EVERY attribute except `srcset` is ONE url and must NOT be split — not on whitespace and
    not on commas. Splitting on whitespace and classifying only the first token is what let
    `/<TAB>/evil.example/x` read as `/`, i.e. internal, while a browser removes the tab and
    resolves `//evil.example/x` (#23).
    """
    if what == "srcset":
        return _srcset_candidates(value)
    return [value]


# `@import` and `url()` are matched inside RAW STYLESHEET TEXT, where the HTML parser does not
# decode character references — so `&#47;&#47;host` there is literally those characters and
# fetches nothing. Everywhere else the value came from an HTML attribute, which IS decoded
# before the URL is resolved. Decoding everything in one pass would be wrong in both
# directions, so the context decides (#123).
_CSS_CONTEXTS = frozenset({"@import", "css url()"})


def _interpretations(candidate: str, what: str) -> list[str]:
    """Every string this one source url could mean by the time a browser fetches it.

    The raw text is always included, and the classifier refuses if ANY interpretation is
    external. Decode-then-classify would be a REGRESSION, not a fix: CSS-unescaping
    `/\\evil.example/b.png` consumes `\\e` as a one-digit hex escape and yields
    `/\\x0evil.example/b.png`, which carries no `//` prefix and reads as internal — silently
    losing the reverse-solidus catch #23 added. Refusing on any interpretation keeps both, and
    keeps the gate failing CLOSED.
    """
    seen = [candidate]
    extra = _css_decode(candidate) if what in _CSS_CONTEXTS else _html.unescape(candidate)
    if extra != candidate:
        seen.append(extra)
    return seen


def _findings(text: str, matchers, out: list[str]) -> None:
    for pattern, what in matchers:
        for m in pattern.finditer(text):
            for candidate in _candidates(m.group(1), what):
                for interpretation in _interpretations(candidate, what):
                    url = _url_value(interpretation)
                    if url and _is_external(url):
                        # Report what the author WROTE, and what it resolves to when the two
                        # differ — a normalised-only message names a string absent from the
                        # source, which is exactly what makes the offending line hard to find.
                        raw, shown = _clip(candidate.strip()), _clip(url)
                        detail = raw if raw == shown else f"{raw} (resolves as {shown})"
                        out.append(f"external request via {what}: {detail}")
                        break   # one finding per url, not one per interpretation


def check_external_requests(html: str) -> list[str]:
    out: list[str] = []
    _findings(html, _FETCHING_ATTRS, out)
    for region in _css_regions(html):
        _findings(region, _CSS_FETCHERS, out)
    return out


# Any scheme at all, `data:` included — unlike `_SCHEME`, which deliberately exempts `data:`
# because an inline payload is not an external request. Here the question is different: a
# reference with a scheme is not a file this repo can ship.
_ANY_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I | re.ASCII)


def internal_references(html: str) -> list[str]:
    """Every url the page FETCHES that is not external — the files that must ship beside it.

    Deliberately the same enumeration and the same definition of "external" that
    `check_external_requests` uses, so the gate and the publisher can never disagree about what
    a page fetches (#121). A page whose reference this returns and whose file does not ship is
    exactly the silent 404 #121 exists to remove.

    Excluded: fragments (same document), anything carrying a scheme (`data:` payloads are inline,
    `https:` is somebody else's server), and anything `_is_external` refuses. What remains is
    path-shaped — including a root-relative `/x.png`, which is returned rather than dropped
    because the CALLER owns the policy on it, and silently ignoring a reference is how the
    original defect behaved.

    Order is first-appearance and duplicates are collapsed, so two references to one file are
    one entry.
    """
    found: list[str] = []
    def collect(text: str, matchers) -> None:
        for pattern, what in matchers:
            for m in pattern.finditer(text):
                for candidate in _candidates(m.group(1), what):
                    url = _url_value(candidate)
                    if (not url or url.startswith("#")
                            or _ANY_SCHEME.match(url) or _is_external(url)):
                        continue
                    found.append(url)

    collect(html, _FETCHING_ATTRS)
    for region in _css_regions(html):
        collect(region, _CSS_FETCHERS)

    seen: set[str] = set()
    return [u for u in found if not (u in seen or seen.add(u))]


# --- 4. AA contrast ------------------------------------------------------------------

def _luminance(hex_colour: str) -> float:
    """WCAG 2.1 relative luminance."""
    h = hex_colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    parts = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        parts.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = parts
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# (foreground token, background token, minimum ratio, why that minimum).
#
# ENUMERATED ON PURPOSE. An earlier draft claimed it would test "the pairs actually used"
# by parsing declarations — incoherent, because parsing finds VALUES while a table decides
# what is TESTED. The gap is closed by a TEST instead: every token defined in `_STYLE` or
# `_COMPONENT_STYLE` must appear somewhere in this table, so adding a token turns the
# suite red until someone classifies it. Loud beats silent.
PAIRS = (
    ("--ink", "--bg", 4.5, "primary body text"),
    ("--ink", "--surface", 4.5, "body text on a card"),
    ("--ink-2", "--bg", 4.5, "secondary body copy"),
    ("--ink-2", "--surface", 4.5, "secondary copy on a card"),
    ("--ink-3", "--bg", 4.5, "muted text is still text"),
    ("--accent", "--bg", 4.5, "the eyebrow and links are text"),
    ("--accent", "--surface", 4.5, "accent text on a card"),
    # A hairline card/table rule is DECORATIVE — WCAG 1.4.11 covers controls and meaningful
    # graphics, not every divider. Requiring 3.0 here was my own misclassification, and
    # loosening it to "must merely differ" is the honest call, not a fudge to pass.
    ("--line", "--bg", 1.0, "a divider rule is decorative, not a control boundary"),
    ("--code", "--bg", 1.0, "a code FILL only has to differ, not contrast"),
    ("--sev-crit", "--sev-crit-bg", 4.5, "badge text on its own fill"),
    ("--sev-high", "--sev-high-bg", 4.5, "badge text on its own fill"),
    ("--sev-med", "--sev-med-bg", 4.5, "badge text on its own fill"),
    ("--sev-low", "--sev-low-bg", 4.5, "badge text on its own fill"),
    ("--req-c", "--req-c-bg", 4.5, "badge text on its own fill"),
    ("--chip-c", "--chip-c-bg", 4.5, "chip text on its own fill"),
    # The green phase chip and badge are `--chip-c` on `--sev-low-bg`, a pair this list did not
    # carry — so the one chip an author reads as "finished" was the one colour nothing gated.
    # It passes today (7.54 dark, 4.82 light); adding it keeps that true after the next retune.
    ("--chip-c", "--sev-low-bg", 4.5, "the finished-state chip on its own fill"),
    ("--defer", "--defer-bg", 4.5, "chip text on its own fill"),
)

# The EXPLICIT toggle blocks, not the bare `:root{`. A bare-`:root` regex also matches the
# `:root{...}` nested inside `@media(prefers-color-scheme:dark)`, so "light" was being
# overwritten with dark values and every light-theme ratio was silently the dark one. Found
# by running the gate on a real page and disbelieving that both themes scored identically.
#
# #73 anchors these to the start of a line, which is the same bug one layer along. The forced-dark
# print block selects `:root,:root[data-theme=dark]` and restores LIGHT values, so an unanchored
# pattern matched inside it and scored the light values as "dark" — the print block being last,
# it won. Every emitter (base stylesheet, roadmap layer, component layer, VDL pack) puts a toggle
# block at the start of its own line and a nested one never is, so anchoring reads only the real
# toggles and cannot be defeated by reordering a selector list.
_THEME_BLOCKS = (
    ("light", re.compile(r"^:root\[data-theme=light\]\{([^}]*)\}", re.M)),
    ("dark", re.compile(r"^:root\[data-theme=dark\]\{([^}]*)\}", re.M)),
)
_TOKEN = re.compile(r"(--[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{3,8})")


def theme_tokens(css: str) -> dict[str, dict[str, str]]:
    """`{theme: {token: hex}}` read from the emitted stylesheet, never hardcoded."""
    out: dict[str, dict[str, str]] = {}
    for theme, block in _THEME_BLOCKS:
        found: dict[str, str] = {}
        for m in block.finditer(css):
            found.update(dict(_TOKEN.findall(m.group(1))))
        if found:
            out[theme] = found
    return out


def check_contrast(html: str) -> list[str]:
    m = re.search(r"<style>(.*?)</style>", html, re.S)
    if not m:
        return ["no <style> block to check contrast against"]
    out: list[str] = []
    for theme, tokens in theme_tokens(m.group(1)).items():
        for fg, bg, minimum, why in PAIRS:
            if fg not in tokens or bg not in tokens:
                continue  # a template that does not inject this layer
            ratio = contrast(tokens[fg], tokens[bg])
            if ratio < minimum:
                out.append(f"{theme}: {fg} on {bg} is {ratio:.2f}:1, below {minimum} ({why})")
    return out


CHECKS = (
    ("stamp", check_stamp),
    ("title", check_title),
    ("external-requests", check_external_requests),
    ("contrast", check_contrast),
)


def lint(html: str) -> list[str]:
    """Every finding, prefixed by the check that raised it. Empty means the page passes."""
    out: list[str] = []
    for name, fn in CHECKS:
        out.extend(f"{name}: {finding}" for finding in fn(html))
    return out


# --- #127: a styled page with none of its style's components -------------------------
#
# DELIBERATELY NOT IN `CHECKS`. This is a PUBLISH policy, not a page defect: rendering a
# document that declares no components is the renderer correctly rendering what it was
# given, and `TestTheEnginePassesItsOwnGate` exists to prove the engine's own output
# passes its own gate. `lint()` is asserted `== []` at twelve sites on prose-only
# fixtures. `publish_doc.gate()` calls this alongside `lint()`, which is where publishing
# — and therefore the policy — actually lives.

# The body class, and ONLY on the body tag. `plain` is the one style that emits no class
# at all (`render/__init__.py:647`), so a match here IS the definition of "styled" — no
# exemption list that can go stale, and pages this engine never drew are exempt for free.
# #150. The previous regex was `<body[^>]*\bclass="tpl-([a-z-]+)"`, which matched only when
# `tpl-<style>` was the ENTIRE double-quoted lowercase attribute value. Cross-model review raised
# it twice during #130 and it was declined both times with a stated reason — this matcher is
# shared with `check_blocks`, so changing it changes the base check, which #130 put out of scope.
# #150 is that scope. All four of these produced NO match, so a genuinely styled page was treated
# as one this engine never drew and was exempt from every component check:
#
#     <body class="theme tpl-roadmap">   tpl- not first
#     <body class="tpl-roadmap extra">   not the whole value
#     <BODY class="tpl-roadmap">         no re.I
#     <body class='tpl-roadmap'>         single quotes
#
# Measured then and re-measured here: the renderer emits none of those, so this was latent rather
# than live — which is precisely when it is cheap to close.
#
# Tokenising, for the same reason `_block_tags_present` tokenises: three rounds of boundary-tuning
# on the block-class regex each left another spoofable variant, and "the token is exactly `tpl-<x>`"
# is not a thing a boundary expresses.
class _BodyClasses(_HTMLParser):
    """Every `<body>` start tag's `class` attribute, in document order.

    A REGEX CANNOT DO THIS EITHER, and a first attempt at one proved it exactly as the
    `_CssRegions` docstring above records for CSS. Four defects, found by probing this
    function against itself before it shipped:

    * `<body title="a>b" class="tpl-roadmap">` — `<body\\b[^>]*>` stops at the `>` INSIDE the
      quoted title, so the class was never seen and a genuinely styled page escaped all three
      component checks. **That is a fail-open**, the one direction that matters.
    * `<body data-class="tpl-roadmap">` — `\\bclass` matches the tail of `data-class`, because
      `\\b` sits happily between `-` and `c`. A page with no template class was gated as though
      it had one.
    * a `tpl-` class inside an HTML COMMENT was collected as though it were markup.
    * so was one inside an attribute VALUE elsewhere on the page.

    The stdlib tokeniser already implements the real HTML rules — quoting, tag case, attribute
    names, character references, and the fact that a comment is not a tag — so it decides what a
    body class is. `convert_charrefs=True` means values arrive already decoded; do NOT decode
    them a second time.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.values: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag != "body":
            return
        for name, value in attrs:
            if name.lower() == "class" and value:
                self.values.append(value)


def template_styles(html: str) -> list[str]:
    """Every `tpl-<style>` token on every `<body>` tag, in document order.

    A list, not a set, and every body inspected rather than the first: the count is what
    `check_template_classification` uses to refuse a document with two bodies, which can
    otherwise spread one page's required devices across them.

    A page with no `tpl-` token stays exempt, and that is load-bearing: `plain` emits no body
    class at all, and neither does a hand-rolled or pre-engine page — six of fourteen published
    pages sampled on 2026-08-03 were exactly that (#128). Refusing those would refuse every page
    this engine did not draw.
    """
    parser = _BodyClasses()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # Fail CLOSED, the same way `_css_regions` does: fall back to the whole document. A
        # page this gate cannot tokenise gets OVER-classified (any `tpl-` token anywhere is
        # treated as the page's style) rather than silently exempted, because an exemption is
        # the failure this function exists to prevent.
        parser.values = re.findall(r'class\s*=\s*["\']([^"\']*)["\']', html)
    out: list[str] = []
    for value in parser.values:
        for token in value.split():
            if token.startswith("tpl-") and len(token) > 4:
                out.append(token[4:])
    return out

# Every template ships its block CSS unconditionally, so a PROSE-ONLY roadmap page carries
# ~148 `blk-` strings as `.blk-` selectors inside <style>. Counting the raw document would
# have made this a gate that can never fail. Same error as #90/#119 (the h2 chip reading
# typed-block content) and #123 (raw source vs the value a browser resolves).
_NOT_MARKUP = re.compile(r"<(style|script)\b[^>]*>.*?</\1>", re.S | re.I)

# A CLASS TOKEN, not a substring. A document that merely mentions `blk-callout` — in its
# title, in prose, in a CSS sample — is still component-free, and the first version of this
# check passed all three (measured). The renderer escapes `"` inside code, so a documented
# `class="blk-x"` in a fenced sample cannot reach this either.
_BLOCK_MARKUP = re.compile(r'class="[^"]*\bblk-')

# Resolved from this file, so it is right from any cwd and in any bound project. A relative
# path here would be the same defect as the one this check exists to report: a pointer that
# names something the reader cannot open.
_VOCAB_DOC = Path(__file__).resolve().parent.parent.parent / "docs" / "design-language.md"


def check_blocks(html: str) -> list[str]:
    """A page wearing a template's CSS while carrying none of that template's components.

    This is what `rawgentic-plan-756` shipped as: `class="tpl-roadmap"`, zero components,
    and every gate green — twelve hours after the composition meter it should have used
    was merged. The renderer had the devices; the document never asked for them.

    A floor, not a proof: one component of any kind satisfies it. Asking for the style's
    own first-read device is #130.
    """
    styled = template_styles(html)
    if not styled:
        return []
    if _BLOCK_MARKUP.search(_NOT_MARKUP.sub("", html)):
        return []
    return [f"the page is styled `{styled[0]}` but carries no typed blocks at all, "
            f"so it publishes as prose wearing that template's CSS. Each style's component "
            f"set, and the grammar for every block, is in {_VOCAB_DOC}. If this document "
            f"really is all prose, pass --skip-component-checks."]


# --- #130: a styled page missing the devices its own style OPENS with -----------------
#
# `check_blocks` above is a floor — one component of any kind clears it. This is the strict
# check the note there names: a `roadmap` can satisfy the floor with a single `chips` block
# and still open with none of a roadmap's own furniture.
#
# Same architecture, for the same reason: DELIBERATELY NOT IN `CHECKS`, because this is a
# PUBLISH policy rather than a rendering defect, and `lint()` is asserted `== []` at twelve
# sites on prose-only fixtures. `publish_doc.gate()` calls it beside `check_blocks`, under
# the same escape hatch, `--skip-component-checks` (`--allow-prose` is its alias).

_BLOCKS = None


def _blocks():
    """`blocks`, however this module was loaded.

    Two loaders, deliberately. The engine and its tests import this file as `render.lint`,
    where the package-relative import yields the SAME module object the rest of the engine
    uses. `publish_doc.py` instead loads it from an exact path and never consults
    `sys.path` — a documented guard, so that a foreign package named `render` earlier on
    the path cannot be selected and executed. There is then no package to be relative to,
    hence the fallback, which resolves its sibling from `__file__` exactly as `_VOCAB_DOC`
    above resolves the vocabulary doc, and likewise never consults `sys.path`.
    """
    global _BLOCKS
    if _BLOCKS is None:
        try:
            from . import blocks as _b               # imported as `render.lint`
        except ImportError:                          # loaded from an exact path
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "_lint_blocks", Path(__file__).resolve().parent / "blocks.py")
            _b = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(_b)
        _BLOCKS = _b
    return _BLOCKS


# Every `class` attribute value, whole. The tags are then read by TOKENISING it, because no
# amount of regex boundary-tuning gets this right and two rounds of review proved it:
#
# 1. A block's inner elements are classed `blk-chip` inside `blk-chips`, `blk-step` inside
#    `blk-steps`. Probing the thirteen committed pages with a loose `blk-([a-z]+)` returned
#    `chip, step, finding, item, row, fill, lbl, for, against, n, tl, when …` — every one an
#    inner element. Intersecting with `BLOCK_TAGS` drops those, since none is a tag.
# 2. `\b` treats `-` as a boundary, so `blk-steps-inner` captured `steps` — a REAL tag, which
#    the intersection then waved through. Patched with `(?![a-z-])`.
# 3. That lookahead still admitted `blk-stats_`, `blk-callout2`, `blk-phasesX`: it excluded
#    only lowercase letters and hyphens, so any other trailing character spoofed a device.
#    An ever-growing lookahead is the wrong shape for "the token is exactly `blk-<tag>`".
#
# So: split the attribute on whitespace, as HTML defines class tokens, and require the WHOLE
# token to equal `blk-<tag>`. Exact by construction, and there is no fourth variant to find.
_CLASS_ATTR = re.compile(r'class="([^"]*)"')


def _block_tags_present(markup: str, known) -> set[str]:
    """Every block tag the markup genuinely CARRIES, by exact class token."""
    present: set[str] = set()
    for m in _CLASS_ATTR.finditer(markup):
        for token in m.group(1).split():
            if token.startswith("blk-") and token[4:] in known:
                present.add(token[4:])
    return present


def check_style_devices(html: str) -> list[str]:
    """A styled page that carries components, but not the ones its style opens with.

    Requires ALL of the style's documented devices (owner decision, 2026-08-05): the source
    column reads "stat strip + a READ THIS FIRST callout stack, then the phase rail", and
    that "+" is conjunctive. Under an at-least-one rule a roadmap carrying only a stat strip
    still opens missing the other two, which is the same gap in weaker form.

    What it proves is PRESENCE, never quality or position — a `review` page with `stats` and
    `findings` passes however badly its verdict headline reads. Cells also name prose and
    structural elements (`design`'s lede, `dashboard`'s TL;DR panel, `review`'s verdict
    headline); those carry no tag and are not checked, because the renderer builds them and
    an author cannot omit them.

    Returns `[]` for a page with no typed blocks AT ALL — that is `check_blocks`'s case and
    it says it better. Exactly one of the two ever fires.
    """
    blocks = _blocks()
    # The RAW list, matching `check_template_classification` exactly — two `<body>` elements
    # with the SAME class must defer to it rather than being deduplicated into one here.
    # Unknown and duplicated classes belong to that check, which runs UNCONDITIONALLY.
    # Returning `[]` for them is not a gap: it keeps each condition reported by exactly one
    # check, and keeps the structural ones outside the reach of --skip-component-checks.
    found = template_styles(html)
    if len(found) != 1 or found[0] not in blocks.FIRST_READ_DEVICES:
        return []
    style = found[0]

    markup = _NOT_MARKUP.sub("", html)
    # The hand-off to `check_blocks` uses ITS OWN predicate, deliberately, so the two can
    # never disagree about which check owns a page. An earlier version bailed on "no
    # recognised block TAGS", which is a strictly narrower condition — and the gap between
    # the two left a page examined by NEITHER: `check_blocks` is satisfied by any `blk-`
    # class at all, so a page carrying only a sub-element class (`blk-chip`, which lives
    # INSIDE `blk-chips`) cleared it, while this check saw no tags and returned early.
    # Found by probing this module's own hand-off; reachable by a hand-edited or
    # renderer-defective page, which is exactly what a gate must not wave through.
    if not _BLOCK_MARKUP.search(markup):
        return []
    present = _block_tags_present(markup, blocks.BLOCK_TAGS)

    if style in blocks.UNDOCUMENTED_FIRST_READ:
        return []
    if style not in blocks.FIRST_READ_DEVICES:
        # Fail CLOSED. The suite's completeness test classifies REGISTRY ENTRIES, this gate
        # reads the class in RENDERED HTML, and the suite does not run at publish time — so
        # a renderer defect or an altered page could otherwise be waved through by the very
        # check meant to catch it.
        return [f"unknown template class `tpl-{style}`: classify it in "
                f"FIRST_READ_DEVICES or UNDOCUMENTED_FIRST_READ before publishing."]

    missing = sorted(blocks.FIRST_READ_DEVICES[style] - present)
    if not missing:
        return []
    named = ", ".join(f"`{t}`" for t in missing)
    return [f"the page is styled `{style}` and carries components, but not the "
            f"{'one' if len(missing) == 1 else 'ones'} that style opens with: {named} "
            f"{'is' if len(missing) == 1 else 'are'} missing. That style's first-read "
            f"element, and the grammar for every block, is in {_VOCAB_DOC}. If this "
            f"document really is all prose, pass --skip-component-checks."]


def check_template_classification(html: str) -> list[str]:
    """The page's template class is unknown, or there is more than one of it.

    SEPARATE from `check_style_devices`, and called UNCONDITIONALLY by
    `publish_doc.gate()` — the one part of this policy the skip flag does not reach.
    Cross-model review found that gap and its reasoning is the whole justification for the
    split: the skip flag means "this document really is all prose", and neither of these
    conditions is a statement about prose. An unclassified template class and two `<body>`
    tags are structural corruption — a renderer defect or an edited page — which is
    precisely what the design says must fail closed. Leaving them inside the flag let the
    flag wave through the exact inputs the fail-closed rule exists to stop.

    A page with NO template class stays exempt: `plain` emits none, and neither does a page
    this engine never drew (six of fourteen published pages sampled on 2026-08-03, #128).
    """
    blocks = _blocks()
    # The RAW list, not a set. Deduplicating first was itself a fail-open hole (found by the
    # pre-PR review): two `<body class="tpl-roadmap">` elements collapsed to one entry and
    # passed as a single well-formed page, while a document with two bodies can spread its
    # required devices across them and satisfy the gate carrying neither properly.
    found = template_styles(html)
    if not found:
        return []
    if len(found) > 1:
        # `template_styles` inspects every `<body>` tag, so this means more than one carries a
        # template token, or one carries two —
        # whether or not the classes agree. A plain `.search()` would silently take whichever
        # came first and let document ORDER decide which style's devices are required.
        named = ", ".join(f"`tpl-{s}`" for s in sorted(set(found)))
        return [f"the page carries {len(found)} elements with a template class ({named}), so "
                f"which style's devices are required is undefined, and a second body can hold "
                f"components the first does not. Emit exactly one."]
    style = found[0]
    if style in blocks.FIRST_READ_DEVICES or style in blocks.UNDOCUMENTED_FIRST_READ:
        return []
    return [f"unknown template class `tpl-{style}`: classify it in FIRST_READ_DEVICES or "
            f"UNDOCUMENTED_FIRST_READ before publishing. The suite's completeness test "
            f"classifies registry entries, so it cannot catch a class that reaches a page "
            f"some other way."]
