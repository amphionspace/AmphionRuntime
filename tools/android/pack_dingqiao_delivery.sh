#!/usr/bin/env bash
# 鼎桥 v0.1 交付包（方案 A：单一 fat AAR）。
#
# 用法（仓库根目录）:
#   bash tools/android/pack_dingqiao_delivery.sh [版本号]
#
# 产物目录: ../../delivery/amphion-dingqiao-v0.1.0-schemeA/
#           ../../delivery/amphion-dingqiao-v0.1.0-schemeA-<date>.zip
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DQ_ROOT="$(cd "$REPO_ROOT/.." && pwd)"
AR_ROOT="$REPO_ROOT/android/AmphionRuntime"
VERSION="${1:-0.1.0}"
DATE="$(date +%Y%m%d)"
PKG_NAME="amphion-dingqiao-v${VERSION}-schemeA"
OUT_ROOT="$DQ_ROOT/delivery/$PKG_NAME"
ZIP_PATH="$DQ_ROOT/delivery/${PKG_NAME}-${DATE}.zip"
AAR_NAME="dingqiao-asr-v${VERSION}.aar"
ERES2NET_SRC="$REPO_ROOT/tools/speaker/models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"

echo "[1/4] build release AARs ..."
cd "$AR_ROOT"
./gradlew :sdk:assembleRelease :sdk-police:assembleRelease :sdk-dingqiao:assembleRelease :sample-dingqiao-demo:assembleRelease

echo "[2/4] merge fat AAR ..."
bash "$REPO_ROOT/tools/android/merge_dingqiao_fat_aar.sh" "$VERSION"
FAT_AAR="$AR_ROOT/build/dingqiao-delivery/$AAR_NAME"

echo "[3/4] assemble delivery tree ..."
rm -rf "$OUT_ROOT"
mkdir -p "$OUT_ROOT"/{aar,demo,models,docs}

cp "$FAT_AAR" "$OUT_ROOT/aar/"
cp "$AR_ROOT/sample-dingqiao-demo/build/outputs/apk/release/sample-dingqiao-demo-release.apk" "$OUT_ROOT/demo/"
if [[ ! -f "$ERES2NET_SRC" ]]; then
  echo "[ERROR] missing $ERES2NET_SRC" >&2
  exit 1
fi
cp "$ERES2NET_SRC" "$OUT_ROOT/models/eres2net.onnx"

cp "$DQ_ROOT/语音识别SDK接口.md" "$OUT_ROOT/docs/"
cp "$AR_ROOT/docs/DINGQIAO_DELIVERY.md" "$OUT_ROOT/docs/"
cp "$AR_ROOT/docs/INTEGRATION.md" "$OUT_ROOT/docs/"
cp "$AR_ROOT/docs/LICENSING.md" "$OUT_ROOT/docs/"

AAR_MB="$(du -m "$OUT_ROOT/aar/$AAR_NAME" | awk '{print $1}')"
APK_MB="$(du -m "$OUT_ROOT/demo/sample-dingqiao-demo-release.apk" | awk '{print $1}')"
MODEL_MB="$(du -m "$OUT_ROOT/models/eres2net.onnx" | awk '{print $1}')"

cd "$REPO_ROOT"
GIT_HASH="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
cat > "$OUT_ROOT/VERSION.txt" <<EOF
package=amphion-dingqiao-schemeA
version=$VERSION
sdk_version=0.2.2
git_commit=$GIT_HASH
build_date=$DATE
fat_aar_mb=$AAR_MB
demo_apk_mb=$APK_MB
voiceprint_model_mb=$MODEL_MB
EOF

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
  Demo APK 内已含 Demo 用 license，不可用于客户正式包。

版本
----
  见 VERSION.txt（commit: $GIT_HASH）
EOF

echo "[4/4] zip ..."
rm -f "$ZIP_PATH"
(cd "$DQ_ROOT/delivery" && zip -qr "$(basename "$ZIP_PATH")" "$(basename "$OUT_ROOT")")

echo "[OK] tree: $OUT_ROOT"
echo "[OK] zip:  $ZIP_PATH"
du -sh "$OUT_ROOT" "$ZIP_PATH"
