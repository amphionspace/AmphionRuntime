#!/usr/bin/env bash
# Build, verify, install, launch, and wait for the Harmony demo engine to become ready.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PROJECT_ROOT="$REPO_ROOT/delivery/harmony-dingqiao"
DEVECO_HOME="${DEVECO_STUDIO_HOME:-/Applications/DevEco-Studio.app/Contents}"
NODE="$DEVECO_HOME/tools/node/bin/node"
HVIGOR="$DEVECO_HOME/tools/hvigor/bin/hvigorw.js"
HDC="$DEVECO_HOME/sdk/default/openharmony/toolchains/hdc"
JAVA_HOME_VALUE="${JAVA_HOME:-$DEVECO_HOME/jbr/Contents/Home}"
HAP="$PROJECT_ROOT/samples/dingqiao-demo/entry/build/default/outputs/default/dingqiao_demo-default-signed.hap"
BUILD_PROFILE="$PROJECT_ROOT/build-profile.json5"
BUNDLE="com.amphion.dingqiao.harmony.demo"
MODULE="dingqiao_demo"
ABILITY="EntryAbility"
DEVICE=""
TIMEOUT_SECONDS=30
SKIP_BUILD=false
SMOKE_DIR="$PROJECT_ROOT/build/smoke"
SIGNING_CONFIG="${HARMONY_SIGNING_CONFIG:-}"

usage() {
  cat <<'EOF'
Usage: build_install_smoke.sh [options]

Options:
  --device SERIAL   HDC target. Auto-detected when exactly one device is connected.
  --timeout SEC     Engine-ready timeout; default 30 seconds.
  --skip-build      Reuse the existing signed HAP.
  --signing-config  Local signing material JSON; defaults to .secure/harmony-signing.json.
  -h, --help        Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --device) DEVICE="$2"; shift 2 ;;
    --timeout) TIMEOUT_SECONDS="$2"; shift 2 ;;
    --skip-build) SKIP_BUILD=true; shift ;;
    --signing-config) SIGNING_CONFIG="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[ERROR] unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

for tool in "$NODE" "$HVIGOR" "$HDC"; do
  [[ -x "$tool" || -f "$tool" ]] || { echo "[ERROR] missing DevEco tool: $tool" >&2; exit 1; }
done
[[ "$TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]] || { echo "[ERROR] --timeout must be a positive integer" >&2; exit 2; }

if [[ -z "$DEVICE" ]]; then
  TARGETS="$($HDC list targets | tr -d '\r' | awk 'NF')"
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
BUILD_PROFILE_BACKUP="$SMOKE_DIR/build-profile.backup.json5"

restore_build_profile() {
  if [[ -f "$BUILD_PROFILE_BACKUP" ]]; then
    cp "$BUILD_PROFILE_BACKUP" "$BUILD_PROFILE"
    rm -f "$BUILD_PROFILE_BACKUP"
  fi
}
trap restore_build_profile EXIT
trap 'restore_build_profile; exit 130' INT TERM

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

  cp "$BUILD_PROFILE" "$BUILD_PROFILE_BACKUP"
  python3 - "$BUILD_PROFILE" "$config" <<'PY'
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
print("[OK] local signing configuration validated and applied temporarily")
PY
}

capture_hilog() {
  "$HDC" -t "$DEVICE" shell hilog -x >"$HILOG_FILE" 2>/dev/null || true
}

fail_with_logs() {
  local message="$1"
  capture_hilog
  echo "[ERROR] $message" >&2
  grep -Ei 'Amphion|Dingqiao|LastFatalMessage|SIGABRT|cppcrash|exception' "$HILOG_FILE" | tail -80 >&2 || true
  echo "[INFO] smoke artifacts: $SMOKE_DIR" >&2
  exit 1
}

"$SCRIPT_DIR/verify_demo_inputs.sh"

if [[ "$SKIP_BUILD" != true ]]; then
  if [[ -z "$SIGNING_CONFIG" && -f "$REPO_ROOT/.secure/harmony-signing.json" ]]; then
    SIGNING_CONFIG="$REPO_ROOT/.secure/harmony-signing.json"
  fi
  [[ -n "$SIGNING_CONFIG" ]] || {
    echo "[ERROR] signed build requires --signing-config or HARMONY_SIGNING_CONFIG" >&2
    echo "        template: $SCRIPT_DIR/harmony-signing.example.json" >&2
    exit 1
  }
  apply_local_signing "$SIGNING_CONFIG"
  echo "[INFO] building signed Harmony demo HAP"
  if ! (
    export PATH="$DEVECO_HOME/tools/node/bin:$PATH"
    export DEVECO_SDK_HOME="$DEVECO_HOME/sdk"
    export JAVA_HOME="$JAVA_HOME_VALUE"
    cd "$PROJECT_ROOT"
    "$NODE" "$HVIGOR" assembleHap --mode module \
      -p product=default \
      -p module=dingqiao_demo@default \
      -p buildMode=debug \
      --no-daemon --stacktrace
  ) >"$BUILD_LOG" 2>&1; then
    tail -120 "$BUILD_LOG" >&2
    exit 1
  fi
  restore_build_profile
  echo "[OK] HAP build succeeded"
fi

"$SCRIPT_DIR/verify_demo_inputs.sh" --hap "$HAP"

echo "[INFO] installing HAP on the USB device"
"$HDC" -t "$DEVICE" install -r "$HAP" >"$INSTALL_LOG"
grep -q 'install bundle successfully' "$INSTALL_LOG" || {
  cat "$INSTALL_LOG" >&2
  exit 1
}

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

  UI_RESULT="$(python3 - "$LOCAL_LAYOUT" <<'PY'
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

failures = ("授权文件准备失败", "授权失败", "引擎初始化失败")
for text in texts:
    if any(marker in text for marker in failures):
        print(f"FAIL\t{text}")
        raise SystemExit(0)
for text in texts:
    if "引擎就绪" in text:
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
