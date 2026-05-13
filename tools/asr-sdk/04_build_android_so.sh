#!/usr/bin/env bash
# 阶段 B.1：交叉编译 sherpa-onnx 的 Android .so
#
# 用法（在 sherpa-asr-sdk 仓库根目录执行）：
#   bash tools/asr-sdk/04_build_android_so.sh                  # 默认编 arm64-v8a
#   bash tools/asr-sdk/04_build_android_so.sh arm64-v8a
#   bash tools/asr-sdk/04_build_android_so.sh armeabi-v7a
#   bash tools/asr-sdk/04_build_android_so.sh all              # 都编
#
# 前置：
#   - 已 export ANDROID_NDK=/path/to/ndk/26.3.11579264
#   - third_party/sherpa-onnx submodule 已经 checkout 在 .gitmodules 期望 tag
#     （首期 v1.13.1）。脚本会校验：必须停在某个上游 release tag 上，否则警告。
#   - 仓库本身（sherpa-asr-sdk）不需要 checkout 任何 tag；版本锁通过 submodule SHA。
#
# 输出（每个 ABI 一份；产物落在 submodule 内的构建目录，被根 .gitignore 排除）：
#   third_party/sherpa-onnx/build-android-arm64-v8a/install/lib/libsherpa-onnx-jni.so
#   third_party/sherpa-onnx/build-android-arm64-v8a/install/lib/libonnxruntime.so

set -euo pipefail

ABI_ARG="${1:-arm64-v8a}"

# ---------- 解析 sherpa-asr-sdk 根 + sherpa-onnx submodule 根 ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SHERPA_ROOT="$REPO_ROOT/third_party/sherpa-onnx"

if [[ ! -f "$SHERPA_ROOT/CMakeLists.txt" ]]; then
  echo "[ERROR] 找不到 sherpa-onnx submodule：$SHERPA_ROOT"
  echo "        请先运行：git submodule update --init --recursive"
  exit 1
fi

cd "$SHERPA_ROOT"

CURRENT_TAG="$(git describe --tags --exact-match 2>/dev/null || true)"
LATEST_TAG="$(git describe --tags --abbrev=0 2>/dev/null || echo unknown)"
if [[ -z "$CURRENT_TAG" ]]; then
  echo "[WARN] third_party/sherpa-onnx 当前不在任何 release tag 上，最近的是 ${LATEST_TAG}。"
  echo "[WARN] SDK 严格锁定 sherpa-onnx 版本，建议先："
  echo "         git -C $SHERPA_ROOT checkout v1.13.1"
  echo "         git -C $REPO_ROOT add third_party/sherpa-onnx"
  echo "       否则不要发版给客户。继续编译（按 Ctrl+C 取消）..."
  sleep 3
else
  echo "[INFO] sherpa-onnx submodule 在 release tag: $CURRENT_TAG"
fi

# ---------- 检查 NDK ----------
if [[ -z "${ANDROID_NDK:-}" ]]; then
  echo "[ERROR] 请先 export ANDROID_NDK=/path/to/ndk/26.3.11579264"
  echo "        参考 tools/asr-sdk/ANDROID_TOOLCHAIN.md"
  exit 1
fi
if [[ ! -f "$ANDROID_NDK/build/cmake/android.toolchain.cmake" ]]; then
  echo "[ERROR] $ANDROID_NDK 看起来不是合法 NDK"
  exit 1
fi

NDK_VERSION="$(grep -E '^Pkg.Revision' "$ANDROID_NDK/source.properties" | awk -F= '{print $2}' | tr -d ' ')"
echo "[INFO] Using NDK $NDK_VERSION at $ANDROID_NDK"
if [[ "$NDK_VERSION" != 26.* ]]; then
  echo "[WARN] 推荐 NDK r26d (26.3.11579264)，当前 $NDK_VERSION 可能与 AGP 8.4 兼容性不佳。"
fi

# ---------- 工具链预检查 ----------
# macOS 默认 没有 cmake / wget，需要 brew install
missing_tools=()
if ! command -v cmake >/dev/null 2>&1; then
  missing_tools+=("cmake")
fi
if ! command -v curl >/dev/null 2>&1; then
  missing_tools+=("curl")
