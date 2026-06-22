#!/usr/bin/env python3
"""Verify the Transsion LITS Vocos 24 kHz streaming Android package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


MODEL_ID = "transsion_lits_en_zh_vocos24k_streaming_proto"
MODEL_VERSION = "0.1.0"

EXPECTED_CONSTANTS = {
    "manifest_version": 1,
    "task": "tts",
    "model_id": MODEL_ID,
    "version": MODEL_VERSION,
    "model_type": "transsion_multilingual_lits_streaming_proto",
    "sample_rate": 24000,
    "mel_bins": 100,
    "hop_length": 384,
    "runtime_format": "onnx",
    "vocoder_type": "vocos",
    "supports_streaming": True,
    "streaming_chunk_size": 100,
    "streaming_pre_lookahead_len": 3,
    "streaming_mel_cache_len": 8,
    "num_decoding_left_chunks": 1,
}

REQUIRED_FILES = {
    "manifest.json",
    "export_report.json",
    "vocos_vocoder.export_report.json",
    "frontend_golden.json",
    "chinese_lexicon.txt",
    "chinese_lexicon.bin",
    "cmudict.txt",
    "cmudict.bin",
    "pinyin_2_bpmf.txt",
    "polychar.txt",
    "zh_en_symbols.json",
    "pinyin_to_tokens.json",
    "arpabet_to_tokens.json",
    "lits_hidden_encoder.onnx",
    "lits_stream_decoder_chunk.ort",
    "lits_stream_decoder_final.ort",
    "vocos_vocoder.onnx",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    return parser.parse_args()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def assert_json_map(path: Path, key: str) -> None:
    payload = read_json(path)
    if not isinstance(payload.get(key), dict) or not payload[key]:
        raise AssertionError(f"{path.name} missing non-empty object field: {key}")


def main() -> int:
    model_dir = parse_args().model_dir.resolve()
    if not model_dir.is_dir():
        raise FileNotFoundError(f"model dir not found: {model_dir}")

    missing = sorted(name for name in REQUIRED_FILES if not (model_dir / name).is_file())
    if missing:
        raise FileNotFoundError("missing required files: " + ", ".join(missing))

    manifest = read_json(model_dir / "manifest.json")
    for key, expected in EXPECTED_CONSTANTS.items():
        actual = manifest.get(key)
        if actual != expected:
            raise AssertionError(f"manifest {key} mismatch: {actual!r} != {expected!r}")

    if manifest.get("supported_languages") != ["zh-en", "en-US"]:
        raise AssertionError("supported_languages mismatch")
    if manifest.get("default_language") != "zh-en":
        raise AssertionError("default_language mismatch")
    if manifest.get("default_speaker_id") not in range(manifest.get("speaker_count", 0)):
        raise AssertionError("default_speaker_id out of range")

    expected_models = {
        ("hidden_encoder_model", "lits_hidden_encoder.onnx"),
        ("stream_decoder_chunk_model", "lits_stream_decoder_chunk.ort"),
        ("stream_decoder_final_model", "lits_stream_decoder_final.ort"),
        ("vocoder_model", "vocos_vocoder.onnx"),
    }
    for field, filename in expected_models:
        entry = manifest.get(field) or {}
        if entry.get("file") != filename:
            raise AssertionError(f"manifest {field}.file mismatch: {entry.get('file')!r} != {filename!r}")

    manifest_files = {entry.get("name"): entry for entry in manifest.get("files", [])}
    for filename, entry in manifest_files.items():
        if not filename:
            continue
        path = model_dir / filename
        if not path.is_file():
            # Some export-only documentation files are allowed to be absent from
            # the Android handoff package.
            if filename == "onnx_streaming_smoke_hello_world.wav":
                continue
            raise FileNotFoundError(path)
        expected_size = entry.get("size_bytes")
        if expected_size is not None and path.stat().st_size != expected_size:
            raise AssertionError(f"size mismatch for {filename}")

    frontend = read_json(model_dir / "frontend_golden.json")
    if not frontend.get("cases"):
        raise AssertionError("frontend_golden cases empty")
    symbols = read_json(model_dir / "zh_en_symbols.json")
    if not isinstance(symbols.get("symbols"), list) or not symbols["symbols"]:
        raise AssertionError("zh_en_symbols symbols empty")
    assert_json_map(model_dir / "pinyin_to_tokens.json", "pinyin_to_tokens")
    assert_json_map(model_dir / "arpabet_to_tokens.json", "arpabet_to_tokens")

    print(f"[OK] verified Vocos 24k streaming package: {model_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
