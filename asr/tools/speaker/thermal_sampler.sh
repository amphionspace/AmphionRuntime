#!/bin/bash
# 两小时发热采样：run_device_stress.py 的 --sample-power 只产 CPU 统计，没有任何温度字段，
# 所以温度要单独采。hidumper 的 -t 不能加引号，否则会被当成字面量。
H=/Users/momo/.local/share/harmony/command-line-tools/sdk/default/openharmony/toolchains/hdc
OUT="$1"; INTERVAL="${2:-30}"
T0=$(date +%s)
# 先探一次拿到传感器名单，作为 CSV 表头
ZONES=$($H shell hidumper -s ThermalService -a -t 2>/dev/null | awk '/^Type: /{print $2}' | paste -sd, -)
echo "elapsed_seconds,$ZONES" > "$OUT"
while true; do
  NOW=$(( $(date +%s) - T0 ))
  VALS=$($H shell hidumper -s ThermalService -a -t 2>/dev/null | awk '/^Temperature: /{print $2}' | paste -sd, -)
  if [ -n "$VALS" ]; then echo "$NOW,$VALS" >> "$OUT"; else echo "$NOW,DEVICE_UNREACHABLE" >> "$OUT"; fi
  sleep "$INTERVAL"
done
