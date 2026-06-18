#!/usr/bin/env python3
"""Amphion ASR 评估 WER 报告生成器（权威计算）。

输入：从设备端导出的 zip 或服务端落盘的目录（两者结构镜像）：

    <data_root>/<tester_id>/<sentence_id>/<recording_id>/{audio.wav,meta.json,hypothesis.txt}

输出：

    <output>/report.json          完整结构化结果
    <output>/report.md            人类可读 markdown
    <output>/per_recording.csv    每条录音的明细
    <output>/anomalies.md         on_device vs offline 差异大的样本（信号）

依赖：

    pip install sherpa-onnx jiwer

典型用法：

    python asr/tools/eval_wer.py \
      --data-root ./eval-data \
      --model-dir asr/tools/demo-model/zipformer_L_zh_en \
      --output ./report

模式：

    --mode offline    强制用 sherpa-onnx OfflineRecognizer（不走 endpoint）
    --mode streaming  用 OnlineRecognizer（默认）+ flush
    --mode none       不重跑识别，直接用 meta.on_device_hypothesis 算 WER
                      （比 streaming 快 100x，适合"先快速看 trend"场景）

设计原则：

- 与 docs/eval/SCHEMA.md 中 meta.json 字段严格对齐
- 与 sample/eval/DeviceWerEstimator.kt 的"现场估算"互为参照：差异大的样本写到
  anomalies.md，提示 ITN / 标点 / 中英分词的偏差信号
- 不依赖任何客户端代码，纯文件遍历
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import struct
import sys
import wave
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

try:
    import jiwer  # noqa: F401
except ImportError:
    print("missing jiwer; install via: pip install jiwer", file=sys.stderr)
    raise

# sherpa_onnx 只在 mode != none 时需要
try:
    import sherpa_onnx
except ImportError:
    sherpa_onnx = None


# ---------- 数据加载 ----------

@dataclass
class Sample:
    """一条录音的全部输入。"""

    recording_id: str
    tester_id: str
    sentence_id: str
    category_id: str
    reference_text: str
    audio_path: Path
    meta_path: Path
    meta: dict
    on_device_hypothesis: str | None
    on_device_wer_estimate: float | None

    @property
    def model_id(self) -> str | None:
        return self.meta.get("model_id")

    @property
    def noise_level(self) -> str:
        return self.meta.get("env", {}).get("noise_level", "unspecified")

    @property
    def device_manufacturer(self) -> str:
        return self.meta.get("device", {}).get("manufacturer", "unknown")


def iter_samples(data_root: Path) -> Iterable[Sample]:
    """递归遍历 data_root，yield 所有 finalized=true 的 Sample。"""
    for tester_dir in sorted(p for p in data_root.iterdir() if p.is_dir()):
        if tester_dir.name.startswith("_"):
            continue
        for sentence_dir in sorted(p for p in tester_dir.iterdir() if p.is_dir()):
            for rec_dir in sorted(p for p in sentence_dir.iterdir() if p.is_dir()):
                meta_path = rec_dir / "meta.json"
                audio_path = rec_dir / "audio.wav"
                if not meta_path.is_file() or not audio_path.is_file():
                    continue
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError) as e:
                    print(f"WARN skip {meta_path}: {e}", file=sys.stderr)
                    continue
                if not meta.get("finalized", False):
                    continue
                yield Sample(
                    recording_id=meta["recording_id"],
                    tester_id=meta["tester_id"],
                    sentence_id=meta["sentence_id"],
                    category_id=meta.get("category_id", ""),
                    reference_text=meta["reference_text"],
                    audio_path=audio_path,
                    meta_path=meta_path,
                    meta=meta,
                    on_device_hypothesis=meta.get("on_device_hypothesis"),
                    on_device_wer_estimate=meta.get("on_device_wer_estimate"),
                )


# ---------- 重跑识别 ----------

def load_wav_int16(path: Path) -> tuple[list[int], int]:
    with wave.open(str(path), "rb") as w:
        n = w.getnframes()
        sr = w.getframerate()
        ch = w.getnchannels()
        sw = w.getsampwidth()
        assert ch == 1 and sw == 2, f"{path}: expect mono 16-bit, got ch={ch} sw={sw}"
        samples = list(struct.unpack("<" + "h" * n, w.readframes(n)))
    return samples, sr


def to_float(samples: list[int]) -> list[float]:
    return [max(-1.0, min(1.0, s / 32768.0)) for s in samples]


class StreamingRecognizer:
    def __init__(self, model_dir: Path, num_threads: int):
        assert sherpa_onnx is not None
        self._r = sherpa_onnx.OnlineRecognizer.from_transducer(
            encoder=str(model_dir / "encoder.int8.onnx"),
            decoder=str(model_dir / "decoder.onnx"),
            joiner=str(model_dir / "joiner.int8.onnx"),
            tokens=str(model_dir / "tokens.txt"),
            num_threads=num_threads,
            sample_rate=16000,
            feature_dim=80,
            decoding_method="greedy_search",
            provider="cpu",
            enable_endpoint_detection=False,
        )

    def transcribe(self, samples_f32: list[float]) -> str:
        s = self._r.create_stream()
        s.accept_waveform(16000, samples_f32)
        s.accept_waveform(16000, [0.0] * 8000)
        s.input_finished()
        while self._r.is_ready(s):
            self._r.decode_stream(s)
        return self._r.get_result(s).text


class OfflineRecognizer:
    def __init__(self, model_dir: Path, num_threads: int):
        assert sherpa_onnx is not None
        # 注：offline 模型与 streaming 模型不通用；如果你的 model_dir 只有 streaming
        # 三件套，这个模式不可用。详见 asr/tools/MODEL_LAYOUT.md
        self._r = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(model_dir / "encoder.int8.onnx"),
            decoder=str(model_dir / "decoder.onnx"),
            joiner=str(model_dir / "joiner.int8.onnx"),
            tokens=str(model_dir / "tokens.txt"),
            num_threads=num_threads,
            sample_rate=16000,
            feature_dim=80,
            decoding_method="greedy_search",
            provider="cpu",
        )

    def transcribe(self, samples_f32: list[float]) -> str:
        s = self._r.create_stream()
        s.accept_waveform(16000, samples_f32)
        self._r.decode_stream(s)
        return self._r.get_result(s).text


# ---------- WER 计算 ----------

def normalize_text(s: str) -> str:
    """轻度 normalize：去掉首尾空白，合并多空格，去掉中文标点。"""
    if not s:
        return ""
    out = s.strip()
    # 中文标点 → 空格（保留英文逗号 / 句号给 jiwer tokenizer）
    table = str.maketrans({"，": " ", "。": " ", "！": " ", "？": " ", "、": " ", "：": " ", "；": " "})
    out = out.translate(table)
    # 合并多空格
    out = " ".join(out.split())
    return out


def compute_wer(ref: str, hyp: str) -> float:
    """对一对 ref/hyp 计算 WER。jiwer 默认按空格分词；
    对中文，jiwer 会把整句视为一个 token，结果非 0 即 1，意义不大。
    所以我们做混合策略：含 ASCII 的按词级（jiwer），纯中文按字符级。"""
    ref_n = normalize_text(ref)
    hyp_n = normalize_text(hyp)
    if not ref_n and not hyp_n:
        return 0.0
    if not ref_n:
        return 1.0

    has_ascii_ref = any(c.isascii() and c.isalpha() for c in ref_n)
    has_ascii_hyp = any(c.isascii() and c.isalpha() for c in hyp_n)
    if has_ascii_ref or has_ascii_hyp:
        return float(jiwer.wer(ref_n, hyp_n))
    # 纯中文：字符级
    return float(jiwer.cer(ref_n, hyp_n))


# ---------- 报告生成 ----------

@dataclass
class Result:
    sample: Sample
    hypothesis: str
    wer: float
    deviation_from_device: float | None = None  # offline_wer - on_device_wer_estimate


@dataclass
class GroupStats:
    name: str
    count: int
    wer_mean: float
    wer_median: float
    wer_p95: float

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "count": self.count,
            "wer_mean": self.wer_mean,
            "wer_median": self.wer_median,
            "wer_p95": self.wer_p95,
        }


def aggregate(results: list[Result], key_func) -> list[GroupStats]:
    groups: dict[str, list[float]] = defaultdict(list)
    for r in results:
        groups[key_func(r)].append(r.wer)
    out = []
    for k, wers in sorted(groups.items()):
        out.append(GroupStats(
            name=k,
            count=len(wers),
            wer_mean=statistics.mean(wers),
            wer_median=statistics.median(wers),
            wer_p95=percentile(wers, 95),
        ))
    return out


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * (p / 100.0)
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] + (s[c] - s[f]) * (k - f)


def write_report_json(results: list[Result], output_dir: Path) -> dict:
    summary = {
        "total": len(results),
        "wer_mean": statistics.mean(r.wer for r in results) if results else 0.0,
        "wer_median": statistics.median(r.wer for r in results) if results else 0.0,
        "wer_p95": percentile([r.wer for r in results], 95),
        "by_tester": [g.to_dict() for g in aggregate(results, lambda r: r.sample.tester_id)],
        "by_category": [g.to_dict() for g in aggregate(results, lambda r: r.sample.category_id or "<none>")],
        "by_noise": [g.to_dict() for g in aggregate(results, lambda r: r.sample.noise_level)],
        "by_manufacturer": [g.to_dict() for g in aggregate(results, lambda r: r.sample.device_manufacturer)],
        "by_model": [g.to_dict() for g in aggregate(results, lambda r: r.sample.model_id or "<unknown>")],
    }
    (output_dir / "report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def write_report_md(summary: dict, output_dir: Path) -> None:
    md = []
    md.append(f"# Amphion ASR 评估 WER 报告\n")
    md.append(f"总样本数: {summary['total']}\n")
    md.append(f"WER 均值: {summary['wer_mean']:.3f}")
    md.append(f"WER 中位数: {summary['wer_median']:.3f}")
    md.append(f"WER p95: {summary['wer_p95']:.3f}\n")

    for title, key in [
        ("按测试员", "by_tester"),
        ("按分类", "by_category"),
        ("按噪声等级", "by_noise"),
        ("按设备厂商", "by_manufacturer"),
        ("按模型", "by_model"),
    ]:
        md.append(f"## {title}\n")
        md.append("| 名称 | 样本数 | WER 均值 | WER 中位数 | WER p95 |")
        md.append("| --- | --- | --- | --- | --- |")
        for g in summary[key]:
            md.append(
                f"| {g['name']} | {g['count']} | {g['wer_mean']:.3f} | {g['wer_median']:.3f} | {g['wer_p95']:.3f} |"
            )
        md.append("")
    (output_dir / "report.md").write_text("\n".join(md), encoding="utf-8")


def write_csv(results: list[Result], output_dir: Path) -> None:
    with (output_dir / "per_recording.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "recording_id", "tester_id", "sentence_id", "category_id",
            "noise_level", "device", "model_id",
            "reference_text", "hypothesis", "wer",
            "on_device_hypothesis", "on_device_wer_estimate", "deviation",
        ])
        for r in results:
            w.writerow([
                r.sample.recording_id,
                r.sample.tester_id,
                r.sample.sentence_id,
                r.sample.category_id,
                r.sample.noise_level,
                r.sample.device_manufacturer,
                r.sample.model_id or "",
                r.sample.reference_text,
                r.hypothesis,
                f"{r.wer:.4f}",
                r.sample.on_device_hypothesis or "",
                f"{r.sample.on_device_wer_estimate:.4f}" if r.sample.on_device_wer_estimate is not None else "",
                f"{r.deviation_from_device:.4f}" if r.deviation_from_device is not None else "",
            ])


def write_anomalies(results: list[Result], output_dir: Path, threshold: float = 0.10) -> None:
    """挑出 offline WER 与 on_device WER 差距 > threshold 的样本，作为 ITN/标点信号。"""
    md = ["# 异常样本（offline vs on-device 差异 > {:.2f}）\n".format(threshold)]
    md.append("差异大可能是以下原因之一：\n- 设备端 ITN 把数字 normalize 了，offline 没\n"
              "- 设备端标点模型加了标点，offline 没\n"
              "- 中英分词差异\n")
    md.append("| recording_id | sentence | ref | hyp(offline) | hyp(on-device) | wer(offline) | wer(on-device) | Δ |")
    md.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    anomalies = [
        r for r in results
        if r.deviation_from_device is not None and abs(r.deviation_from_device) > threshold
    ]
    anomalies.sort(key=lambda r: abs(r.deviation_from_device or 0), reverse=True)
    for r in anomalies[:50]:
        md.append(
            f"| {r.sample.recording_id[:8]} | {r.sample.sentence_id} | "
            f"{r.sample.reference_text} | {r.hypothesis} | {r.sample.on_device_hypothesis or ''} | "
            f"{r.wer:.3f} | {r.sample.on_device_wer_estimate or 0:.3f} | "
            f"{r.deviation_from_device:+.3f} |"
        )
    if not anomalies:
        md.append("| (none) | | | | | | | |")
    (output_dir / "anomalies.md").write_text("\n".join(md), encoding="utf-8")


# ---------- Main ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--data-root", required=True, type=Path, help="录音数据根目录")
    ap.add_argument("--output", required=True, type=Path, help="报告输出目录")
    ap.add_argument("--mode", choices=["streaming", "offline", "none"], default="streaming",
                    help="streaming=用 OnlineRecognizer（默认）；offline=OfflineRecognizer；"
                         "none=直接用 meta.on_device_hypothesis（最快）")
    ap.add_argument("--model-dir", type=Path,
                    help="模型目录（mode=streaming/offline 时必须）")
    ap.add_argument("--num-threads", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条（调试用）")
    args = ap.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    samples = list(iter_samples(args.data_root))
    if args.limit > 0:
        samples = samples[:args.limit]
    if not samples:
        print(f"no samples found under {args.data_root}", file=sys.stderr)
        return 1
    print(f"found {len(samples)} samples")

    recognizer = None
    if args.mode != "none":
        if sherpa_onnx is None:
            print("sherpa_onnx not installed; either pip install sherpa-onnx or use --mode none",
                  file=sys.stderr)
            return 2
        if not args.model_dir or not args.model_dir.is_dir():
            print("--model-dir required for mode=streaming/offline", file=sys.stderr)
            return 2
        recognizer = (
            StreamingRecognizer(args.model_dir, args.num_threads)
            if args.mode == "streaming"
            else OfflineRecognizer(args.model_dir, args.num_threads)
        )

    results: list[Result] = []
    for i, s in enumerate(samples):
        if args.mode == "none":
            hyp = s.on_device_hypothesis or ""
        else:
            try:
                pcm, _sr = load_wav_int16(s.audio_path)
                hyp = recognizer.transcribe(to_float(pcm))
            except Exception as e:
                print(f"WARN decode {s.recording_id} failed: {e}", file=sys.stderr)
                hyp = ""
        wer = compute_wer(s.reference_text, hyp)
        dev = None
        if s.on_device_wer_estimate is not None:
            dev = wer - s.on_device_wer_estimate
        results.append(Result(sample=s, hypothesis=hyp, wer=wer, deviation_from_device=dev))
        if (i + 1) % 20 == 0:
            print(f"  decoded {i + 1}/{len(samples)} ...")

    summary = write_report_json(results, args.output)
    write_report_md(summary, args.output)
    write_csv(results, args.output)
    write_anomalies(results, args.output)

    print(f"\nreport written to {args.output}/")
    print(f"  WER mean   = {summary['wer_mean']:.3f}")
    print(f"  WER median = {summary['wer_median']:.3f}")
    print(f"  WER p95    = {summary['wer_p95']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
