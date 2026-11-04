"""两小时长跑的发热与内存报告。

为什么温度要单独采：`run_device_stress.py --sample-power` 只产出 CPU 占用统计，
report.json 里**没有任何温度字段**，所以温度由 thermal_sampler.sh 并行采集
（`hidumper -s ThermalService -a -t`，`-t` 不能加引号否则被当字面量）。

为什么不用首尾差看内存：首尾差受采样时刻的瞬时抖动支配。这里报分段中位 +
后半程回归斜率，并检查分段中位是否单调——单调才是真实增长的证据。
"""
import argparse
import csv
import json
import os

import numpy as np

# 关注的传感器：机身外壳是用户能摸到的，电池关系续航与降频，system_h 是整机综合
KEY_ZONES = ["Battery", "shell_back", "shell_frame", "shell_front", "system_h", "ambient"]


def load_thermal(path):
    rows, zones = [], []
    with open(path, encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        zones = header[1:]
        for row in reader:
            if len(row) != len(header) or "DEVICE_UNREACHABLE" in row:
                continue
            rows.append([float(x) for x in row])
    data = np.array(rows)
    return zones, data


def temp_scale(data):
    """判别温度单位。鸿蒙的 ThermalService 给毫摄氏度，而安卓各机型的
    /sys/class/thermal 有毫、分、摄氏三种，硬编码 /1000 会把读数差 10~1000 倍。
    按合理机身温度区间（约 10~120 °C）反推除数。"""
    v = data[:, 1:]
    peak = float(np.nanmax(v)) if v.size else 0.0
    if peak > 20000:      # 例如 34500 → 34.5 °C
        return 1000.0, "毫摄氏度"
    if peak > 2000:       # 例如 345 → 34.5 °C
        return 10.0, "分摄氏度"
    return 1.0, "摄氏度"


def thermal_report(zones, data):
    t = data[:, 0] / 60.0
    div, unit = temp_scale(data)
    print(f"温度采样 {len(t)} 点，覆盖 {t[-1]:.1f} 分钟，间隔 ~{np.median(np.diff(data[:,0])):.0f} s"
          f"（原始单位判为{unit}）")
    print(f"\n{'传感器':14s} {'起始':>7s} {'峰值':>7s} {'终值':>7s} {'升幅':>8s} "
          f"{'达峰时刻':>9s} {'末10分钟中位':>12s}")
    last10 = t >= t[-1] - 10
    for i, z in enumerate(zones):
        v = data[:, i + 1] / div
        if v.max() <= 0:            # modem 常年 0，没接基带
            continue
        mark = "*" if z in KEY_ZONES else " "
        print(f"{mark}{z:13s} {v[0]:>6.1f}° {v.max():>6.1f}° {v[-1]:>6.1f}° "
              f"{v.max()-v[0]:>+7.1f}° {t[int(np.argmax(v))]:>8.1f}m {np.median(v[last10]):>11.1f}°")

    # 机身与环境的传感器命名两端不同，按优先级找；找不到就跳过对应小节而不是算错
    def pick(*candidates):
        for name in candidates:
            if name in zones:
                return name
        for name in candidates:
            for z in zones:
                if name in z:
                    return z
        return None

    shell = pick("shell_back", "shell_frame", "shell_front", "board_thermal", "skin")
    ambient = pick("ambient", "ap_ntc", "charger")

    # 环境自己会漂。设备真正的自发热要看"机身温度 − 环境温度"，否则机房升温被算进来
    if shell and ambient and shell != ambient:
        back = data[:, zones.index(shell) + 1] / div
        amb = data[:, zones.index(ambient) + 1] / div
        d = back - amb
        print(f"\n（机身取 {shell}，环境取 {ambient}）")
        print(f"\n扣除环境漂移后（shell_back − ambient）：")
        print(f"  起始 {d[0]:.1f}°  峰值 {d.max():.1f}°  终值 {d[-1]:.1f}°  "
              f"净升幅 {d[-1]-d[0]:+.1f}°")
        print(f"  环境自身升幅 {amb[-1]-amb[0]:+.1f}°（机身原始升幅 {back[-1]-back[0]:+.1f}°）")

    if shell:
        print(f"\n是否进入热平台（取 {shell}）：")
        v = data[:, zones.index(shell) + 1] / div
        for lo, hi, name in ((0, 20, "0~20min"), (20, 40, "20~40min"),
                             (40, 70, "40~70min"), (70, 200, "70min~")):
            m = (t >= lo) & (t < hi)
            if m.sum() < 3:
                continue
            k = np.polyfit(t[m], v[m], 1)[0]
            print(f"  {name:10s} 中位 {np.median(v[m]):5.1f}°  斜率 {k*60:+6.2f}°/小时")


def cpu_report(path):
    """用 /proc 节拍差分算进程占用。安卓的 top -n 1 单次采样恒为 0.0%，不可用。"""
    rows = list(csv.DictReader(open(path)))
    if not rows or "process_cpu_ticks" not in rows[0]:
        return
    pts, syst, ncpu, t = [], [], 0, []
    for r in rows:
        p, s = int(r["process_cpu_ticks"] or 0), int(r["system_cpu_ticks"] or 0)
        if p <= 0 or s <= 0:
            continue
        pts.append(p); syst.append(s); t.append(float(r["elapsed_seconds"]))
        ncpu = int(r.get("logical_cpus") or ncpu or 0)
    if len(pts) < 3 or ncpu == 0:
        return
    dp, ds = np.diff(pts), np.diff(syst)
    ok = ds > 0
    # 进程节拍 / 系统总节拍 × 核数 = 单核等效占用；pid 变化会让差分为负，当作无效点丢掉
    util = np.where(ok & (dp >= 0), dp / np.maximum(ds, 1) * ncpu * 100, np.nan)
    util = util[~np.isnan(util)]
    if util.size == 0:
        return
    print(f"\nCPU（单核等效，{ncpu} 逻辑核，差分自 /proc 节拍）：")
    print(f"  中位 {np.median(util):.1f}%  p95 {np.percentile(util,95):.1f}%  "
          f"峰值 {util.max():.1f}%  整机占用中位 {np.median(util)/ncpu:.1f}%")
    if np.median(util) < 5:
        print("  ⚠ 占用极低：引擎可能没在干活，先核对设备上的 report.jsonl 有无回调")


def memory_report(path):
    t, rss, hwm = [], [], []
    for r in csv.DictReader(open(path)):
        t.append(float(r["elapsed_seconds"]))
        rss.append(int(r["vm_rss_kb"]) / 1024)
        hwm.append(int(r["vm_hwm_kb"]) / 1024)
    t, rss, hwm = np.array(t), np.array(rss), np.array(hwm)
    print(f"\n内存采样 {len(t)} 点，覆盖 {t[-1]/60:.1f} 分钟")
    print(f"RSS {rss.min():.0f}~{rss.max():.0f} MB   HWM 峰值 {hwm.max():.0f} MB")
    print("\n分段中位（八等分）：")
    meds = []
    for i in range(8):
        m = (t >= t[-1] * i / 8) & (t < t[-1] * (i + 1) / 8)
        if m.sum() == 0:
            continue
        meds.append(float(np.median(rss[m])))
        print(f"  第{i+1}段 {t[m][0]/60:5.1f}~{t[m][-1]/60:5.1f}min  "
              f"中位 {meds[-1]:6.0f} MB  p90 {np.percentile(rss[m],90):6.0f}  最大 {rss[m].max():6.0f}")
    rises = sum(1 for a, b in zip(meds, meds[1:]) if b > a)
    steps = len(meds) - 1
    tail = meds[-3:]
    tail_span = max(tail) - min(tail)
    print(f"\n形态：{rises}/{steps} 段相邻上升；"
          f"前半累计 {meds[len(meds)//2-1]-meds[0]:+.0f} MB，"
          f"末三段跨度 {tail_span:.0f} MB（{min(tail):.0f}~{max(tail):.0f}）")
    if rises >= steps - 1 and tail_span < 20:
        print("  判定：**饱和型**——前段明显上升，末段进入平台，不是无界泄漏")
    elif rises >= steps - 1:
        print("  判定：**持续上升**，末段未见平台，需要更长观测")
    else:
        print("  判定：抖动为主，首尾差无意义")
    for lo, name in ((0.0, "全程"), (0.5, "后半程"), (0.75, "最后 1/4")):
        m = t >= t[-1] * lo
        k = np.polyfit(t[m] / 3600, rss[m], 1)[0]
        print(f"  {name}斜率 {k:+.1f} MB/小时（中位 {np.median(rss[m]):.0f} MB）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True, help="run_device_stress.py 的输出目录")
    ap.add_argument("--thermal", required=True, help="thermal_sampler.sh 的 CSV")
    args = ap.parse_args()

    zones, data = load_thermal(args.thermal)
    thermal_report(zones, data)

    mem = os.path.join(args.run_dir, "memory.csv")
    if os.path.isfile(mem):
        cpu_report(mem)
        memory_report(mem)

    rep = os.path.join(args.run_dir, "report.json")
    if os.path.isfile(rep):
        d = json.load(open(rep))
        print(f"\n压测判定 overall={d.get('overall_status')}  失败项={d.get('failures')}")
        cpu = d.get("cpu", {})
        if cpu:
            print(f"CPU 单核等效 中位 {cpu.get('p50_single_core_equivalent_percent')}%  "
                  f"p95 {cpu.get('p95_single_core_equivalent_percent')}%  "
                  f"峰值 {cpu.get('peak_single_core_equivalent_percent')}%  "
                  f"整机占用中位 {cpu.get('p50_device_capacity_percent')}%")
        m = d.get("memory", {})
        if m:
            print(f"脚本内存判定 {m.get('status')}  斜率 {m.get('rss_slope_mb_per_minute')} MB/min  "
                  f"三分位中位 {m.get('rss_third_medians_mb')}  峰值 RSS {m.get('peak_rss_mb')} MB")


if __name__ == "__main__":
    main()
