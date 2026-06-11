#!/usr/bin/env bash
# 方案 A 交付包（fat AAR + 与 fat AAR 同依赖构建的 Demo APK）。
# 不覆盖既有 schemeA 目录（原三模块 Demo 仍在 schemeA 包内）。
#
# 用法（仓库根目录）:
#   bash tools/android/pack_dingqiao_delivery_scheme_a_aligned.sh [版本号]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DQ_ROOT="$(cd "$REPO_ROOT/.." && pwd)"
AR_ROOT="$REPO_ROOT/android/AmphionRuntime"
VERSION="${1:-0.1.0}"
DATE="$(date +%Y%m%d)"
PKG_NAME="amphion-dingqiao-v${VERSION}-schemeA-aligned"
OUT_ROOT="$DQ_ROOT/delivery/$PKG_NAME"
ZIP_PATH="$DQ_ROOT/delivery/${PKG_NAME}-${DATE}.zip"
AAR_NAME="dingqiao-asr-v${VERSION}.aar"
FAT_AAR="$AR_ROOT/build/dingqiao-delivery/$AAR_NAME"
ERES2NET_SRC="$REPO_ROOT/tools/speaker/models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
DEMO_APK_SRC="$AR_ROOT/sample-dingqiao-demo/build/outputs/apk/release/sample-dingqiao-demo-release.apk"

echo "[1/4] build release AARs + merge fat AAR ..."
cd "$AR_ROOT"
./gradlew :sdk:assembleRelease :sdk-police:assembleRelease :sdk-dingqiao:assembleRelease
bash "$REPO_ROOT/tools/android/merge_dingqiao_fat_aar.sh" "$VERSION"
[[ -f "$FAT_AAR" ]] || { echo "[ERROR] missing $FAT_AAR" >&2; exit 1; }

echo "[2/4] build Demo APK against fat AAR ..."
./gradlew :sample-dingqiao-demo:assembleRelease \
  -PdingqiaoUseFatAar=true \
  -PdingqiaoFatAarPath="$FAT_AAR"
[[ -f "$DEMO_APK_SRC" ]] || { echo "[ERROR] missing $DEMO_APK_SRC" >&2; exit 1; }

echo "[3/4] assemble delivery tree ..."
rm -rf "$OUT_ROOT"
mkdir -p "$OUT_ROOT"/{aar,demo,models,docs}

cp "$FAT_AAR" "$OUT_ROOT/aar/"
cp "$DEMO_APK_SRC" "$OUT_ROOT/demo/sample-dingqiao-demo-fat-release.apk"
cp "$ERES2NET_SRC" "$OUT_ROOT/models/eres2net.onnx"

cp "$DQ_ROOT/语音识别SDK接口.md" "$OUT_ROOT/docs/"
cp "$AR_ROOT/docs/customer/DINGQIAO_INTEGRATION.md" "$OUT_ROOT/docs/"
cp "$AR_ROOT/docs/customer/LICENSE.md" "$OUT_ROOT/docs/"

AAR_MB="$(du -m "$OUT_ROOT/aar/$AAR_NAME" | awk '{print $1}')"
APK_MB="$(du -m "$OUT_ROOT/demo/sample-dingqiao-demo-fat-release.apk" | awk '{print $1}')"
MODEL_MB="$(du -m "$OUT_ROOT/models/eres2net.onnx" | awk '{print $1}')"

cd "$REPO_ROOT"
GIT_HASH="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
SDK_VER="$(grep '^AMPHION_RUNTIME_VERSION=' "$AR_ROOT/gradle.properties" | cut -d= -f2- || echo unknown)"
cat > "$OUT_ROOT/VERSION.txt" <<EOF
package=amphion-dingqiao-schemeA-aligned
version=$VERSION
sdk_version=$SDK_VER
git_commit=$GIT_HASH
build_date=$DATE
fat_aar_mb=$AAR_MB
demo_apk_mb=$APK_MB
demo_apk_name=sample-dingqiao-demo-fat-release.apk
demo_aligned_fat_aar=true
voiceprint_model_mb=$MODEL_MB
EOF

cat > "$OUT_ROOT/README.txt" <<EOF
鼎桥警务语音识别 SDK — 方案 A（fat AAR + 对齐 Demo，内部预览）
==============================================================

本包：集成 SDK 与 Demo APK 均基于同一 dingqiao-asr fat AAR。
文档已脱敏（客户向：DINGQIAO_INTEGRATION.md + LICENSE.md，无公钥/内部 SOP）。

目录
----
  aar/$AAR_NAME                    集成用 fat AAR（~${AAR_MB} MB）
  demo/sample-dingqiao-demo-fat-release.apk   Demo（~${APK_MB} MB）
  models/eres2net.onnx             声纹模型（~${MODEL_MB} MB，外置）
  docs/

Gradle 集成
-----------
  dependencies {
      implementation(files("libs/$AAR_NAME"))
  }

正式对鼎桥发包请用: bash tools/android/pack_dingqiao_customer_delivery.sh

版本：见 VERSION.txt
EOF

echo "[4/4] zip ..."
rm -f "$ZIP_PATH"
(cd "$DQ_ROOT/delivery" && zip -qr "$(basename "$ZIP_PATH")" "$(basename "$OUT_ROOT")")

echo "[OK] tree: $OUT_ROOT"
echo "[OK] zip:  $ZIP_PATH"
du -sh "$OUT_ROOT" "$ZIP_PATH"
