#!/usr/bin/env bash
# 阶段 H.1：交叉编译 sherpa-onnx 的 HarmonyOS / OHOS native .so
#
# 用法（在 amphion-runtime 仓库根目录执行）：
#   bash asr/tools/04_build_harmony_so.sh
#
# 输出位于 third_party/.derived/ 的隔离 sherpa checkout。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SHERPA_ROOT="$(bash "$SCRIPT_DIR/prepare_sherpa_source.sh")"
export AMPHION_SHERPA_ROOT="$SHERPA_ROOT"

if [[ ! -f "$SHERPA_ROOT/CMakeLists.txt" ]]; then
  echo "[ERROR] 找不到 sherpa-onnx submodule：$SHERPA_ROOT"
  echo "        请先运行：git submodule update --init --recursive"
  exit 1
fi

_resolve_ohos_native() {
  local d
  for d in \
    "${OHOS_SDK_NATIVE_DIR:-}" \
    "${DEVECO_SDK_HOME:-}/default/openharmony/native" \
    "/Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/native" \
    "$HOME/Library/Huawei/Sdk/default/openharmony/native" \
    "$HOME/Library/OpenHarmony/Sdk/default/openharmony/native" \
    ; do
    [[ -n "$d" && -f "$d/build/cmake/ohos.toolchain.cmake" ]] && echo "$d" && return 0
  done
  return 1
}

if ! OHOS_SDK_NATIVE_DIR="$(_resolve_ohos_native)"; then
  echo "[ERROR] 找不到 OHOS native SDK（需含 build/cmake/ohos.toolchain.cmake）"
  echo "        请参考 asr/tools/HARMONY_TOOLCHAIN.md 设置 OHOS_SDK_NATIVE_DIR"
  exit 1
fi
export OHOS_SDK_NATIVE_DIR

echo "[INFO] Using OHOS native SDK: $OHOS_SDK_NATIVE_DIR"

export PATH="$OHOS_SDK_NATIVE_DIR/build-tools/cmake/bin:$OHOS_SDK_NATIVE_DIR/llvm/bin:$PATH"
export SHERPA_ONNX_ENABLE_TTS=ON
export SHERPA_ONNX_ENABLE_SPEAKER_DIARIZATION=OFF
export SHERPA_ONNX_ENABLE_BINARY=OFF
export SHERPA_ONNX_ENABLE_JNI=OFF
export SHERPA_ONNX_ENABLE_C_API=ON
export BUILD_SHARED_LIBS=ON

# 上游脚本会下载 OHOS onnxruntime 1.16.3 并输出 C-API 产物。
(
  cd "$SHERPA_ROOT"
  bash build-ohos-arm64-v8a.sh
)

OUT_DIR="$SHERPA_ROOT/build-ohos-arm64-v8a/install/lib"
ls -lh "$OUT_DIR/libsherpa-onnx-c-api.so" "$OUT_DIR/libonnxruntime.so"
python3 "$SCRIPT_DIR/verify_harmony_sherpa_symbols.py" \
  --library "$OUT_DIR/libsherpa-onnx-c-api.so" \
  --nm "$OHOS_SDK_NATIVE_DIR/llvm/bin/llvm-nm"

echo "[DONE] 接下来运行 asr/tools/05_package_har_libs.sh"
