"""The pre-publish lint gate (#12, wave 5).

Its own first honest run found four AA failures in the shipped palette and one bug in
itself, so these tests pin both the checks and the two distinctions the checks exist to
draw: a link is not a request, and a date is not a stamp.
"""
import re
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import render as render_artifact  # noqa: E402
from render import lint  # noqa: E402

STYLES = tuple(n for n in render_artifact._TEMPLATES if n != "plain")


def _page(style="design", body="body text", title="Real Title"):
    return render_artifact.render_artifact(body, title=title, style=style, doc_id="d",
                                           generated_at="2026-08-01 12:00 MDT")


class TestTheEnginePassesItsOwnGate:
    """The point of the gate. If the renderer's own output fails it, the gate is either
    wrong or the design language is — and on the first run it was BOTH."""

    @pytest.mark.parametrize("style", STYLES)
    def test_every_template_lints_clean(self, style):
        assert lint.lint(_page(style)) == []


class TestStamp:
    def test_a_real_page_has_one(self):
        assert lint.check_stamp(_page()) == []

    def test_a_date_in_PROSE_is_not_a_stamp(self):
        """Unanchored, any quoted date satisfies the check and a stamp-less page passes."""
        page = _page(body="We measured this on 2026-08-01 12:00 MDT in the body.")
        stripped = re.sub(r"<footer\b.*?</footer>", "", page, flags=re.S)
        stripped = re.sub(r'<div class="eyebrow">.*?</div>', "", stripped, flags=re.S)
        findings = lint.check_stamp(stripped)
        assert findings and "not in the footer" in findings[0]

    def test_no_stamp_at_all_is_reported_differently(self):
        assert "no America/Edmonton timestamp" in lint.check_stamp("<html></html>")[0]


class TestTitle:
    def test_a_real_title_passes(self):
        assert lint.check_title(_page()) == []

    @pytest.mark.parametrize("bad", ["", "  ", "Untitled", "T", "x"])
    def test_a_placeholder_is_refused(self, bad):
        assert lint.check_title(f"<title>{bad}</title>") != []

    def test_a_missing_title_is_refused(self):
        assert lint.check_title("<html><body>x</body></html>") != []


class TestExternalRequests:
    def test_a_real_page_makes_none(self):
        assert lint.check_external_requests(_page()) == []

    def test_an_anchor_to_an_external_site_is_a_LINK_and_is_allowed(self):
        """Conflating a citation with a fetch fails every page that cites a source."""
        page = _page(body="See [the run](https://github.com/x/y/actions/runs/1).")
        assert '<a href="https://github.com' in page
        assert lint.check_external_requests(page) == []

    @pytest.mark.parametrize("markup", [
        '<img src="https://evil.example/x.png">',
        '<img srcset="https://evil.example/x.png 2x, /ok.png 1x">',
        '<video poster="https://evil.example/p.jpg"></video>',
        '<object data="https://evil.example/o.swf"></object>',
        '<link href="https://evil.example/s.css" rel="stylesheet">',
        '<script src="https://evil.example/x.js"></script>',
        '<svg><use xlink:href="https://evil.example/s.svg#i"/></svg>',
        '<svg><image href="https://evil.example/i.png"/></svg>',
        '<meta http-equiv="refresh" content="0; url=https://evil.example/">',
        '<style>@import "https://evil.example/s.css";</style>',
        '<style>body{background:url(https://evil.example/b.png)}</style>',
        # protocol-relative — the form a first draft missed entirely
        '<img src="//evil.example/x.png">',
        '<style>body{background:url(//evil.example/b.png)}</style>',
        # Reverse solidus (#23). A browser treats `\` as `/` for a special scheme, so
        # `/\host/x` resolves to `//host/x` — verified in Chrome, whose DOM reported the
        # <img> src as http://evil.example/x.png. This gate passed such a page as CLEAN.
        '<img src="/\\evil.example/x.png">',
        '<img src="\\/evil.example/x.png">',
        '<style>body{background:url(/\\evil.example/b.png)}</style>',
        # http as well as https, and a mixed-case scheme: a browser lowercases the scheme, so
        # a guard that only matches lowercase https is not a guard.
        '<img src="http://evil.example/x.png">',
        '<img src="HtTpS://evil.example/x.png">',
        # A TAB/LF/CR inside a quoted attribute value survives HTML parsing and is then
        # REMOVED by the URL parser, so `/<TAB>/host/x` resolves to `//host/x`. Splitting the
        # value on whitespace and classifying only the first token called this internal (#23).
        '<img src="/\t/evil.example/x.png">',
        '<img src="/\n/evil.example/x.png">',
        '<img src="/\r/evil.example/x.png">',
        '<img src="htt\tps://evil.example/x.png">',
        # Leading C0 controls. The URL Standard strips every leading/trailing character up to
        # U+0020 — a set Python's own `.strip()` does NOT cover, so U+0001 was enough to hide
        # the `//host` prefix from the classifier while a browser discards it and fetches.
        '<img src="\x01//evil.example/x.png">',
        '<img src="\x00//evil.example/x.png">',
        '<img src="\x1f//evil.example/x.png">',
        '<img src="//evil.example/x.png\x01">',
    ])
    def test_every_fetching_form_is_caught(self, markup):
        assert lint.check_external_requests(markup) != [], markup

    @pytest.mark.parametrize("markup", [
        '<img src="/local.png">',
        '<img src="./local.png">',
        '<img src="data:image/png;base64,AAAA">',
        # A backslash inside a genuinely relative path is not a host swap: normalising for
        # CLASSIFICATION must not over-refuse `dir\file.png` (#23).
        '<img src="dir\\file.png">',
        '<a href="#section">jump</a>',
        '<svg><use href="#icon"/></svg>',
    ])
    def test_local_and_inline_forms_are_allowed(self, markup):
        assert lint.check_external_requests(markup) == [], markup

    def test_a_finding_names_the_source_text_and_what_it_resolves_to(self):
        """#23: reporting only the normalised value names a string absent from the source, so
        the author cannot find the offending line."""
        found = lint.check_external_requests('<img src="/\t/evil.example/x.png">')
        assert len(found) == 1
        assert "/\\t/evil.example/x.png" in found[0], "the source text must be shown"
        assert "resolves as //evil.example/x.png" in found[0]

    def test_a_long_url_keeps_its_host_visible(self):
        """A plain `[:80]` truncation cuts before the host when the userinfo is long, so the
        finding reads as harmless. Both ends survive clipping instead."""
        long_url = "https://user:" + "p" * 90 + "@evil.example/x.png"
        found = lint.check_external_requests(f'<img src="{long_url}">')
        assert len(found) == 1
        assert "evil.example" in found[0], found[0]


