#!/usr/bin/env bash
# Build the Amphion voice HAP.
#
#   bash asr/harmony-apps/amphion-voice/build.sh [debug|release]
#
# Hvigor rejects module paths that are symlinks, while the patched sherpa checkout is published
# through the third_party/.derived/sherpa-onnx link. The link is resolved for the duration of the
# build only; build-profile.json5 is restored on exit. Output: build/amphion-voice-<mode>.hap (signed
# when .secure/amphion-voice-signing.json5 exists, otherwise -unsigned).

set -euo pipefail

MODE="${1:-debug}"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$APP_DIR/../../.." && pwd)"

source "$REPO_ROOT/asr/tools/harmony_env.sh"
[[ -x "$NODE" && -f "$HVIGOR" && -x "$OHPM" ]] || {
  echo "[ERROR] Harmony command line tools not found under DEVECO_CLI_CLT_PATH=$DEVECO_CLI_CLT_PATH" >&2
  exit 1
}

# 04_build_harmony_so.sh materializes and links the patched checkout; do not re-validate it here
# because a native build in progress legitimately writes into that tree.
SHERPA_ROOT="$REPO_ROOT/third_party/.derived/sherpa-onnx"
[[ -d "$SHERPA_ROOT" ]] || { echo "[ERROR] run asr/tools/04_build_harmony_so.sh first" >&2; exit 1; }
SHERPA_HAR="$(cd "$SHERPA_ROOT/harmony-os/SherpaOnnxHar/sherpa_onnx" && pwd -P)"
[[ -f "$SHERPA_HAR/src/main/cpp/libs/arm64-v8a/libsherpa-onnx-c-api.so" ]] || {
  echo "[ERROR] sherpa native libs missing; run asr/tools/04_build_harmony_so.sh and 05_package_har_libs.sh" >&2
  exit 1
}
[[ -f "$APP_DIR/entry/src/main/resources/rawfile/amphion-license.lic" ]] || {
  echo "[WARN] entry/src/main/resources/rawfile/amphion-license.lic is missing; on-device recognition will be unavailable" >&2
}

# hvigor/ is ignored repository-wide; recreate the minimal config on a fresh checkout.
if [[ ! -f "$APP_DIR/hvigor/hvigor-config.json5" ]]; then
  mkdir -p "$APP_DIR/hvigor"
  printf '{\n  "modelVersion": "6.0.0",\n  "dependencies": {},\n  "execution": { "daemon": false }\n}\n' \
    > "$APP_DIR/hvigor/hvigor-config.json5"
fi

PROFILE="$APP_DIR/build-profile.json5"
BACKUP="$(mktemp)"
cp "$PROFILE" "$BACKUP"
restore() {
  cp "$BACKUP" "$PROFILE"; rm -f "$BACKUP"
  # ohpm rewrites this lock file inside the pinned sherpa checkout; keep that checkout pristine.
  git -C "$SHERPA_ROOT" checkout -- harmony-os/SherpaOnnxHar/sherpa_onnx/oh-package-lock.json5 2>/dev/null || true
}
trap restore EXIT

# Signing material stays outside Git (DevEco auto-signing output, copied into .secure/).
SIGNING="${AMPHION_VOICE_SIGNING:-$REPO_ROOT/.secure/amphion-voice-signing.json5}"
[[ -f "$SIGNING" ]] || echo "[WARN] $SIGNING not found; producing an unsigned HAP only" >&2

"$NODE" -e '
const fs = require("fs");
const [file, sherpa, signing] = process.argv.slice(1);
const text = fs.readFileSync(file, "utf8");
let next = text.replace(/("srcPath":\s*")[^"]*SherpaOnnxHar\/sherpa_onnx(")/, `$1${sherpa}$2`);
if (next === text && !text.includes(sherpa)) throw new Error("sherpa_onnx module entry not found in build-profile.json5");
if (fs.existsSync(signing)) {
  next = next.replace(/"signingConfigs":\s*\[\s*\]/, `"signingConfigs": ${fs.readFileSync(signing, "utf8").trim()}`);
}
fs.writeFileSync(file, next);
' "$PROFILE" "$SHERPA_HAR" "$SIGNING"

cd "$APP_DIR"
"$OHPM" install --all
"$DEVECO_CLI_CLT_PATH/hvigor/bin/hvigorw" --mode module -p product=default -p module=amphion_voice@default \
  -p buildMode="$MODE" assembleHap --no-daemon

OUTPUTS="$APP_DIR/entry/build/default/outputs/default"
mkdir -p "$APP_DIR/build"
if [[ -s "$OUTPUTS/amphion_voice-default-signed.hap" ]]; then
  cp "$OUTPUTS/amphion_voice-default-signed.hap" "$APP_DIR/build/amphion-voice-$MODE.hap"
  echo "[DONE] $APP_DIR/build/amphion-voice-$MODE.hap"
else
  [[ -s "$OUTPUTS/amphion_voice-default-unsigned.hap" ]] || { echo "[ERROR] HAP not produced" >&2; exit 1; }
  cp "$OUTPUTS/amphion_voice-default-unsigned.hap" "$APP_DIR/build/amphion-voice-$MODE-unsigned.hap"
  echo "[DONE] $APP_DIR/build/amphion-voice-$MODE-unsigned.hap"
fi
