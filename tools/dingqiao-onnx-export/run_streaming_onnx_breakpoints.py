#!/usr/bin/env python3
"""Run v2 ONNX streaming TTS locally and simulate playback underruns."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxruntime as ort
import soundfile as sf


DEFAULT_MODEL_DIR = (
    Path(__file__).resolve().parent
    / "trial-export"
    / "lits_delivery_16k_hifigan_streaming_proto"
    / "0.1.1-v2-int8-vocoder"
)
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "infer" / "v2_streaming_breakpoints"


@dataclass(frozen=True)
class ChunkSlice:
    start_idx: int
    chunk_size: int
    previous_chunk_size: int


@dataclass(frozen=True)
class PcmQueueEvent:
    index: int
    nominal_ready_ms: float
    enqueue_ms: float
    playback_start_ms: float
    playback_end_ms: float
    duration_ms: float
    queue_depth_after_enqueue: int
    producer_block_ms: float
    underrun_gap_ms: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--case-index", type=int, default=2)
    parser.add_argument("--repeat-case", type=int, default=1)
    parser.add_argument("--speaker-id", type=int, default=0)
    parser.add_argument("--chunk-size", type=int, default=100)
    parser.add_argument("--pcm-queue-capacity", type=int, default=128)
    parser.add_argument(
        "--producer-time-scale",
        type=float,
        default=1.0,
        help="Scale chunk ready times to emulate a slower/faster device. 1.0 uses measured local timing.",
    )
    parser.add_argument("--prefix", default=None)
    parser.add_argument("--trace", action="store_true")
    return parser.parse_args()


def create_session(path: Path, intra_op_threads: int = 2) -> ort.InferenceSession:
    options = ort.SessionOptions()
    options.intra_op_num_threads = intra_op_threads
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])


def build_streaming_chunk_slices(mel_length: int, chunk_size: int) -> list[ChunkSlice]:
    normalized_chunk_size = max(1, int(chunk_size))
    if mel_length <= normalized_chunk_size:
        return [ChunkSlice(start_idx=0, chunk_size=normalized_chunk_size, previous_chunk_size=0)]

    remaining_after_first = mel_length - normalized_chunk_size
    upper = mel_length - (remaining_after_first % normalized_chunk_size)
    slices: list[ChunkSlice] = []
    start_idx = 0
    previous_chunk_size = 0
    while start_idx < upper:
        slices.append(
            ChunkSlice(
                start_idx=start_idx,
                chunk_size=normalized_chunk_size,
                previous_chunk_size=previous_chunk_size,
            )
        )
        previous_chunk_size = normalized_chunk_size
        start_idx += normalized_chunk_size
    return slices or [ChunkSlice(start_idx=0, chunk_size=normalized_chunk_size, previous_chunk_size=0)]


def hamming_window(size: int) -> np.ndarray:
    if size <= 0:
        return np.zeros((0,), dtype=np.float32)
    if size == 1:
        return np.ones((1,), dtype=np.float32)
    return np.hamming(size).astype(np.float32)


def crossfade_leading_in_place(waveform: np.ndarray, previous_tail: np.ndarray, window: np.ndarray) -> None:
    overlap = min(previous_tail.size, waveform.size, window.size // 2)
    if overlap <= 0:
        return
    waveform[:overlap] = (
        waveform[:overlap] * window[:overlap]
        + previous_tail[-overlap:] * window[overlap : overlap + overlap]
    )


def run_hidden(
    session: ort.InferenceSession,
    token_ids: list[int],
    speaker_id: int,
) -> tuple[np.ndarray, np.ndarray, int, np.ndarray]:
    tokens = np.asarray([token_ids], dtype=np.int64)
    token_lengths = np.asarray([tokens.shape[1]], dtype=np.int64)
    speaker = np.asarray([speaker_id], dtype=np.int64)
    mu_y, y_mask, mel_length, speaker_embedding = session.run(
        ["mu_y", "y_mask", "mel_length", "speaker_embedding"],
        {
            "token_ids": tokens,
            "token_lengths": token_lengths,
            "speaker_id": speaker,
        },
    )
    return (
        mu_y.astype(np.float32),
        y_mask.astype(np.float32),
        int(np.ravel(mel_length)[0]),
        speaker_embedding.astype(np.float32),
    )


def run_decoder(
    session: ort.InferenceSession,
    mu_y: np.ndarray,
    y_mask: np.ndarray,
    speaker_embedding: np.ndarray,
) -> np.ndarray:
    return session.run(
        ["mel"],
        {
            "mu_y": mu_y.astype(np.float32),
            "y_mask": y_mask.astype(np.float32),
            "speaker_embedding": speaker_embedding.astype(np.float32),
        },
    )[0].astype(np.float32)


def run_vocoder(session: ort.InferenceSession, mel: np.ndarray) -> np.ndarray:
    waveform = session.run(["waveform"], {"mel": mel.astype(np.float32)})[0].astype(np.float32)
    return np.clip(np.squeeze(waveform), -1.0, 1.0)


def write_wav(path: Path, waveform: np.ndarray, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, np.clip(waveform, -1.0, 1.0), sample_rate, subtype="PCM_16")


def simulate_pcm_queue(
    chunk_records: list[dict[str, object]],
    queue_capacity: int,
    producer_time_scale: float = 1.0,
) -> dict[str, object]:
    """Simulate Android-style producer enqueue and realtime PCM drain."""
    capacity = max(1, int(queue_capacity))
    time_scale = max(0.0, float(producer_time_scale))
    events: list[PcmQueueEvent] = []
    accumulated_block_ms = 0.0
    previous_playback_end_ms: float | None = None
    max_queue_depth = 0
    total_underrun_gap_ms = 0.0

    for record in chunk_records:
        emitted_ms = float(record.get("emitted_ms") or 0.0)
        if emitted_ms <= 0.0:
            continue
        nominal_ready_ms = float(record.get("ready_at_ms") or 0.0) * time_scale
        enqueue_ms = nominal_ready_ms + accumulated_block_ms

        # Queue capacity counts chunks waiting to be taken by the playback drain.
        waiting_starts = [event.playback_start_ms for event in events if event.playback_start_ms > enqueue_ms]
        producer_block_ms = 0.0
        if len(waiting_starts) >= capacity:
            unblock_ms = min(waiting_starts)
            producer_block_ms = max(0.0, unblock_ms - enqueue_ms)
            accumulated_block_ms += producer_block_ms
            enqueue_ms = unblock_ms
            waiting_starts = [start_ms for start_ms in waiting_starts if start_ms > enqueue_ms]

        if previous_playback_end_ms is None:
            playback_start_ms = enqueue_ms
            underrun_gap_ms = 0.0
        else:
            underrun_gap_ms = max(0.0, enqueue_ms - previous_playback_end_ms)
            total_underrun_gap_ms += underrun_gap_ms
            playback_start_ms = max(enqueue_ms, previous_playback_end_ms)

        playback_end_ms = playback_start_ms + emitted_ms
        queue_depth_after_enqueue = len(waiting_starts) + (1 if playback_start_ms > enqueue_ms else 0)
        max_queue_depth = max(max_queue_depth, queue_depth_after_enqueue)
        previous_playback_end_ms = playback_end_ms
        events.append(
            PcmQueueEvent(
                index=int(record["index"]),
                nominal_ready_ms=nominal_ready_ms,
                enqueue_ms=enqueue_ms,
                playback_start_ms=playback_start_ms,
                playback_end_ms=playback_end_ms,
                duration_ms=emitted_ms,
                queue_depth_after_enqueue=queue_depth_after_enqueue,
                producer_block_ms=producer_block_ms,
                underrun_gap_ms=underrun_gap_ms,
            )
        )

    playback_complete_ms = previous_playback_end_ms or 0.0
    return {
        "queue_capacity": capacity,
        "producer_time_scale": time_scale,
        "event_count": len(events),
        "max_queue_depth_chunks": max_queue_depth,
        "producer_block_total_ms": accumulated_block_ms,
        "producer_blocked": accumulated_block_ms > 0.0,
        "playback_complete_ms": playback_complete_ms,
        "total_underrun_gap_ms": total_underrun_gap_ms,
        "underrun_after_first_chunk": total_underrun_gap_ms > 0.0,
        "events": [event.__dict__ for event in events],
    }


def build_underrun_playback_audio(
    chunks: list[np.ndarray],
    queue_simulation: dict[str, object],
    sample_rate: int,
) -> np.ndarray:
    """Render what playback hears: real underrun gaps become silence."""
    event_by_index = {int(event["index"]): event for event in queue_simulation["events"]}
    parts: list[np.ndarray] = []
    for index, chunk in enumerate(chunks):
        event = event_by_index.get(index)
        if event is None:
            continue
        gap_ms = float(event.get("underrun_gap_ms") or 0.0)
        if gap_ms > 0.0:
            silence_samples = round(sample_rate * gap_ms / 1000.0)
            parts.append(np.zeros((silence_samples,), dtype=np.float32))
        parts.append(chunk)
    if not parts:
        return np.zeros((0,), dtype=np.float32)
    return np.concatenate(parts)


def print_streaming_trace(metrics: dict[str, object]) -> None:
    chunks = metrics["chunks"]
    queue = metrics["pcm_queue_simulation"]
    events = {event["index"]: event for event in queue["events"]}
    print("TRACE summary")
    print(
        "  text={!r} chunk_size={} queue_capacity={} mel_length={} chunk_count={}".format(
            metrics["text"],
            metrics["chunk_size"],
            metrics["pcm_queue_capacity"],
            metrics["mel_length"],
            metrics["chunk_count"],
        )
    )
    print(
        "  first_audio_ms={:.3f} total_wall_ms={:.3f} audio_duration_ms={:.3f} rtf={:.4f}".format(
            float(metrics["first_audio_ms"] or 0.0),
            float(metrics["total_wall_ms"]),
            float(metrics["audio_duration_ms"]),
            float(metrics["rtf"] or 0.0),
        )
    )
    print(
        "  queue: producer_time_scale={} max_depth={} producer_block_total_ms={:.3f} underrun_gap_ms={:.3f} playback_complete_ms={:.3f}".format(
            queue["producer_time_scale"],
            queue["max_queue_depth_chunks"],
            float(queue["producer_block_total_ms"]),
            float(queue["total_underrun_gap_ms"]),
            float(queue["playback_complete_ms"]),
        )
    )
    print("TRACE chunks")
    previous_ready_ms: float | None = None
    for chunk in chunks:
        event = events.get(chunk["index"], {})
        ready_ms = float(chunk.get("ready_at_ms") or 0.0)
        producer_gap_ms = 0.0 if previous_ready_ms is None else ready_ms - previous_ready_ms
        previous_ready_ms = ready_ms
        emitted_ms = float(chunk.get("emitted_ms") or 0.0)
        compute_ms = float(chunk["decoder_ms"]) + float(chunk["vocoder_ms"])
        realtime_margin_ms = emitted_ms - producer_gap_ms
        print(
            "  #{index:02d} start={start_idx:>4} final={finalize} "
            "decoder={decoder_ms:>8.3f}ms vocoder={vocoder_ms:>8.3f}ms "
            "compute={compute_ms:>8.3f}ms ready={ready_ms:>8.3f}ms "
            "gap={producer_gap_ms:>8.3f}ms emit={emitted_ms:>8.3f}ms "
            "margin={realtime_margin_ms:>8.3f}ms q_depth={q_depth} "
            "block={block_ms:>7.3f}ms underrun={underrun_ms:>7.3f}ms "
            "play=[{play_start:>8.3f},{play_end:>8.3f}]ms".format(
                index=int(chunk["index"]),
                start_idx=int(chunk["start_idx"]),
                finalize=str(chunk["finalize"]),
                decoder_ms=float(chunk["decoder_ms"]),
                vocoder_ms=float(chunk["vocoder_ms"]),
                compute_ms=compute_ms,
                ready_ms=ready_ms,
                producer_gap_ms=producer_gap_ms,
                emitted_ms=emitted_ms,
                realtime_margin_ms=realtime_margin_ms,
                q_depth=int(event.get("queue_depth_after_enqueue", -1)),
                block_ms=float(event.get("producer_block_ms", 0.0)),
                underrun_ms=float(event.get("underrun_gap_ms", 0.0)),
                play_start=float(event.get("playback_start_ms", 0.0)),
                play_end=float(event.get("playback_end_ms", 0.0)),
            )
        )
        if realtime_margin_ms < 0:
            print("    WARN producer slower than realtime for this chunk gap")
        if float(event.get("underrun_gap_ms", 0.0)) > 0:
            print("    WARN playback underrun before this chunk")
        if float(event.get("producer_block_ms", 0.0)) > 0:
            print("    WARN producer blocked by full PCM queue")


def main() -> None:
    args = parse_args()
    model_dir = args.model_dir
    manifest = json.loads((model_dir / "manifest.json").read_text(encoding="utf-8"))
    frontend = json.loads((model_dir / "frontend_golden.json").read_text(encoding="utf-8"))
    case = frontend["cases"][args.case_index]
    repeat_case = max(1, int(args.repeat_case))
    token_ids = list(case["token_ids"]) * repeat_case
    text = " ".join([case["text"]] * repeat_case)

    sample_rate = int(manifest["sample_rate"])
    hop_length = int(manifest["hop_length"])
    lookahead = int(manifest["streaming_pre_lookahead_len"])
    mel_cache_len = int(manifest["streaming_mel_cache_len"])
    chunk_size = int(args.chunk_size)
    source_cache_len = mel_cache_len * hop_length
    speech_window = hamming_window(source_cache_len * 2)

    hidden_session = create_session(model_dir / manifest["hidden_encoder_model"]["file"])
    chunk_session = create_session(model_dir / manifest["stream_decoder_chunk_model"]["file"])
    vocoder_session = create_session(model_dir / manifest["vocoder_model"]["file"])

    started_at = time.perf_counter()
    hidden_started_at = time.perf_counter()
    mu_y, y_mask, mel_length, speaker_embedding = run_hidden(hidden_session, token_ids, args.speaker_id)
    hidden_ms = (time.perf_counter() - hidden_started_at) * 1000.0

    slices = build_streaming_chunk_slices(mel_length, chunk_size)
    mel_cache: np.ndarray | None = None
    waveform_cache: np.ndarray | None = None
    emitted_chunks: list[np.ndarray] = []
    chunk_records: list[dict[str, object]] = []
    decoder_ms_total = 0.0
    vocoder_ms_total = 0.0
    first_audio_ms: float | None = None

    for index, chunk_slice in enumerate(slices):
        finalize = index == len(slices) - 1
        start_idx = chunk_slice.start_idx
        window_start = max(0, start_idx - chunk_slice.previous_chunk_size)
        window_end = mel_length if finalize else min(mel_length, start_idx + chunk_slice.chunk_size + lookahead)
        window_frames = max(0, window_end - window_start)
        output_frames = window_frames if finalize else max(1, window_frames - lookahead)

        window_mu = mu_y[:, :, window_start:window_end].astype(np.float32)
        if finalize:
            zero_context = np.zeros((window_mu.shape[0], window_mu.shape[1], lookahead), dtype=np.float32)
            window_mu = np.concatenate([window_mu, zero_context], axis=2)
        window_mask = y_mask[:, :, window_start : window_start + output_frames].astype(np.float32)

        decoder_started_at = time.perf_counter()
        mel_window = run_decoder(chunk_session, window_mu, window_mask, speaker_embedding)
        decoder_ms = (time.perf_counter() - decoder_started_at) * 1000.0
        decoder_ms_total += decoder_ms

        mel_chunk = mel_window[:, :, start_idx - window_start :].astype(np.float32)
        if mel_cache is not None:
            mel_chunk = np.concatenate([mel_cache, mel_chunk], axis=2)

        vocoder_started_at = time.perf_counter()
        waveform = run_vocoder(vocoder_session, mel_chunk)
        vocoder_ms = (time.perf_counter() - vocoder_started_at) * 1000.0
        vocoder_ms_total += vocoder_ms

        if waveform_cache is not None:
            crossfade_leading_in_place(waveform, waveform_cache, speech_window)

        emit_samples = waveform.size if finalize else max(0, waveform.size - source_cache_len)
        emitted = waveform[:emit_samples].copy()
        if not finalize:
            mel_cache = mel_chunk[:, :, -mel_cache_len:].astype(np.float32)
            waveform_cache = waveform[-source_cache_len:].copy()
        if emitted.size > 0:
            emitted_chunks.append(emitted)
            if first_audio_ms is None:
                first_audio_ms = (time.perf_counter() - started_at) * 1000.0
        ready_at_ms = (time.perf_counter() - started_at) * 1000.0

        chunk_records.append(
            {
                "index": index,
                "start_idx": start_idx,
                "chunk_size": chunk_slice.chunk_size,
                "previous_chunk_size": chunk_slice.previous_chunk_size,
                "finalize": finalize,
                "window_start": window_start,
                "window_end": window_end,
                "window_frames": window_frames,
                "output_frames": output_frames,
                "decoder_ms": decoder_ms,
                "vocoder_ms": vocoder_ms,
                "mel_chunk_frames_with_cache": int(mel_chunk.shape[2]),
                "emitted_samples": int(emitted.size),
                "emitted_ms": emitted.size * 1000.0 / sample_rate,
                "ready_at_ms": ready_at_ms,
            }
        )

    continuous = np.concatenate(emitted_chunks) if emitted_chunks else np.zeros((0,), dtype=np.float32)
    prefix = args.prefix or f"case{args.case_index}_chunk{chunk_size}"
    output_dir = args.output_dir
    continuous_path = output_dir / f"{prefix}_continuous.wav"
    underrun_path = output_dir / f"{prefix}_underrun_playback.wav"
    metrics_path = output_dir / f"{prefix}_metrics.json"

    total_wall_ms = (time.perf_counter() - started_at) * 1000.0
    audio_duration_ms = continuous.size * 1000.0 / sample_rate if sample_rate > 0 else 0.0
    pcm_queue_simulation = simulate_pcm_queue(
        chunk_records,
        args.pcm_queue_capacity,
        producer_time_scale=args.producer_time_scale,
    )
    underrun_audio = build_underrun_playback_audio(emitted_chunks, pcm_queue_simulation, sample_rate)
    write_wav(continuous_path, continuous, sample_rate)
    write_wav(underrun_path, underrun_audio, sample_rate)
    metrics = {
        "text": text,
        "mode": case.get("mode"),
        "case_index": args.case_index,
        "repeat_case": repeat_case,
        "token_length": len(token_ids),
        "model_dir": str(model_dir),
        "sample_rate": sample_rate,
        "speaker_id": args.speaker_id,
        "chunk_size": chunk_size,
        "first_chunk_size": chunk_size,
        "pcm_queue_capacity": args.pcm_queue_capacity,
        "producer_time_scale": args.producer_time_scale,
        "lookahead": lookahead,
        "mel_cache_len": mel_cache_len,
        "mel_length": mel_length,
        "chunk_count": len(emitted_chunks),
        "hidden_ms": hidden_ms,
        "decoder_ms_total": decoder_ms_total,
        "vocoder_ms_total": vocoder_ms_total,
        "first_audio_ms": first_audio_ms,
        "total_wall_ms": total_wall_ms,
        "audio_duration_ms": audio_duration_ms,
        "rtf": total_wall_ms / audio_duration_ms if audio_duration_ms > 0 else None,
        "continuous_wav": str(continuous_path),
        "underrun_playback_wav": str(underrun_path),
        "underrun_audio_duration_ms": underrun_audio.size * 1000.0 / sample_rate if sample_rate > 0 else 0.0,
        "pcm_queue_simulation": pcm_queue_simulation,
        "chunks": chunk_records,
    }
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.trace:
        print_streaming_trace(metrics)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
