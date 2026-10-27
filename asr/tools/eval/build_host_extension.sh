#!/usr/bin/env bash
# 在宿主机（macOS / Linux）编译带 amphion 补丁的 sherpa-onnx Python 扩展。
#
# 这是整套评测的前提：宿主侧跑的必须是和 SDK 同一份解码器代码（同 32 个
# amphion 补丁），否则测出来的是上游行为而不是我们交付的行为。
#
# 用法：
#   asr/tools/eval/build_host_extension.sh [输出目录]
# 默认输出 third_party/.derived/sherpa-onnx/pypkg，用法：
#   export PYTHONPATH=<输出目录>
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
DERIVED="$REPO_ROOT/third_party/.derived/sherpa-onnx"
BUILD_DIR="${BUILD_DIR:-$DERIVED/build-host-macos}"
OUT_DIR="${1:-$DERIVED/pypkg}"
PYTHON="${PYTHON:-$(command -v python3)}"
JOBS="${JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)}"

# 1) 物化打补丁后的源码（canonical submodule 只读）
"$REPO_ROOT/asr/tools/prepare_sherpa_source.sh"

# 2) 配置 —— 只开 Python 绑定，关掉 TTS/JNI/C-API/portaudio 以缩短编译
#    （TTS 关闭会使上游 __init__.py 引用不存在的符号，见第 4 步）
cmake -S "$DERIVED" -B "$BUILD_DIR" \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=ON \
  -DSHERPA_ONNX_ENABLE_PYTHON=ON \
  -DSHERPA_ONNX_ENABLE_BINARY=ON \
  -DSHERPA_ONNX_ENABLE_TTS=OFF \
  -DSHERPA_ONNX_ENABLE_JNI=OFF \
  -DSHERPA_ONNX_ENABLE_C_API=OFF \
  -DSHERPA_ONNX_ENABLE_PORTAUDIO=OFF \
  -DPYTHON_EXECUTABLE="$PYTHON"

# 3) 编译
cmake --build "$BUILD_DIR" -j "$JOBS"

# 4) 组装可 import 的包
SO="$(find "$BUILD_DIR/lib" -name '_sherpa_onnx*.so' -o -name '_sherpa_onnx*.pyd' | head -1)"
[[ -n "$SO" ]] || { echo "[ERROR] 未找到编译出的扩展 _sherpa_onnx*.so" >&2; exit 1; }
rm -rf "$OUT_DIR/sherpa_onnx"
mkdir -p "$OUT_DIR/sherpa_onnx/lib"
cp "$DERIVED"/sherpa-onnx/python/sherpa_onnx/*.py "$OUT_DIR/sherpa_onnx/"
: > "$OUT_DIR/sherpa_onnx/lib/__init__.py"
cp "$SO" "$OUT_DIR/sherpa_onnx/lib/"

# 上游 __init__.py 导入 GenerationConfig 等 TTS 关闭后不存在的符号，换成裁剪版入口。
cat > "$OUT_DIR/sherpa_onnx/__init__.py" <<'PY'
# 裁剪版入口：扩展在 TTS / 部分特性关闭下编译，原 __init__ 引用的 GenerationConfig 等不存在。
# 这里只导出评测需要且确实存在的符号。
from .online_recognizer import OnlineRecognizer  # noqa: F401
from .lib._sherpa_onnx import (  # noqa: F401
    SpeakerEmbeddingExtractor,
    SpeakerEmbeddingExtractorConfig,
    SpeakerEmbeddingManager,
    OfflineSpeakerDiarization,
    OfflineSpeakerDiarizationConfig,
    OfflineSpeakerSegmentationModelConfig,
    OfflineSpeakerSegmentationPyannoteModelConfig,
    FastClusteringConfig,
)
PY

echo "[OK] 扩展已就绪: $(basename "$SO")"
echo "[OK] 使用方式: export PYTHONPATH=$OUT_DIR"
PY_OK=$(PYTHONPATH="$OUT_DIR" "$PYTHON" -c 'import sherpa_onnx; print("import ok")' 2>&1) || true
echo "[CHECK] $PY_OK"
