#!/usr/bin/env python3
"""离线对照：把 Android sample dump 的 wav 用同一模型在 PC 上 decode，对比实机识别。

典型用法（需要先 pip install sherpa-onnx）：

    python3 tools/asr/decode_offline.py \
      --model-dir tools/asr/demo-model/asr-streaming-zipformer-zh-en-v1-1.0.0 \
      --wav /tmp/asr-dump/2026-05-13_142052/audio.wav \
      --segments 0:5:utt1 5:11:utt2 \
      --gains 0 10

输出：每个 (segment, gain, decoder) 组合的离线识别文本与 RMS。

用途：
- 排查「实机识别 ≠ 模型实际能力」是不是 streaming/endpoint/电平 的锅
- 快速对比 greedy vs modified_beam_search
- 快速验证「+N dB 软增益」对识别的影响
"""

import argparse
import math
import struct
import wave

import sherpa_onnx


def load_wav(path):
    with wave.open(path, "rb") as w:
        n = w.getnframes()
        sr = w.getframerate()
        ch = w.getnchannels()
        sw = w.getsampwidth()
        assert ch == 1 and sw == 2, f"expect mono 16-bit, got ch={ch} sw={sw}"
        samples = struct.unpack("<" + "h" * n, w.readframes(n))
    return list(samples), sr


def to_float(samples, gain_db=0.0):
    g = 10 ** (gain_db / 20.0)
    return [max(-1.0, min(1.0, s / 32768.0 * g)) for s in samples]


def slice_samples(samples, sr, t0, t1):
    return samples[int(t0 * sr):int(t1 * sr)]


def rms_db(seg):
    if not seg:
        return float("nan")
    sq = sum(s * s for s in seg) / len(seg)
    if sq <= 1:
        return -120.0
    return 10 * math.log10(sq / (32768 * 32768))


def make_recognizer(model_dir, decoding_method, max_active_paths,
                    sample_rate, feature_dim, model_type):
    return sherpa_onnx.OnlineRecognizer.from_transducer(
        encoder=f"{model_dir}/encoder.int8.onnx",
        decoder=f"{model_dir}/decoder.onnx",
        joiner=f"{model_dir}/joiner.int8.onnx",
        tokens=f"{model_dir}/tokens.txt",
        num_threads=2,
        sample_rate=sample_rate,
        feature_dim=feature_dim,
        decoding_method=decoding_method,
        max_active_paths=max_active_paths,
        provider="cpu",
        enable_endpoint_detection=False,
        model_type=model_type,
    )


def decode_segment(recognizer, samples_f32, sr):
    s = recognizer.create_stream()
    s.accept_waveform(sr, samples_f32)
    s.accept_waveform(sr, [0.0] * (sr // 2))
    s.input_finished()
    while recognizer.is_ready(s):
        recognizer.decode_stream(s)
    return recognizer.get_result(s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", required=True,
                    help="模型目录，需含 encoder.int8.onnx / decoder.onnx / joiner.int8.onnx / tokens.txt")
    ap.add_argument("--wav", required=True, help="dump 出来的 audio.wav")
    ap.add_argument("--segments", nargs="*", default=[],
                    help="t0:t1:label 列表，例 0:5:utt1 5:11:utt2；省略则跑整段")
    ap.add_argument("--gains", nargs="*", type=float, default=[0.0, 10.0],
                    help="dB 增益列表，默认 0 + 10")
    ap.add_argument("--decoders", nargs="*", default=["greedy", "mbs8"],
                    choices=["greedy", "mbs4", "mbs8", "mbs16"],
                    help="要对比的 decoder 组合，默认 greedy + mbs8")
    ap.add_argument("--sample-rate", type=int, default=16000)
    ap.add_argument("--feature-dim", type=int, default=80)
    ap.add_argument("--model-type", default="zipformer2")
    args = ap.parse_args()

    samples, sr = load_wav(args.wav)
    print(f"loaded {args.wav}: dur={len(samples)/sr:.2f}s sr={sr}")

    segs = []
    for s in args.segments:
        t0, t1, label = s.split(":")
        segs.append((float(t0), float(t1), label))
    if not segs:
        segs = [(0.0, len(samples) / sr, "all")]

    decoder_specs = {
        "greedy": ("greedy_search", 1),
        "mbs4":   ("modified_beam_search", 4),
        "mbs8":   ("modified_beam_search", 8),
        "mbs16":  ("modified_beam_search", 16),
    }
    cache = {}
    for d in args.decoders:
        method, mp = decoder_specs[d]
        cache[d] = make_recognizer(args.model_dir, method, mp,
                                   args.sample_rate, args.feature_dim, args.model_type)

    print()
    print(f"{'segment':<14s} {'gain':>6s}  {'decoder':<7s}  text  (rms_dBFS)")
    print("-" * 80)
    for (t0, t1, label) in segs:
        seg_short = slice_samples(samples, sr, t0, t1)
        d = rms_db(seg_short)
        for gain in args.gains:
            seg_f32 = to_float(seg_short, gain_db=gain)
            for decoder in args.decoders:
                text = decode_segment(cache[decoder], seg_f32, sr)
                gtag = f"+{gain:.0f}dB" if gain != 0 else "0dB"
                print(f"{label:<14s} {gtag:>6s}  {decoder:<7s}  {text!r}  ({d:.1f})")
        print()


if __name__ == "__main__":
    main()