#!/usr/bin/env bash
# Generic zip-only delivery verification.
#
# The final ZIP is the only source of truth. This script extracts it to an
# isolated directory, validates packaged artifacts, optionally installs the APK
# from that extracted ZIP, and writes machine-readable reports.
#
# Usage:
#   DELIVERY_VERIFY_REQUIRED_AAR_ENTRIES='path:min_bytes,...' \
#   DELIVERY_VERIFY_REQUIRED_APK_ENTRIES='path:min_bytes,...' \
#   DELIVERY_VERIFY_LICENSE_ENTRY='assets/amphion-license.lic' \
#   DELIVERY_VERIFY_LICENSE_FEATURES='ASR' \
#   DELIVERY_VERIFY_LICENSE_DEVICE_HASH_COUNT='0' \
#   DELIVERY_VERIFY_ANDROID_PACKAGE='com.example.demo' \
#   bash tools/delivery/verify_delivery_zip_e2e.sh delivery.zip
#
# Optional device/source checks:
#   DELIVERY_VERIFY_DEVICE=1
#   DELIVERY_VERIFY_DEVICE_READY_TEXT='引擎就绪'
#   DELIVERY_VERIFY_DEVICE_MODEL_PATH='/sdcard/.../eres2net.onnx'
#   DELIVERY_VERIFY_SOURCE_TEST=1
#   DELIVERY_VERIFY_SOURCE_DIR='demo-src'
#   DELIVERY_VERIFY_SOURCE_GRADLE_TASK=':sample-dingqiao-demo:connectedDebugAndroidTest'
#   DELIVERY_VERIFY_SOURCE_GRADLE_ARGS='-Pandroid.testInstrumentationRunnerArguments.class=...'
set -euo pipefail

ZIP_PATH="${1:?usage: verify_delivery_zip_e2e.sh <delivery.zip>}"
[[ -f "$ZIP_PATH" ]] || { echo "[ERROR] zip not found: $ZIP_PATH" >&2; exit 1; }

WORKDIR="${DELIVERY_VERIFY_WORKDIR:-$(mktemp -d "${TMPDIR:-/tmp}/delivery-zip-e2e.XXXXXX")}"
REPORT_JSON="${DELIVERY_VERIFY_REPORT_JSON:-$ZIP_PATH.verification.json}"
REPORT_MD="${DELIVERY_VERIFY_REPORT_MD:-$ZIP_PATH.verification.md}"

mkdir -p "$WORKDIR"
rm -rf "$WORKDIR/extract"
mkdir -p "$WORKDIR/extract"

echo "[1/5] extract final zip ..."
unzip -q "$ZIP_PATH" -d "$WORKDIR/extract"

ROOT_DIR="$(
  python3 - "$WORKDIR/extract" <<'PY'
import sys
from pathlib import Path
base = Path(sys.argv[1])
dirs = [p for p in base.iterdir() if p.is_dir()]
if len(dirs) != 1:
    print(f"[ERROR] expected one top-level directory, found {len(dirs)}", file=sys.stderr)
    sys.exit(1)
print(dirs[0])
PY
)"

STATIC_JSON="$WORKDIR/static.json"
SIGN_JSON="$WORKDIR/apk-signature.json"
DEVICE_JSON="$WORKDIR/device.json"
SRC_JSON="$WORKDIR/source-test.json"

echo "[2/5] static artifact checks ..."
python3 - "$ZIP_PATH" "$ROOT_DIR" "$STATIC_JSON" <<'PY'
import base64
import glob
import hashlib
import json
import os
import stat
import sys
import zipfile
from pathlib import Path

zip_path = Path(sys.argv[1])
root = Path(sys.argv[2])
out = Path(sys.argv[3])

def fail(message: str) -> None:
    raise SystemExit(f"[ERROR] {message}")

def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)

def parse_entries(value: str) -> dict[str, int]:
    result = {}
    for raw in [p.strip() for p in value.split(",") if p.strip()]:
        if ":" in raw:
            path, size = raw.rsplit(":", 1)
            result[path] = int(size)
        else:
            result[raw] = 1
    return result

def one_glob(pattern: str, label: str):
    matches = sorted(root.glob(pattern))
    if not matches:
        return None
    if len(matches) != 1:
        fail(f"expected one {label} matching {pattern}, found {len(matches)}")
    return matches[0]

forbidden_fragments = ["/.git/", "/.secure/"]
forbidden_suffixes = ["-private.pem", ".jks", ".keystore", ".p12", ".p7b", ".cer", ".csr"]
for p in [p for p in root.rglob("*") if p.is_file()]:
    rel = "/" + p.relative_to(root).as_posix()
    low = rel.lower()
    if any(fragment in low for fragment in forbidden_fragments):
        fail(f"forbidden path: {rel}")
    if any(low.endswith(suffix) for suffix in forbidden_suffixes):
        fail(f"forbidden file: {rel}")