class TestExternalRequestsAreClassifiedOnDecodedValues:
    """#123. One root cause, three symptoms: the gate classified RAW SOURCE TEXT where the
    browser classifies a DECODED value. Filed separately from #23 because each symptom needs a
    real decoder and its own hostile input."""

    @pytest.mark.parametrize("markup", [
        # AC1 — numeric decimal, named, numeric hex, and a MIXED-CASE named form. `&SOL;` is
        # not a valid reference (HTML named refs are case-sensitive), so the mixed-case case
        # uses `&Tab;`/`&NewLine;`, which are real and decode to URL-significant characters
        # the URL parser then removes.
        '<img src="&#47;&#47;evil.example/x">',
        '<img src="&sol;&sol;evil.example/x">',
        '<img src="&#x2f;&#x2f;evil.example/x">',
        '<img src="/&Tab;/evil.example/x">',
        '<img src="/&NewLine;/evil.example/x">',
        # the same gap on every other fetching attribute, not just `src`
        '<img srcset="&#47;&#47;evil.example/x.png 1x">',
        '<video poster="&#47;&#47;evil.example/p.jpg"></video>',
        '<object data="&#47;&#47;evil.example/o.swf"></object>',
        '<link href="&#47;&#47;evil.example/s.css" rel="stylesheet">',
        '<svg><use xlink:href="&#47;&#47;evil.example/s.svg#i"/></svg>',
        '<svg><image href="&#47;&#47;evil.example/i.png"/></svg>',
        '<meta http-equiv="refresh" content="0; url=&#47;&#47;evil.example/">',
        # a character reference can also hide a whole scheme
        '<img src="&#104;ttps://evil.example/x.png">',
    ])
    def test_a_character_reference_in_an_html_attribute_is_decoded(self, markup):
        """A browser decodes character references while parsing the attribute, THEN resolves the
        result. Classifying the raw `&`-prefixed text calls `&#47;&#47;host` internal."""
        assert lint.check_external_requests(markup) != [], markup

    @pytest.mark.parametrize("markup", [
        # AC2 — CSS consumes escaped code points before URL resolution. Short and long hex
        # forms, with and without the escape's optional trailing space.
        '<style>body{background:url(\\2f\\2f evil.example/x)}</style>',
        '<style>body{background:url(\\00002f\\00002f evil.example/x)}</style>',
        # the escape's trailing space is OPTIONAL — but only when the next character cannot
        # continue the hex run, so the host here starts with a non-hex letter.
        '<style>body{background:url(\\2f\\2fzevil.example/x)}</style>',
        '<style>@import "\\2f\\2f evil.example/s.css";</style>',
        '<style>@import url(\\2f\\2f evil.example/s.css);</style>',
        # the scheme itself escaped
        '<style>body{background:url(\\68 ttps://evil.example/x)}</style>',
    ])
    def test_a_css_escape_is_decoded(self, markup):
        assert lint.check_external_requests(markup) != [], markup

    @pytest.mark.parametrize("markup", [
        # AC3 — the asymmetry, pinned. Inside a <style> block the content is RAW TEXT: the HTML
        # parser does not decode character references there, so `&#47;&#47;host` is literally
        # those characters to the CSS parser and fetches nothing. A single "decode everything"
        # pass would flag these and be wrong.
        '<style>body{background:url(&#47;&#47;evil.example/x)}</style>',
        '<style>@import "&#47;&#47;evil.example/s.css";</style>',
        '<style>body{background:url(&sol;&sol;evil.example/x)}</style>',
    ])
    def test_character_references_are_NOT_decoded_in_raw_stylesheet_text(self, markup):
        assert lint.check_external_requests(markup) == [], markup

    @pytest.mark.parametrize("markup", [
        # AC4 — the two false POSITIVES. A browser collects each srcset URL up to ASCII
        # whitespace, so a comma can belong to the URL itself. Both of these make no external
        # request, and the comma-split gate refused to publish them.
        '<img srcset="/asset,//evil.example/x.png 1x">',
        '<img srcset="data:application/octet-stream;base64,//8= 1x">',
        # a data: URI's mandatory comma, with a descriptor and a sibling candidate
        '<img srcset="data:image/png;base64,AAAA 1x, /local.png 2x">',
        # separator commas with irregular spacing are still separators
        '<img srcset="/a.png 1x ,  /b.png 2x">',
        '<img srcset=",/a.png 1x,,/b.png 2x,">',
    ])
    def test_a_comma_inside_a_srcset_url_is_part_of_the_url(self, markup):
        assert lint.check_external_requests(markup) == [], markup

    @pytest.mark.parametrize("markup", [
        # AC4, the other direction: real external candidates in srcset still fail, wherever
        # they sit in the candidate list.
        '<img srcset="//evil.example/x.png 1x">',
        '<img srcset="/ok.png 1x, //evil.example/x.png 2x">',
        '<img srcset="/ok.png 1x, https://evil.example/x.png 2x, /ok2.png 3x">',
        '<img srcset="/asset,//ok-same-origin.png 1x, //evil.example/x.png 2x">',
    ])
    def test_a_real_external_srcset_candidate_still_fails(self, markup):
        assert lint.check_external_requests(markup) != [], markup

    @pytest.mark.parametrize("markup", [
        # PROSE IS NOT A STYLESHEET. Scanning the whole document for `url()` classified text as
        # CSS. Nothing fetches a url inside a <code> span, and this repo's own campaign log
        # documents both of these forms verbatim — so the gate refused to publish the very
        # document describing the defect (#123).
        '<p><code>url(https://evil.example/x)</code></p>',
        '<p><code>url(\\2f\\2f evil.example/x)</code></p>',
        '<p>write it as <code>@import "https://evil.example/s.css"</code> to see it fail</p>',
        '<pre>body{background:url(//evil.example/b.png)}</pre>',
        # Step 11's High finding: a regex for `style="…"` matched this prose too, so a page
        # merely DOCUMENTING an inline style was refused. As markup it is character data inside
        # <code>, not an attribute on any element.
        '<p><code>style="background:url(https://evil.example/x)"</code></p>',
        '<p>never write <code>style=background:url(//evil.example/x)</code></p>',
    ])
    def test_css_syntax_quoted_in_prose_is_not_a_fetch(self, markup):
        assert lint.check_external_requests(markup) == [], markup

    @pytest.mark.parametrize("markup", [
        # A `style=` ATTRIBUTE is a real CSS context, and unlike a <style> block its value IS
        # html-decoded before CSS sees it — so a character reference there really does fetch.
        '<div style="background:url(https://evil.example/b.png)">x</div>',
        '<div style="background:url(//evil.example/b.png)">x</div>',
        '<div style="background:url(&#47;&#47;evil.example/b.png)">x</div>',
        '<div style="background:url(\\2f\\2f evil.example/b.png)">x</div>',
    ])
    def test_an_inline_style_attribute_is_a_css_context(self, markup):
        assert lint.check_external_requests(markup) != [], markup

    @pytest.mark.parametrize("markup", [
        # Step 11 found these: scoping CSS to REGEX-extracted regions opened three fail-open
        # holes the old whole-document scan had covered. Every one of them is a real published
        # external request, and every one was CAUGHT on the parent commit — so they are
        # regressions, not pre-existing gaps. A regex cannot tokenise HTML; the stdlib parser
        # decides what is CSS.
        #
        # 1. an UNQUOTED attribute value has no quote for a `["']` capture to pair with
        '<div style=background:url(//evil.example/x)>x</div>',
        '<div style=background:url(https://evil.example/x) class=y>x</div>',
        # 2. a single quote INSIDE a double-quoted value ended the capture early
        '<div style="background:url(\'//evil.example/x\')">x</div>',
        "<div style='background:url(\"//evil.example/x\")'>x</div>",
        # 3. an end tag may carry whitespace before `>`, so the raw-text element still closes
        '<style>body{background:url(//evil.example/x)}</style >',
        '<style>body{background:url(//evil.example/x)}</STYLE >',
        '<style>@import "//evil.example/s.css";</style\t>',
    ])
    def test_the_css_region_scoping_did_not_open_a_fail_open_hole(self, markup):
        assert lint.check_external_requests(markup) != [], markup

    def test_an_unparseable_page_fails_closed(self):
        """If the tokeniser ever cannot read a page, the gate must over-refuse rather than admit
        an unexamined stylesheet. Verified through the real entry point, not by faking it."""
        assert lint.check_external_requests(
            '<style>body{background:url(//evil.example/x)}') != []

    def test_an_attribute_value_is_not_decoded_twice(self):
        """The tokeniser already HTML-decodes attribute values. Decoding again would resolve
        `&amp;#47;` — an author's literal `&#47;` text — into a slash that was never there."""
        assert lint.check_external_requests(
            '<div style="background:url(&amp;#47;&amp;#47;evil.example/x)">x</div>') == []

    def test_a_style_block_and_a_style_attribute_disagree_on_character_references(self):
        """The asymmetry in one assertion, because it is the easiest thing here to 'simplify'
        into a single decode pass. Same bytes, opposite correct answers."""
        css = "url(&#47;&#47;evil.example/x)"
        assert lint.check_external_requests(f"<style>body{{background:{css}}}</style>") == []
        assert lint.check_external_requests(f'<div style="background:{css}">x</div>') != []

    def test_a_hex_run_is_not_cut_short_to_manufacture_a_slash(self):
        """The decoder must not be MORE eager than CSS. `url(\\2f\\2fevil.example/x)` looks like
        `//evil...` but `2fe` are three hex digits, so the second escape is U+02FE and the value
        is `/˾vil.example/x` — same-origin, and a browser fetches nothing external. Written as a
        test because the first draft of this suite asserted the opposite and the code was right.
        """
        assert lint.check_external_requests(
            '<style>body{background:url(\\2f\\2fevil.example/x)}</style>') == []

    def test_the_decoders_do_not_swallow_a_reverse_solidus_that_23_catches(self):
        """The regression this fix would otherwise cause, pinned deliberately.

        CSS-unescaping `/\\evil.example/b.png` consumes `\\e` as a one-digit hex escape and
        yields `/\\x0evil.example/b.png` — no `//` prefix, so a decode-then-classify gate reads
        it as INTERNAL and #23's catch silently disappears. Classifying EVERY interpretation
        (raw and decoded) and refusing if any one is external is what keeps both.
        """
        assert lint.check_external_requests(
            '<style>body{background:url(/\\evil.example/b.png)}</style>') != []
        assert lint.check_external_requests('<img src="/\\evil.example/x.png">') != []

    def test_a_finding_still_names_the_source_text(self):
        """A decoded-only message names a string absent from the page (#23's lesson)."""
        found = lint.check_external_requests('<img src="&#47;&#47;evil.example/x">')
        assert len(found) == 1
        assert "&#47;&#47;evil.example/x" in found[0], found[0]
        assert "resolves as //evil.example/x" in found[0], found[0]


