#!/usr/bin/env bash
# 鼎桥正式交付包（方案 A：fat AAR + 对齐 Demo + 客户向文档，不含公钥/内部文档）。
#
# 用法（AmphionRuntime 仓库根目录）:
#   bash asr/tools/delivery/pack_dingqiao_customer_delivery.sh [交付版本号]
#
# 产物: ../delivery/amphion-dingqiao-v<版本>-customer/
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=dingqiao_build_provenance.sh
source "$SCRIPT_DIR/dingqiao_build_provenance.sh"

REPO_ROOT="$(dingqiao_repo_root_from_script)"
DQ_ROOT="$(cd "$REPO_ROOT/.." && pwd)"
AR_ROOT="$(dingqiao_ar_root_from_repo "$REPO_ROOT")"
CUSTOMER_DOCS="$AR_ROOT/docs/customer"
BUILD_DATE="$(date +%Y%m%d)"

dingqiao_load_git_provenance "$REPO_ROOT"
dingqiao_assert_reproducible_build

VERSION="$(dingqiao_resolve_delivery_version "$AR_ROOT" "${1:-}")"
PKG_NAME="amphion-dingqiao-v${VERSION}-customer"
OUT_ROOT="$DQ_ROOT/delivery/$PKG_NAME"
ZIP_PATH="$DQ_ROOT/delivery/${PKG_NAME}-${BUILD_DATE}.zip"
AAR_NAME="dingqiao-asr-v${VERSION}.aar"
FAT_AAR="$AR_ROOT/build/dingqiao-delivery/$AAR_NAME"
ERES2NET_SRC="$REPO_ROOT/asr/tools/speaker/models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
DEMO_APK_SRC="$AR_ROOT/samples/dingqiao-demo/build/outputs/apk/release/dingqiao-demo-release.apk"
DEMO_LIC_SRC="$AR_ROOT/samples/dingqiao-demo/src/main/assets/amphion-license.lic"

echo "[1/4] build release AARs + merge fat AAR ..."
cd "$AR_ROOT"
./gradlew :sdk:assembleRelease :sdk-police:assembleRelease :sdk-dingqiao:assembleRelease
dingqiao_assert_sdk_version_consistent "$AR_ROOT"
bash "$REPO_ROOT/asr/tools/delivery/merge_dingqiao_fat_aar.sh" "$VERSION"
[[ -f "$FAT_AAR" ]] || { echo "[ERROR] missing $FAT_AAR" >&2; exit 1; }

echo "[2/4] build Demo APK (fat AAR aligned) ..."
dingqiao_issue_demo_license "$REPO_ROOT"
./gradlew :samples:dingqiao-demo:assembleRelease \
  -PdingqiaoUseFatAar=true \
  -PdingqiaoFatAarPath="$FAT_AAR"
[[ -f "$DEMO_APK_SRC" ]] || { echo "[ERROR] missing $DEMO_APK_SRC" >&2; exit 1; }
[[ -f "$DEMO_LIC_SRC" ]] || { echo "[ERROR] missing $DEMO_LIC_SRC" >&2; exit 1; }

echo "[3/4] assemble customer delivery tree ..."
rm -rf "$OUT_ROOT"
mkdir -p "$OUT_ROOT"/{aar,demo,models,docs}

cp "$FAT_AAR" "$OUT_ROOT/aar/"
cp "$DEMO_APK_SRC" "$OUT_ROOT/demo/dingqiao-demo-release.apk"
cp "$ERES2NET_SRC" "$OUT_ROOT/models/eres2net.onnx"

dingqiao_stage_customer_docs "$OUT_ROOT/docs" "$CUSTOMER_DOCS" "$DQ_ROOT"

AAR_MB="$(du -m "$OUT_ROOT/aar/$AAR_NAME" | awk '{print $1}')"
APK_MB="$(du -m "$OUT_ROOT/demo/dingqiao-demo-release.apk" | awk '{print $1}')"
MODEL_MB="$(du -m "$OUT_ROOT/models/eres2net.onnx" | awk '{print $1}')"

dingqiao_write_version_txt "$OUT_ROOT/VERSION.txt" \
  "amphion-dingqiao-customer" "$VERSION" \
  "product=amphion-dingqiao-asr" \
  "integration=scheme-a-fat-aar" \
  "aar_file=$AAR_NAME" \
  "aar_mb=$AAR_MB" \
  "demo_apk_mb=$APK_MB" \
  "voiceprint_model_mb=$MODEL_MB" \
  "pack_script=asr/tools/delivery/pack_dingqiao_customer_delivery.sh"

bash "$REPO_ROOT/asr/tools/delivery/verify_dingqiao_delivery.sh" "$OUT_ROOT/VERSION.txt"
bash "$REPO_ROOT/asr/tools/delivery/verify_dingqiao_delivery.sh" "$OUT_ROOT/aar/$AAR_NAME"
bash "$REPO_ROOT/asr/tools/delivery/verify_dingqiao_delivery.sh" "$OUT_ROOT"

echo "[3b/4] embed demo reference source (AAR-aligned, no SDK source) ..."
DINGQIAO_FAT_AAR="$FAT_AAR" \
DINGQIAO_DEMO_APK="$DEMO_APK_SRC" \
DINGQIAO_DEMO_LICENSE="$DEMO_LIC_SRC" \
DINGQIAO_DEMO_SRC_OUT_ROOT="$OUT_ROOT/demo-src" \
DINGQIAO_DEMO_SRC_SKIP_ZIP=1 \
bash "$REPO_ROOT/asr/tools/delivery/pack_dingqiao_demo_source_delivery.sh" "$VERSION"

cat > "$OUT_ROOT/README.txt" <<EOF
鼎桥警务语音识别 SDK v${VERSION}
================================

目录
----
  aar/$AAR_NAME              集成用 SDK（~${AAR_MB} MB）
  demo/dingqiao-demo-release.apk   参考 Demo（~${APK_MB} MB）
  demo-src/                  Demo 参考工程源码（独立 Gradle，默认依赖 libs/ 内同版 AAR）
  models/eres2net.onnx       声纹模型（~${MODEL_MB} MB，放入 setWorkPath）
  docs/                      集成、商用授权（LICENSE.md）、第三方声明（NOTICE）

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
  - 版本与 git 溯源见 VERSION.txt（含 git_commit_full / buildconfig_sdk_version）
  - Demo APK 内 license 为 2 个月试用（绑定 demo 包名+签名）；到期需重签并重打 Demo
  - 第三方开源组件声明见 docs/NOTICE（sherpa-onnx / ONNX Runtime / silero-vad / 3D-Speaker 等）
  - 校验: bash asr/tools/delivery/verify_dingqiao_delivery.sh VERSION.txt
EOF

echo "[4/4] zip (UTF-8 EFS for Windows) ..."
rm -f "$ZIP_PATH"
dingqiao_zip_delivery "$OUT_ROOT" "$ZIP_PATH"

echo "[OK] tree: $OUT_ROOT"
echo "[OK] zip:  $ZIP_PATH"
du -sh "$OUT_ROOT" "$ZIP_PATH"
