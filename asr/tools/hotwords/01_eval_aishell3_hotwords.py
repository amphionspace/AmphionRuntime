#!/usr/bin/env python3
"""Evaluate ASR hotword biasing on aishell3_test_hotwords_500.

The evaluation compares the current Android behavior:

    no hotwords: greedy_search
    with hotwords: modified_beam_search + per-session hotwords

It also optionally evaluates modified_beam_search without hotwords so the report
can separate "beam search" effects from actual contextual biasing effects.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
SPEAKER_TOOL_DIR = REPO_ROOT / "asr" / "tools" / "speaker"
if str(SPEAKER_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(SPEAKER_TOOL_DIR))

from ts_asr import load_audio_mono16k  # noqa: E402

try:
    import sherpa_onnx
except ImportError as e:  # pragma: no cover
    raise SystemExit("缺少 sherpa_onnx，请先安装 sherpa-onnx Python 包") from e


PUNCS = set(" \t\r\n,.!?;:'\"，。！？；：、《》（）()[]{}-—…")
TEST_DATA_ROOT = Path(
    os.environ.get(
        "AMPHION_TEST_DATA_DIR",
        Path.home() / ".cache/amphion-runtime/test-data/v1",
    )
).expanduser()


@dataclass(frozen=True)
class Sample:
    recording_id: str
    speaker: str
    audio_path: Path
    duration_sec: float
    text: str
    hotwords: list[str]


def normalize_zh(text: str) -> str:
    return "".join(ch for ch in text if ch not in PUNCS)


def edit_distance(a: str, b: str) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


def min_substring_distance(needle: str, haystack: str) -> int:
    if not needle:
        return 0
    if not haystack:
        return len(needle)
    n = len(needle)
    lo = max(0, n - 2)
    hi = min(len(haystack), n + 2)
    best = len(needle)
    for start in range(len(haystack)):
        for length in range(lo, hi + 1):
            end = start + length
            if end > len(haystack):
                continue
            best = min(best, edit_distance(needle, haystack[start:end]))
            if best == 0:
                return 0
    return best


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    xs = sorted(values)
    pos = (len(xs) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return float(xs[lo])
    return float(xs[lo] + (xs[hi] - xs[lo]) * (pos - lo))


def describe(values: list[float]) -> dict:
    clean = [float(v) for v in values if math.isfinite(v)]
    if not clean:
        return {"n": 0}
    return {
        "n": len(clean),
        "min": min(clean),
        "p50": percentile(clean, 0.50),
        "p90": percentile(clean, 0.90),
        "max": max(clean),
        "mean": statistics.fmean(clean),
    }


def load_samples(dataset_dir: Path) -> list[Sample]:
    recordings_path = dataset_dir / "aishell3_test_hotwords_500_recordings_packaged.jsonl.gz"
    supervisions_path = dataset_dir / "aishell3_test_hotwords_500_supervisions_punc_hotwords.jsonl.gz"
    recordings: dict[str, dict] = {}
    with gzip.open(recordings_path, "rt", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            recordings[rec["id"]] = rec

    samples: list[Sample] = []
    with gzip.open(supervisions_path, "rt", encoding="utf-8") as f:
        for line in f:
            sup = json.loads(line)
            rec = recordings[sup["recording_id"]]
            rel = rec["sources"][0]["source"]
            hotwords = sup.get("custom", {}).get("hotwords") or []
            if not hotwords:
                continue
            samples.append(
                Sample(
                    recording_id=sup["recording_id"],
                    speaker=sup.get("speaker") or "",
                    audio_path=dataset_dir / rel,
                    duration_sec=float(sup["duration"]),
                    text=sup.get("text") or "",
                    hotwords=[str(w) for w in hotwords if str(w).strip()],
                )
            )
    samples.sort(key=lambda s: s.recording_id)
    return samples


def build_recognizer(
    model_dir: Path,
    *,
    decoding_method: str,
    hotwords_score: float = 1.5,
    max_active_paths: int = 8,
    num_threads: int = 2,
    bpe_vocab: Path | None = None,
) -> "sherpa_onnx.OnlineRecognizer":
    if bpe_vocab is None:
        bpe_vocab = (
            model_dir.parent
            / "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20"
            / "bpe.vocab"
        )
    return sherpa_onnx.OnlineRecognizer.from_transducer(
        encoder=str(model_dir / "encoder.int8.onnx"),
        decoder=str(model_dir / "decoder.onnx"),
        joiner=str(model_dir / "joiner.int8.onnx"),
        tokens=str(model_dir / "tokens.txt"),
        num_threads=num_threads,
        sample_rate=16000,
        feature_dim=80,
        decoding_method=decoding_method,
        max_active_paths=max_active_paths,
        hotwords_score=hotwords_score,
        modeling_unit="cjkchar+bpe",
        bpe_vocab=str(bpe_vocab),
        model_type="zipformer",
        provider="cpu",
        enable_endpoint_detection=False,
    )


def decode(
    recognizer: "sherpa_onnx.OnlineRecognizer",
    samples: np.ndarray,
    *,
    hotwords: str | None = None,
    tail_sec: float = 0.5,
) -> tuple[str, float]:
    t0 = time.time()
    stream = recognizer.create_stream() if hotwords is None else recognizer.create_stream(hotwords)
    stream.accept_waveform(16000, samples)
    if tail_sec > 0:
        stream.accept_waveform(16000, np.zeros(int(16000 * tail_sec), dtype=np.float32))
    stream.input_finished()
    while recognizer.is_ready(stream):
        recognizer.decode_stream(stream)
    text = str(recognizer.get_result(stream))
    return text, time.time() - t0


def sample_metrics(ref: str, hyp: str, hotwords: list[str]) -> dict:
    ref_n = normalize_zh(ref)
    hyp_n = normalize_zh(hyp)
    ref_len = len(ref_n)
    cer_edits = edit_distance(ref_n, hyp_n)
    hw_norm = [normalize_zh(w) for w in hotwords if normalize_zh(w)]
    exact_hits = [w for w in hw_norm if w in hyp_n]
    min_edits = [min_substring_distance(w, hyp_n) for w in hw_norm]
    min_edit_sum = sum(min_edits)
    hw_char_sum = sum(len(w) for w in hw_norm)
    return {
        "text": hyp,
        "cer_edits": cer_edits,
        "ref_len": ref_len,
        "cer": cer_edits / ref_len if ref_len else None,
        "hotword_count": len(hw_norm),
        "hotword_exact_hits": len(exact_hits),
        "hotword_all_hit": len(exact_hits) == len(hw_norm) if hw_norm else False,
        "hotword_min_edits": min_edit_sum,
        "hotword_chars": hw_char_sum,
        "hotword_min_cer": min_edit_sum / hw_char_sum if hw_char_sum else None,
    }


def aggregate(records: list[dict], system: str) -> dict:
    rows = [r["systems"][system] for r in records]
    n = len(rows)
    edit_sum = sum(r["cer_edits"] for r in rows)
    ref_len = sum(r["ref_len"] for r in rows)
    hw_count = sum(r["hotword_count"] for r in rows)
    hw_hits = sum(r["hotword_exact_hits"] for r in rows)
    hw_chars = sum(r["hotword_chars"] for r in rows)
    hw_edits = sum(r["hotword_min_edits"] for r in rows)
    return {
        "system": system,
        "n_samples": n,
        "cer": edit_sum / ref_len if ref_len else None,
        "cer_edits": edit_sum,
        "ref_len": ref_len,
        "hotword_exact_hit_rate": hw_hits / hw_count if hw_count else None,
        "hotword_exact_hits": hw_hits,
        "hotword_total": hw_count,
        "sample_all_hotwords_hit_rate": (
            sum(1 for r in rows if r["hotword_all_hit"]) / n if n else None
        ),
        "hotword_min_cer": hw_edits / hw_chars if hw_chars else None,
        "hotword_min_edits": hw_edits,
        "hotword_chars": hw_chars,
        "decode_elapsed_sec": sum(r["decode_elapsed_sec"] for r in rows),
        "rtf": (
            sum(r["decode_elapsed_sec"] for r in rows)
            / sum(rec["duration_sec"] for rec in records)
            if records
            else None
        ),
        "per_sample_cer": describe([r["cer"] for r in rows if r["cer"] is not None]),
    }


def pct(v: float | None) -> str:
    return "NA" if v is None else f"{v * 100:.2f}%"


def render_md(summary: dict) -> str:
    systems = summary["systems"]
    baseline = systems["baseline_greedy"]
    best = systems[summary["primary_system"]]
    lines: list[str] = []
    lines.append("# AISHELL-3 热词 ASR 评测")
    lines.append("")
    lines.append("## 评测口径")
    lines.append("")
    lines.append(
        "对 500 条带热词标注的 AISHELL-3 测试音频做 A/B：无热词使用 greedy_search，开启热词使用 modified_beam_search + 每条样本自己的 hotwords。"
    )
    lines.append("")
    lines.append("## 最终收益数据表格")
    lines.append("")
    lines.append("| 场景问题 | 指标 | 无热词 baseline | 开启热词 | 收益或代价 | 结论 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    lines.append(
        "| 人名、地名、专名被识别成常见同音词 | 热词精确命中率 | "
        f"{pct(baseline['hotword_exact_hit_rate'])} | {pct(best['hotword_exact_hit_rate'])} | "
        f"提升 {(best['hotword_exact_hit_rate'] - baseline['hotword_exact_hit_rate']) * 100:.2f} 个百分点 | 核心收益 |"
    )
    lines.append(
        "| 一句话中多个热词需要全部保留 | 样本全热词命中率 | "
        f"{pct(baseline['sample_all_hotwords_hit_rate'])} | {pct(best['sample_all_hotwords_hit_rate'])} | "
        f"提升 {(best['sample_all_hotwords_hit_rate'] - baseline['sample_all_hotwords_hit_rate']) * 100:.2f} 个百分点 | 多热词样本收益 |"
    )
    lines.append(
        "| 热词即使没完全命中，也希望更接近正确写法 | 热词片段最小 CER | "
        f"{pct(baseline['hotword_min_cer'])} | {pct(best['hotword_min_cer'])} | "
        f"下降 {(baseline['hotword_min_cer'] - best['hotword_min_cer']) * 100:.2f} 个百分点 | 热词局部错误减少 |"
    )
    lines.append(
        "| 开启热词是否破坏整句识别 | 整体 CER | "
        f"{pct(baseline['cer'])} | {pct(best['cer'])} | "
        f"{(baseline['cer'] - best['cer']) * 100:.2f} 个百分点变化 | 副作用观察 |"
    )
    lines.append(
        "| 热词解码需要更宽搜索路径 | 总 RTF | "
        f"{baseline['rtf']:.3f} | {best['rtf']:.3f} | "
        f"增加 {best['rtf'] - baseline['rtf']:.3f} | 性能代价 |"
    )
    lines.append("")
    lines.append("## 系统对比")
    lines.append("")
    lines.append("| 系统 | 整体 CER | 热词精确命中率 | 样本全热词命中率 | 热词片段最小 CER | 总 RTF |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for row in summary["system_rows"]:
        lines.append(
            f"| {row['system']} | {pct(row['cer'])} | {pct(row['hotword_exact_hit_rate'])} | "
            f"{pct(row['sample_all_hotwords_hit_rate'])} | {pct(row['hotword_min_cer'])} | {row['rtf']:.3f} |"
        )
    lines.append("")
    lines.append("## 数据集")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("| --- | --- |")
    lines.append(f"| 样本数 | {summary['dataset']['num_samples']} |")
    lines.append(f"| 说话人数 | {summary['dataset']['num_speakers']} |")
    lines.append(f"| 热词总数 | {summary['dataset']['hotword_total']} |")
    lines.append(f"| 总时长 | {summary['dataset']['total_duration_sec']:.3f}s |")
    lines.append(f"| 单条时长 p50 / p90 | {summary['dataset']['duration_sec']['p50']:.3f}s / {summary['dataset']['duration_sec']['p90']:.3f}s |")
    lines.append("")
    lines.append("## 指标说明")
    lines.append("")
    lines.append("| 指标 | 名词说明 | 解决或暴露的问题 | 计算口径 | 数值解读 |")
    lines.append("| --- | --- | --- | --- | --- |")
    lines.append("| 热词精确命中率 | 标注热词是否作为连续字符串出现在识别结果中 | 专名、姓名、地名等容易被同音常见词替换 | 命中的热词数 / 标注热词总数 | 越高越好，是热词功能核心收益 |")
    lines.append("| 样本全热词命中率 | 一条音频里的全部热词是否都命中 | 一句话含多个热词时，只命中部分仍会影响业务 | 全部热词命中的样本数 / 样本数 | 越高越好 |")
    lines.append("| 热词片段最小 CER | 热词和识别文本中最相近片段的字符错误率 | 衡量热词未完全命中时是否更接近正确写法 | 每个热词与 hypothesis 所有近长子串取最小编辑距离后汇总 | 越低越好 |")
    lines.append("| 整体 CER | 整句字符错误率 | 观察热词偏置是否损伤非热词上下文 | sum(edit_distance(reference, hypothesis)) / sum(reference_chars) | 越低越好 |")
    lines.append("| RTF | 实时率，处理 1 秒音频需要多少秒 | 观察 modified_beam_search 和热词图带来的性能代价 | 解码耗时 / 音频时长 | 越低越好，小于 1 表示快于实时 |")
    lines.append("")
    lines.append("## 限制")
    lines.append("")
    lines.append("- 本实验只覆盖热词正样本，不评估未出现热词时的误插入风险。")
    lines.append("- 模型使用官方中英 demo zipformer，与具体交付模型可能有差异；结论应在交付模型上复标。")
    lines.append("- 开启热词组按 Android 当前行为同时切换到 modified_beam_search，报告中的 mbs_no_hotwords 用于观察 beam search 本身的影响。")
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--dataset-dir",
        type=Path,
        default=TEST_DATA_ROOT / "aishell3_test_hotwords_500",
    )
    p.add_argument(
        "--model-dir",
        type=Path,
        default=Path("asr/tools/demo-model/zipformer_L_zh_en"),
    )
    p.add_argument(
        "--bpe-vocab",
        type=Path,
        default=Path(
            "asr/tools/demo-model/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20/bpe.vocab"
        ),
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path("asr/tools/hotwords/results/aishell3_hotwords_eval"),
    )
    p.add_argument("--hotwords-scores", type=float, nargs="+", default=[3.0])
    p.add_argument("--max-n", type=int, default=None)
    p.add_argument("--num-threads", type=int, default=2)
    p.add_argument("--include-mbs-empty", action="store_true")
    p.add_argument("--print-every", type=int, default=25)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    samples = load_samples(args.dataset_dir)
    if args.max_n is not None:
        samples = samples[: args.max_n]
    if not samples:
        print("[ERROR] no samples", file=sys.stderr)
        return 2

    baseline_recognizer = build_recognizer(
        args.model_dir,
        decoding_method="greedy_search",
        max_active_paths=4,
        num_threads=args.num_threads,
        bpe_vocab=args.bpe_vocab,
    )
    mbs_empty_recognizer = None
    if args.include_mbs_empty:
        mbs_empty_recognizer = build_recognizer(
            args.model_dir,
            decoding_method="modified_beam_search",
            max_active_paths=8,
            num_threads=args.num_threads,
            bpe_vocab=args.bpe_vocab,
        )
    hotword_recognizers = {
        score: build_recognizer(
            args.model_dir,
            decoding_method="modified_beam_search",
            hotwords_score=score,
            max_active_paths=8,
            num_threads=args.num_threads,
            bpe_vocab=args.bpe_vocab,
        )
        for score in args.hotwords_scores
    }

    records: list[dict] = []
    t0 = time.time()
    jsonl_path = args.out_dir / "eval.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as fout:
        for i, sample in enumerate(samples, start=1):
            audio, _ = load_audio_mono16k(sample.audio_path)
            systems: dict[str, dict] = {}
            hyp, elapsed = decode(baseline_recognizer, audio, hotwords=None)
            systems["baseline_greedy"] = {
                **sample_metrics(sample.text, hyp, sample.hotwords),
                "decode_elapsed_sec": elapsed,
            }
            if mbs_empty_recognizer is not None:
                hyp, elapsed = decode(mbs_empty_recognizer, audio, hotwords=None)
                systems["mbs_no_hotwords"] = {
                    **sample_metrics(sample.text, hyp, sample.hotwords),
                    "decode_elapsed_sec": elapsed,
                }
            hotwords_buf = "\n".join(sample.hotwords)
            for score, recognizer in hotword_recognizers.items():
                key = f"hotwords_score_{score:g}"
                hyp, elapsed = decode(recognizer, audio, hotwords=hotwords_buf)
                systems[key] = {
                    **sample_metrics(sample.text, hyp, sample.hotwords),
                    "decode_elapsed_sec": elapsed,
                }
            rec = {
                "recording_id": sample.recording_id,
                "speaker": sample.speaker,
                "duration_sec": len(audio) / 16000.0,
                "reference_text": sample.text,
                "hotwords": sample.hotwords,
                "systems": systems,
            }
            records.append(rec)
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if args.print_every > 0 and i % args.print_every == 0:
                print(f"[RUN] {i}/{len(samples)}", file=sys.stderr)

    system_names = list(records[0]["systems"].keys())
    system_rows = [aggregate(records, name) for name in system_names]
    systems = {row["system"]: row for row in system_rows}
    primary_system = f"hotwords_score_{args.hotwords_scores[-1]:g}"
    durations = [r["duration_sec"] for r in records]
    hotword_counts = [len(r["hotwords"]) for r in records]
    summary = {
        "config": {
            "dataset_dir": str(args.dataset_dir),
            "model_dir": str(args.model_dir),
            "bpe_vocab": str(args.bpe_vocab),
            "hotwords_scores": args.hotwords_scores,
            "include_mbs_empty": args.include_mbs_empty,
            "elapsed_sec": time.time() - t0,
        },
        "dataset": {
            "num_samples": len(records),
            "num_speakers": len({r["speaker"] for r in records}),
            "hotword_total": sum(hotword_counts),
            "hotword_count": describe([float(x) for x in hotword_counts]),
            "total_duration_sec": sum(durations),
            "duration_sec": describe(durations),
        },
        "primary_system": primary_system,
        "system_rows": system_rows,
        "systems": systems,
    }
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.out_dir / "summary.md").write_text(render_md(summary), encoding="utf-8")
    print(f"[OK] wrote {jsonl_path}", file=sys.stderr)
    print(f"[OK] wrote {args.out_dir / 'summary.json'}", file=sys.stderr)
    print(f"[OK] wrote {args.out_dir / 'summary.md'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
