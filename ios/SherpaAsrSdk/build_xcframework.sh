#!/usr/bin/env bash
# 一键产出 SherpaAsrSdk.xcframework：
#
#   1. 复用上游 build-ios.sh 编译 device + simulator 静态库
#   2. 把 sherpa-onnx.xcframework 重命名为 SherpaAsrSdk.xcframework
#   3. 把上游 swift-api-examples/SherpaOnnx.swift 复制到 Sources/SherpaOnnxBridge/
#   4. 产物放到 ios/SherpaAsrSdk/SherpaAsrSdk.xcframework/
#
# 用法：
#   bash ios/SherpaAsrSdk/build_xcframework.sh
#
# 选项（环境变量）：
#   SKIP_NATIVE_BUILD=1     跳过上游 build-ios.sh（已经编过的开发期加速）
#   ARCHIVE=1               额外产出 SherpaAsrSdk.xcframework.zip + sha256（用于 SPM binaryTarget）
#
# 退出码：0 成功；非 0 任意失败

set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
SDK_ROOT="$ROOT/ios/SherpaAsrSdk"
BRIDGE_DIR="$SDK_ROOT/Sources/SherpaOnnxBridge"
SHERPA_ROOT="$ROOT/third_party/sherpa-onnx"
UPSTREAM_BUILD_DIR="$SHERPA_ROOT/build-ios"
FW_NAME="SherpaAsrSdk"

if [ ! -f "$SHERPA_ROOT/build-ios.sh" ]; then
  echo "[ERROR] $SHERPA_ROOT/build-ios.sh missing; run: git submodule update --init --recursive" >&2
  exit 1
fi

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
// 由 ios/SherpaAsrSdk/build_xcframework.sh 维护；不要直接改本文件。
// 修改请改上游或在 SherpaAsrSdk/ 下做 wrapper。

EOF
cat "$BRIDGE_DIR/SherpaOnnx.swift" >> "$TMP"
mv "$TMP" "$BRIDGE_DIR/SherpaOnnx.swift"

# ---------- 3) module.modulemap （让 Swift 能 import C 头文件） ----------
cat > "$BRIDGE_DIR/module.modulemap" <<'EOF'
// 占位：xcframework 已经自带 module.modulemap；本文件保留以方便子模块 import。
// SwiftPM 与 Xcode 会优先用 xcframework 内的 module map，不需要在这里重复声明 c-api/c-api.h。
EOF

# ---------- 4) 复制并改名 xcframework ----------
DST_FW="$SDK_ROOT/$FW_NAME.xcframework"
rm -rf "$DST_FW"
cp -R "$SRC_FW" "$DST_FW"
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
