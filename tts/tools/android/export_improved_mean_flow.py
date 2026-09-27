#!/usr/bin/env python3
"""Export native LITs IMF checkpoints to the Android interval/KV runtime.

The estimator comes from the matching training source, never the distillation
wrapper. Validation calls that source's IMF solver with independent step caches.
"""
from __future__ import annotations

import argparse
import inspect
import logging
import math
from pathlib import Path
import sys
import tempfile

import numpy as np
import torch
from omegaconf import OmegaConf

import export_intmeanflow_student as common
import export_intmeanflow_streaming as streaming


def load_model(source, checkpoint):
    sys.path.insert(0, str(source))
    from lits.models.lits import LITS
    from lits.models.components.improved_mean_flow import IMF_Causal
    from lits.text import text_to_sequence
    from lits.text.bopomofo_utils import split_bpmf_body
    from lits.text.char_symbols.langs.zh_en_rhyme_body_tone_tokens import symbols

    data = torch.load(checkpoint, map_location="cpu", weights_only=False)
    config = dict(data["hyper_parameters"])
    if config["cfm"]["name"] != "IMF":
        raise ValueError("Expected a native IMF checkpoint")
    if tuple(config["cfm"]["sampling_time_grid"]) != common.SUPPORTED_GRID:
        raise ValueError("This Android export supports only the two-step 0/.5/1 grid")
    if config["cfm"].get("interval_time_scale") != 1.0:
        raise ValueError("Expected normalized interval time (scale 1)")
    unknown = set(config) - set(inspect.signature(LITS.__init__).parameters)
    if unknown:
        raise ValueError(f"Checkpoint/source configuration mismatch: {unknown}")
    for key in ("encoder", "decoder", "cfm", "data_statistics"):
        config[key] = OmegaConf.create(config[key])
    # These paths construct training MAS bounds, not inference duration bounds.
    # Inference tone duration clamps remain enabled in get_hidden_mel.
    for key in config:
        if key.endswith("_path"):
            config[key] = None
    config["optimizer"] = None
    config["scheduler"] = None
    model = LITS(**config).eval().requires_grad_(False)
    model.load_state_dict(data["state_dict"], strict=True)
    if not isinstance(model.decoder, IMF_Causal):
        raise ValueError("Training source did not construct IMF")
    if (model.n_vocab, model.n_spks, model.n_feats) != (173, 2, 100):
        raise ValueError("Unsupported frontend/speaker/mel geometry")
    decoder = config["decoder"]
    if (decoder.static_chunk_size, decoder.decoder_left_frames, decoder.mu_encoder_left_chunks) != (50, 20, -1):
        raise ValueError("Expected chunk=50, decoder history=20, full prior condition history")
    return model, list(symbols), split_bpmf_body, text_to_sequence, data["global_step"]


