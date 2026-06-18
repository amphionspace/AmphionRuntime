#!/usr/bin/env bash
# 预下载 sherpa-onnx Android 编译时 CMake FetchContent 需要的 tarball。
# 解决 GitHub / codeload SSL 不稳定（代理 198.18.x、curl 35）导致编 .so 失败。
#
# 用法（在 amphion-runtime 根目录）:
#   bash asr/tools/prefetch_sherpa_cmake_deps.sh
#   bash asr/tools/04_build_android_so.sh arm64-v8a
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SHERPA_ROOT="$REPO_ROOT/third_party/sherpa-onnx"
CACHE="$SCRIPT_DIR/sherpa-cmake-deps"

mkdir -p "$CACHE" "$HOME/Downloads"

ok()   { printf "\033[32m[OK]\033[0m   %s\n" "$*"; }
info() { printf "\033[36m[INFO]\033[0m %s\n" "$*"; }
warn() { printf "\033[33m[WARN]\033[0m %s\n" "$*"; }
err()  { printf "\033[31m[ERR]\033[0m  %s\n" "$*" >&2; exit 1; }

download_one() {
  local name="$1"
  local outfile="$2"
  local sha256="$3"
  shift 3
  local urls=("$@")

  if [[ -f "$outfile" ]]; then
    local got
    got="$(shasum -a 256 "$outfile" | awk '{print $1}')"
    if [[ "$got" == "$sha256" ]]; then
      ok "$name 已缓存且校验通过"
      return 0
    fi
    warn "$name 缓存损坏，重新下载"
    rm -f "$outfile"
  fi

  for url in "${urls[@]}"; do
    info "下载 $name <- $url"
    if curl -L --fail --retry 5 --retry-delay 3 --connect-timeout 30 \
         -o "$outfile" "$url"; then
      local got
      got="$(shasum -a 256 "$outfile" | awk '{print $1}')"
      if [[ "$got" == "$sha256" ]]; then
        ok "$name 下载成功 -> $outfile"
        return 0
      fi
      warn "$name 校验失败 (got $got)，尝试下一镜像"
      rm -f "$outfile"
    else
      warn "$name 从此 URL 下载失败，尝试下一镜像"
      rm -f "$outfile"
    fi
  done
  return 1
}

download_one_or_warn() {
  if download_one "$@"; then
    return 0
  fi
  warn "${1} 全部镜像均失败（可稍后重试）；cmake 阶段可能再拉"
  return 1
}

download_one "kaldifst" "$CACHE/kaldifst-1.8.0.tar.gz" \
  "3f247b7e5a2409071202f5e2bc6200060f66728c0a3443c03923ad2723e040b3" \
  "https://github.com/k2-fsa/kaldifst/archive/refs/tags/v1.8.0.tar.gz" \
  "https://ghproxy.net/https://github.com/k2-fsa/kaldifst/archive/refs/tags/v1.8.0.tar.gz" \
  "https://mirror.ghproxy.com/https://github.com/k2-fsa/kaldifst/archive/refs/tags/v1.8.0.tar.gz"

if [[ -f "$SHERPA_ROOT/build-android-arm64-v8a/_deps/kaldi_decoder-src/CMakeLists.txt" ]]; then
  ok "kaldi-decoder 已在 build _deps 中，跳过下载"
else
  download_one_or_warn "kaldi-decoder" "$CACHE/kaldi-decoder-0.3.0.tar.gz" \
    "b9f34cfb4fd3b1344100eead79ef4d37aa15962274b9e3056de345021f76a1b0" \
    "https://github.com/k2-fsa/kaldi-decoder/archive/refs/tags/v0.3.0.tar.gz" \
    "https://ghproxy.net/https://github.com/k2-fsa/kaldi-decoder/archive/refs/tags/v0.3.0.tar.gz" \
    "https://ghproxy.com/https://github.com/k2-fsa/kaldi-decoder/archive/refs/tags/v0.3.0.tar.gz" || true
fi

# kaldifst 用 04-10；sherpa 根 cmake/openfst.cmake 用 04-11，两个都要
download_one "openfst-04-10" "$CACHE/openfst-1.8.5-2026-04-10.tar.gz" \
  "c3549940384cbe4fa9f18c2bcfb1bfbd0a80492fd1b0bfa27433cee395a6a199" \
  "https://github.com/csukuangfj/openfst/archive/refs/tags/v1.8.5-2026-04-10.tar.gz" \
  "https://ghproxy.net/https://github.com/csukuangfj/openfst/archive/refs/tags/v1.8.5-2026-04-10.tar.gz" \
  "https://ghproxy.com/https://github.com/csukuangfj/openfst/archive/refs/tags/v1.8.5-2026-04-10.tar.gz"

download_one "openfst-04-11" "$CACHE/openfst-1.8.5-2026-04-11.tar.gz" \
  "57fbc4b950ae81b1a0e1e298af15652da968a6723a592b7874e9b4027a80a5b4" \
  "https://github.com/csukuangfj/openfst/archive/refs/tags/v1.8.5-2026-04-11.tar.gz" \
  "https://ghproxy.net/https://github.com/csukuangfj/openfst/archive/refs/tags/v1.8.5-2026-04-11.tar.gz" \
  "https://ghproxy.com/https://github.com/csukuangfj/openfst/archive/refs/tags/v1.8.5-2026-04-11.tar.gz"

# CMake 在以下路径查找本地包（见 sherpa-onnx/cmake/*.cmake 与 kaldi_decoder 内 kaldifst.cmake）
install_tar() {
  local f="$1"
  for base in \
    "$SHERPA_ROOT" \
    "$SHERPA_ROOT/build-android-arm64-v8a" \
    "$SHERPA_ROOT/build-android-armv7-eabi" \
    "$HOME/Downloads" \
    "/tmp" \
    ; do
    mkdir -p "$base"
    cp -f "$CACHE/$f" "$base/$f"
  done
}

info "分发到 CMake 本地查找路径 ..."
for f in kaldifst-1.8.0.tar.gz; do
  install_tar "$f"
done
for f in kaldi-decoder-0.3.0.tar.gz openfst-1.8.5-2026-04-10.tar.gz openfst-1.8.5-2026-04-11.tar.gz; do
  [[ -f "$CACHE/$f" ]] && install_tar "$f" || true
done

# 清掉上次失败的 FetchContent 半成品
for build in build-android-arm64-v8a build-android-armv7-eabi; do
  bd="$SHERPA_ROOT/$build"
  [[ -d "$bd/_deps/kaldifst-subbuild" ]] || continue
  info "清理 $build 内失败的 kaldifst-subbuild"
  rm -rf "$bd/_deps/kaldifst-subbuild" "$bd/_deps/kaldifst-src" \
         "$bd/_deps/openfst-subbuild" "$bd/_deps/openfst-src" 2>/dev/null || true
done

ok "CMake 依赖已就绪。请重新运行: bash asr/tools/04_build_android_so.sh arm64-v8a"
info "若仍 SSL 失败：关闭系统代理/VPN 后再编，或 export https_proxy= http_proxy= all_proxy="
