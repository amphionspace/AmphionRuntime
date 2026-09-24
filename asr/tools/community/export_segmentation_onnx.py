#!/usr/bin/env python3
"""Export the Community-1 segmentation checkpoint to ONNX."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import onnx
import torch
from pyannote.audio import Model
from pyannote.audio.core.task import Problem, Resolution, Specifications


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    # Community-1 is a trusted, pinned local checkpoint. PyTorch 2.6+ requires
    # its metadata types to be explicitly allow-listed for weights-only loads.
    torch.serialization.add_safe_globals([Specifications, Problem, Resolution])
    model = Model.from_pretrained(args.checkpoint).eval()
    duration = int(model.specifications.duration * model.hparams.sample_rate)
    example = torch.zeros(1, model.hparams.num_channels, duration, dtype=torch.float32)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        model,
        (example,),
        args.output,
        input_names=["input_values"],
        output_names=["logits"],
        dynamic_axes={"input_values": {0: "batch_size"}, "logits": {0: "batch_size"}},
        opset_version=17,
        do_constant_folding=True,
        dynamo=False,
    )
    graph = onnx.load(args.output)
    onnx.checker.check_model(graph)
    metadata = {
        "amphion.source": "pyannote/speaker-diarization-community-1 segmentation checkpoint",
        "sample_rate": str(model.hparams.sample_rate),
        "duration": str(model.specifications.duration),
        "powerset_max_classes": str(model.specifications.powerset_max_classes),
        "output_classes": "7",
    }
    del graph.metadata_props[:]
    for key, value in metadata.items():
        graph.metadata_props.add(key=key, value=value)
    onnx.save(graph, args.output)
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    print(f"wrote {args.output} ({args.output.stat().st_size} bytes, sha256={digest})")


if __name__ == "__main__":
    main()
