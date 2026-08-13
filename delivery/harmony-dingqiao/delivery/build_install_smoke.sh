#!/usr/bin/env bash
# Build, verify, install, launch, and wait for the Harmony demo engine to become ready.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PROJECT_ROOT="$REPO_ROOT/delivery/harmony-dingqiao"
DEVECO_HOME="${DEVECO_STUDIO_HOME:-/Applications/DevEco-Studio.app/Contents}"
NODE="$DEVECO_HOME/tools/node/bin/node"
HVIGOR="$DEVECO_HOME/tools/hvigor/bin/hvigorw.js"
OHPM="$DEVECO_HOME/tools/ohpm/bin/ohpm"
HDC="$DEVECO_HOME/sdk/default/openharmony/toolchains/hdc"
JAVA_HOME_VALUE="${JAVA_HOME:-$DEVECO_HOME/jbr/Contents/Home}"
HAP="$PROJECT_ROOT/samples/dingqiao-demo/entry/build/default/outputs/default/amphion_asr_demo-default-signed.hap"
BUILD_IDENTITY="$PROJECT_ROOT/build/smoke/build-identity.json"
LICENSE_FILE="$PROJECT_ROOT/samples/dingqiao-demo/entry/src/main/resources/rawfile/amphion-license.lic"
DEVICE_ID_FILE="${DINGQIAO_DEVICE_ID_FILE:-$REPO_ROOT/.secure/amphion_asr_demo_device_ids.txt}"
PRIVATE_KEY="${AMPHION_LICENSE_PRIVATE_KEY:-$REPO_ROOT/.secure/amphion-license-private.pem}"
BUNDLE="com.amphion.asr.harmony.demo"
MODULE="amphion_asr_demo"
ABILITY="EntryAbility"
DEVICE=""
TIMEOUT_SECONDS=30
SKIP_BUILD=false
PREPARE_ONLY=false
ZH_EN_ONLY=true
SMOKE_DIR="$PROJECT_ROOT/build/smoke"
SIGNING_CONFIG="${HARMONY_SIGNING_CONFIG:-}"
LICENSE_VENV="$REPO_ROOT/tools/license/.venv"
LICENSE_PYTHON="${LICENSE_PYTHON:-python3}"
NODE_ADDON_API_CACHE="${NODE_ADDON_API_CACHE:-$REPO_ROOT/third_party/sherpa-onnx/harmony-os/SherpaOnnxHar/sherpa_onnx/.cxx/default/default/debug/arm64-v8a/_deps/node_addon_api-src}"
TARGET_SPEAKER_SEPARATOR_MODEL="${TARGET_SPEAKER_SEPARATOR_MODEL:-}"
SPEAKER_TURN_SEGMENTATION_MODEL="${SPEAKER_TURN_SEGMENTATION_MODEL:-}"
BUILD_WORKSPACE=""
TEMP_HAP_COPY=""

usage() {
  cat <<'EOF'
Usage: build_install_smoke.sh [options]

Options:
  --device SERIAL   HDC target. Auto-detected when exactly one device is connected.
  --timeout SEC     Engine-ready timeout; default 30 seconds.
  --skip-build      Reuse the existing signed HAP.
  --prepare-only    Prepare and discard an isolated source tree; do not require device/signing.
  --zh-en-only      Verify and build the current USB carrier without unrelated Yue-English assets.
  --signing-config  Local signing material JSON; defaults to .secure/harmony-signing.json.
  -h, --help        Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --device) DEVICE="$2"; shift 2 ;;
    --timeout) TIMEOUT_SECONDS="$2"; shift 2 ;;
    --skip-build) SKIP_BUILD=true; shift ;;
    --prepare-only) PREPARE_ONLY=true; shift ;;
    --zh-en-only) ZH_EN_ONLY=true; shift ;;
    --signing-config) SIGNING_CONFIG="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[ERROR] unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$PREPARE_ONLY" != true ]]; then
  for tool in "$NODE" "$HVIGOR" "$OHPM" "$HDC"; do
    [[ -x "$tool" || -f "$tool" ]] || { echo "[ERROR] missing DevEco tool: $tool" >&2; exit 1; }
  done
