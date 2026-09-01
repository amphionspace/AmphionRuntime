#!/usr/bin/env bash
# 一键产出 AmphionRuntime.xcframework：
#
#   1. 复用上游 build-ios.sh 编译 device + simulator 静态库
#   2. 把 sherpa-onnx.xcframework 重命名为 AmphionRuntime.xcframework
#   3. 把上游 swift-api-examples/SherpaOnnx.swift 复制到 Sources/SherpaOnnxBridge/
#   4. 产物放到 asr/ios/AmphionRuntime.xcframework/
#
# 用法：
#   bash asr/ios/build_xcframework.sh
#
# 选项（环境变量）：
#   SKIP_NATIVE_BUILD=1     跳过上游 build-ios.sh（已经编过的开发期加速）
#   ARCHIVE=1               额外产出 AmphionRuntime.xcframework.zip + sha256（用于 SPM binaryTarget）
#   ONNXRUNTIME_ARCHIVE=... 使用已下载的 ONNX Runtime 归档（仍会校验 SHA-256）
#
# 退出码：0 成功；非 0 任意失败

set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
SDK_ROOT="$ROOT/asr/ios"
BRIDGE_DIR="$SDK_ROOT/Sources/SherpaOnnxBridge"
CANONICAL_SHERPA_ROOT="$ROOT/third_party/sherpa-onnx"
SHERPA_ROOT="$SDK_ROOT/.native-src/sherpa-onnx"
PATCH_DIR="$ROOT/third_party/patches/sherpa-amphion"
PATCH_MARKER="$SHERPA_ROOT/.amphion-patches-applied"
UPSTREAM_BUILD_DIR="$SHERPA_ROOT/build-ios"
FW_NAME="AmphionRuntime"
ORT_VERSION="1.17.1"
ORT_ARCHIVE_NAME="onnxruntime.xcframework-$ORT_VERSION.tar.bz2"
ORT_ARCHIVE_SHA256="8406c942426551f826a73cb968afbe6dbe04cef899e2fe9c17a7ed775cba69f7"
ORT_ARCHIVE_BYTES="65801328"
ORT_URL="https://github.com/csukuangfj/onnxruntime-libs/releases/download/v$ORT_VERSION/$ORT_ARCHIVE_NAME"
ORT_ROOT="$UPSTREAM_BUILD_DIR/ios-onnxruntime"
ORT_VERSION_ROOT="$ORT_ROOT/$ORT_VERSION"
ORT_ARCHIVE="${ONNXRUNTIME_ARCHIVE:-$ORT_VERSION_ROOT/$ORT_ARCHIVE_NAME}"
ORT_LIBRARY="$ORT_VERSION_ROOT/onnxruntime.xcframework/ios-arm64/onnxruntime.a"
ORT_PROVENANCE="$ORT_VERSION_ROOT/.amphion-source-sha256"

DEVELOPER_PATH="${DEVELOPER_DIR:-$(xcode-select -p 2>/dev/null || true)}"
if [ -z "$DEVELOPER_PATH" ] || [[ "$DEVELOPER_PATH" == *"CommandLineTools"* ]]; then
  echo "[ERROR] full Xcode is required; current developer path: ${DEVELOPER_PATH:-unset}" >&2
  echo "        run: sudo xcode-select -s /Applications/Xcode.app/Contents/Developer" >&2
  exit 1
fi
if ! xcodebuild -version >/dev/null 2>&1; then
  echo "[ERROR] xcodebuild is unavailable from $DEVELOPER_PATH" >&2
  exit 1
fi
export DEVELOPER_DIR="$DEVELOPER_PATH"

if [ ! -f "$CANONICAL_SHERPA_ROOT/build-ios.sh" ]; then
  echo "[ERROR] $CANONICAL_SHERPA_ROOT/build-ios.sh missing; run: git submodule update --init --recursive" >&2
  exit 1
fi

# Native delivery must contain the same Amphion patch series used by Android/Harmony. Apply it in
# an ignored derived worktree so the pinned canonical submodule is never checked out/reset/mutated.
PATCH_SIG="$(cat "$PATCH_DIR"/*.patch | shasum -a 256 | awk '{print $1}')"
if [ ! -e "$SHERPA_ROOT/.git" ]; then
  mkdir -p "$(dirname "$SHERPA_ROOT")"
  echo "[source] Creating isolated sherpa-onnx worktree at $SHERPA_ROOT"
  git -C "$CANONICAL_SHERPA_ROOT" worktree add --detach "$SHERPA_ROOT" v1.13.1