class TestContrast:
    def test_the_maths_matches_known_wcag_values(self):
        assert round(lint.contrast("#000000", "#ffffff"), 2) == 21.0
        assert round(lint.contrast("#ffffff", "#ffffff"), 2) == 1.0
        assert round(lint.contrast("#767676", "#ffffff"), 1) == 4.5   # the canonical AA edge

    def test_light_and_dark_are_read_from_their_OWN_blocks(self):
        """A bare `:root{` regex also matches the one nested inside the dark media query,
        so light was silently scored with dark values — both themes reported identically,
        which is what gave the bug away."""
        css = re.search(r"<style>(.*?)</style>", _page(), re.S).group(1)
        tokens = lint.theme_tokens(css)
        assert set(tokens) == {"light", "dark"}
        assert tokens["light"]["--bg"] != tokens["dark"]["--bg"]

    def test_a_failing_pair_is_reported_with_its_ratio(self):
        css = ("<style>:root[data-theme=light]{--ink:#cccccc;--bg:#ffffff}"
               ":root[data-theme=dark]{--ink:#111111;--bg:#000000}</style>")
        findings = lint.check_contrast(css)
        assert any("--ink on --bg" in f and "below 4.5" in f for f in findings)

    def test_every_declared_token_is_classified_in_the_pair_table(self):
        """The gap the enumerated table would otherwise leave: a NEW token would simply
        not be checked, silently. This turns that into a red suite instead."""
        declared = set()
        for block in (render_artifact._STYLE, render_artifact._COMPONENT_STYLE,
                      render_artifact._ROADMAP_STYLE):
            declared |= set(re.findall(r"(--[a-z0-9-]+)\s*:\s*#", block))
        classified = {t for pair in lint.PAIRS for t in pair[:2]}
        assert declared <= classified, (
            f"unclassified token(s) {sorted(declared - classified)} — add them to "
            f"lint.PAIRS with the threshold that applies and why")


