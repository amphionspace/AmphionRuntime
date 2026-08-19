#!/usr/bin/env bash
# Build the WebRTC AGC2 wrapper for host tests or one mobile ARM64 target.

set -euo pipefail

TARGET="${1:-host}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SOURCE_DIR="$REPO_ROOT/asr/native/audio-processing"
source "$SCRIPT_DIR/ensure_agc_build_tools.sh"
PACKAGE_CACHE="${MESON_PACKAGE_CACHE_DIR:-$SOURCE_DIR/subprojects/packagecache}"
mkdir -p "$PACKAGE_CACHE"
export MESON_PACKAGE_CACHE_DIR="$PACKAGE_CACHE"

setup_and_build() {
  local build_dir="$1"
  shift
  if [[ -f "$build_dir/build.ninja" ]]; then
    "$MESON" setup --reconfigure "$build_dir" "$SOURCE_DIR" "$@"
  else
    "$MESON" setup "$build_dir" "$SOURCE_DIR" "$@"
  fi
  "$MESON" compile -C "$build_dir"
}

case "$TARGET" in
  host)
    BUILD_DIR="$SOURCE_DIR/build-host"
    setup_and_build "$BUILD_DIR"
    "$MESON" test -C "$BUILD_DIR" --print-errorlogs
    ;;
  android-arm64-v8a)
    NDK_ROOT="${ANDROID_NDK_HOME:-${ANDROID_NDK_ROOT:-${ANDROID_NDK:-}}}"
    if [[ -z "$NDK_ROOT" || ! -d "$NDK_ROOT" ]]; then
      echo "[ERROR] set ANDROID_NDK_HOME to an Android NDK" >&2
      exit 1
    fi
    BUILD_DIR="$SOURCE_DIR/build-android-arm64-v8a"
    CROSS_FILE="$BUILD_DIR/android-arm64-v8a.ini"
    mkdir -p "$BUILD_DIR"
    case "$(uname -s)" in
      Darwin) NDK_HOST_TAG="darwin-x86_64" ;;
      Linux) NDK_HOST_TAG="linux-x86_64" ;;
      *)
        echo "[ERROR] unsupported Android NDK host: $(uname -s)" >&2
        exit 1
        ;;
    esac
    TOOLCHAIN="$NDK_ROOT/toolchains/llvm/prebuilt/$NDK_HOST_TAG/bin"
    ANDROID_PLATFORM="${ANDROID_PLATFORM:-android-24}"
    ANDROID_API="${ANDROID_PLATFORM#android-}"
    if [[ ! "$ANDROID_API" =~ ^[0-9]+$ ]]; then
      echo "[ERROR] invalid ANDROID_PLATFORM: $ANDROID_PLATFORM" >&2
      exit 1
    fi
    if [[ ! -x "$TOOLCHAIN/aarch64-linux-android${ANDROID_API}-clang++" ]]; then
      echo "[ERROR] Android NDK compiler not found under $TOOLCHAIN" >&2
      exit 1
    fi
    cat > "$CROSS_FILE" <<EOF
[binaries]
c = '$TOOLCHAIN/aarch64-linux-android${ANDROID_API}-clang'
cpp = '$TOOLCHAIN/aarch64-linux-android${ANDROID_API}-clang++'
ar = '$TOOLCHAIN/llvm-ar'
strip = '$TOOLCHAIN/llvm-strip'
[host_machine]
system = 'android'
cpu_family = 'aarch64'
cpu = 'armv8-a'
endian = 'little'
EOF
    setup_and_build "$BUILD_DIR" --cross-file "$CROSS_FILE"
    "$TOOLCHAIN/llvm-strip" "$BUILD_DIR/libamphion_audio_processing.so"
    ;;
  ohos-arm64-v8a)
    DEVECO_ROOT="${DEVECO_SDK_HOME:-/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony}"
    CLANG="$(find "$DEVECO_ROOT" -path '*/native/llvm/bin/aarch64-unknown-linux-ohos-clang' -type f | sort -V | tail -1)"
    if [[ -z "$CLANG" ]]; then
      echo "[ERROR] OpenHarmony native clang not found under $DEVECO_ROOT" >&2
      exit 1
    fi
    TOOLCHAIN="$(dirname "$CLANG")"
    BUILD_DIR="$SOURCE_DIR/build-ohos-arm64-v8a"
    CROSS_FILE="$BUILD_DIR/ohos-arm64-v8a.ini"
    mkdir -p "$BUILD_DIR"
    cat > "$CROSS_FILE" <<EOF
[binaries]
c = '$TOOLCHAIN/aarch64-unknown-linux-ohos-clang'
cpp = '$TOOLCHAIN/aarch64-unknown-linux-ohos-clang++'
ar = '$TOOLCHAIN/llvm-ar'
strip = '$TOOLCHAIN/llvm-strip'
[properties]
needs_exe_wrapper = true
[host_machine]
system = 'linux'
cpu_family = 'aarch64'
cpu = 'armv8-a'
endian = 'little'
EOF
    setup_and_build "$BUILD_DIR" --cross-file "$CROSS_FILE"
    "$TOOLCHAIN/llvm-strip" "$BUILD_DIR/libamphion_audio_processing.so"
    ;;
  *)
    echo "usage: $0 host|android-arm64-v8a|ohos-arm64-v8a" >&2
    exit 2
    ;;
esac
