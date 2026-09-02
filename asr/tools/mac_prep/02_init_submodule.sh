#!/usr/bin/env bash
# 初始化 sherpa-onnx；网络不稳时加大 buffer，pin 失败则回退 v1.13.1
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$REPO"

git config --global http.postBuffer 524288000 2>/dev/null || true
git config --global http.lowSpeedLimit 0 2>/dev/null || true
git config --global http.lowSpeedTime 999999 2>/dev/null || true

echo "[INFO] init third_party/sherpa-onnx (may take several minutes) ..."
if ! git submodule update --init --recursive; then
  warn() { printf "\033[33m[WARN]\033[0m %s\n" "$*"; }
  warn "submodule update failed; retry with full clone + v1.13.1 fallback ..."
  rm -rf third_party/sherpa-onnx
  git clone --progress https://github.com/k2-fsa/sherpa-onnx.git third_party/sherpa-onnx
  (
    cd third_party/sherpa-onnx
    git fetch --tags origin 2>/dev/null || true
    git checkout v1.13.1
  )
fi

test -f third_party/sherpa-onnx/CMakeLists.txt
bash "$REPO/asr/tools/apply_sherpa_patches.sh"
echo "[OK] submodule ready at $(cd third_party/sherpa-onnx && git rev-parse --short HEAD)"