fi
[[ "$TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]] || { echo "[ERROR] --timeout must be a positive integer" >&2; exit 2; }

if [[ "$PREPARE_ONLY" != true && -z "$DEVICE" ]]; then
  TARGETS="$($HDC list targets | tr -d '\r' | awk 'NF && $0 != "[Empty]"')"
  TARGET_COUNT="$(printf '%s\n' "$TARGETS" | awk 'NF {count++} END {print count+0}')"
  [[ "$TARGET_COUNT" -eq 1 ]] || {
    echo "[ERROR] expected exactly one HDC target; found $TARGET_COUNT. Pass --device SERIAL." >&2
    exit 1
  }
  DEVICE="$TARGETS"
fi

mkdir -p "$SMOKE_DIR"
BUILD_LOG="$SMOKE_DIR/build.log"
INSTALL_LOG="$SMOKE_DIR/install.log"
HILOG_FILE="$SMOKE_DIR/hilog.txt"
LOCAL_LAYOUT="$SMOKE_DIR/layout.json"
REMOTE_LAYOUT="/data/local/tmp/amphion-smoke-layout.json"
LOCAL_GLOBAL_LAYOUT="$SMOKE_DIR/global-layout.json"
REMOTE_GLOBAL_LAYOUT="/data/local/tmp/amphion-smoke-global-layout.json"
LOCAL_SCREENSHOT="$SMOKE_DIR/screen.jpeg"
REMOTE_SCREENSHOT="/data/local/tmp/amphion-smoke-screen.jpeg"

cleanup() {
  [[ -z "$BUILD_WORKSPACE" ]] || rm -rf "$BUILD_WORKSPACE"
  [[ -z "$TEMP_HAP_COPY" ]] || rm -f "$TEMP_HAP_COPY"
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT TERM

ensure_demo_license() {
  if [[ -s "$LICENSE_FILE" ]]; then
    return
  fi
  [[ -s "$PRIVATE_KEY" && -s "$DEVICE_ID_FILE" ]] || {
    echo "[ERROR] demo license is missing and cannot be issued from local secure inputs" >&2
    echo "        expected private key: $PRIVATE_KEY" >&2
    echo "        expected device list: $DEVICE_ID_FILE" >&2
    exit 1
  }
  echo "[INFO] issuing the missing local demo license"
  AMPHION_LICENSE_PRIVATE_KEY="$PRIVATE_KEY" \
    DINGQIAO_DEVICE_ID_FILE="$DEVICE_ID_FILE" \
    DINGQIAO_LICENSE_FEATURES=ASR,TTS \
    "$REPO_ROOT/asr/tools/license/issue_dingqiao_customer.sh" "$LICENSE_FILE"
}

clone_tree() {
  local src="$1"
  local dst="$2"
  mkdir -p "$(dirname "$dst")"
  if ! cp -cR "$src" "$dst" 2>/dev/null; then
    rm -rf "$dst"
    cp -R "$src" "$dst"
  fi
}

publish_har() {
  local source_dir="$1"
  local destination_dir="$2"
  local source_har=""
  local candidate
  for candidate in "$source_dir"/*.har; do
    [[ -f "$candidate" ]] || continue
    [[ -z "$source_har" ]] || {
      echo "[ERROR] expected one HAR in $source_dir" >&2
      return 1
    }
    source_har="$candidate"
  done
  [[ -n "$source_har" ]] || {
    echo "[ERROR] missing built HAR in $source_dir" >&2
    return 1
  }
  tar tzf "$source_har" >/dev/null || {
    echo "[ERROR] invalid built HAR archive: $source_har" >&2
    return 1
  }

  mkdir -p "$destination_dir"
  local destination_har="$destination_dir/$(basename "$source_har")"
  local temp_har="${destination_har}.tmp.$$"
  if ! cp "$source_har" "$temp_har"; then
    rm -f "$temp_har"
    return 1
  fi
  mv -f "$temp_har" "$destination_har"
  for candidate in "$destination_dir"/*.har; do
    [[ "$candidate" == "$destination_har" ]] || rm -f "$candidate"
  done
}

resolve_built_hap() {
  [[ -f "$BUILD_HAP" ]] && return

  local output_dir
  local candidate
  local resolved=""
  output_dir="$(dirname "$BUILD_HAP")"
  for candidate in "$output_dir"/*-signed.hap; do
    [[ -f "$candidate" ]] || continue
    [[ -z "$resolved" ]] || {
      echo "[ERROR] expected one signed HAP in $output_dir" >&2
      return 1
    }
    resolved="$candidate"
  done
  [[ -n "$resolved" ]] || {
    echo "[ERROR] missing signed HAP in $output_dir" >&2
    return 1
  }
  BUILD_HAP="$resolved"
  echo "[INFO] resolved Hvigor HAP output: $(basename "$BUILD_HAP")"
}

prepare_build_workspace() {
  command -v rsync >/dev/null || { echo "[ERROR] rsync is required" >&2; exit 1; }
  BUILD_WORKSPACE="$(mktemp -d "${TMPDIR:-/tmp}/amphion-harmony-build.XXXXXX")"
  local temp_repo="$BUILD_WORKSPACE/repo"
  local sherpa_source="$REPO_ROOT/third_party/sherpa-onnx"
  local sherpa_destination="$temp_repo/third_party/sherpa-onnx"
  local sherpa_commit
  sherpa_commit="$(git -C "$REPO_ROOT" ls-tree HEAD -- third_party/sherpa-onnx | awk '{print $3}')"
  [[ -n "$sherpa_commit" ]] || {
    echo "[ERROR] unable to resolve the pinned sherpa-onnx submodule commit" >&2
    exit 1
  }
  mkdir -p "$(dirname "$sherpa_destination")"
  git clone --quiet --no-hardlinks "$sherpa_source" "$sherpa_destination"
  git -C "$sherpa_destination" checkout --quiet --detach "$sherpa_commit"
  rsync -a \
    "$sherpa_source/harmony-os/SherpaOnnxHar/sherpa_onnx/src/main/cpp/libs/" \
    "$sherpa_destination/harmony-os/SherpaOnnxHar/sherpa_onnx/src/main/cpp/libs/"
  AMPHION_SHERPA_ROOT="$sherpa_destination" \
    bash "$REPO_ROOT/asr/tools/apply_sherpa_patches.sh"
  mkdir -p "$temp_repo/delivery"
  rsync -a \
    --exclude='build/' \
    --exclude='.hvigor/' \
    --exclude='.idea/' \
    "$PROJECT_ROOT/" "$temp_repo/delivery/harmony-dingqiao/"
  clone_tree "$REPO_ROOT/asr/harmony/sdk" "$temp_repo/asr/harmony/sdk"
  clone_tree "$REPO_ROOT/asr/harmony/sdk-police" "$temp_repo/asr/harmony/sdk-police"
  clone_tree "$REPO_ROOT/asr/harmony/sdk-dingqiao" "$temp_repo/asr/harmony/sdk-dingqiao"
  clone_tree \
    "$REPO_ROOT/asr/native/audio-processing/include" \
    "$temp_repo/asr/native/audio-processing/include"
  clone_tree \
    "$REPO_ROOT/tts/harmony/sdk/src/main/cpp/third_party/onnxruntime/include" \
    "$temp_repo/tts/harmony/sdk/src/main/cpp/third_party/onnxruntime/include"
  # DevEco generates this file locally and the repository intentionally ignores
  # every hvigor/ directory. Recreate the minimal project config so the release
  # gate proves a clean checkout instead of depending on workstation state.
  mkdir -p "$temp_repo/delivery/harmony-dingqiao/hvigor"
  cat >"$temp_repo/delivery/harmony-dingqiao/hvigor/hvigor-config.json5" <<'EOF'
{
  "modelVersion": "5.0.0",
  "dependencies": {},
  "execution": {},
  "logging": {},
  "debugging": {},
  "nodeOptions": {}
}
EOF
  find "$temp_repo/asr/harmony" \
    "$temp_repo/third_party/sherpa-onnx" \
    -type d \( -name build -o -name .cxx -o -name .hvigor \) -prune -exec rm -rf {} +
  if [[ -n "$TARGET_SPEAKER_SEPARATOR_MODEL" ]]; then
    [[ -s "$TARGET_SPEAKER_SEPARATOR_MODEL" ]] || {
      echo "[ERROR] target-speaker separator model is unreadable: $TARGET_SPEAKER_SEPARATOR_MODEL" >&2
      exit 1
    }
    local separator_destination="$temp_repo/asr/harmony/sdk-dingqiao/src/main/resources/rawfile/amphion-dingqiao/convtasnet_16k.onnx"
    mkdir -p "$(dirname "$separator_destination")"
    cp "$TARGET_SPEAKER_SEPARATOR_MODEL" "$separator_destination"
    echo "[INFO] injected target-speaker separator into the isolated test build"
  fi
  if [[ -n "$SPEAKER_TURN_SEGMENTATION_MODEL" ]]; then
    [[ -s "$SPEAKER_TURN_SEGMENTATION_MODEL" ]] || {
      echo "[ERROR] speaker-turn segmentation model is unreadable: $SPEAKER_TURN_SEGMENTATION_MODEL" >&2
      exit 1
    }
    local turn_destination="$temp_repo/asr/harmony/sdk-dingqiao/src/main/resources/rawfile/amphion-dingqiao/pyannote-segmentation-3.0.onnx"
    mkdir -p "$(dirname "$turn_destination")"
    cp "$SPEAKER_TURN_SEGMENTATION_MODEL" "$turn_destination"
    echo "[INFO] injected speaker-turn segmentation model into the isolated test build"
  fi
  if [[ -d "$NODE_ADDON_API_CACHE/.git" ]] && \
      [[ "$(git -C "$NODE_ADDON_API_CACHE" rev-parse HEAD 2>/dev/null)" == "c679f6f4c9dc6bf9fc0d99cbe5982bd24a5e2c7b" ]]; then
    "$LICENSE_PYTHON" - \
      "$temp_repo/third_party/sherpa-onnx/harmony-os/SherpaOnnxHar/sherpa_onnx/src/main/cpp/CMakeLists.txt" \
      "$NODE_ADDON_API_CACHE" <<'PY'
import sys
from pathlib import Path

cmake_path = Path(sys.argv[1])
cache_url = Path(sys.argv[2]).resolve().as_uri()
text = cmake_path.read_text(encoding="utf-8")
upstream = "https://github.com/nodejs/node-addon-api.git"
if upstream not in text:
    raise SystemExit("[ERROR] node-addon-api FetchContent declaration changed")
cmake_path.write_text(text.replace(upstream, cache_url, 1), encoding="utf-8")
PY
    echo "[INFO] using the verified local node-addon-api Git cache"
  fi
  BUILD_PROJECT_ROOT="$temp_repo/delivery/harmony-dingqiao"
  BUILD_PROFILE="$BUILD_PROJECT_ROOT/build-profile.json5"
  BUILD_HAP="$BUILD_PROJECT_ROOT/samples/dingqiao-demo/entry/build/default/outputs/default/amphion_asr_demo-default-signed.hap"
}

apply_local_signing() {
  local config="$1"
  local mode
  [[ -s "$config" ]] || { echo "[ERROR] missing local signing config: $config" >&2; exit 1; }
  if [[ "$(uname)" == "Darwin" ]]; then
    mode="$(stat -f '%Lp' "$config")"
  else
    mode="$(stat -c '%a' "$config")"
  fi
  [[ "$mode" == "600" || "$mode" == "400" ]] || {
    echo "[ERROR] signing config must not be group/world readable: chmod 600 $config" >&2
    exit 1
  }

  "$LICENSE_PYTHON" - "$BUILD_PROFILE" "$config" <<'PY'
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from cryptography import x509

profile_path = Path(sys.argv[1])
material_path = Path(sys.argv[2])
profile = json.loads(profile_path.read_text(encoding="utf-8"))
material = json.loads(material_path.read_text(encoding="utf-8"))
required = {"certpath", "keyAlias", "keyPassword", "profile", "signAlg", "storeFile", "storePassword"}
missing = sorted(required - set(material))
if missing:
    raise SystemExit(f"[ERROR] signing config missing keys: {missing}")
for key in ("certpath", "profile", "storeFile"):
    if not Path(material[key]).is_file():
        raise SystemExit(f"[ERROR] signing material path does not exist: {key}")

cert_bytes = Path(material["certpath"]).read_bytes()
blocks = re.findall(b"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", cert_bytes, re.S)
if not blocks:
    raise SystemExit("[ERROR] signing certificate chain is not PEM")
now = datetime.now(timezone.utc)
for block in blocks:
    certificate = x509.load_pem_x509_certificate(block)
    if certificate.not_valid_after_utc <= now:
        raise SystemExit("[ERROR] signing certificate chain contains an expired certificate")

profile["app"]["signingConfigs"] = [{"name": "default", "type": "HarmonyOS", "material": material}]
for product in profile["app"].get("products", []):
    product["signingConfig"] = "default"
profile_path.write_text(json.dumps(profile, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print("[OK] local signing configuration validated in the isolated build workspace")
PY
}

capture_hilog() {
  "$HDC" -t "$DEVICE" shell hilog -x >"$HILOG_FILE" 2>/dev/null || true
}

capture_screen() {
  "$HDC" -t "$DEVICE" shell snapshot_display -f "$REMOTE_SCREENSHOT" >/dev/null 2>&1 || return
  "$HDC" -t "$DEVICE" file recv "$REMOTE_SCREENSHOT" "$LOCAL_SCREENSHOT" >/dev/null 2>&1 || true
}

fail_with_logs() {
  local message="$1"
  capture_hilog
  capture_screen
  echo "[ERROR] $message" >&2
  grep -Ei 'Amphion|Dingqiao|LastFatalMessage|SIGABRT|cppcrash|exception' "$HILOG_FILE" | tail -80 >&2 || true
  echo "[INFO] smoke artifacts: $SMOKE_DIR" >&2
  exit 1
}

dismiss_usb_mode_dialog() {
  rm -f "$LOCAL_GLOBAL_LAYOUT"
  if ! "$HDC" -t "$DEVICE" shell uitest dumpLayout -p "$REMOTE_GLOBAL_LAYOUT" >/dev/null 2>&1; then
    return
  fi
  if ! "$HDC" -t "$DEVICE" file recv "$REMOTE_GLOBAL_LAYOUT" "$LOCAL_GLOBAL_LAYOUT" >/dev/null 2>&1; then
    return
  fi
  if "$LICENSE_PYTHON" - "$LOCAL_GLOBAL_LAYOUT" <<'PY'
import json
import sys
from pathlib import Path

try:
    root = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    raise SystemExit(1)

def contains_usb_dialog(value):
    if isinstance(value, dict):
        attributes = value.get("attributes")
        if isinstance(attributes, dict) and attributes.get("text") == "USB 连接方式":
            return True
        return any(contains_usb_dialog(child) for child in value.values())
    if isinstance(value, list):
        return any(contains_usb_dialog(child) for child in value)
    return False

raise SystemExit(0 if contains_usb_dialog(root) else 1)
PY
  then
    echo "[INFO] dismissing the system USB mode dialog"
    "$HDC" -t "$DEVICE" shell uitest uiInput keyEvent Back >/dev/null 2>&1 || true
    sleep 1
  fi
}

if [[ "$PREPARE_ONLY" == true ]]; then
  prepare_build_workspace
  echo "[DONE] isolated Harmony source preparation passed"
  exit 0
fi

source "$REPO_ROOT/asr/tools/license/ensure_python.sh"
ensure_license_python "$LICENSE_VENV" "$REPO_ROOT/tools/license/requirements.txt"
LICENSE_PYTHON="$LICENSE_VENV/bin/python"

ensure_demo_license
VERIFY_SCOPE_ARGS=(--zh-en-only)
"$SCRIPT_DIR/verify_demo_inputs.sh" "${VERIFY_SCOPE_ARGS[@]}"

if [[ -z "$SIGNING_CONFIG" && -f "$REPO_ROOT/.secure/harmony-signing.json" ]]; then
  SIGNING_CONFIG="$REPO_ROOT/.secure/harmony-signing.json"
fi

if [[ "$SKIP_BUILD" != true ]]; then
  [[ -n "$SIGNING_CONFIG" ]] || {
    echo "[ERROR] signed build requires --signing-config or HARMONY_SIGNING_CONFIG" >&2
    echo "        template: $SCRIPT_DIR/harmony-signing.example.json" >&2
    exit 1
  }
  prepare_build_workspace
  apply_local_signing "$SIGNING_CONFIG"
  echo "[INFO] building signed Harmony demo HAP in an isolated workspace"
  if ! (
    set -e
    export PATH="$DEVECO_HOME/tools/node/bin:$PATH"
    export DEVECO_SDK_HOME="$DEVECO_HOME/sdk"
    export JAVA_HOME="$JAVA_HOME_VALUE"
    cd "$BUILD_PROJECT_ROOT"
    # The isolated workspace intentionally excludes ignored oh_modules. Recreate file dependencies
    # before Hvigor so a clean checkout cannot accidentally rely on packages from a developer tree.
    if ! "$OHPM" install --all; then
      exit 1
    fi
    if ! "$NODE" "$HVIGOR" assembleHap --mode module \
      -p product=default \
      -p module=amphion_asr_demo@default \
      -p buildMode=debug \
      --no-daemon --stacktrace; then
      exit 1
    fi
    for har_module in sherpa_onnx amphion_asr amphion_police amphion_dingqiao; do
      if ! "$NODE" "$HVIGOR" assembleHar --mode module \
        -p product=default \
        -p module="${har_module}@default" \
        -p buildMode=debug \
        --no-daemon --stacktrace; then
        exit 1
      fi
    done
  ) >"$BUILD_LOG" 2>&1; then
    tail -120 "$BUILD_LOG" >&2
    exit 1
  fi
  resolve_built_hap
  "$SCRIPT_DIR/verify_demo_inputs.sh" \
    "${VERIFY_SCOPE_ARGS[@]}" \
    --hap "$BUILD_HAP" \
    --signing-config "$SIGNING_CONFIG"
  publish_har \
    "$BUILD_WORKSPACE/repo/asr/harmony/sdk/build/default/outputs/default" \
    "$REPO_ROOT/asr/harmony/sdk/build/default/outputs/default"
  publish_har \
    "$BUILD_WORKSPACE/repo/asr/harmony/sdk-police/build/default/outputs/default" \
    "$REPO_ROOT/asr/harmony/sdk-police/build/default/outputs/default"
  publish_har \
    "$BUILD_WORKSPACE/repo/asr/harmony/sdk-dingqiao/build/default/outputs/default" \
    "$REPO_ROOT/asr/harmony/sdk-dingqiao/build/default/outputs/default"
  publish_har \
    "$BUILD_WORKSPACE/repo/third_party/sherpa-onnx/harmony-os/SherpaOnnxHar/sherpa_onnx/build/default/outputs/default" \
    "$REPO_ROOT/third_party/sherpa-onnx/harmony-os/SherpaOnnxHar/sherpa_onnx/build/default/outputs/default"
  mkdir -p "$(dirname "$HAP")"
  TEMP_HAP_COPY="${HAP}.tmp.$$"
  cp "$BUILD_HAP" "$TEMP_HAP_COPY"
  mv -f "$TEMP_HAP_COPY" "$HAP"
  TEMP_HAP_COPY=""
  IDENTITY_ARGS=(--write "$BUILD_IDENTITY")
  if [[ "$ZH_EN_ONLY" == true ]]; then
    IDENTITY_ARGS+=(--zh-en-only)
  fi
  python3 "$SCRIPT_DIR/harmony_build_identity.py" "${IDENTITY_ARGS[@]}"
  echo "[OK] HAP build succeeded"
fi

VERIFY_ARGS=(--hap "$HAP")
VERIFY_ARGS+=("${VERIFY_SCOPE_ARGS[@]}")
if [[ -n "$SIGNING_CONFIG" ]]; then
  VERIFY_ARGS+=(--signing-config "$SIGNING_CONFIG")
fi
"$SCRIPT_DIR/verify_demo_inputs.sh" "${VERIFY_ARGS[@]}"

echo "[INFO] installing HAP on the USB device"
"$HDC" -t "$DEVICE" install -r "$HAP" >"$INSTALL_LOG"
grep -q 'install bundle successfully' "$INSTALL_LOG" || {
  cat "$INSTALL_LOG" >&2
  exit 1
}

"$HDC" -t "$DEVICE" shell power-shell wakeup >/dev/null 2>&1 || true
dismiss_usb_mode_dialog
"$HDC" -t "$DEVICE" shell hilog -r >/dev/null
"$HDC" -t "$DEVICE" shell aa force-stop "$BUNDLE" >/dev/null 2>&1 || true
"$HDC" -t "$DEVICE" shell aa start -a "$ABILITY" -b "$BUNDLE" -m "$MODULE" >/dev/null

for elapsed in $(seq 1 "$TIMEOUT_SECONDS"); do
  sleep 1
  PID="$($HDC -t "$DEVICE" shell pidof "$BUNDLE" 2>/dev/null | tr -d '\r')"
  [[ -n "$PID" ]] || fail_with_logs "demo process exited after ${elapsed}s"

  if ! "$HDC" -t "$DEVICE" shell uitest dumpLayout -p "$REMOTE_LAYOUT" -b "$BUNDLE" >/dev/null 2>&1; then
    continue
  fi
  if ! "$HDC" -t "$DEVICE" file recv "$REMOTE_LAYOUT" "$LOCAL_LAYOUT" >/dev/null 2>&1; then
    continue
  fi

  UI_RESULT="$("$LICENSE_PYTHON" - "$LOCAL_LAYOUT" <<'PY'
import json
import sys
from pathlib import Path

try:
    root = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    raise SystemExit(0)

texts = []
def visit(value):
    if isinstance(value, dict):
        attributes = value.get("attributes")
        if isinstance(attributes, dict):
            text = attributes.get("text")
            if isinstance(text, str) and text:
                texts.append(text)
        for child in value.values():
            visit(child)
    elif isinstance(value, list):
        for child in value:
            visit(child)
visit(root)

failures = ("授权文件准备失败", "授权失败", "引擎初始化失败", "运行时拉起失败", "模型加载失败")
for text in texts:
    if any(marker in text for marker in failures):
        print(f"FAIL\t{text}")
        raise SystemExit(0)
# prepareRuntime 返回时默认中英模型必须已经就绪；旧的纯 Runtime ready 文案不能通过此门禁。
for text in texts:
    if "默认中英模型已就绪" in text:
        print(f"READY\t{text}")
        raise SystemExit(0)
PY
)"

  case "$UI_RESULT" in
    READY$'\t'*)
      echo "[OK] ${UI_RESULT#*$'\t'}"
      echo "[OK] process remains alive"
      echo "[DONE] Harmony demo build/install smoke test passed"
      exit 0
      ;;
    FAIL$'\t'*) fail_with_logs "${UI_RESULT#*$'\t'}" ;;
  esac
done

fail_with_logs "timed out after ${TIMEOUT_SECONDS}s waiting for engine readiness"
