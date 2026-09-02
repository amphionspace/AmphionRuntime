#!/usr/bin/env bash
set -euo pipefail
# =============================================================================
# build_arm64_slim_icu.sh — cross-build the slim ICU 78.1 data library for
# aarch64 / OHOS, using the same verified filter (scripts/icu_tn_data_filter.json).
#
# VERIFIED with OHOS Native SDK 5.0.2 (aarch64-unknown-linux-ohos-clang++) on
# macOS arm64 (Rosetta): produces libicudata.a = 2.55 MB. Relinking en_tts/zh_tts
# against it (vendored OHOS libicui18n/uc unchanged) gives arm64 binaries
# 35.97 MB -> 6.92 MB (.rodata 33.56 MB -> 3.14 MB), TN output byte-identical
# (proven on host, same slim icudt78l.dat bytes).
#
# Required:
#   OHOS_NATIVE_SDK   path to the extracted OHOS 'native' dir (has llvm/bin/...)
#   ICU_SOURCES_TGZ   icu4c-78.1-sources.tgz
#   ICU_DATA_ZIP      icu4c-78.1-data.zip
# Optional:
#   OUT_DIR           default: tts/harmony/build-ohos-tn/arm64-slim-icu
# =============================================================================
: "${OHOS_NATIVE_SDK:?path to OHOS native SDK dir}"
: "${ICU_SOURCES_TGZ:?icu4c-78.1-sources.tgz}"
: "${ICU_DATA_ZIP:?icu4c-78.1-data.zip}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FILTER="$REPO/scripts/icu_tn_data_filter.json"
OUT_DIR="${OUT_DIR:-$REPO/tts/harmony/build-ohos-tn/arm64-slim-icu}"
TOOL="$OHOS_NATIVE_SDK/llvm/bin"
W="$OUT_DIR/work"; rm -rf "$W"; mkdir -p "$W"

# 1) host ICU (from-source, no filter) — provides the cross-build tool reference
tar xzf "$ICU_SOURCES_TGZ" -C "$W"; HOST="$W/icu-host"; mv "$W/icu" "$HOST"
rm -f "$HOST/source/data/in/icudt78l.dat"; unzip -oq "$ICU_DATA_ZIP" -d "$HOST/source"
rm -f "$HOST/source/data/in/icudt78l.dat"
( cd "$HOST/source" && chmod +x runConfigureICU configure config.* install-sh 2>/dev/null || true
  ./runConfigureICU MacOSX --enable-static --disable-shared --disable-samples --disable-tests --disable-extras --disable-icuio >/dev/null
  make -j"$(sysctl -n hw.ncpu)" >/dev/null )

# 2) cross ICU for aarch64-linux-ohos, filtered data
tar xzf "$ICU_SOURCES_TGZ" -C "$W"; CROSS="$W/icu-cross"; mv "$W/icu" "$CROSS"
rm -f "$CROSS/source/data/in/icudt78l.dat"; unzip -oq "$ICU_DATA_ZIP" -d "$CROSS/source"
rm -f "$CROSS/source/data/in/icudt78l.dat"
( cd "$CROSS/source" && chmod +x runConfigureICU configure config.* install-sh 2>/dev/null || true
  export ICU_DATA_FILTER_FILE="$FILTER"
  export CC="$TOOL/aarch64-unknown-linux-ohos-clang" CXX="$TOOL/aarch64-unknown-linux-ohos-clang++"
  export AR="$TOOL/llvm-ar" RANLIB="$TOOL/llvm-ranlib" STRIP="$TOOL/llvm-strip"
  ./configure --host=aarch64-linux-ohos --with-cross-build="$HOST/source" --prefix="$OUT_DIR" \
    --enable-static --disable-shared --disable-samples --disable-tests --disable-extras --disable-icuio \
    --with-data-packaging=static CFLAGS="-O2" CXXFLAGS="-O2 -std=c++17"
  make -j"$(sysctl -n hw.ncpu)"; make install )

echo ">> arm64 slim ICU data:"; ls -la "$OUT_DIR/lib/libicudata.a"
echo ">> stage a lib dir for relink (slim data + vendored OHOS code libs):"
STAGE="$OUT_DIR/link-libs"; mkdir -p "$STAGE"
cp "$OUT_DIR/lib/libicudata.a" "$STAGE/"
cp "$REPO/tts/harmony/sdk/src/main/cpp/third_party/ohos-icu/lib/libicui18n.a" "$STAGE/"
cp "$REPO/tts/harmony/sdk/src/main/cpp/third_party/ohos-icu/lib/libicuuc.a" "$STAGE/"
echo ">> then:  SLIM_ICU_LIB_DIR=$STAGE OHOS_NATIVE_SDK=$OHOS_NATIVE_SDK scripts/build_dingqiao_harmony_tn.sh"
echo ">> NOTE: to match the delivered binary shape (static libc++, interpreter"
echo ">>       /system/bin/linker64) on stock SDKs, add -static-libstdc++ and"
echo ">>       -Wl,--dynamic-linker=/system/bin/linker64 to the link (see tts/docs/optimization/TN_SIZE_OPT_REPORT.md §7)."
