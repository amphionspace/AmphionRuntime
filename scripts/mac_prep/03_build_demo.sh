#!/usr/bin/env bash
# 用仓库自带 demo 模型编 sample APK（准备工作 ②）
# 需先通过 01_check_env.sh；首次编 .so 较慢（约 10–30 分钟）
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ANDROID_ENV_QUIET=1
# shellcheck source=/dev/null
source "$SCRIPT_DIR/00_android_env.sh"

if [[ ! -f "${ANDROID_NDK}/build/cmake/android.toolchain.cmake" ]]; then
  echo "[ERROR] 合法 NDK 未找到。期望: $HOME/Library/Android/sdk/ndk/26.3.11579264"
  echo "        当前 ANDROID_NDK=$ANDROID_NDK"
  echo "        若 ANDROID_HOME 含 /Android/Android/ 是路径写错了，请: source scripts/mac_prep/00_android_env.sh"
  exit 1
fi
echo "[INFO] ANDROID_HOME=$ANDROID_HOME"
echo "[INFO] ANDROID_NDK=$ANDROID_NDK"

echo "[1/4] package demo assets ..."
bash tools/asr/08_pack_sdk_assets.sh

echo "[2/4] build arm64 .so (skip if jniLibs already present) ..."
JNI="$REPO/android/AmphionRuntime/sdk/src/main/jniLibs/arm64-v8a/libsherpa-onnx-jni.so"
if [[ ! -f "$JNI" ]]; then
  bash tools/asr/04_build_android_so.sh arm64-v8a
  bash tools/asr/05_package_aar_libs.sh
else
  echo "[SKIP] jniLibs already exist"
fi

echo "[3/4] sync plate homophones to sample assets ..."
SYNC="$REPO/../test_data/plate_enhance/sync_homophones_to_sample.sh"
[[ -f "$SYNC" ]] && bash "$SYNC" || true

ANDROID_DIR="$REPO/android/AmphionRuntime"
if [[ ! -f "$ANDROID_DIR/gradlew" ]]; then
  bash "$ANDROID_DIR/init_gradle_wrapper.sh"
fi
if [[ ! -f "$ANDROID_DIR/local.properties" ]] && [[ -d "${ANDROID_HOME:-$HOME/Library/Android/sdk}" ]]; then
  echo "sdk.dir=${ANDROID_HOME:-$HOME/Library/Android/sdk}" > "$ANDROID_DIR/local.properties"
fi

echo "[4/4] unit test + assemble sample debug ..."
cd "$ANDROID_DIR"
./gradlew :sample:testDebugUnitTest --tests com.amphion.asr.sample.plate.PlateNormalizerTest
./gradlew :sample:assembleDebug

APK="$ANDROID_DIR/sample/build/outputs/apk/debug/sample-debug.apk"
echo "[OK] APK: $APK"
echo "[NEXT] adb install -r $APK"
