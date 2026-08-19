#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 <new-output-dir> [abba-cycles]" >&2
  echo "abba-cycles must be at least 5 (default: 5)" >&2
  echo "optional env: ANDROID_SERIAL, PERF_ALLOW_DIRTY=1" >&2
  exit 2
}

[[ $# -ge 1 && $# -le 2 ]] || usage

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/../../../.." && pwd)
ANDROID_ROOT="$REPO_ROOT/asr/android"
OUTPUT_ARG=$1
CYCLES=${2:-5}

[[ "$CYCLES" =~ ^[0-9]+$ ]] || usage
(( CYCLES >= 5 )) || usage
command -v adb >/dev/null
command -v python3 >/dev/null
command -v shasum >/dev/null

OUTPUT_PARENT=$(dirname "$OUTPUT_ARG")
OUTPUT_NAME=$(basename "$OUTPUT_ARG")
[[ -d "$OUTPUT_PARENT" && -n "$OUTPUT_NAME" && "$OUTPUT_NAME" != "." ]] || {
  echo "output parent must already exist and output must name a new directory" >&2
  exit 1
}
OUTPUT_PARENT=$(cd "$OUTPUT_PARENT" && pwd)
OUTPUT_DIR="$OUTPUT_PARENT/$OUTPUT_NAME"
case "$OUTPUT_DIR/" in
  "$REPO_ROOT/"*)
    echo "evidence output must be outside the Git worktree: $OUTPUT_DIR" >&2
    exit 1
    ;;
esac
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

mkdir -p "$OUTPUT_DIR/artifacts/model" "$OUTPUT_DIR/runs"

ADB=(adb)
if [[ -n "${ANDROID_SERIAL:-}" ]]; then
  ADB+=(-s "$ANDROID_SERIAL")
fi

APP_ID=com.amphion.dingqiao.demo
TEST_APP_ID=com.amphion.dingqiao.demo.test
RUNNER="$TEST_APP_ID/com.amphion.dingqiao.demo.DqCreateOnlyPerfRunner"
TEST_TARGET=com.amphion.dingqiao.demo.DqPoliceHotwordCreateOnlyPerformanceInstrumentedTest#measureOneIsolatedPrepareAndCreate
TARGET_APK="$ANDROID_ROOT/samples/dingqiao-demo/build/outputs/apk/debug/dingqiao-demo-debug.apk"
TEST_APK="$ANDROID_ROOT/samples/dingqiao-demo/build/outputs/apk/androidTest/debug/dingqiao-demo-debug-androidTest.apk"
DEVICE_PERF_ROOT=files/police_hotword_create_only_perf
GIT_SHA=$(git -C "$REPO_ROOT" rev-parse HEAD)
MODEL_MANIFEST="$ANDROID_ROOT/sdk/src/main/assets/amphion-models/manifest.json"
ANALYZER="$SCRIPT_DIR/analyze_police_hotword_create_only_abba.py"
[[ -f "$MODEL_MANIFEST" && -f "$ANALYZER" ]]

git -C "$REPO_ROOT" status --porcelain --untracked-files=all > "$OUTPUT_DIR/git-status.txt"
cp "$MODEL_MANIFEST" "$OUTPUT_DIR/artifacts/model/manifest.json"
(
  cd "$REPO_ROOT"
  shasum -a 256 \
    asr/android/sdk-police/build.gradle.kts \
    asr/android/sdk-police/src/main/java/com/amphion/police/PoliceEngineConfig.kt \
    asr/android/sdk-police/src/main/java/com/amphion/police/PoliceHotwordProfile.kt \
    asr/android/sdk-police/src/main/java/com/amphion/police/PoliceHotwordPruningCandidates.kt \
    asr/android/samples/dingqiao-demo/build.gradle.kts \
    asr/android/samples/dingqiao-demo/src/androidTest/java/com/amphion/dingqiao/demo/DqCreateOnlyPerfRunner.kt \
    asr/android/samples/dingqiao-demo/src/androidTest/java/com/amphion/dingqiao/demo/DqPoliceHotwordCreateOnlyPerformanceInstrumentedTest.kt \
    asr/android/reports/police-hotword-pruning-iter250-20260819/run_police_hotword_create_only_abba.sh \
    asr/android/reports/police-hotword-pruning-iter250-20260819/analyze_police_hotword_create_only_abba.py
) > "$OUTPUT_DIR/artifacts/profile-source-sha256.txt"
MODEL_MANIFEST_SHA256=$(shasum -a 256 "$OUTPUT_DIR/artifacts/model/manifest.json" | awk '{print $1}')
GIT_STATUS_SHA256=$(shasum -a 256 "$OUTPUT_DIR/git-status.txt" | awk '{print $1}')
PROFILE_SOURCE_SHA256=$(shasum -a 256 "$OUTPUT_DIR/artifacts/profile-source-sha256.txt" | awk '{print $1}')

{
  echo "schema_version=1"
  echo "case=police-hotword-create-only-abba"
  echo "git_sha=$GIT_SHA"
  echo "worktree_dirty=$WORKTREE_DIRTY"
  echo "git_status_sha256=$GIT_STATUS_SHA256"
  echo "source_build=true"
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

expected_count() {
  case "$1" in
    full) echo 370 ;;
    prune_ui28) echo 342 ;;
    *) return 1 ;;
  esac
}

