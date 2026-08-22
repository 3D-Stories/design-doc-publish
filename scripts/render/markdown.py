"""The block/inline markdown parser (moved here by #16, wave 1).

Holds `_inline`, the rich inline pass `_inline_rich`, `_render_body_plain`,
`_render_roadmap` and the table helpers.

TWO CONTRACTS THIS MODULE MUST KEEP:

* **`plain` is byte-identical.** The seven constructs #16 fixes are gated: inline
  ones behind the `inline_fn` seam (`plain` keeps bare `_inline`), block ones
  behind `rich=False`. Adding a construct to the ungated path is a regression.
* **Escape-first.** Every transform runs on text `html.escape`d by its caller and
  may only wrap it in whitelisted tags. Nothing here may introduce an unescaped
  `<`. URLs additionally pass `_safe_url`, because an `<a href>`/`<img src>` is
  the one place a scheme like `javascript:` could reintroduce script.

`inline_fn` is resolved at CALL time, never as a def-time default argument — a
default binds at definition, so a replaced `_inline` would never reach a direct
caller and the parser fix would be silently inert.
"""
import html
import sys

from . import blocks
import html as _html

from .lint import _is_external, _url_value
import re

def _inline(escaped: str) -> str:
    """Apply inline emphasis to already-escaped text. Operates only on the
    escaped string, so it can never introduce an unescaped `<`."""
    # `code` first (so ** inside code is left alone)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


# --- #16 wave 1: the rich inline pass -------------------------------------------
#
# Gated behind the `inline_fn` seam: `plain` keeps bare `_inline`, so its bytes are
# unchanged. Everything here runs on ALREADY-ESCAPED text, so a `<` in the source is
# already `&lt;` and cannot be reopened. The one genuinely new risk an <a>/<img>
# introduces is the URL itself, which is why `_safe_url` exists.

# The URL Standard's scheme grammar: a letter, then letters/digits/`+`/`-`/`.`, then `:`.
# Matching the REAL grammar is what lets "everything else is relative" be a safe default —
# `foo:bar` is a scheme and is refused, while `dir/a:b.png` is not one, because the character
# class cannot cross a `/`.
#
# `re.ASCII` matters: the grammar is ASCII-only, but `re.I` alone case-folds Unicode, so `[a-z]`
# would also match U+212A KELVIN SIGN and U+017F LATIN SMALL LETTER LONG S (both measured). That
# direction only ever OVER-refuses — a relative path starting with such a character would be read
# as carrying an unblessed scheme and go literal — so it was a correctness bug, not a hole. Step 11.
_URL_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I | re.ASCII)

_ALLOWED_SCHEMES = frozenset({"http:", "https:", "mailto:"})

# No legitimate URL carries a raw C0 control, space, or angle bracket. Refusing the whole
# class outright removes the smuggling surface rather than enumerating the tricks: a control
# character's job here is to hide a `//host` prefix or split a scheme from a classifier while
# the URL parser discards it and fetches anyway (#23). Quotes are belt-and-braces — the input
# is already escaped, so a real one arrives as `&quot;`/`&#x27;` and passes.
_UNSAFE_CHARS = frozenset(chr(c) for c in range(0x21)) | frozenset("<>\"'\x7f")


def _classifies_safe(reading: str) -> bool:
    """True when this one reading of a url carries no scheme, or a blessed one.

    Refuses three scheme-less forms because a browser resolves each to a HOST: a
    protocol-relative `//host`, and the reverse-solidus `/\\host` and `\\/host` that #23 measured
    Chrome resolving to `http://host`. Percent-encoded slashes (`%2f%2fhost`) are deliberately
    NOT refused — a browser does not decode them before authority parsing, so they stay a
    same-origin path.
    """
    probe = _url_value(reading).replace("\\", "/")
    if not probe or probe.startswith("//"):
        return False
    scheme = _URL_SCHEME.match(probe)
    return scheme.group(0).lower() in _ALLOWED_SCHEMES if scheme else True


