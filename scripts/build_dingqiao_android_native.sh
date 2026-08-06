#!/usr/bin/env bash
set -euo pipefail

# Build the Android arm64 ICU static libraries and, when the legacy TN CLI
# entry points exist, the two TN frontend binaries.
# All paths are derived from this checkout or supplied explicitly by the caller.

usage() {
  cat <<'EOF'
Usage:
  ANDROID_NDK=/path/to/ndk \
  ICU_SOURCE_ARCHIVE=/path/to/icu4c-78.1-sources.tgz \
  scripts/build_dingqiao_android_native.sh

Optional environment variables:
  ANDROID_API_LEVEL       Android API level (default: 24)
  ICU_SOURCE_DIR          ICU source directory containing configure; skips archive extraction
  DINGQIAO_NATIVE_BUILD_ROOT  Build root (default: dingqiao_lits/build/android-icu)
  TN_ANDROID_OUTPUT_DIR   TN output directory (default: dingqiao_lits/e2e_infer/bin-android-arm64)
  LITS_ANDROID_SLIM_ICU   Set to 1/true to build ICU with scripts/icu_tn_data_filter.json
  ICU_DATA_ZIP            Required with LITS_ANDROID_SLIM_ICU; raw ICU 78.1 data zip
  BUILD_TN_BINARIES       auto/1/0 (default: auto). auto builds only if zh.cpp/en.cpp exist.
  BUILD_JOBS              Parallel make jobs (default: system CPU count)
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TN_ROOT="$REPO_ROOT/dingqiao_lits/Dingqiao_Multilingual_Text_Normalization_for_TTS"
BUILD_ROOT="${DINGQIAO_NATIVE_BUILD_ROOT:-$REPO_ROOT/dingqiao_lits/build/android-icu}"
TN_OUTPUT_DIR="${TN_ANDROID_OUTPUT_DIR:-$REPO_ROOT/dingqiao_lits/e2e_infer/bin-android-arm64}"
ANDROID_API_LEVEL="${ANDROID_API_LEVEL:-24}"
BUILD_JOBS="${BUILD_JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)}"
LITS_ANDROID_SLIM_ICU="${LITS_ANDROID_SLIM_ICU:-0}"
BUILD_TN_BINARIES="${BUILD_TN_BINARIES:-auto}"

require_file() {
  if [[ ! -f "$1" ]]; then
    printf 'Missing file: %s\n' "$1" >&2
    exit 1
  fi
}

require_dir() {
  if [[ ! -d "$1" ]]; then
    printf 'Missing directory: %s\n' "$1" >&2
    exit 1
  fi
}

require_dir "$TN_ROOT"
require_file "$TN_ROOT/tts_normalizer_engine.cpp"
require_file "$TN_ROOT/ru_year_spellout.cpp"

case "$BUILD_TN_BINARIES" in
  auto)
    if [[ -f "$TN_ROOT/zh.cpp" && -f "$TN_ROOT/en.cpp" ]]; then
      BUILD_TN_BINARIES=1
    else
      BUILD_TN_BINARIES=0
    fi
    ;;
  1|true|TRUE|yes|YES) BUILD_TN_BINARIES=1 ;;
  0|false|FALSE|no|NO) BUILD_TN_BINARIES=0 ;;
  *) printf 'Invalid BUILD_TN_BINARIES: %s\n' "$BUILD_TN_BINARIES" >&2; exit 1 ;;
esac

if [[ "$BUILD_TN_BINARIES" == 1 ]]; then
  require_file "$TN_ROOT/zh.cpp"
  require_file "$TN_ROOT/en.cpp"
fi

ANDROID_NDK="${ANDROID_NDK:-}"
if [[ -z "$ANDROID_NDK" ]]; then
  printf 'Set ANDROID_NDK to the installed Android NDK directory.\n' >&2
  exit 1
fi
require_dir "$ANDROID_NDK/toolchains/llvm/prebuilt"