def validate_decoder(model, layout, first, following, temperature):
    reports = []
    generator = torch.Generator().manual_seed(20260916)
    for frames in (1, 39, 49, 50, 51, 99, 100, 101, 151, 350, 431):
        mean = torch.randn(1, 100, frames, generator=generator)
        mask = torch.ones(1, 1, frames)
        speaker = model.spk_emb(torch.tensor([frames % 2]))
        noise = torch.randn(mean.shape, generator=generator) * temperature
        # Same partition as Android: merge a short remainder into the last block.
        starts = list(range(0, max(50, frames - frames % 50), 50))
        model.decoder.reset_encoder_cache()
        states = [None, None]
        max_error = 0.0
        for index, start in enumerate(starts):
            end = frames if index == len(starts) - 1 else start + 50
            with torch.no_grad():
                reference = model.decoder.solve_euler(
                    noise[:, :, :end], torch.tensor(common.SUPPORTED_GRID),
                    mean[:, :, :end], mask[:, :, :end], speaker, None,
                    streaming=True, chunk_start=start, use_kv_cache=True,
                )[:, :, start:end]
            x = noise[:, :, start:end].numpy()
            for step in range(2):
                feed = dict(x=x, encoded_mu=mean[:, :, start:end].numpy(),
                            y_mask=mask[:, :, start:end].numpy(),
                            speaker_embedding=speaker.numpy(),
                            t=np.array([step * .5], np.float32), dt=np.array([.5], np.float32))
                if states[step] is not None:
                    feed.update(zip(layout.names, states[step]))
                x, mel, *states[step] = (first if states[step] is None else following).run(None, feed)
            expected = (reference * model.mel_std + model.mel_mean).numpy()
            max_error = max(max_error, streaming.compare(mel, expected, f"{frames}/{start}"))
        reports.append(dict(frames=frames, chunks=len(starts), max_abs=max_error))
        logging.info("IMF solver parity: %s", reports[-1])
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("training-source", "checkpoint", "frontend-assets", "vocos", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    if args.output.exists() or not math.isfinite(args.temperature) or args.temperature < 0 or args.threads < 1:
        parser.error("Output must be new; temperature must be finite/nonnegative and threads positive")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    torch.set_num_threads(args.threads)
    model, symbols, split_body, tokenize, step = load_model(args.training_source.resolve(), args.checkpoint)
    common.validate_frontend(args.frontend_assets, symbols, split_body)
    model_id = f"dingqiao_imf_step{step:08d}_streaming_vocos24k"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".imf-export-", dir=args.output.parent) as directory:
        output = Path(directory) / "bundle"
        output.mkdir()
        common.copy_resources(args.frontend_assets, args.vocos, output)
        hidden = streaming.HiddenEncoder(model, mu_streaming=True).eval()
        inputs = common.encode_example("ni3 hao3 shi4 jie4 .", 1, tokenize) + (torch.tensor([1.0]),)
        names = ["token_ids", "token_lengths", "speaker_id", "length_scale"]
        streaming.export_graph(hidden, inputs, output / "lits_hidden_encoder.onnx", names,
                               ["mu_y", "y_mask", "mel_length", "speaker_embedding"],
                               {"token_ids": {1: "tokens"}, "mu_y": {2: "frames"}, "y_mask": {2: "frames"}})
        hidden_session = streaming.session(output / "lits_hidden_encoder.onnx", args.threads)
        hidden_reports = []
        for text, speaker_id in common.VALIDATION_CASES:
            inputs = common.encode_example(text, speaker_id, tokenize) + (torch.tensor([1.0]),)
            actual = hidden_session.run(None, dict(zip(names, [x.numpy() for x in inputs])))
            with torch.no_grad():
                expected = hidden(*inputs)
            errors = [streaming.compare(a, e.numpy(), text) for a, e in zip(actual, expected)]
            hidden_reports.append(dict(text=text, speaker=speaker_id, max_abs=max(errors)))
        streaming.export_graph(streaming.EncodedCondition(), (torch.zeros(1,100,50), torch.ones(1,1,50)),
                               output / "lits_stream_condition_chunk.onnx", ["mu_y", "y_mask"], ["encoded_mu"],
                               {name: {2: "frames"} for name in ("mu_y", "y_mask", "encoded_mu")})
        layout, first, following = streaming.export_decoders(model, output, args.threads)
        reports = validate_decoder(model, layout, first, following, args.temperature)
        manifest = common.read_json(args.frontend_assets / "manifest.json")
        for key in list(manifest):
            if key.startswith("stream") or key in ("acoustic_model", "hidden_encoder_model", "files", "num_decoding_left_chunks"):
                del manifest[key]
        manifest.update(model_id=model_id, model_type="lits_intmeanflow_streaming", training_objective="improved_mean_flow",
                        supports_streaming=True, default_speaker_id=1, frontend_paradigm="rhyme_body_tone_173", prepend_sil=True,
                        hidden_encoder_model={"file": "lits_hidden_encoder.onnx", "format": "onnx"},
                        vocoder_model={"file": "vocos_vocoder.onnx", "format": "onnx"},
                        stream_decoder_external_loop=True, stream_decoder_n_timesteps=2,
                        stream_decoder_temperature=args.temperature, inference_temperature=args.temperature,
                        stream_condition_chunk_model={"file":"lits_stream_condition_chunk.onnx"},
                        stream_condition_final_model={"file":"lits_stream_condition_chunk.onnx"},
                        stream_decoder_step_model={"file":"lits_stream_decoder_cache_init.onnx"},
                        streaming_chunk_size=50, streaming_pre_lookahead_len=0, streaming_mel_cache_len=8,
                        imf_t_grid=list(common.SUPPORTED_GRID), checkpoint_sha256=common.sha256(args.checkpoint),
                        stream_decoder_cache=dict(mode=streaming.CACHE_MODE, requires_fixed_chunk_size=50,
                                                  state_names=layout.names, state_count=len(layout.names),
                                                  init_model={"file":"lits_stream_decoder_cache_init.onnx"},
                                                  step_model={"file":"lits_stream_decoder_cache_step.onnx"}))
        manifest["notes"] = "Native IMF u-head; two independent step caches, 20-frame history; condition uses training streaming mask."
        cases = []
        for i, (text, speaker) in enumerate(common.VALIDATION_CASES):
            ids = common.encode_example(text, speaker, tokenize)[0][0].tolist()
            cases.append(dict(label=f"imf_{i}", text=text, token_ids=ids,
                              token_length=len(ids), cleaned_text=" ".join(symbols[token] for token in ids)))
        common.write_json(output / "frontend_golden.json", dict(
            scope="Training phonetic-cleaner oracle", vocabulary=173, cases=cases))
        common.write_json(output / "export_report.json", dict(checkpoint_sha256=manifest["checkpoint_sha256"],
                          source_fingerprint_sha256=common.source_fingerprint(args.training_source), global_step=step,
                          objective="improved_mean_flow", interval_time_scale=1, state_dict_strict=True,
                          temperature=args.temperature, chunk_size=50, decoder_left_frames=20,
                          hidden_validation=hidden_reports, chunk_validation=reports,
                          vocos_onnx_sha256=common.sha256(args.vocos)))
        manifest["files"] = [dict(name=p.relative_to(output).as_posix(),size_bytes=p.stat().st_size)
                             for p in sorted(output.rglob("*")) if p.is_file()]
        common.write_json(output / "manifest.json", manifest)
        output.rename(args.output)
    logging.info("Verified IMF bundle: %s", args.output)


if __name__ == "__main__":
    main()
