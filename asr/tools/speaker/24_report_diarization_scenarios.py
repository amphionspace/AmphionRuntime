"""场景级报告：把逐场次指标按人数、房间、重叠率、段长分档切片。

用法：
    SCRATCH=<目录> .venv-speaker/bin/python asr/tools/speaker/24_report_diarization_scenarios.py

依赖 23_score_diarization_scenarios.py 的评分函数（同口径：10 ms 栅格、collar 0、
计重叠、Hungarian），输入是 AISHELL-4 的参考 RTTM 与新模型预测 RTTM。
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
REF_DIR = os.path.expanduser(
    "~/Downloads/aishell4/DATA_ASR/LHOTSE/data_aishell4/test/TextGrid")
HYP_DIR = f"{S}/a4_pred"
ROOM = {"L": "大会议室", "M": "中会议室", "S": "小会议室"}


def load():
    rows = []
    for ref_path in sorted(glob.glob(f"{REF_DIR}/*.rttm")):
        name = os.path.basename(ref_path)[:-5]
        hyp_path = f"{HYP_DIR}/{name}.rttm"
        if not os.path.isfile(hyp_path):
            continue
        ref = sc.read_rttm(ref_path)
        hyp = sc.read_rttm(hyp_path)
        stats = sc.segment_stats(ref)
        metrics = sc.score_one(ref, hyp, stats["duration"])
        rows.append(dict(name=name, room=ROOM.get(name[0], "?"), **stats, **metrics))
    return rows


def show(rows):
    print(f"{'场次':18s} {'房间':6s} {'人数':>4s} {'DER':>7s} "
          f"{'漏检':>7s} {'误报':>7s} {'混淆':>7s} {'覆盖':>6s} {'输出人数':>8s} {'跳变/人':>8s}")
    for r in sorted(rows, key=lambda x: x["name"]):
        print(f"{r['name']:18s} {r['room']:6s} {r['speakers']:>4d} "
              f"{r['der']*100:>6.1f}% {r['miss_rate']*100:>6.1f}% {r['fa_rate']*100:>6.1f}% "
              f"{r['conf_rate']*100:>6.1f}% {r['coverage']*100:>5.0f}% {r['hyp_spk']:>8d} "
              f"{r['flips_per_speaker']:>8.1f}")


def group(rows, key, label, fmt="{}"):
    buckets = defaultdict(list)
    for r in rows:
        buckets[key(r)].append(r)
    print(f"\n=== 按{label}切片 ===")
    print(f"{label:>12s} {'场次':>4s} {'DER':>7s} {'漏检':>7s} {'误报':>7s} "
          f"{'混淆':>7s} {'覆盖':>6s} {'跳变/人':>8s}")
    for k in sorted(buckets):
        g = buckets[k]
        # 按参考说话人时长加权，避免短场次等权拉偏
        w = np.array([r["total"] for r in g])
        agg = lambda f: float(np.average([r[f] for r in g], weights=w))
        print(f"{fmt.format(k):>12s} {len(g):>4d} {agg('der')*100:>6.1f}% "
              f"{agg('miss_rate')*100:>6.1f}% {agg('fa_rate')*100:>6.1f}% "
              f"{agg('conf_rate')*100:>6.1f}% {agg('coverage')*100:>5.0f}% "
              f"{float(np.mean([r['flips_per_speaker'] for r in g])):>8.1f}")


def main():
    rows = load()
    if not rows:
        print("没有可评分的场次，先跑完预测")
        return
    print(f"共 {len(rows)} 场，参考说话人时长合计 {sum(r['total'] for r in rows)/60:.0f} 分钟\n")
    show(rows)
    group(rows, lambda r: r["speakers"], "人数", "{} 人")
    group(rows, lambda r: r["room"], "房间")
    group(rows, lambda r: ("0~2%" if r["overlap_ratio"] < 0.02 else
                           "2~6%" if r["overlap_ratio"] < 0.06 else "6%+"), "重叠率")
    group(rows, lambda r: ("<2.5s" if r["turn_median"] < 2.5 else
                           "2.5~4s" if r["turn_median"] < 4 else "4s+"), "段长中位")
    w = np.array([r["total"] for r in rows])
    print(f"\n全集加权 DER {float(np.average([r['der'] for r in rows], weights=w))*100:.2f}%"
          f"   人数判对 {sum(r['speaker_count_correct'] for r in rows)}/{len(rows)}"
          f"   覆盖率 {float(np.average([r['coverage'] for r in rows], weights=w))*100:.0f}%")


if __name__ == "__main__":
    main()
