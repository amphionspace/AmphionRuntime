#!/usr/bin/env bash
# 打包鼎桥纯血鸿蒙客户交付包（ASR + TTS）。
# 该脚本收集 DevEco/Hvigor 已构建的 HAR/HAP、声纹/TTS 模型与文档，不负责启动 DevEco 构建。

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VERSION="${AMPHION_RUNTIME_VERSION:-0.1.0}"
OUT_ROOT="${1:-$REPO_ROOT/build/dingqiao-harmony-delivery-$VERSION}"

rm -rf "$OUT_ROOT"
mkdir -p "$OUT_ROOT/har" "$OUT_ROOT/demo" "$OUT_ROOT/models" "$OUT_ROOT/tts-models" "$OUT_ROOT/docs"

copy_if_exists() {
  local src="$1"
  local dst="$2"
  if [[ -f "$src" ]]; then
    cp -v "$src" "$dst"
  else
    echo "[WARN] missing: $src"
  fi
}

# DevEco/Hvigor 产物路径在不同版本中略有差异；优先收集常见输出。
copy_if_exists "$REPO_ROOT/asr/harmony/sdk/build/default/outputs/default/sdk.har" "$OUT_ROOT/har/amphion_asr.har"
copy_if_exists "$REPO_ROOT/asr/harmony/sdk-police/build/default/outputs/default/sdk_police.har" "$OUT_ROOT/har/amphion_police.har"
copy_if_exists "$REPO_ROOT/asr/harmony/sdk-dingqiao/build/default/outputs/default/sdk_dingqiao.har" "$OUT_ROOT/har/amphion_dingqiao.har"
copy_if_exists "$REPO_ROOT/tts/harmony/sdk/build/default/outputs/default/sdk.har" "$OUT_ROOT/har/amphion_tts.har"
copy_if_exists "$REPO_ROOT/harmony/samples/dingqiao-demo/entry/build/default/outputs/default/entry-default-signed.hap" "$OUT_ROOT/demo/dingqiao-demo.hap"

copy_if_exists "$REPO_ROOT/asr/android/sdk/src/main/assets/amphion-models/speaker/eres2net.onnx" "$OUT_ROOT/models/eres2net.onnx"
if [[ -d "$REPO_ROOT/tts/models/amphion-tts" ]]; then
  cp -R "$REPO_ROOT/tts/models/amphion-tts" "$OUT_ROOT/tts-models/"
else
  echo "[WARN] missing optional TTS models: $REPO_ROOT/tts/models/amphion-tts"
fi

cp -v "$REPO_ROOT/harmony/docs/DINGQIAO_INTEGRATION.md" "$OUT_ROOT/docs/"
cp -v "$REPO_ROOT/harmony/docs/DINGQIAO_LICENSE_SCHEME.md" "$OUT_ROOT/docs/"
cp -v "$REPO_ROOT/harmony/docs/customer/LICENSE.md" "$OUT_ROOT/docs/"
cp -v "$REPO_ROOT/harmony/docs/customer/NOTICE" "$OUT_ROOT/docs/"
cp -v "$REPO_ROOT/harmony/docs/PRIVACY.md" "$OUT_ROOT/docs/"
cp -v "$REPO_ROOT/harmony/docs/CHANGELOG.md" "$OUT_ROOT/docs/"

(
  cd "$OUT_ROOT"
  find . -type f | sort | while read -r f; do
    shasum -a 256 "$f"
  done > "$OUT_ROOT/docs/checksum.txt"
)

echo "[DONE] $OUT_ROOT"
