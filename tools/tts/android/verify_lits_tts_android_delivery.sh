#!/usr/bin/env bash
# Verify a Lits TTS Android delivery VERSION.txt, AAR, directory, or zip.
#
# Usage:
#   bash tools/tts/android/verify_lits_tts_android_delivery.sh path/to/VERSION.txt
#   bash tools/tts/android/verify_lits_tts_android_delivery.sh path/to/lits-tts-sdk-*.aar
#   bash tools/tts/android/verify_lits_tts_android_delivery.sh path/to/lits-tts-android-sdk-v*/
#   bash tools/tts/android/verify_lits_tts_android_delivery.sh path/to/lits-tts-android-sdk-v*.zip
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lits_tts_delivery_common.sh
source "$SCRIPT_DIR/lits_tts_delivery_common.sh"

REPO_ROOT="$(lits_tts_repo_root_from_script)"
TARGET="${1:?usage: verify_lits_tts_android_delivery.sh <VERSION.txt|*.aar|delivery-dir|*.zip>}"

fail() { echo "[FAIL] $*" >&2; exit 1; }
ok() { echo "[OK] $*"; }

verify_zip() {
  local zip_path="$1"
  python3 - "$zip_path" <<'PY'
import sys
import zipfile
from pathlib import Path

path = Path(sys.argv[1])
with zipfile.ZipFile(path) as zf:
    bad = zf.testzip()
    if bad:
        raise SystemExit(f"bad zip member: {bad}")
    roots = {name.split("/", 1)[0] for name in zf.namelist() if name and not name.endswith("/")}
    if len(roots) != 1:
        raise SystemExit(f"expected exactly one top-level directory, got: {sorted(roots)}")
    print(next(iter(roots)))
PY
}

verify_aar() {
  local aar_path="$1"
  python3 - "$aar_path" <<'PY'
import sys
import zipfile
from pathlib import Path

path = Path(sys.argv[1])
required = {
    "classes.jar",
    "proguard.txt",
    "libs/onnxruntime-android-1.24.3-classes.jar",
    "jni/arm64-v8a/libonnxruntime.so",
    "jni/arm64-v8a/libonnxruntime4j_jni.so",
    "assets/lits-models/tts/lits_delivery_16k_hifigan/1.0.0/manifest.json",
    "assets/lits-models/tts/lits_delivery_16k_hifigan/1.0.0/lits_acoustic.onnx",
    "assets/lits-models/tts/lits_delivery_16k_hifigan/1.0.0/hifigan_vocoder.onnx",
}
with zipfile.ZipFile(path) as zf:
    names = set(zf.namelist())
missing = sorted(required - names)
if missing:
    raise SystemExit("AAR missing required entries: " + ", ".join(missing))
PY
  ok "AAR content verified: $aar_path"
}

verify_sample_apk() {
  local apk_path="$1"
  python3 - "$apk_path" <<'PY'
import sys
import zipfile
from pathlib import Path

path = Path(sys.argv[1])
required = {
    "assets/lits-models/tts/lits_delivery_16k_hifigan/1.0.0/manifest.json",
    "assets/lits-models/tts/lits_delivery_16k_hifigan/1.0.0/lits_acoustic.onnx",
    "assets/lits-models/tts/lits_delivery_16k_hifigan/1.0.0/hifigan_vocoder.onnx",
    "lib/arm64-v8a/libonnxruntime.so",
    "lib/arm64-v8a/libonnxruntime4j_jni.so",
}
with zipfile.ZipFile(path) as zf:
    names = set(zf.namelist())
missing = sorted(required - names)
if missing:
    raise SystemExit("sample APK missing required entries: " + ", ".join(missing))
PY
  ok "sample APK content verified: $apk_path"
}

get_field() {
  local key="$1"
  local file="$2"
  awk -F= -v key="$key" '$1 == key { sub(/^[^=]*=/, ""); print; exit }' "$file"
}

