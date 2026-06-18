#!/usr/bin/env python3
"""主机 CPU 上的声纹模型 RTF 估算（量级参考用）。

为什么是主机 CPU 而不是 Android arm64（与 plan 第 4 节对应说明）：
  - sherpa-onnx 上游没有"对单文件 wav 跑 embedding 并量耗时"的 CLI 二进制
  - SherpaOnnxSpeakerIdentification sample APK 不打耗时 logcat
  - Android 真机自动量 RTF 需要自己编 NDK bench，成本不匹配调研期投入
  - 主机 CPU 给量级参考已足够支撑决策门（HIGH/LOW 阈值 + 是否换 CAM++ 选型）
  - 真机精确 RTF 等 production SDK 工程化阶段，给 SpeakerEngine 加 trace 再量

判定参考（来自调研文档第 4 步）：
  - CAM++ 在 BM1684X int8 上 ~58ms / 1s 输入
  - 主流移动端 CPU FP32 估计 50-200ms / 1s 输入
  - Android arm64-v8a 通常比 Mac/Linux x86_64 CPU 慢 1.5-2.5 倍

输出：
  - asr/tools/speaker/results/rtf_local.json，含每个声纹模型 + 每个窗长的 RTF

用法：
  python asr/tools/speaker/05_rtf_local.py \
    --speaker-models \
      asr/tools/speaker/models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx \
      asr/tools/speaker/models/wespeaker_en_voxceleb_CAM++.onnx \
    --bench-wav path/to/any_clean_speech.wav \
    --window-secs 1.0 2.5 5.0 \
    --warmup 2 --runs 10 \
    --out asr/tools/speaker/results/rtf_local.json
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Dict, List

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "speaker"))

from ts_asr import build_speaker, load_audio_mono16k  # noqa: E402


def bench_one_model(
    model_path: Path,
    samples: np.ndarray,
    *,
    window_secs: List[float],
    warmup: int,
    runs: int,
    sr: int,
    num_threads: int,
    provider: str,
) -> Dict[str, Dict[str, float]]:
    extractor = build_speaker(model_path, num_threads=num_threads, provider=provider)
    print(f"\n[BENCH] {model_path.name}  dim={extractor.dim}")

    out: Dict[str, Dict[str, float]] = {}
    for w_sec in window_secs:
        n_win = int(w_sec * sr)
        if len(samples) < n_win:
            print(
                f"  [SKIP] window {w_sec}s 超过 wav 长度 {len(samples)/sr:.2f}s，跳过"
            )
            continue
        seg = np.ascontiguousarray(samples[:n_win])

        for _ in range(warmup):
            stream = extractor.create_stream()
            stream.accept_waveform(sample_rate=sr, waveform=seg)
            stream.input_finished()
            _ = extractor.compute(stream)

        durations: List[float] = []
        for _ in range(runs):
            t0 = time.perf_counter()
            stream = extractor.create_stream()
            stream.accept_waveform(sample_rate=sr, waveform=seg)
            stream.input_finished()
            _ = extractor.compute(stream)
            durations.append(time.perf_counter() - t0)

        median_ms = statistics.median(durations) * 1000.0
        p10_ms = sorted(durations)[max(0, int(len(durations) * 0.1) - 1)] * 1000.0
        p90_ms = sorted(durations)[int(len(durations) * 0.9) - 1] * 1000.0
        rtf = median_ms / (w_sec * 1000.0)

        out[f"{w_sec}s"] = {
            "median_ms": round(median_ms, 2),
            "p10_ms": round(p10_ms, 2),
            "p90_ms": round(p90_ms, 2),
            "rtf": round(rtf, 4),
        }
        print(
            f"  win={w_sec:.1f}s  median={median_ms:7.2f}ms  "
            f"[{p10_ms:6.2f}, {p90_ms:6.2f}]  rtf={rtf:.4f}"
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--speaker-models",
        type=Path,
        nargs="+",
        required=True,
        help="一个或多个声纹模型路径，逐个 bench",
    )
    parser.add_argument(
        "--bench-wav",
        type=Path,
        required=True,
        help="一段干净语音，至少 5s；脚本会从开头切等长窗口",
    )
    parser.add_argument(
        "--window-secs",
        type=float,
        nargs="+",
        default=[1.0, 2.5, 5.0],
        help="bench 的窗长列表（秒）；默认 1.0 2.5 5.0",
    )
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--num-threads", type=int, default=1)
    parser.add_argument("--provider", type=str, default="cpu")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("asr/tools/speaker/results/rtf_local.json"),
    )
    args = parser.parse_args()

    samples, orig_sr = load_audio_mono16k(args.bench_wav)
    sr = 16000
    print(
        f"[AUDIO] {args.bench_wav.name}  dur={len(samples)/sr:.2f}s  "
        f"orig_sr={orig_sr}"
    )

    report: Dict[str, object] = {
        "host": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "python": platform.python_version(),
        },
        "bench_wav": str(args.bench_wav),
        "wav_duration_sec": round(len(samples) / sr, 3),
        "warmup": args.warmup,
        "runs": args.runs,
        "num_threads": args.num_threads,
        "provider": args.provider,
        "models": {},
        "decision_hint": (
            "决策门参考：主机 CPU 1.0s 窗 RTF > 0.3 即对应 Android arm64-v8a "
            "可能 RTF > 0.5，触发 plan 第 5 节'优先换 CAM++ INT8'分支。仅作量级参考。"
        ),
    }

    for m in args.speaker_models:
        if not m.is_file():
            print(f"[WARN] 模型不存在，跳过: {m}", file=sys.stderr)
            continue
        report["models"][m.name] = bench_one_model(
            m,
            samples,
            window_secs=args.window_secs,
            warmup=args.warmup,
            runs=args.runs,
            sr=sr,
            num_threads=args.num_threads,
            provider=args.provider,
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\n[OK] full report -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