fi
if [ -n "$(git -C "$SHERPA_ROOT" status --porcelain --untracked-files=no)" ]; then
  echo "[ERROR] derived native source is dirty: $SHERPA_ROOT" >&2
  echo "        inspect it manually; this script never resets or deletes source state" >&2
  exit 1
fi
if [ ! -f "$PATCH_MARKER" ]; then
  echo "[source] Applying Amphion sherpa patch series in isolated worktree"
  GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-Amphion CI}" \
  GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-ci@amphion.local}" \
    git -C "$SHERPA_ROOT" am --3way "$PATCH_DIR"/*.patch
  printf '%s\n' "$PATCH_SIG" > "$PATCH_MARKER"
elif [ "$(tr -d '[:space:]' < "$PATCH_MARKER")" != "$PATCH_SIG" ]; then
  echo "[ERROR] Amphion sherpa patch series changed after this derived source was prepared" >&2
  echo "        create a fresh isolated worktree after reviewing the new patches" >&2
  exit 1
fi

# 上游 build-ios.sh 会直接 wget 后解压、但不校验来源。交付构建先在这里固定资产，
# 校验通过后再让上游只执行编译；不修改 third_party 子模块。
if [ ! -f "$ORT_LIBRARY" ]; then
  mkdir -p "$ORT_VERSION_ROOT"
  if [ ! -f "$ORT_ARCHIVE" ]; then
    DOWNLOAD_TMP="$(mktemp "$ORT_VERSION_ROOT/$ORT_ARCHIVE_NAME.download.XXXXXX")"
    trap 'rm -f "$DOWNLOAD_TMP"' EXIT
    echo "[preflight] Downloading pinned ONNX Runtime $ORT_VERSION ..."
    curl -L --fail --retry 3 -o "$DOWNLOAD_TMP" "$ORT_URL"
    ORT_ARCHIVE="$DOWNLOAD_TMP"
  fi

  ACTUAL_BYTES="$(wc -c < "$ORT_ARCHIVE" | tr -d ' ')"
  if [ "$ACTUAL_BYTES" != "$ORT_ARCHIVE_BYTES" ]; then
    echo "[ERROR] ONNX Runtime archive size mismatch: expected $ORT_ARCHIVE_BYTES, got $ACTUAL_BYTES" >&2
    exit 3
  fi
  ACTUAL_SHA256="$(shasum -a 256 "$ORT_ARCHIVE" | awk '{print $1}')"
  if [ "$ACTUAL_SHA256" != "$ORT_ARCHIVE_SHA256" ]; then
    echo "[ERROR] ONNX Runtime archive SHA-256 mismatch" >&2
    echo "        expected: $ORT_ARCHIVE_SHA256" >&2
    echo "        actual:   $ACTUAL_SHA256" >&2
    exit 3
  fi

  echo "[preflight] Verified ONNX Runtime $ORT_VERSION ($ACTUAL_SHA256)"
  tar -xjf "$ORT_ARCHIVE" -C "$ORT_VERSION_ROOT"
  printf '%s\n' "$ORT_ARCHIVE_SHA256" > "$ORT_PROVENANCE"
elif [ ! -f "$ORT_PROVENANCE" ] || [ "$(tr -d '[:space:]' < "$ORT_PROVENANCE")" != "$ORT_ARCHIVE_SHA256" ]; then
  echo "[ERROR] existing ONNX Runtime has no matching Amphion provenance marker: $ORT_VERSION_ROOT" >&2
  echo "        remove this derived directory and rebuild from the pinned archive" >&2
  exit 3
fi
ln -sfn "$ORT_VERSION/onnxruntime.xcframework" "$ORT_ROOT/onnxruntime.xcframework"

cd "$SHERPA_ROOT"

# ---------- 1) 上游编译 ----------
if [ "${SKIP_NATIVE_BUILD:-0}" != "1" ]; then
  echo "[1/4] Building native via upstream build-ios.sh ..."
  bash "$SHERPA_ROOT/build-ios.sh"
else
  echo "[1/4] SKIP_NATIVE_BUILD=1, skipping native build"
fi

# 上游产物：third_party/sherpa-onnx/build-ios/sherpa-onnx.xcframework
SRC_FW="$UPSTREAM_BUILD_DIR/sherpa-onnx.xcframework"
if [ ! -d "$SRC_FW" ]; then
  echo "[ERROR] expected $SRC_FW after build-ios.sh; aborting" >&2
  exit 2
fi

# ---------- 2) 同步 SherpaOnnx.swift 到 Bridge ----------
mkdir -p "$BRIDGE_DIR"
cp "$SHERPA_ROOT/swift-api-examples/SherpaOnnx.swift" "$BRIDGE_DIR/SherpaOnnx.swift"

# 顶部加一行注解说明它是从上游 sync 过来的，不要直接改
TMP="$(mktemp)"
cat > "$TMP" <<EOF
// AUTO-SYNCED FROM upstream swift-api-examples/SherpaOnnx.swift
// 由 asr/ios/build_xcframework.sh 维护；不要直接改本文件。
// 修改请改上游或在 AmphionRuntime/ 下做 wrapper。

EOF
cat "$BRIDGE_DIR/SherpaOnnx.swift" >> "$TMP"
mv "$TMP" "$BRIDGE_DIR/SherpaOnnx.swift"

# Swift target 必须显式导入 binary target 暴露的 C 模块；target dependency 不会自动把
# C declarations 放入当前 Swift module 的作用域。
python3 - "$BRIDGE_DIR/SherpaOnnx.swift" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
source = path.read_text()
needle = "import Foundation  // For NSString\n"
replacement = needle + "import SherpaOnnxBinary\n"
if needle not in source:
    raise SystemExit(f"[ERROR] expected import marker not found in {path}")
path.write_text(source.replace(needle, replacement, 1))
PY

# ---------- 3) 复制并改名 xcframework ----------
DST_FW="$SDK_ROOT/$FW_NAME.xcframework"
rm -rf "$DST_FW"
cp -R "$SRC_FW" "$DST_FW"

# 上游 sherpa-onnx.xcframework 没有携带它链接所需的 ONNX Runtime，直接交付会在
# 客户 App 链接阶段报 `_OrtGetApiBase` 未定义。把已经过上方 provenance 校验的
# 对应 ORT slice 合入同一个静态库，保持 SwiftPM/CocoaPods 都只需一个 XCFramework。
for library in "$DST_FW"/*/libsherpa-onnx.a; do
  slice="$(basename "$(dirname "$library")")"
  case "$slice" in
    ios-arm64)
      ort_library="$ORT_VERSION_ROOT/onnxruntime.xcframework/ios-arm64/onnxruntime.a"
      ;;
    ios-arm64_x86_64-simulator)
      ort_library="$ORT_VERSION_ROOT/onnxruntime.xcframework/ios-arm64_x86_64-simulator/onnxruntime.a"
      ;;
    *)
      echo "[ERROR] unsupported XCFramework slice: $slice" >&2
      exit 4
      ;;
  esac
  if [ ! -f "$ort_library" ]; then
    echo "[ERROR] missing ONNX Runtime slice: $ort_library" >&2
    exit 4
  fi
  merged_library="$(mktemp "$library.merged.XXXXXX")"
  libtool -static -o "$merged_library" "$library" "$ort_library"
  mv "$merged_library" "$library"
