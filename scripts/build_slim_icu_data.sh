#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# build_slim_icu_data.sh  —  PROPOSAL / UNVERIFIED
# =============================================================================
# Produce a SLIM libicudata.a for the Dingqiao TN frontend, keeping only the
# ICU data that the TN engine actually loads at runtime:
#
#   * RBNF spellout data for en + zh (+ root fallback)
#   * the locale resource bundles for en / zh
#   * core uprops/ucase/unorm (nfc) data — required by ICU regex; kept by default
#
# and dropping everything else (~700 locales, collation, break iterators,
# currency, units, timezones, transliterators, region/lang trees).
#
# See scripts/icu_tn_data_filter.json for the exact filter spec, and
# TN_SIZE_OPT_REPORT.md for how it was derived from the code's ICU call surface.
#
# STATUS: This script encodes the two supported build paths but has NOT been
# executed here — the OHOS Native SDK and ICU tools are absent in the dev box
# where the proposal was authored. It is meant to be run by someone who has:
#   - the OHOS Native SDK (aarch64-unknown-linux-ohos toolchain), AND
#   - either the ICU 78 source tree (Path A) or the ICU host tools
#     icupkg / pkgdata built for the host (Path B).
# After running, feed the resulting lib dir back into
# build_dingqiao_harmony_tn.sh via SLIM_ICU_LIB_DIR (see that script) and run
# the full zero-regression gate before shipping.
# =============================================================================

usage() {
  cat <<'EOF'
Two mutually exclusive paths — pick one via MODE:

  # Path A: rebuild ICU 78 data from source with ICU_DATA_FILTER_FILE (cleanest).
  MODE=source \
  ICU_SRC=/path/to/icu/icu4c/source \
  OHOS_NATIVE_SDK=/path/to/openharmony/native \
  scripts/build_slim_icu_data.sh

  # Path B: subset the ALREADY-VENDORED icudt78l.dat with icupkg, then repackage
  # for the target with pkgdata (no full ICU source rebuild).
  MODE=subset \
  ICUPKG=/path/to/host/bin/icupkg \
  PKGDATA=/path/to/host/bin/pkgdata \
  OHOS_NATIVE_SDK=/path/to/openharmony/native \
  scripts/build_slim_icu_data.sh

Output: $OUT_DIR/libicudata.a (default: tts/harmony/build-ohos-tn/slim-icu/lib)
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then usage; exit 0; fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FILTER_FILE="$REPO_ROOT/scripts/icu_tn_data_filter.json"
OHOS_ICU_ROOT="$REPO_ROOT/tts/harmony/sdk/src/main/cpp/third_party/ohos-icu"
OUT_DIR="${OUT_DIR:-$REPO_ROOT/tts/harmony/build-ohos-tn/slim-icu}"
MODE="${MODE:-}"

[[ -f "$FILTER_FILE" ]] || { echo "Missing filter: $FILTER_FILE" >&2; exit 1; }
mkdir -p "$OUT_DIR/lib"

case "$MODE" in
  source)
    : "${ICU_SRC:?set ICU_SRC to icu4c/source}"
    : "${OHOS_NATIVE_SDK:?set OHOS_NATIVE_SDK}"
    echo ">> Path A: rebuild ICU 78 data with data filter"
    echo "   ICU_DATA_FILTER_FILE=$FILTER_FILE"
    echo
    echo "   The canonical ICU cross-data build is:"
    echo "     1. Build ICU once for the HOST to get the data-gen tools."
    echo "     2. Reconfigure for the target (aarch64-unknown-linux-ohos) with"
    echo "        --with-cross-build=<host-build> and static data packaging,"
    echo "        exporting ICU_DATA_FILTER_FILE so only the TN subset is built."
    echo "     3. Copy the produced libicudata.a to \$OUT_DIR/lib."
    echo
    echo "   Verify the ICU 78 source version matches the vendored icudt78l."
    echo "   (Left as explicit manual steps — must not be guessed/automated blind.)"
    exit 3
    ;;
  subset)
    : "${ICUPKG:?set ICUPKG (host icupkg)}"
    : "${PKGDATA:?set PKGDATA (host pkgdata)}"
    : "${OHOS_NATIVE_SDK:?set OHOS_NATIVE_SDK}"
    echo ">> Path B: subset vendored icudt78l.dat with icupkg"
    echo "   1. Extract icudt78l_dat.o from $OHOS_ICU_ROOT/lib/libicudata.a and"
    echo "      recover the raw icudt78l.dat payload."
    echo "   2. '$ICUPKG -l' to list items; build a remove-list of every"
    echo "      coll/*, brkitr/*, curr/*, unit/*, zone/*, region/*, lang/*,"
    echo "      translit/* and every non en/zh/root locale .res."
    echo "   3. '$ICUPKG -r <removelist> icudt78l.dat icudt78l_slim.dat'."
    echo "   4. Repackage for the target with '$PKGDATA -m static' using the"
    echo "      OHOS aarch64 assembler → \$OUT_DIR/lib/libicudata.a."
    echo
    echo "   NOTE: the remove-list MUST be exhaustive; anything left in that TN"
    echo "   never loads is pure dead weight, anything wrongly removed that RBNF"
    echo "   spellout depends on will fail the regression gate. Keep root+en+zh"
    echo "   rbnf, keep uprops/ucase/nfc core, and validate before shipping."
    exit 3
    ;;
  *)
    echo "Set MODE=source or MODE=subset" >&2
    usage
    exit 1
    ;;
esac