case "$(uname -s):$(uname -m)" in
  Darwin:*) HOST_TAG_CANDIDATES=(darwin-arm64 darwin-x86_64) ;;
  Linux:x86_64) HOST_TAG_CANDIDATES=(linux-x86_64) ;;
  *) printf 'Unsupported host platform: %s:%s\n' "$(uname -s)" "$(uname -m)" >&2; exit 1 ;;
esac

NDK_BIN=""
for host_tag in "${HOST_TAG_CANDIDATES[@]}"; do
  candidate="$ANDROID_NDK/toolchains/llvm/prebuilt/$host_tag/bin"
  if [[ -x "$candidate/aarch64-linux-android${ANDROID_API_LEVEL}-clang++" ]]; then
    NDK_BIN="$candidate"
    break
  fi
done
if [[ -z "$NDK_BIN" ]]; then
  printf 'Could not find an Android NDK clang++ toolchain under: %s/toolchains/llvm/prebuilt\n' "$ANDROID_NDK" >&2
  exit 1
fi

ANDROID_TRIPLE="aarch64-linux-android"
ANDROID_CC="$NDK_BIN/${ANDROID_TRIPLE}${ANDROID_API_LEVEL}-clang"
ANDROID_CXX="$NDK_BIN/${ANDROID_TRIPLE}${ANDROID_API_LEVEL}-clang++"
ANDROID_AR="$NDK_BIN/llvm-ar"
ANDROID_RANLIB="$NDK_BIN/llvm-ranlib"
ANDROID_STRIP="$NDK_BIN/llvm-strip"
require_file "$ANDROID_CXX"

ICU_SOURCE_DIR="${ICU_SOURCE_DIR:-}"
if [[ -z "$ICU_SOURCE_DIR" ]]; then
  ICU_SOURCE_ARCHIVE="${ICU_SOURCE_ARCHIVE:-}"
  require_file "$ICU_SOURCE_ARCHIVE"
  ICU_SOURCE_DIR="$BUILD_ROOT/icu/source"
  if [[ ! -x "$ICU_SOURCE_DIR/configure" ]]; then
    rm -rf "$BUILD_ROOT/icu"
    mkdir -p "$BUILD_ROOT/source-archive"
    tar -xzf "$ICU_SOURCE_ARCHIVE" -C "$BUILD_ROOT/source-archive"
    extracted_source="$(find "$BUILD_ROOT/source-archive" -type f -path '*/source/configure' -print -quit)"
    if [[ -z "$extracted_source" ]]; then
      printf 'ICU archive does not contain */source/configure: %s\n' "$ICU_SOURCE_ARCHIVE" >&2
      exit 1
    fi
    archive_root="$(dirname "$(dirname "$extracted_source")")"
    cp -R "$archive_root" "$BUILD_ROOT/icu"
  fi
fi
require_file "$ICU_SOURCE_DIR/configure"

ICU_DATA_FILTER_FILE=""
if [[ "$LITS_ANDROID_SLIM_ICU" == 1 || "$LITS_ANDROID_SLIM_ICU" == true || "$LITS_ANDROID_SLIM_ICU" == TRUE ]]; then
  ICU_DATA_ZIP="${ICU_DATA_ZIP:-}"
  require_file "$ICU_DATA_ZIP"
  ICU_DATA_FILTER_FILE="$REPO_ROOT/scripts/icu_tn_data_filter.json"
  require_file "$ICU_DATA_FILTER_FILE"
  rm -f "$ICU_SOURCE_DIR/data/in/icudt78l.dat"
  unzip -oq "$ICU_DATA_ZIP" -d "$ICU_SOURCE_DIR"
  rm -f "$ICU_SOURCE_DIR/data/in/icudt78l.dat"
fi

HOST_BUILD="$BUILD_ROOT/host-build"
HOST_INSTALL="$BUILD_ROOT/host-install"
ANDROID_BUILD="$BUILD_ROOT/android-arm64-build"
ANDROID_INSTALL="$BUILD_ROOT/android-arm64-install"

