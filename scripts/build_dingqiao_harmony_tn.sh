#!/usr/bin/env bash
set -euo pipefail

# Build the HarmonyOS arm64 TN frontend executables from the submodule source.
# The HarmonyOS native SDK is supplied by DevEco Studio and is passed explicitly.

usage() {
  cat <<'EOF'
Usage:
  OHOS_NATIVE_SDK=/path/to/openharmony/native \
  scripts/build_dingqiao_harmony_tn.sh

Optional environment variables:
  HARMONY_TN_OUTPUT_DIR  Output directory (default: tts/harmony/build-ohos-tn)
  SLIM_ICU_LIB_DIR       Directory holding a slimmed libicudata.a/libicui18n.a/
                         libicuuc.a (see scripts/build_slim_icu_data.sh). When
                         unset, links the vendored full ohos-icu libs exactly as
                         before — this override changes nothing by default.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TN_ROOT="$REPO_ROOT/dingqiao_lits/Dingqiao_Multilingual_Text_Normalization_for_TTS"
OHOS_ICU_ROOT="$REPO_ROOT/tts/harmony/sdk/src/main/cpp/third_party/ohos-icu"
OUTPUT_DIR="${HARMONY_TN_OUTPUT_DIR:-$REPO_ROOT/tts/harmony/build-ohos-tn}"
OHOS_NATIVE_SDK="${OHOS_NATIVE_SDK:-}"

# Directory of the ICU archives to link. Defaults to the vendored full libs;
# point SLIM_ICU_LIB_DIR at a TN-subset build to shrink .rodata (headers are
# taken from OHOS_ICU_ROOT/include regardless — the API surface is unchanged).
ICU_LIB_DIR="${SLIM_ICU_LIB_DIR:-$OHOS_ICU_ROOT/lib}"

if [[ -z "$OHOS_NATIVE_SDK" ]]; then
  printf 'Set OHOS_NATIVE_SDK to the DevEco OpenHarmony native SDK directory.\n' >&2
  exit 1
fi

CXX="$OHOS_NATIVE_SDK/llvm/bin/aarch64-unknown-linux-ohos-clang++"
STRIP="$OHOS_NATIVE_SDK/llvm/bin/llvm-strip"
for required in "$CXX" "$STRIP" "$TN_ROOT/zh.cpp" "$TN_ROOT/en.cpp" \
  "$TN_ROOT/tts_normalizer_engine.cpp" "$TN_ROOT/ru_year_spellout.cpp" \
  "$OHOS_ICU_ROOT/include/unicode/utypes.h" "$ICU_LIB_DIR/libicui18n.a" \
  "$ICU_LIB_DIR/libicuuc.a" "$ICU_LIB_DIR/libicudata.a"; do
  if [[ ! -f "$required" ]]; then
    printf 'Missing file: %s\n' "$required" >&2
    exit 1
  fi
done

mkdir -p "$OUTPUT_DIR"
# The TN executable resolves its bundled rules relative to __FILE__. Map the
# source directory to the model-package root used as process cwd.
for language in zh en; do
  output="$OUTPUT_DIR/${language}_tts"
  "$CXX" \
    -std=c++17 -O2 -fPIE -fexceptions -frtti \
    "-ffile-prefix-map=$TN_ROOT=." \
    -I"$TN_ROOT" \
    -I"$TN_ROOT/third_party" \
    -I"$OHOS_ICU_ROOT/include" \
    "$TN_ROOT/$language.cpp" \
    "$TN_ROOT/tts_normalizer_engine.cpp" \
    "$TN_ROOT/ru_year_spellout.cpp" \
    -L"$ICU_LIB_DIR" \
    -Wl,--start-group -licui18n -licuuc -licudata -Wl,--end-group \
    -fPIE -pie \
    -o "$output"
  "$STRIP" "$output"
  chmod +x "$output"
done

printf 'HarmonyOS TN binaries: %s\n' "$OUTPUT_DIR"
file "$OUTPUT_DIR/zh_tts" "$OUTPUT_DIR/en_tts"
