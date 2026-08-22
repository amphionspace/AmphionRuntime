#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PROJECT_ROOT="$REPO_ROOT/delivery/harmony-dingqiao"
DEVECO_HOME="${DEVECO_STUDIO_HOME:-/Applications/DevEco-Studio.app/Contents}"
NODE="$DEVECO_HOME/tools/node/bin/node"
HVIGOR="$DEVECO_HOME/tools/hvigor/bin/hvigorw.js"
OUTPUT_ROOT="${1:-$PROJECT_ROOT/build/debug-sdk}"
PACKAGE_ROOT="$OUTPUT_ROOT/Amphion-ASR-Debug-SDK"

export PATH="$DEVECO_HOME/tools/node/bin:$PATH"
export DEVECO_SDK_HOME="$DEVECO_HOME/sdk"
export JAVA_HOME="${JAVA_HOME:-$DEVECO_HOME/jbr/Contents/Home}"
cd "$PROJECT_ROOT"

SIGNED_HAP="$PROJECT_ROOT/samples/dingqiao-demo/entry/build/default/outputs/default/amphion_asr_demo-default-signed.hap"
[[ -f "$SIGNED_HAP" ]] || {
  echo "[ERROR] build and verify a signed Debug HAP before packaging so provenance can bind it" >&2
  exit 1
}

for module in sherpa_onnx amphion_asr amphion_police amphion_dingqiao; do
  "$NODE" "$HVIGOR" assembleHar --mode module \
    -p product=default -p module="${module}@default" -p buildMode=debug \
    --no-daemon --stacktrace
done

BUILD_IDENTITY="$OUTPUT_ROOT/build-identity.json"
python3 "$SCRIPT_DIR/harmony_build_identity.py" --write "$BUILD_IDENTITY"

mkdir -p "$PACKAGE_ROOT/sdk" "$PACKAGE_ROOT/tools" "$PACKAGE_ROOT/docs"
bash "$SCRIPT_DIR/assemble_selfcontained_dingqiao_har.sh" --zh-en-only \
  "$PACKAGE_ROOT/sdk/amphion_dingqiao-debug.har"
"$SCRIPT_DIR/verify_selfcontained_dingqiao_har.sh" --zh-en-only \
  "$PACKAGE_ROOT/sdk/amphion_dingqiao-debug.har"
cp "$SCRIPT_DIR/collect_asr_diagnostics.py" "$PACKAGE_ROOT/tools/"
cp "$BUILD_IDENTITY" "$PACKAGE_ROOT/tools/build-identity.json"
cp "$PROJECT_ROOT/docs/debug-sdk/DEBUG_GUIDE.md" "$PACKAGE_ROOT/docs/"
cp "$PROJECT_ROOT/docs/debug-sdk/ISSUE_TEMPLATE.md" "$PACKAGE_ROOT/docs/"
cp "$PROJECT_ROOT/docs/debug-sdk/PRIVACY_NOTICE.md" "$PACKAGE_ROOT/docs/"

(
  cd "$PACKAGE_ROOT"
  find sdk tools docs -type f -print0 | sort -z | xargs -0 shasum -a 256 > checksums.txt
)
mkdir -p "$OUTPUT_ROOT"
(
  cd "$OUTPUT_ROOT"
  ZIP_TEMP_DIR="$(mktemp -d "$OUTPUT_ROOT/.debug-sdk-zip.XXXXXX")"
  /usr/bin/zip -X -q -r "$ZIP_TEMP_DIR/Amphion-ASR-Debug-SDK.zip" Amphion-ASR-Debug-SDK
  mv "$ZIP_TEMP_DIR/Amphion-ASR-Debug-SDK.zip" Amphion-ASR-Debug-SDK.zip
  rmdir "$ZIP_TEMP_DIR"
  shasum -a 256 Amphion-ASR-Debug-SDK.zip > Amphion-ASR-Debug-SDK.zip.sha256
)
echo "[OK] $OUTPUT_ROOT/Amphion-ASR-Debug-SDK.zip"