version_fields = {}
version_path = root / env("DELIVERY_VERIFY_VERSION_PATH", "VERSION.txt")
if version_path.is_file():
    for line in version_path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            version_fields[k] = v
    if env("DELIVERY_VERIFY_REQUIRE_CLEAN_GIT", "1") == "1" and version_fields.get("git_dirty") != "false":
        fail(f"VERSION.txt git_dirty must be false, got {version_fields.get('git_dirty')}")
elif env("DELIVERY_VERIFY_REQUIRE_VERSION", "1") == "1":
    fail(f"missing {version_path.relative_to(root)}")

aar = one_glob(env("DELIVERY_VERIFY_AAR_GLOB", "aar/*.aar"), "AAR")
apk = one_glob(env("DELIVERY_VERIFY_APK_GLOB", "demo/*.apk"), "APK")
required_aar = parse_entries(env("DELIVERY_VERIFY_REQUIRED_AAR_ENTRIES"))
required_apk = parse_entries(env("DELIVERY_VERIFY_REQUIRED_APK_ENTRIES"))

def zip_sizes(path: Path) -> dict[str, int]:
    with zipfile.ZipFile(path) as z:
        return {info.filename: info.file_size for info in z.infolist()}

def check_zip_entries(path, required: dict[str, int], label: str) -> dict[str, int]:
    if not required:
        return {}
    if path is None:
        fail(f"{label} required entries configured but no {label} found")
    sizes = zip_sizes(path)
    checked = {}
    for name, min_bytes in required.items():
        size = sizes.get(name, -1)
        if size < min_bytes:
            fail(f"{label} missing or too small: {name} bytes={size} min={min_bytes}")
        checked[name] = size
    return checked

checked_aar = check_zip_entries(aar, required_aar, "AAR")
checked_apk = check_zip_entries(apk, required_apk, "APK")

license_result = None
license_entry = env("DELIVERY_VERIFY_LICENSE_ENTRY")
if license_entry:
    if apk is None:
        fail("license entry configured but APK missing")
    with zipfile.ZipFile(apk) as z:
        payload = json.loads(base64.b64decode(json.loads(z.read(license_entry).decode("utf-8"))["payload_b64"]).decode("utf-8"))
    expected_features = [p for p in env("DELIVERY_VERIFY_LICENSE_FEATURES").split(",") if p]
    if expected_features and payload.get("features") != expected_features:
        fail(f"license features mismatch: {payload.get('features')} != {expected_features}")
    expected_hash_count = env("DELIVERY_VERIFY_LICENSE_DEVICE_HASH_COUNT")
    actual_hash_count = len(payload.get("authorizedDeviceHashes", []))
    if expected_hash_count and actual_hash_count != int(expected_hash_count):
        fail(f"license device hash count mismatch: {actual_hash_count} != {expected_hash_count}")
    if env("DELIVERY_VERIFY_LICENSE_REQUIRE_EXPIRES", "1") == "1" and not payload.get("expiresAt"):
        fail("license expiresAt is required")
    license_result = {
        "applicationId": payload.get("applicationId"),
        "bundleName": payload.get("bundleName"),
        "features": payload.get("features", []),
        "expiresAt": payload.get("expiresAt"),
        "device_hash_count": actual_hash_count,
    }

source_dir = root / env("DELIVERY_VERIFY_SOURCE_DIR", env("DELIVERY_VERIFY_DEMO_SRC_DIR", "demo-src"))
gradlew = source_dir / "gradlew"
source_result = {"exists": source_dir.is_dir(), "gradlew_executable": False}
if source_dir.is_dir() and gradlew.is_file():
    source_result["gradlew_executable"] = bool(gradlew.stat().st_mode & stat.S_IXUSR)
    if env("DELIVERY_VERIFY_REQUIRE_GRADLEW_EXECUTABLE", "1") == "1" and not source_result["gradlew_executable"]:
        fail("source gradlew is not executable")

for forbidden in [p for p in env("DELIVERY_VERIFY_FORBIDDEN_RELATIVE_PATHS", "").split(",") if p]:
    if (root / forbidden).exists():
        fail(f"forbidden relative path exists: {forbidden}")

result = {
    "zip_path": str(zip_path),
    "zip_sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
    "zip_size_bytes": zip_path.stat().st_size,
    "root_dir": str(root),
    "version": version_fields,
    "aar": {"path": str(aar) if aar else None, "checked_entries": checked_aar},
    "apk": {"path": str(apk) if apk else None, "checked_entries": checked_apk},
    "license": license_result,
    "source": source_result,
}
out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[OK] static checks passed: {out}")
PY

