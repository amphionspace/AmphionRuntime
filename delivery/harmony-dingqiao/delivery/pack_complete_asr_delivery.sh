#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
VERSION="${AMPHION_RUNTIME_VERSION:-0.3.9}"
SOURCE_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"
RELEASE_ZIP="${RELEASE_SDK_ZIP:-$REPO_ROOT/build/amphion-harmony-asr-sdk-v${VERSION}-20260824.zip}"
DIAGNOSTICS_ZIP="${DIAGNOSTICS_SDK_ZIP:-$REPO_ROOT/delivery/harmony-dingqiao/build/diagnostics-sdk-${VERSION}-${SOURCE_COMMIT:0:8}/Amphion-ASR-Diagnostics-SDK.zip}"
OUTPUT_ROOT="${1:-$REPO_ROOT/delivery/harmony-dingqiao/build/complete-sdk-${VERSION}-${SOURCE_COMMIT:0:8}}"
OUTPUT_ZIP="$OUTPUT_ROOT/Amphion-Harmony-ASR-Complete-${VERSION}.zip"
mkdir -p "$OUTPUT_ROOT"
STAGING_ROOT="$(mktemp -d "$OUTPUT_ROOT/.complete-delivery.XXXXXX")"
PACKAGE_ROOT="$STAGING_ROOT/Amphion-Harmony-ASR-Complete-${VERSION}"

cleanup() {
  rm -rf "$STAGING_ROOT"
}
trap cleanup EXIT

[[ -s "$RELEASE_ZIP" ]] || { echo "[ERROR] missing release SDK: $RELEASE_ZIP" >&2; exit 1; }
[[ -s "$DIAGNOSTICS_ZIP" ]] || { echo "[ERROR] missing diagnostics SDK: $DIAGNOSTICS_ZIP" >&2; exit 1; }
mkdir -p "$PACKAGE_ROOT/release-sdk" "$PACKAGE_ROOT/diagnostics-sdk" \
  "$PACKAGE_ROOT/diagnostics-demo" "$PACKAGE_ROOT/demo-source" "$PACKAGE_ROOT/docs"

cp "$RELEASE_ZIP" "$PACKAGE_ROOT/release-sdk/"
cp "$DIAGNOSTICS_ZIP" "$PACKAGE_ROOT/diagnostics-sdk/"
unzip -p "$DIAGNOSTICS_ZIP" \
  'Amphion-ASR-Diagnostics-SDK/demo/amphion_asr_demo-diagnostics-signed.hap' \
  > "$PACKAGE_ROOT/diagnostics-demo/amphion_asr_demo-diagnostics-signed.hap"
[[ -s "$PACKAGE_ROOT/diagnostics-demo/amphion_asr_demo-diagnostics-signed.hap" ]] || {
  echo "[ERROR] diagnostics SDK does not contain the signed diagnostics Demo" >&2
  exit 1
}

git -C "$REPO_ROOT" archive "$SOURCE_COMMIT" \
  delivery/harmony-dingqiao/AppScope \
  delivery/harmony-dingqiao/build-profile.json5 \
  delivery/harmony-dingqiao/hvigorfile.ts \
  delivery/harmony-dingqiao/hvigor \
  delivery/harmony-dingqiao/oh-package.json5 \
  delivery/harmony-dingqiao/samples/dingqiao-demo \
  | tar -x -C "$PACKAGE_ROOT/demo-source" --strip-components=2

cat > "$PACKAGE_ROOT/README.md" <<EOF
# Amphion HarmonyOS ASR ${VERSION} 完整交付

| 目录 | 内容 |
| --- | --- |
| \`release-sdk/\` | 正式 release SDK 及公开集成文档 |
| \`diagnostics-sdk/\` | Diagnostics SDK、采集工具和诊断文档 |
| \`diagnostics-demo/\` | 已签名的 Diagnostics Demo HAP |
| \`demo-source/\` | 与本交付 commit 一致的 Demo 源码，不包含商用授权和签名私密材料 |
| \`docs/\` | 交付身份与全包 SHA-256 清单 |

源码 commit：\`${SOURCE_COMMIT}\`
EOF

python3 "$SCRIPT_DIR/harmony_build_identity.py" \
  --verify "$REPO_ROOT/delivery/harmony-dingqiao/build/smoke/build-identity.json"
cp "$REPO_ROOT/delivery/harmony-dingqiao/build/smoke/build-identity.json" \
  "$PACKAGE_ROOT/docs/build-identity.json"
(
  cd "$PACKAGE_ROOT"
  find . -type f ! -path './docs/checksums.txt' -print0 | sort -z | \
    xargs -0 shasum -a 256 > docs/checksums.txt
  shasum -a 256 -c docs/checksums.txt >/dev/null
)

ZIP_TEMP="$(mktemp -d "$OUTPUT_ROOT/.complete-zip.XXXXXX")"
(
  cd "$STAGING_ROOT"
  /usr/bin/zip -X -q -r "$ZIP_TEMP/$(basename "$OUTPUT_ZIP")" "$(basename "$PACKAGE_ROOT")"
)
mv "$ZIP_TEMP/$(basename "$OUTPUT_ZIP")" "$OUTPUT_ZIP"
rmdir "$ZIP_TEMP"
shasum -a 256 "$OUTPUT_ZIP" > "$OUTPUT_ZIP.sha256"
echo "[OK] $OUTPUT_ZIP"
