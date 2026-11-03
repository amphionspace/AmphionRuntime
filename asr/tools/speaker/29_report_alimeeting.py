"""AliMeeting Eval 报告：标称容量内（2~4 人）的真实远场结果，以及近场/远场配对。

这是目前唯一能验证产品标称人数范围的真实数据集（客户现网只有 4 条）。
近场臂是同一场会议的耳麦混合，内容与说话人完全相同，差别只有房间与距离，
所以两臂之差就是**真实混响与距离的代价**。
"""
import glob
import importlib.util
import os
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "sc", os.path.join(HERE, "23_score_diarization_scenarios.py"))
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)

S = os.environ["SCRATCH"]
REF = f"{S}/ali"
PRED = f"{S}/ali_pred"


def load(arm):
    rows = []
    for ref_path in sorted(glob.glob(f"{REF}/{arm}/*.rttm")):
        name = os.path.basename(ref_path)[:-5]
        hyp_path = f"{PRED}/{arm}/{name}.rttm"
        if not os.path.isfile(hyp_path):
            continue
        ref = sc.read_rttm(ref_path)
        stats = sc.segment_stats(ref)
        metrics = sc.score_one(ref, sc.read_rttm(hyp_path), stats["duration"])
        rows.append(dict(name=name, **stats, **metrics))
    return rows


def show(arm, rows):
    print(f"\n=== {arm} 臂（{len(rows)} 场）===")
    print(f"{'场次':18s} {'人数':>4s} {'重叠':>6s} {'DER':>7s} {'漏检':>7s} {'误报':>7s} "
          f"{'混淆':>7s} {'覆盖':>6s} {'输出人数':>8s} {'跳变/人':>8s}")
    for r in rows:
        print(f"{r['name']:18s} {r['speakers']:>4d} {r['overlap_ratio']*100:>5.1f}% "
              f"{r['der']*100:>6.1f}% {r['miss_rate']*100:>6.1f}% {r['fa_rate']*100:>6.1f}% "
              f"{r['conf_rate']*100:>6.1f}% {r['coverage']*100:>5.0f}% {r['hyp_spk']:>8d} "
              f"{r['flips_per_speaker']:>8.1f}")
    w = np.array([r["total"] for r in rows])
    agg = lambda f: float(np.average([r[f] for r in rows], weights=w))
    print(f"{'加权':18s} {'':>4s} {'':>6s} {agg('der')*100:>6.1f}% "
          f"{agg('miss_rate')*100:>6.1f}% {agg('fa_rate')*100:>6.1f}% "
          f"{agg('conf_rate')*100:>6.1f}% {agg('coverage')*100:>5.0f}% "
          f"{'':>8s} {np.mean([r['flips_per_speaker'] for r in rows]):>8.1f}")
    print(f"  人数判对 {sum(r['speaker_count_correct'] for r in rows)}/{len(rows)}")


def by_count(arm, rows):
    buckets = defaultdict(list)
    for r in rows:
        buckets[r["speakers"]].append(r)
    print(f"\n--- {arm} 按人数（标称容量内）---")
    print(f"{'人数':>6s} {'场次':>4s} {'DER':>7s} {'漏检':>7s} {'混淆':>7s} "
          f"{'覆盖':>6s} {'人数判对':>8s}")
    for k in sorted(buckets):
        g = buckets[k]
        w = np.array([r["total"] for r in g])
        agg = lambda f: float(np.average([r[f] for r in g], weights=w))
        print(f"{k:>4d} 人 {len(g):>4d} {agg('der')*100:>6.1f}% "
              f"{agg('miss_rate')*100:>6.1f}% {agg('conf_rate')*100:>6.1f}% "
              f"{agg('coverage')*100:>5.0f}% "
              f"{sum(r['speaker_count_correct'] for r in g)}/{len(g):<8d}")


def main():
    far = load("far")
    near = load("near")
    if not far:
        print("远场臂还没有预测，先跑完推理")
        return
    show("远场 ch0", far)
    by_count("远场", far)
    if near:
        show("近场 耳麦混合", near)
        by_count("近场", near)
        print("\n=== 近场 vs 远场 配对（同场会议，差别只有房间与距离）===")
        nm = {r["name"]: r for r in near}
        print(f"{'场次':18s} {'人数':>4s} {'近场 DER':>9s} {'远场 DER':>9s} {'差':>8s} "
              f"{'近场混淆':>9s} {'远场混淆':>9s}")
        d = []
        for r in far:
            n = nm.get(r["name"])
            if not n:
                continue
            d.append(r["der"] - n["der"])
            print(f"{r['name']:18s} {r['speakers']:>4d} {n['der']*100:>8.1f}% "
                  f"{r['der']*100:>8.1f}% {(r['der']-n['der'])*100:>+7.1f}pp "
                  f"{n['conf_rate']*100:>8.1f}% {r['conf_rate']*100:>8.1f}%")
        print(f"\n  远场代价中位 {np.median(d)*100:+.1f}pp  "
              f"范围 {min(d)*100:+.1f}~{max(d)*100:+.1f}pp  "
              f"（{sum(1 for x in d if x > 0)}/{len(d)} 场远场更差）")


if __name__ == "__main__":
    main()
