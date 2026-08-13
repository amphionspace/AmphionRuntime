#!/usr/bin/env python3
"""Reproduce the low-volume ASR failure and verify automatic AGC recovery."""

import argparse
import ctypes
import hashlib
import json
import math
import re
import sys
import wave
from pathlib import Path

RATE = 16000
FRAME_SAMPLES = RATE // 100
FIXTURE_SHA256 = "3b8255aed49b90df4bdbd5ae626f37c94da318a4b2f3bd0c746ef2dbc8a7f8fc"
REFERENCE = "帮我核查身份证号码为三七零五零三幺九幺幺二三零九八三"
EXPECTED_OFF = "当我核查身份证号码为三七零五零三幺九幺幺二三零九八三"


def normalize(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", text).lower()


def read_fixture(path: Path):
    import numpy as np

    if hashlib.sha256(path.read_bytes()).hexdigest() != FIXTURE_SHA256:
        raise RuntimeError(f"fixture hash mismatch: {path}")
    with wave.open(str(path), "rb") as reader:
        if reader.getframerate() != RATE or reader.getnchannels() != 1 or reader.getsampwidth() != 2:
            raise RuntimeError("fixture must be 16 kHz mono PCM16 WAV")
        return np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2").astype(np.float32) / 32768.0


def scale_to_dbfs(samples, target_dbfs: float):
    # Keep validation dependency-free so the evidence contract can run in a clean
    # checkout without installing the evaluator's model/runtime dependencies.
    if len(samples) == 0:
        raise ValueError("cannot scale empty, silent, or non-finite audio")
    sum_squares = 0.0
    for sample in samples:
        value = float(sample)
        if not math.isfinite(value):
            raise ValueError("cannot scale empty, silent, or non-finite audio")
        sum_squares += value * value
    rms = math.sqrt(sum_squares / len(samples))
    if not math.isfinite(rms) or rms <= 0.0:
        raise ValueError("cannot scale empty, silent, or non-finite audio")
    gain = 10.0 ** (target_dbfs / 20.0) / rms
    import numpy as np

    return np.ascontiguousarray(np.asarray(samples, dtype=np.float32) * gain, dtype=np.float32)


def apply_agc(samples, library: Path):
    import numpy as np

    lib = ctypes.CDLL(str(library))
    lib.amphion_agc_create.argtypes = [ctypes.c_int]
    lib.amphion_agc_create.restype = ctypes.c_void_p
    lib.amphion_agc_process.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_float), ctypes.c_size_t]
    lib.amphion_agc_process.restype = ctypes.c_int
    lib.amphion_agc_destroy.argtypes = [ctypes.c_void_p]
    handle = lib.amphion_agc_create(RATE)
    if not handle:
        raise RuntimeError("amphion_agc_create failed")
    output = samples.copy()
    try:
        full_samples = len(output) // FRAME_SAMPLES * FRAME_SAMPLES
        for offset in range(0, full_samples, FRAME_SAMPLES):
            frame = output[offset:offset + FRAME_SAMPLES]
            result = lib.amphion_agc_process(
                handle, frame.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), len(frame))
            if result != 0:
                raise RuntimeError(f"amphion_agc_process failed: {result}")
        if full_samples < len(output):
            valid_samples = len(output) - full_samples
            padded = np.zeros(FRAME_SAMPLES, dtype=np.float32)
            padded[:valid_samples] = output[full_samples:]
            result = lib.amphion_agc_process(
                handle, padded.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), len(padded))
            if result != 0:
                raise RuntimeError(f"amphion_agc_process failed while flushing: {result}")
            output[full_samples:] = padded[:valid_samples]
    finally:
        lib.amphion_agc_destroy(handle)
    return output


def recognizer(model_dir: Path):
    import sherpa_onnx

    return sherpa_onnx.OnlineRecognizer.from_transducer(
        encoder=str(model_dir / "encoder.int8.onnx"), decoder=str(model_dir / "decoder.onnx"),
        joiner=str(model_dir / "joiner.onnx"), tokens=str(model_dir / "tokens.txt"),
        bpe_vocab=str(model_dir / "bbpe.vocab"), modeling_unit="bbpe", model_type="zipformer2",
        num_threads=2, sample_rate=RATE, feature_dim=80, decoding_method="modified_beam_search",
        max_active_paths=8, provider="cpu", enable_endpoint_detection=False)


def decode(instance, samples) -> str:
    import numpy as np

    stream = instance.create_stream()
    for offset in range(0, len(samples), RATE // 10):
        stream.accept_waveform(RATE, samples[offset:offset + RATE // 10])
        while instance.is_ready(stream):
            instance.decode_stream(stream)
    stream.accept_waveform(RATE, np.zeros(round(RATE * 1.28), dtype=np.float32))
    stream.input_finished()
    while instance.is_ready(stream):
        instance.decode_stream(stream)
    return normalize(instance.get_result(stream))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--agc-lib", type=Path, required=True)
    parser.add_argument("--fixture", type=Path,
                        default=Path("asr/test-fixtures/voiceprint-fallback/001_recognize.wav"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    low = scale_to_dbfs(read_fixture(args.fixture), -80.0)
    instance = recognizer(args.model_dir)
    off = decode(instance, low)
    automatic = decode(instance, apply_agc(low, args.agc_lib))
    result = {
        "fixture_sha256": FIXTURE_SHA256,
        "target_dbfs": -80,
        "reference": REFERENCE,
        "off_hypothesis": off,
        "automatic_agc_hypothesis": automatic,
        "off_reproduces_failure": off == EXPECTED_OFF,
        "automatic_agc_recovers_reference": automatic == REFERENCE,
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if result["off_reproduces_failure"] and result["automatic_agc_recovers_reference"] else 1


if __name__ == "__main__":
    sys.exit(main())