# --------------------------------------------------------------------------- #127

CALLOUT = ("intro\n\n```callout\nwarn | Read this first\nOne real component.\n```\n")


class TestBlocks:
    """#127. A styled page carrying none of its style's components is prose wearing a
    template's CSS. `rawgentic-plan-756` published exactly that: `class="tpl-roadmap"`,
    zero components, 44 KB — while the composition meter it should have used had been
    merged twelve hours earlier. The renderer had the devices; the document never asked
    for them, and nothing objected.
    """

    @pytest.mark.parametrize("style", STYLES)
    def test_a_prose_only_styled_page_is_refused(self, style):
        assert lint.check_blocks(_page(style)), (
            f"{style} rendered with no components at all and nothing objected")

    def test_one_real_block_is_enough(self):
        """A floor, not a proof. #130 is the strict version that asks for the style's own
        first-read device rather than merely one of anything."""
        assert lint.check_blocks(_page("roadmap", body=CALLOUT)) == []

    def test_the_block_CSS_is_not_mistaken_for_block_markup(self):
        """The trap this check was nearly built on, and the reason it is pinned by name.
        Every template ships its block CSS unconditionally, so a PROSE-ONLY roadmap page
        carries ~148 `blk-` strings inside <style>. Counting the document would have made
        this a gate that can never fail — shipped green, useless. Same region-scanning
        error as #90/#119 (the h2 chip reading typed-block content) and #123 (raw source
        vs the value a browser resolves); third time in this neighbourhood."""
        page = _page("roadmap")
        assert page.count("blk-") > 100, "the block CSS is supposed to be there"
        assert lint.check_blocks(page) != [], "the CSS was counted as markup"

    @pytest.mark.parametrize("body,title", [
        ("body text", "How blk-callout works"),                       # in the title
        ("The renderer reserves the `blk-callout` class.", "Real Title"),   # in prose
        ("```\n.blk-example { color: red }\n```\n", "Real Title"),     # in a CSS sample
    ])
    def test_merely_MENTIONING_a_block_class_is_not_carrying_one(self, body, title):
        """Cross-model review, first pass (gpt-5.6-sol): the first version of this check was
        a raw substring search, and all three of these published clean with zero components
        — measured, not theorised. A doc ABOUT the block vocabulary is the likeliest page in
        this repo to trip it, so the check matches a class TOKEN.
        """
        page = _page("roadmap", body=body, title=title)
        assert lint.check_blocks(page), f"{title!r}/{body[:20]!r} slipped through"

    def test_plain_is_exempt_by_construction(self):
        """`plain` is the one style that emits no body class (`render/__init__.py:647`),
        so "carries a tpl- class" IS the definition of styled. No exemption list to go
        stale, and `plain` is frozen and byte-identical by contract."""
        assert lint.check_blocks(_page("plain")) == []

    def test_a_page_the_engine_never_drew_is_exempt(self):
        """Hand-rolled and pre-engine HTML carries no template class. Six of fourteen
        published pages sampled on 2026-08-03 were exactly that (#128). Refusing them
        would refuse every page this engine did not produce."""
        assert lint.check_blocks("<html><body><p>hand-rolled</p></body></html>") == []

    def test_it_is_NOT_one_of_the_page_quality_checks(self):
        """Deliberate architecture, and the reason it is asserted rather than commented.

        `check_blocks` is a PUBLISH policy, not a rendering defect: rendering a page with
        no components is the renderer correctly rendering what it was given. `lint()` is
        asserted `== []` at twelve sites (here and across test_vdl_packs.py) on
        prose-only fixtures, and `TestTheEnginePassesItsOwnGate` exists to prove the
        engine's own output passes its own gate. Adding this to `CHECKS` would break all
        of that and would assert the engine is broken for doing its job.
        """
        assert "blocks" not in dict(lint.CHECKS)
        assert lint.lint(_page("roadmap")) == []


