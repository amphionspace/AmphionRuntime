#!/bin/bash
# 安卓侧发热 + 内存采样（主机侧，走 adb）。
#
# 为什么在主机侧采：采样进程若跑在设备上，它自己的占用会算进被测应用，而且 adb shell
# 每次调用的开销也会被记进去。主机侧采只在设备上执行只读命令。
#
# 产出两个 CSV，列名与鸿蒙那一轮**完全一致**，所以 31_report_thermal_longrun.py 可直接复用：
#   thermal.csv  elapsed_seconds,<传感器名...>     单位毫摄氏度
#   memory.csv   elapsed_seconds,pid,vm_rss_kb,vm_hwm_kb,vm_data_kb,vm_swap_kb,threads
#
# 用法：sampler_android.sh <输出目录> <包名> [采样间隔秒]
set -u
OUT="${1:?用法: sampler_android.sh <输出目录> <包名> [间隔秒]}"
PKG="${2:?缺少包名}"
INTERVAL="${3:-30}"
mkdir -p "$OUT"

# 温度源有两种，按可用性选：
#   A) /sys/class/thermal/thermal_zone*/{type,temp}  —— 通用、免 root、名字最全
#   B) dumpsys thermalservice                        —— 名字少，但部分机型上 A 不可读
ZONES=$(adb shell 'for z in /sys/class/thermal/thermal_zone*; do
  t=$(cat $z/type 2>/dev/null); [ -n "$t" ] && echo "$z|$t"; done' 2>/dev/null | tr -d '\r')
if [ -z "$ZONES" ]; then
  echo "[WARN] /sys/class/thermal 不可读，回落到 dumpsys thermalservice" >&2
  MODE=dumpsys
  echo "elapsed_seconds,raw" > "$OUT/thermal.csv"
else
  MODE=sysfs
  NAMES=$(echo "$ZONES" | awk -F'|' '{print $2}' | paste -sd, -)
  PATHS=$(echo "$ZONES" | awk -F'|' '{print $1"/temp"}' | paste -sd' ' -)
  echo "elapsed_seconds,$NAMES" > "$OUT/thermal.csv"
  echo "[INFO] 传感器 $(echo "$ZONES" | wc -l | tr -d ' ') 个: $NAMES" >&2
fi

echo "elapsed_seconds,pid,vm_rss_kb,vm_hwm_kb,vm_data_kb,vm_swap_kb,threads" > "$OUT/memory.csv"
T0=$(date +%s)
echo "[INFO] 开始采样，间隔 ${INTERVAL}s，输出 $OUT" >&2

while true; do
  NOW=$(( $(date +%s) - T0 ))

  # 温度
  if [ "$MODE" = sysfs ]; then
    VALS=$(adb shell "cat $PATHS" 2>/dev/null | tr -d '\r' | paste -sd, -)
    if [ -n "$VALS" ]; then
      echo "$NOW,$VALS" >> "$OUT/thermal.csv"
    else
      echo "$NOW,DEVICE_UNREACHABLE" >> "$OUT/thermal.csv"
    fi
  else
    VALS=$(adb shell dumpsys thermalservice 2>/dev/null | tr -d '\r' \
           | grep -oE 'mValue=[0-9.]+' | cut -d= -f2 | paste -sd';' -)
    echo "$NOW,${VALS:-DEVICE_UNREACHABLE}" >> "$OUT/thermal.csv"
  fi

  # 内存：被测进程的 /proc/<pid>/status。instrumented 测试跑在应用进程里，
  # 所以取包名对应的进程，不是 instrumentation 自己的进程。
  PID=$(adb shell pidof "$PKG" 2>/dev/null | tr -d '\r' | awk '{print $1}')
  if [ -n "$PID" ]; then
    ST=$(adb shell "cat /proc/$PID/status" 2>/dev/null | tr -d '\r')
    RSS=$(echo "$ST" | awk '$1=="VmRSS:"{print $2}')
    HWM=$(echo "$ST" | awk '$1=="VmHWM:"{print $2}')
    DATA=$(echo "$ST" | awk '$1=="VmData:"{print $2}')
    SWAP=$(echo "$ST" | awk '$1=="VmSwap:"{print $2}')
    THR=$(echo "$ST" | awk '$1=="Threads:"{print $2}')
    echo "$NOW,$PID,${RSS:-0},${HWM:-0},${DATA:-0},${SWAP:-0},${THR:-0}" >> "$OUT/memory.csv"
  else
    echo "$NOW,0,0,0,0,0,0" >> "$OUT/memory.csv"
  fi

  sleep "$INTERVAL"
done
