#!/usr/bin/env python3
"""Static-quantize the HiFi-GAN vocoder ONNX and run a small CPU benchmark."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from onnxruntime.quantization import CalibrationDataReader, QuantFormat, QuantType, quantize_static


DEFAULT_MODEL_DIR = (
    Path(__file__).resolve().parents[1]
    / "trial-export"
    / "dingqiao_lits_en_zh_hifigan_streaming_proto"
    / "0.1.0"
)


class MelCalibrationReader(CalibrationDataReader):
    def __init__(self, mels: list[np.ndarray]):
        self._mels = iter(mels)

    def get_next(self) -> dict[str, np.ndarray] | None:
        try:
            return {"mel": next(self._mels)}
        except StopIteration:
            return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--speaker-id", type=int, default=0)
    parser.add_argument("--benchmark-repeats", type=int, default=5)
    parser.add_argument(
        "--op-types",
        nargs="+",
        default=["Conv", "ConvTranspose"],
        help="ONNX op types to quantize.",
    )
    return parser.parse_args()


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


def slice_frame_range(values: np.ndarray, start_frame: int, frame_count: int) -> np.ndarray:
    return values[:, :, start_frame : start_frame + frame_count].astype(np.float32)


def run_decoder(
    session: ort.InferenceSession,
    mu_y: np.ndarray,
    y_mask: np.ndarray,
    speaker_embedding: np.ndarray,
) -> np.ndarray:
    return session.run(
        ["mel"],
        {
            "mu_y": mu_y,
            "y_mask": y_mask,
            "speaker_embedding": speaker_embedding,
        },
    )[0].astype(np.float32)


def collect_vocoder_mels(model_dir: Path, speaker_id: int) -> list[np.ndarray]:
    manifest = json.loads((model_dir / "manifest.json").read_text(encoding="utf-8"))
    frontend = json.loads((model_dir / "frontend_golden.json").read_text(encoding="utf-8"))
    chunk_size = int(manifest["streaming_chunk_size"])
    lookahead = int(manifest["streaming_pre_lookahead_len"])
    mel_cache_len = int(manifest["streaming_mel_cache_len"])

    providers = ["CPUExecutionProvider"]
    hidden_session = ort.InferenceSession(str(model_dir / "lits_hidden_encoder.onnx"), providers=providers)
    chunk_session = ort.InferenceSession(str(model_dir / "lits_stream_decoder_chunk.onnx"), providers=providers)

    mels: list[np.ndarray] = []
    for case in frontend["cases"]:
        mu_y, y_mask, mel_length, speaker_embedding = run_hidden(hidden_session, case["token_ids"], speaker_id)
        pad = mel_length % chunk_size
        upper = mel_length - pad
        slice_ids = list(range(0, upper, chunk_size)) if upper > 0 else [0]
        mel_cache: np.ndarray | None = None
        for start_idx in slice_ids:
            finalize = start_idx == slice_ids[-1]
            window_start = max(0, start_idx - chunk_size)
            window_end = mel_length if finalize else min(mel_length, start_idx + chunk_size + lookahead)
            window_frames = max(0, window_end - window_start)
            output_frames = window_frames if finalize else max(1, window_frames - lookahead)

            window_mu = slice_frame_range(mu_y, window_start, window_frames)
            if finalize:
                zero_context = np.zeros((window_mu.shape[0], window_mu.shape[1], lookahead), dtype=np.float32)
                window_mu = np.concatenate([window_mu, zero_context], axis=2)
            window_mask = slice_frame_range(y_mask, window_start, output_frames)
            mel_window = run_decoder(chunk_session, window_mu, window_mask, speaker_embedding)
            mel_chunk = mel_window[:, :, start_idx - window_start :].astype(np.float32)
            if mel_cache is not None:
                mel_chunk = np.concatenate([mel_cache, mel_chunk], axis=2)
            mels.append(mel_chunk)
            if not finalize:
                mel_cache = mel_chunk[:, :, -mel_cache_len:].astype(np.float32)
    return mels


def benchmark(session: ort.InferenceSession, mels: list[np.ndarray], repeats: int) -> tuple[float, np.ndarray]:
    outputs: list[np.ndarray] = []
    started_at = time.perf_counter()
    for _ in range(repeats):
        for mel in mels:
            outputs.append(session.run(["waveform"], {"mel": mel})[0].astype(np.float32))
    elapsed_ms = (time.perf_counter() - started_at) * 1000.0
    return elapsed_ms / max(1, repeats * len(mels)), outputs[0]


def metric_dict(left: np.ndarray, right: np.ndarray) -> dict[str, float]:
    diff = (left - right).astype(np.float32)
    return {
        "mean_abs": float(np.mean(np.abs(diff))),
        "max_abs": float(np.max(np.abs(diff))),
        "rms": float(np.sqrt(np.mean(diff * diff))),
    }


def main() -> None:
    args = parse_args()
    model_dir = args.model_dir
    original_path = model_dir / "hifigan_vocoder.onnx"
    output_path = args.output or model_dir / "hifigan_vocoder_int8.onnx"

    mels = collect_vocoder_mels(model_dir, args.speaker_id)
    print(f"calibration_mels={len(mels)} shapes={[list(m.shape) for m in mels]}")

    quantize_static(
        model_input=str(original_path),
        model_output=str(output_path),
        calibration_data_reader=MelCalibrationReader(mels),
        quant_format=QuantFormat.QDQ,
        activation_type=QuantType.QUInt8,
        weight_type=QuantType.QInt8,
        per_channel=True,
        op_types_to_quantize=args.op_types,
    )

    providers = ["CPUExecutionProvider"]
    original_session = ort.InferenceSession(str(original_path), providers=providers)
    quantized_session = ort.InferenceSession(str(output_path), providers=providers)

    # Warm up both sessions before measuring.
    original_session.run(["waveform"], {"mel": mels[0]})
    quantized_session.run(["waveform"], {"mel": mels[0]})
    original_ms, original_waveform = benchmark(original_session, mels, args.benchmark_repeats)
    quantized_ms, quantized_waveform = benchmark(quantized_session, mels, args.benchmark_repeats)

    print(f"original={original_path} size={original_path.stat().st_size}")
    print(f"quantized={output_path} size={output_path.stat().st_size}")
    print(f"original_avg_ms={original_ms:.2f}")
    print(f"quantized_avg_ms={quantized_ms:.2f}")
    if original_ms > 0:
        print(f"speedup={original_ms / quantized_ms:.3f}x")
    print(f"waveform_diff={metric_dict(original_waveform, quantized_waveform)}")

    manifest_path = model_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["vocoder_model"]["file"] = output_path.name
    manifest_files = [
        entry
        for entry in manifest["files"]
        if entry.get("name") not in {original_path.name, output_path.name}
    ]
    manifest_files.append({"name": output_path.name, "size_bytes": output_path.stat().st_size})
    manifest["files"] = manifest_files
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report_path = model_dir / "export_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["vocoder_quantization"] = {
        "source": original_path.name,
        "output": output_path.name,
        "format": "static_qdq_int8",
        "activation_type": "QUInt8",
        "weight_type": "QInt8",
        "per_channel": True,
        "op_types": args.op_types,
        "calibration_mels": len(mels),
        "original_size_bytes": original_path.stat().st_size,
        "quantized_size_bytes": output_path.stat().st_size,
        "original_avg_ms": original_ms,
        "quantized_avg_ms": quantized_ms,
        "speedup": original_ms / quantized_ms if quantized_ms > 0 else None,
        "waveform_diff": metric_dict(original_waveform, quantized_waveform),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
