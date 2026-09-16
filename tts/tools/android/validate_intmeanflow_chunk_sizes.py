#!/usr/bin/env python3
"""Compare an existing streaming ONNX package with its source at new chunk sizes.

This checks numerical correctness of chunk/cache execution, not perceptual quality
or equivalence between different partitions. Training context stays unchanged.
"""
import argparse
import json
import logging
from pathlib import Path

import torch

import export_intmeanflow_streaming as streaming


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--distill-source", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--chunks", type=int, nargs="+", default=[40, 50, 75, 100, 150, 200])
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    torch.set_num_threads(args.threads)
    model_type, estimator_type, *_ = streaming.common.load_training_api(args.distill_source.resolve())
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    config = checkpoint["distill_args"]
    model = streaming.common.load_student(checkpoint, model_type, estimator_type, streaming=True)
    from meanflow_distill.kv_cache_distill import configure_decoder_streaming_context

    configure_decoder_streaming_context(
        model, decoder_left_frames=int(config["decoder_left_frames"]),
        static_chunk_size=int(config["distill_chunk_size"]),
    )
    with torch.no_grad():
        _, cache = model.decoder.estimator.forward_streaming(
            torch.zeros(1, 100, 100), torch.ones(1, 1, 100), torch.zeros(1, 100, 100),
            torch.tensor(0.5), model.spk_emb(torch.tensor([1])), r=torch.tensor(0.0),
        )
    layout = streaming.CacheLayout.from_cache(cache)
    first = streaming.session(args.model_dir / "lits_stream_decoder_cache_init.onnx", args.threads)
    following = streaming.session(args.model_dir / "lits_stream_decoder_cache_step.onnx", args.threads)
    manifest = json.loads((args.model_dir / "manifest.json").read_text())
    report = {"training_chunk_size": int(config["distill_chunk_size"]), "cases": {}}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    for chunk in args.chunks:
        if chunk < 1:
            parser.error("chunk sizes must be positive")
        report["cases"][str(chunk)] = streaming.validate_chunks(
            model, layout, first, following, manifest["stream_decoder_temperature"],
            chunk, int(config["pre_lookahead_len"]),
        )
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        logging.info("PASS chunk size %d", chunk)


if __name__ == "__main__":
    main()
