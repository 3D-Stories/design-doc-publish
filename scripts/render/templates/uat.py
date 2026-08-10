"""`uat` — a checklist a human executes (#18, wave 4; specs §4d).

The only INTERACTIVE template. Its target is a UAT checklist page, whose structure is
fixed by the owner (2026-08-01) — the only per-project change is colour, which wave 6
supplies. Everything here was measured against that page, not reconstructed: 25 items but
only 16 comment boxes (the defect this issue exists to fix), zero `innerHTML`, one inline
script with no `src`, one page-scoped schema-versioned storage key.

Still declaration-only, like the other nine. Three declarations do the work:

* `BLOCK_VARIANTS` names an engine-owned renderer; this module supplies no callable, so
  parsing and escaping stay behind `_rows` in `blocks.py`.
* `BEFORE_BODY` / `AFTER_BODY` are trusted CONSTANT strings — page furniture, containing
  no author text at any point, which is what makes them safe to emit unescaped.

**CSP exemption, taken explicitly.** The module docstring's "survives a strict
Content-Security-Policy" holds for every template except this one: a strict
`script-src 'self'` blocks inline JavaScript, and an interactive checklist needs some.
The owner's own nominated exemplar ships exactly one inline script, so the exemption is
warranted — but it is stated here and pinned by a test rather than smuggled in.
"""
NAME = "uat"

# #69: this template's page frame. Its reference art (`triage-board.html`) is a dark
# FOUR-COLUMN board with a radial wash — a 900px single column cannot hold one, which is a
# large part of why a light single-column checklist shipped against it. Wide measure, a flush
# masthead with no rule (a board has no document header), and a bigger display size.
FRAME = {
    "ground": "radial-gradient(120% 90% at 50% 0%,#18222c 0%,var(--bg) 62%)",
    "measure": "1240px",
    "gutter": "0 24px 72px",
    "header_pad": "34px 0 14px",
    "header_rule": "none",
    "header_gap": "14px",
    # #75: the frozen capture's first-read element is a DISPLAY headline, not a document title —
    # measured at roughly twice the body scale, which is what makes it read as a masthead.
    "h1_size": "clamp(30px,5.4vw,46px)",
}

# #75: the four accents the frozen target cycles across its parts. Declared here and emitted by
# `frame.palette_layer` as `--tpl-a1…a4` scoped to `body.tpl-uat`, because this stylesheet may not
# contain a colour literal of any form (AC5) and the shared token layer has only one accent hue.
# The full reasoning, including why `color-mix()` is closed off too, is in `frame.py`.
#
# Sampled from `docs/planning/shots/target-uat-checklist.png` and `-items.png`.
ACCENTS = ("#22d3ee", "#a78bfa", "#fbbf24", "#60a5fa")

# #75: the title's phrases alternate ink and accent, divided by `|` where the AUTHOR puts them.
# `render._headline` owns the split; a style that does not declare this is untouched by it.
HEADLINE = "alternate"

SECTIONS = {"section_class": "ut-step"}

MARKERS = {"callout:stop": "ut-stop", "steps": "ut-board"}

# The engine keeps both `steps` renderers; this only picks one.
BLOCK_VARIANTS = {"steps": "checklist"}

