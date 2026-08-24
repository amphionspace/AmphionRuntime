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
ACCEPTANCE_SUMMARY="${ACCEPTANCE_SUMMARY:-$REPO_ROOT/delivery/harmony-dingqiao/build/acceptance-${VERSION}/ACCEPTANCE-SUMMARY.md}"
mkdir -p "$OUTPUT_ROOT"
STAGING_ROOT="$(mktemp -d "$OUTPUT_ROOT/.complete-delivery.XXXXXX")"
PACKAGE_ROOT="$STAGING_ROOT/Amphion-Harmony-ASR-Complete-${VERSION}"

cleanup() {
  rm -rf "$STAGING_ROOT"
}
trap cleanup EXIT

[[ -s "$RELEASE_ZIP" ]] || { echo "[ERROR] missing release SDK: $RELEASE_ZIP" >&2; exit 1; }
[[ -s "$DIAGNOSTICS_ZIP" ]] || { echo "[ERROR] missing diagnostics SDK: $DIAGNOSTICS_ZIP" >&2; exit 1; }
[[ -s "$ACCEPTANCE_SUMMARY" ]] || { echo "[ERROR] missing acceptance summary: $ACCEPTANCE_SUMMARY" >&2; exit 1; }
python3 - "$RELEASE_ZIP" "$DIAGNOSTICS_ZIP" "$VERSION" "$SOURCE_COMMIT" <<'PY'
import hashlib
import json
import sys
import zipfile

release_zip, diagnostics_zip, version, commit = sys.argv[1:]
with zipfile.ZipFile(release_zip) as archive:
    provenance_name = next(
        (name for name in archive.namelist() if name.endswith("/docs/BUILD_PROVENANCE.json")),
        None,
    )
    if provenance_name is None:
        raise SystemExit("[ERROR] release SDK has no BUILD_PROVENANCE.json")
    provenance = json.loads(archive.read(provenance_name))
    if provenance.get("delivery_version") != version:
        raise SystemExit("[ERROR] release SDK version does not match complete delivery")
    if provenance.get("source", {}).get("commit") != commit:
        raise SystemExit("[ERROR] release SDK commit does not match complete delivery")
    if provenance.get("verified_source_identity", {}).get("git_commit") != commit:
        raise SystemExit("[ERROR] release SDK source identity does not match complete delivery")

with zipfile.ZipFile(diagnostics_zip) as archive:
    root = "Amphion-ASR-Diagnostics-SDK/"
    identity = json.loads(archive.read(root + "tools/build-identity.json"))
    if identity.get("git_commit") != commit:
        raise SystemExit("[ERROR] diagnostics SDK commit does not match complete delivery")
    packaged = {
        "amphion_asr.har": "sdk/amphion_asr-diagnostics.har",
        "amphion_police.har": "sdk/amphion_police-diagnostics.har",
        "amphion_dingqiao.har": "sdk/amphion_dingqiao-diagnostics.har",
        "sherpa_onnx.har": "sdk/sherpa_onnx.har",
        "amphion_asr_demo.hap": "demo/amphion_asr_demo-diagnostics-signed.hap",
    }
    for logical_name, relative in packaged.items():
        expected = identity.get("artifacts", {}).get(logical_name, {}).get("sha256")
        actual = hashlib.sha256(archive.read(root + relative)).hexdigest()
        if expected != actual:
            raise SystemExit(f"[ERROR] diagnostics identity mismatch: {relative}")
PY
mkdir -p "$PACKAGE_ROOT/release-sdk" "$PACKAGE_ROOT/diagnostics-sdk" \
  "$PACKAGE_ROOT/diagnostics-demo" "$PACKAGE_ROOT/demo-source/libs" "$PACKAGE_ROOT/docs"

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
  delivery/harmony-dingqiao/oh-package.json5 \
  delivery/harmony-dingqiao/samples/dingqiao-demo \
  | tar -x -C "$PACKAGE_ROOT/demo-source" --strip-components=2
mkdir -p "$PACKAGE_ROOT/demo-source/hvigor"
cat > "$PACKAGE_ROOT/demo-source/hvigor/hvigor-config.json5" <<'EOF'
{
  "modelVersion": "5.0.0",
  "dependencies": {},
  "execution": {},
  "logging": {},
  "debugging": {},
  "nodeOptions": {}
}
EOF
python3 - "$PACKAGE_ROOT/demo-source/build-profile.json5" \
  "$PACKAGE_ROOT/demo-source/samples/dingqiao-demo/entry/oh-package.json5" <<'PY'
import json
import sys
from pathlib import Path

build_profile, module_package = map(Path, sys.argv[1:])
profile = json.loads(build_profile.read_text(encoding="utf-8"))
profile["modules"] = [
    module for module in profile["modules"] if module["name"] == "amphion_asr_demo"
]
build_profile.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")

package = json.loads(module_package.read_text(encoding="utf-8"))
package["dependencies"] = {
    "amphion_dingqiao": "file:../../../libs/amphion_dingqiao.har"
}
module_package.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
PY
unzip -p "$RELEASE_ZIP" '*/har/amphion_dingqiao.har' \
  > "$PACKAGE_ROOT/demo-source/libs/amphion_dingqiao.har"
[[ -s "$PACKAGE_ROOT/demo-source/libs/amphion_dingqiao.har" ]] || {
  echo "[ERROR] release SDK does not contain amphion_dingqiao.har" >&2
  exit 1
}

cat > "$PACKAGE_ROOT/README.md" <<EOF
# Amphion HarmonyOS ASR ${VERSION} 完整交付

| 目录 | 内容 |
| --- | --- |
| \`release-sdk/\` | 正式 release SDK 及公开集成文档 |
| \`diagnostics-sdk/\` | Diagnostics SDK、采集工具和诊断文档 |
| \`diagnostics-demo/\` | 已签名的 Diagnostics Demo HAP |
| \`demo-source/\` | 与本交付 commit 一致的 Demo 源码，不包含商用授权和签名私密材料 |
| \`docs/\` | 真机验收摘要、交付身份与全包 SHA-256 清单 |

源码 commit：\`${SOURCE_COMMIT}\`
EOF

cp "$ACCEPTANCE_SUMMARY" "$PACKAGE_ROOT/docs/ACCEPTANCE-SUMMARY.md"
unzip -p "$DIAGNOSTICS_ZIP" \
  'Amphion-ASR-Diagnostics-SDK/tools/build-identity.json' \
  > "$PACKAGE_ROOT/docs/build-identity.json"
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
