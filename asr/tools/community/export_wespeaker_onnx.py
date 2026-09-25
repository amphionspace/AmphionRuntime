#!/usr/bin/env python3
"""Export the Community-1 WeSpeaker checkpoint for sherpa-onnx."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import onnx
import torch
from pyannote.audio.models.embedding.wespeaker import WeSpeakerResNet34


class WeSpeakerOnnx(torch.nn.Module):
    def __init__(self, checkpoint: Path) -> None:
        super().__init__()
        payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
        self.resnet = WeSpeakerResNet34().resnet
        self.resnet.load_state_dict(
            {
                key.removeprefix("resnet."): value
                for key, value in payload["state_dict"].items()
                if key.startswith("resnet.")
            },
            strict=True,
        )
        self.resnet.eval()

    def forward(self, feats: torch.Tensor, weights: torch.Tensor) -> torch.Tensor:
        # Community-1 pools the complete waveform feature map with the
        # segmentation mask.  Keeping weights as an ONNX input preserves the
        # official weighted mean/std statistics pooling path.
        return self.resnet(feats, weights=weights)[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    torch.manual_seed(0)
    model = WeSpeakerOnnx(args.checkpoint).eval()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    example = torch.zeros(1, 200, 80, dtype=torch.float32)
    example_weights = torch.ones(1, 589, dtype=torch.float32)
    torch.onnx.export(
        model,
        (example, example_weights),
        args.output,
        input_names=["feats", "weights"],
        output_names=["embs"],
        dynamic_axes={
            "feats": {0: "batch", 1: "frames"},
            "weights": {0: "batch", 1: "mask_frames"},
            "embs": {0: "batch"},
        },
        opset_version=17,
        do_constant_folding=True,
        dynamo=False,
    )
    graph = onnx.load(args.output)
    onnx.checker.check_model(graph)
    metadata = {
        "amphion.source": "pyannote/speaker-diarization-community-1 embedding checkpoint",
        "framework": "wespeaker",
        "language": "multilingual",
        "url": "https://huggingface.co/pyannote/speaker-diarization-community-1",
        "comment": "Community-1 WeSpeaker ResNet34 VoxCeleb embedding model",
        "sample_rate": "16000",
        "output_dim": "256",
        # pyannote multiplies normalized waveform samples by 2**15 before
        # extracting Kaldi fbank features.
        "normalize_samples": "0",
        "feature_normalize_type": "global-mean",
    }
    for key, value in metadata.items():
        graph.metadata_props.add(key=key, value=value)
    onnx.save(graph, args.output)
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    print(f"wrote {args.output} ({args.output.stat().st_size} bytes, sha256={digest})")


if __name__ == "__main__":
    main()