verify_version_txt() {
  local version_file="$1"
  local package_id commit_full delivery_version source_dir
  package_id="$(get_field package "$version_file")"
  commit_full="$(get_field git_commit_full "$version_file")"
  delivery_version="$(get_field delivery_version "$version_file")"
  source_dir="$(get_field android_source_dir "$version_file")"

  [[ "$package_id" == "lits-tts-android-sdk" ]] || fail "unexpected package=$package_id"
  [[ -n "$delivery_version" ]] || fail "VERSION.txt missing delivery_version"
  [[ -n "$source_dir" ]] || fail "VERSION.txt missing android_source_dir"
  [[ -n "$commit_full" ]] || fail "VERSION.txt missing git_commit_full"
  git -C "$REPO_ROOT" cat-file -e "$commit_full" 2>/dev/null || \
    fail "git_commit_full=$commit_full not found locally"

  echo "--- $version_file ---"
  sed -n '1,120p' "$version_file"
  ok "VERSION.txt consistent with local git repo"
}

verify_source_tree() {
  local source_root="$1"
  [[ -f "$source_root/android/TtsRuntime/sdk/build.gradle.kts" ]] || \
    fail "missing Android SDK source build.gradle.kts"
  [[ -f "$source_root/android/TtsRuntime/sdk/src/main/java/com/lits/tts/sdk/TextToSpeechApi.kt" ]] || \
    fail "missing TextToSpeechApi.kt"
  [[ -f "$source_root/tools/tts/verify_lits_delivery_16k_package.py" ]] || \
    fail "missing Android model verifier"
  [[ -f "$source_root/tools/tts/license/issue_license.py" ]] || \
    fail "missing license tooling"
  [[ -f "$source_root/tools/tts/trial-export/lits_delivery_16k_hifigan/1.0.0/manifest.json" ]] || \
    fail "missing staged model package in Android source tree"

  python3 - "$source_root" <<'PY'
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
bad = []
for path in root.rglob("*"):
    rel = path.relative_to(root).as_posix()
    if path.is_dir():
        if rel.endswith("/build") or "/build/" in f"/{rel}/" or rel.endswith("/.gradle") or "/.gradle/" in f"/{rel}/":
            bad.append(rel)
        continue
    if path.name == "local.properties" or path.suffix == ".pem":
        bad.append(rel)
    if rel.startswith("android/TtsRuntime/sdk/src/main/assets/"):
        bad.append(rel)
if bad:
    raise SystemExit("source tree contains forbidden files: " + ", ".join(sorted(bad)[:20]))
PY
  ok "Android source tree verified: $source_root"
}

if [[ -f "$TARGET" && "$TARGET" == *.aar ]]; then
  verify_aar "$TARGET"
  exit 0
fi

if [[ -f "$TARGET" && "$TARGET" == *.zip ]]; then
  verify_zip "$TARGET" >/dev/null
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  unzip -q "$TARGET" -d "$tmp"
  entries=("$tmp"/*)
  [[ "${#entries[@]}" -eq 1 && -d "${entries[0]}" ]] || fail "zip must contain exactly one delivery directory"
  bash "$0" "${entries[0]}"
  ok "zip verified: $TARGET"
  exit 0
fi

if [[ -d "$TARGET" ]]; then
  [[ -f "$TARGET/VERSION.txt" ]] || fail "missing VERSION.txt"
  verify_version_txt "$TARGET/VERSION.txt"
  aar_files=("$TARGET"/aar/*.aar)
  [[ "${#aar_files[@]}" -eq 1 && -f "${aar_files[0]}" ]] || fail "expected exactly one aar/*.aar"
  verify_aar "${aar_files[0]}"
  [[ -f "$TARGET/demo/lits-tts-sample-debug.apk" ]] || fail "missing demo/lits-tts-sample-debug.apk"
  verify_sample_apk "$TARGET/demo/lits-tts-sample-debug.apk"
  [[ -f "$TARGET/docs/NOTICE" ]] || fail "missing docs/NOTICE"
  ok "docs/NOTICE present"
  verify_source_tree "$TARGET/android-src/TTS"
  exit 0
fi

[[ -f "$TARGET" ]] || fail "not found: $TARGET"
verify_version_txt "$TARGET"