# --------------------------------------------------------------------------- #130

# One real block of each device this suite needs, in the grammar of
# `docs/typed-blocks-grammar.md`. Built from the doc's own examples so a grammar change
# breaks these loudly rather than silently rendering a code listing.
FENCE = {
    "stats":    "```stats\n82 | sessions read\n```\n",
    "callout":  "```callout\nwarn | Read this first\nOne real component.\n```\n",
    "phases":   "```phases\nWave 1 | 3 of 12 done | warn\n  FA-1 | Fan curve stalls | crit\n```\n",
    "timeline": "```timeline\n09:14 | Alert fires | Error rate crosses 2% | past\n```\n",
    "options":  "```options\nDebounce | Smallest diff | Re-done per call site | chosen\n```\n",
    "chips":    "```chips\nmerged | done\n```\n",
    "findings": "```findings\nhigh | Emphasis ran over markup | A tag landed in an href.\n```\n",
    "steps":    "```steps\n1 | Author the grammar | One real page per type.\n```\n",
    "meter":    "```meter\nChildren merged | 3 | 9\n```\n",
    "legend":   "```legend\ndone | shipped and verified on main\n```\n",
    "steprail": "```steprail\n1 | Fetch at the pinned SHA | A moving ref races. | action\n```\n",
    "flow":     "```flow\nterm | A request arrives\nproc | Validate the token\n```\n",
    # #149: module-map's first-read set requires `nodes`.
    "nodes":    "```nodes\nrender\n  markdown | the block and inline parser\n```\n",
    # #59: minutes is the first style whose first-read set requires `verdict`, so this
    # parametrized suite asked for a sample fence the dict had never needed and raised
    # KeyError. Caught by the full suite, not by any scoped run.
    "verdict":  "```verdict\ndecided | Cap carrier retries before the peak.\n```\n",
}


def _with(tags):
    return "intro\n\n" + "\n".join(FENCE[t] for t in tags)


def _devices(style):
    from render import blocks
    return blocks.FIRST_READ_DEVICES[style]


# Every style that actually carries a requirement.
DEVICE_STYLES = sorted(
    s for s, req in __import__("render.blocks", fromlist=["blocks"]).FIRST_READ_DEVICES.items()
    if req)


