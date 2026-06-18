#!/usr/bin/env python3
"""模拟 Android sample 的 streaming 行为，对比 greedy / modified_beam_search。

典型用法（需要先 pip install sherpa-onnx）：

    python3 asr/tools/decode_streaming.py \
      --model-dir asr/tools/demo-model/zipformer_L_zh_en \
      --wav /tmp/asr-dump/2026-05-13_144818/audio.wav \
      --segments 0:8:en1 8:16:en2 \
      --gain 10

此脚本与 decode_offline.py 的区别：
- decode_offline.py 一次性投递整段音频，适合看模型上限
- decode_streaming.py 按 100ms chunk 投递，启用 endpoint，并可模拟 800ms encoder warmup，
  更接近 Android 端实时使用行为
"""

import argparse
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
    return [s / 32768.0 for s in samples], sr


def slice_samples(samples, sr, t0, t1):
    return samples[int(t0 * sr):int(t1 * sr)]


def apply_gain(samples, gain_db):
    if gain_db == 0:
        return samples
    g = 10 ** (gain_db / 20.0)
    return [max(-1.0, min(1.0, s * g)) for s in samples]


def make_recognizer(model_dir, decoding_method, max_active_paths, args):
    return sherpa_onnx.OnlineRecognizer.from_transducer(
        encoder=f"{model_dir}/encoder.int8.onnx",
        decoder=f"{model_dir}/decoder.onnx",
        joiner=f"{model_dir}/joiner.int8.onnx",
        tokens=f"{model_dir}/tokens.txt",
        num_threads=args.num_threads,
        sample_rate=args.sample_rate,
        feature_dim=args.feature_dim,
        decoding_method=decoding_method,
        max_active_paths=max_active_paths,
        provider="cpu",
        enable_endpoint_detection=True,
        rule1_min_trailing_silence=args.rule1,
        rule2_min_trailing_silence=args.rule2,
        rule3_min_utterance_length=args.rule3,
        model_type=args.model_type,
    )


def warmup_stream(recognizer, stream, sr, warmup_ms):
    if warmup_ms <= 0:
        return
    stream.accept_waveform(sr, [0.0] * (sr * warmup_ms // 1000))
    while recognizer.is_ready(stream):
        recognizer.decode_stream(stream)
    recognizer.reset(stream)


def streaming_decode(recognizer, samples, sr, args):
    stream = recognizer.create_stream()
    warmup_stream(recognizer, stream, sr, args.warmup_ms)

    events = []
    last_partial = ""
    chunk_n = sr * args.chunk_ms // 1000
    t_ms = 0

    for off in range(0, len(samples), chunk_n):
        chunk = samples[off:off + chunk_n]
        stream.accept_waveform(sr, chunk)
        while recognizer.is_ready(stream):
            recognizer.decode_stream(stream)
        t_ms += args.chunk_ms

        if recognizer.is_endpoint(stream):
            text = recognizer.get_result(stream)
            events.append((t_ms, "ENDPOINT", ""))
            events.append((t_ms, "FINAL", text))
            recognizer.reset(stream)
            last_partial = ""
            continue

        text = recognizer.get_result(stream)
        if text != last_partial:
            last_partial = text
            events.append((t_ms, "PARTIAL", text))

    stream.input_finished()
    while recognizer.is_ready(stream):
        recognizer.decode_stream(stream)
    events.append((t_ms, "FINAL", recognizer.get_result(stream)))
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--wav", required=True)
    ap.add_argument("--segments", nargs="*", default=[],
                    help="t0:t1:label 列表；省略则跑整段")
    ap.add_argument("--gain", type=float, default=0.0)
    ap.add_argument("--decoders", nargs="*", default=["greedy", "mbs8"],
                    choices=["greedy", "mbs4", "mbs8", "mbs16"])
    ap.add_argument("--chunk-ms", type=int, default=100)
    ap.add_argument("--warmup-ms", type=int, default=800)
    ap.add_argument("--sample-rate", type=int, default=16000)
    ap.add_argument("--feature-dim", type=int, default=80)
    ap.add_argument("--num-threads", type=int, default=2)
    ap.add_argument("--model-type", default="zipformer2")
    ap.add_argument("--rule1", type=float, default=2.4)
    ap.add_argument("--rule2", type=float, default=1.4)
    ap.add_argument("--rule3", type=float, default=20.0)
    args = ap.parse_args()

    samples, sr = load_wav(args.wav)
    print(f"loaded {args.wav}: dur={len(samples)/sr:.2f}s sr={sr}, gain={args.gain}dB")
    print(f"streaming: chunk={args.chunk_ms}ms warmup={args.warmup_ms}ms "
          f"endpoint=({args.rule1}, {args.rule2}, {args.rule3})")

    segs = []
    for s in args.segments:
        t0, t1, label = s.split(":")
        segs.append((float(t0), float(t1), label))
    if not segs:
        segs = [(0.0, len(samples) / sr, "all")]

    decoder_specs = {
        "greedy": ("greedy_search", 1),
        "mbs4": ("modified_beam_search", 4),
        "mbs8": ("modified_beam_search", 8),
        "mbs16": ("modified_beam_search", 16),
    }

    for t0, t1, label in segs:
        print()
        print(f"================ {label}: {t0:.2f}s-{t1:.2f}s ================")
        seg = apply_gain(slice_samples(samples, sr, t0, t1), args.gain)
        for decoder in args.decoders:
            method, max_active_paths = decoder_specs[decoder]
            recognizer = make_recognizer(args.model_dir, method, max_active_paths, args)
            events = streaming_decode(recognizer, seg, sr, args)
            print(f"--- {decoder} ---")
            for t_ms, kind, text in events:
                if kind == "PARTIAL":
                    continue
                if text:
                    print(f"{t_ms:7d}ms  {kind:<8s}  {text}")
                else:
                    print(f"{t_ms:7d}ms  {kind:<8s}")


if __name__ == "__main__":
    main()
