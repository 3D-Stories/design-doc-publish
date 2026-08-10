"""Checks that read the SOURCE markdown, not the rendered HTML.

`lint.py` answers "is this page well-formed?" and is asserted `== []` against HTML
fixtures at a dozen sites. These two checks cannot live there, because both questions are
about the markdown that produced the page:

  - `check_unsupported_syntax` — does the source use a construct this renderer passes
    through as its own literal characters?
  - `check_status_drift` — did a republish change one surface's status and leave the
    document's other mentions of the same subject saying the old thing?

Both are DELIBERATELY not in `lint.CHECKS`, for the same reason `check_blocks` is not:
they are publish policy, not page defects. `publish_doc` calls them.

Why they exist, measured on a real session 2026-08-08:

  - `~~strikethrough~~` reached a live page as six literal tilde characters. Render, lint,
    deploy and the byte-identity check all passed, because every one of them was asking
    whether the bytes that were linted reached the page. They did. Nobody was asking
    whether the markdown said what its author meant.
  - A milestone was marked shipped in a phases row while four sub-rows kept `note`/`warn`
    badges, a narrative section still opened as a to-do list, and another section still
    called a merged child a "PROPOSED move". Twice in a row, one surface of many.

The shared lesson: a green publish proves delivery, never correctness of the source.
"""
from __future__ import annotations

import difflib
import re
import subprocess

# --- masking code regions ------------------------------------------------------------
#
# Every construct below is legal inside a code fence, inline code, or an HTML comment —
# this file's own docstring contains three of them. Masking replaces those regions with
# spaces rather than deleting them, so every reported line number still indexes the
# author's real file.

_FENCE = re.compile(r"^(?P<f>```+|~~~+)[^\n]*\n.*?^(?P=f)[ \t]*$", re.S | re.M)
_INLINE = re.compile(r"(?<!`)(`+)(?!`).*?(?<!`)\1(?!`)", re.S)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_INDENTED = re.compile(r"^(?: {4}|\t)[^\n]*$", re.M)


def _blank(m: re.Match) -> str:
    """Same length, same newlines — offsets and line numbers survive."""
    return "".join("\n" if c == "\n" else " " for c in m.group(0))


def mask_code(md: str) -> str:
    for pat in (_FENCE, _COMMENT, _INLINE, _INDENTED):
        md = pat.sub(_blank, md)
    return md


# --- check 1: syntax this renderer does not implement --------------------------------
#
# Every pattern here was CONFIRMED to survive into rendered output as its own source
# characters, by rendering a probe and reading the result — not by reading the parser.
# Anything added later earns its place the same way. A construct that merely renders
# imperfectly does NOT belong here; the test is "do the author's own keystrokes appear
# on the page".

_UNSUPPORTED: tuple[tuple[str, re.Pattern, str], ...] = (
    ("strikethrough", re.compile(r"~~(?=\S)[^~\n]+(?<=\S)~~"),
     "renders as literal tildes; write the words instead, or mark it superseded in prose"),
    ("task list", re.compile(r"^[ \t]*[-*+][ \t]+\[[ xX]\][ \t]+\S", re.M),
     "the checkbox renders as literal `[ ]` and the bullet is consumed; use a `steps` "
     "or `chips` block, or plain prose"),
    ("autolink", re.compile(r"<https?://[^>\s]+>"),
     "renders as literal angle brackets and is NOT a link; use [text](url)"),
    ("footnote", re.compile(r"\[\^[^\]\s]+\]"),
     "both the marker and its definition render literally; inline the note or use a "
     "parenthetical"),
    ("highlight", re.compile(r"==(?=\S)[^=\n]+(?<=\S)=="),
     "renders as literal equals signs; use **bold** or a `callout` block"),
    # No `\w` in the lookbehind: a subscript is normally ATTACHED to a word (`H~2~O`),
    # which is exactly the case a word-boundary guard would exclude. Guarding only against
    # a doubled marker is what keeps `~~strike~~` from being reported twice.
    ("subscript/superscript", re.compile(r"(?<!~)~\d+~(?!~)|(?<!\^)\^\d+\^(?!\^)"),
     "renders as literal tildes or carets; spell it out"),
    ("heading id", re.compile(r"^#{1,6}[ \t]+.*\{#[\w-]+\}[ \t]*$", re.M),
     "the brace suffix renders as part of the heading text; the renderer assigns ids "
     "itself"),
    ("emoji shortcode", re.compile(r"(?<![\w:]):[a-z][a-z0-9_+-]{2,}:(?![\w:])"),
     "renders as literal colons; paste the character itself"),
)


