#!/usr/bin/env bash
# 从真机拉回 police_terms_eval.tsv 到 asr/evaluation/police_terms/<round>/。
#
# 用法：
#   ./pull_eval.sh                # 默认拉到 round_baseline/
#   ./pull_eval.sh round1         # 拉到 round1/
#   ./pull_eval.sh round1 --analyze  # 拉完顺手跑 analyze
set -euo pipefail

PKG=com.amphion.asr.sample
BASE=/sdcard/Android/data/$PKG/files
EVAL_TSV=$BASE/police-terms-eval/police_terms_eval.tsv
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ROUND="${1:-round_baseline}"
ANALYZE=0
[[ "${2:-}" == "--analyze" ]] && ANALYZE=1

command -v adb >/dev/null || { echo "[pull] 找不到 adb"; exit 1; }
adb get-state >/dev/null 2>&1 || { echo "[pull] 无设备连接"; exit 1; }
adb shell "[ -f $EVAL_TSV ]" || { echo "[pull] 设备上没有 $EVAL_TSV，先 run_batch.sh"; exit 1; }

OUT_DIR="$HERE/$ROUND"
mkdir -p "$OUT_DIR"
echo "[pull] 拉取 -> $OUT_DIR/police_terms_eval.tsv"
adb pull "$EVAL_TSV" "$OUT_DIR/police_terms_eval.tsv"

ROWS=$(($(wc -l < "$OUT_DIR/police_terms_eval.tsv") - 1))
echo "[pull] 已拉回，数据行=$ROWS"

if [[ $ANALYZE -eq 1 ]]; then
  echo "[pull] 运行 analyze …"
  python3 "$HERE/analyze_police_terms_eval.py" "$OUT_DIR/police_terms_eval.tsv" --out "$OUT_DIR"
fi
