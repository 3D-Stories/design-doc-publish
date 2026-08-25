#!/usr/bin/env python3
"""Render the docs-index page from a derived listing, instead of hand-editing it.

Why derived rather than edited (owner decision 2026-08-01): hand-editing carried a real
lost-row race — two concurrent publishes both fetch version N, each appends its own row, and
the second silently overwrites the first with no conflict and no error. This workspace runs
concurrent sessions and hit that race class on another file the same week. Deriving removes
the shared mutable file entirely, so there is nothing to race on.

The harness is the one caller: `harness/indexpage.py` builds the row snapshot by walking the
GitHub repositories (`harness/convention.py:ConventionIndex`) and this module renders it.
The standalone CLI that used to walk the retired hosting vendor's project list is gone.

Every count on the page is computed here. None may be hand-edited.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# The index groups by rawgentic project. `workspace-` is the cross-project bucket.
WORKSPACE_GROUP = "workspace"
PURPOSES = ("design", "plan", "uat", "audit", "report", "runbook", "analysis", "spec", "review")
DEFAULT_PURPOSE = "doc"

# #14: group colours are NOT defined here any more. A project's colour is resolved by
# `scripts/vdl_packs.py`, which the renderer also calls — that shared answer is the only
# thing making the index swatches and the pages agree (AC6). Re-adding a literal table
# here would restore exactly the drift this deleted, and a test now fails if one appears.
def _vdl_packs():
    import importlib.util
    root = Path(__file__).resolve().parent.parent / "scripts"
    path = root / "vdl_packs.py"
    # Containment, duplicated deliberately at each of the three load sites. A shared
    # helper would itself have to be loaded the same way, so the guard cannot live behind
    # the thing it guards. `render-doc` documents the full reasoning: a symlinked target
    # is EXECUTED before any check can reject it, so the check must precede the load.
    real = path.resolve()
    if not real.is_file() or not real.is_relative_to(root):
        raise RuntimeError(f"refusing to load {path}: resolves to {real}, outside {root}")
    spec = importlib.util.spec_from_file_location("_index_vdl_packs", real)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _user_config():
    """`scripts/user_config.py`, loaded the same guarded way as `vdl_packs` (#9).

    Containment duplicated here on purpose, exactly as the comment above says: a shared
    helper would itself have to be loaded this way, so the guard cannot live behind the
    thing it guards. This module used to decide which account a public page reaches, which
    makes a `sys.path` hijack of it worse than most.
    """
    import importlib.util
    root = Path(__file__).resolve().parent.parent / "scripts"
    path = root / "user_config.py"
    real = path.resolve()
    if not real.is_file() or not real.is_relative_to(root):
        raise RuntimeError(f"refusing to load {path}: resolves to {real}, outside {root}")
    spec = importlib.util.spec_from_file_location("_index_user_config", real)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def group_colors(group: str, workspace_file: Path | None = None) -> tuple[str, str]:
    """(dark, light) for a line — the same pack the rendered pages wear.

    `None` is a real state since #9, not a stand-in for a default that no longer exists:
    a machine that has never run setup has no workspace file, and `pack_for` degrades to
    the seed table and then the name hash rather than raising.
    """
    pack = _vdl_packs().pack_for(group, workspace_file)
    return pack["accent"]["dark"], pack["accent"]["light"]


# Every refusal in the JSON read points here, because a CLI upgrade is the only thing that
# changes this shape: `--format json` is UNDOCUMENTED for `project ls` (it is documented on
# `integration`, `skills` and `deploy-hooks ls`), so an upgrade is free to drop or rename it.
# Exiting loudly is the whole point — guessing is what shipped #125.
def known_projects(workspace_file: Path | None) -> list[str]:
    """rawgentic project names, longest first so prefix matching prefers the specific one
    (a longer name must win over any shorter sibling).

    `None` since #9: the index groups by project as a nicety, so a machine with no
    configured workspace still builds a usable page — every row simply falls into the
    cross-project bucket. That is a degradation the index can afford. `publish_doc` cannot,
    which is why IT calls `require_workspace_file` and refuses instead.
    """
    if workspace_file is None:
        return []
    try:
        data = json.loads(workspace_file.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    return sorted((p["name"].lower() for p in data.get("projects", [])), key=len, reverse=True)


def classify(name: str, projects: list[str]) -> tuple[str, str]:
    """(group, chip) for a page name, matched against the known project list."""
    if name.startswith(WORKSPACE_GROUP + "-"):
        group, rest = WORKSPACE_GROUP, name[len(WORKSPACE_GROUP) + 1:]
    else:
        group = next((p for p in projects if name == p or name.startswith(p + "-")), "other")
        rest = name[len(group) + 1:] if group != "other" else name
    chip = next((tok for tok in rest.split("-") if tok in PURPOSES), DEFAULT_PURPOSE)
    return group, chip


# The Edmonton stamp every new/updated page must carry (owner rule, 2026-07-31). Preferred
# over the deploy age because it is what the DOCUMENT says about itself: a re-deploy with no
# content change moves the deploy age but not this.
def _ago(then: datetime, now: datetime) -> str:
    """Compact relative age: 40m, 6h, 3d, 2w."""
    secs = max(0, int((now - then).total_seconds()))
    for cutoff, div, unit in ((3600, 60, "m"), (86400, 3600, "h"),
                              (604800, 86400, "d"), (10**12, 604800, "w")):
        if secs < cutoff:
            return f"{max(1, secs // div)}{unit}"
    return "?"


# The client-side twin of `_ago()` above, with the wiring that keeps it current (#28).
#
# It is a constant rather than JS written inline in the page template, for two reasons. The
# template is one big f-string, so inline JS needs every brace doubled, while an interpolated
# value is substituted literally and needs none. And a test can hand these exact bytes to `node`
# and compare its answers to `_ago()`'s for the same instants — which is the only honest way to
# prove the two vocabularies agree. Scraping the JS back out of rendered HTML is not.
#
# Deliberately ES5, like the rest of the page's script: `var`, `Array.prototype.slice.call`, the
# global `isFinite` rather than `Number.isFinite`, `getAttribute` rather than `dataset`. A page
# served to unknown browsers is the wrong place to raise the floor casually.
_AGE_JS = """
  // ---- the age answers the READER's clock, not the build's -----------------------------
  // `when()` bakes a build-time string into every row, so a tab left open for a day used to
  // read `3m` for a day. The absolute instant rides in `data-updated`, so the page can answer
  // for itself. Nothing is requested: everything needed is already in the markup.
  var ages = Array.prototype.slice.call(document.querySelectorAll('.when[data-updated]'));
  function ago(then, now){
    // The same cutoffs, divisors, units and floor-of-1 as `_ago()`. A test runs this function
    // under node against that one, so the two cannot drift apart silently.
    var secs = Math.max(0, Math.floor((now - then) / 1000));
    var steps = [[3600, 60, 'm'], [86400, 3600, 'h'], [604800, 86400, 'd'], [1e12, 604800, 'w']];
    for (var i = 0; i < steps.length; i++){
      if (secs < steps[i][0]) return Math.max(1, Math.floor(secs / steps[i][1])) + steps[i][2];
    }
    return '?';
  }
  function retime(){
    // Nothing to do for a tab nobody is looking at. The handler below catches it on return,
    // and the poll beside it guards on the same condition.
    if (document.hidden) return;
    var now = Date.now();
    ages.forEach(function(el){
      // The WHOLE value must be digits, and it must be a plausible instant. `parseInt` takes a
      // numeric PREFIX, so `1786757518797-corrupt` used to pass and overwrite the build-time
      // text with an age, and `17e9` used to become epoch 17ms — the exact opposite of what the
      // comment on this line promised (cross-model review finding, 2026-08-14). The bounds are
      // `_instant()`'s own: 1e11 ms is 1973 and 1e14 is the year 5138.
      var raw = el.getAttribute('data-updated');
      if (!/^[0-9]+$/.test(raw)) return;        // unreadable: the row keeps its build-time text
      var then = Number(raw);
      if (!(then >= 1e11 && then < 1e14)) return;
      el.textContent = (el.hasAttribute('data-approx') ? '~' : '') + ago(then, now);
    });
  }
  if (ages.length){
    retime();
    setInterval(retime, 60000);
    // Separate from the poll's own visibility handler on purpose. This one only rewrites text,
    // so the two cannot fight: if the poll decides on a reload, the reload simply wins.
    document.addEventListener('visibilitychange', function(){ if (!document.hidden) retime(); });
  }
"""


def signature(rows: list[dict]) -> str:
    """A hash of the row set that is stable while nothing real changes.

    Every clock-dependent value is excluded, so an idle account hashes identically on every
    build. BOTH time sources are absolute instants now — a page's own declared stamp, and the
    project's `updatedAt` from the CLI — so both are hashed directly. The old carve-out (deploy
    rows contributed the coarse age TOKEN "6h" instead of a timestamp) existed because the age
    was derived as `now` minus a relative token and therefore drifted on every single build,
    which is the false-positive that makes a change-detector useless. `--format json` reports
    the instant itself, so there is nothing left to drift (#125). `updated_src` stays in the
    canon line below, so a row that switches from a deploy-inferred time to a page-declared one
    still counts as changed.
    """
    def mark(r: dict) -> str:
        return r["updated"].isoformat() if r["updated"] else "-"
    canon = "\n".join(sorted(
        f"{r['name']}\t{r['title']}\t{mark(r)}\t{r['updated_src']}" for r in rows))
    return hashlib.sha256(canon.encode()).hexdigest()


def _sort_key(r: dict) -> tuple:
    """Newest first; rows with no known time sink to the bottom, then alphabetical so the
    order is stable across builds rather than dependent on CLI ordering."""
    return (0, -r["updated"].timestamp(), r["name"]) if r["updated"] else (1, 0, r["name"])


def _color_for(group: str, seen: dict[str, tuple[str, str]],
               workspace_file: Path) -> tuple[str, str]:
    """No positional cycling: the old fallback was `PALETTE[len(seen) % len(PALETTE)]`, so
    a project's colour depended on how many groups sorted before it and adding one project
    silently recoloured others. `pack_for` hashes the name instead."""
    if group not in seen:
        seen[group] = group_colors(group, workspace_file)
    return seen[group]


# Owner request 2026-08-05: index links open a new tab by default.
#
# Applied to the DOCUMENT links only. The group nav emits `href="#slug"`, an in-page jump to a
# section of this same page — sending that to a new tab would break the index's own navigation
# and open a duplicate of the index instead of moving within it. So this is deliberately NOT a
# blanket rule over every anchor, and a test pins the distinction in both directions.
#
# `rel="noopener"` rides along because `target="_blank"` without it is the tabnabbing shape:
# the opened page gets a `window.opener` handle back. Current browsers imply it for
# `target="_blank"`, older ones do not, and saying it costs nothing.
NEW_TAB = ' target="_blank" rel="noopener"'


def render(rows: list[dict], stamp: str, now: datetime, sig: str,
           workspace_file: Path | None = None, scope: str | None = None,
           *, eyebrow: str | None = None) -> str:
    # #9: the team name is user-supplied now, so the two places it reaches the page are an
    # injection surface that did not exist while it was a constant. Both are escaped, and
    # `user_config.validate_scope` has already refused anything that is not a slug — belt
    # and braces, because this page is deployed PUBLICLY.
    tenant = html.escape(scope) if scope else ""
    title_prefix = f"{tenant} · " if tenant else ""
    # #34: the harness passes its own eyebrow. The default matches it rather than the
    # retired vendor wording, and it is escaped like `scope`, because it reaches the page
    # the same way.
    if eyebrow is not None:
        eyebrow = html.escape(eyebrow)
    else:
        eyebrow = (f"{tenant} · living documentation" if tenant
                   else "living documentation")
    groups: dict[str, list[dict]] = {}
    for r in sorted(rows, key=_sort_key):
        groups.setdefault(r["group"], []).append(r)

    def freshest(g: str) -> float:
        times = [r["updated"].timestamp() for r in groups[g] if r["updated"]]
        return max(times) if times else 0.0

    # Most-recently-touched line first (owner request 2026-08-01). Was biggest-group-first;
    # size is a poor proxy for "what am I working on", and every line is one click away in
    # the nav regardless.
    order = sorted(groups, key=lambda g: (-freshest(g), g))

    colors: dict[str, tuple[str, str]] = {}
    for g in order:
        _color_for(g, colors, workspace_file)

    # --- every count below is COMPUTED; none may be hand-edited ---
    total_pages = len(rows)
    total_lines = len(order)

    def slug(g: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", g.lower()).strip("-")

    # An EMPTY listing is a real state: an account with no documents yet, or a credential that
    # cannot read any repository. Found live 2026-08-24, when the index answered 500 because
    # `order[0]` below indexed an empty list. The accent falls back to a defined token rather
    # than to a crash — the page then renders and says, truthfully, that there is nothing here.
    accent = slug(order[0]) if order else "none"
    tokens = "\n".join(
        f"  --l-{slug(g)}:{colors[g][0]};" for g in order)
    tokens_light = "\n".join(
        f"    --l-{slug(g)}:{colors[g][1]};" for g in order)
    group_css = "\n".join(
        f".c-{slug(g)}{{color:var(--l-{slug(g)})}} .b-{slug(g)}{{background:var(--l-{slug(g)})}}"
        for g in order)

    nav = "\n".join(
        f'  <a href="#{slug(g)}"><span class="dot b-{slug(g)}"></span>{html.escape(g)}'
        f'<span class="n">{len(groups[g])}</span></a>' for g in order)

    def when(r: dict) -> str:
        """The row's last-updated cell. `~` marks a time inferred from the DEPLOY age
        rather than declared by the page itself, so the two are never confused.

        `_ago()` is evaluated ONCE, here, against the `now` this build captured — so the string
        below answers "how old was this when the index was BUILT". The page is static, so a row
        went on reading `3m` for days until some other publish rebuilt the index (#28, observed
        live 2026-08-14). Two additive attributes fix that without giving up the string:

        * `data-updated` — the absolute instant in epoch milliseconds, which `_AGE_JS` renders
          against the reader's own clock and re-renders while the page sits open.
        * `data-approx` — the `~`, carried as data. The script rewrites the cell's text, so it
          has to know whether to re-apply the marker, and reading it back out of its own previous
          output would be self-referential.

        Both are emitted only on this branch, where a time actually exists. The build-time string
        stays as the element's text, so a reader with no JavaScript sees the page unchanged.
        """
        if not r["updated"]:
            return '<span class="when none" title="no timestamp found">—</span>'
        tilde = "~" if r["updated_src"] == "deploy" else ""
        exact = r["updated"].strftime("%Y-%m-%d %H:%M")
        src = ("declared by the page" if r["updated_src"] == "page"
               else "inferred from the deploy age (coarse)")
        # NOT named `stamp`: `render()` already takes a `stamp` parameter (the build stamp the
        # footer prints), and shadowing it here would hand a future editor an integer where they
        # reasonably expect that string.
        epoch_ms = int(r["updated"].timestamp() * 1000)
        approx = ' data-approx="1"' if tilde else ""
        return (f'<span class="when" data-updated="{epoch_ms}"{approx} '
                f'title="{exact} America/Edmonton — {src}">'
                f'{tilde}{_ago(r["updated"], now)}</span>')

    def row_li(r: dict) -> str:
        return (f'    <li><a href="{html.escape(r["url"])}"{NEW_TAB}>'
                f'<span class="t">{html.escape(r["title"])}</span>'
                f'<span class="rt">{when(r)}'
                f'<span class="chip">{html.escape(r["chip"])}</span></span>'
                f'<span class="u">{html.escape(r["url"].removeprefix("https://"))}</span></a></li>')

    # "Newest documents on top" (owner request 2026-08-01), read literally: the most recent
    # pages across ALL lines, before any grouping.
    recent = [r for r in sorted(rows, key=_sort_key) if r["updated"]][:8]
    recent_html = "\n".join(
        f'    <li><a href="{html.escape(r["url"])}"{NEW_TAB}>'
        f'<span class="dot b-{slug(r["group"])}"></span>'
        f'<span class="t">{html.escape(r["title"])}</span>'
        f'<span class="rt">{when(r)}<span class="chip">{html.escape(r["group"])}</span></span>'
        f'</a></li>' for r in recent)

    sections = []
    for g in order:
        items = "\n".join(row_li(r) for r in groups[g])
        n = len(groups[g])
        sections.append(
            f'<section class="line c-{slug(g)}" id="{slug(g)}">\n'
            f'  <div class="lhead"><span class="badge b-{slug(g)}">{html.escape(g)}</span>'
            f'<span class="cnt">{n} page{"s" if n != 1 else ""}</span></div>\n'
            f'  <ul class="stations">\n{items}\n  </ul>\n</section>')

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title_prefix}docs index</title>
<meta name="index-signature" content="{sig}">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Crect width='16' height='16' rx='3' fill='%23131720'/%3E%3Ccircle cx='5' cy='8' r='2.2' fill='%235ec8f2'/%3E%3Ccircle cx='11' cy='8' r='2.2' fill='%23f2a65e'/%3E%3C/svg%3E">
<style>
:root{{
  --bg:#131720; --panel:#1a1f2b; --panel2:#20263380; --ink:#e9e7de; --dim:#9aa3b5;
  --hair:#2c3345; --focus:#ffd166;
{tokens}
}}
@media (prefers-color-scheme: light){{
  :root{{ --bg:#f3f1ea; --panel:#ffffff; --panel2:#e9e5da80; --ink:#20242e; --dim:#5c6474;
    --hair:#d8d2c4; --focus:#8a5a00;
{tokens_light}
  }}
}}
*{{box-sizing:border-box;margin:0;padding:0}}
html{{scroll-behavior:smooth}}
@media (prefers-reduced-motion: reduce){{ html{{scroll-behavior:auto}} *{{transition:none!important;animation:none!important}} }}
body{{background:var(--bg);color:var(--ink);font:15px/1.5 ui-sans-serif,system-ui,"Segoe UI",Roboto,sans-serif;min-height:100vh}}
a{{color:inherit;text-decoration:none}}
a:focus-visible,input:focus-visible,button:focus-visible{{outline:2px solid var(--focus);outline-offset:2px;border-radius:4px}}
header{{padding:34px clamp(18px,5vw,54px) 22px;border-bottom:1px solid var(--hair)}}
.eyebrow{{font:600 11px/1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.22em;text-transform:uppercase;color:var(--dim)}}
h1{{font-size:clamp(30px,5.5vw,52px);font-weight:800;letter-spacing:-.03em;line-height:1.05;margin:10px 0 6px}}
h1 .tick{{display:inline-block;width:.45em;height:.45em;border-radius:50%;background:var(--l-{accent});margin:0 .12em 0 .06em}}
.sub{{color:var(--dim);max-width:60ch}}
.hud{{display:flex;flex-wrap:wrap;gap:18px;align-items:center;margin-top:18px}}
.stat{{font:700 13px/1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.06em;color:var(--dim)}}
.stat b{{color:var(--ink);font-size:17px}}
#q{{flex:1 1 260px;max-width:430px;background:var(--panel);color:var(--ink);border:1px solid var(--hair);
   border-radius:9px;padding:10px 14px;font:inherit}}
#q::placeholder{{color:var(--dim)}}
.kbd{{font:600 10.5px/1 ui-monospace,monospace;color:var(--dim);border:1px solid var(--hair);border-radius:4px;padding:2px 5px}}
.wrap{{display:grid;grid-template-columns:230px 1fr;gap:0;align-items:start}}
@media (max-width:820px){{ .wrap{{grid-template-columns:1fr}} nav.lines{{position:static;display:flex;flex-wrap:wrap;gap:6px;border-right:none;border-bottom:1px solid var(--hair)}} nav.lines a{{border-left:none!important;border-radius:99px;border:1px solid var(--hair)}} }}
nav.lines{{position:sticky;top:0;padding:22px 10px 22px clamp(18px,5vw,54px);display:flex;flex-direction:column;gap:2px;border-right:1px solid var(--hair);min-height:50vh}}
nav.lines a{{display:flex;align-items:center;gap:9px;padding:7px 10px;color:var(--dim);font:600 13px/1.2 ui-sans-serif,system-ui,sans-serif;border-left:3px solid transparent}}
nav.lines a:hover{{color:var(--ink);background:var(--panel2)}}
nav.lines a .dot{{width:10px;height:10px;border-radius:50%;flex:none}}
nav.lines a .n{{margin-left:auto;font:600 11px/1 ui-monospace,monospace;color:var(--dim)}}
main{{padding:26px clamp(18px,4vw,50px) 60px}}
section.line{{margin-bottom:34px}}
.lhead{{display:flex;align-items:baseline;gap:12px;margin-bottom:4px}}
.lhead .badge{{font:700 10.5px/1 ui-monospace,monospace;letter-spacing:.14em;text-transform:uppercase;
  padding:4px 9px;border-radius:99px;color:var(--bg)}}
.lhead .cnt{{color:var(--dim);font:600 12px/1 ui-monospace,monospace}}
ul.stations{{list-style:none;border-left:3px solid currentColor;margin-left:6px;padding:6px 0 2px}}
ul.stations li{{position:relative}}
ul.stations li a{{display:grid;grid-template-columns:1fr auto;gap:4px 16px;align-items:baseline;
  padding:9px 12px 9px 24px;border-radius:0 9px 9px 0}}
ul.stations li a::before{{content:"";position:absolute;left:-7.5px;top:50%;transform:translateY(-50%);
  width:9px;height:9px;border-radius:50%;background:var(--bg);border:2.5px solid var(--hair)}}
ul.stations li a:hover{{background:var(--panel2)}}
ul.stations li a:hover::before{{border-color:currentColor}}
.t{{font-weight:650}}
.u{{grid-column:1 / -1;font:12px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--dim);word-break:break-all}}
.rt{{display:flex;align-items:baseline;gap:9px;justify-self:end}}
.chip{{font:700 10px/1 ui-monospace,monospace;letter-spacing:.12em;text-transform:uppercase;color:var(--dim);
  border:1px solid var(--hair);border-radius:4px;padding:3px 6px}}
.when{{font:600 11.5px/1 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--dim);
  min-width:3.2em;text-align:right;cursor:help}}
.when.none{{opacity:.55;cursor:default}}
/* Recently updated — the literal "newest on top" strip, above every grouped line. */
section.recent{{margin:0 0 34px;padding:14px 16px 8px;background:var(--panel);
  border:1px solid var(--hair);border-radius:12px}}
section.recent .rhead{{display:flex;align-items:baseline;gap:12px;margin-bottom:2px}}
section.recent .rhead .badge{{font:700 10.5px/1 ui-monospace,monospace;letter-spacing:.14em;
  text-transform:uppercase;color:var(--dim)}}
section.recent ul{{list-style:none}}
section.recent li a{{display:grid;grid-template-columns:auto 1fr auto;gap:10px;align-items:baseline;
  padding:7px 6px;border-radius:7px}}
section.recent li a:hover{{background:var(--panel2)}}
section.recent .dot{{width:8px;height:8px;border-radius:50%;flex:none;align-self:center}}
li.hide,section.hide{{display:none}}
#recent.hide{{display:none}}
#fresh{{position:fixed;left:50%;transform:translateX(-50%);bottom:20px;z-index:20;display:flex;
  align-items:center;gap:12px;background:var(--panel);color:var(--ink);border:1px solid var(--hair);
  border-radius:999px;padding:9px 10px 9px 18px;box-shadow:0 6px 24px rgba(0,0,0,.28);
  font:600 13px/1 ui-sans-serif,system-ui,sans-serif}}
#fresh[hidden]{{display:none}}
#fresh button{{font:700 12px/1 ui-monospace,monospace;letter-spacing:.06em;text-transform:uppercase;
  background:var(--ink);color:var(--bg);border:0;border-radius:999px;padding:7px 13px;cursor:pointer}}
#none{{display:none;color:var(--dim);padding:30px 0;font-style:italic}}
#none.show{{display:block}}
footer{{border-top:1px solid var(--hair);color:var(--dim);font:12px/1.6 ui-monospace,monospace;
  padding:20px clamp(18px,5vw,54px) 40px}}
{group_css}
</style>
</head>
<body>
<header>
  <div class="eyebrow">{eyebrow}</div>
  <h1>Docs index<span class="tick"></span></h1>
  <p class="sub">Every deployed page, newest first, grouped by the rawgentic project it belongs to. Type to filter; click a line to jump.</p>
  <div class="hud">
    <span class="stat"><b>{total_pages}</b> pages</span>
    <span class="stat"><b>{total_lines}</b> lines</span>
    <input id="q" type="search" placeholder="Filter by name, title, or purpose…" aria-label="Filter pages">
    <span class="kbd">/</span>
    <span class="stat">updated <b>{html.escape(stamp)}</b></span>
  </div>
</header>

<div id="fresh" role="status" hidden><span>New pages published</span><button type="button" id="freshgo">Reload</button></div>

<div class="wrap">
<nav class="lines" aria-label="Project lines">
{nav}
</nav>

<main>
<section class="recent" id="recent">
  <div class="rhead"><span class="badge">recently updated</span></div>
  <ul>
{recent_html}
  </ul>
</section>

{chr(10).join(sections)}

<p id="none">No page matches that filter.</p>
</main>
</div>

<footer>
  naming: {{date}}-{{repo}}-{{doc}} · derived from the repositories by the doc harness —
  never hand-edited · {total_pages} pages across {total_lines} lines ·
  generated {html.escape(stamp)} (America/Edmonton)
</footer>

<script>
(function(){{
  var q = document.getElementById('q');
  var none = document.getElementById('none');
  var sections = Array.prototype.slice.call(document.querySelectorAll('section.line'));
  var recent = document.getElementById('recent');
  document.addEventListener('keydown', function(e){{
    if (e.key === '/' && document.activeElement !== q){{ e.preventDefault(); q.focus(); }}
    if (e.key === 'Escape' && document.activeElement === q){{ q.value=''; apply(); q.blur(); }}
  }});
  function apply(){{
    var needle = q.value.trim().toLowerCase();
    var any = false;
    // The recency strip is a shortcut, not a search result — hide it while filtering so
    // a hit inside it cannot be mistaken for a second copy of a grouped row.
    if (recent) recent.classList.toggle('hide', needle !== '');
    sections.forEach(function(sec){{
      var kept = 0;
      Array.prototype.slice.call(sec.querySelectorAll('li')).forEach(function(li){{
        var hit = !needle || li.textContent.toLowerCase().indexOf(needle) !== -1
                  || sec.id.toLowerCase().indexOf(needle) !== -1;
        li.classList.toggle('hide', !hit);
        if (hit) kept++;
      }});
      sec.classList.toggle('hide', kept === 0);
      if (kept > 0) any = true;
    }});
    none.classList.toggle('show', !any);
  }}
  q.addEventListener('input', apply);
{_AGE_JS}
  // ---- auto-refresh when new content is published -------------------------------------
  // The page is static, so there is nothing to push an update. It polls its own URL and
  // compares the build signature in <meta name="index-signature">, which changes only when
  // a page was added, removed, retitled or restamped — never merely because the clock moved.
  var meta = document.querySelector('meta[name="index-signature"]');
  var mine = meta && meta.getAttribute('content');
  var banner = document.getElementById('fresh');
  var go = document.getElementById('freshgo');
  if (mine && banner && go && window.fetch) {{
    go.addEventListener('click', function(){{ location.reload(); }});
    var stop = false;
    function busy(){{
      // Reloading out from under someone mid-filter loses their query and their scroll
      // position. In that case offer the banner and let them choose the moment.
      return document.activeElement === q || q.value.trim() !== '';
    }}
    function check(){{
      if (stop || document.hidden) return;
      fetch(location.pathname + '?cb=' + Date.now(), {{cache: 'no-store'}})
        .then(function(r){{ return r.ok ? r.text() : null; }})
        .then(function(t){{
          if (!t) return;
          var m = t.match(/name="index-signature" content="([a-f0-9]{{64}})"/);
          if (!m || m[1] === mine) return;
          stop = true;                       // one decision per change, not one per tick
          if (busy()) banner.hidden = false; else location.reload();
        }})
        .catch(function(){{ /* offline or a blip: try again next tick, never disturb the page */ }});
    }}
    setInterval(check, 90000);
    // A tab left open overnight should be current the moment it is looked at again.
    document.addEventListener('visibilitychange', function(){{ if (!document.hidden) check(); }});
  }}
}})();
</script>
</body>
</html>
"""
