#!/usr/bin/env bash
# 鼎桥正式交付包（方案 A：fat AAR + 对齐 Demo + 客户向文档，不含公钥/内部文档）。
#
# 用法（AmphionRuntime 仓库根目录）:
#   bash asr/tools/delivery/pack_dingqiao_customer_delivery.sh [交付版本号]
#
# Demo APK 签名：
#   正式交付应让 Gradle Release 直接产出已签名 APK，或提供以下环境变量对 unsigned APK 签名：
#     DINGQIAO_DEMO_KEYSTORE=/path/to.jks
#     DINGQIAO_DEMO_KEY_ALIAS=alias
#     DINGQIAO_DEMO_STORE_PASS=...
#     DINGQIAO_DEMO_KEY_PASS=...        # 可选，默认等于 STORE_PASS
#   本地验收可显式使用 debug keystore：
#     DINGQIAO_DEMO_SIGN_DEBUG=1 bash asr/tools/delivery/pack_dingqiao_customer_delivery.sh
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
DEMO_APK_DIR="$AR_ROOT/samples/dingqiao-demo/build/outputs/apk/release"
DEMO_APK_SRC="$DEMO_APK_DIR/dingqiao-demo-release.apk"
DEMO_LIC_SRC="$AR_ROOT/samples/dingqiao-demo/src/main/assets/amphion-license.lic"
DEMO_APK_SIGNING="gradle-release"
DEMO_APK_CERT_SHA="${DINGQIAO_DEMO_CERT_SHA256:-}"
DEMO_SIGN_KEYSTORE=""
DEMO_SIGN_ALIAS=""
DEMO_SIGN_STORE_PASS=""
DEMO_SIGN_KEY_PASS=""

if [[ "${DINGQIAO_DEMO_SIGN_DEBUG:-}" == "1" ]]; then
  DEMO_SIGN_KEYSTORE="${DINGQIAO_DEMO_DEBUG_KEYSTORE:-$HOME/.android/debug.keystore}"
  DEMO_SIGN_ALIAS="${DINGQIAO_DEMO_DEBUG_KEY_ALIAS:-androiddebugkey}"
  DEMO_SIGN_STORE_PASS="${DINGQIAO_DEMO_DEBUG_STORE_PASS:-android}"
  DEMO_SIGN_KEY_PASS="${DINGQIAO_DEMO_DEBUG_KEY_PASS:-$DEMO_SIGN_STORE_PASS}"
  DEMO_APK_SIGNING="debug-keystore"
elif [[ -n "${DINGQIAO_DEMO_KEYSTORE:-}" ]]; then
  DEMO_SIGN_KEYSTORE="$DINGQIAO_DEMO_KEYSTORE"
  DEMO_SIGN_ALIAS="${DINGQIAO_DEMO_KEY_ALIAS:?DINGQIAO_DEMO_KEY_ALIAS required when DINGQIAO_DEMO_KEYSTORE is set}"
  DEMO_SIGN_STORE_PASS="${DINGQIAO_DEMO_STORE_PASS:?DINGQIAO_DEMO_STORE_PASS required when DINGQIAO_DEMO_KEYSTORE is set}"
  DEMO_SIGN_KEY_PASS="${DINGQIAO_DEMO_KEY_PASS:-$DEMO_SIGN_STORE_PASS}"
  DEMO_APK_SIGNING="provided-keystore"
fi

if [[ -n "$DEMO_SIGN_KEYSTORE" ]]; then
  DEMO_APK_CERT_SHA="$(dingqiao_cert_sha256_from_keystore "$DEMO_SIGN_KEYSTORE" "$DEMO_SIGN_ALIAS" "$DEMO_SIGN_STORE_PASS")"
  export DINGQIAO_DEMO_CERT_SHA256="$DEMO_APK_CERT_SHA"
fi