def _safe_url(escaped_url: str) -> str | None:
    """Return the URL if it is safe to put in an href/src, else None.

    The accepted set, exactly:

    * an ABSOLUTE url in one of three schemes — `http:`, `https:`, `mailto:`;
    * any RELATIVE reference, meaning one that carries no scheme at all: `assets/diagram.png`,
      `sub/dir/x.png`, `./here.png`, `../up.png`, `/rooted.png`, `?v=2`, `#section`.

    Everything else is refused and the construct renders as literal text. That is still an
    allowlist, not a denylist — the question just moved from "does it start with a blessed
    prefix" to "does it have a scheme, and is that scheme blessed". A url with no scheme cannot
    name another origin, which is what makes the default safe.

    Three things are refused despite having no scheme, because a browser resolves each to a
    host: a protocol-relative `//host`, and the reverse-solidus forms `/\\host` and `\\/host`
    that #23 measured Chrome resolving to `http://host`. Classification happens on the URL
    Standard's normalised value — leading/trailing C0 controls stripped, TAB/LF/CR removed —
    so `\\x01//host` cannot present itself as a relative path. `_is_external` alone does NOT
    catch that form, so this function cannot delegate the question to it.

    BOTH the escaped text and its HTML-DECODED reading are classified, and either one looking
    dangerous refuses the url. The browser decodes an attribute value before parsing the url, so
    the string judged here is not the string that resolves: `javascript&colon;alert(1)` carries
    no scheme as written and becomes `javascript:` once decoded. That is defence in depth rather
    than a reachable exploit — both call sites hand this function ALREADY-ESCAPED text, where an
    author's `&` is `&amp;`, so the decoded reading still holds a literal `&colon;` and stays
    inert (measured). The old prefix allowlist refused these shapes by accident; a guard should
    not depend on a caller invariant it cannot check, so the property is now explicit.

    Scheme safety is NOT the whole rule for every attribute, and this function is not
    the place to add the rest. An `<a href>` may point at another host — a citation is
    not a request — while an `<img src>` may not, because it fetches. That second rule
    lives at the `_img` call site, using the pre-publish gate's own `_is_external` so
    there is one definition of "external" (#23).

    Nor is admitting a url the same as the url WORKING once published. An accepted relative
    image only resolves on a live page because `publish_doc.stage_assets` copies the referenced
    file into the deploy directory, resolved against the markdown source's own directory (#121).
    That publisher REFUSES — so nothing ships — when the file is missing, is a symlink, escapes
    the document's directory, or is root-relative. `SKILL.md` states the author-facing rule. Say
    "accepted here" rather than "works": before #121 this function accepted `./diagram.png` and
    the published page 404d, and the claim that relative images keep working was the unsupported
    one a design review caught.
    """
    u = escaped_url.strip()
    if not u or any(c in _UNSAFE_CHARS for c in u):
        return None
    # Classify on a normalised COPY; nothing here rewrites the url that gets emitted. Both
    # readings must pass, because the browser HTML-decodes the attribute value BEFORE parsing
    # the url — so the string this function judges is not the one that resolves.
    if any(not _classifies_safe(reading) for reading in (u, _html.unescape(u))):
        return None
    return u


def _inline_rich(escaped: str) -> str:
    """`_inline` plus links, images, and italics — #16's inline constructs.

    Order matters: images before links (an image is a link with a leading `!`),
    links before emphasis (so `*` inside a URL is not eaten), and both after code,
    because a code span is a literal quote and must pass through untouched.
    """
    # code + bold first, exactly as plain does
    escaped = _inline(escaped)

    def _img(m):
        alt, url = m.group(1), _safe_url(m.group(2))
        # An `<img src>` FETCHES; an `<a href>` does not, which is why lint.py leaves
        # `<a href>` out of its fetching attributes on purpose. So a scheme-safe URL is
        # still refused here when fetching it would leave the page's own origin — the
        # pre-publish lint gate would refuse to publish such a page anyway, and this uses
        # that gate's own predicate so there is one definition. Note it is stricter than
        # an off-host test and does not compare hosts: an ABSOLUTE url is refused even if
        # it names the host the page will be served from, because a renderer cannot know
        # that origin. Two INDEPENDENT rejections, not one: `_safe_url` allowlists the
        # scheme (it returns `https://h/i.png` happily), and `_is_external` separately
        # rejects a fetching url. Both take the same action — return the original markup —
        # so the construct is left as written, visible and inert; ordinary inline formatting
        # may still apply inside it (`![*x*](https://h/i.png)` keeps its `<em>`) (#23).
        if url is None or _is_external(url):
            return m.group(0)
        return f'<img src="{url}" alt="{alt}">'

    def _link(m):
        text, url = m.group(1), _safe_url(m.group(2))
        if url is None:
            return m.group(0)
        return f'<a href="{url}">{text}</a>'

    # Emphasis may only touch TEXT, never generated markup. Skipping just <code>
    # was not enough: an href built one line above is markup too, so
    # `[x](https://e/*p*)` produced `<a href="https://e/<em>p</em>">` — a tag inside
    # an attribute, which breaks the escape-first structural guarantee. And a
    # <strong> span must be skipped or `_a **b_ c**` misnests into
    # `<em>a <strong>b</em> c</strong>`. So split on EVERY region this renderer can
    # have emitted and transform only what falls between them.
    _GENERATED = re.compile(
        r"(<code>.*?</code>|<strong>.*?</strong>|<a\b[^>]*>.*?</a>|<img\b[^>]*>)", re.S)

    def _outside_code(fragment, fn):
        return "".join(
            part if k % 2 else fn(part)
            for k, part in enumerate(_GENERATED.split(fragment))
        )

    def _emphasis(seg):
        # single * or _ only: ** was already consumed as bold, and a match may not
        # span a newline. The closing delimiter may not sit inside a word either,
        # or `_foo_bar` would eat an intraword underscore.
        seg = re.sub(r"(?<![*\w])\*(?!\*)([^*\n]+?)\*(?![*\w])", r"<em>\1</em>", seg)
        return re.sub(r"(?<![_\w])_(?!_)([^_\n]+?)_(?![_\w])", r"<em>\1</em>", seg)

    def _transform(seg):
        seg = re.sub(r"!\[([^\]\[]*)\]\(([^)\s]+)\)", _img, seg)
        # `(?<!!)`: an image is not a link. Without it a REFUSED image falls through to this
        # pass and comes back as `!<a href="…">alt</a>`, so a refused off-host image would
        # still have appeared as a clickable link with a stray `!`. Unreachable before #23,
        # because the only refusals were bad schemes and `_link` refuses those too.
        seg = re.sub(r"(?<!!)\[([^\]\[]+)\]\(([^)\s]+)\)", _link, seg)
        # Re-split BEFORE emphasis: the <a>/<img> above were generated inside THIS
        # call, so the outer split could not have protected them. Without this an
        # asterisk in a URL becomes a tag inside an href.
        return _outside_code(seg, _emphasis)

    return _outside_code(escaped, _transform)


