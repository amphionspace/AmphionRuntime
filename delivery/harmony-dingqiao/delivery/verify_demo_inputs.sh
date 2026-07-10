#!/usr/bin/env bash
# Fail-fast verification for Harmony demo source inputs and an optional signed HAP.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
MODEL_ROOT="$REPO_ROOT/asr/harmony/sdk/src/main/resources/rawfile/amphion-models"
LICENSE_FILE="$REPO_ROOT/delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/resources/rawfile/amphion-license.lic"
DEVICE_ID_FILE="${DINGQIAO_DEVICE_ID_FILE:-$REPO_ROOT/.secure/current_usb_device_sn.txt}"
PRIVATE_KEY="${AMPHION_LICENSE_PRIVATE_KEY:-$REPO_ROOT/.secure/amphion-license-private.pem}"
HAP=""
BUNDLE_NAME="com.amphion.dingqiao.harmony.demo"

usage() {
  cat <<'EOF'
Usage: verify_demo_inputs.sh [options]

Options:
  --hap PATH             Also verify the built signed HAP.
  --license PATH         License rawfile to verify.
  --device-id-file PATH  Authorized device identifiers, one per line.
  --private-key PATH     Optional private key; verifies it matches the embedded public key.
  -h, --help             Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hap) HAP="$2"; shift 2 ;;
    --license) LICENSE_FILE="$2"; shift 2 ;;
    --device-id-file) DEVICE_ID_FILE="$2"; shift 2 ;;
    --private-key) PRIVATE_KEY="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[ERROR] unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

require_file() {
  [[ -s "$1" ]] || { echo "[ERROR] missing or empty file: $1" >&2; exit 1; }
}

command -v python3 >/dev/null || { echo "[ERROR] python3 is required" >&2; exit 1; }
require_file "$LICENSE_FILE"

python3 "$REPO_ROOT/asr/tools/verify_packed_model_assets.py" --root "$MODEL_ROOT"

python3 - "$REPO_ROOT" <<'PY'
import struct
import sys
from pathlib import Path

root = Path(sys.argv[1])
libraries = [
    root / "asr/harmony/sdk/src/main/cpp/libs/arm64-v8a/libonnxruntime.so",
    root / "asr/harmony/sdk/src/main/cpp/libs/arm64-v8a/libsherpa-onnx-c-api.so",
    root / "third_party/sherpa-onnx/harmony-os/SherpaOnnxHar/sherpa_onnx/src/main/cpp/libs/arm64-v8a/libonnxruntime.so",
    root / "third_party/sherpa-onnx/harmony-os/SherpaOnnxHar/sherpa_onnx/src/main/cpp/libs/arm64-v8a/libsherpa-onnx-c-api.so",
]
for path in libraries:
    data = path.read_bytes()[:20]
    if data[:4] != b"\x7fELF" or len(data) < 20:
        raise SystemExit(f"[ERROR] invalid ELF library: {path}")
    byte_order = "<" if data[5] == 1 else ">"
    if struct.unpack(f"{byte_order}H", data[18:20])[0] != 183:
        raise SystemExit(f"[ERROR] native library is not AArch64: {path}")
print(f"[OK] verified {len(libraries)} AArch64 native libraries")
PY

PUBLIC_KEY_B64="$(python3 - "$REPO_ROOT/asr/harmony/sdk/src/main/ets/com/amphion/asr/License.ets" <<'PY'
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8")
match = re.search(r"LICENSE_PUBLIC_KEY_B64\s*(?::\s*string)?\s*=\s*'([^']+)'", text)
if not match:
    raise SystemExit("embedded license public key not found")
print(match.group(1))
PY
)"

if [[ -s "$PRIVATE_KEY" ]]; then
  command -v openssl >/dev/null || { echo "[ERROR] openssl is required to verify the private key" >&2; exit 1; }
  DERIVED_PUBLIC_KEY="$(openssl pkey -in "$PRIVATE_KEY" -pubout -outform DER 2>/dev/null | openssl base64 -A)"
  [[ "$DERIVED_PUBLIC_KEY" == "$PUBLIC_KEY_B64" ]] || {
    echo "[ERROR] private key does not match the SDK embedded public key" >&2
    exit 1
  }
  echo "[OK] private key matches the SDK embedded public key"
fi

DEVICE_HASH_COUNT="$(python3 - "$LICENSE_FILE" <<'PY'
import base64
import json
import sys
from pathlib import Path

envelope = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
claims = json.loads(base64.b64decode(envelope["payload_b64"]))
print(len(claims.get("authorizedDeviceHashes", [])))
PY
)"

VERIFY_LICENSE=(
  python3 "$REPO_ROOT/tools/license/verify_license.py"
  --license "$LICENSE_FILE"
  --public-key-b64 "$PUBLIC_KEY_B64"
  --bundle-name "$BUNDLE_NAME"
  --required-feature ASR
)

if [[ "$DEVICE_HASH_COUNT" -gt 0 ]]; then
  require_file "$DEVICE_ID_FILE"
  VERIFIED_DEVICE_IDS=0
  while IFS= read -r device_id; do
    [[ -n "${device_id//[[:space:]]/}" ]] || continue
    [[ "$device_id" =~ ^[[:space:]]*# ]] && continue
    "${VERIFY_LICENSE[@]}" --device-id "$device_id" >/dev/null
    VERIFIED_DEVICE_IDS=$((VERIFIED_DEVICE_IDS + 1))
  done < "$DEVICE_ID_FILE"
  [[ "$VERIFIED_DEVICE_IDS" -eq "$DEVICE_HASH_COUNT" ]] || {
    echo "[ERROR] license device hash count does not match the authorized device list" >&2
    exit 1
  }
  echo "[OK] license signature, expiry, feature, and $VERIFIED_DEVICE_IDS device bindings verified"
else
  "${VERIFY_LICENSE[@]}" >/dev/null
  echo "[OK] unbound license signature, expiry, and feature verified"
fi

if [[ -n "$HAP" ]]; then
  require_file "$HAP"
  python3 "$REPO_ROOT/asr/tools/verify_packed_model_assets.py" --archive "$HAP"
  python3 - "$HAP" "$LICENSE_FILE" <<'PY'
import sys
import zipfile
from pathlib import Path

hap = Path(sys.argv[1])
license_path = Path(sys.argv[2])
required = {
    "libs/arm64-v8a/libamphion_asr.so",
    "libs/arm64-v8a/libonnxruntime.so",
    "libs/arm64-v8a/libsherpa-onnx-c-api.so",
    "libs/arm64-v8a/libsherpa_onnx.so",
    "resources/rawfile/amphion-license.lic",
}
with zipfile.ZipFile(hap) as package:
    names = set(package.namelist())
    missing = sorted(required - names)
    if missing:
        raise SystemExit(f"[ERROR] HAP missing required entries: {missing}")
    if any(name.startswith("libs/x86_64/") for name in names):
        raise SystemExit("[ERROR] HAP unexpectedly contains x86_64 native libraries")
    if package.read("resources/rawfile/amphion-license.lic") != license_path.read_bytes():
        raise SystemExit("[ERROR] HAP license differs from the verified source license")
print("[OK] HAP license and required arm64 runtime libraries verified")
PY
fi

echo "[DONE] Harmony demo preflight passed"
