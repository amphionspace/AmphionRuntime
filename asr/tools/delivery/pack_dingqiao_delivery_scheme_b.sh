#!/usr/bin/env bash
# 鼎桥 v0.1 交付包（方案 B：三 AAR 分模块，与 Demo APK 同一次 Release 构建对齐）。
#
# 用法（仓库根目录）:
#   bash asr/tools/delivery/pack_dingqiao_delivery_scheme_b.sh [版本号]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=dingqiao_build_provenance.sh
source "$SCRIPT_DIR/dingqiao_build_provenance.sh"

REPO_ROOT="$(dingqiao_repo_root_from_script)"
DQ_ROOT="$(cd "$REPO_ROOT/.." && pwd)"
AR_ROOT="$(dingqiao_ar_root_from_repo "$REPO_ROOT")"
BUILD_DATE="$(date +%Y%m%d)"

dingqiao_load_git_provenance "$REPO_ROOT"
dingqiao_assert_reproducible_build

VERSION="$(dingqiao_resolve_delivery_version "$AR_ROOT" "${1:-}")"
PKG_NAME="amphion-dingqiao-v${VERSION}-schemeB"
OUT_ROOT="$DQ_ROOT/delivery/$PKG_NAME"
ZIP_PATH="$DQ_ROOT/delivery/${PKG_NAME}-${BUILD_DATE}.zip"
ERES2NET_SRC="$REPO_ROOT/asr/tools/speaker/models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"

SDK_AAR="$AR_ROOT/sdk/build/outputs/aar/sdk-release.aar"
POLICE_AAR="$AR_ROOT/sdk-police/build/outputs/aar/sdk-police-release.aar"
DINGQIAO_AAR="$AR_ROOT/sdk-dingqiao/build/outputs/aar/sdk-dingqiao-release.aar"
DEMO_APK="$AR_ROOT/samples/dingqiao-demo/build/outputs/apk/release/dingqiao-demo-release.apk"

echo "[1/3] build release（三 AAR + Demo APK 同批构建）..."
cd "$AR_ROOT"
dingqiao_issue_demo_license "$REPO_ROOT"
./gradlew :sdk:assembleRelease :sdk-police:assembleRelease :sdk-dingqiao:assembleRelease :samples:dingqiao-demo:assembleRelease
dingqiao_assert_sdk_version_consistent "$AR_ROOT"

for f in "$SDK_AAR" "$POLICE_AAR" "$DINGQIAO_AAR" "$DEMO_APK"; do
  [[ -f "$f" ]] || { echo "[ERROR] missing $f" >&2; exit 1; }
done

echo "[2/3] assemble delivery tree ..."
rm -rf "$OUT_ROOT"
mkdir -p "$OUT_ROOT"/{aar,demo,models,docs}

cp "$SDK_AAR" "$OUT_ROOT/aar/amphion-runtime-release.aar"
cp "$POLICE_AAR" "$OUT_ROOT/aar/amphion-police-release.aar"
cp "$DINGQIAO_AAR" "$OUT_ROOT/aar/dingqiao-sdk-release.aar"
cp "$DEMO_APK" "$OUT_ROOT/demo/dingqiao-demo-release.apk"
cp "$ERES2NET_SRC" "$OUT_ROOT/models/eres2net.onnx"

cp "$DQ_ROOT/语音识别SDK接口.md" "$OUT_ROOT/docs/"
cp "$AR_ROOT/docs/DINGQIAO_DELIVERY.md" "$OUT_ROOT/docs/"
cp "$AR_ROOT/docs/INTEGRATION.md" "$OUT_ROOT/docs/"
cp "$AR_ROOT/docs/LICENSING.md" "$OUT_ROOT/docs/"
cp "$AR_ROOT/NOTICE" "$OUT_ROOT/docs/NOTICE"

SDK_MB="$(du -m "$OUT_ROOT/aar/amphion-runtime-release.aar" | awk '{print $1}')"
POLICE_MB="$(du -m "$OUT_ROOT/aar/amphion-police-release.aar" | awk '{print $1}')"
DINGQIAO_MB="$(du -m "$OUT_ROOT/aar/dingqiao-sdk-release.aar" | awk '{print $1}')"
APK_MB="$(du -m "$OUT_ROOT/demo/dingqiao-demo-release.apk" | awk '{print $1}')"
MODEL_MB="$(du -m "$OUT_ROOT/models/eres2net.onnx" | awk '{print $1}')"

cd "$REPO_ROOT"
dingqiao_write_version_txt "$OUT_ROOT/VERSION.txt" \
  "amphion-dingqiao-schemeB" "$VERSION" \
  "amphion_runtime_aar_mb=$SDK_MB" \
  "amphion_police_aar_mb=$POLICE_MB" \
  "dingqiao_sdk_aar_mb=$DINGQIAO_MB" \
  "demo_apk_mb=$APK_MB" \
  "voiceprint_model_mb=$MODEL_MB" \
  "demo_aligned=true" \
  "pack_script=asr/tools/delivery/pack_dingqiao_delivery_scheme_b.sh"

bash "$REPO_ROOT/asr/tools/delivery/verify_dingqiao_delivery.sh" "$OUT_ROOT/VERSION.txt"
bash "$REPO_ROOT/asr/tools/delivery/verify_dingqiao_delivery.sh" "$OUT_ROOT"

cat > "$OUT_ROOT/README.txt" <<EOF
鼎桥警务语音识别 SDK — 交付预览（方案 B）
==========================================

本包与 Demo APK 对齐：三份 release AAR 与 demo/*.apk 来自同一次 ./gradlew assembleRelease。

目录
----
  aar/amphion-runtime-release.aar   核心 ASR + 模型 + JNI（~${SDK_MB} MB）
  aar/amphion-police-release.aar    警务三域后处理（~${POLICE_MB} MB）
  aar/dingqiao-sdk-release.aar      鼎桥 API 适配 SpeechRecognizeSdk（~${DINGQIAO_MB} MB）
  demo/dingqiao-demo-release.apk   参考 Demo（~${APK_MB} MB，依赖上述三模块）
  models/eres2net.onnx              声纹模型（~${MODEL_MB} MB，外置）
  docs/                             接口与集成说明

Gradle 集成（方案 B）
---------------------
  dependencies {
      implementation(files("libs/dingqiao-sdk-release.aar"))
      implementation(files("libs/amphion-police-release.aar"))
      implementation(files("libs/amphion-runtime-release.aar"))
  }

  依赖链：dingqiao-sdk → amphion-police → amphion-runtime
  对外 API：SpeechRecognizeSdk（见 docs/语音识别SDK接口.md）

与方案 A 的区别
---------------
  方案 A：单一 fat AAR（dingqiao-asr-*.aar），集成最简单。
  方案 B：三模块分发，与工程 :samples:dingqiao-demo 构建方式一致，便于分版本升级。

商用授权
--------
  amphion-runtime-release.aar 已武装离线验签；正式集成需单独签发 amphion-license.lic。

版本
----
  见 VERSION.txt（commit: $GIT_COMMIT_SHORT）
EOF

echo "[3/3] zip (UTF-8 EFS for Windows) ..."
rm -f "$ZIP_PATH"
dingqiao_zip_delivery "$OUT_ROOT" "$ZIP_PATH"

echo "[OK] tree: $OUT_ROOT"
echo "[OK] zip:  $ZIP_PATH"
du -sh "$OUT_ROOT" "$ZIP_PATH"
