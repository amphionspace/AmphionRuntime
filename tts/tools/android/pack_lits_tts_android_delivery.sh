#!/usr/bin/env bash
# Build the Lits TTS Android SDK delivery package.
#
# Usage (repo root):
#   bash tts/tools/android/pack_lits_tts_android_delivery.sh [version]
#
# Optional env:
#   LITS_TTS_MODEL_DIR=/path/to/lits_delivery_16k_hifigan/1.0.0
#   LITS_TTS_DELIVERY_VERSION=0.1.0
#   LITS_TTS_ALLOW_DIRTY=1   # local preview only
#
# Output:
#   ../delivery/lits-tts-android-sdk-v<version>/
#   ../delivery/lits-tts-android-sdk-v<version>-<date>.zip
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lits_tts_delivery_common.sh
source "$SCRIPT_DIR/lits_tts_delivery_common.sh"

REPO_ROOT="$(lits_tts_repo_root_from_script)"
AR_ROOT="$(lits_tts_android_root_from_repo "$REPO_ROOT")"
BUILD_DATE="$(date +%Y%m%d)"

lits_tts_load_git_provenance "$REPO_ROOT"
lits_tts_assert_reproducible_build

VERSION="$(lits_tts_resolve_delivery_version "${1:-}")"
PKG_NAME="lits-tts-android-sdk-v${VERSION}"
OUT_BASE="$(cd "$REPO_ROOT/.." && pwd)/delivery"
OUT_ROOT="$OUT_BASE/$PKG_NAME"
ZIP_PATH="$OUT_BASE/${PKG_NAME}-${BUILD_DATE}.zip"
AAR_NAME="lits-tts-sdk-${VERSION}.aar"
MODEL_DIR="${LITS_TTS_MODEL_DIR:-$(lits_tts_default_model_dir "$REPO_ROOT")}"

echo "[1/5] validate model package ..."
lits_tts_assert_model_dir "$MODEL_DIR"

echo "[2/5] build Android AAR + sample APK ..."
cd "$AR_ROOT"
./gradlew :sdk:testDebugUnitTest :sdk:assembleRelease :sample:assembleDebug \
  -PLITS_TTS_MODEL_DIR="$MODEL_DIR"
AAR_SRC="$AR_ROOT/sdk/build/outputs/aar/sdk-release.aar"
[[ -f "$AAR_SRC" ]] || {
  echo "[ERROR] missing $AAR_SRC" >&2
  exit 1
}
SAMPLE_APK_SRC="$AR_ROOT/sample/build/outputs/apk/debug/sample-debug.apk"
[[ -f "$SAMPLE_APK_SRC" ]] || {
  echo "[ERROR] missing $SAMPLE_APK_SRC" >&2
  exit 1
}

echo "[3/5] assemble delivery tree ..."
rm -rf "$OUT_ROOT"
mkdir -p "$OUT_ROOT"/{aar,demo,android-src,docs}

cp "$AAR_SRC" "$OUT_ROOT/aar/$AAR_NAME"
cp "$SAMPLE_APK_SRC" "$OUT_ROOT/demo/lits-tts-sample-debug.apk"
cp "$AR_ROOT/docs/INTEGRATION.md" "$OUT_ROOT/docs/INTEGRATION.md"
cp "$AR_ROOT/docs/API.md" "$OUT_ROOT/docs/API.md"
cp "$AR_ROOT/docs/DELIVERY.md" "$OUT_ROOT/docs/DELIVERY.md"
cp "$AR_ROOT/docs/LICENSE.md" "$OUT_ROOT/docs/LICENSE.md"
cp "$AR_ROOT/NOTICE" "$OUT_ROOT/docs/NOTICE"

lits_tts_stage_android_source "$OUT_ROOT/android-src/TTS" "$REPO_ROOT" "$MODEL_DIR"

AAR_MB="$(du -sm "$OUT_ROOT/aar/$AAR_NAME" | awk '{print $1}')"
SAMPLE_APK_MB="$(du -sm "$OUT_ROOT/demo/lits-tts-sample-debug.apk" | awk '{print $1}')"
SRC_MB="$(du -sm "$OUT_ROOT/android-src/TTS" | awk '{print $1}')"

lits_tts_write_version_txt "$OUT_ROOT/VERSION.txt" \
  "lits-tts-android-sdk" "$VERSION" \
  "platform=android" \
  "aar_file=$AAR_NAME" \
  "aar_mb=$AAR_MB" \
  "sample_apk_file=lits-tts-sample-debug.apk" \
  "sample_apk_mb=$SAMPLE_APK_MB" \
  "android_source_dir=android-src/TTS" \
  "android_source_mb=$SRC_MB" \
  "model_id=lits_delivery_16k_hifigan" \
  "model_version=1.0.0" \
  "pack_script=tts/tools/android/pack_lits_tts_android_delivery.sh"

cat > "$OUT_ROOT/README.txt" <<EOF
Lits TTS Android SDK v${VERSION}
================================

目录
----
  aar/$AAR_NAME          集成用 Android SDK AAR（约 ${AAR_MB} MB，含模型 + JNI）
  demo/lits-tts-sample-debug.apk  可安装验证 APK（约 ${SAMPLE_APK_MB} MB，依赖本 SDK）
  android-src/TTS/       Android SDK 源码快照（约 ${SRC_MB} MB，含本次构建使用的模型包）
  docs/                  Android AAR 集成、API、授权和第三方声明
  VERSION.txt            版本、git commit 与构建溯源

快速集成
--------
  1. 将 aar/$AAR_NAME 放入宿主 App 的 libs/
  2. implementation(files("libs/$AAR_NAME"))
  3. 按 docs/INTEGRATION.md 初始化 TextToSpeechSdk
  4. 如为武装构建，按 docs/LICENSE.md 放置 amphion-license.lic

从源码重建
----------
  1. 进入 android-src/TTS/tts/android
  2. 确认 Android SDK 路径可用（local.properties 或 ANDROID_HOME / ANDROID_SDK_ROOT）
  3. 执行:
       python ../../tts/tools/verify_lits_delivery_16k_package.py --model-dir ../../tts/tools/trial-export/lits_delivery_16k_hifigan/1.0.0
       ./gradlew :sdk:testDebugUnitTest
       ./gradlew :sdk:assembleRelease
       ./gradlew :sample:assembleDebug

说明
----
  - AAR 内不包含源码；源码通过 android-src/TTS 随交付包提供。
  - android-src/TTS 来自 git-tracked 源码，并叠加本次构建使用的模型包。
  - 私钥、local.properties、Gradle build 产物和生成的 Android assets 不进入源码快照。
EOF

echo "[4/5] verify delivery tree ..."
bash "$SCRIPT_DIR/verify_lits_tts_android_delivery.sh" "$OUT_ROOT"

echo "[5/5] zip delivery ..."
rm -f "$ZIP_PATH"
lits_tts_zip_delivery "$OUT_ROOT" "$ZIP_PATH"
bash "$SCRIPT_DIR/verify_lits_tts_android_delivery.sh" "$ZIP_PATH"

echo "[OK] tree: $OUT_ROOT"
echo "[OK] zip:  $ZIP_PATH"
du -sh "$OUT_ROOT" "$ZIP_PATH"
