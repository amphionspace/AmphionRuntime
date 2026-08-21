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
import json
import struct
import wave
from pathlib import Path


ENDPOINT_REASON_RULE3 = 3


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
    import sherpa_onnx

    joiner = Path(model_dir) / "joiner.int8.onnx"
    if not joiner.is_file():
        joiner = Path(model_dir) / "joiner.onnx"
    return sherpa_onnx.OnlineRecognizer.from_transducer(
        encoder=f"{model_dir}/encoder.int8.onnx",
        decoder=f"{model_dir}/decoder.onnx",
        joiner=str(joiner),
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


def streaming_decode(recognizer, samples, sr, args, transition):
    stream = recognizer.create_stream()
    warmup_stream(recognizer, stream, sr, args.warmup_ms)

    events = []
    committed_tokens = []
    committed_timestamps = []
    last_partial = ""
    chunk_n = sr * args.chunk_ms // 1000
    endpoint_latched = False
    stream_generation = 1
    checkpoint_committed_count = 0
    non_rule3_hard_restart_count = 0
    decode_calls = 0
    segment_start_sample = 0

    def snapshot(kind, sample_offset, decoded_this_chunk, transition_reason):
        result = recognizer.get_result_all(stream)
        endpoint_reason = "native-binding-unavailable"
        endpoint_reason_source = "unavailable-python-binding"
        get_endpoint_reason = getattr(recognizer, "get_endpoint_reason", None)
        if callable(get_endpoint_reason):
            endpoint_reason = get_endpoint_reason(stream)
            endpoint_reason_source = "native"
        timestamps = list(result.timestamps)
        timeline_timestamps = [
            timestamp + segment_start_sample / sr for timestamp in timestamps
        ]
        return {
            "time_ms": round(sample_offset * 1000 / sr),
            "kind": kind,
            "text": result.text.strip(),
            "tokens": list(result.tokens),
            "timestamps": timestamps,
            "timeline_timestamps": timeline_timestamps,
            "sample_offset": sample_offset,
            "segment_start_sample": segment_start_sample,
            "input_frame": sample_offset // max(1, sr // 100),
            "decoder_frame": (
                round(timeline_timestamps[-1] / 0.04)
                if timeline_timestamps else None
            ),
            "decoder_frame_source": "token-timestamp-derived",
            "stream_identity": id(stream),
            "stream_generation": stream_generation,
            "decode_calls": decode_calls,
            "decoded_this_chunk": decoded_this_chunk,
            "endpoint_reason": endpoint_reason,
            "endpoint_reason_source": endpoint_reason_source,
            "transition_reason": transition_reason,
            "result_suppression_reason": (
                "oracle-keeps-decoding"
                if transition == "continuous" and kind == "ENDPOINT"
                else "none"
            ),
        }

    for off in range(0, len(samples), chunk_n):
        chunk = samples[off:off + chunk_n]
        stream.accept_waveform(sr, chunk)
        decoded_this_chunk = 0
        while recognizer.is_ready(stream):
            recognizer.decode_stream(stream)
            decoded_this_chunk += 1
            decode_calls += 1
        sample_offset = off + len(chunk)

        is_endpoint = recognizer.is_endpoint(stream)
        if is_endpoint and not endpoint_latched:
            result = snapshot("ENDPOINT", sample_offset, decoded_this_chunk,
                              f"{transition}-endpoint")
            events.append(result)
            if transition == "continuous":
                endpoint_latched = True
            elif transition == "soft":
                committed_tokens.extend(result["tokens"])
                committed_timestamps.extend(result["timeline_timestamps"])
                recognizer.reset(stream)
                segment_start_sample = sample_offset
            elif transition == "checkpoint":
                committed_tokens.extend(result["tokens"])
                committed_timestamps.extend(result["timeline_timestamps"])
                has_result = bool(result["text"] or result["tokens"])
                if result["endpoint_reason"] == ENDPOINT_REASON_RULE3 and has_result:
                    if not recognizer.commit_rule3_segment(stream):
                        raise RuntimeError("native Rule3 checkpoint was rejected")
                    checkpoint_committed_count += 1
                else:
                    stream = recognizer.create_stream()
                    stream_generation += 1
                    non_rule3_hard_restart_count += 1
                segment_start_sample = sample_offset
            elif transition == "fresh":
                committed_tokens.extend(result["tokens"])
                committed_timestamps.extend(result["timeline_timestamps"])
                stream = recognizer.create_stream()
                stream_generation += 1
                segment_start_sample = sample_offset
            else:
                raise ValueError(f"unsupported endpoint transition: {transition}")
            last_partial = ""
            continue
        if not is_endpoint:
            endpoint_latched = False

        text = recognizer.get_result(stream)
        if text != last_partial:
            last_partial = text
            events.append({
                "time_ms": round(sample_offset * 1000 / sr),
                "kind": "PARTIAL",
                "text": text,
                "sample_offset": sample_offset,
                "stream_generation": stream_generation,
                "decode_calls": decode_calls,
                "decoded_this_chunk": decoded_this_chunk,
            })

    stream.input_finished()
    decoded_at_finish = 0
    while recognizer.is_ready(stream):
        recognizer.decode_stream(stream)
        decoded_at_finish += 1
        decode_calls += 1
    final = snapshot("FINAL", len(samples), decoded_at_finish, "input-finished")
    events.append(final)
    if transition == "continuous":
        committed_tokens = list(final["tokens"])
        committed_timestamps = list(final["timeline_timestamps"])
    else:
        committed_tokens.extend(final["tokens"])
        committed_timestamps.extend(final["timeline_timestamps"])
    return {
        "transition": transition,
        "events": events,
        "committed_tokens": committed_tokens,
        "committed_timestamps": committed_timestamps,
        "checkpoint_committed_count": checkpoint_committed_count,
        "non_rule3_hard_restart_count": non_rule3_hard_restart_count,
    }


def compare_with_continuous(oracle, candidate):
    oracle_tokens = oracle["committed_tokens"]
    candidate_tokens = candidate["committed_tokens"]
    common_length = min(len(oracle_tokens), len(candidate_tokens))
    first_diff = next(
        (i for i in range(common_length)
         if oracle_tokens[i] != candidate_tokens[i]),
        None,
    )
    if first_diff is None and len(oracle_tokens) != len(candidate_tokens):
        first_diff = common_length

    def value_at(values, index):
        return values[index] if index is not None and index < len(values) else None

    oracle_timestamp = value_at(oracle["committed_timestamps"], first_diff)
    candidate_timestamp = value_at(candidate["committed_timestamps"], first_diff)
    timestamp = oracle_timestamp if oracle_timestamp is not None else candidate_timestamp
    return {
        "transition": candidate["transition"],
        "matches_continuous": first_diff is None,
        "endpoint_count": sum(
            event["kind"] == "ENDPOINT" for event in candidate["events"]
        ),
        "checkpoint_committed_count": candidate.get(
            "checkpoint_committed_count", 0
        ),
        "non_rule3_hard_restart_count": candidate.get(
            "non_rule3_hard_restart_count", 0
        ),
        "oracle_token_count": len(oracle_tokens),
        "candidate_token_count": len(candidate_tokens),
        "first_diff_index": first_diff,
        "oracle_token": value_at(oracle_tokens, first_diff),
        "candidate_token": value_at(candidate_tokens, first_diff),
        "oracle_timestamp": oracle_timestamp,
        "candidate_timestamp": candidate_timestamp,
        "decoder_frame": round(timestamp / 0.04) if timestamp is not None else None,
        "decoder_frame_source": "token-timestamp-derived",
    }


def transition_gate_passes(comparisons, expected_rule3_checkpoints=None):
    """Require real native checkpoints and exact checkpoint/oracle token parity."""
    return bool(comparisons) and all(
        comparison["endpoint_count"] > 0
        and (
            comparison["transition"] != "checkpoint"
            or (
                comparison["matches_continuous"]
                and comparison["checkpoint_committed_count"] > 0
                and (
                    expected_rule3_checkpoints is None
                    or (
                        comparison["checkpoint_committed_count"]
                        == expected_rule3_checkpoints
                        and comparison["endpoint_count"]
                        == comparison["checkpoint_committed_count"]
                        and comparison["non_rule3_hard_restart_count"] == 0
                    )
                )
            )
        )
        for comparison in comparisons
    )


def first_nonempty_terminal_after_endpoint(run):
    seen_endpoint = False
    for event in run["events"]:
        if event["kind"] == "ENDPOINT":
            if not seen_endpoint:
                seen_endpoint = True
                continue
            if event.get("text", ""):
                return event["text"]
        elif seen_endpoint and event["kind"] == "FINAL" and event.get("text", ""):
            return event["text"]
    return ""


def boundary_prefix_matches(run, expected_prefix):
    return first_nonempty_terminal_after_endpoint(run).startswith(expected_prefix)


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
    ap.add_argument(
        "--endpoint-transition",
        choices=["continuous", "soft", "fresh", "checkpoint"],
        default="soft",
        help="endpoint 后保持原 stream、soft reset、native checkpoint，或创建 fresh stream",
    )
    ap.add_argument(
        "--compare-transitions",
        action="store_true",
        help="用相同 PCM/参数依次运行 continuous、soft、fresh、checkpoint 并报告首个 token 分叉",
    )
    ap.add_argument(
        "--require-checkpoint-oracle-match",
        action="store_true",
        help="checkpoint 分段 token 与 continuous oracle 不一致时返回失败",
    )
    ap.add_argument(
        "--expected-rule3-checkpoints",
        type=int,
        help="要求每个 decoder/segment 实际成功提交指定次数的 native Rule3 checkpoint",
    )
    ap.add_argument(
        "--expected-after-first-endpoint-prefix",
        help="要求 checkpoint 后第一条非空 endpoint/final 以该文本开头",
    )
    ap.add_argument(
        "--show-token-timestamps",
        action="store_true",
        help="为 endpoint/final 输出 native token 与 timestamp",
    )
    ap.add_argument("--json-output", help="将完整事件写入 JSON 文件")
    args = ap.parse_args()
    if args.require_checkpoint_oracle_match and not args.compare_transitions:
        ap.error("--require-checkpoint-oracle-match requires --compare-transitions")
    if args.expected_rule3_checkpoints is not None:
        if not args.compare_transitions:
            ap.error("--expected-rule3-checkpoints requires --compare-transitions")
        if args.expected_rule3_checkpoints <= 0:
            ap.error("--expected-rule3-checkpoints must be positive")
    if (
        args.expected_after_first_endpoint_prefix
        and not args.compare_transitions
        and args.endpoint_transition != "checkpoint"
    ):
        ap.error(
            "--expected-after-first-endpoint-prefix requires "
            "--endpoint-transition checkpoint or --compare-transitions"
        )

    samples, sr = load_wav(args.wav)
    print(f"loaded {args.wav}: dur={len(samples)/sr:.2f}s sr={sr}, gain={args.gain}dB")
    transition_label = (
        "continuous/soft/fresh/checkpoint"
        if args.compare_transitions else args.endpoint_transition
    )
    print(f"streaming: chunk={args.chunk_ms}ms warmup={args.warmup_ms}ms "
          f"endpoint=({args.rule1}, {args.rule2}, {args.rule3}) "
          f"transition={transition_label}")

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

    runs = []
    comparisons = []
    boundary_gate_failed = False
    for t0, t1, label in segs:
        print()
        print(f"================ {label}: {t0:.2f}s-{t1:.2f}s ================")
        seg = apply_gain(slice_samples(samples, sr, t0, t1), args.gain)
        for decoder in args.decoders:
            method, max_active_paths = decoder_specs[decoder]
            transitions = (["continuous", "soft", "fresh", "checkpoint"]
                           if args.compare_transitions
                           else [args.endpoint_transition])
            decoder_runs = {}
            for transition in transitions:
                recognizer = make_recognizer(
                    args.model_dir, method, max_active_paths, args
                )
                run = streaming_decode(recognizer, seg, sr, args, transition)
                run.update({"label": label, "decoder": decoder})
                runs.append(run)
                decoder_runs[transition] = run
                print(f"--- {decoder} / {transition} ---")
                for event in run["events"]:
                    t_ms = event["time_ms"]
                    kind = event["kind"]
                    text = event.get("text", "")
                    if kind == "PARTIAL":
                        continue
                    if text:
                        print(f"{t_ms:7d}ms  {kind:<8s}  {text}")
                    else:
                        print(f"{t_ms:7d}ms  {kind:<8s}")
                    if args.show_token_timestamps:
                        print(f"             tokens={event.get('tokens', [])}")
                        print(f"             timestamps={event.get('timestamps', [])}")
                gate_transition = transition == "checkpoint"
                if args.expected_after_first_endpoint_prefix and gate_transition:
                    boundary_text = first_nonempty_terminal_after_endpoint(run)
                    boundary_match = boundary_prefix_matches(
                        run, args.expected_after_first_endpoint_prefix
                    )
                    boundary_gate_failed = boundary_gate_failed or not boundary_match
                    print(
                        f"BOUNDARY {decoder}/{transition}: match={boundary_match} "
                        f"expected_prefix={args.expected_after_first_endpoint_prefix!r} "
                        f"actual={boundary_text!r}"
                    )

            if args.compare_transitions:
                for transition in ("soft", "fresh", "checkpoint"):
                    comparison = compare_with_continuous(
                        decoder_runs["continuous"], decoder_runs[transition]
                    )
                    comparison.update({"label": label, "decoder": decoder})
                    comparisons.append(comparison)
                    print(
                        f"COMPARE {decoder}/{transition}: "
                        f"match={comparison['matches_continuous']} "
                        f"endpoints={comparison['endpoint_count']} "
                        f"checkpoints={comparison['checkpoint_committed_count']} "
                        f"tokens={comparison['candidate_token_count']}/"
                        f"{comparison['oracle_token_count']} "
                        f"first_diff={comparison['first_diff_index']} "
                        f"decoder_frame={comparison['decoder_frame']} "
                        f"oracle={comparison['oracle_token']!r} "
                        f"candidate={comparison['candidate_token']!r}"
                    )

    if args.json_output:
        with open(args.json_output, "w", encoding="utf-8") as f:
            json.dump(
                {"runs": runs, "comparisons": comparisons},
                f,
                ensure_ascii=False,
                indent=2,
            )
    checkpoint_gate_requested = (
        args.require_checkpoint_oracle_match
        or args.expected_rule3_checkpoints is not None
    )
    if checkpoint_gate_requested and not transition_gate_passes(
        comparisons, args.expected_rule3_checkpoints
    ):
        raise SystemExit(2)
    if args.expected_after_first_endpoint_prefix and boundary_gate_failed:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