BEFORE_BODY = ('<div class="ut-meter"><span class="ut-track">'
               '<span class="ut-fill" id="ut-fill"></span></span>'
               '<span class="ut-count" id="ut-count">0 / 0</span></div>',
               # The filter toolbar. Native radios, so keyboard operation and checked-state
               # reporting come from the platform rather than from ARIA of our own. The two
               # dimensions are SEPARATE radio groups and each carries its own `role="group"`
               # labelled by the heading the user can already see: under one combined group,
               # "Any" announces with nothing to say which dimension it belongs to.
               #
               # LEVEL OFFERS MUST AND SHOULD ONLY, because D13 named those two. The `steps`
               # grammar also accepts `must-not`, `should-not` and `may`, and a row carrying
               # one of those matches NEITHER level option — it is reachable only under "Any"
               # (confirmed in Chromium: a MAY row stays hidden under both). Widening the
               # toolbar past what the owner named is a scope change, so the gap is recorded
               # here rather than closed on the way past.
               '<div class="ut-filter">'
               '<div class="ut-fgroup" role="group" aria-labelledby="ut-lbl-state">'
               '<span class="ut-flabel" id="ut-lbl-state">Show</span>'
               '<label class="ut-fopt"><input type="radio" name="ut-state" value="all" checked>'
               '<span>All</span></label>'
               '<label class="ut-fopt"><input type="radio" name="ut-state" value="todo">'
               '<span>Not executed</span></label>'
               '<label class="ut-fopt"><input type="radio" name="ut-state" value="done">'
               '<span>Executed</span></label>'
               '</div>'
               '<span class="ut-fsep" aria-hidden="true"></span>'
               '<div class="ut-fgroup" role="group" aria-labelledby="ut-lbl-level">'
               '<span class="ut-flabel" id="ut-lbl-level">Level</span>'
               '<label class="ut-fopt"><input type="radio" name="ut-level" value="all" checked>'
               '<span>Any</span></label>'
               '<label class="ut-fopt"><input type="radio" name="ut-level" value="must">'
               '<span>MUST</span></label>'
               '<label class="ut-fopt"><input type="radio" name="ut-level" value="should">'
               '<span>SHOULD</span></label>'
               '</div>'
               # `role="status"` so emptying the view is announced rather than only drawn.
               # Toggling `hidden` on a live region is less dependable than swapping its text,
               # but it is one attribute and beats silence; announcement was NOT measured here.
               '<span class="ut-fnone" id="ut-fnone" role="status" hidden>Nothing matches this '
               'filter. Answers to hidden items are still saved.</span>'
               '</div>')

_EXPORT = ('<section class="ut-export">'
           '<h2>Hand the results back</h2>'
           '<p>Copies a prompt for the assistant: every item with its state, every note '
           'you wrote, and instructions not to file anything it cannot support.</p>'
           '<button type="button" class="ut-btn" id="ut-copy">Copy the results prompt</button>'
           '<span class="ut-said" id="ut-said"></span>'
           '<textarea class="ut-out" id="ut-out" rows="12" hidden '
           'aria-label="Results prompt"></textarea>'
           '</section>')

