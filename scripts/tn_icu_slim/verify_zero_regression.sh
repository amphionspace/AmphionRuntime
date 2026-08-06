#!/usr/bin/env bash
set -uo pipefail
# =============================================================================
# verify_zero_regression.sh — prove ICU-data slimming does not change TN output.
#
# Builds the en/zh TN drivers TWICE (against a full-ICU prefix and a slim-ICU
# prefix, same ICU 78.1, same TN source/rules) and diffs their normalized
# output byte-for-byte over the regression corpora. The gate is FULL == SLIM.
#
# Usage:
#   FULL_ICU=/path/to/inst-full  SLIM_ICU=/path/to/inst-slim \
#   scripts/tn_icu_slim/verify_zero_regression.sh
#
# Notes:
#  - Run on the host (macOS/Linux) with g++ + the two ICU prefixes from
#    scripts/build_slim_icu_data.sh (build one full, one slim).
#  - The submodule test/expected/*.golden are STALE vs the current rules_v2
#    (even full-ICU differs from them), so they are NOT used as the oracle;
#    the sound oracle is full-vs-slim identity.
# =============================================================================
: "${FULL_ICU:?set FULL_ICU to a full ICU 78.1 install prefix}"
: "${SLIM_ICU:?set SLIM_ICU to the slim ICU 78.1 install prefix}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
TN="$REPO/dingqiao_lits/Dingqiao_Multilingual_Text_Normalization_for_TTS"
[[ -f "$TN/en.cpp" ]] || { echo "TN submodule not checked out at $TN" >&2; exit 1; }
WORK="${WORK:-$HERE/.verify-work}"; mkdir -p "$WORK/bin" "$WORK/out" "$WORK/in"

build() { # locale icu-prefix out
  g++ -std=c++17 -O2 "$TN/$1.cpp" "$TN/tts_normalizer_engine.cpp" "$TN/ru_year_spellout.cpp" \
    -I"$TN" -I"$TN/third_party" -I"$2/include" -L"$2/lib" -licui18n -licuuc -licudata -o "$3"
}
for L in en zh; do build "$L" "$FULL_ICU" "$WORK/bin/${L}_full" && build "$L" "$SLIM_ICU" "$WORK/bin/${L}_slim" || exit 1; done

# Build the corpus: TN test inputs + spellout stress + (if present) SDK stability/golden texts.
cp "$TN/test/in/en.txt" "$WORK/in/en_basic.txt" 2>/dev/null || true
cp "$TN/test/in/zh.txt" "$TN/test/in/zh_car_plates.txt" "$WORK/in/" 2>/dev/null || true
cp "$HERE/spellout_en.txt" "$HERE/spellout_zh.txt" "$WORK/in/" 2>/dev/null || true
python3 - "$REPO/tts/android/testdata/dingqiao_batch_cases" "$WORK/in/corpus_stability.txt" <<'PY' 2>/dev/null || true
import json,sys,glob,os
d,out=sys.argv[1],sys.argv[2]; seen=set(); L=[]
for f in sorted(glob.glob(os.path.join(d,"*.jsonl"))):
  for ln in open(f,encoding="utf-8"):
    try: t=json.loads(ln).get("text")
    except: t=None
    if isinstance(t,str):
      t=" ".join(t.split());
      if t and t not in seen: seen.add(t); L.append(t)
open(out,"w",encoding="utf-8").write("\n".join(L)+"\n") if L else None
PY

echo "### full-ICU vs slim-ICU  (must be byte-identical) ###"
fails=0; njobs=0; lines=0
run() { # locale infile
  local L="$1" IN="$2" tag; [ -f "$IN" ] || return 0
  tag="$L:$(basename "$IN")"; local of="$WORK/out/$tag.full" sf="$WORK/out/$tag.slim"
  "$WORK/bin/${L}_full" <"$IN" >"$of" 2>/dev/null; "$WORK/bin/${L}_slim" <"$IN" >"$sf" 2>/dev/null
  local n; n=$(wc -l <"$IN"|tr -d ' '); njobs=$((njobs+1)); lines=$((lines+n))
  if diff -q "$of" "$sf" >/dev/null; then echo "  OK   $tag ($n)"; else echo "  DIFF $tag ($n) <<< REGRESSION"; diff "$of" "$sf"|head; fails=$((fails+1)); fi
}
for f in "$WORK"/in/en_basic.txt "$WORK"/in/spellout_en.txt "$WORK"/in/corpus_stability.txt; do run en "$f"; done
for f in "$WORK"/in/zh.txt "$WORK"/in/zh_car_plates.txt "$WORK"/in/spellout_zh.txt "$WORK"/in/corpus_stability.txt; do run zh "$f"; done

echo "### latency (best of 3, stability corpus) ###"
for L in en zh; do for v in full slim; do
  [ -f "$WORK/in/corpus_stability.txt" ] || continue; best=99999
  for r in 1 2 3; do t=$({ /usr/bin/time -p "$WORK/bin/${L}_${v}" <"$WORK/in/corpus_stability.txt" >/dev/null; } 2>&1|awk '/^real/{print $2}'); awk -v a="$t" -v b="$best" 'BEGIN{exit !(a<b)}'&&best="$t"; done
  echo "  ${L}_${v}: ${best}s"
done; done

echo "==== jobs=$njobs lines=$lines regressions=$fails ===="
[ "$fails" -eq 0 ] && { echo "PASS: zero-regression (full-ICU == slim-ICU)"; exit 0; } || { echo "FAIL"; exit 1; }
