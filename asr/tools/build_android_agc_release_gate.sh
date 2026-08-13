#!/usr/bin/env bash
# Build and verify the Android AGC AAR in an isolated clone of the current commit.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SOURCE_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"
SHERPA_COMMIT="$(git -C "$REPO_ROOT/third_party/sherpa-onnx" rev-parse HEAD)"
OUTPUT_ROOT="${1:-$REPO_ROOT/asr/android/build/automatic-agc-release/$SOURCE_COMMIT}"
TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/amphion-android-agc-release.XXXXXX")"
CLONE_ROOT="$TEMP_ROOT/repo"

cleanup() {
  rm -rf "$TEMP_ROOT"
}
trap cleanup EXIT

if [[ -e "$OUTPUT_ROOT" ]]; then
  echo "[ERROR] Android release-gate output already exists: $OUTPUT_ROOT" >&2
  exit 1
fi

git clone --quiet --no-checkout --shared "$REPO_ROOT" "$CLONE_ROOT"
git -C "$CLONE_ROOT" checkout --quiet --detach "$SOURCE_COMMIT"
# Android ASR consumes only sherpa-onnx. Avoid coupling this gate to unrelated private
# submodules, which can fail before any Android product code is built or tested.
git -C "$CLONE_ROOT" submodule update --init --recursive third_party/sherpa-onnx

bash "$CLONE_ROOT/asr/tools/03_build_agc_native.sh" android-arm64-v8a
bash "$CLONE_ROOT/asr/tools/04_build_android_so.sh" arm64-v8a
AMPHION_REQUIRE_ANDROID_NATIVE_LIBS=1 \
  bash "$CLONE_ROOT/asr/tools/05_package_aar_libs.sh" arm64-v8a

(
  cd "$CLONE_ROOT/asr/android"
  ./gradlew --no-daemon \
    :sdk:assembleRelease \
    :sdk:testDebugUnitTest \
    :sdk:testReleaseUnitTest \
    :sdk-dingqiao:testDebugUnitTest \
    :sdk-dingqiao:testReleaseUnitTest \
    --rerun-tasks \
    --console=plain
)

AAR="$CLONE_ROOT/asr/android/sdk/build/outputs/aar/sdk-release.aar"
AGC_SO="$CLONE_ROOT/asr/native/audio-processing/build-android-arm64-v8a/libamphion_audio_processing.so"
[[ -s "$AAR" && -s "$AGC_SO" ]] || {
  echo "[ERROR] Android release build did not produce the AAR and AGC runtime" >&2
  exit 1
}

mkdir -p "$OUTPUT_ROOT/sdk/build/outputs/aar"
cp "$AAR" "$OUTPUT_ROOT/sdk/build/outputs/aar/sdk-release.aar"
for module in sdk sdk-dingqiao; do
  for variant in testDebugUnitTest testReleaseUnitTest; do
    source_dir="$CLONE_ROOT/asr/android/$module/build/test-results/$variant"
    target_dir="$OUTPUT_ROOT/$module/build/test-results/$variant"
    mkdir -p "$target_dir"
    cp "$source_dir"/TEST-*.xml "$target_dir/"
  done
done

python3 - "$AAR" "$AGC_SO" <<'PY'
import hashlib
import sys
import zipfile

aar, expected_path = sys.argv[1:]
with open(expected_path, "rb") as stream:
    expected = hashlib.sha256(stream.read()).hexdigest()
with zipfile.ZipFile(aar) as archive:
    required = {
        "jni/arm64-v8a/libsherpa-onnx-jni.so",
        "jni/arm64-v8a/libonnxruntime.so",
        "jni/arm64-v8a/libamphion_audio_processing.so",
    }
    missing = required.difference(archive.namelist())
    if missing:
        raise SystemExit("AAR missing native runtime(s): " + ", ".join(sorted(missing)))
    actual = hashlib.sha256(
        archive.read("jni/arm64-v8a/libamphion_audio_processing.so")
    ).hexdigest()
if actual != expected:
    raise SystemExit("AAR contains an AGC runtime from a different build")
PY

python3 "$CLONE_ROOT/asr/tools/generate_android_test_summary.py" \
  --results-root "$OUTPUT_ROOT" \
  --source-commit "$SOURCE_COMMIT" \
  --sherpa-commit "$SHERPA_COMMIT" \
  --output "$OUTPUT_ROOT/android-tests.json"

echo "[OK] isolated Android AGC release gate: $OUTPUT_ROOT"
