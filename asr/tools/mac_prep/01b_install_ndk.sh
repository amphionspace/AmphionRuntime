#!/usr/bin/env bash
# 用 sdkmanager 安装 NDK 26.3.11579264（需先装 Command-line Tools）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/00_android_env.sh" >/dev/null 2>&1 || true

SDK="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
NDK_VER="26.3.11579264"
PKG="ndk;${NDK_VER}"

find_sdkmanager() {
  local c
  for c in \
    "$SDK/cmdline-tools/latest/bin/sdkmanager" \
    "$SDK/cmdline-tools/bin/sdkmanager" \
    ; do
    [[ -x "$c" ]] && echo "$c" && return 0
  done
  find "$SDK/cmdline-tools" -name sdkmanager -type f 2>/dev/null | head -1
}

SM="$(find_sdkmanager || true)"
if [[ -z "$SM" || ! -x "$SM" ]]; then
  echo "[ERR] 找不到 sdkmanager。请在 Android Studio 里安装："
  echo "      Settings → Android SDK → SDK Tools → 勾选"
  echo "        - Android SDK Command-line Tools (latest)"
  echo "        - NDK (Side by side) → 展开选 ${NDK_VER}"
  echo "      点 Apply，装完再运行: bash asr/tools/mac_prep/01_check_env.sh"
  exit 1
fi

echo "[INFO] using $SM"
yes | "$SM" --licenses >/dev/null 2>&1 || true
"$SM" --install "$PKG"

if [[ -d "$SDK/ndk/$NDK_VER" ]]; then
  echo "[OK] NDK installed: $SDK/ndk/$NDK_VER"
else
  echo "[ERR] install finished but $SDK/ndk/$NDK_VER not found"
  exit 1
fi
