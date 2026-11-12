#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PROJECT_ROOT="$REPO_ROOT/delivery/harmony-dingqiao"
source "$REPO_ROOT/asr/tools/harmony_env.sh"
OUTPUT_ROOT="${1:-$PROJECT_ROOT/build/diagnostics-sdk}"
if [[ "$OUTPUT_ROOT" != /* ]]; then
  OUTPUT_ROOT="$PWD/$OUTPUT_ROOT"
fi
mkdir -p "$OUTPUT_ROOT"
STAGING_ROOT="$(mktemp -d "$OUTPUT_ROOT/.diagnostics-sdk-package.XXXXXX")"
PACKAGE_ROOT="$STAGING_ROOT/Amphion-ASR-Diagnostics-SDK"

# hvigor 不解析模块路径里的符号链接；这里把 build-profile.json5 的 sherpa 模块指向
# 解析后的实体目录，构建结束再还原，避免为了原地构建去复制整棵派生树。
PROFILE="$PROJECT_ROOT/build-profile.json5"
PROFILE_BACKUP="$STAGING_ROOT/build-profile.json5.bak"
PROFILE_REWRITTEN=false
CMAKE_REWRITTEN=false
cleanup() {
  if [[ "$CMAKE_REWRITTEN" == true && -n "${CMAKE_BACKUP:-}" && -f "$CMAKE_BACKUP" ]]; then
    cp "$CMAKE_BACKUP" "$CMAKE_FILE"
  fi
  if [[ "$PROFILE_REWRITTEN" == true && -f "$PROFILE_BACKUP" ]]; then
    cp "$PROFILE_BACKUP" "$PROFILE"
  fi
  rm -rf "$STAGING_ROOT"
}
trap cleanup EXIT

cd "$PROJECT_ROOT"

if [[ "${SKIP_BUILD:-false}" != "true" ]]; then
  cp "$PROFILE" "$PROFILE_BACKUP"
  python3 - "$PROFILE" "$REPO_ROOT/third_party/.derived" <<'PY'
import re
import sys
from pathlib import Path

profile = Path(sys.argv[1])
derived = Path(sys.argv[2]).resolve()
text = profile.read_text(encoding="utf-8")
match = re.search(r'"srcPath":\s*"([^"]*SherpaOnnxHar/sherpa_onnx)"', text)
if not match:
    raise SystemExit("[ERROR] sherpa_onnx module entry not found in build-profile.json5")
concrete = (derived / "sherpa-onnx/harmony-os/SherpaOnnxHar/sherpa_onnx").resolve()
if not concrete.is_dir():
    raise SystemExit(f"[ERROR] resolved sherpa module path missing: {concrete}")
profile.write_text(text.replace(match.group(1), str(concrete), 1), encoding="utf-8")
print(f"[OK] sherpa module resolved to {concrete}")
PY
  PROFILE_REWRITTEN=true
  # sherpa HAR 的 CMake 会 FetchContent 拉 node-addon-api；离线构建时指向本地已缓存源码，
  # 同样在清理阶段还原。
  CMAKE_FILE="$(python3 - "$PROFILE" <<'PY'
import re
import sys
from pathlib import Path
text = Path(sys.argv[1]).read_text(encoding="utf-8")
match = re.search(r'"srcPath":\s*"([^"]*SherpaOnnxHar/sherpa_onnx)"', text)
if not match:
    raise SystemExit(1)
print(Path(match.group(1)) / "src/main/cpp/CMakeLists.txt")
PY
)"
  NODE_ADDON_SRC="${NODE_ADDON_API_PREPATCHED:-$REPO_ROOT/.cache/speaker-screen-repro-acf477c2/napi-configure-probe/_deps/node_addon_api-src}"
  if [[ -f "$CMAKE_FILE" && -d "$NODE_ADDON_SRC" ]]; then
    CMAKE_BACKUP="$STAGING_ROOT/CMakeLists.txt.bak"
    cp "$CMAKE_FILE" "$CMAKE_BACKUP"
    python3 - "$CMAKE_FILE" "$NODE_ADDON_SRC" <<'PY'
import sys
from pathlib import Path
cmake = Path(sys.argv[1])
source = Path(sys.argv[2]).resolve()
text = cmake.read_text(encoding="utf-8")
anchor = "include(FetchContent)"
if anchor not in text:
    raise SystemExit("[ERROR] FetchContent anchor missing")
override = f'set(FETCHCONTENT_SOURCE_DIR_NODE_ADDON_API "{source}" CACHE PATH "" FORCE)\n'
cmake.write_text(text.replace(anchor, override + anchor, 1), encoding="utf-8")
print(f"[OK] node-addon-api bound to local source {source}")
PY
    CMAKE_REWRITTEN=true
  fi
fi

if [[ "${SKIP_BUILD:-false}" != "true" ]]; then
  for module in sherpa_onnx amphion_asr amphion_police amphion_dingqiao; do
    "$NODE" "$HVIGOR" assembleHar --mode module \
      -p product=default -p module="${module}@default" -p buildMode=diagnostics \
      --no-daemon --stacktrace
  done

  if [[ "${INCLUDE_SIGNED_DEMO:-false}" == "true" ]]; then
    "$NODE" "$HVIGOR" assembleHap --mode module \
      -p product=default -p module=amphion_asr_demo@default -p buildMode=diagnostics \
      --no-daemon --stacktrace
  fi
fi

BUILD_IDENTITY="$OUTPUT_ROOT/build-identity.json"
if [[ "${SKIP_BUILD:-false}" == "true" ]]; then
  VERIFIED_BUILD_IDENTITY="${BUILD_IDENTITY_PATH:-$PROJECT_ROOT/build/smoke/build-identity.json}"
  python3 "$SCRIPT_DIR/harmony_build_identity.py" --verify "$VERIFIED_BUILD_IDENTITY" \
    --build-mode diagnostics
  cp "$VERIFIED_BUILD_IDENTITY" "$BUILD_IDENTITY"
else
  python3 "$SCRIPT_DIR/harmony_build_identity.py" --write "$BUILD_IDENTITY" \
    --build-mode diagnostics
fi

mkdir -p "$PACKAGE_ROOT/sdk" "$PACKAGE_ROOT/demo" "$PACKAGE_ROOT/tools" "$PACKAGE_ROOT/docs"
cp "$REPO_ROOT/asr/harmony/sdk/build/default/outputs/default/amphion_asr.har" \
  "$PACKAGE_ROOT/sdk/amphion_asr-diagnostics.har"
cp "$REPO_ROOT/asr/harmony/sdk-police/build/default/outputs/default/amphion_police.har" \
  "$PACKAGE_ROOT/sdk/amphion_police-diagnostics.har"
cp "$REPO_ROOT/asr/harmony/sdk-dingqiao/build/default/outputs/default/amphion_dingqiao.har" \
  "$PACKAGE_ROOT/sdk/amphion_dingqiao-diagnostics.har"
SHERPA_ROOT="$(bash "$REPO_ROOT/asr/tools/prepare_sherpa_source.sh")"
cp "$SHERPA_ROOT/harmony-os/SherpaOnnxHar/sherpa_onnx/build/default/outputs/default/sherpa_onnx.har" \
  "$PACKAGE_ROOT/sdk/sherpa_onnx.har"
cp "$SCRIPT_DIR/collect_asr_diagnostics.py" "$PACKAGE_ROOT/tools/"
cp "$BUILD_IDENTITY" "$PACKAGE_ROOT/tools/build-identity.json"
cp "$PROJECT_ROOT/docs/diagnostics-sdk/DIAGNOSTICS_GUIDE.md" "$PACKAGE_ROOT/docs/"
cp "$PROJECT_ROOT/docs/diagnostics-sdk/ISSUE_TEMPLATE.md" "$PACKAGE_ROOT/docs/"
cp "$PROJECT_ROOT/docs/diagnostics-sdk/PRIVACY_NOTICE.md" "$PACKAGE_ROOT/docs/"

SIGNED_HAP="$PROJECT_ROOT/samples/dingqiao-demo/entry/build/default/outputs/default/amphion_asr_demo-default-signed.hap"
if [[ "${INCLUDE_SIGNED_DEMO:-false}" == "true" && ! -f "$SIGNED_HAP" ]]; then
  echo "[ERROR] requested signed diagnostics Demo is missing: $SIGNED_HAP" >&2
  exit 1
fi
if [[ "${INCLUDE_SIGNED_DEMO:-false}" == "true" ]]; then
  cp "$SIGNED_HAP" "$PACKAGE_ROOT/demo/amphion_asr_demo-diagnostics-signed.hap"
fi

(
  cd "$PACKAGE_ROOT"
  find sdk demo tools docs -type f -print0 | sort -z | xargs -0 shasum -a 256 > checksums.txt
)
(
  cd "$STAGING_ROOT"
  ZIP_TEMP_DIR="$(mktemp -d "$OUTPUT_ROOT/.diagnostics-sdk-zip.XXXXXX")"
  /usr/bin/zip -X -q -r "$ZIP_TEMP_DIR/Amphion-ASR-Diagnostics-SDK.zip" Amphion-ASR-Diagnostics-SDK
  mv "$ZIP_TEMP_DIR/Amphion-ASR-Diagnostics-SDK.zip" "$OUTPUT_ROOT/Amphion-ASR-Diagnostics-SDK.zip"
  rmdir "$ZIP_TEMP_DIR"
  cd "$OUTPUT_ROOT"
  shasum -a 256 Amphion-ASR-Diagnostics-SDK.zip > Amphion-ASR-Diagnostics-SDK.zip.sha256
)
echo "[OK] $OUTPUT_ROOT/Amphion-ASR-Diagnostics-SDK.zip"