fi
# wget 不强制：如果没有但有 curl，下面会用 curl 主动 prefetch onnxruntime
if [[ ${#missing_tools[@]} -gt 0 ]]; then
  echo "[ERROR] 缺少必备工具：${missing_tools[*]}"
  echo "        macOS 用户请先："
  echo "          /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"   # 没装 brew 时"
  echo "          eval \"\$(/opt/homebrew/bin/brew shellenv)\"                                                      # 让 brew 进 PATH"
  echo "          brew install ${missing_tools[*]} wget"
  exit 1
fi

echo "[INFO] cmake: $(command -v cmake) ($(cmake --version | head -1))"
if command -v wget >/dev/null 2>&1; then
  echo "[INFO] wget:  $(command -v wget)"
else
  echo "[WARN] 没装 wget；上游 build-android-*.sh 会用 wget 下 onnxruntime；本脚本会用 curl 提前下好绕过这一步。"
fi

# ---------- onnxruntime prefetch（避免上游脚本因 wget 缺失失败） ----------
# 如果 build-android-${ABI}/${ONNX_VER}/jni/<abi>/libonnxruntime.so 已经存在，上游脚本会跳过下载
ONNX_VER="1.24.3"
prefetch_onnxruntime() {
  local ABI="$1"
  local CACHE_DIR="$SHERPA_ROOT/build-android-${ABI}/${ONNX_VER}"
  local TARGET="$CACHE_DIR/jni/${ABI}/libonnxruntime.so"
  if [[ -f "$TARGET" ]]; then
    echo "[PREFETCH] onnxruntime ${ONNX_VER} 已缓存 -> $TARGET"
    return 0
  fi
  mkdir -p "$CACHE_DIR"
  local URL="https://github.com/csukuangfj/onnxruntime-libs/releases/download/v${ONNX_VER}/onnxruntime-android-${ONNX_VER}.zip"
  local ZIP="$CACHE_DIR/onnxruntime-android-${ONNX_VER}.zip"
  echo "[PREFETCH] downloading onnxruntime ${ONNX_VER} via curl..."
  curl -L --fail -o "$ZIP" "$URL"
  echo "[PREFETCH] unzipping..."
  ( cd "$CACHE_DIR" && unzip -o -q "$ZIP" && rm -f "$ZIP" )
  if [[ ! -f "$TARGET" ]]; then
    echo "[ERROR] onnxruntime prefetch 失败：解压后没有 $TARGET"
    return 1
  fi
  echo "[PREFETCH] OK -> $TARGET"
}

# ---------- 公共环境变量 ----------
# 与官方 build-android-arm64-v8a.sh 完全一致的开关，关掉 SDK 不需要的能力
# - 我们只做 ASR + VAD，不需要 TTS / Speaker / KWS / Punctuation 等
export SHERPA_ONNX_ENABLE_TTS=OFF
export SHERPA_ONNX_ENABLE_SPEAKER_DIARIZATION=OFF
export SHERPA_ONNX_ENABLE_BINARY=OFF
export SHERPA_ONNX_ENABLE_C_API=OFF       # 我们走 JNI，不需要 C API
export SHERPA_ONNX_ENABLE_JNI=ON
export SHERPA_ONNX_ANDROID_PLATFORM="android-24"   # 与 SDK minSdk 一致
export BUILD_SHARED_LIBS=ON

build_one_abi() {
  local ABI="$1"
  local SCRIPT
  case "$ABI" in
    arm64-v8a)    SCRIPT="$SHERPA_ROOT/build-android-arm64-v8a.sh";;
    armeabi-v7a)  SCRIPT="$SHERPA_ROOT/build-android-armv7-eabi.sh";;
    *) echo "unsupported abi: $ABI"; return 1;;
  esac

  if [[ ! -x "$SCRIPT" ]]; then
    chmod +x "$SCRIPT"
  fi

  prefetch_onnxruntime "$ABI"

  echo
  echo "================================================"
  echo "[BUILD] ABI = $ABI"
  echo "[BUILD] script = $SCRIPT"
  echo "================================================"
  ( cd "$SHERPA_ROOT" && bash "$SCRIPT" )

  local OUT_DIR="$SHERPA_ROOT/build-android-${ABI}/install/lib"
  echo
  echo "[CHECK] $OUT_DIR"
  ls -lh "$OUT_DIR/libsherpa-onnx-jni.so" "$OUT_DIR/libonnxruntime.so" || {
    echo "[ERROR] 没有生成预期的 .so"; return 2;
  }

  # 确认依赖关系
  command -v "$ANDROID_NDK/toolchains/llvm/prebuilt/$(uname -s | tr A-Z a-z)-x86_64/bin/llvm-readelf" >/dev/null \
    && READ="$ANDROID_NDK/toolchains/llvm/prebuilt/$(uname -s | tr A-Z a-z)-x86_64/bin/llvm-readelf" \
    || READ="$(which readelf)"
  if command -v "$READ" >/dev/null; then
    echo "[CHECK] libsherpa-onnx-jni.so NEEDED:"
    "$READ" -d "$OUT_DIR/libsherpa-onnx-jni.so" | grep NEEDED || true
  fi
}

case "$ABI_ARG" in
  arm64-v8a|armeabi-v7a)
    build_one_abi "$ABI_ARG"
    ;;
  all)
    build_one_abi arm64-v8a
    build_one_abi armeabi-v7a
    ;;
  *)
    echo "Unknown ABI: $ABI_ARG"; exit 1
    ;;
esac

echo
echo "[DONE] 接下来运行 tools/asr-sdk/05_package_aar_libs.sh 把 .so 拷到 SDK 工程。"
