"""真实会议上的重叠讲话轴：不合成、不混音，直接用 AliMeeting 28 场的人工标注。

两种切法，都是新旧模型同音频同评分：
1. 按场次的自然重叠率分档（<5% / 5~15% / 15~25% / >25%）——注意重叠率与人数强相关（2 人场 2~10%，
   4 人场 16~64%），这一档位表同时也在换人数，所以表里把人数构成列出来；
2. 同一场内把时间栅格分成"单人说话区"（参考里恰好 1 人）与"重叠区"（≥2 人），分别算漏检与混淆——
   这才是去掉人数混杂后的"重叠本身的代价"。

用法：SCRATCH=<目录> python 36_report_real_overlap.py [--json <输出>]   （目录布局见 34_report_old_vs_new.py）
--json 把每场的分区指标落成 JSON（只含公开数据集的场次 ID 与数字），作为报告证据入库。
"""
import glob
import importlib.util
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("sc", os.path.join(HERE, "23_score_diarization_scenarios.py"))
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)
S = os.environ["SCRATCH"]
BINS = [("<5%", 0, 5), ("5~15%", 5, 15), ("15~25%", 15, 25), (">25%", 25, 101)]


def active_count(ref, n):
    grid = np.zeros(n, np.int16)
    for begin, end, _ in ref:
        grid[max(0, int(begin / sc.STEP)):min(n, int(end / sc.STEP))] += 1
    return grid


def collect():
    rows = []
    for arm in ("far", "near"):
        for s in ("ali", "alitest"):
            for path in sorted(glob.glob(f"{S}/{s}/{arm}/*.rttm")):
                name = os.path.basename(path)[:-5]
                ref = sc.read_rttm(path)
                st = sc.segment_stats(ref)
                n = int(st["duration"] / sc.STEP) + 1
                count = active_count(ref, n)
                for model, pred_dir in (("new", f"{S}/{s}_pred/{arm}"), ("old", f"{S}/{s}_old/{arm}")):
                    hyp_path = f"{pred_dir}/{name}.rttm"
                    if not os.path.isfile(hyp_path):
                        continue
                    hyp = sc.read_rttm(hyp_path)
                    whole = sc.der(ref, hyp, n)
                    single = sc.der(ref, hyp, n, count == 1)
                    overlap = sc.der(ref, hyp, n, count >= 2)
                    rows.append(dict(arm=arm, name=name, model=model, spk=st["speakers"], ov=st["overlap_ratio"] * 100,
                                     der=whole["der"], miss=whole["miss_rate"], conf=whole["conf_rate"], total=whole["total"],
                                     s_miss=single["miss_rate"], s_conf=single["conf_rate"], s_total=single["total"],
                                     o_miss=overlap["miss_rate"], o_conf=overlap["conf_rate"], o_total=overlap["total"]))
    return rows


def wavg(rows, key, weight):
    rows = [r for r in rows if r[key] is not None]
    return 100 * np.average([r[key] for r in rows], weights=[r[weight] for r in rows]) if rows else float("nan")


def main():
    rows = collect()
    if "--json" in sys.argv:
        out = sys.argv[sys.argv.index("--json") + 1]
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"scorer": "23_score_diarization_scenarios.py (10 ms grid, collar 0, overlap scored, Hungarian)",
                       "regions": {"single": "reference active speakers == 1", "overlap": "reference active speakers >= 2"},
                       "sessions": [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()} for r in rows]},
                      f, ensure_ascii=False, indent=1)
    for arm in ("far", "near"):
        print(f"\n===== {arm}：按场次自然重叠率分档（时长加权；两模型同音频）=====")
        print(f"{'档':8s} {'场':>3s} {'人数构成':12s} {'中位重叠':>7s} | {'旧DER':>6s} {'旧漏':>5s} {'旧混':>5s} | {'新DER':>6s} {'新漏':>5s} {'新混':>5s} | 新更好")
        for label, lo, hi in BINS:
            new = [r for r in rows if r["arm"] == arm and r["model"] == "new" and lo <= r["ov"] < hi]
            old = [r for r in rows if r["arm"] == arm and r["model"] == "old" and lo <= r["ov"] < hi]
            if not new:
                continue
            mix = dict(sorted({k: sum(1 for r in new if r["spk"] == k) for k in {r["spk"] for r in new}}.items()))
            better = sum(1 for a in new for b in old if a["name"] == b["name"] and a["der"] < b["der"])
            print(f"{label:8s} {len(new):>3d} {str(mix):12s} {np.median([r['ov'] for r in new]):6.1f}% | "
                  f"{wavg(old, 'der', 'total'):5.1f}% {wavg(old, 'miss', 'total'):4.1f}% {wavg(old, 'conf', 'total'):4.1f}% | "
                  f"{wavg(new, 'der', 'total'):5.1f}% {wavg(new, 'miss', 'total'):4.1f}% {wavg(new, 'conf', 'total'):4.1f}% | {better}/{len(new)}")
        print(f"\n----- {arm}：同一场内 单人说话区 vs 重叠区（时长加权）-----")
        for spk in (None, 2, 3, 4):
            for model in ("old", "new"):
                R = [r for r in rows if r["arm"] == arm and r["model"] == model and (spk is None or r["spk"] == spk)]
                share = 100 * sum(r["o_total"] for r in R) / sum(r["total"] for r in R)
                print(f"  {('全部' if spk is None else f'{spk}人'):4s} {model}: 单人区 漏 {wavg(R, 's_miss', 's_total'):4.1f}% 混 {wavg(R, 's_conf', 's_total'):4.1f}% | "
                      f"重叠区 漏 {wavg(R, 'o_miss', 'o_total'):4.1f}% 混 {wavg(R, 'o_conf', 'o_total'):4.1f}%  (重叠区占语音 {share:.1f}%)")


if __name__ == "__main__":
    main()