build_profile() {
  local profile=$1
  local count
  count=$(expected_count "$profile")
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
    "-PdingqiaoUseFatAar=false"
    "-PdingqiaoCreateOnlyPerfRunner=true"
  )
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
  local model_payload_sha256
  target_apk_sha256=$(shasum -a 256 "$artifact_dir/target.apk" | awk '{print $1}')
  test_apk_sha256=$(shasum -a 256 "$artifact_dir/test.apk" | awk '{print $1}')
  model_payload_sha256=$(
    python3 "$ANALYZER" --print-model-payload-hash \
      "$artifact_dir/target.apk" "$OUTPUT_DIR/artifacts/model/manifest.json"
  )
  {
    echo "profile=$profile"
    echo "expected_count=$count"
    echo "git_sha=$GIT_SHA"
    echo "worktree_dirty=$WORKTREE_DIRTY"
    echo "git_status_sha256=$GIT_STATUS_SHA256"
    echo "source_build=true"
    echo "model_manifest_sha256=$MODEL_MANIFEST_SHA256"
    echo "model_payload_sha256=$model_payload_sha256"
    echo "profile_source_sha256=$PROFILE_SOURCE_SHA256"
    echo "target_apk_sha256=$target_apk_sha256"
    echo "test_apk_sha256=$test_apk_sha256"
  } > "$artifact_dir/manifest.txt"
}

build_profile full
build_profile prune_ui28

clean_create_only_state() {
  # Exact app-private test root only. Never clear package data, remove packages, or touch Demo
  # preferences, databases, external files or the normal dingqiao_work directory.
  [[ "$DEVICE_PERF_ROOT" == "files/police_hotword_create_only_perf" ]]
  "${ADB[@]}" shell run-as "$APP_ID" rm -rf "$DEVICE_PERF_ROOT"
}

