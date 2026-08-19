#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 <16k-wav-dir> <new-output-dir> [abba-cycles]" >&2
  echo "required env: AUDIO_ASSET (basename of one wav under 16k-wav-dir)" >&2
  echo "optional env: ANDROID_SERIAL, DINGQIAO_DEMO_ASSET_DIR, PERF_ALLOW_DIRTY=1" >&2
  exit 2
}

[[ $# -ge 2 && $# -le 3 ]] || usage

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../../../.." && pwd)
ANDROID_ROOT="$REPO_ROOT/asr/android"
AUDIO_DIR=$(cd "$1" && pwd)
OUTPUT_DIR=$2
CYCLES=${3:-2}

[[ "$CYCLES" =~ ^[1-9][0-9]*$ ]] || usage
: "${AUDIO_ASSET:?set AUDIO_ASSET to the exact wav basename used by every ABBA run}"
if [[ "$AUDIO_ASSET" == */* || "$AUDIO_ASSET" == *$'\n'* ]]; then
  echo "AUDIO_ASSET must be one basename without path separators or newlines" >&2
  exit 1
fi
command -v adb >/dev/null
command -v python3 >/dev/null
command -v shasum >/dev/null
[[ -d "$AUDIO_DIR" ]]
[[ -f "$AUDIO_DIR/$AUDIO_ASSET" ]] || {
  echo "AUDIO_ASSET is not a file directly under the input directory: $AUDIO_ASSET" >&2
  exit 1
}

if [[ -e "$OUTPUT_DIR" ]]; then
  echo "output path already exists; choose a new path: $OUTPUT_DIR" >&2
  exit 1
fi

WORKTREE_DIRTY=false
if [[ -n "$(git -C "$REPO_ROOT" status --porcelain --untracked-files=all)" ]]; then
  WORKTREE_DIRTY=true
  if [[ "${PERF_ALLOW_DIRTY:-0}" != "1" ]]; then
    echo "formal performance runs require a clean worktree (or PERF_ALLOW_DIRTY=1)" >&2
    exit 1
  fi
fi

mkdir -p "$OUTPUT_DIR/artifacts/audio" "$OUTPUT_DIR/artifacts/model" "$OUTPUT_DIR/runs"
OUTPUT_DIR=$(cd "$OUTPUT_DIR" && pwd)

ADB=(adb)
if [[ -n "${ANDROID_SERIAL:-}" ]]; then
  ADB+=(-s "$ANDROID_SERIAL")
fi

APP_ID=com.amphion.dingqiao.demo
TEST_APP_ID=com.amphion.dingqiao.demo.test
RUNNER="$TEST_APP_ID/androidx.test.runner.AndroidJUnitRunner"
TEST_TARGET=com.amphion.dingqiao.demo.DqPoliceHotwordPerformanceInstrumentedTest#measureCompiledDefaultProfile
TARGET_APK="$ANDROID_ROOT/samples/dingqiao-demo/build/outputs/apk/debug/dingqiao-demo-debug.apk"
TEST_APK="$ANDROID_ROOT/samples/dingqiao-demo/build/outputs/apk/androidTest/debug/dingqiao-demo-debug-androidTest.apk"
GIT_SHA=$(git -C "$REPO_ROOT" rev-parse HEAD)
MODEL_MANIFEST="$ANDROID_ROOT/sdk/src/main/assets/amphion-models/manifest.json"
[[ -f "$MODEL_MANIFEST" ]]
git -C "$REPO_ROOT" status --porcelain --untracked-files=all > "$OUTPUT_DIR/git-status.txt"
cp "$AUDIO_DIR/$AUDIO_ASSET" "$OUTPUT_DIR/artifacts/audio/input.wav"
cp "$MODEL_MANIFEST" "$OUTPUT_DIR/artifacts/model/manifest.json"
(
  cd "$REPO_ROOT"
  shasum -a 256 \
    asr/android/sdk-police/build.gradle.kts \
    asr/android/sdk-police/src/main/java/com/amphion/police/PoliceEngineConfig.kt \
    asr/android/sdk-police/src/main/java/com/amphion/police/PoliceHotwordProfile.kt \
    asr/android/sdk-police/src/main/java/com/amphion/police/PoliceHotwordPruningCandidates.kt
) > "$OUTPUT_DIR/artifacts/profile-source-sha256.txt"
AUDIO_SHA256=$(shasum -a 256 "$OUTPUT_DIR/artifacts/audio/input.wav" | awk '{print $1}')
MODEL_MANIFEST_SHA256=$(shasum -a 256 "$OUTPUT_DIR/artifacts/model/manifest.json" | awk '{print $1}')
GIT_STATUS_SHA256=$(shasum -a 256 "$OUTPUT_DIR/git-status.txt" | awk '{print $1}')
PROFILE_SOURCE_SHA256=$(shasum -a 256 "$OUTPUT_DIR/artifacts/profile-source-sha256.txt" | awk '{print $1}')

{
  echo "git_sha=$GIT_SHA"
  echo "worktree_dirty=$WORKTREE_DIRTY"
  echo "git_status_sha256=$GIT_STATUS_SHA256"
  echo "audio_dir=$AUDIO_DIR"
  echo "audio_asset=$AUDIO_ASSET"
  echo "audio_evidence=artifacts/audio/input.wav"
  echo "audio_sha256=$AUDIO_SHA256"
  echo "model_manifest_evidence=artifacts/model/manifest.json"
  echo "model_manifest_sha256=$MODEL_MANIFEST_SHA256"
  echo "profile_source_evidence=artifacts/profile-source-sha256.txt"
  echo "profile_source_sha256=$PROFILE_SOURCE_SHA256"
  echo "abba_cycles=$CYCLES"
  echo "android_serial=${ANDROID_SERIAL:-adb-default}"
} > "$OUTPUT_DIR/run-manifest.txt"

"${ADB[@]}" get-state > "$OUTPUT_DIR/device-state.txt"
"${ADB[@]}" devices -l > "$OUTPUT_DIR/adb-devices.txt"
"${ADB[@]}" shell getprop > "$OUTPUT_DIR/device-getprop.txt"
"${ADB[@]}" shell cat /proc/cpuinfo > "$OUTPUT_DIR/device-cpuinfo.txt"

build_profile() {
  local profile=$1
  local artifact_dir="$OUTPUT_DIR/artifacts/$profile"
  local gradle_args=(
    --no-daemon
    --console=plain
    :sdk-police:clean
    :sdk-dingqiao:clean
    :samples:dingqiao-demo:clean
    :samples:dingqiao-demo:assembleDebug
    :samples:dingqiao-demo:assembleDebugAndroidTest
    "-PpoliceDefaultHotwordProfile=$profile"
    "-PdingqiaoEvalAudioDir=$AUDIO_DIR"
    "-PdingqiaoUseFatAar=false"
  )
  if [[ -n "${DINGQIAO_DEMO_ASSET_DIR:-}" ]]; then
    gradle_args+=("-PdingqiaoDemoAssetDir=$DINGQIAO_DEMO_ASSET_DIR")
  fi
  mkdir -p "$artifact_dir"

  (
    cd "$ANDROID_ROOT"
    ./gradlew "${gradle_args[@]}"
  ) > "$artifact_dir/build.log" 2>&1

  [[ -f "$TARGET_APK" && -f "$TEST_APK" ]]
  cp "$TARGET_APK" "$artifact_dir/target.apk"
  cp "$TEST_APK" "$artifact_dir/test.apk"
  local target_apk_sha256
  local test_apk_sha256
  target_apk_sha256=$(shasum -a 256 "$artifact_dir/target.apk" | awk '{print $1}')
  test_apk_sha256=$(shasum -a 256 "$artifact_dir/test.apk" | awk '{print $1}')
  {
    echo "profile=$profile"
    echo "git_sha=$GIT_SHA"
    echo "worktree_dirty=$WORKTREE_DIRTY"
    echo "git_status_sha256=$GIT_STATUS_SHA256"
    echo "audio_asset=$AUDIO_ASSET"
    echo "audio_sha256=$AUDIO_SHA256"
    echo "model_manifest_sha256=$MODEL_MANIFEST_SHA256"
    echo "profile_source_sha256=$PROFILE_SOURCE_SHA256"
    echo "target_apk_sha256=$target_apk_sha256"
    echo "test_apk_sha256=$test_apk_sha256"
  } > "$artifact_dir/manifest.txt"
}

build_profile full
build_profile prune_ui28

run_one() {
  local cycle=$1
  local position=$2
  local profile=$3
  local run_id
  run_id=$(printf 'c%02d-p%02d-%s' "$cycle" "$position" "$profile")
  local run_dir="$OUTPUT_DIR/runs/$run_id"
  local artifact_dir="$OUTPUT_DIR/artifacts/$profile"
  local artifact_manifest_sha256
  local target_apk_sha256
  local test_apk_sha256
  artifact_manifest_sha256=$(shasum -a 256 "$artifact_dir/manifest.txt" | awk '{print $1}')
  target_apk_sha256=$(awk -F= '$1 == "target_apk_sha256" { print $2 }' "$artifact_dir/manifest.txt")
  test_apk_sha256=$(awk -F= '$1 == "test_apk_sha256" { print $2 }' "$artifact_dir/manifest.txt")
  mkdir -p "$run_dir"

  {
    echo "run_id=$run_id"
    echo "cycle=$cycle"
    echo "position=$position"
    echo "profile=$profile"
    echo "git_sha=$GIT_SHA"
    echo "worktree_dirty=$WORKTREE_DIRTY"
    echo "git_status_sha256=$GIT_STATUS_SHA256"
    echo "audio_asset=$AUDIO_ASSET"
    echo "audio_sha256=$AUDIO_SHA256"
    echo "model_manifest_sha256=$MODEL_MANIFEST_SHA256"
    echo "profile_source_sha256=$PROFILE_SOURCE_SHA256"
    echo "artifact_manifest_sha256=$artifact_manifest_sha256"
    echo "target_apk_sha256=$target_apk_sha256"
    echo "test_apk_sha256=$test_apk_sha256"
  } > "$run_dir/meta.txt"

  "${ADB[@]}" install -r -t "$artifact_dir/target.apk" > "$run_dir/install-target.txt" 2>&1
  "${ADB[@]}" install -r -t "$artifact_dir/test.apk" > "$run_dir/install-test.txt" 2>&1
  "${ADB[@]}" shell am force-stop "$APP_ID" > "$run_dir/force-stop-target-before.txt" 2>&1
  "${ADB[@]}" shell am force-stop "$TEST_APP_ID" > "$run_dir/force-stop-test-before.txt" 2>&1 || true
  "${ADB[@]}" shell run-as "$APP_ID" rm -rf files/police_hotword_perf \
    > "$run_dir/clean-perf-before.txt" 2>&1
  "${ADB[@]}" shell cmd package compile -m speed -f "$APP_ID" > "$run_dir/compile-target.txt" 2>&1 || true
  "${ADB[@]}" shell cmd package compile -m speed -f "$TEST_APP_ID" > "$run_dir/compile-test.txt" 2>&1 || true
  "${ADB[@]}" shell dumpsys battery > "$run_dir/battery-before.txt" 2>&1 || true
  "${ADB[@]}" shell dumpsys thermalservice > "$run_dir/thermal-before.txt" 2>&1 || true
  "${ADB[@]}" logcat -c

  local instrument_args=(
    shell am instrument -w -r
    -e class "$TEST_TARGET"
    -e runId "$run_id"
    -e expectedProfile "$profile"
  )
  instrument_args+=(-e audioAsset "$AUDIO_ASSET")
  instrument_args+=("$RUNNER")

  set +e
  "${ADB[@]}" "${instrument_args[@]}" > "$run_dir/instrument.txt" 2>&1
  local instrument_status=$?
  set -e
  echo "$instrument_status" > "$run_dir/instrument-exit-code.txt"

  "${ADB[@]}" logcat -d -v epoch \
    'AmphionMetrics:I' 'AmphionRuntime:V' 'DqPoliceHotwordPerf:I' '*:S' \
    > "$run_dir/metrics.log" 2>&1 || true
  "${ADB[@]}" exec-out run-as "$APP_ID" cat files/police_hotword_perf/report.jsonl \
    > "$run_dir/report.jsonl" 2> "$run_dir/report-pull-error.txt" || true
  "${ADB[@]}" shell dumpsys battery > "$run_dir/battery-after.txt" 2>&1 || true
  "${ADB[@]}" shell dumpsys thermalservice > "$run_dir/thermal-after.txt" 2>&1 || true
  "${ADB[@]}" shell am force-stop "$APP_ID" > "$run_dir/force-stop-target-after.txt" 2>&1
  "${ADB[@]}" shell am force-stop "$TEST_APP_ID" > "$run_dir/force-stop-test-after.txt" 2>&1 || true
  "${ADB[@]}" shell run-as "$APP_ID" rm -rf files/police_hotword_perf \
    > "$run_dir/clean-perf-after.txt" 2>&1
}

for ((cycle = 1; cycle <= CYCLES; cycle++)); do
  position=0
  for profile in full prune_ui28 prune_ui28 full; do
    position=$((position + 1))
    run_one "$cycle" "$position" "$profile"
  done
done

git -C "$REPO_ROOT" status --porcelain --untracked-files=all > "$OUTPUT_DIR/git-status-after.txt"
echo "git_status_after_sha256=$(shasum -a 256 "$OUTPUT_DIR/git-status-after.txt" | awk '{print $1}')" \
  >> "$OUTPUT_DIR/run-manifest.txt"

python3 "$SCRIPT_DIR/analyze_police_hotword_perf_abba.py" "$OUTPUT_DIR"
echo "[PASS] ABBA artifacts and summary: $OUTPUT_DIR"