mkdir -p "$BUILD_ROOT"
if [[ ! -f "$HOST_BUILD/config.status" ]]; then
  rm -rf "$HOST_BUILD"
  mkdir -p "$HOST_BUILD"
  (
    cd "$HOST_BUILD"
    "$ICU_SOURCE_DIR/configure" \
      --prefix="$HOST_INSTALL" \
      --disable-samples \
      --disable-tests \
      --enable-static \
      --disable-shared \
      --with-data-packaging=static
  )
fi
make -C "$HOST_BUILD" -j"$BUILD_JOBS"
make -C "$HOST_BUILD" install

if [[ ! -f "$ANDROID_BUILD/config.status" ]]; then
  rm -rf "$ANDROID_BUILD"
  mkdir -p "$ANDROID_BUILD"
  (
    cd "$ANDROID_BUILD"
    if [[ -n "$ICU_DATA_FILTER_FILE" ]]; then
      export ICU_DATA_FILTER_FILE
    fi
    CC="$ANDROID_CC" \
    CXX="$ANDROID_CXX" \
    AR="$ANDROID_AR" \
    RANLIB="$ANDROID_RANLIB" \
    "$ICU_SOURCE_DIR/configure" \
      --host="$ANDROID_TRIPLE" \
      --with-cross-build="$HOST_BUILD" \
      --prefix="$ANDROID_INSTALL" \
      --disable-samples \
      --disable-tests \
      --enable-static \
      --disable-shared \
      --with-data-packaging=static \
      CFLAGS=-fPIC \
      CXXFLAGS='-fPIC -std=c++17'
  )
fi
make -C "$ANDROID_BUILD" -j"$BUILD_JOBS"
make -C "$ANDROID_BUILD" install

for library in libicui18n.a libicuuc.a libicudata.a; do
  require_file "$ANDROID_BUILD/lib/$library"
done
require_file "$ANDROID_INSTALL/include/unicode/utypes.h"

if [[ "$BUILD_TN_BINARIES" == 1 ]]; then
  mkdir -p "$TN_OUTPUT_DIR"
  # The TN executable resolves its bundled rules relative to __FILE__. Map the
  # source directory to the model-package root used as process cwd.
  for language in zh en; do
    output="$TN_OUTPUT_DIR/${language}_tts"
    "$ANDROID_CXX" \
      -std=c++17 -O2 -fPIE -fexceptions -frtti \
      "-ffile-prefix-map=$TN_ROOT=." \
      -I"$TN_ROOT" \
      -I"$TN_ROOT/third_party" \
      -I"$ANDROID_INSTALL/include" \
      "$TN_ROOT/$language.cpp" \
      "$TN_ROOT/tts_normalizer_engine.cpp" \
      "$TN_ROOT/ru_year_spellout.cpp" \
      -L"$ANDROID_BUILD/lib" \
      -Wl,--start-group -licui18n -licuuc -licudata -Wl,--end-group \
      -static-libstdc++ -fPIE -pie \
      -o "$output"
    "$ANDROID_STRIP" "$output"
    chmod +x "$output"
  done
fi

printf 'Android ICU: %s\n' "$ANDROID_INSTALL"
if [[ -n "$ICU_DATA_FILTER_FILE" ]]; then
  printf 'Android ICU data filter: %s\n' "$ICU_DATA_FILTER_FILE"
fi
if [[ "$BUILD_TN_BINARIES" == 1 ]]; then
  printf 'Android TN binaries: %s\n' "$TN_OUTPUT_DIR"
  file "$TN_OUTPUT_DIR/zh_tts" "$TN_OUTPUT_DIR/en_tts"
else
  printf 'Android TN binaries: skipped (BUILD_TN_BINARIES=0; JNI build uses ICU libs via Gradle/CMake)\n'
fi