# --- table detection helpers (escape-first callers still html.escape each cell) ---

_TABLE_SEP_CELL = re.compile(r"^:?-+:?$")


def _is_table_separator(line: str) -> bool:
    """A GFM separator row: pipe-delimited cells each matching ``:?-+:?`` (dashes
    with optional leading/trailing alignment colon), e.g. ``| --- | :-: |``."""
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2):
        return False
    cells = stripped.strip("|").split("|")
    return bool(cells) and all(_TABLE_SEP_CELL.match(c.strip()) for c in cells)


def _split_table_row(line: str) -> list[str]:
    """Split a ``| a | b |`` row into stripped cells, dropping the empty cells
    the leading/trailing pipes produce."""
    return [c.strip() for c in line.strip().strip("|").split("|")]


# The feature id keying this component's optional CSS/JS layers in `blocks.py`.
_CODE_FEATURE = "codecopy"


def _code_listing(info: str, code: str, *, rich: bool, ctx=None) -> str:
    """Render a fence that named no block type — the ordinary code listing.

    `plain` keeps the bare `<pre><code>` it has always emitted. That is not timidity: the
    style is documented as "an unstyled document with no template CSS", it is pinned
    byte-for-byte by three separate gates, and no `--type` ever implies it. A styled,
    scripted control is the one thing it is defined not to have.

    The rich form wraps that SAME listing — byte-for-byte, `<pre><code>` included, so every
    existing test that greps for it still finds it — in a box carrying the fence's info
    string and a copy button.

    The button ships `hidden` and the optional script reveals it. A page read with
    JavaScript disabled therefore shows no control that cannot work, and the listing stays
    selectable either way. `info` is author text, so it is escaped like everything else.
    """
    listing = "<pre><code>" + html.escape(code) + "</code></pre>"
    if not rich:
        return listing
    blocks.note_feature(ctx, _CODE_FEATURE)
    lang = html.escape(info.strip()) if info.strip() else "code"
    return ('<div class="doc-code">'
            f'<div class="doc-code-bar"><span class="doc-code-lang">{lang}</span>'
            '<button class="doc-code-copy" type="button" hidden>Copy</button></div>'
            f"{listing}</div>")


