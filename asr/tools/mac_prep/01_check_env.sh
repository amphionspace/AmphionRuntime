#!/usr/bin/env bash
# Mac 开发环境自检（对应「等待模型期间」准备工作 ①）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# 与 00_android_env.sh 使用同一套默认路径
if [[ -f "$SCRIPT_DIR/00_android_env.sh" ]]; then
  ANDROID_ENV_QUIET=1
  # shellcheck source=/dev/null
  source "$SCRIPT_DIR/00_android_env.sh" >/dev/null 2>&1 || true
fi

ok()   { printf "\033[32m[OK]\033[0m   %s\n" "$*"; }
warn() { printf "\033[33m[WARN]\033[0m %s\n" "$*"; }
err()  { printf "\033[31m[MISS]\033[0m %s\n" "$*"; }

FAIL=0

if command -v git >/dev/null; then ok "git $(git --version | awk '{print $3}')"; else err "git"; FAIL=1; fi

if /usr/libexec/java_home -V >/dev/null 2>&1; then
  ok "JDK: $(/usr/libexec/java_home 2>/dev/null)"
else
  err "JDK — 安装: brew install --cask temurin@17"
  FAIL=1
fi

SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Library/Android/sdk}}"
if [[ -d "$SDK" && -d "$SDK/platform-tools" ]]; then
  ok "Android SDK: $SDK"
elif [[ -d "$HOME/Library/Android/sdk/platform-tools" ]]; then
  SDK="$HOME/Library/Android/sdk"
  export ANDROID_HOME="$SDK" ANDROID_SDK_ROOT="$SDK"
  ok "Android SDK: $SDK (auto-detected)"
else
  err "Android SDK — 打开 Android Studio 完成 Setup Wizard，或: source asr/tools/mac_prep/00_android_env.sh"
  err "  期望目录: $HOME/Library/Android/sdk/platform-tools"
  FAIL=1
fi

if command -v adb >/dev/null; then ok "adb $(adb version | head -1)"; else
  err "adb — brew install --cask android-platform-tools 或 Android Studio SDK Tools"
  FAIL=1
fi

NDK_VER="26.3.11579264"
NDK_DIR="$SDK/ndk/$NDK_VER"
if [[ -d "$NDK_DIR" ]]; then ok "NDK $NDK_VER"; else
  warn "NDK $NDK_VER 未安装 — Android Studio SDK Manager 安装 NDK r26d"
fi

REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
if [[ -f "$REPO/third_party/sherpa-onnx/CMakeLists.txt" ]]; then
  ok "sherpa-onnx submodule"
else
  err "sherpa-onnx submodule 未初始化 — 运行 asr/tools/mac_prep/02_init_submodule.sh"
  FAIL=1
fi

if command -v python3 >/dev/null; then ok "python3"; else err "python3"; FAIL=1; fi

if command -v cmake >/dev/null; then ok "cmake $(cmake --version | head -1)"; else
  err "cmake — 编 native .so 需要: brew install cmake"
  FAIL=1
fi

if [[ $FAIL -eq 0 ]]; then
  ok "环境就绪，可运行 03_build_demo.sh"
else
  warn "请先补齐 MISS 项后再编 demo / 跑 Gradle 测试"
  exit 1
fi
