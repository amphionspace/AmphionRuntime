"""合成场景的分组报告：每组 5 个独立样本，报中位与极差，不只报均值。

为什么要报离散度：两条 +5/−5 与两条 0/0 的均值都是 0。单看均值会把"有升有降"抹平。
"""
import importlib.util
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "sc", os.path.join(HERE, "23_score_diarization_scenarios.py"))
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)

S = os.environ["SCRATCH"]
SYNTH = f"{S}/synth"
PRED = f"{S}/synth_pred"

ORDER = ["2人-sequential", "2人-roundrobin", "3人-sequential", "3人-roundrobin",
         "4人-sequential", "4人-roundrobin", "单人-5分钟",
         "段长1s", "段长2s", "段长3s", "段长5s", "段长10s",
         "SNR20dB", "SNR15dB", "SNR10dB", "SNR5dB"]


def main():
    index = json.load(open(f"{SYNTH}/index.json"))
    groups = {}
    for item in index:
        hyp_path = f"{PRED}/{item['name']}.rttm"
        if not os.path.isfile(hyp_path):
            continue
        ref = sc.read_rttm(f"{SYNTH}/{item['name']}.rttm")
        hyp = sc.read_rttm(hyp_path)
        m = sc.score_one(ref, hyp, item["duration"])
        groups.setdefault(item["group"], []).append(m)

    print(f"{'场景':16s} {'样本':>4s} {'真实人数':>6s} {'输出人数':>12s} {'DER中位':>8s} "
          f"{'DER极差':>8s} {'漏检':>7s} {'误报':>7s} {'混淆':>7s} {'覆盖':>6s} {'跳变/人':>8s}")
    for name in ORDER:
        rows = groups.get(name)
        if not rows:
            continue
        der = np.array([r["der"] for r in rows])
        hyp_spk = [r["hyp_spk"] for r in rows]
        ref_spk = rows[0]["ref_spk"]
        print(f"{name:16s} {len(rows):>4d} {ref_spk:>6d} "
              f"{str(sorted(set(hyp_spk))):>12s} {np.median(der)*100:>7.1f}% "
              f"{(der.max()-der.min())*100:>7.1f}% "
              f"{np.median([r['miss_rate'] for r in rows])*100:>6.1f}% "
              f"{np.median([r['fa_rate'] for r in rows])*100:>6.1f}% "
              f"{np.median([r['conf_rate'] for r in rows])*100:>6.1f}% "
              f"{np.median([r['coverage'] for r in rows])*100:>5.0f}% "
              f"{np.median([r['flips_per_speaker'] for r in rows]):>8.1f}")

    print("\n=== 依次 vs 轮询（同人数直接对比）===")
    for n in (2, 3, 4):
        a = groups.get(f"{n}人-sequential")
        b = groups.get(f"{n}人-roundrobin")
        if not a or not b:
            continue
        da = np.median([r["der"] for r in a]) * 100
        db = np.median([r["der"] for r in b]) * 100
        ca = sum(r["speaker_count_correct"] for r in a)
        cb = sum(r["speaker_count_correct"] for r in b)
        print(f"  {n} 人：依次 DER {da:5.1f}%（人数判对 {ca}/{len(a)}）  "
              f"轮询 DER {db:5.1f}%（{cb}/{len(b)}）  差 {da-db:+.1f}pp")


if __name__ == "__main__":
    main()