def _render_body_plain(markdown: str, inline_fn=None, rich: bool = False,
                       doc_type: str | None = None, markers=None, decorate=None,
                       variants=None, ctx=None) -> str:
    """Escape-first block renderer. Every line is escaped before classification;
    transforms only wrap escaped text in whitelisted tags. ``inline_fn`` is the
    inline pass applied to already-escaped text — defaults to bare ``_inline``;
    template renderers pass a decorator-wrapped variant (#344). It is never applied
    to fenced-code content (code stays verbatim, only html-escaped)."""
    inline_fn = inline_fn if inline_fn is not None else _inline
    # Normalize CR line endings so callers passing raw-CRLF strings get the same
    # hard-break detection as the CLI's universal-newline file read (#344 8a review).
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    i = 0
    in_list = False
    para: list[str] = []  # buffered consecutive plain source lines

    # rich mode tracks a STACK so a nested bullet can nest; plain keeps the flat
    # boolean it always had, so its output cannot change.
    # (tag, indent, nested_inside_parent_li)
    list_stack: list[tuple[str, int, bool]] = []

    def close_list():
        nonlocal in_list
        if rich:
            while list_stack:
                closed, _ind, nested = list_stack.pop()
                out.append(f"</{closed}>" + ("</li>" if nested else ""))
            return
        if in_list:
            out.append("</ul>")
            in_list = False

    def flush_para():
        """Emit the buffered plain lines as one <p>. Single-line buffers stay
        byte-identical to the pre-#344 renderer (escape the raw line, inline once).
        Multi-line buffers join with soft-wrap spaces, honouring two-space hard
        breaks (standard markdown): the placeholder \\x00 marks a hard break in the
        joined string, survives the single inline pass, then becomes <br>. Source
        \\x00 is stripped first so a literal null in the input can't forge a break."""
        if not para:
            return
        buf = para[:]
        para.clear()
        if len(buf) == 1:
            out.append(f"<p>{inline_fn(html.escape(buf[0]))}</p>")
            return
        src = [ln.replace("\x00", "") for ln in buf]  # (a) collision guard
        n = len(src)
        parts: list[str] = []
        for idx, ln in enumerate(src):
            hard = bool(re.search(r" {2,}$", ln))  # (b) 2+ trailing spaces
            if hard:
                ln = ln.rstrip(" ")
            parts.append(html.escape(ln))          # (c) escape each line
            if idx < n - 1:                         # separator; last-line break dropped
                parts.append("\x00" if hard else " ")
        joined = inline_fn("".join(parts))          # (d) inline ONCE over the whole
        joined = joined.replace("\x00", "<br>")     # (e) placeholder -> <br>
        out.append(f"<p>{joined}</p>")              # (f)

    while i < len(lines):
        raw = lines[i]

        # fenced code block — capture verbatim, escape the whole thing, no inline
        if raw.strip().startswith("```"):
            flush_para()
            close_list()
            info = raw.strip()[3:].strip()      # the fence's info string (#17)
            i += 1
            code: list[str] = []
            closed = False
            while i < len(lines):
                if lines[i].strip().startswith("```"):
                    closed = True
                    i += 1
                    break
                code.append(lines[i])
                i += 1
            if closed:
                # #17: a fence whose info string names a BLOCK TYPE renders a
                # component. Rich styles only — in `plain`, and in every other
                # markdown viewer, the fence stays a code listing, which is the
                # graceful-degradation story the grammar is built on.
                rendered = None
                if rich:
                    rendered = blocks.render_fence(info, "\n".join(code),
                                                   doc_type=doc_type, markers=markers,
                                                   decorate=decorate,
                                                   variants=variants, ctx=ctx)
                if rendered is not None:
                    out.append(rendered)
                else:
                    out.append(_code_listing(info, "\n".join(code), rich=rich, ctx=ctx))
            else:
                # Unclosed fence: do NOT swallow the rest of the doc into one code
                # block (that silently drops every heading/section after it — a real
                # hazard for spec docs, which routinely contain fences). Render the
                # captured lines as normal blocks and warn.
                print("render_artifact: WARNING unclosed ``` fence — rendering the "
                      "remainder as normal text, not code", file=sys.stderr)
                out.append(_render_body_plain("\n".join(code), inline_fn=inline_fn,
                                              rich=rich, doc_type=doc_type, markers=markers,
                                              decorate=decorate,
                                              variants=variants, ctx=ctx))
            continue

        stripped = raw.strip()
        if not stripped:
            flush_para()
            close_list()
            i += 1
            continue

        m = re.match(r"(#{1,6})\s+(.*)", raw)
        if m:
            flush_para()
            close_list()
            level = len(m.group(1))
            out.append(f"<h{level}>{inline_fn(html.escape(m.group(2)))}</h{level}>")
            i += 1
            continue

        # #16: a horizontal rule. Rich only — plain kept it as body text.
        if rich and re.fullmatch(r"(?:-{3,}|\*{3,}|_{3,})", stripped):
            flush_para()
            close_list()
            out.append("<hr>")
            i += 1
            continue

        _m_ul = re.match(r"[-*]\s+", stripped)
        # #16: ordered lists. Rich only — plain let them fall into the paragraph
        # accumulator, which is exactly the reported corruption.
        _m_ol = re.match(r"\d+[.)]\s+", stripped) if rich else None
        if _m_ul or _m_ol:
            flush_para()
            if rich:
                tag = "ol" if _m_ol else "ul"
                indent = len(raw) - len(raw.lstrip())
                while list_stack and (list_stack[-1][1] > indent
                                      or (list_stack[-1][1] == indent
                                          and list_stack[-1][0] != tag)):
                    # a nested list closes INSIDE its parent <li>, so close that too
                    closed, _ind, nested = list_stack.pop()
                    out.append(f"</{closed}>" + ("</li>" if nested else ""))
                if not list_stack or list_stack[-1][1] < indent:
                    # A nested list belongs INSIDE the parent <li>, not beside it.
                    # The parent item was emitted self-closed, so reopen it by
                    # dropping that </li> before descending.
                    nested = bool(list_stack) and out and out[-1].endswith("</li>")
                    if nested:
                        out[-1] = out[-1][: -len("</li>")]
                    start = ""
                    if tag == "ol":
                        n = int(re.match(r"(\d+)", stripped).group(1))
                        if n != 1:
                            start = f' start="{n}"'
                    out.append(f"<{tag}{start}>")
                    list_stack.append((tag, indent, nested))
                item = re.sub(r"^(?:[-*]|\d+[.)])\s+", "", stripped)
                out.append(f"<li>{inline_fn(html.escape(item))}</li>")
                i += 1
                continue
            if not in_list:
                out.append("<ul>")
                in_list = True
            item = re.sub(r"^[-*]\s+", "", stripped)
            out.append(f"<li>{inline_fn(html.escape(item))}</li>")
            i += 1
            continue

        # A hard-wrapped list item's continuation line (standard markdown: indented
        # to the item's content column). Rich only — plain is frozen byte-for-byte
        # and keeps its old paragraph-beside-the-list behavior. Joins ONLY onto a
        # simple self-closed item: after a nested list closes, out[-1] is
        # "</ul></li>", which also ends with </li> and must never absorb prose.
        # Measured live 2026-08-22: every wrapped bullet on the unified-roadmap page
        # split mid-sentence at the left margin. Guarded by test_list_continuation.py.
        if (rich and list_stack and out
                and out[-1].startswith("<li>") and out[-1].endswith("</li>")
                and stripped
                and (len(raw) - len(raw.lstrip())) >= 2
                and not stripped.startswith((">", "|", "#"))):
            out[-1] = (out[-1][: -len("</li>")] + " "
                       + inline_fn(html.escape(stripped)) + "</li>")
            i += 1
            continue

        if stripped.startswith(">"):
            flush_para()
            close_list()
            quote = re.sub(r"^>\s?", "", stripped)
            out.append(f"<blockquote>{inline_fn(html.escape(quote))}</blockquote>")
            i += 1
            continue

        # table: a "| ... |" header row immediately followed by a "| --- | :-: |"
        # separator row. A pipe row with no separator next is NOT a table (falls
        # through to the paragraph branch below, unchanged).
        if (stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2
                and i + 1 < len(lines) and _is_table_separator(lines[i + 1])):
            flush_para()
            close_list()
            header_cells = _split_table_row(lines[i])
            out.append("<table>")
            out.append("<thead><tr>" + "".join(
                f"<th>{inline_fn(html.escape(c))}</th>" for c in header_cells) + "</tr></thead>")
            i += 2  # skip header + separator
            body_rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                body_rows.append(_split_table_row(lines[i]))
                i += 1
            if body_rows:
                out.append("<tbody>")
                for cells in body_rows:
                    out.append("<tr>" + "".join(
                        f"<td>{inline_fn(html.escape(c))}</td>" for c in cells) + "</tr>")
                out.append("</tbody>")
            out.append("</table>")
            continue

        # plain line: no block pattern matched — buffer it; flushed on the next
        # blank/block boundary or EOF into ONE <p> (soft-wrap join + hard breaks).
        close_list()
        para.append(raw)
        i += 1

    flush_para()
    close_list()
    return "\n".join(out)


