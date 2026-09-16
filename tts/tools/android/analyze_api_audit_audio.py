#!/usr/bin/env python3
"""Measure duration, gain and voiced F0 in ApiAuditDeviceTest PCM (24 kHz s16le)."""
import argparse
import json
from pathlib import Path

import librosa
import numpy as np

SAMPLE_RATE = 24000
VARIANTS = ("baseline", "slow", "fast", "half-volume", "mute", "pitch-up")


def analyze(root: Path) -> dict:
    rows = {}
    signals = {}
    pitch_tracks = {}
    for name in VARIANTS:
        signal = np.frombuffer((root / f"{name}.pcm").read_bytes(), dtype="<i2")
        signal = signal.astype(np.float64) / 32768
        signals[name] = signal
        rows[name] = {
            "seconds": len(signal) / SAMPLE_RATE,
            "rms": float(np.sqrt(np.mean(signal * signal))),
        }
        if name in ("baseline", "pitch-up"):
            f0, voiced, _ = librosa.pyin(
                signal, sr=SAMPLE_RATE, fmin=65, fmax=450,
                frame_length=2048, hop_length=256,
            )
            pitch_tracks[name] = (f0, voiced)
            rows[name]["median_voiced_f0_hz"] = float(np.nanmedian(f0))

    base_f0, base_voiced = pitch_tracks["baseline"]
    raised_f0, raised_voiced = pitch_tracks["pitch-up"]
    if base_f0.shape != raised_f0.shape:
        raise ValueError("Pitch comparison requires equal output duration")
    common_voiced = base_voiced & raised_voiced
    if not np.any(common_voiced):
        raise ValueError("No common voiced frames for pitch comparison")
    rows["pitch_comparison"] = {
        "voiced_frame_count": int(common_voiced.sum()),
        "median_f0_ratio": float(np.median(raised_f0[common_voiced] / base_f0[common_voiced])),
        "waveform_correlation": float(np.corrcoef(signals["baseline"], signals["pitch-up"])[0, 1]),
    }
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    args = parser.parse_args()
    report = json.dumps(analyze(args.input_dir), indent=2) + "\n"
    (args.input_dir / "audio-analysis.json").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
