#!/usr/bin/env python3
"""Compare final decoder ONNX with chunk decoder plus zero lookahead context."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort


DEFAULT_MODEL_DIR = (
    Path(__file__).resolve().parent
    / "trial-export"
    / "lits_delivery_16k_hifigan_streaming_proto"
    / "0.1.1"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--speaker-id", type=int, default=0)
    return parser.parse_args()


def metric_dict(left: np.ndarray, right: np.ndarray) -> dict[str, float]:
    diff = (left - right).astype(np.float32)
    return {
        "mean_abs": float(np.mean(np.abs(diff))),
        "max_abs": float(np.max(np.abs(diff))),
        "rms": float(np.sqrt(np.mean(diff * diff))),
    }


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


def main() -> None:
    args = parse_args()
    model_dir = args.model_dir
    manifest = json.loads((model_dir / "manifest.json").read_text(encoding="utf-8"))
    frontend = json.loads((model_dir / "frontend_golden.json").read_text(encoding="utf-8"))
    chunk_size = int(manifest["streaming_chunk_size"])
    lookahead = int(manifest["streaming_pre_lookahead_len"])

    providers = ["CPUExecutionProvider"]
    hidden_session = ort.InferenceSession(str(model_dir / "lits_hidden_encoder.onnx"), providers=providers)
    chunk_session = ort.InferenceSession(str(model_dir / "lits_stream_decoder_chunk.onnx"), providers=providers)
    final_session = ort.InferenceSession(str(model_dir / "lits_stream_decoder_final.onnx"), providers=providers)

    print(f"model_dir={model_dir}")
    print(f"chunk_size={chunk_size} lookahead={lookahead}")
    for case in frontend["cases"]:
        mu_y, y_mask, mel_length, speaker_embedding = run_hidden(
            hidden_session,
            case["token_ids"],
            args.speaker_id,
        )
        pad = mel_length % chunk_size
        upper = mel_length - pad
        slice_ids = list(range(0, upper, chunk_size)) if upper > 0 else [0]
        final_start = slice_ids[-1]
        window_start = max(0, final_start - chunk_size)

        final_mu = mu_y[:, :, window_start:mel_length].astype(np.float32)
        final_mask = y_mask[:, :, window_start:mel_length].astype(np.float32)
        zero_context = np.zeros((final_mu.shape[0], final_mu.shape[1], lookahead), dtype=np.float32)
        padded_mu = np.concatenate([final_mu, zero_context], axis=2)

        final_1 = final_session.run(
            ["mel"],
            {
                "mu_y": final_mu,
                "y_mask": final_mask,
                "speaker_embedding": speaker_embedding,
            },
        )[0].astype(np.float32)
        final_2 = final_session.run(
            ["mel"],
            {
                "mu_y": final_mu,
                "y_mask": final_mask,
                "speaker_embedding": speaker_embedding,
            },
        )[0].astype(np.float32)
        zero_1 = chunk_session.run(
            ["mel"],
            {
                "mu_y": padded_mu,
                "y_mask": final_mask,
                "speaker_embedding": speaker_embedding,
            },
        )[0].astype(np.float32)
        zero_2 = chunk_session.run(
            ["mel"],
            {
                "mu_y": padded_mu,
                "y_mask": final_mask,
                "speaker_embedding": speaker_embedding,
            },
        )[0].astype(np.float32)

        common_frames = min(final_1.shape[2], zero_1.shape[2])
        print()
        print(f"case={case['text']}")
        print(
            "mel_length={} final_start={} window_start={} final_mu={} padded_mu={} mask={}".format(
                mel_length,
                final_start,
                window_start,
                list(final_mu.shape),
                list(padded_mu.shape),
                list(final_mask.shape),
            )
        )
        print(f"final_mel={list(final_1.shape)} zero_mel={list(zero_1.shape)}")
        print(f"final_repeat={metric_dict(final_1[:, :, :common_frames], final_2[:, :, :common_frames])}")
        print(f"zero_repeat={metric_dict(zero_1[:, :, :common_frames], zero_2[:, :, :common_frames])}")
        print(f"final_vs_zero={metric_dict(final_1[:, :, :common_frames], zero_1[:, :, :common_frames])}")


if __name__ == "__main__":
    main()