# --- #199: opt-in "roadmap" style — bubble cards + completion chips ---

# The ctx key `render_artifact(section_chips=False)` seeds to suppress every section
# chip on the page. Defined HERE and imported upward by `render/__init__.py` — the
# dependency arrow between these modules already points this way (never downward).
CTX_SECTION_CHIPS_OFF = "_section_chips_off"

# Completion status → chip class, in PRECEDENCE order. The chip LABEL is always the
# matched keyword from THIS fixed vocabulary (never raw section text), so it is
# escape-safe by construction — an injection in the status position can never reach
# the label. Word-boundary matched so "incomplete" does not match "complete".
_STATUS_VOCAB: tuple[tuple[tuple[str, ...], str], ...] = (
    (("done", "shipped", "merged", "complete"), "c-conf"),
    (("abandoned", "blocked", "dropped", "halted", "reverted"), "c-defer"),
    (("planned", "next", "not started", "in progress", "pending", "todo"), "c-plan"),
)


# #21 (absorbing #55): a keyword preceded by one of these is NOT a claim that it holds.
# "not done" used to render a green DONE and "not measured" a MEASURED — the chip asserting the
# opposite of the sentence beside it.
_NEGATORS = frozenset((
    "not", "no", "never", "cannot", "isnt", "isn't", "arent", "aren't", "wasnt", "wasn't",
    "werent", "weren't", "hasnt", "hasn't", "havent", "haven't", "hadnt", "hadn't",
    "wont", "won't", "cant", "can't", "dont", "don't", "doesnt", "doesn't",
    # #119: the quantifier forms. `no` was already here, which is why the first framing of that
    # issue ("leading quantifiers are unhandled") was wrong — `Nothing shipped` failed because
    # `nothing` was absent from this set entirely, not because of where it sat.
    "nothing", "none", "neither",
))

