#!/usr/bin/env bash
# 在终端里 source 本文件，或把末尾「写入 ~/.zshrc」段复制进去。
# 用法: source /path/to/amphion-runtime/scripts/mac_prep/00_android_env.sh

# ----- Java 17（Gradle 需要）-----
if /usr/libexec/java_home -v 17 &>/dev/null; then
  export JAVA_HOME="$(/usr/libexec/java_home -v 17)"
  export PATH="$JAVA_HOME/bin:$PATH"
fi

# ----- Android SDK（Studio 首次启动向导装完后才有这个目录）-----
# 常见笔误：~/Library/Android/Android/sdk（多一层 Android）→ 自动纠正
if [[ "${ANDROID_HOME:-}" == *"/Android/Android/"* ]]; then
  export ANDROID_HOME="$HOME/Library/Android/sdk"
elif [[ -z "${ANDROID_HOME:-}" ]]; then
  export ANDROID_HOME="$HOME/Library/Android/sdk"
fi
export ANDROID_SDK_ROOT="$ANDROID_HOME"

NDK_VER="26.3.11579264"
_default_ndk="$HOME/Library/Android/sdk/ndk/$NDK_VER"
if [[ -f "${ANDROID_NDK:-}/build/cmake/android.toolchain.cmake" ]]; then
  :
elif [[ -f "$_default_ndk/build/cmake/android.toolchain.cmake" ]]; then
  export ANDROID_NDK="$_default_ndk"
else
  export ANDROID_NDK="${ANDROID_NDK:-$ANDROID_HOME/ndk/$NDK_VER}"
fi

# adb / platform-tools：Homebrew cask 在 /opt/homebrew/bin，Studio SDK 在 $ANDROID_HOME/platform-tools
export PATH="/opt/homebrew/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/tools:$PATH"

# Android Studio.app（Homebrew cask 默认位置）
export ANDROID_STUDIO_APP="/Applications/Android Studio.app"

_show() {
  printf '\033[36m[android-env]\033[0m JAVA_HOME=%s\n' "${JAVA_HOME:-<unset>}"
  printf '\033[36m[android-env]\033[0m ANDROID_HOME=%s\n' "$ANDROID_HOME"
  printf '\033[36m[android-env]\033[0m ANDROID_NDK=%s\n' "$ANDROID_NDK"
  command -v adb >/dev/null && printf '\033[36m[android-env]\033[0m adb=%s (%s)\n' "$(command -v adb)" "$(adb version | head -1)"
  if [[ -d "$ANDROID_HOME" ]]; then
    printf '\033[32m[OK]\033[0m   SDK directory exists\n'
  else
    printf '\033[33m[WARN]\033[0m SDK not found — open Android Studio once: More Actions → SDK Manager\n'
  fi
  if [[ -d "$ANDROID_NDK" ]]; then
    printf '\033[32m[OK]\033[0m   NDK exists\n'
  else
    printf '\033[33m[WARN]\033[0m NDK %s missing — install NDK 26.3.11579264 in SDK Manager\n' "$ANDROID_NDK"
  fi
}

[[ -z "${ANDROID_ENV_QUIET:-}" ]] && _show