# One inline script. DOM-builder only: no innerHTML, outerHTML, document.write or eval.
# Storage mirrors the target — ONE page-scoped, schema-versioned key holding a single JSON
# blob, with try/catch on BOTH read and write so a browser with storage disabled degrades
# to a working-but-forgetful checklist rather than a page that throws on load.
_SCRIPT = """<script>
(function(){
  var KEY = document.body.getAttribute('data-uat-key') || 'uat:unknown:v1';
  var REPO = document.body.getAttribute('data-uat-repo') || 'this project';
  var boxes = [].slice.call(document.querySelectorAll('input[type=checkbox][data-k]'));
  var notes = [].slice.call(document.querySelectorAll('textarea[data-note]'));
  var saved = {};
  try { saved = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (e) { saved = {}; }
  if (typeof saved !== 'object' || Array.isArray(saved)) saved = {};
  // Parsing is not validating. A stored "false" is a TRUTHY string and would restore as
  // checked; a stored number would render as a note. Coerce by type, never by truthiness.
  function wasChecked(k){ return saved['c:' + k] === true; }
  function savedNote(k){ var v = saved['n:' + k]; return typeof v === 'string' ? v : ''; }

  // #59: MERGE, never replace. `st` used to start empty, so every stored key whose item was
  // not on THIS page was dropped on the next keystroke — a human's typed notes, gone with
  // nothing on screen to say so. Measured 12 keys -> 6 after unticking one box.
  // Re-read from storage rather than reusing the load-time `saved`: two tabs on the same
  // doc-id otherwise clobber each other, and re-reading costs nothing at this size.
  function save(){
    var st = {};
    try {
      var prev = JSON.parse(localStorage.getItem(KEY) || '{}');
      if (prev && typeof prev === 'object' && !Array.isArray(prev)) st = prev;
    } catch (e) { st = {}; }
    boxes.forEach(function(b){ st['c:' + b.dataset.k] = b.checked; });
    notes.forEach(function(t){ st['n:' + t.dataset.note] = t.value; });
    try { localStorage.setItem(KEY, JSON.stringify(st)); } catch (e) {}
    meter();
  }
  // Keys held in storage that this page has no element for. An orphan is either an item the
  // author deliberately deleted, or one that vanished because its fence degraded — the page
  // cannot tell those apart, so it never discards either and the export prints them instead.
  function orphans(){
    var mine = {};
    boxes.forEach(function(b){ mine['c:' + b.dataset.k] = 1; });
    notes.forEach(function(t){ mine['n:' + t.dataset.note] = 1; });
    var cur = {};
    try {
      var p = JSON.parse(localStorage.getItem(KEY) || '{}');
      if (p && typeof p === 'object' && !Array.isArray(p)) cur = p;
    } catch (e) { cur = {}; }
    // Grouped by ID, not by key. Emitting one line per stored key listed `B1` twice — once
    // for its tick, once for its note — and a reader cannot tell that is one item. Caught by
    // reading the generated export rather than by any test.
    var ids = [], seen = {};
    Object.keys(cur).forEach(function(k){
      if (mine[k] || (k.indexOf('c:') !== 0 && k.indexOf('n:') !== 0)) return;
      var id = k.slice(2);
      if (!seen[id]) { seen[id] = {}; ids.push(id); }
      seen[id][k.charAt(0)] = cur[k];
    });
    var out = [];
    ids.forEach(function(id){
      var tick = seen[id].c === true;
      var note = typeof seen[id].n === 'string' ? seen[id].n.replace(/\\s+/g, ' ').trim() : '';
      if (!tick && !note) return;   // an unticked item with no note holds nothing to lose
      out.push('- `' + id + '` - ' + (tick ? 'executed' : 'not executed')
             + (note ? ' - ' + note : ' - (no note)'));
    });
    return out;
  }
  function meter(){
    var n = boxes.filter(function(b){ return b.checked; }).length;
    var fill = document.getElementById('ut-fill');
    var count = document.getElementById('ut-count');
    if (fill) fill.style.width = (boxes.length ? (100 * n / boxes.length) : 0) + '%';
    if (count) count.textContent = n + ' / ' + boxes.length;
  }
  boxes.forEach(function(b){
    b.checked = wasChecked(b.dataset.k);
    b.addEventListener('change', save);
  });
  notes.forEach(function(t){
    t.value = savedNote(t.dataset.note);
    t.classList.toggle('filled', t.value.trim() !== '');
    t.addEventListener('input', function(){
      t.classList.toggle('filled', t.value.trim() !== '');
      save();
    });
  });
  meter();

  // ---- Filtering. CSS-ONLY HIDING, and that is a correctness requirement, not a style
  // preference. `boxes` and `notes` are SNAPSHOT arrays taken once at load, and `save()`
  // above rebuilds the entire stored blob from them. Two consequences, both measured in
  // Chromium rather than reasoned about:
  //   * merely detaching a row is survivable — the arrays keep the reference, so a detached
  //     item's tick and note are still written on the next save;
  //   * REPLACING the rows is not. Re-render a list wholesale and both arrays hold orphans,
  //     so a tick on a rebuilt row reaches no listener and no storage while the screen shows
  //     it ticked — the meter read 3/6 against four visible ticks. (The markup-writing APIs
  //     that do this are named in the banned list in tests/test_uat_template.py; they are
  //     deliberately not spelled out here, because AC4's guard greps this script for them.)
  // Reassigning `boxes`/`notes` to a filtered subset does the same damage without touching
  // the DOM at all. This handler therefore does exactly one thing: set an attribute on
  // <body>. Every input stays in the document, in both arrays, whatever is on screen.
  function applyFilter(){
    var st = document.querySelector('input[name=ut-state]:checked');
    var lv = document.querySelector('input[name=ut-level]:checked');
    document.body.setAttribute('data-ut-state', st ? st.value : 'all');
    document.body.setAttribute('data-ut-level', lv ? lv.value : 'all');
    // "Nothing matches" has to be measured, not inferred from the filter pair: whether a
    // combination is empty depends on the document AND on what is currently ticked.
    // Derived from `boxes`, NOT from a class selector. Two existing guards assert the item
    // class name is absent from a page whose fence degraded, and naming it here — even in a
    // script — would defeat them. Going through the checkboxes is also truer: an item without
    // one is not something the filter can act on.
    var items = boxes.map(function(b){ return b.closest('li'); }).filter(Boolean);
    var shown = items.filter(function(li){ return li.offsetParent !== null; }).length;
    var none = document.getElementById('ut-fnone');
    if (none) none.hidden = !(items.length && shown === 0);
  }
  [].slice.call(document.querySelectorAll('input[name=ut-state], input[name=ut-level]'))
    .forEach(function(r){ r.addEventListener('change', applyFilter); });
  // A tick can empty the current view, so re-evaluate after every save too.
  boxes.forEach(function(b){ b.addEventListener('change', applyFilter); });
  applyFilter();

  // Built ONCE from the elements themselves. Interpolating an authored id into a
  // selector let `x"]` throw inside build(), which killed the export outright — clipboard
  // and fallback both. A map cannot be injected into.
  var titles = {};
  boxes.forEach(function(b){
    var t = b.parentNode.querySelector('.ut-title');
    titles[b.dataset.k] = t ? t.textContent : b.dataset.k;
  });
  function label(k){
    return Object.prototype.hasOwnProperty.call(titles, k) ? titles[k] : k;
  }
  function build(){
    var done = [], todo = [], obs = [];
    boxes.forEach(function(b){
      (b.checked ? done : todo).push('- [' + (b.checked ? 'x' : ' ') + '] '
        + b.dataset.k + ' - ' + label(b.dataset.k));
    });
    notes.forEach(function(t){
      if (t.value.trim() !== '')
        obs.push('### ' + t.dataset.note + ' - ' + label(t.dataset.note)
                 + '\\n' + t.value.trim());
    });
    var title = document.title;
    var L = [];
    L.push('# UAT results - ' + title);
    L.push('');
    L.push(done.length + ' of ' + boxes.length + ' items executed.');
    L.push('');
    L.push('## Executed');
    L.push(done.length ? done.join('\\n') : '_none_');
    L.push('');
    L.push('## Not executed');
    L.push(todo.length ? todo.join('\\n') : '_none_');
    L.push('');
    L.push('## Observations');
    L.push(obs.length ? obs.join('\\n\\n') : '_none_');
    L.push('');
    // #59, question 3: an orphaned answer is exactly the case where a human's work would
    // otherwise disappear, so omitting it would lose the note at the moment it matters.
    // Printed under its own heading, never merged into Observations, because there is no
    // item text to attach it to and it must not read as an answer to something on this page.
    var orph = orphans();
    if (orph.length) {
      L.push('## Answers with no matching item on this page');
      L.push('These were stored under this doc-id but the current page has no item for them '
           + '- an item was removed, renamed, or its fence degraded. Kept so nothing typed is '
           + 'lost; read them before assuming they are stale.');
      L.push('');
      L.push(orph.join('\\n'));
      L.push('');
    }
    L.push('---');
    L.push('File these against ' + REPO + '. A checkbox records EXECUTED, nothing more: '
         + 'an unchecked item means NOT EXECUTED, not failed, and a checked one is not a '
         + 'pass. Whether something FAILED is only ever stated in an observation, so read '
         + 'those before filing anything, and treat each on its merits - some record a '
         + 'pass, a timing or a preference. Do not open a bug without reproducing it '
         + 'first. Claim nothing the notes do not support, and quote the item id in '
         + 'anything you file.');
    return L.join('\\n');
  }
  function reveal(text){
    var ta = document.getElementById('ut-out');
    if (!ta) return;
    ta.hidden = false;
    ta.value = text;
    ta.focus();
    ta.select();
  }
  function said(msg){
    var d = document.getElementById('ut-said');
    if (d) d.textContent = msg;
  }
  var btn = document.getElementById('ut-copy');
  if (btn) btn.addEventListener('click', function(){
    var md = build();
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(md).then(
        function(){ said('Copied. Paste it to the assistant.'); },
        function(){ reveal(md); said('Clipboard blocked - copy it from the box.'); });
    } else {
      reveal(md);
      said('Clipboard unavailable - copy it from the box.');
    }
  });
})();
</script>"""