echo "[3/5] APK signature check ..."
APK_PATH="$(
  python3 - "$STATIC_JSON" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["apk"]["path"] or "")
PY
)"
if [[ -n "$APK_PATH" && -f "$APK_PATH" && "${DELIVERY_VERIFY_APK_SIGNATURE:-1}" == "1" ]]; then
  command -v apksigner >/dev/null 2>&1 || { echo "[ERROR] apksigner not found" >&2; exit 1; }
  apksigner verify --verbose "$APK_PATH" > "$WORKDIR/apksigner.txt"
  python3 - "$WORKDIR/apksigner.txt" "$SIGN_JSON" <<'PY'
import json, sys
text = open(sys.argv[1], encoding="utf-8").read()
if "Verifies" not in text or "Number of signers:" not in text:
    raise SystemExit("[ERROR] APK signature verification failed")
open(sys.argv[2], "w", encoding="utf-8").write(json.dumps({
    "ran": True,
    "verified": True,
    "summary": [line for line in text.splitlines() if line.startswith("Verified ") or line.startswith("Number of signers:")],
}, ensure_ascii=False, indent=2))
PY
  echo "[OK] APK signature verified"
else
  python3 - "$SIGN_JSON" <<'PY'
import json, sys
open(sys.argv[1], "w", encoding="utf-8").write(json.dumps({"ran": False}, ensure_ascii=False, indent=2))
PY
fi

if [[ "${DELIVERY_VERIFY_DEVICE:-0}" == "1" ]]; then
  echo "[4/5] device install check from extracted APK ..."
  PACKAGE="${DELIVERY_VERIFY_ANDROID_PACKAGE:?DELIVERY_VERIFY_ANDROID_PACKAGE is required when DELIVERY_VERIFY_DEVICE=1}"
  READY_TEXT="${DELIVERY_VERIFY_DEVICE_READY_TEXT:-}"
  MODEL_PATH="${DELIVERY_VERIFY_DEVICE_MODEL_PATH:-}"
  WAIT_SEC="${DELIVERY_VERIFY_DEVICE_WAIT_SEC:-25}"
  adb uninstall "$PACKAGE" >/dev/null 2>&1 || true
  adb logcat -c
  adb install -r -g "$APK_PATH"
  adb shell monkey -p "$PACKAGE" -c android.intent.category.LAUNCHER 1 >/dev/null
  sleep "$WAIT_SEC"
  adb shell uiautomator dump /sdcard/delivery_zip_e2e_window.xml >/dev/null
  adb pull /sdcard/delivery_zip_e2e_window.xml "$WORKDIR/window.xml" >/dev/null
  MODEL_BYTES="-1"
  if [[ -n "$MODEL_PATH" ]]; then
    MODEL_BYTES="$(adb shell "if [ -f '$MODEL_PATH' ]; then stat -c %s '$MODEL_PATH'; else echo -1; fi" | tr -d '\r[:space:]')"
  fi
  APP_PID="$(adb shell pidof "$PACKAGE" 2>/dev/null | tr -d '\r' | cut -d' ' -f1 || true)"
  if [[ -n "$APP_PID" ]]; then
    adb logcat -d -v time --pid "$APP_PID" > "$WORKDIR/logcat.txt" 2>/dev/null || adb logcat -d -v time > "$WORKDIR/logcat.txt"
  else
    adb logcat -d -v time > "$WORKDIR/logcat.txt"
  fi
  python3 - "$WORKDIR/window.xml" "$WORKDIR/logcat.txt" "$MODEL_BYTES" "$DEVICE_JSON" "$READY_TEXT" <<'PY'
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

window_xml, log_path, model_bytes_raw, out, ready_text = sys.argv[1:6]
model_bytes = int(model_bytes_raw or "-1")
texts = []
root = ET.parse(window_xml).getroot()
for node in root.iter("node"):
    text = node.attrib.get("text", "")
    if text:
        texts.append(text)
log_text = Path(log_path).read_text(encoding="utf-8", errors="replace")
bad_patterns = [
    "FATAL EXCEPTION",
    "UnsatisfiedLinkError",
    "dlopen failed",
    "device SN unavailable",
    "DEVICE_MISMATCH",
    "code=6007",
    "speaker model not found",
    "引擎初始化失败",
]
bad_matches = [p for p in bad_patterns if re.search(re.escape(p), log_text, flags=re.IGNORECASE)]
if ready_text and not any(ready_text in text for text in texts):
    raise SystemExit(f"[ERROR] ready text not found: {ready_text}")
if model_bytes != -1 and model_bytes < 30 * 1024 * 1024:
    raise SystemExit(f"[ERROR] model file too small: {model_bytes}")
