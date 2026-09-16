#!/usr/bin/env python3
"""Export the KV-cache-trained IntMeanFlow decoder for Android streaming."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import torch

import export_intmeanflow_student as common

LOGGER = logging.getLogger(__name__)
MODEL_ID = "dingqiao_intmeanflow_student_0010000_streaming_vocos24k"
CACHE_MODE = "intmeanflow_absolute_kv_v1"


@dataclass(frozen=True)
class CacheLayout:
    counts: tuple[int, ...]
    groups = ("att", "att_offset", "conv", "ds", "us")

    @classmethod
    def from_cache(cls, cache):
        return cls(tuple(len(cache[group]) for group in cls.groups))

    @property
    def names(self):
        return [
            f"cache_{group}_{i}"
            for group, count in zip(self.groups, self.counts)
            for i in range(count)
        ]

    def flatten(self, cache):
        device = cache["att"][0].device
        return tuple(
            (
                torch.as_tensor(value, dtype=torch.float32, device=device)
                .reshape(1)
                .clamp_min(0)
                if group == "att_offset"
                else value
            )
            for group in self.groups
            for value in cache[group]
        )

    def inflate(self, values):
        result = {}
        cursor = 0
        for group, count in zip(self.groups, self.counts):
            result[group] = list(values[cursor : cursor + count])
            if group == "att_offset":
                result[group] = [value.reshape(()) for value in result[group]]
            cursor += count
        return result


class HiddenEncoder(torch.nn.Module):
    """Training uses whole-utterance mu encoding before chunked decoding."""

    def __init__(self, model, mu_streaming=False):
        super().__init__()
        self.model = model
        self.mu_streaming = mu_streaming

    def forward(self, token_ids, token_lengths, speaker_id, length_scale):
        hidden = self.model.get_hidden_mel(
            token_ids,
            token_lengths,
            spks=speaker_id,
            length_scale=length_scale.reshape(()),
        )
        # Stateless full-sequence encoding uses the training attention mask.
        # encode_mu(streaming=True) is a different, stateful inference API.
        encoded = self.model.decoder.encoder(
            hidden["mu_y"], hidden["y_mask"], streaming=self.mu_streaming
        )
        length = hidden["y_max_length"]
        return (
            encoded[:, :, :length],
            hidden["y_mask"][:, :, :length],
            length.reshape(1),
            hidden["spks"],
        )


class EncodedCondition(torch.nn.Module):
    def forward(self, mu_y, y_mask):
        return mu_y * y_mask


class DecoderStep(torch.nn.Module):
    def __init__(self, model, layout, cached):
        super().__init__()
        self.model = model
        self.layout = layout
        self.cached = cached

    def forward(self, x, encoded_mu, y_mask, speaker_embedding, t, dt, *states):
        cache = self.layout.inflate(states) if self.cached else None
        velocity, next_cache = self.model.decoder.estimator.forward_streaming(
            x,
            y_mask,
            encoded_mu,
            (t + dt).reshape(()),
            speaker_embedding,
            step_cache=cache,
            r=t.reshape(()),
        )
        next_x = x + dt.reshape(()) * velocity
        mel = next_x * self.model.mel_std + self.model.mel_mean
        return next_x, mel, *self.layout.flatten(next_cache)


def export_graph(model, inputs, path, input_names, output_names, dynamic_axes):
    common.clear_rotary_cache(model)
    torch.onnx.export(
        model,
        inputs,
        str(path),
        input_names=input_names,
        output_names=output_names,
        dynamic_axes=dynamic_axes,
        opset_version=17,
        dynamo=False,
    )
    onnx.checker.check_model(str(path))


def session(path, threads):
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    return ort.InferenceSession(
        str(path), sess_options=options, providers=["CPUExecutionProvider"]
    )


def export_decoders(model, output, threads):
    mean = torch.randn(1, 100, 100)
    mask = torch.ones(1, 1, 100)
    speaker = model.spk_emb(torch.tensor([0]))
    noise = torch.zeros_like(mean)
    with torch.no_grad():
        _, cache = model.decoder.estimator.forward_streaming(
            noise, mask, mean, torch.tensor(0.5), speaker, r=torch.tensor(0.0)
        )
    layout = CacheLayout.from_cache(cache)
    state = layout.flatten(cache)
    names = ["x", "encoded_mu", "y_mask", "speaker_embedding", "t", "dt"]
    outputs = ["x_next", "mel"] + ["next_" + name for name in layout.names]
    inputs = (noise, mean, mask, speaker, torch.tensor([0.0]), torch.tensor([0.5]))
    axes = {
        name: {2: "frames"} for name in ("x", "encoded_mu", "y_mask", "x_next", "mel")
    }
    for name in layout.names:
        if name.startswith("cache_att_") and not name.startswith("cache_att_offset_"):
            axes[name] = {2: "cached_frames"}
            axes["next_" + name] = {2: "next_cached_frames"}
    for cached, filename in (
        (False, "lits_stream_decoder_cache_init.onnx"),
        (True, "lits_stream_decoder_cache_step.onnx"),
    ):
        LOGGER.info("Exporting %s", filename)
        selected_axes = {
            key: value
            for key, value in axes.items()
            if cached or not key.startswith("cache_")
        }
        export_graph(
            DecoderStep(model, layout, cached).eval(),
            inputs + (state if cached else ()),
            output / filename,
            names + (layout.names if cached else []),
            outputs,
            selected_axes,
        )
    return (
        layout,
        session(output / "lits_stream_decoder_cache_init.onnx", threads),
        session(output / "lits_stream_decoder_cache_step.onnx", threads),
    )


def compare(actual, expected, label):
    if actual.shape != expected.shape or not np.isfinite(actual).all():
        raise ValueError(f"Invalid output shape or values: {label}")
    error = np.abs(actual - expected)
    if error.max() > 0.001:
        raise ValueError(f"Streaming parity failed: {label}: {error.max()}")
    return float(error.max())


def validate_chunks(
    model, layout, first, following, temperature, chunk_size, lookahead
):
    from meanflow_distill.kv_cache_distill import (
        compute_chunk_starts,
        student_trajectory_kv_cache,
    )

    reports = []
    generator = torch.Generator().manual_seed(20260915)
    for frames in sorted(
        {
            16,
            chunk_size - 1,
            chunk_size,
            chunk_size + 1,
            2 * chunk_size - 1,
            2 * chunk_size,
            2 * chunk_size + 1,
            350,
            431,
        }
    ):
        mean = torch.randn(1, 100, frames, generator=generator)
        mask = torch.ones(1, 1, frames)
        speaker = model.spk_emb(torch.tensor([frames % 2]))
        noise = torch.randn(mean.shape, generator=generator) * temperature
        with torch.no_grad():
            reference, _ = student_trajectory_kv_cache(
                model,
                mean,
                mask,
                speaker,
                noise,
                common.SUPPORTED_GRID,
                chunk_size=chunk_size,
                pre_lookahead_len=lookahead,
            )
        states = [None, None]
        result = []
        starts = compute_chunk_starts(frames, chunk_size)
        for index, start in enumerate(starts):
            end = frames if index == len(starts) - 1 else start + chunk_size
            x = noise[:, :, start:end].numpy()
            for step in range(2):
                feed = {
                    "x": x,
                    "encoded_mu": mean[:, :, start:end].numpy(),
                    "y_mask": mask[:, :, start:end].numpy(),
                    "speaker_embedding": speaker.detach().numpy(),
                    "t": np.array([step * 0.5], np.float32),
                    "dt": np.array([0.5], np.float32),
                }
                if states[step] is not None:
                    feed.update(zip(layout.names, states[step]))
                values = (first if states[step] is None else following).run(None, feed)
                x, mel, *states[step] = values
            result.append(mel)
        actual = np.concatenate(result, axis=2)
        expected = (reference[-1] * model.mel_std + model.mel_mean).detach().numpy()
        error = compare(actual, expected, f"frames={frames}")
        reports.append({"frames": frames, "chunks": len(starts), "max_abs": error})
        LOGGER.info(
            "Validated %d frames / %d chunks: max error %.3g",
            frames,
            len(starts),
            error,
        )
    return reports


def main():
    args = common.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    model_type, estimator_type, training_symbols, split_body, text_to_sequence = (
        common.load_training_api(args.distill_source)
    )
    symbols, _ = common.validate_frontend(
        args.frontend_assets, training_symbols, split_body
    )
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    config = checkpoint["distill_args"]
    matched = config.get("teacher_matched_streaming", False)
    mu_streaming = bool(config.get("mu_streaming", False))
    chunk_size = int(config["distill_chunk_size"])
    left_frames = int(config["decoder_left_frames"])
    lookahead = int(config["pre_lookahead_len"])
    if matched:
        if config.get("kv_cache_distill") or not mu_streaming:
            raise ValueError(
                "Expected teacher-matched training without KV-cache distillation"
            )
        expected_chunk = 50
    else:
        if not config.get("kv_cache_distill") or mu_streaming:
            raise ValueError(
                "Expected KV-cache distillation with whole-utterance mu encoding"
            )
        expected_chunk = 100
    if (chunk_size, left_frames, lookahead) != (expected_chunk, 20, 3):
        raise ValueError(f"Expected chunk={expected_chunk}, left=20, lookahead=3")
    model_id = (
        "dingqiao_intmeanflow_student_0010000_streaming_matched50_vocos24k"
        if matched
        else MODEL_ID
    )
    torch.set_num_threads(args.threads)
    model = common.load_student(checkpoint, model_type, estimator_type, streaming=True)
    from meanflow_distill.kv_cache_distill import configure_decoder_streaming_context

    configure_decoder_streaming_context(
        model, decoder_left_frames=left_frames, static_chunk_size=chunk_size
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".stream-export-", dir=args.output.parent
    ) as temporary:
        output = Path(temporary) / "bundle"
        output.mkdir()
        common.copy_resources(args.frontend_assets, args.vocos, output)
        hidden = HiddenEncoder(model, mu_streaming=mu_streaming).eval()
        inputs = common.encode_example("ni3 hao3 shi4 jie4 .", 1, text_to_sequence) + (
            torch.tensor([1.0]),
        )
        export_graph(
            hidden,
            inputs,
            output / "lits_hidden_encoder.onnx",
            ["token_ids", "token_lengths", "speaker_id", "length_scale"],
            ["mu_y", "y_mask", "mel_length", "speaker_embedding"],
            {
                "token_ids": {1: "tokens"},
                "mu_y": {2: "frames"},
                "y_mask": {2: "frames"},
            },
        )
        hidden_session = session(output / "lits_hidden_encoder.onnx", args.threads)
        hidden_reports = []
        for text, speaker_id in common.VALIDATION_CASES:
            example = common.encode_example(text, speaker_id, text_to_sequence) + (
                torch.tensor([1.0]),
            )
            feed = dict(
                zip(
                    ["token_ids", "token_lengths", "speaker_id", "length_scale"],
                    [x.numpy() for x in example],
                )
            )
            actual = hidden_session.run(None, feed)
            with torch.no_grad():
                expected = hidden(*example)
            errors = [
                compare(a, e.detach().numpy(), text) for a, e in zip(actual, expected)
            ]
            hidden_reports.append({"text": text, "max_abs": max(errors)})
        export_graph(
            EncodedCondition(),
            (torch.zeros(1, 100, 100), torch.ones(1, 1, 100)),
            output / "lits_stream_condition_chunk.onnx",
            ["mu_y", "y_mask"],
            ["encoded_mu"],
            {
                "mu_y": {2: "frames"},
                "y_mask": {2: "frames"},
                "encoded_mu": {2: "frames"},
            },
        )
        layout, first, following = export_decoders(model, output, args.threads)
        reports = validate_chunks(
            model, layout, first, following, args.temperature, chunk_size, lookahead
        )
        manifest = common.read_json(args.frontend_assets / "manifest.json")
        for key in list(manifest):
            if key.startswith("stream") or key in (
                "acoustic_model",
                "hidden_encoder_model",
                "files",
            ):
                del manifest[key]
        manifest.update(
            model_id=model_id,
            model_type="lits_intmeanflow_streaming",
            supports_streaming=True,
            frontend_paradigm="rhyme_body_tone_173",
            prepend_sil=True,
            hidden_encoder_model={"file": "lits_hidden_encoder.onnx", "format": "onnx"},
            vocoder_model={"file": "vocos_vocoder.onnx", "format": "onnx"},
            stream_decoder_external_loop=True,
            stream_decoder_n_timesteps=2,
            stream_decoder_temperature=args.temperature,
            inference_temperature=args.temperature,
            stream_condition_chunk_model={"file": "lits_stream_condition_chunk.onnx"},
            stream_condition_final_model={"file": "lits_stream_condition_chunk.onnx"},
            stream_decoder_step_model={"file": "lits_stream_decoder_cache_init.onnx"},
            streaming_chunk_size=chunk_size,
            streaming_pre_lookahead_len=0,
            streaming_mel_cache_len=8,
            student_t_grid=list(common.SUPPORTED_GRID),
            checkpoint_sha256=common.sha256(args.checkpoint),
            stream_decoder_cache={
                "mode": CACHE_MODE,
                "requires_fixed_chunk_size": chunk_size,
                "state_names": layout.names,
                "state_count": len(layout.names),
                "init_model": {"file": "lits_stream_decoder_cache_init.onnx"},
                "step_model": {"file": "lits_stream_decoder_cache_step.onnx"},
            },
        )
        report = {
            "checkpoint_sha256": common.sha256(args.checkpoint),
            "source_fingerprint_sha256": common.source_fingerprint(args.distill_source),
            "temperature": args.temperature,
            "training_mu_streaming": mu_streaming,
            "teacher_matched_streaming": matched,
            "training_kv_cache_distill": bool(config.get("kv_cache_distill")),
            "inference_path": "causal_kv",
            "chunk_size": chunk_size,
            "training_pre_lookahead_len": lookahead,
            "decoder_left_frames": left_frames,
            "hidden_validation": hidden_reports,
            "chunk_validation": reports,
        }
        common.write_json(output / "export_report.json", report)
        cases = []
        for index, (text, speaker_id) in enumerate(common.VALIDATION_CASES):
            ids = common.encode_example(text, speaker_id, text_to_sequence)[0].tolist()[
                0
            ]
            cases.append(
                {
                    "label": f"training_oracle_{index + 1}",
                    "text": text,
                    "cleaned_text": " ".join(symbols[token] for token in ids),
                    "token_ids": ids,
                    "token_length": len(ids),
                }
            )
        common.write_json(
            output / "frontend_golden.json",
            {
                "scope": "Training phonetic-cleaner oracle; not full raw-text coverage.",
                "vocabulary": 173,
                "cases": cases,
            },
        )
        manifest.pop("num_decoding_left_chunks", None)
        manifest["notes"] = (
            f"IntMeanFlow cached decoder; condition streaming mask={mu_streaming}; "
            f"{chunk_size}-frame chunks and 20-frame KV history."
        )
        manifest["files"] = [
            {"name": p.relative_to(output).as_posix(), "size_bytes": p.stat().st_size}
            for p in sorted(output.rglob("*"))
            if p.is_file()
        ]
        common.write_json(output / "manifest.json", manifest)
        output.rename(args.output)
    LOGGER.info("Verified streaming bundle: %s", args.output)


if __name__ == "__main__":
    main()
