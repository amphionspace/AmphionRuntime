#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析真机拉回的 police_terms_eval.tsv，出分类别基线：
  - 每类 & 总体：条数、字准/CER、整句准确率（标点无关）、术语命中率、空/错条数
  - failures.tsv       非整句命中的用例（含 CER、缺失术语），供人工分诊
  - confusion_pairs.tsv 相邻编辑合并出的词级混淆对 (ref_seg -> hyp_seg) 频次，喂 Phase 3

整句准确率同时给两口径：
  - device_sent_match ：设备侧 sent_match 列（标点敏感，偏严，仅参考）
  - sent_acc          ：标点/空白无关重算（对甲方口径），normalized 与 ref 归一后相等

引擎输出取 `normalized` 列（= V2 后处理后，交付默认）；同时附 asr_raw 口径看 V2 增益。

用法：
  python3 analyze_police_terms_eval.py round_baseline/police_terms_eval.tsv --out round_baseline
"""
import argparse
import csv
import os
import sys
from collections import Counter

# utt_id 前缀 -> 类别 key（本批 20260711）
PREFIX2CAT = {
    "vocab_": "vocab",
    "appname_": "appname",
    "specialcode_": "specialcode",
    "policedialog_": "dialog",
}
CAT_ORDER = ["dialog", "vocab", "appname", "specialcode"]
CAT_LABEL = {
    "dialog": "行业对话",
    "vocab": "行业词汇",
    "appname": "应用名称",
    "specialcode": "特殊代码",
}
# 分类别验收目标（甲方口径：字准 char_acc = 1 - CER 为主，整句 sent_acc 仅参考）
CAT_TARGET = {"dialog": 0.98, "vocab": 0.95, "appname": 0.90, "specialcode": 0.90}

_PUNCT = set("，。、；：？！“”‘’（）()《》【】〔〕—…·,.;:?!\"'`~-_／/\\|　 \t\r\n")


def cat_of(utt_id):
    for pfx, cat in PREFIX2CAT.items():
        if utt_id.startswith(pfx):
            return cat
    return "other"


def clean(s):
    """去标点/空白，用于 CER 与整句比对。"""
    return "".join(ch for ch in s if ch not in _PUNCT)


def edits(ref, hyp):
    """Levenshtein 距离 + 回溯操作序列。返回 (dist, ops)。
    ops 元素： ('=', rc, hc) | ('s', rc, hc) | ('d', rc, '') | ('i', '', hc)"""
    n, m = len(ref), len(hyp)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
    # 回溯
    ops = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and ref[i - 1] == hyp[j - 1] and dp[i][j] == dp[i - 1][j - 1]:
            ops.append(("=", ref[i - 1], hyp[j - 1])); i -= 1; j -= 1
        elif i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + 1:
            ops.append(("s", ref[i - 1], hyp[j - 1])); i -= 1; j -= 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            ops.append(("d", ref[i - 1], "")); i -= 1
        else:
            ops.append(("i", "", hyp[j - 1])); j -= 1
    ops.reverse()
    return dp[n][m], ops


def merge_confusions(ops):
    """把相邻的 s/d/i 合并成词级混淆对 (ref_seg -> hyp_seg)。"""
    pairs = []
    rbuf, hbuf = [], []
    for op, rc, hc in ops:
        if op == "=":
            if rbuf or hbuf:
                pairs.append(("".join(rbuf), "".join(hbuf)))
                rbuf, hbuf = [], []
        else:
            if rc:
                rbuf.append(rc)
            if hc:
                hbuf.append(hc)
    if rbuf or hbuf:
        pairs.append(("".join(rbuf), "".join(hbuf)))
    return pairs


def pct(x):
    return f"{100.0 * x:.2f}%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tsv", help="police_terms_eval.tsv 路径")
    ap.add_argument("--out", default=None, help="输出目录（默认与 tsv 同目录）")
    args = ap.parse_args()

    tsv_path = os.path.abspath(args.tsv)
    out_dir = os.path.abspath(args.out) if args.out else os.path.dirname(tsv_path)
    os.makedirs(out_dir, exist_ok=True)

    rows = []
    with open(tsv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for r in reader:
            rows.append(r)
    if not rows:
        sys.exit(f"[analyze] 空文件: {tsv_path}")

    # 按 utt_id 去重（断点续跑可能重复；保留最后一次）
    dedup = {}
    for r in rows:
        dedup[r.get("utt_id", "")] = r
    rows = list(dedup.values())

    # 分类别累计
    stats = {c: dict(n=0, cer_num=0, cer_den=0, sent_ok=0, dev_sent_ok=0,
                     term_total=0, term_hit=0, empty=0,
                     raw_cer_num=0, raw_sent_ok=0) for c in CAT_ORDER}
    stats["other"] = dict(stats["dialog"]);
    for k in stats["other"]:
        stats["other"][k] = 0

    failures = []
    confusion = Counter()

    for r in rows:
        utt = r.get("utt_id", "")
        cat = cat_of(utt)
        st = stats.setdefault(cat, dict(n=0, cer_num=0, cer_den=0, sent_ok=0, dev_sent_ok=0,
                                        term_total=0, term_hit=0, empty=0,
                                        raw_cer_num=0, raw_sent_ok=0))
        ref = r.get("ref_text", "")
        hyp = r.get("normalized", "")
        raw = r.get("asr_raw", "")
        exp_terms = [t for t in r.get("expected_terms", "").split(",") if t]
        dev_term_hit = r.get("term_hit", "") == "Y"
        dev_sent = r.get("sent_match", "") == "Y"

        cref, chyp, craw = clean(ref), clean(hyp), clean(raw)
        dist, ops = edits(cref, chyp)
        cer = dist / max(1, len(cref))
        sent_ok = (cref == chyp and cref != "")
        raw_dist, _ = edits(cref, craw)

        st["n"] += 1
        st["cer_num"] += dist
        st["cer_den"] += len(cref)
        st["raw_cer_num"] += raw_dist
        if sent_ok:
            st["sent_ok"] += 1
        if cref == craw and cref != "":
            st["raw_sent_ok"] += 1
        if dev_sent:
            st["dev_sent_ok"] += 1
        if exp_terms:
            st["term_total"] += 1
            if dev_term_hit:
                st["term_hit"] += 1
        if not chyp:
            st["empty"] += 1

        if not sent_ok:
            failures.append(dict(
                category=cat, utt_id=utt, cer=f"{cer:.3f}",
                ref_text=ref, normalized=hyp, asr_raw=raw,
                missed_terms=r.get("term_miss_detail", ""),
            ))
            for rseg, hseg in merge_confusions(ops):
                confusion[(cat, rseg, hseg)] += 1

    # ---- 打印汇总 ----
    def line(cat):
        st = stats.get(cat)
        if not st or st["n"] == 0:
            return None
        cer = st["cer_num"] / max(1, st["cer_den"])
        raw_cer = st["raw_cer_num"] / max(1, st["cer_den"])
        char_acc = 1.0 - cer  # 字准 = 验收主口径
        sent_acc = st["sent_ok"] / st["n"]
        raw_sent = st["raw_sent_ok"] / st["n"]
        dev_sent = st["dev_sent_ok"] / st["n"]
        term = (st["term_hit"] / st["term_total"]) if st["term_total"] else float("nan")
        tgt = CAT_TARGET.get(cat)
        flag = ""
        if tgt is not None:
            # 验收按字准判定（甲方口径）
            flag = "  ✅达标" if char_acc >= tgt else f"  ❌未达({pct(tgt)})"
        term_s = "n/a" if st["term_total"] == 0 else pct(term)
        return (f"  {CAT_LABEL.get(cat, cat):6s} n={st['n']:<5d} "
                f"字准={pct(char_acc)} "
                f"整句={pct(sent_acc)} "
                f"CER={pct(cer)}(raw {pct(raw_cer)}) "
                f"术语={term_s} 空={st['empty']}{flag}")

    print(f"\n=== police_terms 基线（{os.path.basename(os.path.dirname(tsv_path)) or tsv_path}）===")
    print(f"数据行(去重后): {len(rows)}")
    print("分类别（字准=1−CER 验收主口径；整句=标点无关 exact；术语=设备 term_hit；✅/❌ 按字准判）:")
    tot = dict(n=0, cer_num=0, cer_den=0, sent_ok=0)
    for cat in CAT_ORDER + [c for c in stats if c not in CAT_ORDER]:
        l = line(cat)
        if l:
            print(l)
            st = stats[cat]
            tot["n"] += st["n"]; tot["cer_num"] += st["cer_num"]
            tot["cer_den"] += st["cer_den"]; tot["sent_ok"] += st["sent_ok"]
    if tot["n"]:
        print(f"  {'总体':6s} n={tot['n']:<5d} 整句={pct(tot['sent_ok']/tot['n'])} "
              f"CER={pct(tot['cer_num']/max(1,tot['cer_den']))}")

    # ---- failures.tsv ----
    fpath = os.path.join(out_dir, "failures.tsv")
    with open(fpath, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, delimiter="\t",
                           fieldnames=["category", "utt_id", "cer", "ref_text",
                                       "normalized", "asr_raw", "missed_terms"])
        w.writeheader()
        for row in sorted(failures, key=lambda x: (x["category"], -float(x["cer"]))):
            w.writerow(row)

    # ---- confusion_pairs.tsv ----
    cpath = os.path.join(out_dir, "confusion_pairs.tsv")
    with open(cpath, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["category", "ref_seg", "hyp_seg", "count", "equal_len"])
        for (cat, rseg, hseg), cnt in confusion.most_common():
            w.writerow([cat, rseg, hseg, cnt, "Y" if len(rseg) == len(hseg) else "N"])

    print(f"\n[analyze] failures      -> {fpath}  ({len(failures)} 条)")
    print(f"[analyze] confusion_pairs-> {cpath}  ({len(confusion)} 对)")


if __name__ == "__main__":
    main()