# #119 widened this from two words to six. Two is what let "No work is done." publish a green
# DONE, with the negator three words away.
#
# Six is measured, not guessed. Cross-model review supplied the cases that bound it from both
# sides, and 23 sentences were then scored at every value from 3 to 7: six passes 22, five passes
# 20, seven passes 20. Seven starts neutralising real statements across a conjunction ("This is
# not a risk AND the work is done" -> neutral); five stops reaching "It is not true that the work
# is done", which then publishes DONE, asserting exactly what the sentence denies.
#
# A named clause-BOUNDARY set was tried in place of a window and REJECTED. It reads as more
# principled and is strictly worse, because every named boundary is a place a negation leaks
# through: with `nor` a boundary, "The work is neither done nor shipped." published SHIPPED (the
# scan skipped the negated `done` and found `shipped` past the `nor`), and with `that` a boundary,
# "It is not true that this was measured." published MEASURED. Both assert the opposite of their
# own sentence, which is the defect class this issue exists to remove. Cross-model review found
# both; neither was in the issue.
#
# THE ONE ACCEPTED ERROR, recorded because it cannot be designed away at this level: "There is no
# doubt the work is done." reads neutral. Its negator sits the same distance from the keyword as
# the one in "It is not true that the work is done." — opposite correct answers, identical
# distance — so NO window satisfies both, and nothing short of modelling negator SCOPE will.
# Forced to choose, prefer the neutral chip: under-claiming loses information, the other direction
# publishes a status nobody wrote. Pinned by name in the suite so it stays visible.
_NEGATOR_REACH = 6


def _negated(low: str, start: int) -> bool:
    """Whether the keyword beginning at `start` sits under a negator.

    Looks only LEFT, and never past the start of its own clause. Both limits earn their keep:

    * left-only is what makes `not started` safe — there the negator IS the keyword's own first
      word, so nothing precedes the match and it survives as the vocabulary entry it is;
    * stopping at a clause boundary is what makes "not done, in progress" land on IN PROGRESS.
      Without it the `not` from the first clause reached across the comma and neutralised the
      second, so the sentence that said most plainly what the state IS produced a blank chip.

    The window is a heuristic and `_NEGATOR_REACH` documents it as one, including the single
    sentence shape it gets wrong and why a cleverer-looking lexical rule was rejected for being
    worse.
    """
    clause = re.split(r"[,;:.()—–]", low[:start])[-1]
    return any(w in _NEGATORS for w in clause.split()[-_NEGATOR_REACH:])


def _scan(low: str, vocab) -> tuple[str, str] | None:
    """First un-negated keyword, by category precedence. Shared so the two chips cannot drift."""
    for words, cls in vocab:
        for w in words:
            for m in re.finditer(rf"\b{re.escape(w)}\b", low):
                if not _negated(low, m.start()):
                    return (cls, w.upper())
    return None


def status_chip(text: str) -> tuple[str, str]:
    """Return (css_class, label) for a section's completion status. Scans by
    category precedence (done > attention > planned), word-boundary matched.
    Fail-safe neutral ``("c-plan", "—")`` when no keyword is found. The label is
    drawn from the fixed vocab above, never the raw input — see the note there.

    #21: a negated keyword is SKIPPED and the scan continues rather than returning neutral on
    the spot, so "not done, in progress" lands on IN PROGRESS — what the sentence actually says.
    Neutral is reached only when nothing survives, which is the honest chip for a bare "not
    done": that text says what the state is not, never what it is.
    """
    return _scan(text.lower(), _STATUS_VOCAB) or ("c-plan", "—")


def _render_roadmap(markdown: str, inline_fn=None, rich: bool = False,
                    doc_type: str | None = None, markers=None, decorate=None,
                    variants=None, ctx=None, section_class: str = "mstone") -> str:
    """Render each ``## `` (h2) section as a dashboard-style ``.mstone`` bubble card
    titled with a completion chip. Preamble before the first h2 renders plain.

    #13: the body of this moved into `render_sections`, which six other templates now
    share. This stays as the roadmap/dashboard entry point and as the back-compat name —
    `render/__init__.py` re-exports it and the existing tests call through it. Roadmap
    and dashboard pass DIFFERENT `section_class` values: they share this callable, so a
    single hardcoded class would leak roadmap's own marker into dashboard.
    """
    return render_sections(
        markdown, inline_fn=inline_fn, rich=rich, doc_type=doc_type, markers=markers,
        decorate=decorate, variants=variants, ctx=ctx,
        section_class=section_class, chip_resolver=roadmap_status_chip,
        heading_tag="h3")


# --- #13 wave 3: the shared section renderer ---------------------------------------
#
# `_render_roadmap` above was already "split on h2 outside fences, wrap each section,
# chip it". Six of the eight #13 templates want the same shape with different classes,
# so the logic moves here ONCE and each template passes a config. `_render_roadmap`
# becomes a call into it, which is why roadmap and dashboard keep the exact markup
# their tests pin.

