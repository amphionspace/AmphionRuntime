#!/usr/bin/env bash
# 把 build/push/（metadata.jsonl + wavs/）推到真机 batch-eval 目录，并清理本批 progress。
# 依赖：先跑 build_cases.py 生成 build/push/。
#
# 用法：
#   ./push_batch_eval.sh                 # 推送 + 清 progress（保留旧输出 tsv）
#   ./push_batch_eval.sh --archive-old   # 推送前把设备上旧的 police_terms_eval.tsv 拉回 _archive/
set -euo pipefail

PKG=com.amphion.asr.sample
BASE=/sdcard/Android/data/$PKG/files
BATCH_DIR=$BASE/batch-eval
EVAL_DIR=$BASE/police-terms-eval
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PUSH_DIR="$HERE/build/push"

ARCHIVE_OLD=0
[[ "${1:-}" == "--archive-old" ]] && ARCHIVE_OLD=1

command -v adb >/dev/null || { echo "[push] 找不到 adb"; exit 1; }
adb get-state >/dev/null 2>&1 || { echo "[push] 无设备连接（adb devices 检查）"; exit 1; }
[[ -f "$PUSH_DIR/metadata.jsonl" ]] || { echo "[push] 缺 $PUSH_DIR/metadata.jsonl，先跑 build_cases.py"; exit 1; }
[[ -d "$PUSH_DIR/wavs" ]] || { echo "[push] 缺 $PUSH_DIR/wavs/，先跑 build_cases.py"; exit 1; }

WAV_COUNT=$(find "$PUSH_DIR/wavs" -name '*.wav' | wc -l | tr -d ' ')
echo "[push] 待推送 wav: $WAV_COUNT 条"

if [[ $ARCHIVE_OLD -eq 1 ]]; then
  if adb shell "[ -f $EVAL_DIR/police_terms_eval.tsv ]"; then
    STAMP=$(date +%Y%m%d_%H%M%S)
    mkdir -p "$HERE/_archive"
    echo "[push] 归档设备旧输出 -> _archive/police_terms_eval_$STAMP.tsv"
    adb pull "$EVAL_DIR/police_terms_eval.tsv" "$HERE/_archive/police_terms_eval_$STAMP.tsv"
  fi
fi

echo "[push] 清理设备旧 batch-eval/wavs 与 metadata …"
adb shell "rm -rf $BATCH_DIR/wavs $BATCH_DIR/metadata.jsonl $BATCH_DIR/batch_eval_terms_progress.txt"
adb shell "mkdir -p $BATCH_DIR"

echo "[push] 推送 metadata.jsonl …"
adb push "$PUSH_DIR/metadata.jsonl" "$BATCH_DIR/metadata.jsonl" >/dev/null

echo "[push] 推送 wavs/（$WAV_COUNT 条，可能耗时）…"
adb push "$PUSH_DIR/wavs" "$BATCH_DIR/" >/dev/null

REMOTE_WAVS=$(adb shell "ls $BATCH_DIR/wavs | wc -l" | tr -d '\r ')
REMOTE_META=$(adb shell "wc -l < $BATCH_DIR/metadata.jsonl" | tr -d '\r ')
echo "[push] 设备端 wavs=$REMOTE_WAVS  metadata 行数=$REMOTE_META"
if [[ "$REMOTE_WAVS" != "$WAV_COUNT" ]]; then
  echo "[push][warn] 设备 wav 数($REMOTE_WAVS) != 本地($WAV_COUNT)，请检查"
fi
echo "[push] 完成。下一步：./run_batch.sh [category]"
