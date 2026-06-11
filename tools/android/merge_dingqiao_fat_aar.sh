#!/usr/bin/env bash
# 将 sdk + sdk-police + sdk-dingqiao 三个 release AAR 合并为单一 dingqiao-asr-*.aar（方案 A）。
#
# 用法（仓库根目录）:
#   bash tools/android/merge_dingqiao_fat_aar.sh [版本号]
#
# 默认版本号 0.1.0 → 输出 dingqiao-asr-v0.1.0.aar
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
AR_ROOT="$REPO_ROOT/android/AmphionRuntime"
VERSION="${1:-0.1.0}"
OUT_NAME="dingqiao-asr-v${VERSION}.aar"

SDK_AAR="$AR_ROOT/sdk/build/outputs/aar/sdk-release.aar"
SDK_CLASSES_UNMINIFIED="$AR_ROOT/sdk/build/intermediates/compile_library_classes_jar/release/bundleLibCompileToJarRelease/classes.jar"
POLICE_AAR="$AR_ROOT/sdk-police/build/outputs/aar/sdk-police-release.aar"
DINGQIAO_AAR="$AR_ROOT/sdk-dingqiao/build/outputs/aar/sdk-dingqiao-release.aar"

for f in "$SDK_AAR" "$SDK_CLASSES_UNMINIFIED" "$POLICE_AAR" "$DINGQIAO_AAR"; do
  if [[ ! -f "$f" ]]; then
    echo "[ERROR] missing $f — run assembleRelease for :sdk :sdk-police :sdk-dingqiao first" >&2
    exit 1
  fi
done

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

unpack() {
  local aar="$1" name="$2"
  mkdir -p "$WORKDIR/$name"
  unzip -q "$aar" -d "$WORKDIR/$name"
}

unpack "$SDK_AAR" sdk
unpack "$POLICE_AAR" police
unpack "$DINGQIAO_AAR" dingqiao

MERGE="$WORKDIR/merge"
mkdir -p "$MERGE/assets" "$MERGE/jni" "$MERGE/META-INF"

# classes.jar：合并三模块字节码。sdk 用未混淆 compile jar（release AAR 已 R8，直接合并会导致
# files() 集成 / Demo 二次 R8 报 Missing class b.* 或 b.C/b.c 冲突）。
CLASSES_DIR="$WORKDIR/classes_merge"
mkdir -p "$CLASSES_DIR"
(cd "$CLASSES_DIR" && jar xf "$SDK_CLASSES_UNMINIFIED")
for mod in police dingqiao; do
  (cd "$CLASSES_DIR" && jar xf "$WORKDIR/$mod/classes.jar")
done
(cd "$CLASSES_DIR" && jar cf "$MERGE/classes.jar" .)

# assets / jni：sdk 含模型与 native，police 含警务 FST/词表
cp -R "$WORKDIR/sdk/assets/"* "$MERGE/assets/" 2>/dev/null || true
cp -R "$WORKDIR/police/assets/"* "$MERGE/assets/" 2>/dev/null || true
cp -R "$WORKDIR/dingqiao/assets/"* "$MERGE/assets/" 2>/dev/null || true
cp -R "$WORKDIR/sdk/jni/"* "$MERGE/jni/" 2>/dev/null || true

# 对外 manifest 以 dingqiao 适配层为准
cp "$WORKDIR/dingqiao/AndroidManifest.xml" "$MERGE/AndroidManifest.xml"

# consumer ProGuard 规则（供业务 App R8；勿带入 sdk-release 混淆 mapping）
{
  echo "# --- sdk/consumer-rules.pro ---"
  cat "$AR_ROOT/sdk/consumer-rules.pro"
  echo
  echo "# --- sdk-police/consumer-rules.pro ---"
  cat "$AR_ROOT/sdk-police/consumer-rules.pro"
  echo
  echo "# --- sdk-dingqiao/consumer-rules.pro ---"
  cat "$AR_ROOT/sdk-dingqiao/consumer-rules.pro"
} > "$MERGE/proguard.txt"

# R.txt：仅 sdk 有资源索引时保留
if [[ -f "$WORKDIR/sdk/R.txt" ]]; then
  cp "$WORKDIR/sdk/R.txt" "$MERGE/R.txt"
fi

OUT_DIR="$AR_ROOT/build/dingqiao-delivery"
mkdir -p "$OUT_DIR"
OUT_PATH="$OUT_DIR/$OUT_NAME"
rm -f "$OUT_PATH"
(cd "$MERGE" && zip -qr "$OUT_PATH" .)

SIZE_MB="$(du -m "$OUT_PATH" | awk '{print $1}')"
echo "[OK] $OUT_PATH (${SIZE_MB} MB)"
