#!/usr/bin/env bash
set -euo pipefail
# =============================================================================
# build_host_zh_tts.sh — rebuild the host (macOS) native TN binary the harness
# needs (zh_tts), from the TN submodule source + a host ICU 78.1 build.
#
# The binary loads rules_v2/*.json at RUNTIME from the submodule, so you only
# need to rebuild it when the C++ engine (tts_normalizer_engine.cpp / zh.cpp)
# changes — NOT when you edit rules_v2 JSON.
#
# Usage:
#   tts/tools/tn/pronunciation_fix/g2p_score/build_host_zh_tts.sh
#   # then: export ZH_TTS=<printed path>   (score_all.py reads $ZH_TTS)
#
# Env overrides:
#   OUT_DIR            build/output root (default: tts/training/dingqiao_lits/build/host-tn, gitignored)
#   ICU_SOURCES_TGZ    path to icu4c-78.1-sources.tgz (else auto-download)
#   FORCE=1            rebuild even if the binary already exists
#   BUILD_EN=1         also build en_tts
# =============================================================================
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../../.." && pwd)"
TN="$REPO/tts/training/dingqiao_lits/Dingqiao_Multilingual_Text_Normalization_for_TTS"
OUT_DIR="${OUT_DIR:-$REPO/tts/training/dingqiao_lits/build/host-tn}"
ICU_PREFIX="$OUT_DIR/icu-inst"
BIN="$OUT_DIR/zh_tts"

if [[ ! -f "$TN/zh.cpp" ]]; then
  echo "TN submodule not checked out. Run:" >&2
  echo "  git submodule update --init tts/training/dingqiao_lits/Dingqiao_Multilingual_Text_Normalization_for_TTS" >&2
  echo "  (private repo; the logged-in gh account needs access — HTTPS works via gh creds)" >&2
  exit 1
fi
mkdir -p "$OUT_DIR"

if [[ -x "$BIN" && "${FORCE:-0}" != "1" ]]; then
  echo "zh_tts already built (FORCE=1 to rebuild):"
  echo "  $BIN"
  echo "  export ZH_TTS=$BIN"
  exit 0
fi

# --- 1. host ICU 78.1 (static) ---
if [[ ! -f "$ICU_PREFIX/lib/libicudata.a" ]]; then
  echo ">> building host ICU 78.1 ..."
  SRC_TGZ="${ICU_SOURCES_TGZ:-$OUT_DIR/icu4c-78.1-sources.tgz}"
  if [[ ! -f "$SRC_TGZ" ]]; then
    echo ">> downloading ICU 78.1 sources ..."
    if command -v gh >/dev/null 2>&1; then
      ( cd "$OUT_DIR" && gh release download release-78.1 --repo unicode-org/icu \
          --pattern 'icu4c-78.1-sources.tgz' --clobber )
      SRC_TGZ="$OUT_DIR/icu4c-78.1-sources.tgz"
    else
      curl -fL -o "$SRC_TGZ" \
        "https://github.com/unicode-org/icu/releases/download/release-78.1/icu4c-78.1-sources.tgz"
    fi
  fi
  rm -rf "$OUT_DIR/icu"; tar xzf "$SRC_TGZ" -C "$OUT_DIR"
  ( cd "$OUT_DIR/icu/source"
    chmod +x runConfigureICU configure config.guess config.sub install-sh 2>/dev/null || true
    CXXFLAGS="-O2 -std=c++17" CFLAGS="-O2" ./runConfigureICU MacOSX \
      --prefix="$ICU_PREFIX" --enable-static --disable-shared \
      --disable-samples --disable-tests --disable-extras --disable-icuio >/dev/null
    make -j"$(sysctl -n hw.ncpu)" >/dev/null
    make install >/dev/null )
fi

# --- 2. link the TN binary(ies) ---
build_one() {
  local lang="$1" out="$2"
  g++ -std=c++17 -O2 \
    "$TN/$lang.cpp" "$TN/tts_normalizer_engine.cpp" "$TN/ru_year_spellout.cpp" \
    -I"$TN" -I"$TN/third_party" -I"$ICU_PREFIX/include" \
    -L"$ICU_PREFIX/lib" -licui18n -licuuc -licudata \
    -o "$out"
  echo "  built $out ($(stat -f%z "$out") bytes)"
}
echo ">> building TN binary(ies) ..."
build_one zh "$BIN"
[[ "${BUILD_EN:-0}" == "1" ]] && build_one en "$OUT_DIR/en_tts"

echo
echo "DONE. Point the harness at it:"
echo "  export ZH_TTS=$BIN"
echo "  cd $REPO/tts/tools/tn/pronunciation_fix/g2p_score && python3 score_all.py"
