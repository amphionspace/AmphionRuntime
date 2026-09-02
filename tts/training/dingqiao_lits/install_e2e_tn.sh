#!/bin/bash
# Build Dingqiao TN binaries and install macOS host binaries for infer_e2e.py.
#
# e2e_infer/ is NOT in git (see .gitignore). This script creates it on first run.
# Dingqiao build.sh outputs to Dingqiao_Multilingual_Text_Normalization_for_TTS/test/bin/;
# we copy *_tts into a platform-specific directory so macOS and Android builds do not overwrite each other.
#
# Usage (from repo root):
#   export ICU_ROOT="$CONDA_PREFIX"   # Linux / Conda if needed
#   bash install_e2e_tn.sh
#
# Outputs:
#   e2e_infer/bin-macos-arm64/       macOS host binaries for local frontend tests
#   e2e_infer/bin-android-arm64/     Android binaries built separately with the NDK

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TN_ROOT="$REPO_ROOT/Dingqiao_Multilingual_Text_Normalization_for_TTS"
BUILD_OUT="$TN_ROOT/test/bin"
INSTALL_DIR="${TN_INSTALL_DIR:-$REPO_ROOT/e2e_infer/bin-macos-arm64}"

if [[ ! -d "$TN_ROOT" ]]; then
  echo "Missing TN submodule: $TN_ROOT" >&2
  echo "Run: git submodule update --init Dingqiao_Multilingual_Text_Normalization_for_TTS" >&2
  exit 1
fi

echo "[install_e2e_tn] Building TN binaries ..."
bash "$TN_ROOT/test/scripts/build.sh"

echo "[install_e2e_tn] Installing to $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR"
cp -f "$BUILD_OUT"/*_tts "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR"/*_tts

if [[ "${TN_UPDATE_LEGACY_BIN:-0}" == "1" ]]; then
  LEGACY_DIR="$REPO_ROOT/e2e_infer/bin"
  echo "[install_e2e_tn] TN_UPDATE_LEGACY_BIN=1, also updating $LEGACY_DIR ..."
  mkdir -p "$LEGACY_DIR"
  cp -f "$BUILD_OUT"/*_tts "$LEGACY_DIR/"
  chmod +x "$LEGACY_DIR"/*_tts
fi

echo "[install_e2e_tn] Done. Installed:"
ls -1 "$INSTALL_DIR"/*_tts
