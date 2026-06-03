#!/usr/bin/env python3
"""TS-ASR 评估汇总：读 03_eval.py 输出的 JSONL，算 baseline vs 方案 A 指标。

第一性原理设计：

1. baseline = 所有 cut 直接用 ASR hypothesis 与 reference 算 CER/WER，无门控
2. 方案 A @ threshold = verify_score 跨过阈值则采纳 hypothesis，否则视为空字符串
3. 与 sample_type 交叉：
   - positive: 期望 verify pass → 算 CER/WER。ref 不空，hyp 看是否被采纳
   - negative_distractor / negative_silence: 期望 verify reject → 算
     false_alarm_rate（采纳的占比）。这两类 ref 文本意义已变（不是 target 的 GT）

关键指标定义（micro 口径）：

- CER (字符) / WER (词)：sum(edit_distance) / sum(ref_len)，与 jiwer 默认一致
- FAR @ thr = (#negatives with score >= thr) / (#total negatives)
- FRR @ thr = (#positives with score <  thr) / (#total positives)
- EER = 让 FAR == FRR 的阈值；对 score 网格扫描线性内插

边界处理：

- verify_score 为 None（段长 < min_seg_sec）：视为 reject（方案 A 不采纳），
  统计上记到 "score_missing" 桶
- ref 为空：跳过 CER/WER 累加（不会让某条 negative 把分母拖到 0）
- hyp 为空 + ref 不空：CER/WER = 100%（编辑距离 = ref 长度）

用法：

    python tools/speaker/04_eval_summary.py \
        --jsonl tools/speaker/results/eval_sanity.jsonl \
        --out-json tools/speaker/results/eval_sanity_summary.json \
        --out-md   tools/speaker/results/eval_sanity_summary.md
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional


# ---------- 文本归一与编辑距离 ----------

def normalize_zh(text: str) -> list[str]:
    """中文按字符切，去除空白与英文标点。"""
    out: list[str] = []
    for ch in text:
        if ch.isspace():
            continue
        # 通用标点过滤；保留汉字 / 数字 / 英文字符
        if ch in ",.!?;:'\"，。！？；：、《》（）()[]{}-—…":
            continue
        out.append(ch)
    return out


def normalize_en(text: str) -> list[str]:
    """英文按空格切词，全部小写化，去标点。"""
    cleaned = []
    for ch in text:
        if ch.isalnum() or ch.isspace() or ch == "'":
            cleaned.append(ch.lower())
        else:
            cleaned.append(" ")
    return [t for t in "".join(cleaned).split() if t]


def edit_distance(a: list[str], b: list[str]) -> int:
    """标准 Levenshtein，O(len(a)*len(b)) 时空。"""
    if not a:
        return len(b)
    if not b:
        return len(a)
    n, m = len(a), len(b)
    if n < m:
        a, b = b, a
        n, m = m, n
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        curr = [i] + [0] * m
        for j in range(1, m + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[m]


def tokenize(text: str, language: str) -> list[str]:
    if (language or "").lower().startswith("zh"):
        return normalize_zh(text)
    return normalize_en(text)


# ---------- 累加器 ----------

@dataclass
class CerWerAccumulator:
    """累加 numerator 与 denominator，最后除一次（micro 平均）。"""
    edit_sum: int = 0
    ref_len_sum: int = 0
    n_samples: int = 0
    n_ref_empty: int = 0  # 跳过的样本数

    def add(self, ref: str, hyp: str, language: str) -> None:
        ref_tokens = tokenize(ref, language)
        hyp_tokens = tokenize(hyp, language)
        if not ref_tokens:
            self.n_ref_empty += 1
            return
        self.edit_sum += edit_distance(ref_tokens, hyp_tokens)
        self.ref_len_sum += len(ref_tokens)
        self.n_samples += 1

    def rate(self) -> Optional[float]:
        if self.ref_len_sum == 0:
            return None
        return self.edit_sum / self.ref_len_sum


# ---------- 阈值扫描 ----------

def sweep_far_frr(
    pos_scores: list[Optional[float]],
    neg_scores: list[Optional[float]],
    *,
    grid: Optional[list[float]] = None,
) -> list[dict]:
    """对阈值网格扫描算 FAR / FRR / accuracy。

    score=None 视为 reject（方案 A 不采纳）；这样 None 在 positive 里贡献 FRR=1，
    在 negative 里贡献 FAR=0。
    """
    if grid is None:
        grid = [round(0.10 + i * 0.025, 4) for i in range(int((0.85 - 0.10) / 0.025) + 1)]
    pos_total = len(pos_scores)
    neg_total = len(neg_scores)

    rows: list[dict] = []
    for thr in grid:
        fa = 0
        for s in neg_scores:
            if s is not None and s >= thr:
                fa += 1
        fr = 0
        for s in pos_scores:
            if s is None or s < thr:
                fr += 1
        far = fa / neg_total if neg_total else None
        frr = fr / pos_total if pos_total else None
        rows.append(
            {
                "threshold": thr,
                "far": far,
                "frr": frr,
                "fa_count": fa,
                "fr_count": fr,
                "neg_total": neg_total,
                "pos_total": pos_total,
            }
        )
    return rows


def find_eer(rows: list[dict]) -> dict:
    """从 sweep 结果里找 EER（FAR ≈ FRR）。线性内插。"""
    best = None
    for i in range(len(rows) - 1):
        a, b = rows[i], rows[i + 1]
        if a["far"] is None or a["frr"] is None or b["far"] is None or b["frr"] is None:
            continue
        diff_a = a["far"] - a["frr"]
        diff_b = b["far"] - b["frr"]
        if diff_a == 0:
            return {"threshold": a["threshold"], "eer": a["far"]}
        if diff_a * diff_b < 0:
            t = diff_a / (diff_a - diff_b)
            thr = a["threshold"] + t * (b["threshold"] - a["threshold"])
            far = a["far"] + t * (b["far"] - a["far"])
            return {"threshold": round(thr, 4), "eer": round(far, 4)}
        if best is None or abs(diff_a) < abs(best[0]):
            best = (abs(diff_a), a)
    if best is not None:
        a = best[1]
        return {"threshold": a["threshold"], "eer": (a["far"] + a["frr"]) / 2.0}
    return {"threshold": None, "eer": None}


# ---------- 分桶 ----------

def overlap_bucket(o: Optional[float]) -> str:
    if o is None:
        return "none"
    if o < 0.1:
        return "0-0.1"
    if o < 0.2:
        return "0.1-0.2"
    if o < 0.3:
        return "0.2-0.3"
    if o < 0.5:
        return "0.3-0.5"
    return ">=0.5"


def sample_bucket(rec: dict) -> str:
    """统一桶名：与 Target_speaker.md 6.x 节对齐。"""
    st = rec["sample_type"]
    if st == "positive":
        return f"positive_overlap_{overlap_bucket(rec.get('overlap_ratio'))}"
    if st == "negative_distractor":
        return "negative_distractor"
    if st == "negative_silence":
        return "negative_silence"
    return st


# ---------- 主体 ----------

def load_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[WARN] skip bad line: {e}", file=sys.stderr)
    return out


def compute_baseline_metrics(records: list[dict]) -> dict:
    """baseline = 不门控，所有 positive 用 hypothesis vs ref 算 CER/WER。

    negative 在 baseline 下没有 ref，单独算"非空 hypothesis 占比"作为参考。
    """
    zh_acc = CerWerAccumulator()
    en_acc = CerWerAccumulator()
    neg_total = 0
    neg_nonempty = 0
    for r in records:
        if r["sample_type"] == "positive":
            ref = r["reference_text"] or ""
            hyp = r["hypothesis_text"] or ""
            if (r.get("language") or "").lower().startswith("zh"):
                zh_acc.add(ref, hyp, r.get("language") or "zh")
            else:
                en_acc.add(ref, hyp, r.get("language") or "en")
        else:
            neg_total += 1
            hyp = (r.get("hypothesis_text") or "").strip()
            if hyp:
                neg_nonempty += 1
    return {
        "zh_cer": zh_acc.rate(),
        "zh_n": zh_acc.n_samples,
        "en_wer": en_acc.rate(),
        "en_n": en_acc.n_samples,
        "negative_hyp_nonempty_rate": (
            neg_nonempty / neg_total if neg_total else None
        ),
        "negative_total": neg_total,
        "negative_hyp_nonempty": neg_nonempty,
    }


def compute_method_a_metrics(
    records: list[dict], thresholds: list[float]
) -> dict:
    """方案 A 在每个阈值下的 CER/WER + FAR/FRR + 误报率。

    采纳规则：verify_score is not None and verify_score >= threshold → 采纳。
    """
    pos_scores = [r.get("verify_score") for r in records if r["sample_type"] == "positive"]
    neg_scores = [r.get("verify_score") for r in records if r["sample_type"].startswith("negative")]

    out: dict = {"per_threshold": []}
    for thr in thresholds:
        zh_acc = CerWerAccumulator()
        en_acc = CerWerAccumulator()
        neg_total = 0
        neg_accepted = 0
        for r in records:
            score = r.get("verify_score")
            accepted = score is not None and score >= thr
            if r["sample_type"] == "positive":
                ref = r["reference_text"] or ""
                hyp = r["hypothesis_text"] or "" if accepted else ""
                lang = (r.get("language") or "")
                if lang.lower().startswith("zh"):
                    zh_acc.add(ref, hyp, lang or "zh")
                else:
                    en_acc.add(ref, hyp, lang or "en")
            else:
                neg_total += 1
                if accepted:
                    neg_accepted += 1
        # 同时算 FAR / FRR（忽略空 score 的 cut，与 sweep 函数等价）
        fa = sum(1 for s in neg_scores if s is not None and s >= thr)
        fr = sum(1 for s in pos_scores if s is None or s < thr)
        out["per_threshold"].append(
            {
                "threshold": thr,
                "zh_cer": zh_acc.rate(),
                "zh_n": zh_acc.n_samples,
                "en_wer": en_acc.rate(),
                "en_n": en_acc.n_samples,
                "negative_accepted_rate": (
                    neg_accepted / neg_total if neg_total else None
                ),
                "negative_total": neg_total,
                "negative_accepted": neg_accepted,
                "far": fa / len(neg_scores) if neg_scores else None,
                "frr": fr / len(pos_scores) if pos_scores else None,
                "fa_count": fa,
                "fr_count": fr,
            }
        )
    sweep_rows = sweep_far_frr(pos_scores, neg_scores)
    eer = find_eer(sweep_rows)
    out["sweep"] = sweep_rows
    out["eer"] = eer
    out["pos_total"] = len(pos_scores)
    out["neg_total"] = len(neg_scores)
    out["pos_score_missing"] = sum(1 for s in pos_scores if s is None)
    out["neg_score_missing"] = sum(1 for s in neg_scores if s is None)
    return out


def compute_per_bucket(
    records: list[dict], thresholds: list[float]
) -> dict:
    """每个桶单独算 baseline + 方案 A 在指定阈值下的 metric。"""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        grouped[sample_bucket(r)].append(r)
    out: dict = {}
    for bucket, items in sorted(grouped.items()):
        out[bucket] = {
            "n": len(items),
            "baseline": compute_baseline_metrics(items),
            "method_a": compute_method_a_metrics(items, thresholds),
        }
    return out


def compute_score_distribution(records: list[dict]) -> dict:
    """positive vs negative 的 verify_score 分布（中位数 / p10 / p50 / p90）。"""

    def stats(scores: list[float]) -> dict:
        if not scores:
            return {"n": 0}
        scores = sorted(scores)
        n = len(scores)

        def q(p: float) -> float:
            i = max(0, min(n - 1, int(round((n - 1) * p))))
            return float(scores[i])

        return {
            "n": n,
            "min": scores[0],
            "p10": q(0.10),
            "p50": q(0.50),
            "p90": q(0.90),
            "max": scores[-1],
            "mean": sum(scores) / n,
        }

    pos = [r["verify_score"] for r in records
           if r["sample_type"] == "positive" and r.get("verify_score") is not None]
    neg = [r["verify_score"] for r in records
           if r["sample_type"].startswith("negative") and r.get("verify_score") is not None]
    return {"positive": stats(pos), "negative": stats(neg)}


def compute_timings(records: list[dict]) -> dict:
    fields = ["load_audio", "load_enroll", "enroll", "verify", "asr"]
    out: dict = {}
    for f in fields:
        vals = [r["timings_sec"][f] for r in records if r.get("timings_sec", {}).get(f) is not None]
        if not vals:
            out[f] = {"n": 0}
            continue
        vals.sort()
        n = len(vals)
        out[f] = {
            "n": n,
            "p10": vals[int(0.10 * (n - 1))],
            "p50": vals[n // 2],
            "p90": vals[int(0.90 * (n - 1))],
            "mean": sum(vals) / n,
            "sum": sum(vals),
        }
    durs = [r["duration_sec"] for r in records if r.get("duration_sec")]
    if durs and out.get("verify", {}).get("sum") is not None and out.get("asr", {}).get("sum") is not None:
        total_audio = sum(durs)
        out["rtf"] = {
            "verify_rtf_total": out["verify"]["sum"] / total_audio,
            "asr_rtf_total": out["asr"]["sum"] / total_audio,
            "pipeline_rtf_total": (out["verify"]["sum"] + out["asr"]["sum"]) / total_audio,
            "total_audio_sec": total_audio,
        }
    return out


# ---------- Markdown 渲染 ----------

def fmt_pct(x: Optional[float]) -> str:
    if x is None:
        return "-"
    return f"{x * 100:.2f}%"


def fmt_num(x: Optional[float], digits: int = 4) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "-"
    return f"{x:.{digits}f}"


def render_md(summary: dict, jsonl_path: Path) -> str:
    md: list[str] = []
    md.append(f"# TS-ASR 评估汇总报告\n")
    md.append(f"输入 JSONL: `{jsonl_path}`\n")
    md.append(f"总样本数: {summary['n_records']}\n")
    md.append("")

    md.append("## 1. 总体 baseline（不做 verify 门控）\n")
    base = summary["overall_baseline"]
    md.append("| 维度 | 值 |")
    md.append("| --- | --- |")
    md.append(f"| zh CER (positive 中文) | {fmt_pct(base['zh_cer'])} ({base['zh_n']} 条) |")
    md.append(f"| en WER (positive 英文) | {fmt_pct(base['en_wer'])} ({base['en_n']} 条) |")
    md.append(f"| negative 非空 hypothesis 占比 | {fmt_pct(base['negative_hyp_nonempty_rate'])} ({base['negative_hyp_nonempty']}/{base['negative_total']}) |")
    md.append("")

    md.append("## 2. verify_score 分布\n")
    dist = summary["score_distribution"]
    md.append("| 类别 | n | min | p10 | p50 | p90 | max | mean |")
    md.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for k in ("positive", "negative"):
        d = dist[k]
        if d["n"] == 0:
            md.append(f"| {k} | 0 | - | - | - | - | - | - |")
            continue
        md.append(
            f"| {k} | {d['n']} | {fmt_num(d['min'])} | {fmt_num(d['p10'])} |"
            f" {fmt_num(d['p50'])} | {fmt_num(d['p90'])} | {fmt_num(d['max'])} |"
            f" {fmt_num(d['mean'])} |"
        )
    md.append("")

    md.append("## 3. EER 与阈值扫描\n")
    eer = summary["overall_method_a"]["eer"]
    md.append(f"EER = {fmt_pct(eer['eer'])} 在 threshold = {fmt_num(eer['threshold'])}")
    md.append("")
    md.append("阈值扫描（top 关键点）：")
    md.append("| threshold | FAR | FRR |")
    md.append("| --- | --- | --- |")
    sweep = summary["overall_method_a"]["sweep"]
    for row in sweep:
        thr = row["threshold"]
        if thr in (0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75):
            md.append(f"| {thr:.2f} | {fmt_pct(row['far'])} | {fmt_pct(row['frr'])} |")
    md.append("")

    md.append("## 4. 总体 baseline vs 方案 A（关键阈值）\n")
    md.append(
        "| 维度 | baseline | A@0.25 | A@0.40 | A@0.55 |"
    )
    md.append("| --- | --- | --- | --- | --- |")
    pt = {row["threshold"]: row for row in summary["overall_method_a"]["per_threshold"]}
    md.append(
        "| zh CER | "
        f"{fmt_pct(base['zh_cer'])} | "
        f"{fmt_pct(pt.get(0.25, {}).get('zh_cer'))} | "
        f"{fmt_pct(pt.get(0.40, {}).get('zh_cer'))} | "
        f"{fmt_pct(pt.get(0.55, {}).get('zh_cer'))} |"
    )
    md.append(
        "| en WER | "
        f"{fmt_pct(base['en_wer'])} | "
        f"{fmt_pct(pt.get(0.25, {}).get('en_wer'))} | "
        f"{fmt_pct(pt.get(0.40, {}).get('en_wer'))} | "
        f"{fmt_pct(pt.get(0.55, {}).get('en_wer'))} |"
    )
    md.append(
        "| FAR (negative 误采纳) | - | "
        f"{fmt_pct(pt.get(0.25, {}).get('far'))} | "
        f"{fmt_pct(pt.get(0.40, {}).get('far'))} | "
        f"{fmt_pct(pt.get(0.55, {}).get('far'))} |"
    )
    md.append(
        "| FRR (positive 漏采纳) | - | "
        f"{fmt_pct(pt.get(0.25, {}).get('frr'))} | "
        f"{fmt_pct(pt.get(0.40, {}).get('frr'))} | "
        f"{fmt_pct(pt.get(0.55, {}).get('frr'))} |"
    )
    md.append("")

    md.append("## 5. 按桶细分\n")
    md.append("（每桶都给 baseline 与方案 A @0.25 / @0.40 / @0.55；空表示桶内无相应语种样本）\n")
    md.append("| bucket | n | base CER zh | base WER en | A@0.40 CER zh | A@0.40 WER en | A@0.40 FAR | A@0.40 FRR |")
    md.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    per_bucket = summary["per_bucket"]
    for bk in sorted(per_bucket.keys()):
        info = per_bucket[bk]
        b = info["baseline"]
        ma = {row["threshold"]: row for row in info["method_a"]["per_threshold"]}.get(0.40, {})
        md.append(
            f"| {bk} | {info['n']} | "
            f"{fmt_pct(b['zh_cer'])} ({b['zh_n']}) | "
            f"{fmt_pct(b['en_wer'])} ({b['en_n']}) | "
            f"{fmt_pct(ma.get('zh_cer'))} | "
            f"{fmt_pct(ma.get('en_wer'))} | "
            f"{fmt_pct(ma.get('far'))} | "
            f"{fmt_pct(ma.get('frr'))} |"
        )
    md.append("")

    if summary.get("timings"):
        md.append("## 6. 时延 / RTF（host CPU）\n")
        t = summary["timings"]
        md.append("| stage | p10 | p50 | p90 | mean | n |")
        md.append("| --- | --- | --- | --- | --- | --- |")
        for stage in ("load_audio", "load_enroll", "enroll", "verify", "asr"):
            s = t.get(stage, {})
            if s.get("n", 0) == 0:
                continue
            md.append(
                f"| {stage} | {fmt_num(s['p10'], 3)}s | {fmt_num(s['p50'], 3)}s | {fmt_num(s['p90'], 3)}s | {fmt_num(s['mean'], 3)}s | {s['n']} |"
            )
        rtf = t.get("rtf")
        if rtf:
            md.append("")
            md.append(f"verify RTF = {fmt_num(rtf['verify_rtf_total'], 3)} | "
                      f"ASR RTF = {fmt_num(rtf['asr_rtf_total'], 3)} | "
                      f"pipeline RTF = {fmt_num(rtf['pipeline_rtf_total'], 3)}（音频总时长 {fmt_num(rtf['total_audio_sec'], 1)}s）")
        md.append("")

    md.append("## 7. 决策建议\n")
    md.append(
        "按 docs/speaker/PIPELINE.md 第 6 节决策门，把上面 EER / FAR / RTF 数字逐条对照即可。"
    )
    return "\n".join(md)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="TS-ASR 评估汇总")
    p.add_argument("--jsonl", required=True, type=Path)
    p.add_argument("--out-json", required=True, type=Path)
    p.add_argument("--out-md", required=True, type=Path)
    p.add_argument(
        "--thresholds",
        type=str,
        default="0.20,0.25,0.30,0.35,0.40,0.45,0.50,0.55,0.60,0.65",
        help="逗号分隔的方案 A 阈值列表",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    records = load_jsonl(args.jsonl)
    if not records:
        print(f"[ERROR] {args.jsonl} 为空", file=sys.stderr)
        return 2

    thresholds = sorted({round(float(x), 4) for x in args.thresholds.split(",")})
    summary = {
        "n_records": len(records),
        "sample_type_counts": dict(Counter(r["sample_type"] for r in records)),
        "language_counts": dict(Counter((r.get("language") or "?") for r in records)),
        "overall_baseline": compute_baseline_metrics(records),
        "overall_method_a": compute_method_a_metrics(records, thresholds),
        "score_distribution": compute_score_distribution(records),
        "timings": compute_timings(records),
        "per_bucket": compute_per_bucket(records, thresholds),
    }

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2)
    )
    args.out_md.write_text(render_md(summary, args.jsonl))
    print(f"[DONE] summary json -> {args.out_json}")
    print(f"[DONE] summary md   -> {args.out_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
