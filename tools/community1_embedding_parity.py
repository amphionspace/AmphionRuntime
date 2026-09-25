#!/usr/bin/env python3
"""Compare Community-1 ONNX embeddings with saved pyannote outputs."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import kaldi_native_fbank as knf
import numpy as np
import onnxruntime as ort
import soundfile as sf


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WAV = ROOT / "dingqiao" / "meeting-offline-noroler4.wav"
DEFAULT_MODEL = ROOT / "shared" / "models" / "asr" / "dingqiao" / "community1-wespeaker.onnx"
DEFAULT_REFERENCE = ROOT / "dingqiao" / "python-community-first-intermediates.npz"
SAMPLE_RATE = 16_000
CHUNK_SAMPLES = 10 * SAMPLE_RATE
LOCAL_SPEAKERS = 3


@dataclass(frozen=True)
class Candidate:
    name: str
    scale: float
    snip_edges: bool
    window_type: str
    high_freq: float


CANDIDATES = (
    Candidate("community", 32768.0, True, "hamming", 0.0),
    Candidate("community-unscaled", 1.0, True, "hamming", 0.0),
    Candidate("sherpa-old", 1.0, False, "povey", -400.0),
    Candidate("sherpa-old-scaled", 32768.0, False, "povey", -400.0),
)


def load_chunk(path: Path, chunk: int) -> np.ndarray:
    audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    if sample_rate != SAMPLE_RATE:
        raise ValueError(f"expected {SAMPLE_RATE} Hz audio, got {sample_rate}")
    audio = np.mean(audio, axis=1, dtype=np.float32)
    begin = chunk * SAMPLE_RATE
    end = begin + CHUNK_SAMPLES
    if end > len(audio):
        audio = np.pad(audio, (0, end - len(audio)))
    return np.ascontiguousarray(audio[begin:end], dtype=np.float32)


def fbank(samples: np.ndarray, candidate: Candidate) -> np.ndarray:
    opts = knf.FbankOptions()
    opts.frame_opts.samp_freq = SAMPLE_RATE
    opts.frame_opts.frame_shift_ms = 10.0
    opts.frame_opts.frame_length_ms = 25.0
    opts.frame_opts.dither = 0.0
    opts.frame_opts.remove_dc_offset = True
    opts.frame_opts.preemph_coeff = 0.97
    opts.frame_opts.window_type = candidate.window_type
    opts.frame_opts.round_to_power_of_two = True
    opts.frame_opts.snip_edges = candidate.snip_edges
    opts.mel_opts.num_bins = 80
    opts.mel_opts.low_freq = 20.0
    opts.mel_opts.high_freq = candidate.high_freq
    opts.use_energy = False

    extractor = knf.OnlineFbank(opts)
    extractor.accept_waveform(SAMPLE_RATE, (samples * candidate.scale).tolist())
    extractor.input_finished()
    features = np.asarray(
        [extractor.get_frame(i) for i in range(extractor.num_frames_ready)],
        dtype=np.float32,
    )
    return features - np.mean(features, axis=0, keepdims=True)


def cosine(left: np.ndarray, right: np.ndarray) -> float:
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    return float(np.dot(left, right) / max(denominator, 1e-20))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wav", type=Path, default=DEFAULT_WAV)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--chunk", type=int, default=0)
    args = parser.parse_args()

    saved = np.load(args.reference)
    reference = saved["emb"][args.chunk].astype(np.float32)
    bitmasks = saved["masks"][args.chunk]
    waveform = load_chunk(args.wav, args.chunk)
    session = ort.InferenceSession(str(args.model), providers=["CPUExecutionProvider"])

    print(f"wav={args.wav}")
    print(f"chunk={args.chunk} samples={len(waveform)} mask_frames={len(bitmasks)}")
    for candidate in CANDIDATES:
        features = fbank(waveform, candidate)
        print(f"\n[{candidate.name}] feature_shape={features.shape}")
        for local in range(LOCAL_SPEAKERS):
            # embedding_exclude_overlap=True keeps frames where only this local
            # speaker is active. This is the mask passed by pyannote inference.
            weights = (bitmasks == (1 << local)).astype(np.float32)[None, :]
            actual = session.run(
                None, {"feats": features[None, :, :], "weights": weights}
            )[0][0]
            expected = reference[local]
            clean = int(np.count_nonzero(weights))
            if not np.isfinite(expected).all():
                print(f"  local={local} clean={clean} reference=NaN")
                continue
            print(
                f"  local={local} clean={clean} cosine={cosine(actual, expected):.9f} "
                f"max_abs={np.max(np.abs(actual - expected)):.9g} "
                f"norm={np.linalg.norm(actual):.9f} "
                f"reference_norm={np.linalg.norm(expected):.9f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
