#!/usr/bin/env python3
"""分阶段实时率与滞后曲线：把一场实验按屏幕/排空阶段切开计算。

指标口径与《锁屏解析延迟-分析报告-20261014》一致：
  lag        = 已写入音频时长 − 已处理音频时长
  实时率     = Δ已处理音频秒 / Δ墙钟秒
"""
import glob
import json
import statistics
import sys
from pathlib import Path


def pct(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    return s[min(len(s) - 1, int(round(p / 100.0 * (len(s) - 1))))]


def load(run: Path):
    f = glob.glob(str(run / "stress/*/diagnostics/*/events.full.ndjson"))
    if not f:
        raise SystemExit(f"{run}: 无事件文件")
    return [json.loads(l) for l in open(f[0], encoding="utf-8")]


def series(evs, event, field):
    """返回 [(wallMs, 样点值)]，样点取 field（样本数）。"""
    out = []
    for e in evs:
        if e["event"] == event:
            v = e["fields"].get(field)
            if v is not None:
                out.append((e["wallTimeMs"], v))
    return out


def at(sr, t):
    """阶梯插值：取不晚于 t 的最后一个样点值。"""
    lo, hi, best = 0, len(sr) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if sr[mid][0] <= t:
            best = sr[mid][1]
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def analyze(run: Path):
    meta = json.loads((run / "scenario.json").read_text(encoding="utf-8"))
    evs = load(run)
    written = series(evs, "DIARIZATION_AUDIO_APPENDED", "audioEndSample")
    if not written:
        written = [(t, v * 16000 // 1000) for t, v in series(evs, "AUDIO_PROGRESS", "audioBytesWritten")]
        written = [(t, v // 2) for t, v in written]  # 16bit → 样本
    processed = series(evs, "DIARIZATION_ASR_PROCESSED", "audioEndSample")
    if not (written and processed):
        raise SystemExit(f"{run}: 缺少写入或处理进度序列")

    t0 = written[0][0]
    t_input_end = written[-1][0]
    t_last = max(evs, key=lambda e: e["wallTimeMs"])["wallTimeMs"]

    # 阶段切分
    phases = []
    if meta["screen"] == "off" and meta.get("suspended"):
        t_sus = t0 + int(meta["suspend_after_s"] * 1000)
        phases = [("亮屏起始段", t0, t_sus),
                  ("熄屏期", t_sus, t_input_end),
                  ("亮屏排空期", t_input_end, t_last)]
    else:
        span = t_input_end - t0
        phases = [("全程", t0, t_input_end),
                  ("前 1/3", t0, t0 + span // 3),
                  ("中 1/3", t0 + span // 3, t0 + 2 * span // 3),
                  ("后 1/3", t0 + 2 * span // 3, t_input_end),
                  ("输入结束后排空", t_input_end, t_last)]

    rows = []
    for name, a, b in phases:
        pa, pb = at(processed, a), at(processed, b)
        if pa is None:
            pa = 0
        if pb is None or b <= a:
            continue
        d_audio = (pb - pa) / 16000.0
        d_wall = (b - a) / 1000.0
        rows.append({"phase": name,
                     "wall_s": round(d_wall, 1),
                     "audio_done_s": round(d_audio, 1),
                     "realtime": round(d_audio / d_wall, 3) if d_wall else None})

    # lag 曲线（每 15 秒一个采样点）
    curve = []
    t = t0
    while t <= t_last:
        w, p = at(written, t), at(processed, t)
        if w is not None and p is not None:
            curve.append({"rel_s": round((t - t0) / 1000.0, 1),
                          "written_s": round(w / 16000.0, 1),
                          "processed_s": round(p / 16000.0, 1),
                          "lag_s": round((w - p) / 16000.0, 1)})
        t += 15000
    lags = [c["lag_s"] for c in curve]
    peak = max(curve, key=lambda c: c["lag_s"]) if curve else None

    return {
        "name": meta["name"], "cpu_ids": meta["cpu_ids"], "screen": meta["screen"],
        "t0_ms": t0, "input_end_ms": t_input_end, "last_event_ms": t_last,
        "input_feed_s": round((t_input_end - t0) / 1000.0, 1),
        "observed_tail_s": round((t_last - t_input_end) / 1000.0, 1),
        "audio_total_s": round(written[-1][1] / 16000.0, 1),
        "audio_processed_s": round(processed[-1][1] / 16000.0, 1),
        "unprocessed_at_end_s": round((written[-1][1] - processed[-1][1]) / 16000.0, 1),
        "phases": rows,
        "lag_peak": peak,
        "lag_p50_s": round(statistics.median(lags), 1) if lags else None,
        "lag_p95_s": round(pct(lags, 95), 1) if lags else None,
        "lag_curve": curve,
    }


if __name__ == "__main__":
    for d in sys.argv[1:]:
        p = Path(d)
        r = analyze(p)
        (p / "phases.json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        brief = {k: v for k, v in r.items() if k != "lag_curve"}
        print(json.dumps(brief, ensure_ascii=False, indent=2))
        print()
