#!/bin/bash
# 安卓侧发热长跑采样（主机侧，走 adb）。
#
# 为什么在主机侧采：采样进程若跑在设备上，它自己的占用会算进被测应用，adb shell
# 每次调用的开销也会被记进去。主机侧采，设备上只执行只读命令。
#
# 产出三个 CSV。前两个列名与鸿蒙那一轮**完全一致**，所以 31_report_thermal_longrun.py
# 可直接复用；第三个是安卓特有的节流证据。
#   thermal.csv   elapsed_seconds,<传感器名...>                     单位毫摄氏度
#   memory.csv    elapsed_seconds,pid,vm_rss_kb,vm_hwm_kb,vm_data_kb,vm_swap_kb,threads
#   throttle.csv  elapsed_seconds,thermal_status,khz_little,khz_mid,khz_big
#
# 为什么要单独记节流：温度曲线平下来有两种完全不同的原因——散热到位，或者系统降频
# 把算力压下去了。只看温度分不出这两者，而后者意味着识别性能在劣化。
#
# 用法：sampler_android.sh <输出目录> <包名> [采样间隔秒]
set -u
OUT="${1:?用法: sampler_android.sh <输出目录> <包名> [间隔秒]}"
PKG="${2:?缺少包名}"
INTERVAL="${3:-30}"
mkdir -p "$OUT"

# 该机型有 89 个 thermal_zone，全采会让报告不可读，且多数是关闭的（-273000）或
# 与本测无关的射频/摄像头。这里按用途筛一份固定清单，缺哪个就跳过哪个。
#   机身三面：用户能摸到的温度，是对外报数的依据
#   battery/xo/wlc：离热源较远，作环境的弱代理（**不是**环境传感器，见下）
#   skin-msm-therm：安卓用来触发节流的皮肤温度
#   cpu/cpuss/gpuss/ddr：定位热源
WANT="shell_back shell_frame shell_front battery skin-msm-therm xo-therm wlc-therm \
cpu-0-0 cpu-1-0 cpuss-0 gpuss-0 ddr aoss-0 conn-therm"

MAP=$(adb shell 'for z in /sys/class/thermal/thermal_zone*; do
  t=$(cat $z/type 2>/dev/null); [ -n "$t" ] && echo "$z|$t"; done' 2>/dev/null | tr -d '\r')
[ -n "$MAP" ] || { echo "[ERROR] /sys/class/thermal 读不到" >&2; exit 1; }

NAMES=""; PATHS=""
for w in $WANT; do
  line=$(echo "$MAP" | awk -F'|' -v w="$w" '$2==w{print $1; exit}')
  if [ -n "$line" ]; then
    NAMES="${NAMES:+$NAMES,}$w"
    PATHS="${PATHS:+$PATHS }$line/temp"
  else
    echo "[WARN] 无此传感器，已跳过: $w" >&2
  fi
done
[ -n "$NAMES" ] || { echo "[ERROR] 清单里的传感器一个都没匹配上" >&2; exit 1; }
echo "[INFO] 采集 $(echo "$NAMES" | tr ',' '\n' | grep -c .) 个传感器: $NAMES" >&2

echo "elapsed_seconds,$NAMES" > "$OUT/thermal.csv"
# 带上 CPU 节拍数，与鸿蒙那轮的列完全一致。为什么不用 top：安卓的 `top -n 1` 单次采样
# 算不出占用、恒为 0.0%，曾据此误判"没在干活"并中止了一次正常的两小时跑。
# 用 /proc/<pid>/stat 的 utime+stime 与 /proc/stat 的总节拍做差分，才是可靠的占用率。
echo "elapsed_seconds,pid,vm_rss_kb,vm_hwm_kb,vm_data_kb,vm_swap_kb,threads,process_cpu_ticks,system_cpu_ticks,logical_cpus" > "$OUT/memory.csv"
NCPU=$(adb shell "cat /proc/cpuinfo" 2>/dev/null | tr -d '\r' | grep -c '^processor')
echo "elapsed_seconds,thermal_status,khz_little,khz_mid,khz_big" > "$OUT/throttle.csv"

# 三簇的 cpufreq policy；该机型是 policy0/4/7（小/中/大）
FREQ_PATHS="/sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq \
/sys/devices/system/cpu/cpufreq/policy4/scaling_cur_freq \
/sys/devices/system/cpu/cpufreq/policy7/scaling_cur_freq"

T0=$(date +%s)
echo "[INFO] 开始采样，间隔 ${INTERVAL}s，输出 $OUT" >&2

while true; do
  NOW=$(( $(date +%s) - T0 ))

  # 一次 adb 调用取全部温度，少一点往返开销
  VALS=$(adb shell "cat $PATHS" 2>/dev/null | tr -d '\r' | paste -sd, -)
  if [ -n "$VALS" ]; then
    echo "$NOW,$VALS" >> "$OUT/thermal.csv"
  else
    echo "$NOW,DEVICE_UNREACHABLE" >> "$OUT/thermal.csv"
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
    # /proc/<pid>/stat 第 14、15 列是 utime、stime；进程名含空格会错位，所以从 ')' 后面数
    PT=$(adb shell "cat /proc/$PID/stat" 2>/dev/null | tr -d '\r' \
         | sed 's/^.*) //' | awk '{print $12+$13}')
    SYST=$(adb shell "head -1 /proc/stat" 2>/dev/null | tr -d '\r' \
           | awk '{s=0; for(i=2;i<=NF;i++) s+=$i; print s}')
    echo "$NOW,$PID,${RSS:-0},${HWM:-0},${DATA:-0},${SWAP:-0},${THR:-0},${PT:-0},${SYST:-0},${NCPU:-0}" >> "$OUT/memory.csv"
  else
    echo "$NOW,0,0,0,0,0,0,0,0,${NCPU:-0}" >> "$OUT/memory.csv"
  fi

  # 节流等级 + 三簇频率
  TS=$(adb shell dumpsys thermalservice 2>/dev/null | tr -d '\r' \
       | awk -F': ' '/^Thermal Status/{print $2; exit}')
  FQ=$(adb shell "cat $FREQ_PATHS" 2>/dev/null | tr -d '\r' | paste -sd, -)
  echo "$NOW,${TS:-},${FQ:-,,}" >> "$OUT/throttle.csv"

  sleep "$INTERVAL"
done