def check_unsupported_syntax(md: str) -> list[str]:
    """Constructs whose own source characters would reach the page. file:line + the text."""
    masked = mask_code(md)
    starts = [m.start() for m in re.finditer(r"^", masked, re.M)]

    def line_of(pos: int) -> int:
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    out: list[str] = []
    for name, pat, advice in _UNSUPPORTED:
        seen: set[int] = set()
        for m in pat.finditer(masked):
            ln = line_of(m.start())
            if ln in seen:          # one report per line per construct, not per hit
                continue
            seen.add(ln)
            snippet = md.splitlines()[ln - 1].strip()
            if len(snippet) > 90:
                snippet = snippet[:87] + "..."
            out.append(f"line {ln}: {name} — {advice}\n      {snippet}")
    return out


# --- check 2: a status change that did not sweep the document ------------------------
#
# The user's own framing, and the reason this is not an NLP problem: "matching an
# identifier against the status vocabulary near it would have caught every miss".
# `near` is the same line, because these documents are line-oriented — a table row, a
# phase row, a callout line, a bullet.

_SUBJECT = re.compile(r"#\d{1,5}\b|\bM\d+(?:\.\d+)?\b|\b[A-Z]{2,5}-\d{1,4}\b")

# Two vocabularies, because they carry opposite information.
# The lowercase words are the `phases` state tokens, so these two lists and
# `blocks._PHASE_STATES` have to name the same vocabulary. #166 added the tokens that were
# missing here — `shipped`/`merged` below, `pending`/`active`/`failed` in the open list. Without
# them a phase marked `merged` read as NOT done to this check, so a done phase with a stale open
# child sailed through: exactly the miss `_phase_child_drift` exists to catch. A blessed token
# this file cannot see is a silent hole, which is the same defect class #166 is about.
_DONE = re.compile(
    r"\b(?:SHIPPED|DONE|CLOSED|MERGED|COMPLETE|COMPLETED|LANDED|RESOLVED|FIXED|"
    r"VERIFIED|ok|done|shipped|merged)\b")
_OPEN = re.compile(
    r"\b(?:PAUSED|BLOCKED|PROPOSED|TODO|PENDING|OPEN|WIP|DEFERRED|PARKED|PLANNED|"
    r"NOT STARTED|IN PROGRESS|note|warn|crit|blocked|wip|next|planned|"
    r"pending|active|failed)\b")


# #167: the compound `<label>:<level>` chip. `<label>:done` ALREADY reads as done through the
# list above — `\bdone\b` matches after the colon, and that was verified by probe before this
# comment was written, not assumed. The other three levels matched NOTHING, so a `bug:must`
# child sitting under a phase marked done was invisible to `_phase_child_drift` — the exact
# contradiction that check exists to catch.
#
# Anchored on the COLON rather than added as bare words to `_OPEN`. A bare `should` would fire
# on ordinary prose — "this should be fine" — in any line that also carries a subject id, and a
# stale-status check that cries wolf gets ignored, which costs more than the gap it closes.
_COMPOUND_OPEN = re.compile(r":(?:must|should|could)\b")

# A compound chip's LABEL is a TYPE, not a status, so it must not vote on whether the line reads
# done or open. One label collides today — `note` is also an open-list word — and `note:done`
# therefore read as done AND open at once. Found by the test, not by inspection.
#
# Stripping the label to a bare `:<level>` fixes it without loosening anything: the colon anchor
# survives, so ordinary prose ("this should be fine") still cannot trip the open check.
#
# `[a-z]+` rather than the renderer's label list, deliberately. This file should not need an edit
# every time a label is added, and whether a label is spelled correctly is the renderer's job —
# it already warns loudly about an unknown one.
_COMPOUND_LABEL = re.compile(r"\b[a-z]+:(must|should|could|done)\b")


def _status(line: str) -> tuple[bool, bool]:
    line = _COMPOUND_LABEL.sub(r":\1", line)
    return (bool(_DONE.search(line)),
            bool(_OPEN.search(line) or _COMPOUND_OPEN.search(line)))