echo "[1/4] build release AARs + merge fat AAR ..."
AMPHION_REQUIRE_ANDROID_NATIVE_LIBS=1 \
  bash "$REPO_ROOT/asr/tools/05_package_aar_libs.sh" arm64-v8a
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
if [[ ! -f "$DEMO_APK_SRC" ]]; then
  unsigned_apk="$DEMO_APK_DIR/dingqiao-demo-release-unsigned.apk"
  if [[ -n "$DEMO_SIGN_KEYSTORE" && -f "$unsigned_apk" ]]; then
    signed_apk="$DEMO_APK_DIR/dingqiao-demo-release-delivery-signed.apk"
    echo "[INFO] signing unsigned Demo APK with $DEMO_APK_SIGNING"
    dingqiao_sign_apk "$unsigned_apk" "$signed_apk" \
      "$DEMO_SIGN_KEYSTORE" "$DEMO_SIGN_ALIAS" "$DEMO_SIGN_STORE_PASS" "$DEMO_SIGN_KEY_PASS"
    DEMO_APK_SRC="$signed_apk"
  elif [[ "${DINGQIAO_ALLOW_UNSIGNED_DEMO:-}" == "1" && -f "$unsigned_apk" ]]; then
    echo "[WARN] using unsigned Demo APK only because DINGQIAO_ALLOW_UNSIGNED_DEMO=1: $unsigned_apk" >&2
    DEMO_APK_SRC="$unsigned_apk"
    DEMO_APK_SIGNING="unsigned-preview"
  fi
fi
[[ -f "$DEMO_APK_SRC" ]] || { echo "[ERROR] missing $DEMO_APK_SRC" >&2; exit 1; }
if [[ "$DEMO_APK_SIGNING" == "unsigned-preview" ]]; then
  echo "[ERROR] unsigned Demo APK is not allowed for customer delivery" >&2
  exit 1
fi
[[ -f "$DEMO_LIC_SRC" ]] || { echo "[ERROR] missing $DEMO_LIC_SRC" >&2; exit 1; }
dingqiao_verify_apk_signature "$DEMO_APK_SRC"
if [[ -z "$DEMO_APK_CERT_SHA" ]]; then
  DEMO_APK_CERT_SHA="$(dingqiao_apk_cert_sha256_from_apk "$DEMO_APK_SRC")"
fi
dingqiao_verify_apk_native_libs "$DEMO_APK_SRC"
dingqiao_verify_apk_speaker_model "$DEMO_APK_SRC"
dingqiao_verify_apk_asr_models "$DEMO_APK_SRC"

echo "[3/4] assemble customer delivery tree ..."
rm -rf "$OUT_ROOT"
mkdir -p "$OUT_ROOT"/{aar,demo,docs}

cp "$FAT_AAR" "$OUT_ROOT/aar/"
cp "$DEMO_APK_SRC" "$OUT_ROOT/demo/dingqiao-demo-release.apk"

dingqiao_stage_customer_docs "$OUT_ROOT/docs" "$CUSTOMER_DOCS" "$DQ_ROOT"

AAR_MB="$(du -m "$OUT_ROOT/aar/$AAR_NAME" | awk '{print $1}')"
APK_MB="$(du -m "$OUT_ROOT/demo/dingqiao-demo-release.apk" | awk '{print $1}')"

dingqiao_write_version_txt "$OUT_ROOT/VERSION.txt" \
  "amphion-dingqiao-customer" "$VERSION" \
  "product=amphion-dingqiao-asr" \
  "integration=scheme-a-fat-aar" \
  "aar_file=$AAR_NAME" \
  "aar_mb=$AAR_MB" \
  "demo_apk_mb=$APK_MB" \
  "demo_apk_signing=$DEMO_APK_SIGNING" \
  "demo_apk_cert_sha256=${DEMO_APK_CERT_SHA:-not-set}" \
  "voiceprint_model=embedded-in-aar" \
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
  - 商用授权文件单独下发，不包含在本压缩包内；正式 App 授权可绑定 SN 清单，并可供 ASR/TTS 共用。
  - 声纹模型已内置于 SDK AAR，首次运行会自动解包到 setWorkPath，无需单独下发 models/eres2net.onnx。
  - 版本与 git 溯源见 VERSION.txt（含 git_commit_full / buildconfig_sdk_version）
  - Demo APK 内 license 为 2 个月试用（记录 demo 包名，绑定 Demo 签名，不绑定 SN）；签名来源见 VERSION.txt 的 demo_apk_signing
  - 第三方开源组件声明见 docs/NOTICE（sherpa-onnx / ONNX Runtime / silero-vad / 3D-Speaker 等）
  - 快速静态校验: bash asr/tools/delivery/verify_dingqiao_delivery.sh <本zip>
  - 最终验收: 按内部流程运行 tools/delivery/verify_delivery_zip_e2e.sh，以最终 zip 解压内容为唯一验收对象
EOF

echo "[4/4] zip (UTF-8 EFS for Windows) ..."
rm -f "$ZIP_PATH"
dingqiao_zip_delivery "$OUT_ROOT" "$ZIP_PATH"

echo "[OK] tree: $OUT_ROOT"
echo "[OK] zip:  $ZIP_PATH"
du -sh "$OUT_ROOT" "$ZIP_PATH"
