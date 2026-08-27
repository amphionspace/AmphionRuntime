#!/usr/bin/env bash
# Fail-fast verification for Harmony demo source inputs and an optional signed HAP.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
MODEL_ROOT="$REPO_ROOT/asr/harmony/sdk/src/main/resources/rawfile/amphion-models"
POLICE_ROOT="$REPO_ROOT/asr/harmony/sdk-police/src/main/resources/rawfile/amphion-police"
LICENSE_FILE="$REPO_ROOT/delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/resources/rawfile/amphion-license.lic"
DEVICE_ID_FILE="${DINGQIAO_DEVICE_ID_FILE:-$REPO_ROOT/.secure/amphion_asr_demo_device_ids.txt}"
PRIVATE_KEY="${AMPHION_LICENSE_PRIVATE_KEY:-$REPO_ROOT/.secure/amphion-license-private.pem}"
HAP=""
BUNDLE_NAME="com.amphion.asr.harmony.demo"
MODULE_NAME="amphion_asr_demo"
SIGNING_CONFIG="${HARMONY_SIGNING_CONFIG:-}"
ZH_EN_ONLY=false
DEVECO_HOME="${DEVECO_STUDIO_HOME:-/Applications/DevEco-Studio.app/Contents}"
HAP_SIGN_TOOL_JAR="${HAP_SIGN_TOOL_JAR:-$DEVECO_HOME/sdk/default/openharmony/toolchains/lib/hap-sign-tool.jar}"
JAVA_BIN="${JAVA_HOME:+$JAVA_HOME/bin/java}"
JAVA_BIN="${JAVA_BIN:-$DEVECO_HOME/jbr/Contents/Home/bin/java}"
LICENSE_VENV="$REPO_ROOT/tools/license/.venv"
VERIFY_DIR=""
ZH_EN_ONLY=false

usage() {
  cat <<'EOF'
Usage: verify_demo_inputs.sh [options]

Options:
  --hap PATH             Also verify the built signed HAP.
  --license PATH         License rawfile to verify.
  --device-id-file PATH  Authorized device identifiers, one per line.
  --private-key PATH     Optional private key; verifies it matches the embedded public key.
  --signing-config PATH  Expected signing config; required with --hap, defaults to .secure.
  --zh-en-only           Verify the demo's ZH_EN-only model payload.
  -h, --help             Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hap) HAP="$2"; shift 2 ;;
    --license) LICENSE_FILE="$2"; shift 2 ;;
    --device-id-file) DEVICE_ID_FILE="$2"; shift 2 ;;
    --private-key) PRIVATE_KEY="$2"; shift 2 ;;
    --signing-config) SIGNING_CONFIG="$2"; shift 2 ;;
    --zh-en-only) ZH_EN_ONLY=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[ERROR] unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -n "$HAP" && -z "$SIGNING_CONFIG" && -s "$REPO_ROOT/.secure/harmony-signing.json" ]]; then
  SIGNING_CONFIG="$REPO_ROOT/.secure/harmony-signing.json"
fi
if [[ -n "$HAP" && -z "$SIGNING_CONFIG" ]]; then
  echo "[ERROR] HAP provenance verification requires --signing-config or HARMONY_SIGNING_CONFIG" >&2
  exit 1
fi

require_file() {
  [[ -s "$1" ]] || { echo "[ERROR] missing or empty file: $1" >&2; exit 1; }
}

cleanup_verify_dir() {
  [[ -z "$VERIFY_DIR" ]] || rm -rf "$VERIFY_DIR"
}

source "$REPO_ROOT/asr/tools/license/ensure_python.sh"
ensure_license_python "$LICENSE_VENV" "$REPO_ROOT/tools/license/requirements.txt"
PYTHON="$LICENSE_VENV/bin/python"
require_file "$LICENSE_FILE"

"$PYTHON" "$REPO_ROOT/asr/tools/sync_harmony_police_assets.py" --check
MODEL_VERIFY_ARGS=(--root "$MODEL_ROOT")
if [[ "$ZH_EN_ONLY" == true ]]; then
  MODEL_VERIFY_ARGS+=(--zh-en-only)
fi
"$PYTHON" "$REPO_ROOT/asr/tools/verify_packed_model_assets.py" "${MODEL_VERIFY_ARGS[@]}"
"$PYTHON" "$SCRIPT_DIR/verify_dingqiao_model_md5.py" --root "$MODEL_ROOT"

"$PYTHON" - "$REPO_ROOT" <<'PY'
import struct
import sys
from pathlib import Path