def check_status_drift(old_md: str, new_md: str) -> list[str]:
    """Subjects that moved to a done state somewhere, while another line still says open.

    Returns one finding per stale line. Empty when the sweep was complete — or when there
    was no previous version to compare against, which is the first-publication case.
    """
    if not old_md.strip():
        return []

    old_lines, new_lines = old_md.splitlines(), new_md.splitlines()
    changed: set[str] = set()
    sm = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        before = "\n".join(old_lines[i1:i2])
        after = "\n".join(new_lines[j1:j2])
        # A subject counts as "just marked done" when the new text says done for it and
        # the old text did not. Both halves matter: without the old half, every mention
        # of an already-done subject would be re-reported on every republish forever.
        for subj in set(_SUBJECT.findall(after)):
            new_done = any(subj in ln and _status(ln)[0] for ln in after.splitlines())
            old_done = any(subj in ln and _status(ln)[0] for ln in before.splitlines())
            if new_done and not old_done:
                changed.add(subj)

    if not changed:
        return []

    masked = mask_code(new_md).splitlines()
    out: list[str] = []
    for subj in sorted(changed):
        for n, raw in enumerate(masked, 1):
            if subj not in raw:
                continue
            done, still_open = _status(raw)
            if still_open and not done:
                out.append(
                    f"line {n}: {subj} was marked done in this revision, but this line "
                    f"still reads as open\n      {_snip(new_lines[n - 1])}")
    return out + _phase_child_drift(new_md)


def _snip(line: str, limit: int = 90) -> str:
    s = line.strip()
    return s if len(s) <= limit else s[: limit - 3] + "..."


# A `phases` block states parent and child structurally: an unindented row is a phase, an
# indented row is an item inside it (`typed-blocks-grammar.md`). That is what makes the
# four-stale-sub-rows case machine-checkable without understanding a word of English — a
# phase that reads done whose own children still read open is a contradiction the document
# is making with itself, and it needs no previous version to detect.

_PHASES = re.compile(r"^```phases[^\n]*\n(.*?)^```", re.S | re.M)


def _phase_child_drift(md: str) -> list[str]:
    out: list[str] = []
    for blk in _PHASES.finditer(md):
        base = md[: blk.start()].count("\n") + 1      # the fence's own line
        phase_line = phase_text = ""
        phase_done = False
        phase_n = 0
        for off, raw in enumerate(blk.group(1).splitlines(), 1):
            if not raw.strip():
                continue
            n = base + off
            indented = raw[:1] in (" ", "\t")
            if not indented:
                phase_line, phase_n = raw, n
                phase_done, _ = _status(raw)
                phase_text = raw.split("|")[0].strip()
                continue
            if not phase_done:
                continue
            done, still_open = _status(raw)
            if still_open and not done:
                out.append(
                    f"line {n}: this item still reads as open, but its phase "
                    f"\"{_snip(phase_text, 40)}\" (line {phase_n}) reads as done"
                    f"\n      {_snip(raw)}")
    return out


# --- the previous version, for the diff above ---------------------------------------

def previous_committed(md_path) -> str:
    """The last COMMITTED text of this document, or "" when there is none.

    Git is the only possible source. This account's own notes record that an old
    deployment's bytes cannot be fetched back, so the live page cannot serve as the
    previous version — and an untracked or brand-new document correctly has none, which is
    why "" means "first publication, nothing to compare" rather than an error.
    """
    # Walk for `.git` FIRST, with no subprocess at all. Two reasons, and the second is the
    # load-bearing one. Asking git about a file outside a repository is a wasted process.
    # And this pipeline's own invariant — asserted at five sites — is that a stage-3
    # refusal makes ZERO subprocess calls, because "nothing ran" is how "nothing deployed"
    # is proven. A check that spawns git on every run would quietly retire that proof.
    if not any((p / ".git").exists() for p in [md_path.parent, *md_path.parent.parents]):
        return ""
    try:
        proc = subprocess.run(["git", "show", f"HEAD:./{md_path.name}"],
                              cwd=str(md_path.parent), capture_output=True, text=True,
                              check=False)
        return proc.stdout if proc.returncode == 0 else ""
    except (OSError, AttributeError, TypeError):
        # No git binary, or a caller that has substituted subprocess. Either way there is
        # no previous version to compare against, which is the first-publication case —
        # never a reason to block a deploy.
        return ""