done

# 上游 XCFramework 只有 Headers，没有 module map。SwiftPM 的 binaryTarget 因此会复制
# 静态库但不会导入任何 SherpaOnnx* C 声明。每个 slice 都写入同名模块映射，使
# `import SherpaOnnxBinary` 在真机与模拟器上具有一致行为。
while IFS= read -r headers_dir; do
  cat > "$headers_dir/module.modulemap" <<'EOF'
module SherpaOnnxBinary {
  header "sherpa-onnx/c-api/c-api.h"
  export *
}
EOF
done < <(find "$DST_FW" -type d -name Headers -print)

echo "[3/4] Wrote $DST_FW"

# ---------- 5) 可选：打包 + sha256 ----------
if [ "${ARCHIVE:-0}" == "1" ]; then
  ZIP="$SDK_ROOT/$FW_NAME.xcframework.zip"
  rm -f "$ZIP"
  ( cd "$SDK_ROOT" && zip -ry "$FW_NAME.xcframework.zip" "$FW_NAME.xcframework" >/dev/null )
  shasum -a 256 "$ZIP" | tee "$ZIP.sha256"
  echo "[4/4] Wrote $ZIP and $ZIP.sha256"
else
  echo "[4/4] ARCHIVE=0, skip zip"
fi

echo
echo "Done. 接下来你可以在 Xcode 中 File → Add Packages → 'Add Local' 选择 $SDK_ROOT 来集成。"
