#!/usr/bin/env python3
"""Shared HTML design-artifact renderer (#174).

Turns a design/spec markdown doc into a self-contained, CSP-safe HTML artifact:
inline CSS only, no external hosts (no CDN link/script/font/img), so it renders
anywhere and survives a strict Content-Security-Policy — with TWO stated exceptions,
both inline <script> and neither ever fetched:

  1. The interactive `uat` template (#18), for the style as a whole.
  2. The `codecopy` component, on any RICH style, and only on a page that actually
     contains an ordinary code fence. Writing to the clipboard has no declarative
     expression, so the button cannot exist without it.

A strict `script-src 'self'` must therefore permit an inline script (or its hash) for
those pages. `plain` emits no script under any input, and a rich page with no fence and
no uat template still emits none — `test_uat_template.py` and `test_code_copy.py` pin
both halves.
Optionally embeds a run's
telemetry (read from the run-record structure — never hand-retyped) and always
stamps a visible "Last updated" datetime.

SECURITY (the load-bearing property): this is an HTML generator fed
possibly-untrusted spec text, so it is **escape-first**. Every piece of text —
markdown body, title, telemetry values — is `html.escape`d BEFORE any block
transform runs, and the block transforms only ever wrap already-escaped text in
a fixed whitelist of tags. A `<script>` (or an `onerror=` attribute) in a spec
therefore renders as inert text, never as active markup.

STDLIB ONLY: the CI env installs just pytest + jsonschema, so this pulls in no
markdown library. The renderer handles the common blocks (headings, lists,
fenced code, blockquotes, tables, bold/inline-code, paragraphs) and leaves
anything else as an escaped paragraph — a lossy-but-safe floor, never an
injection. Consecutive plain lines (no blank/block line between them) form ONE
paragraph with soft-wrap joining — a single space between lines — and two-space
hard breaks (a line ending in 2+ spaces becomes a `<br>`), standard markdown
semantics (changed in #344; single-line paragraphs are unchanged).

Datetime default is mountain time (owner preference for rawgentic reports,
#174); pass `generated_at` for a deterministic stamp.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from string import Template as _Template


def _mountain_now() -> str:
    """Current wall-clock in Calgary/Alberta mountain time, with the CORRECT
    seasonal label (MDT in summer, MST in winter) — owner is in Calgary, AB, so
    use the real America/Edmonton zone rather than a fixed offset (a fixed UTC-7
    would read an hour slow and mislabel 'MST' during daylight time)."""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/Edmonton"))
        return now.strftime("%Y-%m-%d %H:%M %Z")
    except Exception:
        # Fallback if tzdata is unavailable: UTC, honestly labelled (never a wrong MST/MDT).
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# --- inline markdown (escape-first: input here is ALREADY html.escape'd) ---

# --- the markdown parser lives in render/markdown.py (moved by #16) ---
# Re-exported so existing importers of `render._inline` etc. keep working.
from .markdown import (  # noqa: E402,F401
    _inline, _inline_rich, _is_table_separator, _render_body_plain, _render_roadmap,
    _split_table_row, status_chip, _STATUS_VOCAB, render_sections,
    roadmap_status_chip, confidence_chip, CTX_SECTION_CHIPS_OFF,
)
from . import blocks as _blocks  # noqa: E402
from . import frame as _frame  # noqa: E402
from . import templates as _templates  # noqa: E402
from . import tokens as _tokens  # noqa: E402
from . import vdl as _vdl  # noqa: E402


# --- #344: inline decorators — badge/chip markup on ALREADY-escaped-and-inlined text ---
#
# A decorator receives the output of `_inline` (escape-first: may contain only
# attribute-free <code>/<strong>, guarded by test_inline_closed_grammar_guard). It
# adds badge <span>s to the text OUTSIDE <code>…</code> spans only — a code span is
# a literal quote (e.g. `Severity: High`) and must render undecorated. Because the
# input is already escaped, every inserted span wraps inert text; a spec's <script>
# stays &lt;script&gt;. Each decorator runs ONE re.sub pass and never rescans its own
# inserted markup.

_CODE_SPAN_RE = re.compile(r"<code>.*?</code>", re.DOTALL)

# #74: where the resolved VDL pack sits in the per-render scratchpad.
_CTX_VDL = "_vdl_pack"


def furniture_pack(ctx) -> dict | None:
    """The render's VDL pack, for a `BEFORE_BODY` callable. `None` when no pack was resolved.

    **Why this is safe to emit unescaped**, which AC4 asks be stated rather than assumed.
    Furniture is a trusted constant written in this repo and emitted without escaping; a callable
    does not change that, because what it can reach is not author text. The pack comes from
    `vdl_packs.py` — repository configuration, resolved through the shared module the index and
    the pages both read — and never from the markdown being rendered. `render_artifact` puts
    nothing else in the scratchpad that originates with the document.

    The colour accessors in `vdl.py` additionally `fullmatch` a hex literal before returning it,
    so a malformed pack yields `None` rather than a string that lands in markup. A callable that
    prints something OTHER than a validated colour owns escaping it — say so at that call site.
    """
    pack = (ctx or {}).get(_CTX_VDL)
    return pack if isinstance(pack, dict) else None


def _decorate_outside_code(fragment: str, seg_fn) -> str:
    """Apply ``seg_fn`` to the parts of ``fragment`` OUTSIDE ``<code>…</code>`` spans,
    passing code spans through verbatim. ``fragment`` is `_inline` output."""
    out: list[str] = []
    last = 0
    for m in _CODE_SPAN_RE.finditer(fragment):
        out.append(seg_fn(fragment[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(seg_fn(fragment[last:]))
    return "".join(out)


def _decorate_scores(fragment: str) -> str:
    """Wrap ``N/5`` fidelity scores (N in 0–5, optional one decimal) in a ``.score`` chip."""
    return _decorate_outside_code(
        fragment,
        lambda seg: re.sub(r"\b([0-5](?:\.\d)?)/5\b",
                           r'<span class="score">\1/5</span>', seg))


def _decorate_severity(fragment: str) -> str:
    """Wrap a ``Severity: <Level>`` level in a ``.sev .sev-<level>`` badge (level lowercased)."""
    return _decorate_outside_code(
        fragment,
        lambda seg: re.sub(
            r"(Severity: )(Critical|High|Medium|Low)\b",
            lambda m: f'{m.group(1)}<span class="sev sev-{m.group(2).lower()}">{m.group(2)}</span>',
            seg))


def _decorate_requirements(fragment: str) -> str:
    """Wrap RFC-2119 keywords in a ``.req .req-<slug>`` badge. Longest-first alternation
    so ``MUST NOT`` becomes ONE ``req-must-not`` span, never a nested ``MUST`` span."""
    # [ \x00]+ (not a literal space) so a two-space hard break falling between
    # MUST/SHOULD and NOT — the \x00 placeholder at decoration time — still reads
    # as the prohibition, not a positive MUST (#344 8a review).
    return _decorate_outside_code(
        fragment,
        lambda seg: re.sub(
            r"\b(MUST[ \x00]+NOT|SHOULD[ \x00]+NOT|MUST|SHOULD|MAY)\b",
            lambda m: '<span class="req req-{}">{}</span>'.format(
                "-".join(m.group(1).replace("\x00", " ").lower().split()), m.group(1)),
            seg))


def _render_body(markdown: str, style: str = "plain", ctx: dict | None = None) -> str:
    """Dispatch on style via the ``_TEMPLATES`` registry (defined below with the CSS
    blocks). ``plain`` (default) adds no template CSS, decorator, or body class; its
    block output matches pre-#199 for single-line paragraphs, with GFM tables added
    in #343 and multi-line soft-wrap paragraph joining in #344. A decorator,
    if the template has one, is composed after ``_inline`` and applied wherever the
    body renderer runs its inline pass. Unknown styles fall back to plain WITH a
    stderr warning (the CLI argparse-rejects them; library callers get the loud
    fallback instead of a silent restyle — #344 8a review)."""
    # Normalize CR endings at the dispatch point so BOTH renderer families (plain and
    # roadmap/dashboard) see LF-only input — a raw-CRLF library string otherwise
    # leaks \r into roadmap h3 headings (#344 Step 11 review).
    markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    if style not in _TEMPLATES:
        print(f"render_artifact: WARNING unknown style {style!r} — falling back to "
              f"plain (choose one of {tuple(_TEMPLATES)})", file=sys.stderr)
    renderer, _css, dec = _TEMPLATES.get(style, _TEMPLATES["plain"])
    # #16: `plain` keeps bare `_inline` and the ungated block loop, so its bytes are
    # unchanged (AC2). Every richer template gets the seven fixed constructs — the
    # inline ones via `_inline_rich`, the block ones via `rich=True`.
    rich = style != "plain" and style in _TEMPLATES
    base = _inline_rich if rich else _inline
    inline_fn = (lambda esc: dec(base(esc))) if dec else base
    # #39: only the bound template renderers take a ctx. `plain` is `_render_body_plain`,
    # whose signature is fixed and whose bytes are pinned — it gets no ctx and can record
    # no feature, which is correct: plain renders every typed block as a code listing.
    if rich:
        return renderer(markdown, inline_fn=inline_fn, rich=rich, doc_type=style, ctx=ctx)
    return renderer(markdown, inline_fn=inline_fn, rich=rich, doc_type=style)


# --- telemetry (read-only consumer of the run-record shape) ---

def _telemetry_html(t: dict) -> str:
    """Render a run-record dict as an escaped telemetry table. Tolerant of missing
    keys (partial records are valid mid-lifecycle); every value is escaped."""
    if not isinstance(t, dict):
        # A telemetry value that isn't an object (schema drift, wrong file) must
        # not crash the render — surface it visibly instead of a raw traceback.
        return "<section class='telemetry-section'><h2>Run telemetry</h2>" \
               "<p><em>telemetry unavailable (not a run-record object)</em></p></section>"

    def esc(v):
        return html.escape(str(v))

    rows: list[str] = []
    issue = t.get("issue") or {}
    if issue:
        rows.append(f"<tr><th>Issue</th><td>#{esc(issue.get('number','?'))} "
                    f"({esc(issue.get('type','?'))}, {esc(issue.get('complexity','?'))})</td></tr>")
    if "lane" in t:
        rows.append(f"<tr><th>Lane</th><td>{esc(t['lane'])}</td></tr>")
    tests = t.get("tests") or {}
    if tests:
        rows.append(f"<tr><th>Tests</th><td>{esc(tests.get('added','?'))} added · "
                    f"{esc(tests.get('passing','?'))}/{esc(tests.get('total','?'))} passing</td></tr>")
    # #22: `ran` is the ONLY thing separating a scan that found nothing from one that
    # never happened. The producer (rawgentic hooks/work_summary.py) REQUIRES ran=false
    # to carry blocking_resolved=0, advisory=0 and skipped=[], so in the data the two
    # are identical — rendering the counts turned a missing gate into an apparent pass.
    # Tested by IDENTITY, never truthiness: bool("false") is True, so `if ran:` would
    # report {"ran": "false"} as a completed clean scan, reintroducing this very bug.
    unknown = "?"                            # never let unknown data read as a measurement
    # #22: the security row is emitted even when the section is ABSENT, because a row
    # that is not there is a row nobody notices — and this is the one line a reader uses
    # to decide whether something is safe to ship. Guarded on the record being
    # recognisably a run-record, so a wholly unrecognised object still falls through to
    # the "telemetry unavailable" placeholder rather than growing a lone security row.
    looks_like_run_record = (bool(issue or tests or t.get("outcome") or t.get("usage")
                                  or t.get("gates")) or "lane" in t)
    if "security_scan" in t or looks_like_run_record:
        sec = t.get("security_scan")         # absent, or an explicit null, both land in
                                             # the not-a-dict branch below
        if not isinstance(sec, dict):
            # Covers null, {}, [], 0, "" and any truthy non-dict. A truthy non-dict does
            # NOT fall through a falsy-default — it would reach .get() and raise, taking
            # down the whole render. Same tolerance the gates loop already applies.
            body = "not reported"
        elif sec.get("ran") is False:
            body = "not run"
        elif sec.get("ran") is not True:
            body = "not reported"            # absent or non-boolean: the record never said
        else:
            def _count(v):
                # Presence is not usability. `type(v) is int` deliberately excludes bool,
                # which is an int subclass — otherwise advisory=False renders "False".
                return esc(v) if type(v) is int and v >= 0 else unknown

            sk = sec.get("skipped")
            # Entries must be non-blank: [""] would join to "" and then fall back to
            # "none", i.e. a corrupt entry claiming nothing was skipped; ["   "] would
            # render a visually empty value.
            skipped = ((", ".join(esc(s) for s in sk) or "none")
                       if isinstance(sk, list) and all(isinstance(s, str) and s.strip() for s in sk)
                       else unknown)
            body = (f"{_count(sec.get('blocking_resolved'))} blocking resolved · "
                    f"{_count(sec.get('advisory'))} advisory · skipped: {skipped}")
        rows.append(f"<tr><th>Security scan</th><td>{body}</td></tr>")
    outcome = t.get("outcome") or {}
    if outcome:
        rows.append(f"<tr><th>Outcome</th><td>PR {esc(outcome.get('pr_number','?'))} · "
                    f"merged: {esc(outcome.get('merged','?'))} · CI: {esc(outcome.get('ci','?'))}</td></tr>")
    usage = t.get("usage") or {}
    if usage:
        wc = usage.get("wall_clock_s")
        rows.append(f"<tr><th>Usage</th><td>in {esc(usage.get('input_tokens','?'))} / "
                    f"out {esc(usage.get('output_tokens','?'))} tokens"
                    + (f" · {esc(wc)}s wall" if wc is not None else "") + "</td></tr>")

    gates = t.get("gates") or []
    gate_rows = ""
    for g in gates:
        if not isinstance(g, dict):
            continue  # drifted record: skip a non-dict gate entry rather than crash
        gate_rows += (f"<tr><td>{esc(g.get('step','?'))}</td><td>{esc(g.get('name','?'))}</td>"
                      f"<td>{esc(g.get('findings',0))}</td><td>{esc(g.get('resolved',0))}</td>"
                      f"<td>{esc(g.get('status','?'))}</td></tr>")
    gate_table = ""
    if gate_rows:
        gate_table = ("<h2>Quality gates</h2><table class='gates'><thead><tr>"
                      "<th>Step</th><th>Gate</th><th>Findings</th><th>Resolved</th><th>Status</th>"
                      "</tr></thead><tbody>" + gate_rows + "</tbody></table>")

    summary = ("<table class='telemetry'><tbody>" + "".join(rows) + "</tbody></table>") if rows else ""
    if not summary and not gate_table:
        # Passed a dict but nothing recognized (run-record schema drift) — a visible
        # placeholder beats silently emitting no telemetry on a lifecycle artifact
        # whose whole point is embedding the run data.
        return "<section class='telemetry-section'><h2>Run telemetry</h2>" \
               "<p><em>telemetry unavailable (no recognized run-record fields)</em></p></section>"
    return "<section class='telemetry-section'><h2>Run telemetry</h2>" + summary + gate_table + "</section>"


_STYLE_TPL = """
:root{--bg:#12181c;--surface:#1a2228;--ink:#e7edf0;--ink-2:#a8b6bd;--ink-3:#76858f;
--line:#2a353c;--accent:#2dd4bf;--code:#232d34}
:root[data-theme=dark]{--bg:#12181c;--surface:#1a2228;--ink:#e7edf0;--ink-2:#a8b6bd;
--ink-3:#76858f;--line:#2a353c;--accent:#2dd4bf;--code:#232d34}
:root[data-theme=light]{--bg:#f6f7f8;--surface:#fff;--ink:#1a2126;--ink-2:#4b5a63;
--ink-3:#667279;--line:#dde3e6;--accent:#0f766e;--code:#eef1f3}
@media print{:root,:root[data-theme=dark]{--bg:#f6f7f8;--surface:#fff;--ink:#1a2126;
--ink-2:#4b5a63;--ink-3:#667279;--line:#dde3e6;--accent:#0f766e;--code:#eef1f3}}
*{box-sizing:border-box}
body{margin:0;background:$ground;color:var(--ink);
font:15px/1.6 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased}
.wrap{max-width:$measure;margin:0 auto;padding:$gutter}
header{padding:$header_pad;border-bottom:$header_rule;margin-bottom:$header_gap}
.eyebrow{color:var(--accent);font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase}
h1{font-size:$h1_size;margin:.3em 0;font-weight:750;letter-spacing:-.02em}
h2{font-size:$h2_size;font-weight:700;margin:$h2_rhythm}
h3{font-size:16px;font-weight:650;margin:1.2em 0 .3em}
p,li{color:var(--ink-2)}
code{background:var(--code);border-radius:$radius_sm;padding:1px 5px;font:12.5px/1.4 ui-monospace,Menlo,Consolas,monospace}
pre{background:var(--code);border:1px solid var(--line);border-radius:$radius_md;padding:12px 14px;overflow-x:auto}
pre code{background:none;padding:0}
blockquote{border-left:3px solid var(--accent);margin:.6em 0;padding:.2em 0 .2em 14px;color:var(--ink-3)}
table{border-collapse:collapse;width:100%;margin:.6em 0;font-size:13.5px}
th,td{text-align:left;padding:8px 12px;border-bottom:1px solid var(--line);vertical-align:top}
.telemetry th{white-space:nowrap;color:var(--ink-3);width:1%}
.telemetry-section{background:var(--surface);border:1px solid var(--line);border-radius:$radius_lg;padding:4px 18px 14px;margin-top:24px}
footer{margin-top:40px;padding-top:16px;border-top:1px solid var(--line);color:var(--ink-3);font-size:12.5px}
"""

# #42: the radius scale is named in `tokens.py` and substituted in HERE, so the token data is the
# single source rather than a second copy that drifts. `string.Template` (not %-formatting or an
# f-string) because this CSS is full of braces and contains `%`, while it contains no `$` at all.
# `test_tokens.py` pins the result to the exact pre-#42 SHA-256: the substitution is required to be
# byte-for-byte inert, which is what keeps AC5's frozen `plain` output frozen.
# #69 substitutes the FRAME slots through the same seam, for the same reason: the frame a
# template may own is named data in `frame.py`, and the default page is what it always was.
# Substituting the defaults must be byte-inert — pinned by test_frame_ownership.py against #73.
_STYLE = _Template(_STYLE_TPL).substitute(
    radius_sm=_tokens.RADII["sm"],
    radius_md=_tokens.RADII["md"],
    radius_lg=_tokens.RADII["lg"],
    **_frame.DEFAULTS,
)

# #199: injected ONLY in roadmap style, so plain output stays byte-identical to
# pre-#199. Adds the chip/card color tokens (dashboard values, light + dark) plus
# the .mstone / .chip / completion-color component rules the dashboard uses.
_ROADMAP_STYLE = """
:root{--chip-c:#2dd4bf;--chip-c-bg:#123531;--defer:#fbbf24;--defer-bg:#302a14}
:root[data-theme=dark]{--chip-c:#2dd4bf;--chip-c-bg:#123531;--defer:#fbbf24;--defer-bg:#302a14}
:root[data-theme=light]{--chip-c:#0f766e;--chip-c-bg:#e6f2f0;--defer:#955a06;--defer-bg:#f8f2e2}
@media print{:root,:root[data-theme=dark]{--chip-c:#0f766e;--chip-c-bg:#e6f2f0;--defer:#955a06;--defer-bg:#f8f2e2}}
.mstone{background:var(--surface);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:12px;padding:14px 16px;margin:14px 0}
.mstone h3{margin:0 0 .4em;font-size:15px;display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.chip{font-size:11px;font-weight:700;letter-spacing:.04em;padding:2px 8px;border-radius:999px;text-transform:uppercase;white-space:nowrap}
.c-conf{color:var(--chip-c);background:var(--chip-c-bg)}
.c-defer{color:var(--defer);background:var(--defer-bg)}
.c-plan{color:var(--ink-2);background:var(--code)}
"""

# #344: shared component styles for the decorator badges — injected by every
# non-plain template (never plain, so plain stays byte-identical). Defines the
# severity/requirement color tokens in all three theme blocks (:root light, @media
# dark, [data-theme] overrides), consistent with the existing palette.
_COMPONENT_STYLE = """
:root{--sev-crit:#f87171;--sev-crit-bg:#3b1717;--sev-high:#fb923c;--sev-high-bg:#3a2410;--sev-med:#fbbf24;--sev-med-bg:#302a14;--sev-low:#a8b6bd;--sev-low-bg:#232d34;--req-c:#2dd4bf;--req-c-bg:#123531}
:root[data-theme=dark]{--sev-crit:#f87171;--sev-crit-bg:#3b1717;--sev-high:#fb923c;--sev-high-bg:#3a2410;--sev-med:#fbbf24;--sev-med-bg:#302a14;--sev-low:#a8b6bd;--sev-low-bg:#232d34;--req-c:#2dd4bf;--req-c-bg:#123531}
:root[data-theme=light]{--sev-crit:#b91c1c;--sev-crit-bg:#fdecec;--sev-high:#c2410c;--sev-high-bg:#fdeee2;--sev-med:#955a06;--sev-med-bg:#f8f2e2;--sev-low:#4b5a63;--sev-low-bg:#eef1f3;--req-c:#0f766e;--req-c-bg:#e6f2f0}
@media print{:root,:root[data-theme=dark]{--sev-crit:#b91c1c;--sev-crit-bg:#fdecec;--sev-high:#c2410c;--sev-high-bg:#fdeee2;--sev-med:#955a06;--sev-med-bg:#f8f2e2;--sev-low:#4b5a63;--sev-low-bg:#eef1f3;--req-c:#0f766e;--req-c-bg:#e6f2f0}}
.score{font:11.5px/1.4 ui-monospace,Menlo,Consolas,monospace;font-weight:700;background:var(--code);color:var(--accent);border-radius:5px;padding:1px 6px}
.sev{font-size:11px;font-weight:700;letter-spacing:.03em;padding:1px 7px;border-radius:999px;text-transform:uppercase;white-space:nowrap}
.sev-critical{color:var(--sev-crit);background:var(--sev-crit-bg)}
.sev-high{color:var(--sev-high);background:var(--sev-high-bg)}
.sev-medium{color:var(--sev-med);background:var(--sev-med-bg)}
.sev-low{color:var(--sev-low);background:var(--sev-low-bg)}
.req{font-size:11px;font-weight:700;letter-spacing:.03em;padding:1px 6px;border-radius:5px;color:var(--req-c);background:var(--req-c-bg)}
.req-must-not,.req-should-not{color:var(--sev-crit);background:var(--sev-crit-bg)}
.req-may{color:var(--ink-3);background:var(--code)}
"""

# #13: the per-template accent blocks that used to live here (one or two CSS lines each)
# moved into `templates/<name>.py` alongside that type's structure config and marker map.
# `_ROADMAP_STYLE` stays above because roadmap AND dashboard both inject it.

# The decorators cannot live in `templates/` without that package importing this module,
# so the registry binds them here by name. Adding a decorator to a template is a one-line
# change in this map.
_DECORATORS = {
    "report": _decorate_scores,
    "review": _decorate_severity,
    "spec": _decorate_requirements,
}

# Templates whose cards come from the roadmap/dashboard family. Everything else renders
# through `render_sections` (which is `_render_body_plain` plus optional structure) —
# the two families differ only in the config they pass.
_ROADMAP_FAMILY = ("roadmap", "dashboard")


def _bind(name):
    """Bind one template's structure config and marker map onto a renderer.

    Returned callable keeps the `(markdown, inline_fn, rich, doc_type)` signature every
    caller already uses, so `_render_body` needs no knowledge of any of this. The marker
    map flows DOWNWARD from here — template to markdown to blocks — which is why
    `blocks.py` never imports a template.
    """
    module = _templates.TEMPLATES[name]
    cfg = _templates.sections_config(module)
    markers = _templates.MARKERS[name]
    # The same decorator the prose pass uses. Typed fences bypass `inline_fn`, so without
    # this a `steps req` row rendered a bare MUST where the template promises a chip.
    decorate = _DECORATORS.get(name)
    variants = _templates.VARIANTS[name]
    # Trusted CONSTANT furniture (#18) — uat's meter, filter, export control and script,
    # and since #41 workflow's step-kind key. They hold no author text at any point, which
    # is why they are emitted unescaped. A template declaring neither is unchanged.
    # NOTE: this is prepended INDEPENDENTLY of sectioning, so furniture alone changes a
    # template's tag sequence. A structural test that only asserts "this style differs from
    # plain" is therefore satisfied by furniture and proves nothing about the body — that
    # trap was caught in #41's design gate before it shipped.
    # #74: a furniture entry may be a CALLABLE taking the render context, so a template can print
    # its project's real values instead of only painting `var(--accent)`. Plain strings are left
    # exactly as they were, which is why every template that does not opt in is byte-identical —
    # measured against per-style SHAs captured before the change, not assumed.
    #
    # Deferred to render time, not joined here: the whole point is a value that differs per
    # render, and `_bind` runs once at import.
    furniture = _templates.BEFORE_BODY[name]
    after = "".join(_templates.AFTER_BODY[name])

    def render(markdown, inline_fn=None, rich=False, doc_type=None, ctx=None):
        # A FRESH per-document scratchpad. Identity that must be unique page-wide — the
        # uat checklist's item ids — accumulates here, so two fences in one document
        # cannot collide, and two documents cannot leak into each other.
        #
        # #39: the caller MAY supply one. `render_artifact` does, because it needs to read
        # back which optional features actually rendered in order to decide which CSS/JS
        # layers to emit — and the scratchpad used to be created and discarded in here,
        # where nothing outside the closure could see it. An absent ctx keeps the old
        # behaviour exactly: a fresh dict nobody else reads.
        if ctx is None:
            ctx = {}
        # #67: typed-fence cells reached `_prose` but never the inline pass, so an author
        # writing `**bold**` inside a callout — by reflex, the file is markdown everywhere
        # else — got asterisks printed at the reader. `_prose` already funnels every prose
        # cell through `decorate`, so composing the inline pass into that one callable fixes
        # all seventeen sites without touching any of them, and `blocks` still imports
        # nothing upward.
        #
        # Inline runs FIRST, then the decorator. The other order would let the decorator's
        # word match land inside an `<em>`/`<strong>` span the inline pass had just opened.
        block_inline = inline_fn or (lambda escaped: escaped)
        cell = ((lambda escaped: decorate(block_inline(escaped))) if decorate
                else block_inline)
        body = render_sections(markdown, inline_fn=inline_fn, rich=rich,
                               doc_type=doc_type, markers=markers, decorate=cell,
                               variants=variants, ctx=ctx, **cfg)
        before = "".join(f(ctx) if callable(f) else f for f in furniture)
        return before + body + after
    render.__name__ = f"_render_{name}"
    return render


def _css_for(name):
    """Shared layers first, then this template's own. Every non-plain template gets the
    component tokens and — new in #13 — `BLOCK_CSS`, without which every typed block
    renders as unstyled stacked text (the gap wave 2 left behind)."""
    layers = [_COMPONENT_STYLE, _blocks.BLOCK_CSS]
    if name in _ROADMAP_FAMILY:
        layers.append(_ROADMAP_STYLE)
    # #69: the frame this style declares, BEFORE its own stylesheet — the frame is the base a
    # template decorates, so a hand-written rule at equal specificity still wins on source order.
    layers.append(_frame.css_layer(name, getattr(_templates.TEMPLATES[name], "FRAME", None)))
    # #75: the decorative accent palette, if this style declares one. Emitted only when declared,
    # so the nine that do not are byte-inert — see `frame.palette_layer` for why the engine writes
    # these values and a template's own stylesheet may not.
    layers.append(_frame.palette_layer(name, getattr(_templates.TEMPLATES[name], "ACCENTS", None)))
    layers.append(_templates.CSS[name])
    return layers


# #344/#13: template registry — name -> (body_renderer, [extra_css_blocks], decorator|None).
# Insertion order is meaningful (drives argparse choices ordering). ``plain`` stays
# renderer=_render_body_plain with no template CSS, decorator, or body class (its
# block semantics themselves changed in #343/#344 — see the module docstring), and is
# the ONE entry not built from `templates/`, because it has nothing to declare.
_TEMPLATES = {"plain": (_render_body_plain, [], None)}
_TEMPLATES.update({
    name: (_bind(name), _css_for(name), _DECORATORS.get(name))
    for name in _templates.TEMPLATES
})


def _strip_duplicate_title(markdown: str, title: str) -> str:
    """Drop a leading `# <title>` heading that merely repeats the page title.

    Operates on SOURCE, before any renderer or template wrapper sees it — see the call
    site for why that matters.

    #67: it used to remove the heading ONLY on a byte-for-byte match with `--title`, so
    abbreviating the title for a browser tab or a Vercel project name silently produced a page
    with two `<h1>` elements — bad for a screen reader, and it reads as a duplicated title to
    everyone else. A live page shipped with exactly that.

    The issue's diagnosis is the fix: *an exact-string match is the wrong test for "is this the
    same heading"*. So sameness is now judged after normalising case, whitespace and trailing
    punctuation, and one being a prefix of the other counts — which is what abbreviating IS.
    A genuinely different heading is still the author's own and still survives, but it no longer
    does so in silence: it warns that the page will carry two `<h1>`s, which is AC3's other limb.

    Only the LEADING heading is considered: a later `# ` is content, not the title restated.
    """
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        m = re.match(r"#\s+(.*)", line)
        heading = m.group(1).strip() if m else None
        # A heading carrying inline markdown is left alone: it is not a plain restatement of
        # the title, and removing it would drop formatting the author meant to show.
        if heading is not None and not any(c in heading for c in "*_`["):
            if _same_heading(heading, title):
                del lines[i]
            else:
                _blocks._warn(
                    f"the document's leading h1 {heading!r} is not the title "
                    f"{title.strip()!r}, so this page will have TWO h1 elements — drop the "
                    f"heading, or pass it as --title, if it was meant to be the page title")
        break
    return "\n".join(lines)


def _headline(title: str, style: str) -> tuple[str, str]:
    """`(plain title, h1 inner HTML)` — the two-tone display headline, opt-in per style (#75).

    The frozen `uat` target's first-read element is a headline whose phrases alternate between
    ink and accent. **Only the author can say where the phrases divide** — the engine splitting
    on word count, or on the halfway mark, would be guessing at emphasis. So the author writes the
    divisions with `|`, the separator this engine already uses for every other field:

        --title "Three builds | landed | since you | last tested."

    A style that does not declare `HEADLINE` gets exactly what it got before — `html.escape(title)`
    and nothing else — which is what keeps the other nine byte-identical. A declaring style whose
    title carries no `|` also falls through to that path: one phrase is not two tones.

    The separator is stripped everywhere ELSE the title is used — the `<title>` element, the
    storage-key slug, and the duplicate-`h1` comparison — so a pipe in the headline can never
    leak into a browser tab or silently change a page's storage key.
    """
    declared = getattr(_templates.TEMPLATES.get(style), "HEADLINE", None)
    parts = [p.strip() for p in title.split("|")] if declared else []
    parts = [p for p in parts if p]
    if not declared or len(parts) < 2:
        return title, html.escape(title)
    plain = " ".join(parts)
    spans = " ".join(
        f'<span class="h1-{"b" if i % 2 else "a"}">{html.escape(p)}</span>'
        for i, p in enumerate(parts))
    return plain, spans


def _same_heading(heading: str, title: str) -> bool:
    """Whether a leading `# ` restates the page title, abbreviation included.

    Abbreviating the title for a browser tab or a Vercel project name is ordinary, and the
    abbreviation is nearly always a prefix — "Backlog re-evaluation — epics E1 to E5" against a
    heading that continues "…, after the audit". Byte equality called those two different
    documents and shipped a duplicated title.
    """
    def norm(s):
        return re.sub(r"\s+", " ", s).strip().strip(".,;:—–-").casefold()

    a, b = norm(heading), norm(title)
    return bool(a) and bool(b) and (a == b or a.startswith(b) or b.startswith(a))


def _slug(text: str) -> str:
    """A conservative slug, used ONLY for the title fallback.

    Never applied to an explicit `doc_id`: slugging collapses case and every punctuation
    run, so `repo/a`, `repo:a` and `REPO-A` all became one key and three distinct UAT
    documents silently shared state on one origin. A localStorage key needs no slug
    syntax, so the transformation bought nothing and cost correctness.
    """
    return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-") or "unknown"


def render_artifact(markdown: str, *, title: str, subtitle: str = "",
                    telemetry: dict | None = None, generated_at: str | None = None,
                    style: str = "plain", doc_id: str | None = None,
                    vdl: dict | None = None, section_chips: bool = True) -> str:
    """Render `markdown` to a self-contained CSP-safe HTML string. All text is
    HTML-escaped before rendering (see module docstring). `generated_at` defaults
    to the current mountain-time stamp. `style` selects a template from ``_TEMPLATES``
    (plain default, unchanged; roadmap #199; report/design/dashboard/review/spec #344).
    Non-plain templates stamp ``<body class="tpl-<style>">`` and inject their CSS
    blocks; plain keeps a bare ``<body>`` (byte-stable). Unknown styles fall back to
    plain rendering and get no body class."""
    stamp = generated_at or _mountain_now()
    # #75: resolved BEFORE anything reads the title, so the `<title>` element, the storage slug
    # and the duplicate-h1 check all see the separator-free form. `h1_html` is the only consumer
    # of the split, and for the nine styles that do not declare `HEADLINE` it is exactly
    # `html.escape(title)` — the byte the header emitted before this existed.
    title, h1_html = _headline(title, style)
    etitle = html.escape(title)
    esub = html.escape(subtitle)
    _renderer, css_blocks, _dec = _TEMPLATES.get(style, _TEMPLATES["plain"])
    # #16, the seventh construct: the page header already renders <h1>{title}</h1>,
    # so a doc whose first line is `# <same title>` shipped TWO identical <h1>s.
    # Rich styles only — `plain` page bytes are pinned by AC2, and a plain doc keeps
    # whatever it always emitted.
    #
    # #13 moved this from the rendered HTML to the SOURCE. It used to be a `\A<h1>`
    # regex over the body, which silently stopped working the moment a template wrapped
    # its preamble (`.dz-lead`, `.db-tldr`) — the body then starts with the wrapper, the
    # anchor misses, and the duplicate title comes back. Stripping the heading before
    # anything renders is independent of what the template does with the result.
    if style != "plain" and style in _TEMPLATES:
        markdown = _strip_duplicate_title(markdown, title)
    # #39: `render_artifact` owns the per-document scratchpad so it can read back which
    # optional components actually rendered. It has to: the body is built here (before the
    # CSS is assembled below), and the scratchpad used to live and die inside `_bind`.
    ctx: dict = {}
    # #74: furniture that wants to PRINT a project's real values needs to see them. The resolved
    # pack goes in the scratchpad every renderer already receives, so no signature grows and
    # nothing that ignores it can change. Trusted config from `vdl_packs.py`, never author text —
    # see `_frame`/`templates` docs and `furniture_pack()` below.
    if vdl is not None:
        ctx[_CTX_VDL] = vdl
    # Page-level section-chip opt-out for narrative documents whose prose discusses
    # completion vocabulary as subject matter — the scanner's one unfixable-from-the-
    # document shape (see the note at the emission site in `markdown.render_sections`).
    if not section_chips:
        ctx[CTX_SECTION_CHIPS_OFF] = True
    # #173: a chip's tooltip prefers the DOCUMENT's own legend to the built-in vocabulary, so a
    # pre-pass has to read the legend before any block renders. Blocks render independently and
    # in document order, and a legend commonly sits BELOW the phase rail it explains — so by the
    # time the rail is built, the meanings it needs have not been seen yet. One scan of the
    # source is the cheapest fix and needs no second pass over the output.
    _blocks.collect_legend(markdown, ctx)
    body = _render_body(markdown, style=style, ctx=ctx)
    _features = _blocks.used_features(ctx)
    # `telemetry is not None` (not truthiness): an explicit empty {} means "record
    # present but empty" → the placeholder, distinct from None ("no telemetry").
    tel = _telemetry_html(telemetry) if telemetry is not None else ""
    sub_html = f'<p class="sub">{esub}</p>' if subtitle else ""
    css = _STYLE + "".join(css_blocks)
    # #39: the optional feature layers sit AFTER the shared/template blocks and BEFORE the
    # VDL layer, in a fixed declaration order. A page that used no new component appends
    # the empty string, so its bytes are unchanged — that is the byte-identity contract,
    # kept by construction rather than by remembering.
    css += _blocks.optional_css(_features)
    # …and the matching script, if any component needs one. Emitted ONCE per page, just
    # before </body>, so the markup it enhances already exists. A page using no scripted
    # component appends the empty string and is byte-unchanged.
    _js = _blocks.optional_js(_features)
    # The newline belongs to the CONTENT, not the template: `{feature_js}` on its own line
    # would emit a blank line on every page that has no script, which is a byte change on
    # every existing page. byte-identity caught exactly that.
    feature_js = ("\n" + _js) if _js else ""
    # #14: the per-project VDL layer goes LAST, after every template block. Placed
    # earlier, a template that redeclared --accent would silently take the page back.
    # `plain` gets no pack and no layer, so its bytes stay pinned (AC1).
    if vdl and style != "plain":
        css += _vdl.css_layer(vdl)
    # Body class marks non-plain templates for their accent selectors; plain stays a
    # bare <body> (no template markup or CSS is ever added to plain).
    body_class = f' class="tpl-{style}"' if style in _TEMPLATES and style != "plain" else ""
    # #18: `uat` persists tester answers in localStorage, so it needs a page identity that
    # is NOT derived from presentation. A title slug would make two pages sharing a title
    # share all state on one origin, and would abandon every saved answer on a rename — so
    # `doc_id` is explicit, and its absence WARNS rather than silently doing the risky
    # thing. It doubles as the routing token the export names as a destination.
    body_data = ""
    if style == "uat":
        if not doc_id:
            print("render_artifact: WARNING uat page has no doc_id — falling back to the "
                  "title slug for its localStorage key; rename the title and every saved "
                  "answer is abandoned. Pass --doc-id.", file=sys.stderr)
        # An explicit doc_id is used VERBATIM — it is the author's chosen namespace and
        # normalising it is how distinct ids collide. Only the title fallback is slugged.
        ident = doc_id.strip() if doc_id else _slug(title)
        body_data = (f' data-uat-key="uat:{html.escape(ident)}:v1"'
                     f' data-uat-repo="{html.escape(doc_id or title)}"')
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="design-doc-publish">
<title>{etitle}</title>
<style>{css}</style>
</head>
<body{body_class}{body_data}>
<div class="wrap">
<header>
<div class="eyebrow">design artifact · updated {html.escape(stamp)}</div>
<h1>{h1_html}</h1>
{sub_html}
</header>
<main>
{body}
{tel}
</main>
<footer>Last updated: {html.escape(stamp)} · generated by design-doc-publish — self-contained, no external resources.</footer>
</div>{feature_js}
</body>
</html>
"""


def _resolve_pack(project, workspace_file):
    """Resolve through the shared module, never a local table — that shared answer
    is the only reason the index and the pages agree (#14 §5)."""
    import importlib.util
    root = Path(__file__).resolve().parent.parent
    path = root / "vdl_packs.py"
    # Containment, duplicated deliberately at each of the three load sites. A shared
    # helper would itself have to be loaded the same way, so the guard cannot live behind
    # the thing it guards. `render-doc` documents the full reasoning: a symlinked target
    # is EXECUTED before any check can reject it, so the check must precede the load.
    real = path.resolve()
    if not real.is_file() or not real.is_relative_to(root):
        raise RuntimeError(f"refusing to load {path}: resolves to {real}, outside {root}")
    spec = importlib.util.spec_from_file_location("_render_vdl_packs", real)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.pack_for(project, workspace_file)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Render a markdown design doc to a CSP-safe HTML artifact.")
    ap.add_argument("--md", required=True, help="input markdown file")
    ap.add_argument("--out", required=True, help="output HTML file")
    ap.add_argument("--title", required=True)
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--telemetry", help="run-record JSON file to embed (optional)")
    ap.add_argument("--generated-at", dest="generated_at", help="datetime stamp (default: mountain time now)")
    ap.add_argument("--doc-id", dest="doc_id",
                    help="stable identifier for a uat page (its localStorage namespace and "
                         "the destination its export names). Ignored by other styles.")
    ap.add_argument("--project",
                    help="rawgentic project whose VDL pack this page wears (#14). "
                         "Omitted, the page renders in the default palette.")
    ap.add_argument("--workspace-file",
                    default=str(Path.home() / "rawgentic" / ".rawgentic_workspace.json"))
    ap.add_argument("--style", choices=tuple(_TEMPLATES), default="plain",
                    help="template: plain (default), roadmap (h2 bubble cards + chips), "
                         "or report/design/dashboard/review/spec (#344 component styles)")
    args = ap.parse_args(argv)

    try:
        md = open(args.md, encoding="utf-8").read()
    except OSError as e:
        print(f"render_artifact: could not read markdown {args.md}: {e}", file=sys.stderr)
        return 2
    tel = None
    if args.telemetry:
        try:
            tel = json.load(open(args.telemetry, encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"render_artifact: could not read telemetry {args.telemetry}: {e}", file=sys.stderr)
            return 2
    pack = None
    if args.project:
        pack = _resolve_pack(args.project, Path(args.workspace_file))
    html_out = render_artifact(md, title=args.title, subtitle=args.subtitle,
                               telemetry=tel, generated_at=args.generated_at,
                               style=args.style, doc_id=args.doc_id, vdl=pack)
    open(args.out, "w", encoding="utf-8").write(html_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
