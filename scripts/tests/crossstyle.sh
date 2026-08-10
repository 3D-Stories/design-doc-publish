#!/usr/bin/env bash
# Cross-style byte check (#40, reworked by #42).
#
# Renders one component-exercising fixture through every style each tree KNOWS, at the branch base
# and at HEAD, and reports which styles' bytes moved. A template-rebuild PR must move its target
# style and NOTHING else; `plain` moving is an AC2 failure.
#
# This exists because the obvious check — "the committed exemplar's diff is empty" — is a no-op:
# that fixture has no typed component block, so feature CSS can never reach it.
#
# usage: scripts/tests/crossstyle.sh <head-tree> <base-tree> <outdir> <mode>
#
#   <target-style>      exactly that style may move; anything else fails. The target may be a
#                       style HEAD has and base does not — a new-style PR — in which case it must
#                       actually RENDER something, and no existing style may move.
#                       #90: may be a COMMA-SEPARATED list (`roadmap,dashboard,analysis`) for a
#                       fix inside a resolver several templates share. EVERY style listed must
#                       move and nothing else may, so naming three is still a precise claim —
#                       unlike `--foundation`, which permits all of them.
#   --foundation        the T0 relocation commit only: every rich style is expected to move, and
#                       `plain` still may not.
#   --no-style-change   shared tooling only: nothing may move, be added, or be removed. The ONLY
#                       mode in which "nothing moved" is a pass.
#
# A mode is MANDATORY. An earlier version made the target optional and then printed OK
# unconditionally in that mode. That is a false green, and it produced one before review caught it.
#
# #42 removed the hard-coded ten-style roster: it could not check a PR adding an eleventh style at
# all, and an intersection-only replacement printed OK while an existing style had been DELETED
# from HEAD. Each tree's roster now comes from that tree's own `render-doc --help`, the comparison
# runs over the intersection, and what is only on one side has explicit rules.
# `scripts/tests/test_crossstyle_guards.py` pins every rule to the false green it prevents.
set -euo pipefail

HEAD_TREE=${1:?head tree required}
BASE_TREE=${2:?base tree required}
OUT=${3:?output dir required}
TARGET=${4:?mode required: a target style, --foundation, or --no-style-change}

STAMP="2026-08-02 00:00 MDT"
REL="."

# Each tree's roster comes from its OWN launcher, so a tree is never asked for a style it lacks.
# `--help` prints the choice list twice (usage line, then the option description); the first match
# is the whole list. An unreadable roster exits 2 — "the drift guard did not run" must never be
# silent, and must never degrade into "nothing moved, OK".
styles_of() {
  local doc="$1/$REL/scripts/render-doc"
  [ -f "$doc" ] || { echo "FAIL: no render-doc launcher at $doc"; exit 2; }
  local list=""
  list=$(python3 "$doc" --help 2>/dev/null | tr '\n' ' ' \
         | grep -o -- '--style {[^}]*}' | head -1 | sed 's/.*{//; s/}//; s/,/ /g') || true
  [ -n "$list" ] || { echo "FAIL: could not read the style roster from $doc"; exit 2; }
  echo "$list"
}

in_list() { case " $2 " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

HEAD_STYLES=$(styles_of "$HEAD_TREE")
BASE_STYLES=$(styles_of "$BASE_TREE")

COMMON=""; NEW=""; REMOVED=""
for s in $HEAD_STYLES; do
  if in_list "$s" "$BASE_STYLES"; then COMMON="$COMMON $s"; else NEW="$NEW $s"; fi
done
for s in $BASE_STYLES; do
  in_list "$s" "$HEAD_STYLES" || REMOVED="$REMOVED $s"
done
COMMON=${COMMON# }; NEW=${NEW# }; REMOVED=${REMOVED# }

echo "styles common to both trees: ${COMMON:-<none>}"
[ -n "$NEW" ] && echo "styles only at HEAD (new): $NEW" || true
[ -n "$REMOVED" ] && echo "styles only at BASE (removed): $REMOVED" || true

# The fixture comes from the BASE tree and is used for BOTH renders. If HEAD supplied it, a PR
# could weaken the fixture — drop the timeline block, say — and the leak it would have exposed
# simply vanishes from the probe while real documents still change. The base copy is the
# invariant; a fixture improvement takes effect from the next PR, which is the right direction.
FIXTURE="$BASE_TREE/$REL/scripts/tests/fixtures/crossstyle.md"
if [ ! -f "$FIXTURE" ]; then
  FIXTURE="$HEAD_TREE/$REL/scripts/tests/fixtures/crossstyle.md"
  echo "NOTE: base has no fixture — this is its introducing commit, using HEAD's copy."
  echo "      The anti-drift rule (always render the BASE fixture) applies from the next PR."
  [ -f "$FIXTURE" ] || { echo "FAIL: no fixture in base or head"; exit 2; }
fi

# Refuse to write into a directory that already holds anything: these are caller-supplied paths
# and every render is an unconditional truncation.
if [ -e "$OUT" ] && [ -n "$(ls -A "$OUT" 2>/dev/null || true)" ]; then
  echo "FAIL: $OUT exists and is not empty — pass a fresh directory"; exit 2
fi

failed_render=""
render_all() {                       # $1 = tree, $2 = destination dir, $3 = styles
  local doc="$1/$REL/scripts/render-doc"
  # `render-doc`, never `python3 -m render`: the cwd precedes PYTHONPATH on sys.path, so from
  # inside a scripts/ directory a bare `-m render` imports THAT tree's engine for both sides and
  # silently compares a tree with itself.
  [ -f "$doc" ] || { echo "FAIL: no render-doc launcher at $doc"; exit 2; }
  mkdir -p "$2"
  local s
  for s in $3; do
    # --doc-id keeps `uat` from warning about a title-slug localStorage key; it changes no other
    # style, and a fixed value keeps the two runs comparable.
    if ! python3 "$doc" --md "$FIXTURE" --out "$2/$s.html" --title "Cross-style probe" \
         --style "$s" --doc-id "crossstyle-probe" --generated-at "$STAMP" 2>"$2/$s.stderr"; then
      failed_render="$failed_render $s"
    fi
  done
}

render_all "$BASE_TREE" "$OUT/base" "$BASE_STYLES"
render_all "$HEAD_TREE" "$OUT/head" "$HEAD_STYLES"

sha256sum "$FIXTURE" | sed 's/^/fixture: /'

moved=""; errored=""
for s in $COMMON; do
  # `cmp -s` exits 1 for "differ" and 2 for "could not compare". Folding 2 into "differ" would
  # let a missing or unreadable render masquerade as an ordinary change.
  set +e; cmp -s "$OUT/base/$s.html" "$OUT/head/$s.html"; rc=$?; set -e
  case $rc in
    0) ;;
    1) moved="$moved $s" ;;
    *) errored="$errored $s" ;;
  esac
