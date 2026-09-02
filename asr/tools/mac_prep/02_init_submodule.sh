#!/usr/bin/env bash
# 初始化 sherpa-onnx；网络不稳时加大 buffer，pin 失败则回退 v1.13.1
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$REPO"

git config --global http.postBuffer 524288000 2>/dev/null || true
git config --global http.lowSpeedLimit 0 2>/dev/null || true
git config --global http.lowSpeedTime 999999 2>/dev/null || true

echo "[INFO] init third_party/sherpa-onnx (may take several minutes) ..."
git submodule update --init --recursive

test -f third_party/sherpa-onnx/CMakeLists.txt
DERIVED="$(bash "$REPO/asr/tools/prepare_sherpa_source.sh")"
echo "[OK] canonical submodule remains pinned at $(cd third_party/sherpa-onnx && git rev-parse --short HEAD)"
echo "[OK] Amphion patched source ready at $DERIVED"