run_one() {
  local cycle=$1
  local position=$2
  local profile=$3
  local count
  count=$(expected_count "$profile")
  local run_id
  run_id=$(printf 'c%02d-p%02d-%s' "$cycle" "$position" "$profile")
  local run_dir="$OUTPUT_DIR/runs/$run_id"
  local artifact_dir="$OUTPUT_DIR/artifacts/$profile"
  local artifact_manifest_sha256
  local target_apk_sha256
  local test_apk_sha256
  local model_payload_sha256
  artifact_manifest_sha256=$(shasum -a 256 "$artifact_dir/manifest.txt" | awk '{print $1}')
  target_apk_sha256=$(awk -F= '$1 == "target_apk_sha256" { print $2 }' "$artifact_dir/manifest.txt")
  test_apk_sha256=$(awk -F= '$1 == "test_apk_sha256" { print $2 }' "$artifact_dir/manifest.txt")
  model_payload_sha256=$(awk -F= '$1 == "model_payload_sha256" { print $2 }' "$artifact_dir/manifest.txt")
  mkdir -p "$run_dir"

  {
    echo "run_id=$run_id"
    echo "cycle=$cycle"
    echo "position=$position"
    echo "profile=$profile"
    echo "expected_count=$count"
    echo "git_sha=$GIT_SHA"
    echo "worktree_dirty=$WORKTREE_DIRTY"
    echo "git_status_sha256=$GIT_STATUS_SHA256"
    echo "source_build=true"
    echo "model_manifest_sha256=$MODEL_MANIFEST_SHA256"
    echo "model_payload_sha256=$model_payload_sha256"
    echo "profile_source_sha256=$PROFILE_SOURCE_SHA256"
    echo "artifact_manifest_sha256=$artifact_manifest_sha256"
    echo "target_apk_sha256=$target_apk_sha256"
    echo "test_apk_sha256=$test_apk_sha256"
  } > "$run_dir/meta.txt"

  "${ADB[@]}" install -r -t "$artifact_dir/target.apk" > "$run_dir/install-target.txt" 2>&1
  "${ADB[@]}" install -r -t "$artifact_dir/test.apk" > "$run_dir/install-test.txt" 2>&1
  "${ADB[@]}" shell pm path "$APP_ID" > "$run_dir/installed-target-path.txt" 2>&1
  "${ADB[@]}" shell pm path "$TEST_APP_ID" > "$run_dir/installed-test-path.txt" 2>&1
  "${ADB[@]}" shell am force-stop "$APP_ID" > "$run_dir/force-stop-target-before.txt" 2>&1
  "${ADB[@]}" shell am force-stop "$TEST_APP_ID" > "$run_dir/force-stop-test-before.txt" 2>&1 || true
  clean_create_only_state > "$run_dir/clean-create-only-before.txt" 2>&1
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
    -e expectedCount "$count"
    -e targetApkSha256 "$target_apk_sha256"
    -e testApkSha256 "$test_apk_sha256"
    -e modelManifestSha256 "$MODEL_MANIFEST_SHA256"
    -e modelPayloadSha256 "$model_payload_sha256"
    "$RUNNER"
  )

  set +e
  "${ADB[@]}" "${instrument_args[@]}" > "$run_dir/instrument.txt" 2>&1
  local instrument_status=$?
  set -e
  echo "$instrument_status" > "$run_dir/instrument-exit-code.txt"

  "${ADB[@]}" logcat -d -v epoch \
    'AmphionMetrics:I' 'AmphionRuntime:V' 'DqPoliceCreateOnlyPerf:I' '*:S' \
    > "$run_dir/metrics.log" 2>&1 || true
  "${ADB[@]}" exec-out run-as "$APP_ID" \
    cat "$DEVICE_PERF_ROOT/report.jsonl" \
    > "$run_dir/report.jsonl" 2> "$run_dir/report-pull-error.txt" || true
  "${ADB[@]}" shell dumpsys battery > "$run_dir/battery-after.txt" 2>&1 || true
  "${ADB[@]}" shell dumpsys thermalservice > "$run_dir/thermal-after.txt" 2>&1 || true
  "${ADB[@]}" shell am force-stop "$APP_ID" > "$run_dir/force-stop-target-after.txt" 2>&1
  "${ADB[@]}" shell am force-stop "$TEST_APP_ID" > "$run_dir/force-stop-test-after.txt" 2>&1 || true
  clean_create_only_state > "$run_dir/clean-create-only-after.txt" 2>&1
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

python3 "$ANALYZER" "$OUTPUT_DIR"
echo "[VALID] create-only ABBA artifacts and summary: $OUTPUT_DIR"
