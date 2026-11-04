#!/bin/bash
# 安卓侧发热长跑的一键运行：基线 → 采样 → instrumented 长跑 → 收尾 → 报告。
#
# 与鸿蒙那一轮对齐的三点：
#   1) 负载是**实时速率**（20 ms / 640 字节定长帧按节拍喂），不是灌数据
#   2) 开启角色分离（maxSpeakers=4）
#   3) 温度与内存由主机侧采样，产出与鸿蒙同格式的 CSV，复用同一份报告脚本
#
# 用法：
#   run_android_longrun.sh <输出目录> [时长分钟=120] [采样间隔秒=30] [--skip-build]
set -eu
OUT="${1:?用法: run_android_longrun.sh <输出目录> [时长分钟] [间隔秒] [--skip-build]}"
MINUTES="${2:-120}"
INTERVAL="${3:-30}"
SKIP_BUILD="${4:-}"

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
PKG=com.amphion.dingqiao.demo
TEST_CLASS=com.amphion.dingqiao.demo.DqThermalLongRunTest
HERE="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$OUT"
echo "[INFO] 输出 $OUT  时长 ${MINUTES} 分钟  采样间隔 ${INTERVAL}s"

# ---- 1. 设备 ----
DEV=$(adb devices | awk 'NR>1 && $2=="device"{print $1}' | head -1)
[ -n "$DEV" ] || { echo "[ERROR] 没有处于 device 状态的安卓设备" >&2; exit 1; }
echo "[INFO] 设备 $DEV  $(adb shell getprop ro.product.model | tr -d '\r')" \
     "/ $(adb shell getprop ro.product.manufacturer | tr -d '\r')" \
     "/ SoC $(adb shell getprop ro.board.platform | tr -d '\r')"
adb shell getprop ro.product.model > "$OUT/device.txt" 2>/dev/null || true
adb shell getprop ro.board.platform >> "$OUT/device.txt" 2>/dev/null || true

# ---- 2. 等温度回到基线 ----
# 不等基线的话，起点温度带着上一轮的余热，升幅会被低估。
echo "[INFO] 等温度稳定（4 次 × 100s）"
for i in 1 2 3 4; do
  T=$(adb shell 'cat /sys/class/thermal/thermal_zone0/temp' 2>/dev/null | tr -d '\r')
  echo "  基线检查 $i: zone0 = ${T:-读不到}"
  [ "$i" -lt 4 ] && sleep 100
done

# ---- 3. 构建安装 ----
if [ "$SKIP_BUILD" != "--skip-build" ]; then
  echo "[INFO] 构建并安装测试 APK"
  ( cd "$ROOT/asr/android" && ./gradlew :samples:dingqiao-demo:installDebug \
      :samples:dingqiao-demo:installDebugAndroidTest --console=plain -q )
else
  echo "[INFO] 跳过构建，使用设备上已安装的包"
fi

# ---- 4. 采样器 ----
"$HERE/sampler_android.sh" "$OUT" "$PKG" "$INTERVAL" > "$OUT/sampler.log" 2>&1 &
SAMPLER=$!
trap 'kill $SAMPLER 2>/dev/null || true' EXIT
sleep 3
echo "[INFO] 采样器 pid $SAMPLER"

# ---- 5. 长跑 ----
# am instrument 自己不会超时，但 adb 连接可能断；日志落盘以便事后诊断。
echo "[INFO] 启动长跑，预计 ${MINUTES} 分钟"
adb shell am instrument -w -r \
  -e class "$TEST_CLASS" \
  -e durationMinutes "$MINUTES" \
  "$PKG.test/androidx.test.runner.AndroidJUnitRunner" \
  > "$OUT/instrument.log" 2>&1 || echo "[WARN] instrument 退出非零，见 instrument.log"

# ---- 6. 收尾 ----
kill $SAMPLER 2>/dev/null || true
trap - EXIT
sleep 1
echo "[INFO] 采样点 温度 $(( $(wc -l < "$OUT/thermal.csv") - 1 ))  内存 $(( $(wc -l < "$OUT/memory.csv") - 1 ))"
echo "[INFO] 掉线次数 $(grep -c DEVICE_UNREACHABLE "$OUT/thermal.csv" || true)"
tail -5 "$OUT/instrument.log" || true

# ---- 7. 报告 ----
echo
"$ROOT/.venv-speaker/bin/python" "$HERE/31_report_thermal_longrun.py" \
  --run-dir "$OUT" --thermal "$OUT/thermal.csv" || \
  echo "[WARN] 报告生成失败，CSV 仍在 $OUT"
