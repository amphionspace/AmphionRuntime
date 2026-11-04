"""新旧模型在**同场景、同音频**上的并排对比。

此前的场景报告里只有客户 4 条有新旧对比，其余全是新模型单臂。本脚本把 32_ 跑出的
旧模型（community-1：pyannote + eres2net + 聚类，已在客户 4 条上精确复现归档数字）
与新模型（Sortformer）放到同一批音频上逐场对照。

用法：SCRATCH=<目录> python 34_report_old_vs_new.py
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


def score_dir(ref_dir, hyp_dir):
    """返回 {场次名: 指标}；两臂缺任一则跳过该场，保证逐场可比。"""
    out = {}
    for ref_path in sorted(glob.glob(f"{ref_dir}/*.rttm")):
        name = os.path.basename(ref_path)[:-5]
        hyp = f"{hyp_dir}/{name}.rttm"
        if not os.path.isfile(hyp):
            continue
        ref = sc.read_rttm(ref_path)
        st = sc.segment_stats(ref)
        m = sc.score_one(ref, sc.read_rttm(hyp), st["duration"])
        m.update(st)
        out[name] = m
    return out


def wavg(rows, key):
    w = np.array([r["total"] for r in rows])
    return float(np.average([r[key] for r in rows], weights=w))


def alimeeting(arm="far"):
    new, old = {}, {}
    for s in ("ali", "alitest"):
        new.update(score_dir(f"{S}/{s}/{arm}", f"{S}/{s}_pred/{arm}"))
        old.update(score_dir(f"{S}/{s}/{arm}", f"{S}/{s}_old/{arm}"))
    names = sorted(set(new) & set(old))
    if not names:
        print(f"[{arm}] 两臂没有共同场次"); return
    print(f"\n=== AliMeeting {arm}：{len(names)} 场逐场对比（同音频）===")
    print(f"{'场次':14s} {'人数':>4s} {'旧 DER':>8s} {'新 DER':>8s} {'差':>8s} "
          f"{'旧混淆':>7s} {'新混淆':>7s} {'旧人数':>6s} {'新人数':>6s}")
    better = 0
    for n in names:
        o, w = old[n], new[n]
        d = (w["der"] - o["der"]) * 100
        better += d < 0
        print(f"{n:14s} {o['speakers']:>4d} {o['der']*100:>7.1f}% {w['der']*100:>7.1f}% "
              f"{d:>+7.1f}pp {o['conf_rate']*100:>6.1f}% {w['conf_rate']*100:>6.1f}% "
              f"{o['hyp_spk']:>6d} {w['hyp_spk']:>6d}")
    print(f"\n新模型更好的场次：{better}/{len(names)}")

    print(f"\n--- 按人数（时长加权）---")
    print(f"{'人数':>5s} {'场次':>4s} {'旧 DER':>8s} {'新 DER':>8s} {'差':>8s} "
          f"{'旧混淆':>7s} {'新混淆':>7s} {'旧判对':>6s} {'新判对':>6s}")
    by = defaultdict(list)
    for n in names:
        by[new[n]["speakers"]].append(n)
    for k in sorted(by):
        on = [old[n] for n in by[k]]; nn = [new[n] for n in by[k]]
        print(f"{k:>4d}人 {len(by[k]):>4d} {wavg(on,'der')*100:>7.1f}% {wavg(nn,'der')*100:>7.1f}% "
              f"{(wavg(nn,'der')-wavg(on,'der'))*100:>+7.1f}pp "
              f"{wavg(on,'conf_rate')*100:>6.1f}% {wavg(nn,'conf_rate')*100:>6.1f}% "
              f"{sum(r['speaker_count_correct'] for r in on):>3d}/{len(on):<2d} "
              f"{sum(r['speaker_count_correct'] for r in nn):>3d}/{len(nn):<2d}")
    on = [old[n] for n in names]; nn = [new[n] for n in names]
    print(f"\n{'合计':>5s} {len(names):>4d} {wavg(on,'der')*100:>7.1f}% {wavg(nn,'der')*100:>7.1f}% "
          f"{(wavg(nn,'der')-wavg(on,'der'))*100:>+7.1f}pp "
          f"{wavg(on,'conf_rate')*100:>6.1f}% {wavg(nn,'conf_rate')*100:>6.1f}% "
          f"{sum(r['speaker_count_correct'] for r in on):>3d}/{len(on):<2d} "
          f"{sum(r['speaker_count_correct'] for r in nn):>3d}/{len(nn):<2d}")
    print(f"  旧模型多报/少报：{sum(r['hyp_spk']>r['speakers'] for r in on)}/{sum(r['hyp_spk']<r['speakers'] for r in on)}"
          f"   新模型多报/少报：{sum(r['hyp_spk']>r['speakers'] for r in nn)}/{sum(r['hyp_spk']<r['speakers'] for r in nn)}")
    print("  注：旧模型给定 num_clusters=4，所以 4 人场它必然判对、2/3 人场必然多报——人数判对一列对旧模型不公平，看 DER 与混淆。")


def controlled():
    import json
    print("\n=== 受控单轴（真实会议说话人；每组 5 样本取中位）===")
    print(f"{'场景':18s} {'旧 DER':>8s} {'新 DER':>8s} {'差':>8s} {'旧混淆':>7s} {'新混淆':>7s} {'旧漏检':>7s} {'新漏检':>7s}")
    for s in ("synth3", "synth4", "synth5", "synth6"):
        idx_path = f"{S}/{s}/index.json"
        if not os.path.isfile(idx_path):
            continue
        groups = defaultdict(list)
        for it in json.load(open(idx_path)):
            groups[it["group"]].append(it)
        for g, items in groups.items():
            o, n = [], []
            for it in items:
                ref = sc.read_rttm(f"{S}/{s}/{it['name']}.rttm")
                ho, hn = f"{S}/{s}_old/{it['name']}.rttm", f"{S}/{s}_pred/{it['name']}.rttm"
                if not (os.path.isfile(ho) and os.path.isfile(hn)):
                    continue
                o.append(sc.score_one(ref, sc.read_rttm(ho), it["duration"]))
                n.append(sc.score_one(ref, sc.read_rttm(hn), it["duration"]))
            if not o:
                continue
            med = lambda rows, k: float(np.median([r[k] for r in rows])) * 100
            print(f"{g:18s} {med(o,'der'):>7.1f}% {med(n,'der'):>7.1f}% {med(n,'der')-med(o,'der'):>+7.1f}pp "
                  f"{med(o,'conf_rate'):>6.1f}% {med(n,'conf_rate'):>6.1f}% "
                  f"{med(o,'miss_rate'):>6.1f}% {med(n,'miss_rate'):>6.1f}%")


if __name__ == "__main__":
    alimeeting("far")
    alimeeting("near")
    controlled()
