#!/usr/bin/env python3
"""TS-ASR 阶段 1 离线 pipeline（方案 A 工程化加固版）。

输入：
  - 一段或多段 wav 文件（输入路径列表，或 --input-jsonl 指向一个 jsonl 清单）
  - target_embedding.npy（由 01_enroll_target.py 产出）
  - 流式 zipformer ASR modelDir（来自 asr/tools/ 已导出量化好的产物）
  - silero_vad.onnx（由 00_download_models.sh 拉取）
  - 声纹 embedding 模型（与 enrollment 时同款）

Pipeline（与 plan 第 1 节 mermaid 图一一对应）：
  silero VAD 切段 → 最短 1.5s 门限 → 滑窗 2.5s/1.0s 多打分取 max
  → 双阈值（默认 HIGH 0.55 / LOW 0.25，必须 ROC 标定后回填）
  → target 段送流式 zipformer 整段推理（AcceptWaveform + 0.5s tail + InputFinished + while ready: decode）
  → 输出带 [target] / [other] / [unknown] 标签的转写

输出：
  - JSONL，每段一行：
      {"audio": "...", "seg_idx": 0, "start_sec": 1.23, "end_sec": 4.56,
       "duration_sec": 3.33, "score": 0.62, "label": "target",
       "text": "...", "asr_used": true}

为什么不在调研期就做流式 endpointing 嵌入：
  - VAD 切段 + 段后 verify + 整段 decode 是 sherpa-onnx 上游 speaker-identification-with-vad-non-streaming-asr.py
    的标准做法，调试简单
  - 流式嵌入需要把 verify 嵌进 OnlineRecognizer 的 endpointing 钩子，改动量大且与 ASR 解码状态耦合
  - 若 MVP 通过决策门进入 production，再把这部分搬到三端 SDK

用法：
  python asr/tools/speaker/02_ts_asr_offline.py \
    --asr-model-dir asr/tools/demo-model/asr-streaming-zipformer-zh-en-1.0.0/ \
    --speaker-model asr/tools/speaker/models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx \
    --silero-vad-model asr/tools/speaker/models/silero_vad.onnx \
    --target-embedding asr/tools/speaker/data/target_embedding.npy \
    --input path/to/test1.wav path/to/test2.wav \
    --out asr/tools/speaker/results/test_run.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Iterable, List, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "speaker"))

import sherpa_onnx  # noqa: E402

from ts_asr import (  # noqa: E402
    DEFAULT_HIGH,
    DEFAULT_HOP_SEC,
    DEFAULT_LOW,
    DEFAULT_MIN_SEG_SEC,
    DEFAULT_WIN_SEC,
    asr_decode_full_segment,
    build_recognizer,
    build_speaker,
    cosine,
    load_audio_mono16k,
    segment_score,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    p.add_argument(
        "--asr-model-dir",
        type=Path,
        required=True,
        help="流式 zipformer ASR modelDir（4 文件命名见 asr/tools/MODEL_LAYOUT.md）",
    )
    p.add_argument(
        "--speaker-model",
        type=Path,
        required=True,
        help="声纹 embedding ONNX 路径，必须与 enrollment 时使用的同款",
    )
    p.add_argument(
        "--silero-vad-model",
        type=Path,
        required=True,
        help="silero_vad.onnx 路径",
    )
    p.add_argument(
        "--target-embedding",
        type=Path,
        required=True,
        help="target_embedding.npy 路径，由 01_enroll_target.py 产出",
    )

    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--input",
        type=Path,
        nargs="+",
        help="输入 wav 文件路径列表",
    )
    src.add_argument(
        "--input-jsonl",
        type=Path,
        help="JSONL 清单，每行 {\"audio\": \"...\"}",
    )

    p.add_argument(
        "--out",
        type=Path,
        required=True,
        help="输出 JSONL 路径，每段一行",
    )

    p.add_argument("--threshold-high", type=float, default=DEFAULT_HIGH)
    p.add_argument("--threshold-low", type=float, default=DEFAULT_LOW)
    p.add_argument("--min-seg-sec", type=float, default=DEFAULT_MIN_SEG_SEC)
    p.add_argument("--win-sec", type=float, default=DEFAULT_WIN_SEC)
    p.add_argument("--hop-sec", type=float, default=DEFAULT_HOP_SEC)

    p.add_argument("--vad-min-silence-sec", type=float, default=0.25)
    p.add_argument("--vad-min-speech-sec", type=float, default=0.25)
    p.add_argument(
        "--vad-max-speech-sec",
        type=float,
        default=10.0,
        help="单段超过该值会被强制切；调研文档加固点未设此值，按上游默认 5s 偏短改 10s",
    )

    p.add_argument(
        "--decode-unknown",
        action="store_true",
        help="对中间态（LOW < score < HIGH）也跑 ASR，仅打 [unknown] 标签；默认丢弃",
    )
    p.add_argument(
        "--num-threads",
        type=int,
        default=2,
        help="ASR/embedding 各自的 num_threads",
    )
    p.add_argument("--provider", type=str, default="cpu")
    p.add_argument(
        "--print-stdout",
        action="store_true",
        help="同时把每段结果打到 stdout",
    )

    return p.parse_args()


def iter_inputs(args: argparse.Namespace) -> Iterable[Path]:
    if args.input:
        yield from args.input
        return
    with args.input_jsonl.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            yield Path(obj["audio"])


def vad_segment(
    samples: np.ndarray,
    silero_vad_path: Path,
    sample_rate: int,
    *,
    min_silence_sec: float,
    min_speech_sec: float,
    max_speech_sec: float,
) -> List[Tuple[int, np.ndarray]]:
    """同步切段：返回 [(start_sample_idx, segment_samples), ...]。"""
    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = str(silero_vad_path)
    config.silero_vad.threshold = 0.5
    config.silero_vad.min_silence_duration = min_silence_sec
    config.silero_vad.min_speech_duration = min_speech_sec
    config.silero_vad.max_speech_duration = max_speech_sec
    config.sample_rate = sample_rate
    if not config.validate():
        raise ValueError("silero_vad config invalid")

    window_size = config.silero_vad.window_size
    vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=100)

    segments: List[Tuple[int, np.ndarray]] = []
    cursor = samples
    while len(cursor) > window_size:
        vad.accept_waveform(cursor[:window_size])
        cursor = cursor[window_size:]
        while not vad.empty():
            seg = vad.front
            segments.append(
                (int(seg.start), np.asarray(seg.samples, dtype=np.float32))
            )
            vad.pop()
    vad.flush()
    while not vad.empty():
        seg = vad.front
        segments.append(
            (int(seg.start), np.asarray(seg.samples, dtype=np.float32))
        )
        vad.pop()
    return segments


def classify(score: float, *, high: float, low: float) -> str:
    if score >= high:
        return "target"
    if score <= low:
        return "other"
    return "unknown"


def process_file(
    audio_path: Path,
    *,
    target_emb: np.ndarray,
    extractor: "sherpa_onnx.SpeakerEmbeddingExtractor",
    recognizer: "sherpa_onnx.OnlineRecognizer",
    args: argparse.Namespace,
) -> List[dict]:
    samples, orig_sr = load_audio_mono16k(audio_path)
    sr = 16000

    t_vad_start = time.perf_counter()
    segments = vad_segment(
        samples,
        args.silero_vad_model,
        sample_rate=sr,
        min_silence_sec=args.vad_min_silence_sec,
        min_speech_sec=args.vad_min_speech_sec,
        max_speech_sec=args.vad_max_speech_sec,
    )
    vad_elapsed = time.perf_counter() - t_vad_start

    audio_dur = len(samples) / sr
    print(
        f"[FILE] {audio_path.name}  dur={audio_dur:.2f}s  segs={len(segments)}  "
        f"vad_elapsed={vad_elapsed:.2f}s  orig_sr={orig_sr}"
    )

    rows: List[dict] = []
    for idx, (start_idx, seg_samples) in enumerate(segments):
        start_sec = start_idx / sr
        seg_dur = len(seg_samples) / sr
        end_sec = start_sec + seg_dur

        score = segment_score(
            extractor,
            target_emb,
            seg_samples,
            sr=sr,
            win_sec=args.win_sec,
            hop_sec=args.hop_sec,
            min_seg_sec=args.min_seg_sec,
        )

        if score is None:
            row = {
                "audio": str(audio_path),
                "seg_idx": idx,
                "start_sec": round(start_sec, 3),
                "end_sec": round(end_sec, 3),
                "duration_sec": round(seg_dur, 3),
                "score": None,
                "label": "below_min_seg",
                "text": "",
                "asr_used": False,
            }
            rows.append(row)
            if args.print_stdout:
                print(
                    f"  [SKIP] seg{idx} {start_sec:6.2f}~{end_sec:6.2f}  "
                    f"dur={seg_dur:.2f}s  < min_seg_sec({args.min_seg_sec}s)"
                )
            continue

        label = classify(score, high=args.threshold_high, low=args.threshold_low)
        do_decode = label == "target" or (
            label == "unknown" and args.decode_unknown
        )

        text = ""
        if do_decode:
            text = asr_decode_full_segment(recognizer, seg_samples, sr=sr)

        row = {
            "audio": str(audio_path),
            "seg_idx": idx,
            "start_sec": round(start_sec, 3),
            "end_sec": round(end_sec, 3),
            "duration_sec": round(seg_dur, 3),
            "score": round(float(score), 4),
            "label": label,
            "text": text,
            "asr_used": do_decode,
        }
        rows.append(row)

        if args.print_stdout:
            tag = f"[{label}]"
            print(
                f"  {tag:9s} seg{idx} {start_sec:6.2f}~{end_sec:6.2f}  "
                f"dur={seg_dur:.2f}s  score={score:.3f}  {text}"
            )

    return rows


def main() -> int:
    args = parse_args()

    target_emb = np.load(args.target_embedding).astype(np.float32)
    print(
        f"[INFO] target embedding loaded: dim={target_emb.shape[0]}  "
        f"|emb|={float(np.linalg.norm(target_emb)):.4f} (≈1 表示已单位化)"
    )

    extractor = build_speaker(
        args.speaker_model,
        num_threads=1,
        provider=args.provider,
    )
    if extractor.dim != target_emb.shape[0]:
        print(
            f"[ERROR] embedding dim 不匹配：target={target_emb.shape[0]} "
            f"vs extractor={extractor.dim}。请确认 speaker-model 与 enrollment 时是同一个模型。",
            file=sys.stderr,
        )
        return 2

    recognizer = build_recognizer(
        args.asr_model_dir,
        num_threads=args.num_threads,
        provider=args.provider,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    n_files = 0
    n_target = n_other = n_unknown = n_short = 0
    t_total = time.perf_counter()
    with args.out.open("w") as fp:
        for audio_path in iter_inputs(args):
            if not audio_path.is_file():
                print(f"[WARN] 文件不存在，跳过: {audio_path}", file=sys.stderr)
                continue
            rows = process_file(
                audio_path,
                target_emb=target_emb,
                extractor=extractor,
                recognizer=recognizer,
                args=args,
            )
            for r in rows:
                fp.write(json.dumps(r, ensure_ascii=False) + "\n")
                if r["label"] == "target":
                    n_target += 1
                elif r["label"] == "other":
                    n_other += 1
                elif r["label"] == "unknown":
                    n_unknown += 1
                else:
                    n_short += 1
            n_files += 1
    elapsed = time.perf_counter() - t_total

    print(
        f"\n[DONE] files={n_files}  target={n_target}  other={n_other}  "
        f"unknown={n_unknown}  below_min={n_short}  elapsed={elapsed:.1f}s"
    )
    print(f"[OK  ] results -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
