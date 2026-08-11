"""A docstring may not claim a defect is live without naming an issue, in one canonical form (#113).

The rot this prevents, measured 2026-08-03: four `KNOWN DEFECT` blocks in `scripts/render/`
described behaviour the code no longer had. Three pointed at closed issues. A `KNOWN DEFECT`
block is the strongest "someone fix this" signal in this codebase, so a stale one costs a future
session either a re-fix or — worse — a workaround built around a defect that is not there.

**The canonical form is mandatory, and that is what makes the guard possible.** Any live-defect
claim must open exactly:

    KNOWN DEFECT, still live — #NN

Free-wording it ("KNOWN DEFECT, remains unresolved") is refused by
`test_every_defect_marker_uses_the_canonical_form`. Without that rule the guard could only
recognise phrasings it had been told about, and a new phrasing would pass silently while the
manifest quietly stopped being the whole truth — caught in review before this shipped.

**Why an offline manifest rather than a live GitHub check.** #113's AC3 asked for one or the
other with the choice justified. The unit suite stays offline because it runs in a pre-push gate
with no token guaranteed, and because the issue itself says a test that quietly needs the network
is worse than no test.

An earlier version of this docstring also argued a network check "cannot be written correctly",
because grepping `#NN` out of `scripts/render/` returns `#955`, `#1218`, `#6672` and other CSS
values. **That argument was a false dichotomy and is withdrawn.** Now that the canonical header
exists, a network check *can* extract exactly the live-defect citations and query only those. It
is not done here because this suite must stay offline — a fair reason — not because it is
impossible. Doing it as a separate scheduled or PR-time check is a reasonable follow-up.

**What this proves, stated precisely.** It proves every live-defect claim uses the canonical
form, that the set of files carrying one is exactly the registered set, and that each block cites
the issue the manifest records. It does NOT prove those issues are still open — nothing offline
can. That gap is **procedurally mitigated, not closed**: #119 carries an acceptance criterion
requiring these blocks to be updated when it closes. An acceptance criterion is a human
procedure, so closing #119 without touching these files would leave the suite green and the claim
stale. To audit by hand:

    gh issue view 119 --repo 3D-Stories/example --json state
"""
import re
from pathlib import Path

RENDER = Path(__file__).resolve().parent.parent / "render"

# The ONE accepted way to claim a defect is currently live. Captures the issue number.
CANONICAL = re.compile(r"KNOWN DEFECT, still live\s*[—-]+\s*\*{0,2}#(\d{1,4})")

# Anything that looks like a live-defect claim. Every hit must ALSO match CANONICAL.
# Deliberately narrow: ordinary design commentary and `# ponytail:` notes are out of scope
# per #113's "Not in scope".
SUSPECT = re.compile(r"KNOWN DEFECT|NOT fixed here")

# One entry per live-defect BLOCK, in source order — a list, not a set, so a second uncited
# block in an already-registered file cannot hide behind the first one's citation.
LIVE_DEFECT_CITATIONS = {
    # `templates/analysis.py`, `templates/roadmap.py` and `templates/dashboard.py` each carried a
    # [119] entry until 2026-08-05. #119 shipped — the negator vocabulary gained the quantifier
    # forms and the two-token reach window became clause scope — so all three blocks moved to the
    # past tense and left this registry. That is the intended lifecycle, and this guard is what
    # forced it: the blocks could not be updated without the registry noticing.
    # `lint.py` carried a [123] entry until 2026-08-05, for `srcset` being comma-split rather
    # than parsed. #123 shipped — `srcset` now uses the HTML candidate-scanning algorithm, and
    # the two decode gaps it also covered (HTML character references, CSS escapes) are classified
    # on every interpretation of the value — so the block moved to past tense and left this
    # registry. Same intended lifecycle as the three [119] entries above.
    # `markdown.py` carried a [122] entry until 2026-08-05, for `_safe_url` refusing ordinary
    # relative paths. #122 shipped — the allowlist now asks whether a url has a SCHEME and
    # whether that scheme is blessed, instead of whether it starts with a blessed prefix — so
    # the block moved to past tense and left this registry.
    #
    # THE REGISTRY IS NOW EMPTY, and that is a real state, not a broken fixture: every
    # live-defect block the epic inherited has shipped. The guard still runs, and an empty
    # registry makes it strictest — ANY new `KNOWN DEFECT, still live` block anywhere under
    # `render/` now fails `test_no_unregistered_live_defect_claim` until it is registered here
    # with the issue that will close it. Do not delete this dict when it is empty.
}


def _sources():
    return sorted(p for p in RENDER.rglob("*.py") if "__pycache__" not in p.parts)


def _rel(p):
    return p.relative_to(RENDER).as_posix()


def _cited(text):
    """Issue number of every canonical live-defect block, in source order."""
    return [int(m.group(1)) for m in CANONICAL.finditer(text)]


def test_every_defect_marker_uses_the_canonical_form():
    """A live-defect claim the guard cannot parse is a claim the guard cannot check."""
    for p in _sources():
        text = p.read_text(encoding="utf-8")
        suspects = len(SUSPECT.findall(text))
        canonical = len(_cited(text))
        assert suspects == canonical, (
            f"{_rel(p)}: {suspects} live-defect marker(s) but {canonical} in canonical form. "
            f"Every one must read exactly 'KNOWN DEFECT, still live — #NN'.")


def test_no_unregistered_live_defect_claim():
    found = {_rel(p) for p in _sources() if _cited(p.read_text(encoding="utf-8"))}
    assert found == set(LIVE_DEFECT_CITATIONS), (
        f"live-defect claims in source: {sorted(found)}; "
        f"registered: {sorted(LIVE_DEFECT_CITATIONS)}")


def test_every_block_cites_its_registered_issue_in_order():
    """Per-BLOCK, not unioned per file: two blocks in one file are two separate obligations."""
    for rel, expected in LIVE_DEFECT_CITATIONS.items():
        cited = _cited((RENDER / rel).read_text(encoding="utf-8"))
        assert cited == expected, f"{rel} cites {cited} in source order, expected {expected}"


def test_the_guard_would_catch_what_it_is_for():
    """The guard's own negative test — an absence assertion that cannot fail is this epic's defect."""
    assert _cited("KNOWN DEFECT, still live — #119. Broken.") == [119]
    # free-wording is a suspect with no canonical match, which the form test turns into a failure
    assert SUSPECT.search("KNOWN DEFECT, remains unresolved.")
    assert not _cited("KNOWN DEFECT, remains unresolved.")
    # two blocks are two obligations, not one
    assert _cited("KNOWN DEFECT, still live — #1. x\nKNOWN DEFECT, still live — #2. y") == [1, 2]
    # history in the past tense is not a live claim
    assert not _cited("This was fixed in #86, and the history is kept.")
