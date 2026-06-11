#!/usr/bin/env bash
# 将 sdk + sdk-police + sdk-dingqiao 三个 release AAR 合并为单一 dingqiao-asr-*.aar（方案 A）。
#
# 用法（AmphionRuntime 仓库根目录）:
#   bash tools/android/merge_dingqiao_fat_aar.sh [交付版本号]
#
# 默认交付版本号 = gradle.properties 的 AMPHION_RUNTIME_VERSION
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=dingqiao_build_provenance.sh
source "$SCRIPT_DIR/dingqiao_build_provenance.sh"

REPO_ROOT="$(dingqiao_repo_root_from_script)"
AR_ROOT="$(dingqiao_ar_root_from_repo "$REPO_ROOT")"
BUILD_DATE="$(date +%Y%m%d)"
dingqiao_load_git_provenance "$REPO_ROOT"
dingqiao_assert_reproducible_build
dingqiao_assert_sdk_version_consistent "$AR_ROOT"

VERSION="$(dingqiao_resolve_delivery_version "$AR_ROOT" "${1:-}")"
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

CLASSES_DIR="$WORKDIR/classes_merge"
mkdir -p "$CLASSES_DIR"
(cd "$CLASSES_DIR" && jar xf "$SDK_CLASSES_UNMINIFIED")
for mod in police dingqiao; do
  (cd "$CLASSES_DIR" && jar xf "$WORKDIR/$mod/classes.jar")
done
(cd "$CLASSES_DIR" && jar cf "$MERGE/classes.jar" .)

cp -R "$WORKDIR/sdk/assets/"* "$MERGE/assets/" 2>/dev/null || true
cp -R "$WORKDIR/police/assets/"* "$MERGE/assets/" 2>/dev/null || true
cp -R "$WORKDIR/dingqiao/assets/"* "$MERGE/assets/" 2>/dev/null || true
cp -R "$WORKDIR/sdk/jni/"* "$MERGE/jni/" 2>/dev/null || true

cp "$WORKDIR/dingqiao/AndroidManifest.xml" "$MERGE/AndroidManifest.xml"

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

if ! grep -q 'java.lang.invoke.StringConcatFactory' "$MERGE/proguard.txt"; then
  echo "[ERROR] merged proguard.txt missing -dontwarn java.lang.invoke.StringConcatFactory" >&2
  exit 1
fi

dingqiao_embed_aar_build_manifest "$MERGE" "$AR_ROOT" "$VERSION"

if [[ -f "$WORKDIR/sdk/R.txt" ]]; then
  cp "$WORKDIR/sdk/R.txt" "$MERGE/R.txt"
fi

OUT_DIR="$AR_ROOT/build/dingqiao-delivery"
mkdir -p "$OUT_DIR"
OUT_PATH="$OUT_DIR/$OUT_NAME"
rm -f "$OUT_PATH"
(cd "$MERGE" && zip -qr "$OUT_PATH" .)

dingqiao_verify_aar_provenance "$OUT_PATH" "$SDK_VERSION" "$GIT_COMMIT_FULL"

SIZE_MB="$(du -m "$OUT_PATH" | awk '{print $1}')"
echo "[OK] $OUT_PATH (${SIZE_MB} MB) sdk=$SDK_VERSION git=$GIT_COMMIT_SHORT"
