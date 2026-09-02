#!/usr/bin/env bash
# 推车牌数据集到真机 batch-eval/ 并拉起 PlateBatchEvalActivity。
# 用法：./push_run_plate.sh [DATA_DIR]
#   DATA_DIR 默认 <repo>/test_data/plate_number（须含 metadata.jsonl + wavs/）
set -euo pipefail

PKG=com.amphion.asr.sample
ACT=.plate.PlateBatchEvalActivity
FILTER=license_plate_v2
BASE=/sdcard/Android/data/$PKG/files
BATCH=$BASE/batch-eval
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${1:-$HERE/../../../test_data/plate_number}"

adb get-state >/dev/null 2>&1 || { echo "[plate] 无设备"; exit 1; }
[[ -f "$DATA_DIR/metadata.jsonl" && -d "$DATA_DIR/wavs" ]] || { echo "[plate] 缺 $DATA_DIR/metadata.jsonl 或 wavs/"; exit 1; }

N=$(find "$DATA_DIR/wavs" -name '*.wav' | wc -l | tr -d ' ')
echo "[plate] 推送 $N 条到 $BATCH"
adb shell "rm -rf $BATCH/wavs $BATCH/metadata.jsonl $BATCH/batch_eval_progress.txt; mkdir -p $BATCH"
adb push "$DATA_DIR/metadata.jsonl" "$BATCH/metadata.jsonl" >/dev/null
adb push "$DATA_DIR/wavs" "$BATCH/" >/dev/null
echo "[plate] 设备端 wavs=$(adb shell "ls $BATCH/wavs | wc -l" | tr -d '\r ')"

adb shell am force-stop "$PKG"; sleep 1
adb shell am start -n "$PKG/$ACT" --es filter "$FILTER" --ez auto_start true --ez fresh true >/dev/null
echo "[plate] 已启动。进度: adb shell 'logcat -s PlateBatchEvalAct:I'"
echo "[plate] 收结果: adb pull $BASE/plate-eval <round_dir>"
