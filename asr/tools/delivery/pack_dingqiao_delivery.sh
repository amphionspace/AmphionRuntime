#!/usr/bin/env bash
# 鼎桥 v0.1 交付包（方案 A：单一 fat AAR）。
#
# 用法（仓库根目录）:
#   bash asr/tools/delivery/pack_dingqiao_delivery.sh [版本号]
#
# 产物目录: ../../delivery/amphion-dingqiao-v0.1.0-schemeA/
#           ../../delivery/amphion-dingqiao-v0.1.0-schemeA-<date>.zip
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
PKG_NAME="amphion-dingqiao-v${VERSION}-schemeA"
OUT_ROOT="$DQ_ROOT/delivery/$PKG_NAME"
ZIP_PATH="$DQ_ROOT/delivery/${PKG_NAME}-${BUILD_DATE}.zip"
AAR_NAME="dingqiao-asr-v${VERSION}.aar"
ERES2NET_SRC="$REPO_ROOT/asr/tools/speaker/models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"

echo "[1/4] build release AARs ..."
cd "$AR_ROOT"
dingqiao_issue_demo_license "$REPO_ROOT"
./gradlew :sdk:assembleRelease :sdk-police:assembleRelease :sdk-dingqiao:assembleRelease :samples:dingqiao-demo:assembleRelease
dingqiao_assert_sdk_version_consistent "$AR_ROOT"

echo "[2/4] merge fat AAR ..."
bash "$REPO_ROOT/asr/tools/delivery/merge_dingqiao_fat_aar.sh" "$VERSION"
FAT_AAR="$AR_ROOT/build/dingqiao-delivery/$AAR_NAME"

echo "[3/4] assemble delivery tree ..."
rm -rf "$OUT_ROOT"
mkdir -p "$OUT_ROOT"/{aar,demo,models,docs}

cp "$FAT_AAR" "$OUT_ROOT/aar/"
cp "$AR_ROOT/samples/dingqiao-demo/build/outputs/apk/release/dingqiao-demo-release.apk" "$OUT_ROOT/demo/"
if [[ ! -f "$ERES2NET_SRC" ]]; then
  echo "[ERROR] missing $ERES2NET_SRC" >&2
  exit 1
fi
cp "$ERES2NET_SRC" "$OUT_ROOT/models/eres2net.onnx"

cp "$DQ_ROOT/语音识别SDK接口.md" "$OUT_ROOT/docs/"
cp "$AR_ROOT/docs/DINGQIAO_DELIVERY.md" "$OUT_ROOT/docs/"
cp "$AR_ROOT/docs/INTEGRATION.md" "$OUT_ROOT/docs/"
cp "$AR_ROOT/docs/LICENSING.md" "$OUT_ROOT/docs/"
cp "$AR_ROOT/NOTICE" "$OUT_ROOT/docs/NOTICE"

AAR_MB="$(du -m "$OUT_ROOT/aar/$AAR_NAME" | awk '{print $1}')"
APK_MB="$(du -m "$OUT_ROOT/demo/dingqiao-demo-release.apk" | awk '{print $1}')"
MODEL_MB="$(du -m "$OUT_ROOT/models/eres2net.onnx" | awk '{print $1}')"

cd "$REPO_ROOT"
dingqiao_write_version_txt "$OUT_ROOT/VERSION.txt" \
  "amphion-dingqiao-schemeA" "$VERSION" \
  "fat_aar_mb=$AAR_MB" \
  "demo_apk_mb=$APK_MB" \
  "voiceprint_model_mb=$MODEL_MB" \
  "pack_script=asr/tools/delivery/pack_dingqiao_delivery.sh"

bash "$REPO_ROOT/asr/tools/delivery/verify_dingqiao_delivery.sh" "$OUT_ROOT/VERSION.txt"
bash "$REPO_ROOT/asr/tools/delivery/verify_dingqiao_delivery.sh" "$OUT_ROOT/aar/$AAR_NAME"
bash "$REPO_ROOT/asr/tools/delivery/verify_dingqiao_delivery.sh" "$OUT_ROOT"

cat > "$OUT_ROOT/README.txt" <<EOF
鼎桥警务语音识别 SDK — 交付预览（方案 A）
==========================================

本包供内部评审：单一 fat AAR，内嵌 sdk + sdk-police + ASR 模型资产。

目录
----
  aar/$AAR_NAME          集成用（~${AAR_MB} MB，含模型 + JNI + 警务域 + 鼎桥 API）
  demo/*.apk             参考 Demo（三模块分依赖构建，可与 fat AAR 对照验证）
  models/eres2net.onnx   声纹模型（~${MODEL_MB} MB，运行时放入 setWorkPath，不进 AAR）
  docs/                  接口契约与集成说明

Gradle 集成（方案 A）
---------------------
  dependencies {
      implementation(files("libs/$AAR_NAME"))
  }

  初始化见 docs/DINGQIAO_DELIVERY.md §5；对外 API 为 SpeechRecognizeSdk。

端侧模型占用（估算）
--------------------
  fat AAR 内 ASR 模型（zh-en + yue-en + 标点 + ITN + VAD）  ~423 MB
  警务域 assets                                              ~4 MB
  JNI .so                                                    ~28 MB
  声纹 eres2net.onnx（外置，启用声纹时）                      ~38 MB
  首次运行另解包到 filesDir（zh-CN 约 ~248 MB，与 APK 内资产有重叠）

  详见 VERSION.txt；与鼎桥 500 MB 上限对比时请明确验收口径（仅运行模型 vs 安装总占用）。

商用授权
--------
  Release AAR 已武装离线验签；正式集成需单独签发 amphion-license.lic。
  - Demo APK 内嵌 Demo 用 license（2 个月试用，绑定 demo 包名+签名），不可用于客户正式包

版本
----
  见 VERSION.txt（commit: $GIT_COMMIT_SHORT）
EOF

echo "[4/4] zip (UTF-8 EFS for Windows) ..."
rm -f "$ZIP_PATH"
dingqiao_zip_delivery "$OUT_ROOT" "$ZIP_PATH"

echo "[OK] tree: $OUT_ROOT"
echo "[OK] zip:  $ZIP_PATH"
du -sh "$OUT_ROOT" "$ZIP_PATH"
