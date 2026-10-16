#!/usr/bin/env python3
"""把一场绑核/屏幕实验的原始产物折算成报告指标。"""
import csv, glob, hashlib, json, re, statistics, sys
from pathlib import Path


def pct(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    return s[min(len(s) - 1, int(round(p / 100.0 * (len(s) - 1))))]


def stats(vals):
    if not vals:
        return None
    return {"n": len(vals), "p50": round(statistics.median(vals), 2),
            "p95": round(pct(vals, 95), 2), "max": round(max(vals), 2),
            "mean": round(statistics.fmean(vals), 2)}


def load_events(run):
    f = glob.glob(str(run / "stress/*/diagnostics/*/events.full.ndjson"))
    if not f:
        return [], None
    evs = [json.loads(l) for l in open(f[0], encoding="utf-8")]
    return evs, Path(f[0])


def analyze(run: Path):
    out = {"run": run.name}
    meta = json.loads((run / "scenario.json").read_text(encoding="utf-8"))
    out["scenario"] = {k: meta[k] for k in ("name", "cpu_ids", "screen", "pace_ms",
                                            "num_threads", "audio_seconds",
                                            "suspend_after_s", "suspended", "driver_rc",
                                            "wall_total_s")}
    pace = meta["pace_ms"]
    audio_s = meta["audio_seconds"]

    # ---- 温度 ----
    pre, post = meta["temps_pre"], meta["temps_post"]
    out["thermal"] = {
        "shell_back_pre": pre.get("shell_back"), "shell_back_post": post.get("shell_back"),
        "shell_back_rise": round(post.get("shell_back", 0) - pre.get("shell_back", 0), 2),
        "system_h_pre": pre.get("system_h"), "system_h_post": post.get("system_h"),
        "system_h_rise": round(post.get("system_h", 0) - pre.get("system_h", 0), 2),
    }

    # ---- 绑核 / QoS 证据 ----
    hil = run / "hilog-stream.txt"
    sched = {}
    overflow = 0
    if hil.exists():
        txt = hil.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"AmphionScheduling: ([a-z-]+) result=(-?\d+)", txt):
            sched.setdefault(m.group(1), {}).setdefault(m.group(2), 0)
            sched[m.group(1)][m.group(2)] += 1
        enc = re.findall(r"community-encoder backend=(\S+) device=(\S+)", txt)
        out["encoder_backend"] = sorted(set(enc))[:3]
        overflow = len(re.findall(r"Overflow", txt))
    out["scheduling_log"] = sched
    out["overflow_hits"] = overflow

    # ---- cpuset / 线程掩码时间线 ----
    samples = []
    sp = run / "sampler.ndjson"
    if sp.exists():
        for l in open(sp, encoding="utf-8"):
            try:
                samples.append(json.loads(l))
            except Exception:
                pass
    cpuset_tl, mask_tl = [], []
    prev = None
    for s in samples:
        c = s.get("cpuset")
        if c and c != prev:
            cpuset_tl.append({"t": s["wallTimeMs"], "cpuset": c})
            prev = c
        if s.get("thread_masks"):
            mask_tl.append({"t": s["wallTimeMs"], "masks": s["thread_masks"],
                            "threads": s.get("threads")})
    out["cpuset_timeline"] = cpuset_tl
    out["thread_mask_samples"] = len(mask_tl)
    if mask_tl:
        mid = mask_tl[len(mask_tl) // 2]
        out["thread_masks_mid"] = mid
        out["thread_masks_last"] = mask_tl[-1]
        # 小核独占占比（掩码恰为 0-3）
        def small_only(ms):
            tot = sum(ms.values())
            sm = sum(v for k, v in ms.items() if k.replace(" ", "") in ("0-3", "0,1,2,3"))
            return round(100.0 * sm / tot, 1) if tot else None
        out["small_core_thread_pct_mid"] = small_only(mid["masks"])
        out["small_core_thread_pct_last"] = small_only(mask_tl[-1]["masks"])

    # ---- 进程 CPU 占用 ----
    ticks = [(s["wallTimeMs"], s.get("cpu_ticks", "")) for s in samples if s.get("cpu_ticks")]
    cpu_pct = []
    HZ = 100.0
    for (t1, a), (t2, b) in zip(ticks, ticks[1:]):
        try:
            u1, s1 = [int(x) for x in a.split()[:2]]
            u2, s2 = [int(x) for x in b.split()[:2]]
        except Exception:
            continue
        dt = (t2 - t1) / 1000.0
        if dt > 0.5:
            cpu_pct.append(100.0 * ((u2 + s2) - (u1 + s1)) / HZ / dt)
    out["process_cpu_pct"] = stats(cpu_pct)

    # ---- 事件流 ----
    evs, evpath = load_events(run)
    out["events_file"] = str(evpath) if evpath else None
    out["events_total"] = len(evs)
    out["events_truncated"] = bool(evs) and evs[0]["sequence"] != 1
    out["events_first_sequence"] = evs[0]["sequence"] if evs else None

    by = {}
    for e in evs:
        by.setdefault(e["event"], []).append(e)

    # 会话时间基准
    appended = by.get("DIARIZATION_AUDIO_APPENDED", [])
    t_first_audio = appended[0]["wallTimeMs"] if appended else None
    t_last_audio = appended[-1]["wallTimeMs"] if appended else None
    comp = by.get("CALLBACK_COMPLETE", [])
    t_complete = comp[-1]["wallTimeMs"] if comp else None
    out["timeline_ms"] = {"first_audio": t_first_audio, "last_audio": t_last_audio,
                          "complete": t_complete}
    if t_first_audio and t_last_audio:
        out["input_feed_wall_s"] = round((t_last_audio - t_first_audio) / 1000.0, 1)
    if t_first_audio and t_complete:
        wall = (t_complete - t_first_audio) / 1000.0
        out["session_wall_s"] = round(wall, 1)
        out["realtime_factor_session"] = round(audio_s / wall, 3) if wall else None

    # lag 曲线（报告口径：已写入音频 − 角色窗完成点）
    q = by.get("DIARIZATION_QUEUE", [])
    lag = []
    for e in q:
        f = e["fields"]
        lag.append({"t": e["wallTimeMs"],
                    "rel_s": round((e["wallTimeMs"] - t_first_audio) / 1000.0, 1) if t_first_audio else None,
                    "audio_pos_s": round(f.get("audioEndSample", 0) / 16000.0, 1),
                    "done_s": round(f.get("completedThroughSample", 0) / 16000.0, 1),
                    "lag_ms": f.get("audioDelayMs"),
                    "pending": f.get("pendingJobs")})
    out["lag_curve"] = lag
    if lag:
        vals = [x["lag_ms"] for x in lag if x["lag_ms"] is not None]
        out["lag_stats_ms"] = stats(vals)
        out["lag_peak"] = max(lag, key=lambda x: x["lag_ms"] or 0)
        out["lag_last"] = lag[-1]

    # 吐字节奏：partial 回调间隔
    res = by.get("CALLBACK_RESULT", [])
    partial = [e for e in res if not e["fields"].get("isFinal")]
    finals = [e for e in res if e["fields"].get("isFinal")]
    out["callback_counts"] = {"partial": len(partial), "final": len(finals)}
    if len(partial) > 2:
        gaps = [partial[i + 1]["wallTimeMs"] - partial[i]["wallTimeMs"] for i in range(len(partial) - 1)]
        out["partial_gap_ms"] = stats(gaps)
    if res and t_first_audio:
        out["first_result_latency_ms"] = res[0]["wallTimeMs"] - t_first_audio

    # 角色窗耗时
    wins = by.get("DIARIZATION_COMMUNITY_WINDOW", [])
    for k in ("segmentationMs", "featureMs", "embeddingMs", "encoderMs", "inferenceWallMs"):
        out.setdefault("window_timing", {})[k] = stats([w["fields"][k] for w in wins if k in w["fields"]])
    if wins:
        out["window_count"] = len(wins)
        out["window_encoder"] = sorted({(w["fields"].get("encoderBackend"),
                                         w["fields"].get("encoderDevice")) for w in wins})[:2]

    # ASR 侧滞后：写入进度 vs ASR 已处理
    proc = by.get("DIARIZATION_ASR_PROCESSED", [])
    if proc and appended:
        pairs = []
        pi = 0
        for a in appended[::10]:
            while pi + 1 < len(proc) and proc[pi + 1]["wallTimeMs"] <= a["wallTimeMs"]:
                pi += 1
            w_ms = a["fields"].get("audioEndSample", 0) / 16.0 if "audioEndSample" in a["fields"] else None
            p_ms = proc[pi]["fields"].get("audioEndSample", 0) / 16.0
            if w_ms is not None:
                pairs.append(w_ms - p_ms)
        out["asr_lag_ms"] = stats([x for x in pairs if x >= 0])

    # 全程队列深度（不受事件环截断影响）
    rs = glob.glob(str(run / "stress/*/diagnostics/*/resource-samples.csv"))
    if rs:
        rows = list(csv.DictReader(open(rs[0], encoding="utf-8")))
        depth = []
        for r in rows:
            try:
                depth.append({"t": int(r["wallTimeMs"]),
                              "rel_s": round((int(r["wallTimeMs"]) - t_first_audio) / 1000.0, 1) if t_first_audio else None,
                              "depth": int(r["audioQueueDepth"]),
                              "backlog_ms": int(r["audioQueueDepth"]) * pace,
                              "threads": int(r["threadCount"]),
                              "rssKb": int(r["rssKb"])})
            except Exception:
                pass
        out["queue_curve"] = depth
        if depth:
            out["queue_backlog_ms"] = stats([d["backlog_ms"] for d in depth])
            out["queue_peak"] = max(depth, key=lambda d: d["depth"])

    # 识别文本（跨场一致性）
    txt = "".join(e["fields"].get("text", "") for e in finals)
    out["final_text_chars"] = len(txt)
    out["final_text_sha256"] = hashlib.sha256(txt.encode()).hexdigest()[:16]
    out["final_text_head"] = txt[:80]

    # 驱动自评
    rep = glob.glob(str(run / "stress/*/report.json"))
    if rep:
        d = json.loads(Path(rep[0]).read_text(encoding="utf-8"))
        out["driver_status"] = d.get("overall_status")
        out["driver_failures"] = d.get("failures")
        out["driver_cpu"] = d.get("cpu")
        app = d.get("application")
        dev = d.get("device")
        for src in (app, dev):
            if isinstance(src, dict) and src.get("sdkVersion"):
                out["sdk_version"] = src["sdkVersion"]
                break
    return out


if __name__ == "__main__":
    for d in sys.argv[1:]:
        p = Path(d)
        r = analyze(p)
        (p / "metrics.json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in r.items()
                          if k not in ("lag_curve", "queue_curve", "driver_cpu")},
                         ensure_ascii=False, indent=2)[:3000])
