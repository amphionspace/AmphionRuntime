#!/usr/bin/env python3
"""TS-ASR 阶段 1 多模板注册脚本。

输入：
  - 至少 3 段 enrollment 音频（推荐 5-10s/段，不同语速/距离/设备）
  - 声纹 embedding 模型（默认 3D-Speaker eres2net；--speaker-model 可改 CAM++）

输出：
  - target_embedding.npy（已单位化的均值 embedding，dtype=float32，shape=[dim]）
  - target_embedding.meta.json（注册音频清单与每段时长，方便复盘）

为什么要多模板（对应调研文档第 4.1 节加固点 1）：
  - 单段注册在跨域（远场 / 方言 / 信道）下 EER 会从 6.78% 升到 11-13%
  - 多段均值能直接抵消"短音频不稳"和"跨域漂移"两个失败域
  - 实操中 ≥3 段、覆盖不同声学条件比 1 段 30s 更有效

用法：
  python asr/tools/speaker/01_enroll_target.py \
    --speaker-model asr/tools/speaker/models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx \
    --enroll-wavs path/to/enroll1.wav path/to/enroll2.wav path/to/enroll3.wav \
    --out asr/tools/speaker/data/target_embedding.npy
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools" / "speaker"))

from ts_asr import build_speaker, enroll, load_audio_mono16k  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--speaker-model",
        type=Path,
        required=True,
        help="声纹 embedding ONNX 路径，例如 asr/tools/speaker/models/3dspeaker_*.onnx",
    )
    p.add_argument(
        "--enroll-wavs",
        type=Path,
        nargs="+",
        required=True,
        help="enrollment 音频路径列表；推荐 ≥3 段，每段 5-10s",
    )
    p.add_argument(
        "--out",
        type=Path,
        required=True,
        help="输出 target_embedding.npy 路径；同名 .meta.json 自动落盘",
    )
    p.add_argument("--num-threads", type=int, default=1)
    p.add_argument("--provider", type=str, default="cpu")
    p.add_argument(
        "--allow-fewer-than-3",
        action="store_true",
        help="放宽 ≥3 段约束，仅在调研阶段试跑时使用",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if len(args.enroll_wavs) < 3 and not args.allow_fewer_than_3:
        print(
            f"[ERROR] enrollment 段数 {len(args.enroll_wavs)} < 3。"
            "调研文档加固点 1 要求 ≥3 段；如确需放宽，加 --allow-fewer-than-3。",
            file=sys.stderr,
        )
        return 2

    for w in args.enroll_wavs:
        if not w.is_file():
            print(f"[ERROR] enrollment 音频不存在: {w}", file=sys.stderr)
            return 2

    extractor = build_speaker(
        args.speaker_model,
        num_threads=args.num_threads,
        provider=args.provider,
    )
    dim = extractor.dim
    print(f"[INFO] embedding dim = {dim}")

    wavs = []
    meta_segments = []
    for w in args.enroll_wavs:
        samples, sr = load_audio_mono16k(w)
        wavs.append((samples, 16000))
        dur = len(samples) / 16000.0
        meta_segments.append(
            {"path": str(w), "duration_sec": round(dur, 3), "orig_sample_rate": sr}
        )
        print(f"[ENROLL] {w.name}  {dur:.2f}s  (orig {sr} Hz)")

    short = [m for m in meta_segments if m["duration_sec"] < 3.0]
    if short:
        print(
            f"[WARN] 以下 enrollment 段 < 3s，embedding 可能不稳：{[m['path'] for m in short]}"
        )

    emb = enroll(extractor, wavs)
    if emb.shape != (dim,):
        print(
            f"[ERROR] embedding shape 异常: 期望 ({dim},)，得到 {emb.shape}",
            file=sys.stderr,
        )
        return 3

    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.save(args.out, emb.astype(np.float32))
    print(f"[OK  ] target embedding saved: {args.out}  shape={emb.shape}")

    meta_path = args.out.with_suffix(args.out.suffix + ".meta.json")
    meta = {
        "speaker_model": str(args.speaker_model),
        "embedding_dim": int(dim),
        "num_segments": len(args.enroll_wavs),
        "enroll_segments": meta_segments,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "已单位化（L2 归一）+ 多段均值；阈值需在 03_eval.py 出结果后回填",
    }
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print(f"[OK  ] meta saved: {meta_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
