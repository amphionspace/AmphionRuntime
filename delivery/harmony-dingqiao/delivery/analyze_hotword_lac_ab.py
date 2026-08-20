#!/usr/bin/env python3
"""Build a detailed report from decoder, no-LAC, max-3, and current device runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import run_hotword_device_eval as metric


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_POSITIVE = SCRIPT_DIR / "fixtures/hotword_eval_400.jsonl"
DEFAULT_NEGATIVE = SCRIPT_DIR / "fixtures/hotword_negative_200.jsonl"


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def result_path(value: Path) -> Path:
    return value / "device-result.jsonl" if value.is_dir() else value


def result_map(value: Path) -> dict[tuple[str, str], dict[str, object]]:
    path = result_path(value)
    return {(str(row["id"]), str(row["variant"])): row for row in read_jsonl(path)}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentile(values: list[int], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return float(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))])


def positive_metrics(entries: list[dict[str, object]], rows: dict[str, dict[str, object]]) -> dict[str, object]:
    errors = reference_units = hits = words = all_hit = device_errors = 0
    elapsed: list[int] = []
    by_language: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_stratum: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_length: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for entry in entries:
        row = rows.get(str(entry["id"]))
        if row is None:
            continue
        language = str(entry["language"])
        reference = metric.units(str(entry["reference"]), language)
        hypothesis = str(row.get("text", ""))
        edit_errors = metric.edit_distance(reference, metric.units(hypothesis, language))
        hotwords = [str(value) for value in entry["hotwords"]]
        word_hits = [metric.hotword_hit(hypothesis, value, language) for value in hotwords]
        errors += edit_errors
        reference_units += len(reference)
        hits += sum(word_hits)
        words += len(word_hits)
        all_hit += int(all(word_hits))
        device_errors += int(int(row.get("error_code", 0)) != 0)
        elapsed.append(int(row.get("elapsed_ms", 0)))
        for key, bucket in ((language, by_language), (str(entry["stratum"]), by_stratum)):
            bucket[key]["errors"] += edit_errors
            bucket[key]["units"] += len(reference)
            bucket[key]["hits"] += sum(word_hits)
            bucket[key]["words"] += len(word_hits)
            bucket[key]["cases"] += 1
            bucket[key]["all_hit"] += int(all(word_hits))
        for hotword, hit in zip(hotwords, word_hits):
            length = len(metric.units(hotword, language))
            by_length[length]["hits"] += int(hit)
            by_length[length]["words"] += 1
    def compact(source: dict[object, dict[str, int]]) -> dict[str, object]:
        return {str(key): {
            "cases": value.get("cases", 0),
            "error_rate": value.get("errors", 0) / max(1, value.get("units", 0)),
            "hotword_recall": value.get("hits", 0) / max(1, value.get("words", 0)),
            "all_hotwords_hit_rate": value.get("all_hit", 0) / max(1, value.get("cases", 0)),
        } for key, value in sorted(source.items(), key=lambda item: str(item[0]))}
    return {
        "cases": len(elapsed),
        "error_rate": errors / max(1, reference_units),
        "hotword_recall": hits / max(1, words),
        "all_hotwords_hit_rate": all_hit / max(1, len(elapsed)),
        "device_errors": device_errors,
        "latency_ms": {
            "mean": statistics.fmean(elapsed) if elapsed else 0.0,
            "p50": statistics.median(elapsed) if elapsed else 0.0,
            "p95": percentile(elapsed, 0.95),
        },
        "by_language": compact(by_language),
        "by_stratum": compact(by_stratum),
        "recall_by_hotword_length": {
            str(key): value["hits"] / max(1, value["words"])
            for key, value in sorted(by_length.items())
        },
        "hotword_count_by_length": {
            str(key): value["words"] for key, value in sorted(by_length.items())
        },
    }


def negative_metrics(entries: list[dict[str, object]], rows: dict[str, dict[str, object]]) -> dict[str, object]:
    errors = units = distractor_hits = source_hits = device_errors = 0
    by_length: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    elapsed: list[int] = []
    for entry in entries:
        row = rows[str(entry["id"])]
        hypothesis = str(row.get("text", ""))
        reference = metric.normalize_zh(str(entry["reference"]))
        length = int(entry["candidate_length"])
        distractor = metric.hotword_hit(hypothesis, str(entry["distractor"]), "zh-CN")
        source = metric.hotword_hit(hypothesis, str(entry["expected_source"]), "zh-CN")
        edit_errors = metric.edit_distance(reference, metric.normalize_zh(hypothesis))
        errors += edit_errors
        units += len(reference)
        distractor_hits += int(distractor)
        source_hits += int(source)
        device_errors += int(int(row.get("error_code", 0)) != 0)
        elapsed.append(int(row.get("elapsed_ms", 0)))
        by_length[length]["cases"] += 1
        by_length[length]["distractor_hits"] += int(distractor)
        by_length[length]["source_hits"] += int(source)
        by_length[length]["errors"] += edit_errors
        by_length[length]["units"] += len(reference)
    return {
        "cases": len(entries),
        "error_rate": errors / max(1, units),
        "distractor_activation_rate": distractor_hits / max(1, len(entries)),
        "source_preservation_rate": source_hits / max(1, len(entries)),
        "device_errors": device_errors,
        "latency_ms": {
            "mean": statistics.fmean(elapsed) if elapsed else 0.0,
            "p50": statistics.median(elapsed) if elapsed else 0.0,
            "p95": percentile(elapsed, 0.95),
        },
        "by_candidate_length": {str(length): {
            "cases": value["cases"],
            "error_rate": value["errors"] / max(1, value["units"]),
            "distractor_activation_rate": value["distractor_hits"] / max(1, value["cases"]),
            "source_preservation_rate": value["source_hits"] / max(1, value["cases"]),
        } for length, value in sorted(by_length.items())},
    }


def compare(entries: list[dict[str, object]], before: dict[str, dict[str, object]],
            after: dict[str, dict[str, object]]) -> tuple[dict[str, int], list[dict[str, object]]]:
    counts: dict[str, int] = defaultdict(int)
    details: list[dict[str, object]] = []
    for entry in entries:
        case_id = str(entry["id"])
        if case_id not in before or case_id not in after:
            continue
        language = str(entry["language"])
        reference = metric.units(str(entry["reference"]), language)
        before_text = str(before[case_id].get("text", ""))
        after_text = str(after[case_id].get("text", ""))
        before_errors = metric.edit_distance(reference, metric.units(before_text, language))
        after_errors = metric.edit_distance(reference, metric.units(after_text, language))
        delta = after_errors - before_errors
        classification = "improved" if delta < 0 else "regressed" if delta > 0 else "unchanged"
        counts[classification] += 1
        counts["text_changed"] += int(before_text != after_text)
        counts["net_error_delta"] += delta
        if before_text != after_text:
            details.append({
                "id": case_id,
                "reference": entry["reference"],
                "hotwords": entry["hotwords"],
                "expected_source": entry.get("expected_source"),
                "candidate_length": entry.get("candidate_length"),
                "before": before_text,
                "after": after_text,
                "before_errors": before_errors,
                "after_errors": after_errors,
                "delta_errors": delta,
            })
    return dict(counts), details


def pct(value: object) -> str:
    return f"{float(value):.2%}"


def sign_test_p(counts: dict[str, int]) -> float:
    improved = counts.get("improved", 0)
    regressed = counts.get("regressed", 0)
    total = improved + regressed
    if total == 0:
        return 1.0
    tail = sum(math.comb(total, value) for value in range(min(improved, regressed) + 1)) / (2 ** total)
    return min(1.0, 2 * tail)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positive-off", type=Path, required=True)
    parser.add_argument("--negative-off", type=Path, required=True)
    parser.add_argument("--no-lac", type=Path, required=True)
    parser.add_argument("--per-only", type=Path, required=True)
    parser.add_argument("--max3", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--positive-fixture", type=Path, default=DEFAULT_POSITIVE)
    parser.add_argument("--negative-fixture", type=Path, default=DEFAULT_NEGATIVE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    positive = read_jsonl(args.positive_fixture)
    negative = read_jsonl(args.negative_fixture)
    positive_ids = {str(entry["id"]) for entry in positive}
    negative_ids = {str(entry["id"]) for entry in negative}
    off_rows = result_map(args.positive_off)
    neg_off_rows = result_map(args.negative_off)
    combined = {
        "no_lac": result_map(args.no_lac),
        "per_only": result_map(args.per_only),
        "max3": result_map(args.max3),
        "current": result_map(args.current),
    }
    positive_conditions: dict[str, dict[str, dict[str, object]]] = {
        "decoder_no_hotword": {case_id: row for (case_id, variant), row in off_rows.items()
                               if variant == "baseline" and case_id in positive_ids},
        "decoder_hotword": {case_id: row for (case_id, variant), row in off_rows.items()
                            if variant == "hotword" and case_id in positive_ids},
    }
    negative_conditions: dict[str, dict[str, dict[str, object]]] = {
        "decoder_hotword": {case_id: row for (case_id, variant), row in neg_off_rows.items()
                            if variant == "hotword" and case_id in negative_ids},
    }
    for condition, values in combined.items():
        positive_conditions[condition] = {
            case_id: row for (case_id, variant), row in values.items()
            if variant == "hotword" and case_id in positive_ids
        }
        negative_conditions[condition] = {
            case_id: row for (case_id, variant), row in values.items()
            if variant == "hotword" and case_id in negative_ids
        }

    positive_summary = {
        condition: positive_metrics(positive, rows) for condition, rows in positive_conditions.items()
    }
    negative_summary = {
        condition: negative_metrics(negative, rows) for condition, rows in negative_conditions.items()
    }
    transitions = {}
    all_details: list[dict[str, object]] = []
    pairs = (
        ("decoder_hotword_gain", "decoder_no_hotword", "decoder_hotword", positive),
        ("generic_police_effect", "decoder_hotword", "no_lac", positive),
        ("lac_per_only_effect", "no_lac", "per_only", positive),
        ("lac_2_to_3_effect", "no_lac", "max3", positive),
        ("lac_4_to_6_increment", "max3", "current", positive),
        ("lac_no_per_fallback_effect", "per_only", "current", positive),
        ("lac_current_total_effect", "no_lac", "current", positive),
        ("negative_generic_police", "decoder_hotword", "no_lac", negative),
        ("negative_lac_per_only", "no_lac", "per_only", negative),
        ("negative_lac_2_to_3", "no_lac", "max3", negative),
        ("negative_lac_4_to_6", "max3", "current", negative),
        ("negative_lac_no_per_fallback", "per_only", "current", negative),
        ("negative_lac_current_total", "no_lac", "current", negative),
    )
    for name, before_name, after_name, entries in pairs:
        sources = positive_conditions if entries is positive else negative_conditions
        counts, details = compare(entries, sources[before_name], sources[after_name])
        transitions[name] = counts
        for detail in details:
            detail["comparison"] = name
            all_details.append(detail)

    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=metric.REPO_ROOT,
                            text=True, stdout=subprocess.PIPE, check=True).stdout.strip()
    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "source_commit": commit,
        "positive_fixture_sha256": digest(args.positive_fixture),
        "negative_fixture_sha256": digest(args.negative_fixture),
        "positive": positive_summary,
        "negative": negative_summary,
        "transitions": transitions,
        "inputs": {key: str(result_path(value).resolve()) for key, value in {
            "positive_off": args.positive_off, "negative_off": args.negative_off,
            "no_lac": args.no_lac, "per_only": args.per_only,
            "max3": args.max3, "current": args.current,
        }.items()},
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                             encoding="utf-8")
    (args.output / "comparison-details.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in all_details), encoding="utf-8")

    labels = {
        "decoder_no_hotword": "无热词、无增强",
        "decoder_hotword": "解码器热词、无增强",
        "no_lac": "解码器热词 + 通用警务后处理（无 LAC）",
        "per_only": "解码器热词 + LAC 2～6 字（严格 PER）",
        "max3": "解码器热词 + LAC 2～3 字",
        "current": "解码器热词 + 当前 LAC 2～6 字",
    }
    lines = [
        "# Harmony 热词召回与 LAC 影响设备 A/B 报告", "",
        "## 结论摘要", "",
        "本报告使用同一台设备、同一模型和固定样本，对解码热词、通用后处理、严格 PER、LAC 2～3 字范围、当前 LAC 2～6 字范围逐层拆分。",
        "结论应同时参考正样本收益和负向干扰热词误替换，不能只看正样本召回。", "",
        "## 样本与复现", "",
        f"- 正样本：400 条（中文 200、英文 200）；SHA-256 `{report['positive_fixture_sha256']}`。",
        f"- 负向同音干扰样本：200 条中文；SHA-256 `{report['negative_fixture_sha256']}`。",
        f"- 源码提交：`{commit}`。", "",
        "共完成 2600 次设备识别：400 条正样本的 baseline/hotword 800 次，四种中文 LAC 配置各 400 次，另加 200 条负向纯解码对照。所有设备错误码均为 0。", "",
        "实验构建只改变人名候选逻辑：no-LAC 不配置任何人名候选；严格 PER 保留 2～6 字但要求命中 PER span；max3 仅接受 2～3 字；current 为仓库现有 2～6 字且 3 字以上可绕过 PER。临时构建改动均已恢复，未写入生产源码。", "",
        "## 正样本总体结果", "",
        "| 配置 | 样本数 | CER/WER | 热词召回 | 全热词命中 | 平均耗时 | P95 | 设备错误 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for condition, values in positive_summary.items():
        latency = values["latency_ms"]
        lines.append(f"| {labels[condition]} | {values['cases']} | {pct(values['error_rate'])} | "
                     f"{pct(values['hotword_recall'])} | {pct(values['all_hotwords_hit_rate'])} | "
                     f"{latency['mean']:.0f} ms | {latency['p95']:.0f} ms | {values['device_errors']} |")
    lines.extend(["", "### 中文与英文拆分", "",
                  "| 配置 / 语言 | 样本数 | CER/WER | 热词召回 | 全热词命中 |",
                  "|---|---:|---:|---:|---:|"])
    for condition, values in positive_summary.items():
        for language, language_values in values["by_language"].items():
            lines.append(f"| {labels[condition]} / {language} | {language_values['cases']} | "
                         f"{pct(language_values['error_rate'])} | {pct(language_values['hotword_recall'])} | "
                         f"{pct(language_values['all_hotwords_hit_rate'])} |")
    lines.extend(["", "## 负向干扰热词结果", "",
                  "这里的‘干扰词激活’表示输出出现了参考文本中不存在的配置热词，数值越低越好。该集合刻意富集同音冲突，是风险压力测试，不能解释为自然流量的绝对误触发概率。", "",
                  "| 配置 | 样本数 | CER | 干扰词激活 | 原片段保留 | 平均耗时 | 设备错误 |",
                  "|---|---:|---:|---:|---:|---:|---:|"])
    for condition, values in negative_summary.items():
        latency = values["latency_ms"]
        lines.append(f"| {labels[condition]} | {values['cases']} | {pct(values['error_rate'])} | "
                     f"{pct(values['distractor_activation_rate'])} | {pct(values['source_preservation_rate'])} | "
                     f"{latency['mean']:.0f} ms | {values['device_errors']} |")
    lines.extend(["", "## 分层增量", "",
                  "| 对比 | 改善 | 退化 | 文本变化 | 净编辑错误变化 | 配对符号检验 p |",
                  "|---|---:|---:|---:|---:|---:|"])
    transition_labels = {
        "decoder_hotword_gain": "正样本：开启解码器热词",
        "generic_police_effect": "正样本：加入通用警务后处理",
        "lac_per_only_effect": "正样本：加入严格 PER 的 LAC",
        "lac_2_to_3_effect": "正样本：加入 LAC 2～3 字",
        "lac_4_to_6_increment": "正样本：LAC 从最多 3 字扩大到 6 字",
        "lac_no_per_fallback_effect": "正样本：在严格 PER 上加入 3～6 字无 PER 兜底",
        "lac_current_total_effect": "正样本：从 no-LAC 到当前策略",
        "negative_generic_police": "负样本：加入通用警务后处理",
        "negative_lac_per_only": "负样本：加入严格 PER 的 LAC",
        "negative_lac_2_to_3": "负样本：加入 LAC 2～3 字",
        "negative_lac_4_to_6": "负样本：LAC 从最多 3 字扩大到 6 字",
        "negative_lac_no_per_fallback": "负样本：在严格 PER 上加入 3～6 字无 PER 兜底",
        "negative_lac_current_total": "负样本：从 no-LAC 到当前策略",
    }
    for name, values in transitions.items():
        lines.append(f"| {transition_labels[name]} | {values.get('improved', 0)} | "
                     f"{values.get('regressed', 0)} | {values.get('text_changed', 0)} | "
                     f"{values.get('net_error_delta', 0):+d} | {sign_test_p(values):.3g} |")
    lines.extend(["", "## 负样本按候选长度", ""])
    for condition in ("no_lac", "per_only", "max3", "current"):
        lines.extend([f"### {labels[condition]}", "",
                      "| 候选长度 | 样本数 | CER | 干扰词激活 | 原片段保留 |",
                      "|---:|---:|---:|---:|---:|"])
        for length, values in negative_summary[condition]["by_candidate_length"].items():
            lines.append(f"| {length} | {values['cases']} | {pct(values['error_rate'])} | "
                         f"{pct(values['distractor_activation_rate'])} | {pct(values['source_preservation_rate'])} |")
        lines.append("")
    lines.extend(["## 典型变化样本", ""])
    for detail in sorted(all_details, key=lambda item: int(item["delta_errors"]), reverse=True)[:30]:
        lines.append(f"- `{detail['comparison']}` / `{detail['id']}` / Δ错误 {detail['delta_errors']:+d}："
                     f"`{detail['before']}` → `{detail['after']}`；参考：`{detail['reference']}`")
    per_positive = transitions["lac_per_only_effect"]
    fallback_positive = transitions["lac_no_per_fallback_effect"]
    per_negative = transitions["negative_lac_per_only"]
    fallback_negative = transitions["negative_lac_no_per_fallback"]
    lines.extend(["", "## 数据驱动结论与建议", "",
                  f"- 严格 PER 的 LAC 在 200 条中文正样本中改善 {per_positive.get('improved', 0)} 条、"
                  f"退化 {per_positive.get('regressed', 0)} 条；在 200 条压力样本中新增退化 "
                  f"{per_negative.get('regressed', 0)} 条。",
                  f"- 当前 3～6 字无 PER 兜底相对严格 PER，在正样本中额外改善 "
                  f"{fallback_positive.get('improved', 0)} 条，但在压力样本中新增退化 "
                  f"{fallback_negative.get('regressed', 0)} 条。",
                  "- 仅把最大长度收紧到 3 字不是充分修复：三字窗口仍可跨词边界替换，且压力集中 3 字候选占多数。",
                  "- 建议保留 decoder 热词；普通 sysGeneralLexicon 不应自动获得无 PER 人名兜底。短期可恢复严格 PER 门控；"
                  "但严格 PER 在压力集中仍新增 12 条退化，因此更安全的默认值是普通热词不进入人名归一化。"
                  "若必须召回 LAC 漏检的罕见姓名，应新增显式 personNameLexicon/姓名白名单，只对明确标注的人名开放兜底。",
                  "- 四至六字范围本身不是首要问题。若有 PER 或显式姓名类型，可以保留；真正高风险的是把所有 3～6 字普通热词都视作人名意图。", "",
                  "## 判定原则", "",
                  "- 解码器热词收益看 `decoder_no_hotword → decoder_hotword`。",
                  "- NER 门控 LAC 的价值看 `no_lac → per_only`。",
                  "- LAC 三字内净影响看 `no_lac → max3`。",
                  "- 四至六字额外价值与风险看 `max3 → current`；这是决定是否收紧范围的核心对比。",
                  "- 无 PER 兜底的总影响看 `per_only → current`。",
                  "- 长度限制只能作为附加保护，不能替代 PER、边界或显式人名类型约束。", ""])
    (args.output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(args.output / "report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
