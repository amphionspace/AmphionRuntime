#!/usr/bin/env python3
"""Export the local 24 kHz Vocos vocoder to an Android-friendly ONNX model."""

from __future__ import annotations

import argparse
import json
import sys
import types
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch
import torch.nn.functional as F
import yaml


SDK_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = SDK_ROOT.parent
DEFAULT_VOCOS_ROOT = WORKSPACE_ROOT / "tts" / "training" / "dingqiao_lits" / "vocos-24k"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vocos-root", type=Path, default=DEFAULT_VOCOS_ROOT)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_VOCOS_ROOT / "last.ckpt")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mel-frames", type=int, default=64)
    parser.add_argument("--opset", type=int, default=17)
    return parser.parse_args()


def ensure_imports(vocos_root: Path) -> None:
    if str(vocos_root) not in sys.path:
        sys.path.insert(0, str(vocos_root))
    if "encodec" not in sys.modules:
        try:
            __import__("encodec")
        except ModuleNotFoundError:
            encodec_stub = types.ModuleType("encodec")

            class _MissingEncodecModel:
                @staticmethod
                def encodec_model_24khz(*_args, **_kwargs):
                    raise RuntimeError("encodec is unavailable for this mel-feature Vocos export.")

                @staticmethod
                def encodec_model_48khz(*_args, **_kwargs):
                    raise RuntimeError("encodec is unavailable for this mel-feature Vocos export.")

            encodec_stub.EncodecModel = _MissingEncodecModel
            sys.modules["encodec"] = encodec_stub


class RealIstftHead(torch.nn.Module):
    """Export-friendly equivalent of Vocos ISTFTHead without complex tensors."""

    def __init__(self, head: torch.nn.Module):
        super().__init__()
        self.out = head.out
        self.n_fft = int(head.istft.n_fft)
        self.win_length = int(head.istft.win_length)
        self.hop_length = int(head.istft.hop_length)

        freq_bins = self.n_fft // 2 + 1
        n = torch.arange(self.win_length, dtype=torch.float32).view(self.win_length, 1)
        k = torch.arange(freq_bins, dtype=torch.float32).view(1, freq_bins)
        angle = 2 * np.pi * n * k / self.n_fft
        scale = torch.full((freq_bins,), 2.0 / self.n_fft)
        scale[0] = 1.0 / self.n_fft
        scale[-1] = 1.0 / self.n_fft
        self.register_buffer("cos_basis", torch.cos(angle) * scale.view(1, -1))
        self.register_buffer("sin_basis", torch.sin(angle) * scale.view(1, -1))
        self.register_buffer("window", head.istft.window.float())

        overlap_weight = torch.zeros(self.win_length, 1, self.win_length)
        for index in range(self.win_length):
            overlap_weight[index, 0, index] = 1.0
        self.register_buffer("overlap_weight", overlap_weight)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.out(x).transpose(1, 2)
        mag, phase = x.chunk(2, dim=1)
        mag = torch.clamp(torch.exp(mag), max=1e2)
        real = mag * torch.cos(phase)
        imag = mag * torch.sin(phase)

        frames = (
            torch.matmul(real.transpose(1, 2), self.cos_basis.t())
            - torch.matmul(imag.transpose(1, 2), self.sin_basis.t())
        ).transpose(1, 2)
        frames = frames * self.window.view(1, self.win_length, 1)

        y = F.conv_transpose1d(frames, self.overlap_weight, stride=self.hop_length)
        envelope_input = self.window.square().view(1, self.win_length, 1).expand(
            frames.shape[0],
            self.win_length,
            frames.shape[2],
        )
        envelope = F.conv_transpose1d(envelope_input, self.overlap_weight, stride=self.hop_length)
        pad = (self.win_length - self.hop_length) // 2
        return y[:, :, pad:-pad] / envelope[:, :, pad:-pad].clamp_min(1e-11)


class VocosOnnxWrapper(torch.nn.Module):
    def __init__(self, vocos: torch.nn.Module):
        super().__init__()
        self.backbone = vocos.backbone
        self.head = RealIstftHead(vocos.head)

    def forward(self, mel: torch.Tensor) -> torch.Tensor:
        return self.head(self.backbone(mel))


def instantiate_vocos(vocos_root: Path):
    from vocos.pretrained import Vocos, instantiate_class

    config = yaml.safe_load((vocos_root / "config.yaml").read_text(encoding="utf-8"))
    init_args = config["model"]["init_args"]
    feature_extractor = instantiate_class(args=(), init=init_args["feature_extractor"])
    backbone = instantiate_class(args=(), init=init_args["backbone"])
    head = instantiate_class(args=(), init=init_args["head"])
    return Vocos(feature_extractor=feature_extractor, backbone=backbone, head=head), init_args


def load_vocos(vocos_root: Path, checkpoint: Path):
    model, init_args = instantiate_vocos(vocos_root)
    checkpoint_obj = torch.load(str(checkpoint), map_location="cpu")
    state_dict = checkpoint_obj.get("state_dict", checkpoint_obj)
    missing, unexpected = model.load_state_dict(state_dict, strict=False)
    if missing:
        raise RuntimeError(f"Vocos generator missing keys: {missing[:8]}")
    model.eval()
    return model, init_args, unexpected


def main() -> int:
    args = parse_args()
    args.vocos_root = args.vocos_root.resolve()
    args.checkpoint = args.checkpoint.resolve()
    args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    ensure_imports(args.vocos_root)

    vocos, init_args, unexpected = load_vocos(args.vocos_root, args.checkpoint)
    wrapper = VocosOnnxWrapper(vocos).eval()
    n_mels = int(init_args["feature_extractor"]["init_args"]["n_mels"])
    sample_rate = int(init_args["sample_rate"])
    hop_length = int(init_args["head"]["init_args"]["hop_length"])
    mel = torch.randn(1, n_mels, args.mel_frames, dtype=torch.float32)
    with torch.inference_mode():
        reference = wrapper(mel).detach().cpu().numpy()
    torch.onnx.export(
        wrapper,
        (mel,),
        str(args.output),
        input_names=["mel"],
        output_names=["waveform"],
        dynamic_axes={"mel": {2: "mel_frames"}, "waveform": {2: "audio_samples"}},
        opset_version=args.opset,
        dynamo=False,
    )
    session = ort.InferenceSession(str(args.output), providers=["CPUExecutionProvider"])
    ort_waveform = session.run(["waveform"], {"mel": mel.numpy()})[0]
    diff = np.abs(ort_waveform - reference)
    report = {
        "vocoder": "vocos24k",
        "checkpoint": str(args.checkpoint),
        "onnx": str(args.output),
        "sample_rate": sample_rate,
        "hop_length": hop_length,
        "n_mels": n_mels,
        "unexpected_checkpoint_keys": len(unexpected),
        "validation": {
            "shape": list(ort_waveform.shape),
            "mean_abs": float(diff.mean()),
            "max_abs": float(diff.max()),
        },
    }
    report_path = args.output.with_suffix(".export_report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
