#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
甲方口径术语命中率统计（验收主指标）：四个子领域各自「目标术语/话术是否被识别对」达 97%？

不看字准/整句，只看：每条造句里的**甲方清单目标词**有没有出现在交付输出(normalized)里。
词表来自甲方 警言警语_.txt（分【北京应用名称】【特殊代码】【行业词汇】【行业对话】四节）。

用法：
  python3 term_hit_report.py <police_terms_eval.tsv> --terms /path/警言警语_.txt [--out DIR]

输出：
  - 终端：四域 命中率（按词次 occurrence + 按整句 all-hit），对照 97%
  - term_hit_missed.tsv：逐条 miss（域/utt/目标词/normalized），供迭代
"""
import argparse
import csv
import os
import re
import sys
from collections import defaultdict

SECTIONS = {  # 词表节名 -> 类别 key（对齐 utt_id 前缀）
    "北京应用名称": "appname",
    "特殊代码": "specialcode",
    "行业词汇": "vocab",
    "行业对话": "dialog",
}
PREFIX2CAT = {"vocab_": "vocab", "appname_": "appname",
              "specialcode_": "specialcode", "policedialog_": "dialog"}
CAT_ORDER = ["appname", "specialcode", "vocab", "dialog"]
CAT_LABEL = {"appname": "应用名称", "specialcode": "特殊代码",
             "vocab": "行业词汇", "dialog": "行业对话"}
TARGET = 0.97

RADIO = {"幺": "1", "两": "2", "三": "3", "四": "4", "五": "5",
         "六": "6", "拐": "7", "八": "8", "勾": "9", "钩": "9", "洞": "0"}
_PUNCT = set("，。、；：？！“”‘’（）()《》【】〔〕—…·,.;:?!\"'`~-_／/\\|　 \t\r\n")


def clean(s):
    return "".join(c for c in s if c not in _PUNCT)


def cer(ref, hyp):
    """字错率 = Levenshtein(ref,hyp)/len(ref)，标点无关。行业对话口径用。"""
    a, b = clean(ref), clean(hyp)
    if not a:
        return 0.0
    n, m = len(a), len(b)
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        for j in range(1, m + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[m] / n


def clean_term(t):
    # 甲方词条清洗：去括号/连字符/空白，生成候选变体
    t = t.strip()
    variants = set()
    base = t.replace("-", "").replace("（", "").replace("）", "") \
            .replace("(", "").replace(")", "").replace(" ", "")
    if base:
        variants.add(base)
    # 括号内容视为可选后缀：治安移动警务（平台版）-> 也加 治安移动警务
    m = re.match(r"^(.*?)[（(].*?[）)]\s*$", t)
    if m and m.group(1).strip():
        variants.add(m.group(1).replace("-", "").strip())
    return {v for v in variants if v}


def parse_terms(path):
    sec = {v: [] for v in SECTIONS.values()}
    cur = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            m = re.match(r"^【(.+?)】$", s)
            if m:
                cur = SECTIONS.get(m.group(1).strip())
                continue
            if cur is None:
                continue
            if cur == "specialcode":
                continue  # 电台数字单独按 RADIO 处理
            for v in clean_term(s):
                if len(v) >= 2:  # 单字词噪声大，跳过（如某些单字），保留≥2
                    sec[cur].append(v)
    # 每节去重 + 按长度降序（最长匹配）
    for k in sec:
        sec[k] = sorted(set(sec[k]), key=len, reverse=True)
    return sec


def longest_match_terms(ref, terms):
    """非重叠最长匹配，返回命中的目标词列表（按出现顺序，可重复）。"""
    text = clean(ref)
    tset = terms  # 已按长度降序
    # 为效率：用 set 快速判断，逐位扫描
    tlens = sorted({len(t) for t in tset}, reverse=True)
    tby = set(tset)
    out = []
    i = 0
    n = len(text)
    while i < n:
        matched = None
        for L in tlens:
            if i + L <= n and text[i:i + L] in tby:
                matched = text[i:i + L]
                break
        if matched:
            out.append(matched)
            i += len(matched)
        else:
            i += 1
    return out


def specialcode_codes(ref):
    """提取 ref 中的电台数字码（≥2 连续电台字），返回 [(radio, arabic)]。"""
    text = clean(ref)
    out = []
    run = []
    for ch in text + "　":  # 末尾补全角空格，flush 结尾的码
        if ch in RADIO:
            run.append(ch)
        else:
            if len(run) >= 2:
                radio = "".join(run)
                arabic = "".join(RADIO[c] for c in run)
                out.append((radio, arabic))
            run = []
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tsv")
    ap.add_argument("--terms", required=True, help="甲方 警言警语_.txt")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    tsv_path = os.path.abspath(args.tsv)
    out_dir = os.path.abspath(args.out) if args.out else os.path.dirname(tsv_path)
    sec = parse_terms(args.terms)

    rows = {}
    with open(tsv_path, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            rows[r.get("utt_id", "")] = r
    rows = list(rows.values())

    # 统计容器
    occ = defaultdict(lambda: [0, 0])   # 词次：[total, hit]（hit=normalized 命中）
    utt = defaultdict(lambda: [0, 0])   # 整句：[有目标词的utt, 全命中utt]
    dlg = [0, 0]                         # 行业对话字准：[编辑距离和, ref字数和]
    dlg_n = 0
    missed = []                          # (cat, utt_id, term, normalized)

    for r in rows:
        u = r.get("utt_id", "")
        cat = next((c for p, c in PREFIX2CAT.items() if u.startswith(p)), None)
        if cat is None:
            continue
        norm = clean(r.get("normalized", ""))
        raw = clean(r.get("asr_raw", ""))

        if cat == "dialog":
            # 甲方口径：话术按字准 1−CER（不逐字整条命中）
            ref = r.get("ref_text", "")
            a = clean(ref)
            if a:
                dist = round(cer(ref, r.get("normalized", "")) * len(a))
                dlg[0] += dist
                dlg[1] += len(a)
                dlg_n += 1
            continue

        if cat == "specialcode":
            codes = specialcode_codes(r.get("ref_text", ""))
            targets = codes  # list of (radio, arabic)
            if not targets:
                continue
            all_hit = True
            for radio, arabic in targets:
                hit = (arabic in norm) or (radio in norm)
                occ[cat][0] += 1
                if hit:
                    occ[cat][1] += 1
                else:
                    all_hit = False
                    missed.append((cat, u, f"{radio}→{arabic}", r.get("normalized", "")))
            utt[cat][0] += 1
            if all_hit:
                utt[cat][1] += 1
            continue

        terms = longest_match_terms(r.get("ref_text", ""), sec[cat])
        if not terms:
            continue
        all_hit = True
        for t in terms:
            hit = t in norm
            occ[cat][0] += 1
            if hit:
                occ[cat][1] += 1
            else:
                all_hit = False
                missed.append((cat, u, t, r.get("normalized", "")))
        utt[cat][0] += 1
        if all_hit:
            utt[cat][1] += 1

    # 输出
    def pct(a, b):
        return f"{100.0*a/b:.2f}%" if b else "n/a"

    print(f"\n=== 甲方口径 术语命中率（{os.path.basename(os.path.dirname(tsv_path)) or tsv_path}）目标 ≥{int(TARGET*100)}% ===")
    print("命中=目标词出现在交付输出 normalized 中。词次=按术语出现次数；整句=该句所有目标词全中。")
    print(f"{'子领域':8s} {'目标词次':>8s} {'词次命中':>9s}  {'含词句数':>8s} {'整句全中':>9s}  判定")
    for cat in CAT_ORDER:
        if cat == "dialog":
            if dlg_n == 0:
                print(f"{CAT_LABEL[cat]:8s} {'(无数据)':>8s}")
                continue
            char_acc = 1 - dlg[0] / max(1, dlg[1])
            flag = "✅达标" if char_acc >= TARGET else "❌未达"
            print(f"{CAT_LABEL[cat]:8s} {dlg_n:8d} {'字准':>9s}  {'—':>8s} {pct(int(char_acc*10000),10000):>9s}  {flag}(字准1−CER)")
            continue
        ot, oh = occ[cat]
        ut, uh = utt[cat]
        if ot == 0:
            print(f"{CAT_LABEL[cat]:8s} {'(无数据)':>8s}")
            continue
        occ_rate = oh / ot
        flag = "✅达标" if occ_rate >= TARGET else "❌未达"
        print(f"{CAT_LABEL[cat]:8s} {ot:8d} {pct(oh,ot):>9s}  {ut:8d} {pct(uh,ut):>9s}  {flag}(词次)")

    # missed 落盘 + top 漏词
    mpath = os.path.join(out_dir, "term_hit_missed.tsv")
    with open(mpath, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["category", "utt_id", "missed_term", "normalized"])
        for row in sorted(missed):
            w.writerow(row)
    print(f"\n[term-hit] 漏词明细 -> {mpath}  ({len(missed)} 条)")
    # top missed per cat
    from collections import Counter
    for cat in CAT_ORDER:
        cnt = Counter(m[2] for m in missed if m[0] == cat)
        if cnt:
            top = "，".join(f"{t}×{n}" for t, n in cnt.most_common(12))
            print(f"  [{CAT_LABEL[cat]}] top漏词: {top}")


if __name__ == "__main__":
    main()
