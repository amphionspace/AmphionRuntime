#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PROJECT_ROOT="$REPO_ROOT/delivery/harmony-dingqiao"
DEVECO_HOME="${DEVECO_STUDIO_HOME:-/Applications/DevEco-Studio.app/Contents}"
NODE="$DEVECO_HOME/tools/node/bin/node"
HVIGOR="$DEVECO_HOME/tools/hvigor/bin/hvigorw.js"
OUTPUT_ROOT="${1:-$PROJECT_ROOT/build/diagnostics-sdk}"
if [[ "$OUTPUT_ROOT" != /* ]]; then
  OUTPUT_ROOT="$PWD/$OUTPUT_ROOT"
fi
mkdir -p "$OUTPUT_ROOT"
STAGING_ROOT="$(mktemp -d "$OUTPUT_ROOT/.diagnostics-sdk-package.XXXXXX")"
PACKAGE_ROOT="$STAGING_ROOT/Amphion-ASR-Diagnostics-SDK"

cleanup() {
  rm -rf "$STAGING_ROOT"
}
trap cleanup EXIT

export PATH="$DEVECO_HOME/tools/node/bin:$PATH"
export DEVECO_SDK_HOME="$DEVECO_HOME/sdk"
export JAVA_HOME="${JAVA_HOME:-$DEVECO_HOME/jbr/Contents/Home}"
cd "$PROJECT_ROOT"

if [[ "${SKIP_BUILD:-false}" != "true" ]]; then
  for module in sherpa_onnx amphion_asr amphion_police amphion_dingqiao; do
    "$NODE" "$HVIGOR" assembleHar --mode module \
      -p product=default -p module="${module}@default" -p buildMode=diagnostics \
      --no-daemon --stacktrace
  done

  if [[ "${INCLUDE_SIGNED_DEMO:-false}" == "true" ]]; then
    "$NODE" "$HVIGOR" assembleHap --mode module \
      -p product=default -p module=amphion_asr_demo@default -p buildMode=diagnostics \
      --no-daemon --stacktrace
  fi
fi

BUILD_IDENTITY="$OUTPUT_ROOT/build-identity.json"
python3 "$SCRIPT_DIR/harmony_build_identity.py" --write "$BUILD_IDENTITY"

mkdir -p "$PACKAGE_ROOT/sdk" "$PACKAGE_ROOT/demo" "$PACKAGE_ROOT/tools" "$PACKAGE_ROOT/docs"
cp "$REPO_ROOT/asr/harmony/sdk/build/default/outputs/default/amphion_asr.har" \
  "$PACKAGE_ROOT/sdk/amphion_asr-diagnostics.har"
cp "$REPO_ROOT/asr/harmony/sdk-police/build/default/outputs/default/amphion_police.har" \
  "$PACKAGE_ROOT/sdk/amphion_police-diagnostics.har"
cp "$REPO_ROOT/asr/harmony/sdk-dingqiao/build/default/outputs/default/amphion_dingqiao.har" \
  "$PACKAGE_ROOT/sdk/amphion_dingqiao-diagnostics.har"
cp "$REPO_ROOT/third_party/sherpa-onnx/harmony-os/SherpaOnnxHar/sherpa_onnx/build/default/outputs/default/sherpa_onnx.har" \
  "$PACKAGE_ROOT/sdk/sherpa_onnx.har"
cp "$SCRIPT_DIR/collect_asr_diagnostics.py" "$PACKAGE_ROOT/tools/"
cp "$BUILD_IDENTITY" "$PACKAGE_ROOT/tools/build-identity.json"
cp "$PROJECT_ROOT/docs/diagnostics-sdk/DIAGNOSTICS_GUIDE.md" "$PACKAGE_ROOT/docs/"
cp "$PROJECT_ROOT/docs/diagnostics-sdk/ISSUE_TEMPLATE.md" "$PACKAGE_ROOT/docs/"
cp "$PROJECT_ROOT/docs/diagnostics-sdk/PRIVACY_NOTICE.md" "$PACKAGE_ROOT/docs/"

SIGNED_HAP="$PROJECT_ROOT/samples/dingqiao-demo/entry/build/default/outputs/default/amphion_asr_demo-default-signed.hap"
if [[ "${INCLUDE_SIGNED_DEMO:-false}" == "true" && ! -f "$SIGNED_HAP" ]]; then
  echo "[ERROR] requested signed diagnostics Demo is missing: $SIGNED_HAP" >&2
  exit 1
fi
if [[ "${INCLUDE_SIGNED_DEMO:-false}" == "true" ]]; then
  cp "$SIGNED_HAP" "$PACKAGE_ROOT/demo/amphion_asr_demo-diagnostics-signed.hap"
fi

(
  cd "$PACKAGE_ROOT"
  find sdk demo tools docs -type f -print0 | sort -z | xargs -0 shasum -a 256 > checksums.txt
)
(
  cd "$STAGING_ROOT"
  ZIP_TEMP_DIR="$(mktemp -d "$OUTPUT_ROOT/.diagnostics-sdk-zip.XXXXXX")"
  /usr/bin/zip -X -q -r "$ZIP_TEMP_DIR/Amphion-ASR-Diagnostics-SDK.zip" Amphion-ASR-Diagnostics-SDK
  mv "$ZIP_TEMP_DIR/Amphion-ASR-Diagnostics-SDK.zip" "$OUTPUT_ROOT/Amphion-ASR-Diagnostics-SDK.zip"
  rmdir "$ZIP_TEMP_DIR"
  cd "$OUTPUT_ROOT"
  shasum -a 256 Amphion-ASR-Diagnostics-SDK.zip > Amphion-ASR-Diagnostics-SDK.zip.sha256
)
echo "[OK] $OUTPUT_ROOT/Amphion-ASR-Diagnostics-SDK.zip"
