#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UI 术语命中统计：pulled tsv × termmap，看目标 term 是否出现在交付输出 normalized 中。"""
import argparse, csv, os, sys
from collections import Counter

_P = set("，。、；：？！“”‘’（）()《》【】—…·,.;:?!\"'`~-_／/\\|　 \t\r\n")
def clean(s): return "".join(c for c in s if c not in _P)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tsv")
    ap.add_argument("--termmap", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    out_dir = os.path.abspath(args.out) if args.out else os.path.dirname(os.path.abspath(args.tsv))

    tm = {}
    for r in csv.DictReader(open(args.termmap), delimiter="\t"):
        tm[r["utt_id"]] = r["term"]
    rows = {r["utt_id"]: r for r in csv.DictReader(open(args.tsv), delimiter="\t")}

    n = hit = hit_raw = 0
    missed = []           # (term, utt, normalized)
    per_term = {}         # term -> [total, hit]
    for utt, term in tm.items():
        r = rows.get(utt)
        if not r:
            continue
        norm = clean(r.get("normalized", "")); raw = clean(r.get("asr_raw", ""))
        t = clean(term)
        h = t in norm
        n += 1; hit += h; hit_raw += (t in raw)
        per_term.setdefault(term, [0, 0]); per_term[term][0] += 1; per_term[term][1] += h
        if not h:
            missed.append((term, utt, r.get("normalized", "")))

    print(f"\n=== 警务 UI 术语命中率（{os.path.basename(os.path.dirname(os.path.abspath(args.tsv))) or args.tsv}）===")
    print(f"用例 {n} 条，目标词命中(normalized) {hit}  = {100*hit/max(1,n):.2f}%   （裸解码 raw {100*hit_raw/max(1,n):.2f}%）")
    # 逐词：两句都中 / 一句 / 全漏
    full = sum(1 for t, (a, b) in per_term.items() if b == a)
    part = sum(1 for t, (a, b) in per_term.items() if 0 < b < a)
    zero = sum(1 for t, (a, b) in per_term.items() if b == 0)
    print(f"逐词（{len(per_term)} 词）：两句全中 {full}，半中 {part}，全漏 {zero}")

    fpath = os.path.join(out_dir, "ui_missed.tsv")
    with open(fpath, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["term", "utt_id", "normalized"])
        for row in sorted(missed):
            w.writerow(row)
    print(f"\n[ui] 漏词明细 -> {fpath}  ({len(missed)} 条)")
    # 全漏的词（两句都没中，最该修）
    zero_terms = [t for t, (a, b) in per_term.items() if b == 0]
    if zero_terms:
        print(f"[ui] 全漏词（{len(zero_terms)}）: " + "，".join(zero_terms))


if __name__ == "__main__":
    main()