def roadmap_status_chip(heading: str, body: str) -> tuple[str, str]:
    """The roadmap/dashboard completion chip: `status_chip` applied with precedence.

    `status_chip` itself takes ONE argument; the heading-versus-body precedence has
    always lived in the caller. Moving it here verbatim keeps the rule in one place
    rather than re-expressing it as data:

    A DEFINITIVE heading status (done/abandoned) wins — that's where the author states
    it. A neutral/weak heading (c-plan, e.g. an incidental "next" in "Next.js") does NOT
    suppress a definitive body status, so an actually-shipped section still reads DONE.
    Fall through to the heading's own neutral label only when the body is neutral too.
    """
    h_cls, h_label = status_chip(heading)
    if h_cls in ("c-conf", "c-defer"):
        return h_cls, h_label
    b_cls, b_label = status_chip(body)
    return (b_cls, b_label) if b_cls in ("c-conf", "c-defer") else (h_cls, h_label)


# Confidence vocabulary for `analysis` (specs §4d: "measured, confirmed, or inferred").
# Same fixed-vocab, escape-safe-by-construction shape as `_STATUS_VOCAB`: the LABEL is
# always the matched keyword from this tuple, never raw section text.
_CONFIDENCE_VOCAB: tuple[tuple[tuple[str, ...], str], ...] = (
    (("measured",), "c-measured"),
    (("confirmed", "verified"), "c-confirmed"),
    (("inferred", "assumed", "unverified"), "c-inferred"),
)


def confidence_chip(heading: str, body: str) -> tuple[str, str]:
    """`analysis`'s per-answer confidence chip. Heading first, then body; neutral when
    neither names a confidence level, because a missing claim is not an inferred one.

    #21: same negation rule as `status_chip`, through the same scanner — "not measured" was
    rendering a MEASURED chip. One defect in two functions, which is why #55 folded into #21.
    """
    for text in (heading, body):
        hit = _scan(text.lower(), _CONFIDENCE_VOCAB)
        if hit:
            return hit
    return ("c-unstated", "—")


def _split_leading_blocks(lines: list[str]) -> tuple[list[str], list[str]]:
    """Peel typed/fenced blocks off the FRONT of a preamble, returning (blocks, rest).

    Dashboard's sticky state bar and its TL;DR panel are two consecutive first-read
    elements (specs §4d), so wrapping the whole preamble would bury the state bar inside
    `.db-tldr`. Peeling on the SOURCE — never by reordering author content, and never by
    parsing our own HTML back — keeps both at the top in the order they were written.
    """
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        if not lines[i].strip().startswith("```"):
            break
        i += 1
        while i < len(lines) and not lines[i].strip().startswith("```"):
            i += 1
        i += 1  # the closing fence
    return lines[:i], lines[i:]


def _prose_only(lines: list[str]) -> list[str]:
    """The section's own prose, with fenced blocks removed — the only text a chip may read.

    #90: chips were resolved against the section's RAW source, so any section merely
    CONTAINING a completion word published a status nobody wrote — `## Risks` chipped DONE
    off a findings row, `## Phases` chipped COMPLETE off a phase band's state badge. A typed
    block's cells are data the author wrote ABOUT the work; only the prose is a claim about
    the section.

    Fences are matched on the STRIPPED line, exactly as the h2 boundary scan above does — the
    two must agree, or a fence that opens for one closes for the other.

    An UNCLOSED fence keeps its content, because `_render_body_plain` renders that remainder
    as normal text rather than swallowing the document. The scanner reads what the reader
    sees; that is the whole point of the fix, so it must hold at the ragged edge too.
    """
    out: list[str] = []
    fence_start: int | None = None
    for ln in lines:
        if ln.strip().startswith("```"):
            if fence_start is None:
                fence_start = len(out)      # opening: remember where to cut back to
            else:
                del out[fence_start:]       # closing: the block's content was never prose
                fence_start = None
            continue
        out.append(ln)
    return out                              # an unclosed fence leaves its lines in place