if bad_matches:
    raise SystemExit(f"[ERROR] bad log patterns found: {bad_matches}")
Path(out).write_text(json.dumps({
    "ran": True,
    "texts": texts,
    "speaker_model_bytes": model_bytes,
    "bad_log_patterns": bad_matches,
}, ensure_ascii=False, indent=2), encoding="utf-8")
print("[OK] device check passed")
PY
else
  python3 - "$DEVICE_JSON" <<'PY'
import json, sys
open(sys.argv[1], "w", encoding="utf-8").write(json.dumps({"ran": False}, ensure_ascii=False, indent=2))
PY
  echo "[4/5] skip device check"
fi

SOURCE_TEST="${DELIVERY_VERIFY_SOURCE_TEST:-${DELIVERY_VERIFY_DEMO_SRC_TEST:-0}}"
if [[ "$SOURCE_TEST" == "1" ]]; then
  echo "[4b/5] source package device test from extracted ZIP ..."
  SRC_DIR="$ROOT_DIR/${DELIVERY_VERIFY_SOURCE_DIR:-${DELIVERY_VERIFY_DEMO_SRC_DIR:-demo-src}}"
  TASK="${DELIVERY_VERIFY_SOURCE_GRADLE_TASK:-${DELIVERY_VERIFY_DEMO_SRC_GRADLE_TASK:-}}"
  [[ -n "$TASK" ]] || { echo "[ERROR] DELIVERY_VERIFY_SOURCE_GRADLE_TASK is required" >&2; exit 1; }
  GRADLE_ARGS="${DELIVERY_VERIFY_SOURCE_GRADLE_ARGS:-${DELIVERY_VERIFY_DEMO_SRC_GRADLE_ARGS:-}}"
  SDK_DIR="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
  [[ -d "$SDK_DIR" ]] || { echo "[ERROR] Android SDK not found: $SDK_DIR" >&2; exit 1; }
  (
    cd "$SRC_DIR"
    printf 'sdk.dir=%s\n' "$SDK_DIR" > local.properties
    ./gradlew "$TASK" $GRADLE_ARGS
  ) | tee "$WORKDIR/source-test.log"
  if [[ -n "${DELIVERY_VERIFY_ANDROID_PACKAGE:-}" && -n "$APK_PATH" && -f "$APK_PATH" ]]; then
    adb uninstall "$DELIVERY_VERIFY_ANDROID_PACKAGE" >/dev/null 2>&1 || true
    adb install -r -g "$APK_PATH" >/dev/null
  fi
  python3 - "$SRC_JSON" <<'PY'
import json, sys
open(sys.argv[1], "w", encoding="utf-8").write(json.dumps({"ran": True, "passed": True}, ensure_ascii=False, indent=2))
PY
else
  python3 - "$SRC_JSON" <<'PY'
import json, sys
open(sys.argv[1], "w", encoding="utf-8").write(json.dumps({"ran": False}, ensure_ascii=False, indent=2))
PY
fi

echo "[5/5] write reports ..."
python3 - "$STATIC_JSON" "$SIGN_JSON" "$DEVICE_JSON" "$SRC_JSON" "$REPORT_JSON" "$REPORT_MD" <<'PY'
import json
import sys
from pathlib import Path

static = json.load(open(sys.argv[1], encoding="utf-8"))
sign = json.load(open(sys.argv[2], encoding="utf-8"))
device = json.load(open(sys.argv[3], encoding="utf-8"))
source = json.load(open(sys.argv[4], encoding="utf-8"))
report_json = Path(sys.argv[5])
report_md = Path(sys.argv[6])
report = {
    "status": "PASS",
    "static": static,
    "apk_signature": sign,
    "device": device,
    "source_test": source,
}
report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
lines = [
    "# Delivery Zip Verification Report",
    "",
    "- Status: PASS",
    f"- Zip: `{static['zip_path']}`",
    f"- SHA-256: `{static['zip_sha256']}`",
    f"- Commit: `{static['version'].get('git_commit_full', '')}`",
    f"- Git dirty: `{static['version'].get('git_dirty', '')}`",
    f"- APK signature verified: `{sign.get('verified')}`",
    f"- Device check ran: `{device.get('ran')}`",
    f"- Source test ran: `{source.get('ran')}`",
]
if static.get("license"):
    lines += [
        f"- License applicationId record: `{static['license'].get('applicationId')}`",
        f"- License bundleName record: `{static['license'].get('bundleName')}`",
        f"- License features: `{','.join(static['license'].get('features', []))}`",
        f"- License device hash count: `{static['license'].get('device_hash_count')}`",
        f"- License expiresAt: `{static['license'].get('expiresAt')}`",
    ]
report_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"[OK] report json: {report_json}")
print(f"[OK] report md:   {report_md}")
PY