class TestStyleDevices:
    """#130. `check_blocks` is a floor — one component of ANY kind clears it. This is the
    strict check: a styled page must carry every device its own style OPENS with, read from
    the first-read column of `design-language.md` via `blocks.FIRST_READ_DEVICES`.

    Owner decision 2026-08-05: ALL of a style's documented devices, not merely one. The
    conjunctive reading is what the source column says ("stat strip + a READ THIS FIRST
    callout stack, then the phase rail").
    """

    @pytest.mark.parametrize("style", DEVICE_STYLES)
    def test_a_page_with_every_device_passes(self, style):
        page = _page(style, body=_with(sorted(_devices(style))))
        assert lint.check_style_devices(page) == []

    @pytest.mark.parametrize("style", DEVICE_STYLES)
    def test_dropping_one_device_is_a_finding(self, style):
        """The can-it-fail half. Each style is driven with every device but one, so a
        requirement that silently parsed to the empty set cannot look like a pass.

        A FILLER block the style does not require is always present, for two reasons: it
        keeps `design` and `uat` — which require exactly one device each — inside this
        check's domain rather than falling through to `check_blocks`'s zero-block case,
        and it makes the assertion stronger everywhere else by proving the finding fires
        on a page that genuinely carries components.
        """
        required = sorted(_devices(style))
        filler = next(t for t in FENCE if t not in required)
        for dropped in required:
            kept = [t for t in required if t != dropped]
            page = _page(style, body=_with(kept + [filler]))
            findings = lint.check_style_devices(page)
            assert findings, f"{style} without `{dropped}` published clean"
            assert dropped in findings[0], f"the finding does not name `{dropped}`"
            assert style in findings[0], "the finding does not name the style"

    @pytest.mark.parametrize("style", ["design", "uat"])
    def test_a_single_device_style_with_NO_blocks_falls_to_check_blocks(self, style):
        """The two styles requiring exactly one device. Dropping it leaves zero blocks,
        which is `check_blocks`'s case — pinned so the hand-off stays deliberate and one
        publish failure never reads as two."""
        page = _page(style, body="prose only")
        assert lint.check_blocks(page) != []
        assert lint.check_style_devices(page) == []

    def test_it_names_every_missing_device_at_once(self):
        page = _page("workflow", body=_with(["legend"]))
        finding = lint.check_style_devices(page)[0]
        assert "flow" in finding and "steprail" in finding, \
            "a reader fixing one device at a time needs the whole list"

    # --- disjoint from check_blocks -------------------------------------------------

    def test_a_page_with_NO_blocks_is_left_to_check_blocks(self):
        """Exactly one of the two ever fires. A zero-block page is `check_blocks`'s case and
        it says it better; reporting both would make one publish failure read as two."""
        page = _page("roadmap")
        assert lint.check_blocks(page) != []
        assert lint.check_style_devices(page) == []

    def test_a_page_with_a_wrong_block_is_left_to_THIS_check(self):
        """The exact hole #130 was filed for: `chips` satisfies the floor, and the page
        still opens with none of roadmap's own devices."""
        page = _page("roadmap", body=_with(["chips"]))
        assert lint.check_blocks(page) == []
        assert lint.check_style_devices(page) != []

    # --- the exemptions, each pinned ------------------------------------------------

    def test_plain_is_exempt_by_construction(self):
        assert lint.check_style_devices(_page("plain", body=_with(["chips"]))) == []

    def test_a_page_the_engine_never_drew_is_exempt(self):
        assert lint.check_style_devices(
            '<html><body><p class="blk-chips">hand-rolled</p></body></html>') == []

    def test_a_structural_style_requires_nothing(self):
        """`analysis` opens with `.an-answer`, which the renderer builds from the first
        paragraph. An author cannot omit it, so there is nothing to require — and that must
        be a STATEMENT, which is why the doc spells it `none (structural)`."""
        assert lint.check_style_devices(_page("analysis", body=_with(["chips"]))) == []

    @pytest.mark.parametrize("style", ["design-system", "module-map", "slide-deck"])
    def test_the_last_three_styles_are_no_longer_un_opinionated(self, style):
        """#149 gave them a documented first-read element, so they are gated like the rest.
        This test asserted the OPPOSITE until then — it is inverted rather than deleted,
        because "these three are exempt" is exactly the claim that stopped being true."""
        from render import blocks
        assert style in blocks.FIRST_READ_DEVICES
        assert blocks.FIRST_READ_DEVICES[style], f"{style} parsed to an empty requirement"
        # A page carrying a block the style accepts but does not open with is now refused.
        filler = next(t for t in FENCE if t not in blocks.FIRST_READ_DEVICES[style])
        assert lint.check_style_devices(_page(style, body=_with([filler]))) != []

    def test_no_style_is_left_un_opinionated(self):
        """`UNDOCUMENTED_FIRST_READ` is empty as of #149. Kept as the declared home for the
        next template added without a row, so the completeness test can still refuse it."""
        from render import blocks
        assert blocks.UNDOCUMENTED_FIRST_READ == frozenset()

    # --- fail closed ----------------------------------------------------------------

    def test_an_UNKNOWN_template_class_is_a_finding(self):
        """Cross-model design review, and it overturned my own decline. I had reasoned that
        the suite's completeness test made an unclassified template unshippable — but that
        test classifies REGISTRY ENTRIES, this gate reads the class in RENDERED HTML, and
        the suite does not run at publish time. A renderer defect or an altered page could
        present a class no test ever saw and be waved through by the check meant to catch
        it."""
        page = _page("roadmap", body=_with(["chips"])).replace(
            'class="tpl-roadmap"', 'class="tpl-roadmapp"')
        findings = lint.check_template_classification(page)
        assert findings and "tpl-roadmapp" in findings[0]
        assert lint.check_style_devices(page) == [], \
            "each condition is reported by exactly one check"

    def test_MORE_THAN_ONE_template_class_is_a_finding(self):
        page = _page("roadmap", body=_with(sorted(_devices("roadmap")))).replace(
            "</body>", '<body class="tpl-spec"></body></body>')
        findings = lint.check_template_classification(page)
        assert findings, "two <body> classes let class ORDER decide whether a page passes"
        assert "roadmap" in findings[0] and "spec" in findings[0]

    def test_the_multiple_class_finding_does_not_depend_on_order(self):
        both = [_page("roadmap", body=_with(sorted(_devices("roadmap")))).replace(
                    "</body>", '<body class="tpl-spec"></body></body>'),
                _page("spec", body=_with(sorted(_devices("spec")))).replace(
                    "</body>", '<body class="tpl-roadmap"></body></body>')]
        assert all(lint.check_template_classification(p) for p in both)

    @pytest.mark.parametrize("style", DEVICE_STYLES + ["plain", "analysis"])
    def test_classification_is_silent_on_every_real_page(self, style):
        """The structural check must never fire on output this engine actually produces."""
        assert lint.check_template_classification(_page(style)) == []

    def test_a_page_the_engine_never_drew_is_not_misread_as_unknown(self):
        assert lint.check_template_classification("<html><body><p>x</p></body></html>") == []

    def test_an_undocumented_but_classified_style_is_silent(self):
        assert lint.check_template_classification(_page("module-map")) == []

    # --- the traps `check_blocks` already paid for ----------------------------------

    def test_a_sub_element_class_does_not_satisfy_a_requirement(self):
        """MEASURED, not theorised: probing the 13 committed pages with a loose
        `blk-([a-z]+)` returned `chip`, `step`, `finding`, `row`, `fill`, `lbl` … — a
        block's INNER elements. `blk-chip` sits inside `blk-chips`. Left unfiltered it
        would satisfy a `chips` requirement outright."""
        page = _page("dashboard", body=_with(["stats"]))
        page = page.replace("</body>", '<p class="blk-chip">not a chips block</p></body>')
        findings = lint.check_style_devices(page)
        assert findings and "chips" in findings[0]

    @pytest.mark.parametrize("body,title", [
        ("body text", "How blk-phases works"),
        ("The renderer reserves the `blk-phases` class.", "Real Title"),
        ("```\n.blk-phases { color: red }\n```\n", "Real Title"),
    ])
    def test_merely_MENTIONING_a_device_class_is_not_carrying_one(self, body, title):
        """The three payloads that defeated the first version of `check_blocks` (#127,
        found by cross-model review). A doc ABOUT the vocabulary is the likeliest page in
        this repo to trip it."""
        page = _page("roadmap", body=_with(["stats", "callout"]) + "\n" + body, title=title)
        findings = lint.check_style_devices(page)
        assert findings and "phases" in findings[0]

    def test_the_block_CSS_is_not_mistaken_for_block_markup(self):
        page = _page("roadmap", body=_with(["stats", "callout"]))
        assert page.count("blk-") > 100, "the block CSS is supposed to be there"
        assert lint.check_style_devices(page), "the CSS was counted as markup"

    # --- architecture ----------------------------------------------------------------

    def test_it_is_NOT_one_of_the_page_quality_checks(self):
        """Same reason as `check_blocks`: a publish POLICY, not a rendering defect.
        `lint()` is asserted `== []` on prose-only fixtures at twelve sites."""
        assert "style-devices" not in dict(lint.CHECKS)
        assert lint.lint(_page("roadmap")) == []

    # --- the two gaps the inline review of this change found -------------------------

    def test_a_sub_element_ONLY_page_is_examined_by_THIS_check(self):
        """The hand-off gap, found by probing this module against itself.

        `check_blocks` is satisfied by ANY `blk-` class, filtered against nothing. An
        earlier version of `check_style_devices` returned early on "no recognised block
        TAGS", which is strictly narrower — so a page carrying only a sub-element class
        cleared the first check and was skipped by the second, and NEITHER examined it.
        Both now branch on the same predicate, so they cannot disagree about ownership.
        """
        page = ('<html><head><style>.blk-x{}</style></head><body class="tpl-roadmap">'
                '<p class="blk-chip">only a sub-element</p></body></html>')
        assert lint.check_blocks(page) == [], "check_blocks is satisfied by any blk- class"
        findings = lint.check_style_devices(page)
        assert findings, "a page no check examines is a gate that does not gate"
        assert "phases" in findings[0] and "stats" in findings[0]

    @pytest.mark.parametrize("cls", [
        # `\\b` treats `-` as a boundary, so these captured their parent's name.
        "blk-steps-inner", "blk-stats-row", "blk-phases-x",
        # These defeated the `(?![a-z-])` patch that fixed the three above, because it
        # excluded only lowercase letters and hyphens. Found by the pre-PR review, and the
        # reason detection now tokenises the class attribute instead of tuning a lookahead.
        "blk-steps_", "blk-steps2", "blk-stepsX", "blk-steps.", "blk-steps:x",
    ])
    def test_a_NEAR_MISS_class_token_does_not_impersonate_a_real_one(self, cls):
        """Only an exact `blk-<tag>` class token counts. Three rounds of boundary-tuning
        each left another spoofable suffix; tokenising the attribute ends the family."""
        page = (f'<html><body class="tpl-spec"><p class="blk-chips">c</p>'
                f'<p class="{cls}">x</p></body></html>')
        findings = lint.check_style_devices(page)
        assert findings, f"{cls} satisfied a requirement it does not carry"
        assert "steps" in findings[0]

    def test_TWO_IDENTICAL_body_classes_are_caught(self):
        """Pre-PR review: deduplicating the matches first was itself fail-open. Two
        `<body class="tpl-roadmap">` elements collapsed to one entry and passed as a single
        well-formed page — while a document with two bodies can spread its required devices
        across them and satisfy the gate carrying neither properly."""
        page = _page("roadmap", body=_with(sorted(_devices("roadmap")))).replace(
            "</body>", '<body class="tpl-roadmap"></body></body>')
        findings = lint.check_template_classification(page)
        assert findings, "two identical body classes deduplicated into one"
        assert "2 elements" in findings[0]
        assert lint.check_style_devices(page) == [], "classification owns this condition"

    def test_required_devices_cannot_be_split_across_two_bodies(self):
        """The reason the count matters rather than the class names: each body alone is
        incomplete, and only their union satisfies roadmap."""
        page = _page("roadmap", body=_with(["stats", "callout"])).replace(
            "</body>", '<body class="tpl-roadmap"><p class="blk-phases">p</p></body></body>')
        assert lint.check_template_classification(page), \
            "the union of two bodies must not satisfy one page's requirement"