def render_sections(markdown: str, inline_fn=None, rich: bool = False,
                    doc_type: str | None = None, markers=None, decorate=None,
                    variants=None, ctx=None, *,
                    section_class: str | None = None, chip_resolver=None,
                    chip_class: str | None = None, lead_class: str | None = None,
                    preamble_class: str | None = None,
                    index_class: str | None = None,
                    heading_tag: str = "h3") -> str:
    """Render `markdown` as an h2-sectioned document. Every parameter is optional; with
    none of them set this is `_render_body_plain` with extra steps, which is the point —
    a template opts into exactly the structure it needs.

    Escape-first throughout: headings are escaped exactly as the plain renderer does,
    bodies go through the plain renderer, and a chip label is fixed vocab, never author
    text passed through `inline_fn`.
    """
    inline_fn = inline_fn if inline_fn is not None else _inline
    lines = markdown.split("\n")
    h2 = re.compile(r"##(?!#)\s+(.*)")

    # Section boundaries = h2 lines OUTSIDE fenced code blocks. A "## " inside a fence
    # (a Makefile `## help` target, a doc quoting slot markdown) is content, not a card.
    boundaries: list[int] = []
    in_fence = False
    for idx, ln in enumerate(lines):
        if ln.strip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence and h2.match(ln):
            boundaries.append(idx)

    def body_of(src: list[str]) -> str:
        return _render_body_plain("\n".join(src), inline_fn=inline_fn, rich=rich,
                                  doc_type=doc_type, markers=markers, decorate=decorate,
                                  variants=variants, ctx=ctx)

    # Sectioning is OPT-IN. Without it this must leave the document structure alone —
    # `design` wants only the preamble treatment, and wrapping its h2s in sections (which
    # demotes each heading to the `heading_tag` default of h3) silently changed document
    # semantics and killed the `.tpl-design h2` accent rule. Caught by LOOKING at a
    # rendered page, which is why reading the diff would not have found it.
    #
    # #41: `workflow` used to be named here alongside `design` and is no longer. It now
    # opts IN — but passes `heading_tag: "h2"` so its stage headings keep their level.
    # The demotion is the hazard, not the wrapper; a template can take one without the
    # other, and a runbook stage wants the section AND the h2.
    sectioned = any((section_class, chip_resolver, lead_class, index_class))

    out: list[str] = []
    first = boundaries[0] if boundaries else len(lines)
    pre = lines[:first]
    if any(l.strip() for l in pre):
        lead_blocks, prose = _split_leading_blocks(pre)
        if any(l.strip() for l in lead_blocks):
            out.append(body_of(lead_blocks))
        if any(l.strip() for l in prose):
            rendered = body_of(prose)
            if preamble_class:
                rendered = f'<div class="{preamble_class}">{rendered}</div>'
            out.append(rendered)

    if not sectioned:
        # The preamble is already emitted; everything from the first h2 on renders as an
        # ordinary body, every heading at the level its author wrote.
        rest = lines[first:]
        if any(l.strip() for l in rest):
            out.append(body_of(rest))
        return "\n".join(out)

    headings = [h2.match(lines[b]).group(1) for b in boundaries]
    if index_class and headings:
        items = "".join(
            # NOT inline_fn: a heading containing a link would nest <a> inside <a>,
            # which is invalid and breaks the entry. The index is navigation, not prose.
            f'<li><a href="#s{n}">{html.escape(h)}</a></li>'
            for n, h in enumerate(headings, 1))
        out.append(f'<nav class="{index_class}"><ol>{items}</ol></nav>')

    for bi, start in enumerate(boundaries):
        end = boundaries[bi + 1] if bi + 1 < len(boundaries) else len(lines)
        heading = headings[bi]
        sec = lines[start + 1:end]
        body_html = body_of(sec)
        if lead_class and body_html.startswith("<p>"):
            # Only when the section OPENS with a paragraph. A section opening with a
            # block would otherwise have the lead class land on a <p> nested inside a
            # callout — marking evidence as the answer.
            body_html = f'<p class="{lead_class}">' + body_html[len("<p>"):]
        chip_html = ""
        if chip_resolver and not (ctx or {}).get(CTX_SECTION_CHIPS_OFF):
            # The opt-out exists for NARRATIVE pages whose prose discusses completion
            # vocabulary as subject matter ("who may declare done" rendered [DONE] on a
            # real page, 2026-08-10). It suppresses the chip wholesale — page-level, via
            # `render_artifact(section_chips=False)` — rather than adding heading grammar,
            # which was considered and rejected once already (see roadmap.py's history).
            # #90: PROSE only. Applied here rather than inside `roadmap_status_chip` so the
            # sibling resolver `analysis` passes (`confidence_chip`) is fixed by the same
            # line — that one reads a fenced "measured" as the author's own confidence, on
            # the one doc type whose whole purpose is separating confirmed from inferred.
            cls, label = chip_resolver(heading, "\n".join(_prose_only(sec)))
            extra = f" {chip_class}" if chip_class else ""
            chip_html = f' <span class="chip {cls}{extra}">{html.escape(label)}</span>'
        cls_attr = f' class="{section_class}"' if section_class else ""
        # The anchor exists to be a link target, so it is emitted only when something
        # links to it. Without this, every roadmap card would gain an `id` nothing uses.
        id_attr = f' id="s{bi + 1}"' if index_class else ""
        out.append(
            f'<section{cls_attr}{id_attr}>'
            f'<{heading_tag}>{inline_fn(html.escape(heading))}{chip_html}</{heading_tag}>'
            f'{body_html}</section>')
    return "\n".join(out)
