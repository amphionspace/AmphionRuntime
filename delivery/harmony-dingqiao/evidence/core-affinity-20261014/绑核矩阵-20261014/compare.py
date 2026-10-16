#!/usr/bin/env python3
"""把各场 metrics.json / phases.json 汇成横向对比表（markdown）。"""
import json
import sys
from pathlib import Path

ORDER = ["D-baseline", "A-small-on", "E-mid-on", "C-big-on", "B-small-off",
         "B2-small-off-unlock", "B3-off-nobind-unlock"]
LABEL = {
    "D-baseline": "D 亮屏·不绑核",
    "A-small-on": "A 亮屏·绑小核 0-3",
    "E-mid-on": "E 亮屏·绑中核 4-7",
    "C-big-on": "C 亮屏·请求大核 10-11",
    "B-small-off": "B 熄屏·绑小核 0-3",
    "B2-small-off-unlock": "B2 熄屏·绑小核·400s 解锁",
    "B3-off-nobind-unlock": "B3 熄屏·不绑核·400s 解锁",
}


def g(d, *path, default=None):
    cur = d
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def main(root: Path):
    runs = {}
    for name in ORDER:
        p = root / "runs" / name
        if (p / "metrics.json").exists():
            runs[name] = {"m": json.loads((p / "metrics.json").read_text(encoding="utf-8"))}
            if (p / "phases.json").exists():
                runs[name]["p"] = json.loads((p / "phases.json").read_text(encoding="utf-8"))
    names = [n for n in ORDER if n in runs]

    rows = [
        ("请求 cpuIds", lambda r: g(r["m"], "scenario", "cpu_ids")),
        ("屏幕状态", lambda r: "亮屏" if g(r["m"], "scenario", "screen") == "on" else "熄屏(60s 后)"),
        ("绑核读回一致 affinity-exact", lambda r: ("—" if not g(r["m"], "scheduling_log", "affinity-exact")
                                                  else list(g(r["m"], "scheduling_log", "affinity-exact").keys())[0])),
        ("进程 cpuset", lambda r: "/".join(sorted({x["cpuset"].split("/")[-1] for x in g(r["m"], "cpuset_timeline", default=[])}))),
        ("掩码=0-3 的线程数(中段)", lambda r: g(r["m"], "thread_masks_mid", "masks", default={}).get("0,1,2,3", 0)),
        ("线程总数(中段)", lambda r: g(r["m"], "thread_masks_mid", "threads")),
        ("**会话实时率**", lambda r: g(r["m"], "realtime_factor_session")),
        ("ASR 滞后 p50 (ms)", lambda r: g(r["m"], "asr_lag_ms", "p50")),
        ("ASR 滞后 p95 (ms)", lambda r: g(r["m"], "asr_lag_ms", "p95")),
        ("**ASR 滞后峰值 (s)**", lambda r: round((g(r["m"], "asr_lag_ms", "max") or 0) / 1000.0, 1)),
        ("写入队列积压峰值 (s)", lambda r: round((g(r["m"], "queue_peak", "backlog_ms") or 0) / 1000.0, 1)),
        ("角色窗 lag p50 (ms)", lambda r: g(r["m"], "lag_stats_ms", "p50")),
        ("角色窗 lag 峰值 (ms)", lambda r: g(r["m"], "lag_stats_ms", "max")),
        ("partial 间隔 p50 (ms)", lambda r: g(r["m"], "partial_gap_ms", "p50")),
        ("partial 间隔 p95 (ms)", lambda r: g(r["m"], "partial_gap_ms", "p95")),
        ("partial 条数", lambda r: g(r["m"], "callback_counts", "partial")),
        ("final 条数", lambda r: g(r["m"], "callback_counts", "final")),
        ("segmentation p50 (ms)", lambda r: g(r["m"], "window_timing", "segmentationMs", "p50")),
        ("fbank p50 (ms)", lambda r: g(r["m"], "window_timing", "featureMs", "p50")),
        ("embedding p50 (ms)", lambda r: g(r["m"], "window_timing", "embeddingMs", "p50")),
        ("encoder(NPU) p50 (ms)", lambda r: g(r["m"], "window_timing", "encoderMs", "p50")),
        ("单窗推理 p50 (ms)", lambda r: g(r["m"], "window_timing", "inferenceWallMs", "p50")),
        ("进程 CPU p50 (%)", lambda r: g(r["m"], "process_cpu_pct", "p50")),
        ("机身温升 shell_back (°C)", lambda r: g(r["m"], "thermal", "shell_back_rise")),
        ("60s 缓冲 Overflow", lambda r: g(r["m"], "overflow_hits")),
        ("识别文本字数", lambda r: g(r["m"], "final_text_chars")),
        ("文本 sha256(前16)", lambda r: g(r["m"], "final_text_sha256")),
        ("驱动判定", lambda r: g(r["m"], "driver_status")),
    ]

    out = []
    out.append("| 指标 | " + " | ".join(LABEL[n] for n in names) + " |")
    out.append("|---|" + "---|" * len(names))
    for title, fn in rows:
        vals = []
        for n in names:
            try:
                v = fn(runs[n])
            except Exception:
                v = None
            vals.append("—" if v is None else str(v))
        out.append(f"| {title} | " + " | ".join(vals) + " |")

    print("\n".join(out))
    print()
    print("### 分阶段实时率")
    for n in names:
        p = runs[n].get("p")
        if not p:
            continue
        print(f"\n**{LABEL[n]}**")
        print("| 阶段 | 墙钟 s | 已处理音频 s | 实时率 |")
        print("|---|---|---|---|")
        for ph in p["phases"]:
            print(f"| {ph['phase']} | {ph['wall_s']} | {ph['audio_done_s']} | {ph['realtime']}× |")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "."))
