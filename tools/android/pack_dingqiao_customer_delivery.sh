#!/usr/bin/env bash
# 鼎桥正式交付包（方案 A：fat AAR + 对齐 Demo + 客户向文档，不含公钥/内部文档）。
#
# 用法（AmphionRuntime 仓库根目录）:
#   bash tools/android/pack_dingqiao_customer_delivery.sh [版本号]
#
# 产物: ../delivery/amphion-dingqiao-v<版本>-customer/
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DQ_ROOT="$(cd "$REPO_ROOT/.." && pwd)"
AR_ROOT="$REPO_ROOT/android/AmphionRuntime"
CUSTOMER_DOCS="$AR_ROOT/docs/customer"
VERSION="${1:-0.1.0}"
DATE="$(date +%Y%m%d)"
PKG_NAME="amphion-dingqiao-v${VERSION}-customer"
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

echo "[2/4] build Demo APK (fat AAR aligned) ..."
./gradlew :sample-dingqiao-demo:assembleRelease \
  -PdingqiaoUseFatAar=true \
  -PdingqiaoFatAarPath="$FAT_AAR"
[[ -f "$DEMO_APK_SRC" ]] || { echo "[ERROR] missing $DEMO_APK_SRC" >&2; exit 1; }

echo "[3/4] assemble customer delivery tree ..."
rm -rf "$OUT_ROOT"
mkdir -p "$OUT_ROOT"/{aar,demo,models,docs}

cp "$FAT_AAR" "$OUT_ROOT/aar/"
cp "$DEMO_APK_SRC" "$OUT_ROOT/demo/sample-dingqiao-demo-release.apk"
cp "$ERES2NET_SRC" "$OUT_ROOT/models/eres2net.onnx"

# 客户向文档（不含 LICENSING.md / INTEGRATION.md / 内部 DINGQIAO_DELIVERY.md）
cp "$DQ_ROOT/语音识别SDK接口.md" "$OUT_ROOT/docs/"
cp "$CUSTOMER_DOCS/DINGQIAO_INTEGRATION.md" "$OUT_ROOT/docs/"
cp "$CUSTOMER_DOCS/LICENSE.md" "$OUT_ROOT/docs/"

AAR_MB="$(du -m "$OUT_ROOT/aar/$AAR_NAME" | awk '{print $1}')"
APK_MB="$(du -m "$OUT_ROOT/demo/sample-dingqiao-demo-release.apk" | awk '{print $1}')"
MODEL_MB="$(du -m "$OUT_ROOT/models/eres2net.onnx" | awk '{print $1}')"

cat > "$OUT_ROOT/VERSION.txt" <<EOF
product=amphion-dingqiao-asr
version=$VERSION
sdk_version=0.2.2
build_date=$DATE
aar_file=$AAR_NAME
aar_mb=$AAR_MB
demo_apk_mb=$APK_MB
voiceprint_model_mb=$MODEL_MB
integration=scheme-a-fat-aar
EOF

cat > "$OUT_ROOT/README.txt" <<EOF
鼎桥警务语音识别 SDK v${VERSION}
================================

目录
----
  aar/$AAR_NAME              集成用 SDK（~${AAR_MB} MB）
  demo/sample-dingqiao-demo-release.apk   参考 Demo（~${APK_MB} MB）
  models/eres2net.onnx       声纹模型（~${MODEL_MB} MB，放入 setWorkPath）
  docs/                      集成与授权说明

快速集成
--------
  1. 将 aar/ 下文件放入工程 libs/
  2. implementation(files("libs/$AAR_NAME"))
  3. 按 docs/DINGQIAO_INTEGRATION.md 初始化 SpeechRecognizeSdk
  4. 向我方申请 amphion-license.lic（见 docs/LICENSE.md），放入 assets/

说明
----
  - SDK 已内置授权校验能力；交付包内不含验签公钥，请勿自行配置密钥。
  - 商用授权文件单独下发，不包含在本压缩包内。
  - 版本信息见 VERSION.txt
EOF

echo "[4/4] zip ..."
rm -f "$ZIP_PATH"
(cd "$DQ_ROOT/delivery" && zip -qr "$(basename "$ZIP_PATH")" "$(basename "$OUT_ROOT")")

echo "[OK] tree: $OUT_ROOT"
echo "[OK] zip:  $ZIP_PATH"
du -sh "$OUT_ROOT" "$ZIP_PATH"
