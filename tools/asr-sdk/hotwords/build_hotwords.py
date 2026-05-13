#!/usr/bin/env python3
"""
把业务方维护的 CSV 热词词典转换成 sherpa-onnx 接受的 hotwords.txt 格式。

CSV 输入约定（第一行表头）：

    word,score,category,note
    语音识别,1.5,asr,通用
    端到端,2.0,asr,公司术语
    浦东机场,1.0,navigation,POI
    Apple Pay,2.0,payment,品牌

字段：
- word        必填，热词字符串
- score       可选，每词权重；缺省时用 --default-score（默认 1.5）
- category    可选，业务分类；用 --include-category / --exclude-category 过滤
- note        可选，仅给人看，不影响输出

输出格式（hotwords.txt，UTF-8）：

    语音识别 :1.5
    端到端 :2.0
    浦东机场 :1.0
    Apple Pay :2.0

注意：
- 默认按 word 字段去重；同 word 不同 score 时取首次出现的（输入顺序敏感）
- 中文热词不需要预分词；sherpa-onnx 的 modeling_unit=cjkchar+bpe 会自动处理
- 热词数量上限建议 < 200；超过后命中率反而下降（ContextGraph 平均匹配代价上升）

用法：

    python tools/asr-sdk/hotwords/build_hotwords.py \\
        --csv tools/asr-sdk/hotwords/sample.csv \\
        --out /tmp/hotwords.txt \\
        --include-category asr,navigation \\
        --default-score 1.5 \\
        --max-words 200

退出码：
    0  成功
    1  参数错误
    2  输入文件解析失败
    3  超过 max-words
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Set


@dataclass(frozen=True)
class HotwordEntry:
    word: str
    score: float
    category: str


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter,
                                description=__doc__)
    p.add_argument("--csv", required=True, type=Path, action="append",
                   help="CSV 输入；可重复指定多次以合并多个词典")
    p.add_argument("--out", required=True, type=Path,
                   help="输出 hotwords.txt 路径")
    p.add_argument("--default-score", type=float, default=1.5,
                   help="缺省 score；建议 [0.5, 3.0]")
    p.add_argument("--include-category",
                   help="只包含这些 category 的词，逗号分隔；不指定 = 全部")
    p.add_argument("--exclude-category",
                   help="排除这些 category 的词，逗号分隔；与 include 同时存在时先 include 再 exclude")
    p.add_argument("--max-words", type=int, default=200,
                   help="超出后退出 3；上游建议 ≤ 200")
    p.add_argument("--stats-out", type=Path, default=None,
                   help="可选；写一份 JSON 统计：按 category 计数 / 平均 score")
    return p.parse_args()


def read_csv(path: Path) -> List[HotwordEntry]:
    if not path.is_file():
        raise SystemExit(f"[ERROR] CSV 不存在：{path}")
    rows: List[HotwordEntry] = []
    with path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if "word" not in (reader.fieldnames or []):
            raise SystemExit(f"[ERROR] {path} 缺少 word 列")
        for ln, row in enumerate(reader, start=2):
            word = (row.get("word") or "").strip()
            if not word:
                continue
            score_raw = (row.get("score") or "").strip()
            try:
                score = float(score_raw) if score_raw else float("nan")
            except ValueError:
                raise SystemExit(f"[ERROR] {path}:{ln} score 不是数字：{score_raw}")
            category = (row.get("category") or "").strip().lower()
            rows.append(HotwordEntry(word=word, score=score, category=category))
    return rows


def filter_entries(entries: Iterable[HotwordEntry],
                   include: Optional[Set[str]],
                   exclude: Optional[Set[str]]) -> List[HotwordEntry]:
    out: List[HotwordEntry] = []
    for e in entries:
        if include is not None and e.category not in include:
            continue
        if exclude is not None and e.category in exclude:
            continue
        out.append(e)
    return out


def dedupe_keep_first(entries: Iterable[HotwordEntry]) -> List[HotwordEntry]:
    seen: Set[str] = set()
    out: List[HotwordEntry] = []
    for e in entries:
        if e.word in seen:
            continue
        seen.add(e.word)
        out.append(e)
    return out


def render(entries: List[HotwordEntry], default_score: float) -> str:
    lines: List[str] = []
    for e in entries:
        score = e.score if e.score == e.score else default_score   # NaN check
        # sherpa-onnx 的格式：word words... :score（score 必须以 : 开头，且和词以空格分隔）
        # 中文中间不能含空格（会被解析成多个词，与训练时不一致）
        word = e.word
        if any(c.isspace() and not c == " " for c in word):
            print(f"[WARN] word contains tab / cr / lf, replaced: {word!r}", file=sys.stderr)
            word = " ".join(word.split())
        lines.append(f"{word} :{score:.2f}")
    return "\n".join(lines) + "\n"


def stats(entries: List[HotwordEntry], default_score: float) -> dict:
    by_cat = Counter(e.category or "(uncategorized)" for e in entries)
    score_sum = 0.0
    score_n = 0
    for e in entries:
        s = e.score if e.score == e.score else default_score
        score_sum += s
        score_n += 1
    return {
        "total": len(entries),
        "by_category": dict(by_cat),
        "avg_score": (score_sum / score_n) if score_n else 0.0,
    }


def main() -> int:
    args = parse_args()
    include = (set(s.strip().lower() for s in args.include_category.split(","))
               if args.include_category else None)
    exclude = (set(s.strip().lower() for s in args.exclude_category.split(","))
               if args.exclude_category else None)

    all_entries: List[HotwordEntry] = []
    for csv_path in args.csv:
        all_entries.extend(read_csv(csv_path))

    print(f"[INFO] loaded {len(all_entries)} raw entries from {len(args.csv)} csv(s)")

    filtered = filter_entries(all_entries, include, exclude)
    print(f"[INFO] {len(filtered)} entries after include/exclude filtering")

    deduped = dedupe_keep_first(filtered)
    print(f"[INFO] {len(deduped)} entries after dedupe")

    if len(deduped) > args.max_words:
        print(f"[ERROR] {len(deduped)} > max-words={args.max_words}; please trim before publishing",
              file=sys.stderr)
        return 3

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(deduped, args.default_score), encoding="utf-8")
    print(f"[INFO] wrote {args.out}")

    if args.stats_out:
        s = stats(deduped, args.default_score)
        args.stats_out.parent.mkdir(parents=True, exist_ok=True)
        args.stats_out.write_text(json.dumps(s, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        print(f"[INFO] stats -> {args.stats_out}: {s}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
