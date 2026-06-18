#!/usr/bin/env python3
"""Verify the local 16 kHz Lits_delivery ONNX package."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import onnx


EXPECTED_CONSTANTS = {
    "manifest_version": 1,
    "task": "tts",
    "model_type": "multilingual_lits",
    "sample_rate": 16000,
    "mel_bins": 80,
    "hop_length": 256,
    "runtime_format": "onnx",
    "vocoder_type": "hifigan",
}
EXPECTED_FILES = {
    "smoke_tokens.json",
    "frontend_golden.json",
    "chinese_lexicon.txt",
    "cmudict.txt",
    "pinyin_2_bpmf.txt",
    "polychar.txt",
    "zh_en_symbols.json",
    "pinyin_to_tokens.json",
    "arpabet_to_tokens.json",
    "lits_acoustic.onnx",
    "hifigan_vocoder.onnx",
}

OPTIONAL_DOCUMENTATION_FILES = {
    "onnx_smoke_hello_world.wav",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tensor_names(value_infos) -> list[str]:
    return [value.name for value in value_infos]


def check_onnx(path: Path, expected_inputs: set[str], expected_outputs: set[str]) -> None:
    model = onnx.load(str(path))
    onnx.checker.check_model(model)
    inputs = set(tensor_names(model.graph.input))
    outputs = set(tensor_names(model.graph.output))
    missing_inputs = expected_inputs - inputs
    missing_outputs = expected_outputs - outputs
    if missing_inputs or missing_outputs:
        raise AssertionError(
            f"{path.name} signature mismatch: inputs={sorted(inputs)} outputs={sorted(outputs)} "
            f"missing_inputs={sorted(missing_inputs)} missing_outputs={sorted(missing_outputs)}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    return parser.parse_args()


def assert_json_map(path: Path, key: str) -> None:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload.get(key), dict) or not payload[key]:
        raise AssertionError(f"{path.name} missing non-empty object field: {key}")


def main() -> int:
    args = parse_args()
    model_dir = args.model_dir.resolve()
    manifest_path = model_dir / "manifest.json"
    report_path = model_dir / "export_report.json"
    smoke_tokens_path = model_dir / "smoke_tokens.json"

    if not model_dir.is_dir():
        raise FileNotFoundError(f"model dir not found: {model_dir}")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")
    if not report_path.is_file():
        raise FileNotFoundError(f"report not found: {report_path}")
    if not smoke_tokens_path.is_file():
        raise FileNotFoundError(f"smoke_tokens.json not found: {smoke_tokens_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    for key, value in EXPECTED_CONSTANTS.items():
        if manifest.get(key) != value:
            raise AssertionError(f"manifest {key} mismatch: {manifest.get(key)!r} != {value!r}")

    if manifest.get("supported_languages") != ["zh-en", "en-US"]:
        raise AssertionError("supported_languages mismatch")
    if manifest.get("default_language") != "zh-en":
        raise AssertionError("default_language mismatch")
    if manifest.get("default_speaker_id") not in range(manifest.get("speaker_count", 0)):
        raise AssertionError("default_speaker_id out of range")

    names = {entry["name"]: entry for entry in manifest["files"]}
    missing_manifest_files = EXPECTED_FILES - set(names)
    if missing_manifest_files:
        raise AssertionError(f"manifest files missing: {sorted(missing_manifest_files)}")

    for entry in manifest["files"]:
        path = model_dir / entry["name"]
        if entry["name"] in OPTIONAL_DOCUMENTATION_FILES and not path.is_file():
            continue
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.stat().st_size != entry["size_bytes"]:
            raise AssertionError(f"size mismatch for {entry['name']}")
        if sha256(path).lower() != entry["sha256"].lower():
            raise AssertionError(f"sha256 mismatch for {entry['name']}")

    acoustic_file = manifest["acoustic_model"]["file"]
    vocoder_file = manifest["vocoder_model"]["file"]
    if names[acoustic_file]["role"] != "acoustic_model":
        raise AssertionError("acoustic_model.file role mismatch")
    if names[vocoder_file]["role"] != "vocoder_model":
        raise AssertionError("vocoder_model.file role mismatch")

    check_onnx(model_dir / acoustic_file, {"token_ids", "token_lengths", "speaker_id"}, {"mel"})
    check_onnx(model_dir / vocoder_file, {"mel"}, {"waveform"})

    smoke_tokens = json.loads(smoke_tokens_path.read_text(encoding="utf-8-sig"))
    if smoke_tokens.get("source_mode") != "manual_phonemes":
        raise AssertionError("smoke token source_mode mismatch")
    if not smoke_tokens.get("token_ids"):
        raise AssertionError("smoke token_ids empty")
    if not smoke_tokens.get("interspersed_token_ids"):
        raise AssertionError("smoke interspersed_token_ids empty")

    frontend_golden = json.loads((model_dir / "frontend_golden.json").read_text(encoding="utf-8-sig"))
    if not frontend_golden.get("cases"):
        raise AssertionError("frontend_golden cases empty")
    for case in frontend_golden["cases"]:
        if not case.get("token_ids"):
            raise AssertionError("frontend_golden token_ids empty")
        if case.get("token_length") != len(case["token_ids"]):
            raise AssertionError("frontend_golden token_length mismatch")

    symbols = json.loads((model_dir / "zh_en_symbols.json").read_text(encoding="utf-8-sig"))
    if not isinstance(symbols.get("symbols"), list) or not symbols["symbols"]:
        raise AssertionError("zh_en_symbols symbols empty")

    assert_json_map(model_dir / "pinyin_to_tokens.json", "pinyin_to_tokens")
    assert_json_map(model_dir / "arpabet_to_tokens.json", "arpabet_to_tokens")

    report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    validation = report.get("validation") or {}
    if "acoustic" not in validation or "vocoder" not in validation or "end_to_end" not in validation:
        raise AssertionError("export_report validation fields missing")

    print(f"[OK] verified 16k package: {model_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
