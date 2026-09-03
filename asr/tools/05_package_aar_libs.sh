#!/usr/bin/env bash
# 阶段 B.2：把编出来的 .so 拷到 SDK 工程的 jniLibs/<abi>/
#
# 用法：
#   bash asr/tools/05_package_aar_libs.sh                  # 拷已经存在的全部 ABI
#   bash asr/tools/05_package_aar_libs.sh arm64-v8a
#   bash asr/tools/05_package_aar_libs.sh all
#
# 交付打包时设置 AMPHION_REQUIRE_ANDROID_NATIVE_LIBS=1：
#   若目标 ABI 的 native 构建产物或必需 .so 缺失，立即失败。
#
# 这一步执行完，SDK 工程就具备了完整的 native 依赖，可以直接：
#   cd asr/android && ./gradlew :sdk:assembleRelease

set -euo pipefail

ABI_ARG="${1:-all}"
STRICT="${AMPHION_REQUIRE_ANDROID_NATIVE_LIBS:-0}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SHERPA_ROOT="${AMPHION_SHERPA_ROOT:-$(bash "$SCRIPT_DIR/prepare_sherpa_source.sh")}"
SDK_JNI_LIBS_DIR="$REPO_ROOT/asr/android/sdk/src/main/jniLibs"
AGC_ROOT="$REPO_ROOT/asr/native/audio-processing"

verify_no_host_paths() {
  local native_lib="$1"
  local host_paths
  host_paths="$(LC_ALL=C strings "$native_lib" | grep -E '/Users/|/home/' | sort -u | head -20 || true)"
  if [[ -n "$host_paths" ]]; then
    echo "[ERROR] native library contains a developer-machine path: $native_lib" >&2
    printf '%s\n' "$host_paths" >&2
    echo "        Rebuild it with the repository native build script before packaging." >&2
    return 1
  fi
}

copy_one_abi() {
  local ABI="$1"
  local SRC_DIR="$SHERPA_ROOT/build-android-${ABI}/install/lib"
  local DST_DIR="$SDK_JNI_LIBS_DIR/${ABI}"
  local AGC_SO="$AGC_ROOT/build-android-${ABI}/libamphion_audio_processing.so"

  if [[ ! -d "$SRC_DIR" ]]; then
    if [[ "$STRICT" == "1" ]]; then
      echo "[ERROR] $SRC_DIR 不存在，请先运行 04_build_android_so.sh $ABI" >&2
      return 1
    fi
    echo "[SKIP] $SRC_DIR 不存在，请先运行 04_build_android_so.sh $ABI"
    return 0
  fi

  mkdir -p "$DST_DIR"

  echo "[COPY] $ABI"
  for f in libsherpa-onnx-jni.so libonnxruntime.so; do
    if [[ -f "$SRC_DIR/$f" ]]; then
      verify_no_host_paths "$SRC_DIR/$f"
      cp -fv "$SRC_DIR/$f" "$DST_DIR/$f"
    else
      if [[ "$STRICT" == "1" ]]; then
        echo "[ERROR] $SRC_DIR/$f 缺失" >&2
        return 1
      fi
      echo "[WARN] $SRC_DIR/$f 缺失"
    fi
  done
  if [[ -f "$AGC_SO" ]]; then
    verify_no_host_paths "$AGC_SO"
    cp -fv "$AGC_SO" "$DST_DIR/libamphion_audio_processing.so"
  elif [[ "$STRICT" == "1" ]]; then
    echo "[ERROR] $AGC_SO 缺失，请先运行 03_build_agc_native.sh android-$ABI" >&2
    return 1
  else
    echo "[WARN] $AGC_SO 缺失"
  fi

  # 别忘了 strip（NDK 已经 strip 过 release 版本，这里只确认大小）
  ls -lh "$DST_DIR/"
}

case "$ABI_ARG" in
  arm64-v8a|armeabi-v7a)
    copy_one_abi "$ABI_ARG"
    ;;
  all)
    copy_one_abi arm64-v8a
    copy_one_abi armeabi-v7a
    ;;
  *)
    echo "Unknown ABI: $ABI_ARG"; exit 1
    ;;
esac

echo
echo "[DONE] 已拷到 $SDK_JNI_LIBS_DIR"
echo "[NEXT] 进 asr/android 执行："
echo "         ./gradlew :sdk:assembleRelease"
echo "       AAR 输出在 sdk/build/outputs/aar/sdk-release.aar"
