"""会话时长对角色归属的影响：把同一场真实会议截成不同长度，只变时长。

动机：混淆率在两类数据上差了一个数量级，而时长与数据集强共线——
  丁桥 1.8~6.2 min、合成集 2 min  → 混淆 22~40%
  AliMeeting 26~37 min            → 混淆 1.5%
Sortformer 每 9.92 s 提交一次、spkcache 188 帧，2 分钟只有约 12 次提交，
30 分钟有约 180 次。若归属要靠时间积累，短会就是最弱的工况——而**客户的录音
全是 2~6 分钟**，正好落在这里。

做法：同一场 AliMeeting 远场音频截取前 N 分钟，参考 RTTM 同步截断（跨界区间裁到
边界），逐长度评分。音频、说话人、房间全部不变，时长是唯一变量。
"""
import argparse
import glob
import os
import subprocess
import wave

import numpy as np

SR = 16000


def truncate_rttm(segs, limit):
    out = []
    for begin, end, spk in segs:
        if begin >= limit:
            continue
        out.append((begin, min(end, limit), spk))
    return out


def cut_wav(src, dst, seconds):
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src,
                        "-t", str(seconds), "-acodec", "copy", dst],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:300])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ali", required=True, help="29_ 用的 ali/far 目录")
    ap.add_argument("--out", required=True)
    ap.add_argument("--minutes", default="2,5,10,20")
    args = ap.parse_args()

    mins = [float(x) for x in args.minutes.split(",")]
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(
        "sc", os.path.join(here, "23_score_diarization_scenarios.py"))
    sc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sc)

    index = []
    for ref_path in sorted(glob.glob(f"{args.ali}/*.rttm")):
        name = os.path.basename(ref_path)[:-5]
        src = f"{args.ali}/{name}.wav"
        if not os.path.isfile(src):
            continue
        segs = sc.read_rttm(ref_path)
        w = wave.open(src, "rb")
        full = w.getnframes() / w.getframerate()
        w.close()
        for m in mins:
            limit = m * 60
            if limit >= full:
                continue
            tag = f"{name}_{int(m)}min"
            d = f"{args.out}/{tag}"
            os.makedirs(args.out, exist_ok=True)
            if not os.path.isfile(f"{d}.wav"):
                cut_wav(src, f"{d}.wav", limit)
            cut = truncate_rttm(segs, limit)
            with open(f"{d}.rttm", "w", encoding="utf-8") as handle:
                for b, e, s in cut:
                    handle.write(f"SPEAKER {tag} 1 {b:.3f} {e-b:.3f} "
                                 f"<NA> <NA> {s} <NA> <NA>\n")
            index.append(dict(name=tag, session=name, minutes=m,
                              speakers=len({s for _, _, s in cut}), duration=limit))
        print(f"  {name:18s} 全长 {full/60:.1f} min → 截 {[int(m) for m in mins if m*60 < full]}")
    import json
    json.dump(index, open(f"{args.out}/index.json", "w"), ensure_ascii=False, indent=1)
    print(f"\n共 {len(index)} 条截断样本")




def report(scratch):
    """按截断长度汇总，并与全程结果配对，看归属是否随时长改善。"""
    import importlib.util, json
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(
        "sc", os.path.join(here, "23_score_diarization_scenarios.py"))
    sc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sc)
    index = json.load(open(f"{scratch}/alilen/index.json"))
    rows = []
    for it in index:
        hyp = f"{scratch}/alilen_pred/{it['name']}.rttm"
        if not os.path.isfile(hyp):
            continue
        ref = sc.read_rttm(f"{scratch}/alilen/{it['name']}.rttm")
        m = sc.score_one(ref, sc.read_rttm(hyp), it["duration"])
        rows.append(dict(**it, **m))
    # 全程臂
    for ref_path in sorted(glob.glob(f"{scratch}/ali/far/*.rttm")):
        name = os.path.basename(ref_path)[:-5]
        hyp = f"{scratch}/ali_pred/far/{name}.rttm"
        if not os.path.isfile(hyp):
            continue
        ref = sc.read_rttm(ref_path)
        st = sc.segment_stats(ref)
        m = sc.score_one(ref, sc.read_rttm(hyp), st["duration"])
        rows.append(dict(name=name, session=name, minutes=st["duration"]/60,
                         speakers=st["speakers"], duration=st["duration"], **m))

    print(f"{'截断长度':>8s} {'样本':>4s} {'DER':>7s} {'漏检':>7s} {'混淆':>8s} "
          f"{'覆盖':>6s} {'人数判对':>8s} {'跳变/人':>8s}")
    buckets = {}
    for r in rows:
        key = "全程" if r["minutes"] > 25 else f"{int(r['minutes'])} min"
        buckets.setdefault(key, []).append(r)
    for key in ("2 min", "5 min", "10 min", "20 min", "全程"):
        g = buckets.get(key)
        if not g:
            continue
        w = np.array([r["total"] for r in g])
        agg = lambda f: float(np.average([r[f] for r in g], weights=w))
        print(f"{key:>8s} {len(g):>4d} {agg('der')*100:>6.1f}% {agg('miss_rate')*100:>6.1f}% "
              f"{agg('conf_rate')*100:>7.2f}% {agg('coverage')*100:>5.0f}% "
              f"{sum(r['speaker_count_correct'] for r in g)}/{len(g):<8d} "
              f"{float(np.mean([r['flips_per_speaker'] for r in g])):>8.1f}")

    print("\n--- 仅 4 人场次（合成集报 37~40% 混淆的那一档）---")
    print(f"{'截断长度':>8s} {'样本':>4s} {'DER':>7s} {'混淆':>8s} {'人数判对':>8s}")
    for key in ("2 min", "5 min", "10 min", "20 min", "全程"):
        g = [r for r in buckets.get(key, []) if r["speakers"] == 4]
        if not g:
            continue
        w = np.array([r["total"] for r in g])
        agg = lambda f: float(np.average([r[f] for r in g], weights=w))
        print(f"{key:>8s} {len(g):>4d} {agg('der')*100:>6.1f}% {agg('conf_rate')*100:>7.2f}% "
              f"{sum(r['speaker_count_correct'] for r in g)}/{len(g)}")


if __name__ == "__main__":
    import sys
    if "--report" in sys.argv:
        report(os.environ["SCRATCH"])
    else:
        main()
