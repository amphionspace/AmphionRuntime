#!/usr/bin/env python3
"""Small streaming LITS + HiFi-GAN inference smoke test.

This script is intentionally separate from ``inference_stream.py`` so it can be
used as a focused local test while keeping the production batch CLI unchanged.
It streams the acoustic decoder by mel chunks, vocodes each chunk with HiFi-GAN,
keeps a short mel/audio cache, and cross-fades chunk boundaries.

Defaults point to the retrained Dingqiao checkpoints inside this repository:
``lits-en-zh.ckpt`` and ``hifigan/hifigan.ckpt``.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import traceback
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

from hifigan.env import AttrDict
from hifigan.models import Generator
from lits.models.lits import LITS
from lits.text import text_to_sequence
from lits.utils.utils import intersperse


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_CHECKPOINT = REPO_ROOT / "lits-en-zh.ckpt"
DEFAULT_HIFIGAN_CHECKPOINT = REPO_ROOT / "hifigan" / "hifigan.ckpt"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "infer_output" / "hifigan_stream_test"

MODEL2CLEANER = {
    "en-zh-dict": "en_zh_dict_mixed_cleaners",
    "en-zh": "pinyin_direct_mixed_cleaners",
    "ar-en": "ar_en_mixed_cleaners",
    "bn-en": "bn_en_mixed_cleaners",
    "en-ru": "en_ru_mixed_cleaners",
}
CONTROL_CHARS_PATTERN = re.compile(
    r"[\x00-\x1f\x7f-\x9f"
    r"\u200b-\u200f"
    r"\u202a-\u202e"
    r"\u2066-\u2069"
    r"\ufeff\ufff9-\ufffb]"
)
WHITESPACE_PATTERN = re.compile(r"\s+")
PINYIN_PATTERN = re.compile(r"^[a-z]+[0-5]$")
NON_ENGLISH_SPK_PATTERN = re.compile(
    r"[\u4e00-\u9fff\u0600-\u06ff\u0980-\u09ff\u0400-\u04ff\u0300-\u0301]"
)


@dataclass(frozen=True)
class TestCase:
    name: str
    text: str
    spk_id: int | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=DEFAULT_CHECKPOINT,
        help=f"Retrained LITS checkpoint inside dingqiao_lits. Default: {DEFAULT_CHECKPOINT}",
    )
    parser.add_argument(
        "--hifigan-checkpoint",
        type=Path,
        default=DEFAULT_HIFIGAN_CHECKPOINT,
        help=f"HiFi-GAN checkpoint inside dingqiao_lits. Default: {DEFAULT_HIFIGAN_CHECKPOINT}",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--model-lang",
        choices=sorted(MODEL2CLEANER),
        default="en-zh-dict",
        help="Frontend cleaner/token inventory to use.",
    )
    parser.add_argument(
        "--text",
        action="append",
        default=[],
        help="Text to synthesize. Can be passed multiple times.",
    )
    parser.add_argument(
        "--input-txt",
        type=Path,
        default=None,
        help="Optional list file. Each line can be text, name|text, or name|spk_id|text.",
    )
    parser.add_argument("--spk-id", type=int, default=None, help="Override speaker id for all --text inputs.")
    parser.add_argument("--chunk-size", type=int, default=100, help="Mel frames emitted per streaming step.")
    parser.add_argument("--mel-cache-len", type=int, default=8, help="Mel frames kept for HiFi-GAN overlap.")
    parser.add_argument("--pre-lookahead-len", type=int, default=3, help="Future mel frames supplied to non-final chunks.")
    parser.add_argument(
        "--num-decoding-left-chunks",
        type=int,
        default=1,
        help="-1 uses full history; 0 uses current chunk only; N uses current plus N previous chunks.",
    )
    parser.add_argument("--n-timesteps", type=int, default=10)
    parser.add_argument("--length-scale", type=float, default=1.0)
    parser.add_argument("--temperature", type=float, default=0.667)
    parser.add_argument("--add-blank", action="store_true", help="Match checkpoints trained with blank token insertion.")
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--write-chunks", action="store_true", help="Also save per-chunk wav files for boundary inspection.")
    return parser.parse_args()


def require_file(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    return path


def load_lits(checkpoint_path: Path, device: torch.device, num_decoding_left_chunks: int) -> LITS:
    model = LITS.load_from_checkpoint(str(checkpoint_path), map_location=device, weights_only=False)
    model.eval().to(device)
    if hasattr(model, "decoder") and hasattr(model.decoder, "num_decoding_left_chunks"):
        model.decoder.num_decoding_left_chunks = num_decoding_left_chunks
    return model


def load_hifigan(checkpoint_path: Path, device: torch.device) -> tuple[Generator, AttrDict]:
    config_path = checkpoint_path.parent / "config.json"
    if not config_path.is_file():
        raise FileNotFoundError(f"HiFi-GAN config.json not found next to checkpoint: {config_path}")
    with config_path.open(encoding="utf-8") as handle:
        hparams = AttrDict(json.load(handle))
    generator = Generator(hparams).to(device)
    state = torch.load(str(checkpoint_path), map_location=device, weights_only=False)
    generator.load_state_dict(state["generator"])
    generator.eval()
    generator.remove_weight_norm()
    return generator, hparams


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = CONTROL_CHARS_PATTERN.sub("", text)
    return WHITESPACE_PATTERN.sub(" ", text).strip()


def infer_spk_id(text: str, model_lang: str) -> int:
    if model_lang in ("en-zh", "en-zh-dict"):
        if NON_ENGLISH_SPK_PATTERN.search(text):
            return 1
        for token in text.strip().split():
            if token not in ("_", "/", "|") and PINYIN_PATTERN.match(token):
                return 1
        return 0
    return 1 if NON_ENGLISH_SPK_PATTERN.search(text) else 0


def parse_input_line(line: str, index: int) -> TestCase:
    parts = [part.strip() for part in line.strip().split("|")]
    if len(parts) == 3:
        return TestCase(name=Path(parts[0]).stem or f"case_{index:03d}", spk_id=int(parts[1]), text=parts[2])
    if len(parts) == 2:
        return TestCase(name=Path(parts[0]).stem or f"case_{index:03d}", spk_id=None, text=parts[1])
    return TestCase(name=f"case_{index:03d}", spk_id=None, text=line.strip())


def parse_jsonl_case(line: str, source_path: Path, index: int) -> TestCase:
    payload = json.loads(line)
    if "text" not in payload:
        raise ValueError(f"JSONL line {index + 1} in {source_path} does not contain a `text` field.")
    sample_id = payload.get("id", index + 1)
    name = f"{source_path.stem}_{int(sample_id):03d}" if isinstance(sample_id, int) else f"{source_path.stem}_{sample_id}"
    spk_id = payload.get("spk_id")
    return TestCase(name=name, spk_id=int(spk_id) if spk_id is not None else None, text=str(payload["text"]))


def load_cases(args: argparse.Namespace) -> list[TestCase]:
    cases: list[TestCase] = []
    if args.input_txt:
        with args.input_txt.open(encoding="utf-8") as handle:
            for i, line in enumerate(handle):
                if line.strip():
                    if args.input_txt.suffix == ".jsonl":
                        cases.append(parse_jsonl_case(line, args.input_txt, i))
                    else:
                        cases.append(parse_input_line(line, i))
    for i, text in enumerate(args.text, start=len(cases)):
        cases.append(TestCase(name=f"case_{i:03d}", text=text, spk_id=args.spk_id))
    if not cases:
        cases.append(TestCase(name="hello_world", text="Hello world.", spk_id=args.spk_id))
    return cases


def fade_in_out(fade_in_audio: torch.Tensor, fade_out_audio: torch.Tensor, window: np.ndarray) -> torch.Tensor:
    device = fade_in_audio.device
    fade_in_audio = fade_in_audio.cpu().clone()
    fade_out_audio = fade_out_audio.cpu()
    overlap_len = int(window.shape[0] / 2)
    fade_in_audio[..., :overlap_len] = (
        fade_in_audio[..., :overlap_len] * window[:overlap_len]
        + fade_out_audio[..., -overlap_len:] * window[overlap_len:]
    )
    return fade_in_audio.to(device)


class StreamingHifiganTester:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.cleaner = MODEL2CLEANER[args.model_lang]
        self.model = load_lits(args.checkpoint, self.device, args.num_decoding_left_chunks)
        self.vocoder, self.vocoder_hparams = load_hifigan(args.hifigan_checkpoint, self.device)
        self.sample_rate = int(self.vocoder_hparams.sampling_rate)
        self.hop_size = int(self.vocoder_hparams.hop_size)
        self.vocoder_num_mels = int(self.vocoder_hparams.num_mels)
        if self.model.n_feats < self.vocoder_num_mels:
            raise ValueError(
                f"Mel mismatch: LITS outputs {self.model.n_feats} bins, "
                f"but HiFi-GAN expects {self.vocoder_num_mels}."
            )
        self.mel_trim_bins = self.vocoder_num_mels if self.model.n_feats > self.vocoder_num_mels else None

    def process_text(self, text: str) -> dict[str, torch.Tensor | str]:
        raw_text = normalize_text(text)
        token_ids, cleaned_text = text_to_sequence(raw_text, [self.cleaner])
        if self.args.add_blank:
            token_ids = intersperse(token_ids, 0)
        x = torch.tensor(token_ids, dtype=torch.long, device=self.device)[None]
        if x.numel() == 0:
            raise ValueError("Empty token sequence after tokenization.")
        x_lengths = torch.tensor([x.shape[-1]], dtype=torch.long, device=self.device)
        token_max = int(x.max().item())
        if token_max >= int(getattr(self.model, "n_vocab", 0)):
            raise ValueError(f"Token id {token_max} exceeds model.n_vocab={self.model.n_vocab}.")
        return {"x": x, "x_lengths": x_lengths, "raw_text": raw_text, "cleaned_text": cleaned_text}

    def speaker_tensor(self, spk_id: int | None) -> torch.Tensor | None:
        if getattr(self.model, "n_spks", 1) <= 1:
            return None
        if spk_id is None:
            raise ValueError("This checkpoint is multi-speaker; pass --spk-id or use input lines with spk_id.")
        upper = int(self.model.spk_emb.num_embeddings - 1) if hasattr(self.model, "spk_emb") else int(self.model.n_spks - 1)
        if not (0 <= spk_id <= upper):
            raise ValueError(f"spk_id out of range: {spk_id}, expected [0, {upper}].")
        return torch.tensor([spk_id], dtype=torch.long, device=self.device)

    @torch.inference_mode()
    def to_waveform(self, mel: torch.Tensor) -> torch.Tensor:
        if self.mel_trim_bins is not None:
            mel = mel[:, : self.mel_trim_bins, :]
        audio = self.vocoder(mel).clamp(-1, 1)
        target_len = int(mel.shape[-1] * self.hop_size)
        return audio[..., :target_len].squeeze(0).cpu().squeeze()

    @torch.inference_mode()
    def stream_case(self, case: TestCase) -> dict[str, object]:
        if torch.cuda.is_available():
            torch.cuda.synchronize()
        start_time = time.perf_counter()

        spk_id = case.spk_id
        if spk_id is None:
            spk_id = infer_spk_id(case.text, self.args.model_lang)
        spks = self.speaker_tensor(spk_id)
        text_processed = self.process_text(case.text)

        hidden = self.model.get_hidden_mel(
            text_processed["x"],
            text_processed["x_lengths"],
            spks=spks,
            length_scale=self.args.length_scale,
        )
        y_max_length = int(hidden["y_max_length"].item())
        remainder = y_max_length % self.args.chunk_size
        non_tail_len = y_max_length - remainder
        slice_starts = list(range(0, non_tail_len, self.args.chunk_size))
        if not slice_starts:
            slice_starts = [0]

        global_z = torch.randn(
            1,
            self.model.n_feats,
            y_max_length,
            device=self.device,
        ) * self.args.temperature

        cache: dict[str, torch.Tensor] = {}
        chunk_waveforms: list[torch.Tensor] = []
        chunk_stats: list[dict[str, float | int | bool]] = []
        first_audio_ms: float | None = None

        source_cache_len = int(self.args.mel_cache_len * self.hop_size)
        speech_window = np.hanning(2 * source_cache_len)

        for chunk_index, start_idx in enumerate(slice_starts):
            chunk_start_time = time.perf_counter()
            finalize = chunk_index == len(slice_starts) - 1
            if finalize:
                end_idx = y_max_length
                y_mask = hidden["y_mask"][:, :, :end_idx]
            else:
                end_idx = min(start_idx + self.args.chunk_size + self.args.pre_lookahead_len, y_max_length)
                y_mask = hidden["y_mask"][:, :, : max(start_idx + self.args.chunk_size, 1)]

            encoder_outputs = hidden["mu_y"][:, :, :end_idx]
            mel = self.model.get_mel(
                mu_y=encoder_outputs,
                y_mask=y_mask,
                spks=hidden.get("spks"),
                n_timesteps=self.args.n_timesteps,
                finalize=finalize,
                temperature=self.args.temperature,
                streaming=True,
                z=global_z[:, :, :end_idx],
            )[0, :, start_idx:].unsqueeze(0)

            if cache:
                mel = torch.cat([cache["mel"], mel], dim=2)

            waveform = self.to_waveform(mel).unsqueeze(0)
            if "waveform" in cache:
                waveform = fade_in_out(waveform, cache["waveform"], speech_window)

            if finalize:
                emitted = waveform[0]
            else:
                cache["mel"] = mel[:, :, -self.args.mel_cache_len :]
                cache["waveform"] = waveform[:, -source_cache_len:]
                emitted = waveform[:, :-source_cache_len][0]

            if first_audio_ms is None:
                if torch.cuda.is_available():
                    torch.cuda.synchronize()
                first_audio_ms = (time.perf_counter() - start_time) * 1000

            if torch.cuda.is_available():
                torch.cuda.synchronize()
            chunk_ms = (time.perf_counter() - chunk_start_time) * 1000
            chunk_waveforms.append(emitted.squeeze())
            chunk_stats.append(
                {
                    "index": chunk_index,
                    "start_mel": int(start_idx),
                    "end_mel": int(end_idx),
                    "finalize": finalize,
                    "emitted_samples": int(emitted.numel()),
                    "elapsed_ms": chunk_ms,
                }
            )

        waveform = torch.cat(chunk_waveforms, dim=0)
        total_s = time.perf_counter() - start_time
        return {
            "case": case,
            "raw_text": text_processed["raw_text"],
            "cleaned_text": text_processed["cleaned_text"],
            "spk_id": spk_id,
            "waveform": waveform,
            "chunk_waveforms": chunk_waveforms,
            "chunk_stats": chunk_stats,
            "first_audio_ms": first_audio_ms,
            "total_ms": total_s * 1000,
            "rtf": total_s * self.sample_rate / max(int(waveform.numel()), 1),
            "mel_frames": y_max_length,
        }


def save_result(result: dict[str, object], output_dir: Path, sample_rate: int, write_chunks: bool) -> None:
    case = result["case"]
    assert isinstance(case, TestCase)
    output_dir.mkdir(parents=True, exist_ok=True)
    wav_path = output_dir / f"{case.name}.wav"
    waveform = result["waveform"]
    assert isinstance(waveform, torch.Tensor)
    sf.write(wav_path, waveform.numpy(), sample_rate, "PCM_24")

    if write_chunks:
        chunk_dir = output_dir / f"{case.name}_chunks"
        chunk_dir.mkdir(parents=True, exist_ok=True)
        for i, chunk in enumerate(result["chunk_waveforms"]):
            assert isinstance(chunk, torch.Tensor)
            sf.write(chunk_dir / f"chunk_{i:03d}.wav", chunk.numpy(), sample_rate, "PCM_24")

    metrics_path = output_dir / f"{case.name}.json"
    metrics = {
        "name": case.name,
        "text": result["raw_text"],
        "cleaned_text": result["cleaned_text"],
        "spk_id": result["spk_id"],
        "sample_rate": sample_rate,
        "mel_frames": result["mel_frames"],
        "wav_samples": int(waveform.numel()),
        "audio_sec": int(waveform.numel()) / sample_rate,
        "first_audio_ms": result["first_audio_ms"],
        "total_ms": result["total_ms"],
        "rtf": result["rtf"],
        "chunks": result["chunk_stats"],
    }
    metrics_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    args = parse_args()
    args.checkpoint = require_file(args.checkpoint, "LITS checkpoint")
    args.hifigan_checkpoint = require_file(args.hifigan_checkpoint, "HiFi-GAN checkpoint")
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    tester = StreamingHifiganTester(args)
    cases = load_cases(args)
    print(f"Device: {tester.device}")
    print(f"LITS checkpoint: {args.checkpoint}")
    print(f"HiFi-GAN checkpoint: {args.hifigan_checkpoint}")
    print(
        f"HiFi-GAN: sr={tester.sample_rate}, hop={tester.hop_size}, "
        f"num_mels={tester.vocoder_num_mels}"
    )
    print(f"Cases: {len(cases)}")

    rtfs: list[float] = []
    first_latencies: list[float] = []
    failures = 0
    for i, case in enumerate(cases, start=1):
        try:
            print(f"\n[{i}/{len(cases)}] {case.name}: {case.text}")
            result = tester.stream_case(case)
            save_result(result, args.output_dir, tester.sample_rate, args.write_chunks)
            rtfs.append(float(result["rtf"]))
            first_latencies.append(float(result["first_audio_ms"]))
            print(
                f"  spk={result['spk_id']} mel={result['mel_frames']} "
                f"chunks={len(result['chunk_stats'])} "
                f"first_audio={result['first_audio_ms']:.2f} ms "
                f"total={result['total_ms']:.2f} ms rtf={result['rtf']:.4f}"
            )
            for chunk in result["chunk_stats"]:
                print(
                    "    chunk {index:02d}: mel {start_mel}->{end_mel}, "
                    "samples={emitted_samples}, {elapsed_ms:.2f} ms, final={finalize}".format(**chunk)
                )
        except Exception:
            failures += 1
            print(f"  FAILED: {case.name}")
            traceback.print_exc()

    if rtfs:
        print(
            "\nSummary: "
            f"mean_rtf={np.mean(rtfs):.4f} +/- {np.std(rtfs):.4f}, "
            f"mean_first_audio={np.mean(first_latencies):.2f} ms"
        )
        print(f"Output: {args.output_dir}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
