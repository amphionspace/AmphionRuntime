#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# build_slim_icu_data.sh  —  build a TN-subset ICU 78.1 data library
# =============================================================================
# Produces a slim libicudata.a containing only the ICU data the TN engine loads:
#   RBNF spellout (en/zh/root) + locale bundles (en/zh) + misc/supplemental +
#   currency (REQUIRED by RBNF's DecimalFormatSymbols) + core uprops/nfc/regex.
# Everything else (coll, brkitr, ~700 other locales, units, zones, regions,
# languages, transliterators, converters) is dropped via ICU_DATA_FILTER_FILE.
#
# Filter spec: tts/tools/tn/icu_tn_data_filter.json
# Report: tts/docs/optimization/TN_SIZE_OPT_REPORT.md
#
# The HOST recipe below was executed and VERIFIED on macOS arm64: it yields
# libicudata 31.57MB -> 2.55MB and byte-identical TN output vs full ICU across
# 4426 corpus lines. For the actual arm64/OHOS delivery, run the SAME recipe
# with runConfigureICU targeting the cross toolchain (see "TARGET" note), then
# feed the result to build_dingqiao_harmony_tn.sh via SLIM_ICU_LIB_DIR.
#
# WARNING: do NOT drop curr_tree from the filter. Without it the RBNF spellout
# constructor fails (U_MISSING_RESOURCE_ERROR) and every number silently
# normalizes to an empty string. This is invisible to a build/smoke check and
# only shows up in an output diff.
# =============================================================================

usage() {
  cat <<'EOF'
Required:
  ICU_SOURCES_TGZ  Path to icu4c-78.1-sources.tgz   (unicode-org/icu release-78.1)
  ICU_DATA_ZIP     Path to icu4c-78.1-data.zip       (raw data sources, same release)
Optional:
  OUT_DIR          Output prefix (default: tts/harmony/build-ohos-tn/slim-icu)
  ICU_PLATFORM     runConfigureICU platform (default: MacOSX). For the delivery,
                   use the OHOS cross build instead (see TARGET note in-file).

Example (host verification build):
  ICU_SOURCES_TGZ=~/dl/icu4c-78.1-sources.tgz \
  ICU_DATA_ZIP=~/dl/icu4c-78.1-data.zip \
  tts/tools/tn/build_slim_icu_data.sh
EOF
}
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then usage; exit 0; fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
FILTER_FILE="$REPO_ROOT/tts/tools/tn/icu_tn_data_filter.json"
OUT_DIR="${OUT_DIR:-$REPO_ROOT/tts/harmony/build-ohos-tn/slim-icu}"
ICU_PLATFORM="${ICU_PLATFORM:-MacOSX}"
: "${ICU_SOURCES_TGZ:?set ICU_SOURCES_TGZ to icu4c-78.1-sources.tgz}"
: "${ICU_DATA_ZIP:?set ICU_DATA_ZIP to icu4c-78.1-data.zip}"
[[ -f "$FILTER_FILE" ]] || { echo "Missing filter: $FILTER_FILE" >&2; exit 1; }

WORK="$OUT_DIR/work"
rm -rf "$WORK" && mkdir -p "$WORK" "$OUT_DIR/lib"

echo ">> unpacking ICU sources + raw data"
tar xzf "$ICU_SOURCES_TGZ" -C "$WORK"          # -> $WORK/icu
SRC="$WORK/icu/source"
# Force a FROM-SOURCE data build (the prebuilt data/in/icudt78l.dat would
# bypass the filter). Drop in the raw data sources, remove the prebuilt blob.
rm -f "$SRC/data/in/icudt78l.dat"
unzip -oq "$ICU_DATA_ZIP" -d "$SRC"            # -> $SRC/data/{locales,rbnf,curr,misc,...}
rm -f "$SRC/data/in/icudt78l.dat"

echo ">> configure + build filtered data ($ICU_PLATFORM)"
cd "$SRC"
chmod +x runConfigureICU configure config.guess config.sub install-sh 2>/dev/null || true
# TARGET/OHOS: replace the runConfigureICU line with an ICU cross-build:
#   1. build ICU once for the host to get the data tools, then
#   2. ./configure --host=aarch64-linux-ohos --with-cross-build=<hostbuild> \
#        CC=.../aarch64-unknown-linux-ohos-clang CXX=.../...-clang++ \
#        --enable-static --disable-shared ...   (ICU_DATA_FILTER_FILE still set)
export ICU_DATA_FILTER_FILE="$FILTER_FILE"
CXXFLAGS="-O2 -std=c++17" CFLAGS="-O2" \
  ./runConfigureICU "$ICU_PLATFORM" --prefix="$OUT_DIR" \
  --enable-static --disable-shared --disable-samples --disable-tests --disable-extras --disable-icuio
make -j"$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu)"
make install

echo ">> slim ICU data ready:"
ls -la "$OUT_DIR/lib/libicudata.a"
echo ">> next: SLIM_ICU_LIB_DIR=$OUT_DIR/lib OHOS_NATIVE_SDK=<sdk> tts/tools/tn/build_dingqiao_harmony_tn.sh"
echo ">> then run tts/tools/tn/icu_slim/verify_zero_regression.sh before shipping."
