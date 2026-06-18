#!/usr/bin/env bash
# 方案 A 交付包（fat AAR + 与 fat AAR 同依赖构建的 Demo APK）。
#
# 用法（AmphionRuntime 仓库根目录）:
#   bash asr/tools/delivery/pack_dingqiao_delivery_scheme_a_aligned.sh [交付版本号]
# 交付版本号默认 = gradle.properties AMPHION_RUNTIME_VERSION
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
PKG_NAME="amphion-dingqiao-v${VERSION}-schemeA-aligned"
OUT_ROOT="$DQ_ROOT/delivery/$PKG_NAME"
ZIP_PATH="$DQ_ROOT/delivery/${PKG_NAME}-${BUILD_DATE}.zip"
AAR_NAME="dingqiao-asr-v${VERSION}.aar"
FAT_AAR="$AR_ROOT/build/dingqiao-delivery/$AAR_NAME"
ERES2NET_SRC="$REPO_ROOT/asr/tools/speaker/models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
DEMO_APK_SRC="$AR_ROOT/sample-dingqiao-demo/build/outputs/apk/release/sample-dingqiao-demo-release.apk"

echo "[1/4] build release AARs + merge fat AAR ..."
cd "$AR_ROOT"
./gradlew :sdk:assembleRelease :sdk-police:assembleRelease :sdk-dingqiao:assembleRelease
dingqiao_assert_sdk_version_consistent "$AR_ROOT"
bash "$REPO_ROOT/asr/tools/delivery/merge_dingqiao_fat_aar.sh" "$VERSION"
[[ -f "$FAT_AAR" ]] || { echo "[ERROR] missing $FAT_AAR" >&2; exit 1; }

echo "[2/4] build Demo APK against fat AAR ..."
dingqiao_issue_demo_license "$REPO_ROOT"
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

dingqiao_stage_customer_docs "$OUT_ROOT/docs" "$AR_ROOT/docs/customer" "$DQ_ROOT"

AAR_MB="$(du -m "$OUT_ROOT/aar/$AAR_NAME" | awk '{print $1}')"
APK_MB="$(du -m "$OUT_ROOT/demo/sample-dingqiao-demo-fat-release.apk" | awk '{print $1}')"
MODEL_MB="$(du -m "$OUT_ROOT/models/eres2net.onnx" | awk '{print $1}')"

cd "$REPO_ROOT"
dingqiao_write_version_txt "$OUT_ROOT/VERSION.txt" \
  "amphion-dingqiao-schemeA-aligned" "$VERSION" \
  "fat_aar_file=$AAR_NAME" \
  "fat_aar_mb=$AAR_MB" \
  "demo_apk_mb=$APK_MB" \
  "demo_apk_name=sample-dingqiao-demo-fat-release.apk" \
  "demo_aligned_fat_aar=true" \
  "voiceprint_model_mb=$MODEL_MB" \
  "pack_script=asr/tools/delivery/pack_dingqiao_delivery_scheme_a_aligned.sh"

bash "$REPO_ROOT/asr/tools/delivery/verify_dingqiao_delivery.sh" "$OUT_ROOT/VERSION.txt"
bash "$REPO_ROOT/asr/tools/delivery/verify_dingqiao_delivery.sh" "$OUT_ROOT/aar/$AAR_NAME"
bash "$REPO_ROOT/asr/tools/delivery/verify_dingqiao_delivery.sh" "$OUT_ROOT"

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
  docs/                            集成说明、商用授权、第三方开源声明（NOTICE）

Gradle 集成
-----------
  dependencies {
      implementation(files("libs/$AAR_NAME"))
  }

正式对鼎桥发包: bash asr/tools/delivery/pack_dingqiao_customer_delivery.sh
校验溯源: bash asr/tools/delivery/verify_dingqiao_delivery.sh VERSION.txt
EOF

echo "[4/4] zip (UTF-8 EFS for Windows) ..."
rm -f "$ZIP_PATH"
dingqiao_zip_delivery "$OUT_ROOT" "$ZIP_PATH"

echo "[OK] tree: $OUT_ROOT"
echo "[OK] zip:  $ZIP_PATH"
du -sh "$OUT_ROOT" "$ZIP_PATH"
