#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新旧声学模型回归对比：按 term_hit 列（设备口径 = 甲方口径）逐条 join 对齐。

用法：
  python3 compare_regression.py <baseline.tsv> <new.tsv> [--label-old 旧 --label-new 新]

输出：
  - 四域 + 整体 命中率对照（旧 / 新 / Δ）
  - 回退清单（旧 Y -> 新 N）
  - 改善清单（旧 N -> 新 Y）
"""
import argparse
import csv
import sys
from collections import defaultdict

CAT_FROM_PREFIX = {
    "vocab": "行业词汇",
    "appname": "应用名称",
    "specialcode": "特殊代码",
    "policedialog": "行业对话",
}
CAT_ORDER = ["行业词汇", "行业对话", "应用名称", "特殊代码"]


def cat_of(utt_id: str) -> str:
    pref = utt_id.split("_")[0]
    return CAT_FROM_PREFIX.get(pref, pref)


def load(path):
    rows = {}
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f, delimiter="\t")
        for row in r:
            uid = row.get("utt_id", "").strip()
            if not uid:
                continue
            rows[uid] = row
    return rows


def rate(rows, uids):
    tot = len(uids)
    hit = sum(1 for u in uids if rows[u].get("term_hit", "").strip() == "Y")
    return hit, tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("baseline")
    ap.add_argument("new")
    ap.add_argument("--label-old", default="旧模型")
    ap.add_argument("--label-new", default="新模型")
    args = ap.parse_args()

    old = load(args.baseline)
    new = load(args.new)

    common = sorted(set(old) & set(new))
    only_old = set(old) - set(new)
    only_new = set(new) - set(old)
    if only_old or only_new:
        print(f"[warn] 仅旧:{len(only_old)} 仅新:{len(only_new)}（只对比交集 {len(common)} 条）", file=sys.stderr)

    by_cat = defaultdict(list)
    for u in common:
        by_cat[cat_of(u)].append(u)

    print(f"\n{'类别':<8}{args.label_old:>12}{args.label_new:>12}{'Δ':>10}")
    print("-" * 44)
    cats = [c for c in CAT_ORDER if c in by_cat] + [c for c in by_cat if c not in CAT_ORDER]
    for c in cats:
        uids = by_cat[c]
        ho, to = rate(old, uids)
        hn, tn = rate(new, uids)
        ro, rn = 100 * ho / to, 100 * hn / tn
        print(f"{c:<9}{ho:>4}/{to:<4}{ro:>5.1f}%{hn:>5}/{tn:<4}{rn:>5.1f}%{rn-ro:>+9.1f}pp")
    ho, to = rate(old, common)
    hn, tn = rate(new, common)
    ro, rn = 100 * ho / to, 100 * hn / tn
    print("-" * 44)
    print(f"{'整体':<9}{ho:>4}/{to:<4}{ro:>5.1f}%{hn:>5}/{tn:<4}{rn:>5.1f}%{rn-ro:>+9.1f}pp")

    regress = [u for u in common
               if old[u].get("term_hit") == "Y" and new[u].get("term_hit") == "N"]
    improve = [u for u in common
               if old[u].get("term_hit") == "N" and new[u].get("term_hit") == "Y"]

    def show(title, uids):
        print(f"\n=== {title}（{len(uids)} 条）===")
        for u in uids:
            ref = old[u].get("ref_text", "")
            no = old[u].get("normalized", "")
            nn = new[u].get("normalized", "")
            print(f"[{cat_of(u)}] {u}  ref={ref}")
            print(f"    旧: {no}")
            print(f"    新: {nn}")

    show(f"回退（{args.label_old} Y → {args.label_new} N）", regress)
    show(f"改善（{args.label_old} N → {args.label_new} Y）", improve)

    print(f"\n净变化: 改善 +{len(improve)}  回退 -{len(regress)}  =净 {len(improve)-len(regress):+d} 条")


if __name__ == "__main__":
    main()
