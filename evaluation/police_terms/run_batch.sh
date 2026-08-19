#!/usr/bin/env bash
# 触发真机 PoliceTermsBatchEvalActivity 跑批量评测。
#
# 用法：
#   ./run_batch.sh              # 跑全部 4 类（fresh，重置输出 tsv + progress）
#   ./run_batch.sh appname      # 只跑「应用名称」类
#   ./run_batch.sh vocab        # 只跑「行业词汇」类
#   ./run_batch.sh dialog       # 只跑「行业对话」类
#   ./run_batch.sh specialcode  # 只跑「特殊代码」类
#   ./run_batch.sh all --resume # 跑全部但不 fresh（断点续跑，保留已完成）
#   ./run_batch.sh all --hotword-profile=none # iter250 裁剪诊断；不传则沿用设备偏好（通常为 full）
#
# 说明：fresh=true 会 reset 输出 tsv 并清 progress；--resume 关掉 fresh。
# 评测在设备端异步跑，本脚本只负责拉起；用 ./pull_eval.sh 观察/收结果。
set -euo pipefail

PKG=com.amphion.asr.sample
ACT=.police_terms.PoliceTermsBatchEvalActivity
ORIG_PREFIX=police_terms_20260711

CAT="${1:-all}"
RESUME=0
HOTWORD_PROFILE=
for arg in "${@:2}"; do
  case "$arg" in
    --resume) RESUME=1 ;;
    --hotword-profile=full) HOTWORD_PROFILE=full ;;
    --hotword-profile=none) HOTWORD_PROFILE=none ;;
    *) echo "[run] 未知参数 '$arg'（可选 --resume|--hotword-profile=full|--hotword-profile=none）"; exit 1 ;;
  esac
done

if [[ $RESUME -eq 1 && -n "$HOTWORD_PROFILE" ]]; then
  echo "[run] 显式 hotword profile 禁止 --resume，避免跨 profile 混用旧 TSV/progress；请 fresh 重跑。"
  exit 1
fi

case "$CAT" in
  all)          FILTER="$ORIG_PREFIX" ;;
  vocab|dialog|appname|specialcode)
                FILTER="${ORIG_PREFIX}_${CAT}" ;;
  *) echo "[run] 未知类别 '$CAT'（可选 all|vocab|dialog|appname|specialcode）"; exit 1 ;;
esac

FRESH=true
[[ $RESUME -eq 1 ]] && FRESH=false

command -v adb >/dev/null || { echo "[run] 找不到 adb"; exit 1; }
adb get-state >/dev/null 2>&1 || { echo "[run] 无设备连接"; exit 1; }

PROFILE_LABEL="${HOTWORD_PROFILE:-preference(default)}"
PROFILE_ARGS=()
if [[ -n "$HOTWORD_PROFILE" ]]; then
  PROFILE_ARGS+=(--es hotword_profile "$HOTWORD_PROFILE")
fi
echo "[run] 类别=$CAT  filter=$FILTER  fresh=$FRESH  hotword_profile=$PROFILE_LABEL"
# 先 force-stop：Activity 是 standard 启动模式且未重写 onNewIntent，残留实例会吞掉新 intent
# （新 filter/fresh 不生效、批处理不启动）。force-stop 保证每次干净 onCreate + autoStart。
adb shell am force-stop "$PKG"
sleep 1
adb shell am start -n "$PKG/$ACT" \
  --es filter "$FILTER" \
  "${PROFILE_ARGS[@]}" \
  --ez auto_start true \
  --ez fresh "$FRESH" >/dev/null
echo "[run] 已拉起评测（设备端异步执行）。"
echo "[run] 进度：adb shell 'logcat -s PoliceTermsBatchEval:I PoliceTermsBatchAct:I'"
echo "[run] 收结果：./pull_eval.sh roundN"