AFTER_BODY = (_EXPORT, _SCRIPT)

# AC5: tokens only. Not one literal colour in any form — no hex, rgb(), hsl(),
# color-mix() or named colour — so wave 6's per-project packs restyle all of it by
# overriding custom properties.
CSS = """
/* Filter toolbar — the reference's `.toolbar`/`.filters`. Native radios styled as pills; the
   real control is the input, so keyboard and assistive tech get it for free. */
.tpl-uat .ut-filter{display:flex;flex-wrap:wrap;align-items:center;gap:8px;
background:var(--surface);border:1px solid var(--line);border-radius:12px;
padding:9px 14px;margin:0 0 18px}
.tpl-uat .ut-flabel{font:10.5px/1.4 ui-monospace,Menlo,Consolas,monospace;letter-spacing:.06em;
text-transform:uppercase;color:var(--ink-3)}
.tpl-uat .ut-fsep{width:1px;height:18px;background:var(--line);margin:0 4px}
.tpl-uat .ut-fgroup{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
/* No `gap` here: the radio is out of flow, so the span is the only in-flow child and a gap
   would space nothing. The label/input spacing comes from the group rule above. */
.tpl-uat .ut-fopt{display:inline-flex;align-items:center;cursor:pointer;
border:1px solid var(--line);border-radius:999px;padding:3px 11px;font-size:12.5px;
color:var(--ink-2)}
.tpl-uat .ut-fopt input{position:absolute;opacity:0;width:0;height:0}
/* Selected state uses the accent as TEXT and BORDER over a tinted fill, rather than a solid
   accent block with a contrasting foreground on it: AC5 forbids a literal colour anywhere in
   this template and there is no on-accent token to pair with a solid fill. Same idiom as the
   severity pills. */
.tpl-uat .ut-fopt:has(input:checked){background:var(--code);border-color:var(--accent);
color:var(--accent);font-weight:650}
.tpl-uat .ut-fopt:has(input:focus-visible){outline:2px solid var(--accent);outline-offset:2px}
.tpl-uat .ut-fnone{flex-basis:100%;font-size:12.5px;color:var(--ink-3)}
/* The filter itself. Hiding is `display:none` on the ITEM — the input stays in the document
   and in the script's snapshot arrays, so `save()` still sees every box and note. See the
   script comment for why the alternative, rebuilding the rows, silently desynchronises what
   is on screen from what is stored. */
.tpl-uat[data-ut-state="todo"] .ut-item:has(input[type=checkbox]:checked){display:none}
.tpl-uat[data-ut-state="done"] .ut-item:not(:has(input[type=checkbox]:checked)){display:none}
.tpl-uat[data-ut-level="must"] .ut-item:not(:has(.blk-level.is-must)){display:none}
.tpl-uat[data-ut-level="should"] .ut-item:not(:has(.blk-level.is-should)){display:none}
/* Board treatment — the reference's `.column`/`.card`. The section is the column and each item
   is a card. NOT adopted: the reference's side-by-side multi-column `.board`. A UAT is executed
   top to bottom, and columns would invite skipping — the checklist stays one column.
   Also not adopted: its `.col-count`, which is a per-column TOTAL, not a per-card label —
   `triage-board.html:361` does `var n = col.querySelectorAll(".card").length;` and writes it
   into a span in the column head. Left out because the sticky meter already reports progress
   for the whole page, and a per-section total cannot be a CSS counter: counters read in
   document order, so a heading that precedes its items cannot show their final count. Adding
   it would mean extending the script, which is a feature rather than a body rebuild. An
   earlier draft here reset and incremented a `ut-card` counter that nothing consumed and so
   rendered no count at all; that dead CSS is gone. */
.tpl-uat .ut-board .ut-item{background:var(--surface);
border:1px solid var(--line);border-radius:10px;padding:10px 13px;margin:0}
/* The divider idiom further down (`.ut-item:first-child{border-top:0}`) predates the card
   treatment and has the SAME specificity as the rule above, so without this the first card of
   every checklist rendered with an open top edge — measured in Chromium: 0px top, 1px on the
   other three sides. Revert: delete this one rule. */
.tpl-uat .ut-board .ut-item:first-child{border-top:1px solid var(--line)}
.tpl-uat .ut-board .ut-items{display:grid;gap:8px;margin:10px 0 0;padding:0}
/* #75 — the frozen target's devices. Everything below was measured off
   `docs/planning/shots/target-uat-checklist.png` and `-items.png`, not reconstructed from a
   description of them.

   THE PART ACCENT. Each part owns one of four hues and spends it on the panel's left edge, its
   PART pill, its checkbox borders and its item ordinals. `--ut-a` is the indirection: every
   device below reads it, and only these four rules decide it, so re-ordering the cycle is a
   four-line change rather than a sweep. The fallback keeps the style working if the palette is
   ever withdrawn. `nth-of-type` counts sections, and the export panel is the last section on the
   page — it may collect a cycle value, which is harmless because it sets its own edge. */
.tpl-uat .ut-step{--ut-a:var(--tpl-a1,var(--accent))}
.tpl-uat .ut-step:nth-of-type(4n+2){--ut-a:var(--tpl-a2,var(--accent))}
.tpl-uat .ut-step:nth-of-type(4n+3){--ut-a:var(--tpl-a3,var(--accent))}
.tpl-uat .ut-step:nth-of-type(4n+4){--ut-a:var(--tpl-a4,var(--accent))}
/* THE PART PILL. A counter, not authored text: the author writes `## Install` and the page says
   `PART 1  Install`. Numbering a part is exactly what a counter is good at — unlike the per-column
   TOTAL rejected above, which a counter genuinely cannot do, because counters read in document
   order and a heading precedes the items it would have to count. */
.tpl-uat main{counter-reset:ut-part}
.tpl-uat .ut-step{counter-increment:ut-part}
.tpl-uat .ut-step>h3:first-of-type{display:flex;align-items:center;gap:12px;flex-wrap:wrap;
font-size:19px;margin:14px 0 2px}
.tpl-uat .ut-step>h3:first-of-type::before{content:"part " counter(ut-part);flex:none;
font:700 10.5px/1.6 ui-monospace,Menlo,Consolas,monospace;letter-spacing:.13em;
text-transform:uppercase;padding:3px 10px;border-radius:7px;color:var(--bg);background:var(--ut-a)}
/* THE PANEL EDGE, matching the pill. Depth by ground, not shadow — the approved spec's rule 2. */
.tpl-uat .ut-step{border-left:3px solid var(--ut-a)}
/* THE EYEBROW, as a bordered pill with a dot rather than a bare line of small caps. */
.tpl-uat header .eyebrow{display:inline-flex;align-items:center;gap:9px;
border:1px solid var(--line);border-radius:999px;padding:6px 14px;
font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11px;letter-spacing:.13em}
.tpl-uat header .eyebrow::before{content:"";width:7px;height:7px;border-radius:50%;
background:var(--accent);flex:none}
/* THE TWO-TONE DISPLAY HEADLINE. `render._headline` emits the spans; this only colours them.
   The alternation is the author's, phrase by phrase — see the HEADLINE declaration above. */
.tpl-uat h1{line-height:1.12;letter-spacing:-.02em;max-width:22ch}
.tpl-uat h1 .h1-a{color:var(--ink)}
.tpl-uat h1 .h1-b{color:var(--tpl-a1,var(--accent))}

.tpl-uat .ut-meter{position:sticky;top:0;z-index:5;display:flex;gap:12px;align-items:center;
background:var(--bg);border-bottom:1px solid var(--line);padding:12px 0;margin:0 0 22px}
.tpl-uat .ut-track{flex:1;height:8px;border-radius:999px;background:var(--code);overflow:hidden}
.tpl-uat .ut-fill{display:block;height:100%;width:0;background:var(--accent);
transition:width .18s ease}
/* The count is the page's running score, so it is mono and it takes the accent — in the target
   it is the one coloured thing in the sticky bar. */
.tpl-uat .ut-count{font:13px/1.4 ui-monospace,Menlo,Consolas,monospace;font-weight:700;
color:var(--accent);white-space:nowrap;letter-spacing:.06em}
.tpl-uat .ut-step{background:var(--surface);border:1px solid var(--line);border-radius:14px;
padding:6px 22px 20px;margin:22px 0}
.tpl-uat .ut-step h3{letter-spacing:.01em}
.tpl-uat .ut-items{list-style:none;margin:0;padding:0}
.tpl-uat .ut-item{border-top:1px solid var(--line);padding:12px 0}
.tpl-uat .ut-item:first-child{border-top:0}
.tpl-uat .ut-row{display:flex;gap:11px;align-items:flex-start;cursor:pointer}
.tpl-uat .ut-row input{position:absolute;opacity:0;width:0;height:0}
/* #75 — REAL SQUARE CHECKBOXES, in the part's own accent. The target's boxes are the largest
   interactive thing on the page and they read as checkboxes at a glance; at 19px in a muted
   border they read as decoration. 24px, 2px border, and the tick is drawn rather than implied by
   a filled square, so a checked box still says "checked" to someone who cannot see the fill. */
.tpl-uat .ut-box{flex:0 0 auto;position:relative;width:24px;height:24px;margin-top:1px;
border-radius:7px;border:2px solid var(--ut-a,var(--ink-3));background:var(--bg)}
.tpl-uat .ut-row input:checked+.ut-box{background:var(--ut-a,var(--accent));
border-color:var(--ut-a,var(--accent))}
.tpl-uat .ut-row input:checked+.ut-box::after{content:"";position:absolute;left:7px;top:3px;
width:5px;height:10px;border:solid var(--bg);border-width:0 2.5px 2.5px 0;transform:rotate(42deg)}
.tpl-uat .ut-row input:focus-visible+.ut-box{outline:2px solid var(--ut-a,var(--accent));
outline-offset:2px}
.tpl-uat .ut-txt{display:flex;flex-direction:column;gap:2px}
/* The ordinal takes the part's accent — in the target it is the only thing tying a row back to
   the band it belongs to once the reader has scrolled past the pill. */
.tpl-uat .ut-n{font:10.5px/1.4 ui-monospace,Menlo,Consolas,monospace;font-weight:700;
letter-spacing:.06em;text-transform:uppercase;color:var(--ut-a,var(--ink-3))}
.tpl-uat .ut-title{font-weight:650;color:var(--ink)}
.tpl-uat .ut-row input:checked~.ut-txt .ut-title{color:var(--ink-3);text-decoration:line-through}
.tpl-uat .ut-text{color:var(--ink-2);font-size:13.5px}
/* BONUS, not this issue's — #78 lists "unstyled level chips on uat" among four deferred defects.
   Taken here because it is three rules and because the level sits inside the item row this issue
   rebuilds, so leaving it bare would have been visible in the screenshot #75 ships as evidence.
   The filter already depends on `.blk-level.is-must` / `.is-should` existing, so nothing new is
   introduced — only the pill shape the rest of the engine gives every other chip.

   `align-self` is load-bearing, not tidying: `.ut-txt` is a flex COLUMN, so an `inline-block`
   child stretches to the full row width and the chip shipped as a wide bar. Caught by looking at
   the rendered page; no test would have called it wrong, because the chip was genuinely there.

   UNDO: delete these three rules; #78 keeps the item on its list either way. */
.tpl-uat .blk-level{align-self:flex-start;display:inline-block;
font:700 9.5px/1.7 ui-monospace,Menlo,Consolas,monospace;
letter-spacing:.11em;text-transform:uppercase;padding:1px 7px;border-radius:6px;margin-top:3px;
color:var(--ink-3);background:var(--code)}
.tpl-uat .blk-level.is-must{color:var(--sev-crit);background:var(--sev-crit-bg)}
.tpl-uat .blk-level.is-should{color:var(--sev-med);background:var(--sev-med-bg)}
.tpl-uat .ut-note{display:block;width:100%;margin:8px 0 0 30px;max-width:calc(100% - 30px);
font:13px/1.5 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:var(--ink);
background:var(--bg);border:1px dashed var(--line);border-radius:8px;padding:7px 10px;resize:vertical}
.tpl-uat .ut-note:focus{outline:none;border-style:solid;border-color:var(--accent)}
.tpl-uat .ut-note.filled{border-style:solid;background:var(--code)}
/* #75 — THE STOP CALLOUT. The target marks it with a filled disc carrying a bar: at a glance,
   before any word is read, this is the one thing on the page that means halt. The disc is drawn
   here rather than shipped as an image, so the page stays self-contained; the bar is the disc's
   own `::after`, which is why the disc needs a positioning context.
   `aria-hidden` is unnecessary — a CSS `::before` is decoration and is not in the accessibility
   tree, and the callout's own heading already carries the meaning in words. */
.tpl-uat .ut-stop>.blk-callout{position:relative;border:1px solid var(--sev-crit);
border-left:4px solid var(--sev-crit);background:var(--sev-crit-bg);
border-radius:10px;padding:12px 14px 12px 42px}
.tpl-uat .ut-stop>.blk-callout::before{content:"";position:absolute;left:14px;top:14px;
width:16px;height:16px;border-radius:50%;background:var(--sev-crit)}
.tpl-uat .ut-stop>.blk-callout::after{content:"";position:absolute;left:18px;top:21px;
width:8px;height:2px;border-radius:1px;background:var(--sev-crit-bg)}
.tpl-uat .ut-export{background:var(--surface);border:1px solid var(--line);
border-left:4px solid var(--accent);border-radius:14px;padding:6px 20px 20px;margin:32px 0 0}
.tpl-uat .ut-btn{font:700 14px ui-monospace,Menlo,Consolas,monospace;cursor:pointer;
border:none;border-radius:12px;padding:12px 20px;color:var(--bg);background:var(--accent)}
.tpl-uat .ut-said{margin-left:12px;font-size:13px;color:var(--ink-2)}
/* `[hidden]` must win. The rule below sets `display:block` unconditionally, which overrides
   the HTML `hidden` attribute the export textarea ships with — so the fallback box rendered as
   a permanently visible empty panel under the button instead of appearing only when the
   clipboard is refused. Pre-existing (identical at this PR's base) and uat-only, so it is fixed
   here as a one-line adjacent win rather than filed. Revert: delete this single rule. */
.tpl-uat .ut-out[hidden]{display:none}
.tpl-uat .ut-out{display:block;width:100%;margin-top:14px;
font:12px/1.5 ui-monospace,Menlo,Consolas,monospace;color:var(--ink);background:var(--code);
border:1px solid var(--line);border-radius:10px;padding:10px 12px}
"""