root = Path(sys.argv[1])
libraries = [
    root / "asr/harmony/sdk/src/main/cpp/libs/arm64-v8a/libamphion_audio_processing.so",
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

PUBLIC_KEY_B64="$("$PYTHON" - "$REPO_ROOT/asr/harmony/sdk/src/main/ets/com/amphion/asr/License.ets" <<'PY'
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

VERIFY_LICENSE=(
  "$PYTHON" "$REPO_ROOT/tools/license/verify_license.py"
  --license "$LICENSE_FILE"
  --public-key-b64 "$PUBLIC_KEY_B64"
  --bundle-name "$BUNDLE_NAME"
  --required-feature ASR
)

"${VERIFY_LICENSE[@]}" >/dev/null
"$PYTHON" "$REPO_ROOT/tools/license/verify_license_device_set.py" \
  --license "$LICENSE_FILE" \
  --device-id-file "$DEVICE_ID_FILE"
echo "[OK] license signature, expiry, feature, and device set verified"

if [[ -n "$HAP" ]]; then
  require_file "$HAP"
  require_file "$HAP_SIGN_TOOL_JAR"
  [[ -x "$JAVA_BIN" ]] || { echo "[ERROR] missing Java runtime: $JAVA_BIN" >&2; exit 1; }

  VERIFY_DIR="$(mktemp -d "${TMPDIR:-/tmp}/amphion-hap-verify.XXXXXX")"
  trap cleanup_verify_dir EXIT
  trap 'cleanup_verify_dir; exit 130' INT TERM
  if ! "$JAVA_BIN" -jar "$HAP_SIGN_TOOL_JAR" verify-app \
      -inFile "$HAP" \
      -outCertChain "$VERIFY_DIR/cert-chain.cer" \
      -outProfile "$VERIFY_DIR/profile.p7b" \
      >"$VERIFY_DIR/verify-app.log" 2>&1; then
    cat "$VERIFY_DIR/verify-app.log" >&2
    echo "[ERROR] HAP signature verification failed" >&2
    exit 1
  fi
  grep -q 'verify-app success' "$VERIFY_DIR/verify-app.log" || {
    cat "$VERIFY_DIR/verify-app.log" >&2
    echo "[ERROR] HAP signature tool did not report success" >&2
    exit 1
  }
  require_file "$VERIFY_DIR/cert-chain.cer"
  require_file "$VERIFY_DIR/profile.p7b"

  if ! "$JAVA_BIN" -jar "$HAP_SIGN_TOOL_JAR" verify-profile \
      -inFile "$VERIFY_DIR/profile.p7b" \
      -outFile "$VERIFY_DIR/profile-result.json" \
      >"$VERIFY_DIR/verify-profile.log" 2>&1; then
    cat "$VERIFY_DIR/verify-profile.log" >&2
    echo "[ERROR] embedded HAP profile verification failed" >&2
    exit 1
  fi

  HAP_MODEL_VERIFY_ARGS=(--archive "$HAP")
  if [[ "$ZH_EN_ONLY" == true ]]; then
    HAP_MODEL_VERIFY_ARGS+=(--zh-en-only)
  fi
  "$PYTHON" "$REPO_ROOT/asr/tools/verify_packed_model_assets.py" "${HAP_MODEL_VERIFY_ARGS[@]}"
  "$PYTHON" "$SCRIPT_DIR/verify_dingqiao_model_md5.py" --archive "$HAP"
  "$PYTHON" "$SCRIPT_DIR/verify_harmony_native_abi.py" --hap "$HAP"
  "$PYTHON" - \
    "$HAP" \
    "$LICENSE_FILE" \
    "$VERIFY_DIR/profile-result.json" \
    "$BUNDLE_NAME" \
    "$MODULE_NAME" \
    "$MODEL_ROOT/manifest.json" \
    "$POLICE_ROOT" \
    "$REPO_ROOT/shared/models/asr/dingqiao/eres2net.onnx" \
    "$REPO_ROOT/shared/models/asr/dingqiao/pyannote-segmentation-3.0.onnx" \
    "$REPO_ROOT/asr/harmony/sdk/src/main/cpp/libs/arm64-v8a/libsherpa-onnx-c-api.so" \
    "$REPO_ROOT/asr/harmony/sdk/src/main/cpp/libs/arm64-v8a/libonnxruntime.so" \
    "$REPO_ROOT/asr/harmony/sdk/src/main/cpp/libs/arm64-v8a/libamphion_audio_processing.so" \
    "$ZH_EN_ONLY" <<'PY'
import json
import hashlib
import sys
import zipfile
from pathlib import Path

hap = Path(sys.argv[1])
license_path = Path(sys.argv[2])
profile_result_path = Path(sys.argv[3])
expected_bundle = sys.argv[4]
expected_module = sys.argv[5]
local_manifest = Path(sys.argv[6])
police_root = Path(sys.argv[7])
local_voiceprint = Path(sys.argv[8])
local_speaker_turn = Path(sys.argv[9])
local_sherpa = Path(sys.argv[10])
local_ort = Path(sys.argv[11])
local_agc = Path(sys.argv[12])
zh_en_only = sys.argv[13] == "true"
required = {
    "libs/arm64-v8a/libamphion_audio_processing.so",
    "libs/arm64-v8a/libamphion_asr.so",
    "libs/arm64-v8a/libonnxruntime.so",
    "libs/arm64-v8a/libsherpa-onnx-c-api.so",
    "libs/arm64-v8a/libsherpa_onnx.so",
    "resources/rawfile/amphion-license.lic",
    "resources/rawfile/amphion-dingqiao/eres2net.onnx",
    "resources/rawfile/amphion-dingqiao/pyannote-segmentation-3.0.onnx",
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
    if package.read("resources/rawfile/amphion-models/manifest.json") != local_manifest.read_bytes():
        raise SystemExit("[ERROR] HAP model manifest differs from the verified local manifest")
    if package.read("resources/rawfile/amphion-dingqiao/eres2net.onnx") != local_voiceprint.read_bytes():
        raise SystemExit("[ERROR] HAP voiceprint model differs from the verified SDK asset")
    if package.read("resources/rawfile/amphion-dingqiao/pyannote-segmentation-3.0.onnx") != local_speaker_turn.read_bytes():
        raise SystemExit("[ERROR] HAP speaker-turn model differs from the verified SDK asset")
    if not zh_en_only:
        police_manifest = json.loads((police_root / "manifest.json").read_text(encoding="utf-8"))
        for relative, expected_sha256 in police_manifest["files"].items():
            member = f"resources/rawfile/amphion-police/{relative}"
            if member not in names:
                raise SystemExit(f"[ERROR] HAP missing police asset: {member}")
            if hashlib.sha256(package.read(member)).hexdigest() != expected_sha256:
                raise SystemExit(f"[ERROR] HAP police asset differs from Android source: {member}")
    if package.read("libs/arm64-v8a/libsherpa-onnx-c-api.so") != local_sherpa.read_bytes():
        raise SystemExit("[ERROR] HAP sherpa native library differs from the verified local library")
    if package.read("libs/arm64-v8a/libonnxruntime.so") != local_ort.read_bytes():
        raise SystemExit("[ERROR] HAP ONNX Runtime library differs from the verified local library")
    if package.read("libs/arm64-v8a/libamphion_audio_processing.so") != local_agc.read_bytes():
        raise SystemExit("[ERROR] HAP AGC native library differs from the verified local library")
    try:
        module = json.loads(package.read("module.json"))
    except (KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"[ERROR] invalid HAP module metadata: {exc}") from exc
    if module.get("app", {}).get("bundleName") != expected_bundle:
        raise SystemExit("[ERROR] HAP bundle name does not match the Dingqiao demo")
    if module.get("module", {}).get("name") != expected_module:
        raise SystemExit("[ERROR] HAP module name does not match the Dingqiao demo")

profile_result = json.loads(profile_result_path.read_text(encoding="utf-8"))
if profile_result.get("verifiedPassed") is not True:
    raise SystemExit("[ERROR] embedded HAP profile did not pass signature verification")
profile_bundle = profile_result.get("content", {}).get("bundle-info", {}).get("bundle-name")
if profile_bundle != expected_bundle:
    raise SystemExit("[ERROR] embedded HAP profile is issued for a different bundle")
print("[OK] HAP signature, profile, identity, license, and arm64 runtime verified")
PY

  require_file "$SIGNING_CONFIG"
  if [[ "$(uname)" == "Darwin" ]]; then
    SIGNING_CONFIG_MODE="$(stat -f '%Lp' "$SIGNING_CONFIG")"
  else
    SIGNING_CONFIG_MODE="$(stat -c '%a' "$SIGNING_CONFIG")"
  fi
  [[ "$SIGNING_CONFIG_MODE" == "600" || "$SIGNING_CONFIG_MODE" == "400" ]] || {
    echo "[ERROR] signing config must not be group/world readable: chmod 600 $SIGNING_CONFIG" >&2
    exit 1
  }
  "$PYTHON" - "$SIGNING_CONFIG" "$VERIFY_DIR/cert-chain.cer" <<'PY'
import json
import re
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes


def fingerprints(path: Path) -> set[bytes]:
    blocks = re.findall(
        b"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
        path.read_bytes(),
        re.DOTALL,
    )
    if not blocks:
        raise SystemExit(f"[ERROR] certificate chain is not PEM: {path}")
    return {x509.load_pem_x509_certificate(block).fingerprint(hashes.SHA256()) for block in blocks}


config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected_path = Path(config.get("certpath", ""))
if not expected_path.is_file():
    raise SystemExit("[ERROR] signing config certpath is missing or invalid")
if fingerprints(expected_path) != fingerprints(Path(sys.argv[2])):
    raise SystemExit("[ERROR] HAP certificate chain differs from the expected signing config")
print("[OK] HAP certificate chain matches the expected signing config")
PY
  cleanup_verify_dir
  VERIFY_DIR=""
  trap - EXIT INT TERM
fi

echo "[DONE] Harmony demo preflight passed"
