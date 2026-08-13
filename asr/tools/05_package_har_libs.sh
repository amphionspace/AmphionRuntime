#!/usr/bin/env bash
# 阶段 H.2：把 HarmonyOS native .so 复制到 Amphion HAR 与上游 sherpa_onnx HAR。

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SRC="$REPO_ROOT/third_party/sherpa-onnx/build-ohos-arm64-v8a/install/lib"
AMPHION_DST="$REPO_ROOT/asr/harmony/sdk/src/main/cpp/libs/arm64-v8a"
SHERPA_DST="$REPO_ROOT/third_party/sherpa-onnx/harmony-os/SherpaOnnxHar/sherpa_onnx/src/main/cpp/libs/arm64-v8a"
AGC_SO="$REPO_ROOT/asr/native/audio-processing/build-ohos-arm64-v8a/libamphion_audio_processing.so"

for f in libsherpa-onnx-c-api.so libonnxruntime.so; do
  if [[ ! -f "$SRC/$f" ]]; then
    echo "[ERROR] 缺少 ${SRC}/${f}，请先运行 asr/tools/04_build_harmony_so.sh"
    exit 1
  fi
done
if [[ ! -f "$AGC_SO" ]]; then
  echo "[ERROR] 缺少 ${AGC_SO}，请先运行 asr/tools/03_build_agc_native.sh ohos-arm64-v8a"
  exit 1
fi

mkdir -p "$AMPHION_DST" "$SHERPA_DST"
cp -v "$SRC/libsherpa-onnx-c-api.so" "$AMPHION_DST/"
cp -v "$SRC/libonnxruntime.so" "$AMPHION_DST/"
cp -v "$AGC_SO" "$AMPHION_DST/"
cp -v "$SRC/libsherpa-onnx-c-api.so" "$SHERPA_DST/"
cp -v "$SRC/libonnxruntime.so" "$SHERPA_DST/"

echo "[DONE] Harmony native libs packaged."