class TestStyleDiscoveryTokenises:
    """#150. Style discovery used to require `tpl-<style>` to be the ENTIRE double-quoted
    lowercase `class` value, so every shape below produced no match — and a page with no
    match is treated as one this engine never drew, i.e. exempt from EVERY component check.

    Measured before the change (recorded in #150's body): all four were silently exempt.
    Raised twice by cross-model review during #130 and declined both times with a stated
    reason — the matcher is shared with `check_blocks`, so #130 put it out of scope. This is
    that scope.
    """

    ALL = ("intro\n\n```stats\n82 | children merged\n```\n\n"
           "```callout\nwarn | Read this first\nOne real component.\n```\n\n"
           "```phases\nWave 1 | 3 of 12 | warn\n  FA-1 | Stalls | crit\n```\n")

    @pytest.mark.parametrize("body_tag,expected", [
        ('<body class="theme tpl-roadmap">', ["roadmap"]),      # tpl- not first
        ('<body class="tpl-roadmap extra">', ["roadmap"]),       # not the whole value
        ('<BODY class="tpl-roadmap">',       ["roadmap"]),       # uppercase tag
        ("<body class='tpl-roadmap'>",       ["roadmap"]),       # single quotes
        ('<body class=tpl-roadmap>',         ["roadmap"]),       # unquoted
        ('<body  CLASS = "a tpl-roadmap b" >', ["roadmap"]),     # spacing + attr case
        ('<body class="tpl-roadmap tpl-spec">', ["roadmap", "spec"]),  # two on one body
        ('<body>',                           []),                # plain / hand-rolled
        ('<body class="theme">',             []),                # classes but no template
    ])
    def test_every_shape_is_discovered(self, body_tag, expected):
        assert lint.template_styles(f"<html>{body_tag}<p>x</p></body></html>") == expected

    def test_a_styled_page_with_an_extra_class_is_no_longer_silently_exempt(self):
        """The whole point. Before #150 this page passed both component checks."""
        page = _page("roadmap").replace('class="tpl-roadmap"', 'class="theme tpl-roadmap"')
        assert lint.check_blocks(page), "a prose-only roadmap was exempt because of one extra class"

    def test_the_same_page_carrying_its_devices_still_passes(self):
        page = _page("roadmap", body=self.ALL).replace(
            'class="tpl-roadmap"', 'class="theme tpl-roadmap"')
        assert lint.check_blocks(page) == []
        assert lint.check_style_devices(page) == []
        assert lint.check_template_classification(page) == []

    def test_a_malformed_near_miss_is_an_unknown_class_not_an_exemption(self):
        """`tpl-roadmap2` used to match nothing and vanish. Now it is a named unknown."""
        page = _page("roadmap", body=self.ALL).replace("tpl-roadmap", "tpl-roadmap2")
        findings = lint.check_template_classification(page)
        assert findings and "tpl-roadmap2" in findings[0]

    def test_a_page_the_engine_never_drew_is_STILL_exempt(self):
        """Load-bearing: six of fourteen published pages sampled 2026-08-03 were hand-rolled
        or pre-engine (#128). Widening discovery must not start refusing them."""
        for page in ("<html><body><p>hand-rolled</p></body></html>",
                     '<html><body class="wrapper"><p class="blk-chips">x</p></body></html>'):
            assert lint.template_styles(page) == []
            assert lint.check_blocks(page) == []
            assert lint.check_style_devices(page) == []
            assert lint.check_template_classification(page) == []

    def test_two_bodies_are_still_counted_separately(self):
        page = ('<html><body class="a tpl-roadmap"><p class="blk-stats">s</p></body>'
                "<body class='tpl-spec'></body></html>")
        assert lint.template_styles(page) == ["roadmap", "spec"]
        assert lint.check_template_classification(page)

    @pytest.mark.parametrize("style", STYLES)
    def test_every_real_rendered_page_is_still_discovered(self, style):
        """Regression floor: the widening must not change what the engine's own output reports."""
        assert lint.template_styles(_page(style)) == [style]

    def test_plain_reports_no_style(self):
        assert lint.template_styles(_page("plain")) == []

    # --- the four defects the inline probe found in the first regex version -----------

    def test_a_quoted_ATTRIBUTE_VALUE_containing_a_gt_does_not_hide_the_class(self):
        """THE FAIL-OPEN, and the only one of the four that mattered in the dangerous
        direction. `<body\\b[^>]*>` stopped at the `>` inside the quoted title, so the class
        was never seen and a genuinely styled page escaped all three component checks."""
        page = '<html><body title="a>b" class="tpl-roadmap"><p>x</p></body></html>'
        assert lint.template_styles(page) == ["roadmap"]
        assert lint.check_blocks(page), "a styled page slipped past the gate entirely"

    def test_a_data_class_attribute_is_not_a_class_attribute(self):
        """`\\bclass` matched the tail of `data-class` — `\\b` sits happily between `-` and `c`
        — so a page with no template class was gated as though it had one."""
        assert lint.template_styles(
            '<html><body data-class="tpl-roadmap"><p>x</p></body></html>') == []

    def test_a_template_class_inside_an_HTML_COMMENT_is_not_markup(self):
        assert lint.template_styles(
            '<html><!-- <body class="tpl-roadmap"> --><body><p>x</p></body></html>') == []

    def test_a_template_class_inside_another_attribute_value_is_not_markup(self):
        assert lint.template_styles(
            '<html><body><p title=\'<body class="tpl-roadmap">\'>x</p></body></html>') == []

    @pytest.mark.parametrize("html", [
        '<html><body><p>the string &lt;body class="tpl-roadmap"&gt; in prose</p></body></html>',
        '<html><body classy="tpl-roadmap"><p>x</p></body></html>',
        '<html><body class="tpl-"><p>x</p></body></html>',          # a bare prefix is not a style
    ])
    def test_near_misses_report_no_style(self, html):
        assert lint.template_styles(html) == []

    def test_a_character_reference_in_the_class_is_decoded_like_a_browser_would(self):
        """`convert_charrefs` gives the value a browser sees: `tpl-roadmap&#32;x` is two
        tokens, the first of which is the style."""
        assert lint.template_styles(
            '<html><body class="tpl-roadmap&#32;x"><p>y</p></body></html>') == ["roadmap"]

    def test_unparseable_input_fails_CLOSED_not_open(self):
        """The fallback over-classifies rather than exempting, because an exemption is the
        failure this function exists to prevent."""
        assert lint.template_styles('<html><body class="tpl-roadmap"><p>x') == ["roadmap"]
