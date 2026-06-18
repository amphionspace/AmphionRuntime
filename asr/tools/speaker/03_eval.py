#!/usr/bin/env python3
"""TS-ASR 评估主跑脚本：对每条 cut 同时算 verify_score + ASR hypothesis。

设计原理（第一性原理）：

1. baseline = 纯 ASR 跑混合音，hypothesis 无任何门控
2. 方案 A = 同样的 ASR hypothesis，只在 verify_score 跨过阈值时被采纳
3. 既然 hypothesis 是同一份，对每条 cut 跑 1 次 ASR 即可同时支撑两条曲线
   （而不是为 baseline 跑一次、为方案 A 再跑一次）

输出 JSONL，每行一条 cut。下游 04_eval_summary.py（待写）读这份 JSONL 即可
按 sample_type / overlap_ratio / num_interferers / language / source_dataset
分桶计算 baseline CER/WER 与方案 A 各阈值下的 FAR/FRR/CER/WER。

Pipeline 简化与决策：

- 不再做 silero VAD 切段：测试集 cuts 本身已是按 utterance 切好的短段
  （median 5.19s，<1.5s 占 0.3%）；二次 VAD 没有信息增益且会引入边界误差
- segment_score() 内部仍做 "≥1.5s 门限 + 滑窗 2.5s/1.0s 取 max"，覆盖加固
  点 2 / 3
- 多模板注册采用"贴业务"策略：每条 cut 用自己的 enrollment_audio 单段注册
  （加固点 1 的 ablation 留待二阶优化跑一次"按 speaker 聚合"）
- ASR 无条件跑，无论 verify 是否通过都解码出来；下游 summary 按阈值分桶时
  按 verify_score 决定方案 A 是否采纳本条 hypothesis

性能预算（host CPU）：
- speaker emb 单段 RTF ~0.05-0.1
- ASR zipformer L INT8 RTF ~0.15-0.3
- 每条 cut 平均 ~1.5s 处理时间，6555 条全量约 2.5-3 小时
- 第一版建议先跑 --max-n 50 sanity，再决定全量

用法：

    # sanity（覆盖各桶各 5-10 条）
    python asr/tools/speaker/03_eval.py \
        --cuts /Users/boxp/data/ts_hw_test/ts_hw_test_cuts_all.jsonl.gz \
        --asr-model-dir asr/tools/demo-model/zipformer_L_zh_en \
        --speaker-model asr/tools/speaker/models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx \
        --out asr/tools/speaker/results/eval_sanity.jsonl \
        --max-n 50 --stratified

    # 全量
    python asr/tools/speaker/03_eval.py \
        --cuts /Users/boxp/data/ts_hw_test/ts_hw_test_cuts_all.jsonl.gz \
        --asr-model-dir asr/tools/demo-model/zipformer_L_zh_en \
        --speaker-model asr/tools/speaker/models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx \
        --out asr/tools/speaker/results/eval_full.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

# 让脚本独立可跑：把 asr/tools/speaker/ 加进 sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ts_asr import (  # noqa: E402
    DEFAULT_HIGH,
    DEFAULT_LOW,
    DEFAULT_MIN_SEG_SEC,
    DEFAULT_WIN_SEC,
    DEFAULT_HOP_SEC,
    EvalSample,
    TsHwTestDataset,
    asr_decode_full_segment,
    build_recognizer,
    build_speaker,
    enroll,
    segment_score,
)


def stratified_sample(
    ds: TsHwTestDataset, *, total: int, seed: int = 42
) -> list[EvalSample]:
    """按 sample_type × overlap_ratio 分层抽样，覆盖 6 个桶。

    桶定义（与 Target_speaker.md 6.x 节对应）：
        B1 positive 0.1<=ovl<0.2
        B2 positive 0.2<=ovl<0.3
        B3 positive 0.3<=ovl<0.5
        B4 positive ovl>=0.5
        B5 negative_distractor
        B6 negative_silence
    """
    buckets = [
        ("B1_overlap_0.1-0.2", dict(sample_type="positive", overlap_min=0.1, overlap_max=0.2)),
        ("B2_overlap_0.2-0.3", dict(sample_type="positive", overlap_min=0.2, overlap_max=0.3)),
        ("B3_overlap_0.3-0.5", dict(sample_type="positive", overlap_min=0.3, overlap_max=0.5)),
        ("B4_overlap_>=0.5", dict(sample_type="positive", overlap_min=0.5)),
        ("B5_negative_distractor", dict(sample_type="negative_distractor")),
        ("B6_negative_silence", dict(sample_type="negative_silence")),
    ]
    per_bucket = max(total // len(buckets), 1)
    out: list[EvalSample] = []
    seen: set[str] = set()
    for name, kw in buckets:
        n_before = len(out)
        for s in ds.iter(max_n=per_bucket, seed=seed, **kw):
            if s.cut_id in seen:
                continue
            seen.add(s.cut_id)
            out.append(s)
        print(
            f"[STRATIFY] {name}: 抽到 {len(out) - n_before}/{per_bucket} 条",
            file=sys.stderr,
        )
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="TS-ASR 评估：每条 cut 跑 verify + ASR，输出 JSONL"
    )
    p.add_argument("--cuts", required=True, type=Path, help="cuts.jsonl.gz")
    p.add_argument(
        "--asr-model-dir",
        required=True,
        type=Path,
        help="流式 zipformer modelDir，含 4 个标准文件名",
    )
    p.add_argument(
        "--speaker-model",
        required=True,
        type=Path,
        help="声纹 onnx 模型路径",
    )
    p.add_argument(
        "--out", required=True, type=Path, help="输出 JSONL 路径（追加写入）"
    )
    p.add_argument("--max-n", type=int, default=None, help="最多跑 N 条")
    p.add_argument(
        "--stratified",
        action="store_true",
        help="启用分层抽样（与 --max-n 配合，覆盖 6 个桶）",
    )
    p.add_argument(
        "--source-dataset",
        type=str,
        default=None,
        help="只跑某个 source_dataset",
    )
    p.add_argument(
        "--language", type=str, default=None, help="只跑某种语言（zh / en）"
    )
    p.add_argument("--num-threads-asr", type=int, default=2)
    p.add_argument("--num-threads-spk", type=int, default=1)
    p.add_argument("--win-sec", type=float, default=DEFAULT_WIN_SEC)
    p.add_argument("--hop-sec", type=float, default=DEFAULT_HOP_SEC)
    p.add_argument("--min-seg-sec", type=float, default=DEFAULT_MIN_SEG_SEC)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--audio-root-remote",
        type=str,
        default=None,
        help="路径 rebase 的 remote 前缀；默认用 dataset 模块的常量",
    )
    p.add_argument(
        "--audio-root-local",
        type=str,
        default=None,
        help="路径 rebase 的 local 前缀；默认用 dataset 模块的常量",
    )
    p.add_argument(
        "--resume",
        action="store_true",
        help="如果 --out 已存在，跳过其中的 cut_id（断点续跑）",
    )
    p.add_argument(
        "--print-every",
        type=int,
        default=10,
        help="每跑 N 条打印一次进度",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)

    print(f"[BOOT] 加载 cuts: {args.cuts}", file=sys.stderr)
    ds_kwargs: dict = {}
    if args.audio_root_remote:
        ds_kwargs["audio_root_remote"] = args.audio_root_remote
    if args.audio_root_local:
        ds_kwargs["audio_root_local"] = args.audio_root_local
    ds = TsHwTestDataset(args.cuts, **ds_kwargs)
    print(f"[BOOT] cuts 共 {len(ds)} 条", file=sys.stderr)

    skip_ids: set[str] = set()
    if args.resume and args.out.is_file():
        with args.out.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if isinstance(rec, dict) and "cut_id" in rec:
                        skip_ids.add(rec["cut_id"])
                except json.JSONDecodeError:
                    continue
        print(
            f"[RESUME] {args.out} 已有 {len(skip_ids)} 条记录，将跳过",
            file=sys.stderr,
        )

    if args.stratified:
        if args.max_n is None:
            print("[ERROR] --stratified 需要同时指定 --max-n", file=sys.stderr)
            return 2
        candidates = stratified_sample(ds, total=args.max_n, seed=args.seed)
        samples = [s for s in candidates if s.cut_id not in skip_ids]
    else:
        # 先用 dataset 过滤 source_dataset / language，再过滤 skip_ids，最后 max_n。
        # 这是 --resume 与 --max-n 协同的正确顺序：先排除已跑，再按抽样上限取。
        candidates = list(
            ds.iter(
                source_dataset=args.source_dataset,
                language=args.language,
            )
        )
        candidates = [s for s in candidates if s.cut_id not in skip_ids]
        if args.max_n is not None and len(candidates) > args.max_n:
            rng = np.random.default_rng(args.seed)
            idxs = rng.permutation(len(candidates))[: args.max_n]
            samples = [candidates[int(i)] for i in idxs]
        else:
            samples = candidates

    if not samples:
        print("[INFO] 没有需要跑的新样本（可能已全部 resume 完）", file=sys.stderr)
        return 0

    print(f"[BOOT] 加载 ASR modelDir: {args.asr_model_dir}", file=sys.stderr)
    recognizer = build_recognizer(
        args.asr_model_dir, num_threads=args.num_threads_asr
    )
    print(f"[BOOT] 加载声纹模型: {args.speaker_model}", file=sys.stderr)
    extractor = build_speaker(
        args.speaker_model, num_threads=args.num_threads_spk
    )

    print(f"[RUN ] 待评估 {len(samples)} 条 → {args.out}", file=sys.stderr)
    t_run_start = time.time()

    with args.out.open("a", encoding="utf-8") as fout:
        ok = 0
        err = 0
        for i, sample in enumerate(samples):
            t0 = time.time()
            try:
                rec_audio, _ = sample.load_audio()
            except Exception as e:  # pragma: no cover
                print(
                    f"[ERR ] {sample.cut_id} load_audio 失败: {e}", file=sys.stderr
                )
                err += 1
                continue
            t_load_a = time.time() - t0

            t0 = time.time()
            try:
                enroll_audio, _ = sample.load_enrollment_audio()
            except Exception as e:  # pragma: no cover
                print(
                    f"[ERR ] {sample.cut_id} load_enrollment 失败: {e}",
                    file=sys.stderr,
                )
                err += 1
                continue
            t_load_e = time.time() - t0

            t0 = time.time()
            try:
                target_emb = enroll(extractor, [(enroll_audio, 16000)])
            except Exception as e:
                print(
                    f"[ERR ] {sample.cut_id} enroll 失败: {e}", file=sys.stderr
                )
                err += 1
                continue
            t_enroll = time.time() - t0

            t0 = time.time()
            verify_score = segment_score(
                extractor,
                target_emb,
                rec_audio,
                sr=16000,
                win_sec=args.win_sec,
                hop_sec=args.hop_sec,
                min_seg_sec=args.min_seg_sec,
            )
            t_verify = time.time() - t0

            t0 = time.time()
            try:
                hyp = asr_decode_full_segment(recognizer, rec_audio, sr=16000)
            except Exception as e:
                print(
                    f"[ERR ] {sample.cut_id} ASR 失败: {e}", file=sys.stderr
                )
                err += 1
                continue
            t_asr = time.time() - t0

            row = {
                "cut_id": sample.cut_id,
                "sample_type": sample.sample_type,
                "speaker_id": sample.speaker_id,
                "language": sample.language,
                "source_dataset": sample.source_dataset,
                "duration_sec": sample.duration,
                "enrollment_duration_sec": sample.enrollment_duration,
                "overlap_ratio": sample.overlap_ratio,
                "num_interferers": sample.num_interferers,
                "target_snr_db": sample.target_snr_db,
                "noise_source": sample.noise_source,
                "reference_text": sample.text,
                "verify_score": verify_score,
                "hypothesis_text": hyp,
                "timings_sec": {
                    "load_audio": round(t_load_a, 4),
                    "load_enroll": round(t_load_e, 4),
                    "enroll": round(t_enroll, 4),
                    "verify": round(t_verify, 4),
                    "asr": round(t_asr, 4),
                },
            }
            fout.write(json.dumps(row, ensure_ascii=False) + "\n")
            fout.flush()
            ok += 1

            if (i + 1) % args.print_every == 0:
                elapsed = time.time() - t_run_start
                avg = elapsed / (i + 1)
                eta = avg * (len(samples) - (i + 1))
                print(
                    f"[PROG] {i + 1}/{len(samples)} ok={ok} err={err}"
                    f" avg={avg:.2f}s/cut elapsed={elapsed:.0f}s eta={eta:.0f}s",
                    file=sys.stderr,
                )

    elapsed = time.time() - t_run_start
    print(
        f"[DONE] 跑完 {ok} 条 (err {err})，总耗时 {elapsed:.1f}s（{elapsed / max(ok,1):.2f}s/cut）",
        file=sys.stderr,
    )
    print(f"[DONE] 输出: {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