done
moved=${moved# }; errored=${errored# }

echo "styles whose bytes moved: ${moved:-<none>}"
rc=0
[ -n "$errored" ] && { echo "FAIL: could not compare: $errored"; rc=1; } || true

# A style vanishing from HEAD is exactly the regression this script exists to catch, in every
# mode. The intersection-only design had no rule for it and printed OK while `workflow` was gone.
[ -n "$REMOVED" ] && { echo "FAIL: styles removed at HEAD: $REMOVED"; rc=1; } || true
[ -z "$COMMON" ] && { echo "FAIL: the two trees share no styles — nothing was compared"; rc=1; } || true

case " $moved " in
  *" plain "*) echo "FAIL: plain moved — AC2 violation"; rc=1 ;;
esac

case "$TARGET" in
  --no-style-change)
    # Shared tooling only. The one mode where "nothing moved" is the pass condition — so it must
    # also prove the rosters are intact, or a removal would slip through AS "nothing moved".
    [ -n "$moved" ] && { echo "FAIL: --no-style-change, but these moved: $moved"; rc=1; } || true
    [ -n "$NEW" ] && { echo "FAIL: --no-style-change, but these were added: $NEW"; rc=1; } || true
    [ -n "$failed_render" ] && { echo "FAIL: a style failed to render:$failed_render"; rc=1; } || true
    ;;
  --foundation)
    # Every rich style is expected to move here; an unmoved one means the relocation missed it.
    # The old version asserted nothing at all and printed OK unconditionally.
    for s in $COMMON; do
      [ "$s" = "plain" ] && continue
      in_list "$s" "$moved" || { echo "FAIL: foundation expects $s to move; it did not"; rc=1; }
    done
    [ -n "$NEW" ] && { echo "FAIL: foundation adds no styles, but found: $NEW"; rc=1; } || true
    ;;
  *)
    # #90: the target may be a COMMA-SEPARATED list. A fix inside a resolver that several
    # templates share moves every style that shares it — `roadmap`, `dashboard` and `analysis`
    # all route through the one `chip_resolver` call — and there was no honest way to declare
    # that. `--foundation` was the only mode permitting more than one, and it permits ALL of
    # them, which would have laundered a real leak as an expected move. Naming the exact set
    # keeps the guard's precision: every style listed must move, and nothing else may.
    TARGETS=$(printf '%s' "$TARGET" | tr ',' ' ')

    # Any HEAD-only style that is not a declared target is unexpected, not a note. One was
    # reported as OK alongside a target that had never been rendered.
    for s in $NEW; do
      in_list "$s" "$TARGETS" && continue
      echo "FAIL: $s is new at HEAD but the target is $TARGET"; rc=1
    done
    for s in $moved; do
      [ "$s" = "plain" ] && continue
      in_list "$s" "$TARGETS" && continue
      echo "FAIL: $s moved but the target is $TARGET — a rule leaked out of its template"; rc=1
    done
    for t in $TARGETS; do
      if in_list "$t" "$NEW"; then
        # Being new is not itself the proof: it has to render, and to produce something.
        in_list "$t" "$failed_render" && { echo "FAIL: new style $t failed to render"; rc=1; } || true
        [ -s "$OUT/head/$t.html" ] || { echo "FAIL: new style $t rendered an empty file"; rc=1; }
      elif in_list "$t" "$COMMON"; then
        in_list "$t" "$moved" || {
          echo "FAIL: nothing moved, but this PR claims to rebuild $t — the change is inert"
          rc=1; }
      else
        echo "FAIL: target $t is not a style either tree knows"; rc=1
      fi
    done
    ;;
esac

[ $rc -eq 0 ] && echo "OK" || true
exit $rc
