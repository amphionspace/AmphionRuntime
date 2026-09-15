#!/usr/bin/env python3
"""Export and validate a two-step, 173-token IntMeanFlow student bundle.

Requires the matching training source and its compiled monotonic_align extension.
Only load trusted checkpoints: training checkpoints contain Python objects.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import logging
import math
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

import numpy as np
import onnx
import onnxruntime as ort
import torch
from omegaconf import OmegaConf

LOGGER = logging.getLogger(__name__)
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend/rhyme_body_tone_173"
SUPPORTED_GRID = (0.0, 0.5, 1.0)
TONES = frozenset("ˉˊˇˋ˙")
VALIDATION_CASES = (
    ("yi1 .", 1),
    ("er4 .", 1),
    ("ni3 hao3 shi4 jie4 .", 1),
    ("HH AH0 L OW1 _ W ER1 L D .", 0),
)
RESOURCE_FILES = (
    "frontend_rules.json",
    "chinese_lexicon.txt",
    "chinese_lexicon.bin",
    "chinese_surname_lexicon.txt",
    "cmudict.txt",
    "cmudict.bin",
    "supplement_lexicon.json",
    "polyphone_context.txt",
    "polyphone_phrases.txt",
    "pinyin_2_bpmf.txt",
    "polychar.txt",
    "arpabet_to_tokens.json",
    "rules_v2/zh.full.json",
    "rules_v2/en.full.json",
    "rules_v2/zh_pinyin.json",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distill-source", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument(
        "--frontend-assets",
        type=Path,
        required=True,
        help="Legacy frontend bundle used to verify the pinyin conversion",
    )
    parser.add_argument(
        "--vocos",
        type=Path,
        required=True,
        help="Matching, already validated 24 kHz Vocos ONNX",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New output directory; existing directories are not overwritten",
    )
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    if not math.isfinite(args.temperature) or args.temperature < 0:
        parser.error("temperature must be finite and nonnegative")
    if args.threads < 1:
        parser.error("threads must be positive")
    for name in ("distill_source", "frontend_assets"):
        path = getattr(args, name).resolve()
        if not path.is_dir():
            parser.error(f"{name} is not a directory: {path}")
        setattr(args, name, path)
    for name in ("checkpoint", "vocos"):
        path = getattr(args, name).resolve()
        if not path.is_file():
            parser.error(f"{name} is not a file: {path}")
        setattr(args, name, path)
    args.output = args.output.resolve()
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_fingerprint(source: Path) -> str:
    """Identify the supplied source even when it was copied without Git metadata."""
    digest = hashlib.sha256()
    files = sorted(
        path
        for package in ("lits", "meanflow_distill")
        for path in (source / package).rglob("*.py")
    )
    for path in files:
        digest.update(path.relative_to(source).as_posix().encode("utf-8") + b"\0")
        digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest()


def load_training_api(source: Path) -> tuple[Any, Any, list[str], Callable, Callable]:
    sys.path.insert(0, str(source))
    try:
        from lits.models.lits import LITS
        from lits.text import text_to_sequence
        from lits.text.bopomofo_utils import split_bpmf_body
        from lits.text.char_symbols.langs.zh_en_rhyme_body_tone_tokens import symbols
        from meanflow_distill.interval_estimator import IntervalConditionedEstimator
    except ModuleNotFoundError as error:
        if error.name == "lits.utils.monotonic_align.core":
            raise RuntimeError(
                "Build the training source's monotonic_align Cython extension first; "
                "see tts/android/docs/STUDENT_10000.md."
            ) from error
        raise
    return (
        LITS,
        IntervalConditionedEstimator,
        list(symbols),
        split_bpmf_body,
        text_to_sequence,
    )


def validate_frontend(
    assets: Path,
    training_symbols: list[str],
    split_body: Callable,
) -> tuple[list[str], dict[str, list[str]]]:
    symbols = read_json(FRONTEND_DIR / "zh_en_symbols.json")["symbols"]
    mapping = read_json(FRONTEND_DIR / "pinyin_to_tokens.json")["pinyin_to_tokens"]
    if len(symbols) != 173 or len(set(symbols)) != 173 or symbols[1] != "<sil>":
        raise ValueError("Invalid committed 173-token inventory")
    if symbols != training_symbols:
        raise ValueError("Training token IDs differ from the committed inventory")
    legacy = read_json(assets / "pinyin_to_tokens.json")["pinyin_to_tokens"]
    converted = {}
    for pinyin, tokens in legacy.items():
        tones = [token for token in tokens if token in TONES]
        if len(tones) != 1:
            raise ValueError(f"Expected one tone for {pinyin}: {tokens}")
        body = "".join(token for token in tokens if token != "_" and token not in TONES)
        initial, rhyme = split_body(body)
        converted[pinyin] = [token for token in (initial, rhyme, tones[0]) if token]
    if mapping != converted:
        raise ValueError("Pinyin mapping differs from the training-source conversion")
    for pinyin, tokens in mapping.items():
        if not tokens or any(token not in symbols for token in tokens):
            raise ValueError(f"Invalid committed pinyin mapping: {pinyin}")
    return symbols, mapping


def load_student(
    checkpoint: dict[str, Any],
    model_type: Any,
    estimator_type: Any,
    *,
    streaming: bool = False,
) -> torch.nn.Module:
    grid = tuple(checkpoint["metadata"]["student_t_grid"])
    if grid != SUPPORTED_GRID:
        raise ValueError(
            f"Only the trained two-step grid {SUPPORTED_GRID} is supported: {grid}"
        )
    if checkpoint["distill_args"]["decoder_streaming"] is not streaming:
        raise ValueError(f"Expected decoder_streaming={streaming} in the checkpoint")
    parameters = inspect.signature(model_type.__init__).parameters
    config = {
        key: value
        for key, value in checkpoint["hyper_parameters"].items()
        if key in parameters
    }
    for key in ("encoder", "decoder", "cfm", "data_statistics"):
        config[key] = OmegaConf.create(config[key])
    # Training-only asset paths are not needed once all checkpoint parameters load.
    for key in config:
        if key.endswith("_path"):
            config[key] = None
    config["optimizer"] = None
    model = model_type(**config)
    model.decoder.estimator = estimator_type(model.decoder.estimator)
    model.load_state_dict(checkpoint["state_dict"], strict=True)
    if (model.n_vocab, model.n_spks, model.n_feats) != (173, 2, 100):
        raise ValueError("Expected 173 tokens, two speakers and 100 mel channels")
    return model.eval().requires_grad_(False)


class AcousticModel(torch.nn.Module):
    """Keep the trained interval solver and expose noise for export validation."""

    def __init__(self, model: torch.nn.Module, temperature: float) -> None:
        super().__init__()
        self.model = model
        self.temperature = temperature

    def condition(self, token_ids, token_lengths, speaker_id):
        hidden = self.model.get_hidden_mel(token_ids, token_lengths, spks=speaker_id)
        mean = self.model.decoder.encode_mu(
            hidden["mu_y"],
            hidden["y_mask"],
            finalize=True,
            streaming=False,
        )
        length = hidden["y_max_length"]
        return mean[:, :, :length], hidden["y_mask"][:, :, :length], hidden["spks"]

    def solve(self, mean, mask, speaker, noise):
        state = noise
        for start, end in zip(SUPPORTED_GRID[:-1], SUPPORTED_GRID[1:]):
            start_time = torch.full((1,), start, dtype=state.dtype, device=state.device)
            end_time = torch.full((1,), end, dtype=state.dtype, device=state.device)
            velocity = self.model.decoder.estimator(
                state,
                mask,
                mean,
                end_time,
                speaker,
                None,
                streaming=False,
                r=start_time,
            )
            state = state + (end - start) * velocity
        return state * self.model.mel_std + self.model.mel_mean

    def forward(self, token_ids, token_lengths, speaker_id):
        mean, mask, speaker = self.condition(token_ids, token_lengths, speaker_id)
        noise = torch.randn_like(mean) * self.temperature
        return self.solve(mean, mask, speaker, noise), noise


def encode_example(
    text: str, speaker: int, text_to_sequence: Callable
) -> tuple[torch.Tensor, ...]:
    ids, _ = text_to_sequence(text, ["pinyin_direct_mixed_rhyme_body_tone_cleaners"])
    return (
        torch.tensor([ids], dtype=torch.long),
        torch.tensor([len(ids)], dtype=torch.long),
        torch.tensor([speaker], dtype=torch.long),
    )


def clear_rotary_cache(model: torch.nn.Module) -> None:
    # Trace dynamic rotary positions instead of freezing a previous input's cache.
    for module in model.modules():
        for name in ("cos_cached", "sin_cached"):
            if hasattr(module, name):
                setattr(module, name, None)


def export_and_validate(
    wrapper: AcousticModel,
    output: Path,
    text_to_sequence: Callable,
    threads: int,
) -> list[dict[str, Any]]:
    example = encode_example("ni3 hao3 .", 1, text_to_sequence)
    clear_rotary_cache(wrapper)
    with torch.inference_mode():
        wrapper(*example)
    clear_rotary_cache(wrapper)
    torch.onnx.export(
        wrapper,
        example,
        str(output),
        input_names=["token_ids", "token_lengths", "speaker_id"],
        output_names=["mel", "initial_noise"],
        dynamic_axes={
            "token_ids": {1: "tokens"},
            "mel": {2: "frames"},
            "initial_noise": {2: "frames"},
        },
        opset_version=17,
        dynamo=False,
    )
    onnx.checker.check_model(str(output))
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(
        str(output), sess_options=options, providers=["CPUExecutionProvider"]
    )
    reports = []
    for text, speaker in VALIDATION_CASES:
        ids, lengths, speaker_id = encode_example(text, speaker, text_to_sequence)
        feeds = {
            "token_ids": ids.numpy(),
            "token_lengths": lengths.numpy(),
            "speaker_id": speaker_id.numpy(),
        }
        mel, noise = session.run(None, feeds)
        with torch.inference_mode():
            mean, mask, embedding = wrapper.condition(ids, lengths, speaker_id)
            expected = wrapper.solve(
                mean, mask, embedding, torch.from_numpy(noise)
            ).numpy()
        if not np.isfinite(mel).all() or not np.isfinite(expected).all():
            raise ValueError(f"Non-finite acoustic output for {text}")
        error = np.abs(mel - expected)
        mean_error, max_error = float(error.mean()), float(error.max())
        if mean_error >= 0.005 or max_error >= 0.1:
            raise ValueError(
                f"ONNX parity failed for {text}: mean={mean_error}, max={max_error}"
            )
        reports.append(
            {
                "text": text,
                "speaker": speaker,
                "tokens": ids.tolist()[0],
                "shape": list(mel.shape),
                "mean_abs": mean_error,
                "max_abs": max_error,
            }
        )
        LOGGER.info(
            "Validated %r: mean error %.3g, max error %.3g", text, mean_error, max_error
        )
    graph = onnx.load(str(output))
    del graph.graph.output[1:]  # Android consumes mel only; noise is validation-only.
    onnx.save(graph, str(output))
    onnx.checker.check_model(str(output))
    return reports


def copy_resources(source: Path, vocos: Path, destination: Path) -> None:
    required = (
        "frontend_rules.json",
        "chinese_lexicon.txt",
        "cmudict.txt",
        "pinyin_2_bpmf.txt",
        "arpabet_to_tokens.json",
        "rules_v2/zh.full.json",
        "rules_v2/en.full.json",
        "rules_v2/zh_pinyin.json",
    )
    missing = [name for name in required if not (source / name).is_file()]
    if missing:
        raise ValueError(f"Missing frontend resources: {', '.join(missing)}")
    for name in RESOURCE_FILES:
        path = source / name
        if path.is_file():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    for name in ("zh_en_symbols.json", "pinyin_to_tokens.json"):
        shutil.copy2(FRONTEND_DIR / name, destination / name)
    shutil.copy2(vocos, destination / "vocos_vocoder.onnx")


def write_metadata(
    output: Path,
    args: argparse.Namespace,
    checkpoint: dict[str, Any],
    symbols: list[str],
    validation: list[dict[str, Any]],
) -> None:
    checkpoint_hash = sha256(args.checkpoint)
    report = {
        "source_fingerprint_sha256": source_fingerprint(args.distill_source),
        "checkpoint_sha256": checkpoint_hash,
        "acoustic_sha256": sha256(output / "lits_acoustic.onnx"),
        "vocos_sha256": sha256(args.vocos),
        "state_dict_strict": True,
        "vocabulary": len(symbols),
        "supports_streaming": False,
        "student_t_grid": list(SUPPORTED_GRID),
        "inference_temperature": args.temperature,
        "training_temperature": float(checkpoint["distill_args"]["temperature"]),
        "validation": validation,
    }
    write_json(output / "export_report.json", report)
    cases = [
        {
            "label": f"training_oracle_{index + 1}",
            "text": row["text"],
            "cleaned_text": " ".join(symbols[token] for token in row["tokens"]),
            "token_ids": row["tokens"],
            "token_length": len(row["tokens"]),
        }
        for index, row in enumerate(validation)
    ]
    write_json(
        output / "frontend_golden.json",
        {
            "scope": "Training phonetic-cleaner oracle; not full Android raw-text coverage.",
            "vocabulary": len(symbols),
            "cases": cases,
        },
    )
    manifest = {
        "manifest_version": 1,
        "task": "tts",
        "model_id": "dingqiao_intmeanflow_student_0010000_vocos24k",
        "version": "0.1.0",
        "model_type": "lits_intmeanflow_utterance",
        "model_lang": "zh-en/en-US",
        "sample_rate": 24000,
        "mel_bins": 100,
        "hop_length": 384,
        "speaker_count": 2,
        "default_speaker_id": 0,
        "supports_streaming": False,
        "default_language": "zh-en",
        "supported_languages": ["zh-en", "en-US"],
        "runtime_format": "onnx",
        "vocoder_type": "vocos",
        "acoustic_model": {"file": "lits_acoustic.onnx", "format": "onnx"},
        "vocoder_model": {"file": "vocos_vocoder.onnx", "format": "onnx"},
        "frontend_paradigm": "rhyme_body_tone_173",
        "prepend_sil": True,
        "student_t_grid": list(SUPPORTED_GRID),
        "inference_temperature": args.temperature,
        "checkpoint_sha256": checkpoint_hash,
        "files": [
            {
                "name": path.relative_to(output).as_posix(),
                "size_bytes": path.stat().st_size,
            }
            for path in sorted(output.rglob("*"))
            if path.is_file()
        ],
    }
    write_json(output / "manifest.json", manifest)


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    model_type, estimator_type, training_symbols, split_body, text_to_sequence = (
        load_training_api(args.distill_source)
    )
    symbols, _ = validate_frontend(args.frontend_assets, training_symbols, split_body)
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    torch.set_num_threads(args.threads)
    model = load_student(checkpoint, model_type, estimator_type)
    wrapper = AcousticModel(model, args.temperature).eval()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # A failed export never leaves a directory that looks like a finished bundle.
    with tempfile.TemporaryDirectory(
        prefix=".student-export-", dir=args.output.parent
    ) as temporary:
        output = Path(temporary) / "bundle"
        output.mkdir()
        copy_resources(args.frontend_assets, args.vocos, output)
        validation = export_and_validate(
            wrapper, output / "lits_acoustic.onnx", text_to_sequence, args.threads
        )
        write_metadata(output, args, checkpoint, symbols, validation)
        output.rename(args.output)
    LOGGER.info("Verified student bundle: %s", args.output)


if __name__ == "__main__":
    main()
