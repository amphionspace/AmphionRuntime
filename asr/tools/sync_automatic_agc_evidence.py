#!/usr/bin/env python3
"""Verify that automatic AGC evidence matches the accuracy-affecting implementation."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "asr/android/reports/automatic-agc-evaluation/report.json"
# Only sources that can change AGC samples or framing belong to the expensive accuracy-evidence
# fingerprint. Session orchestration is covered by the lightweight signal-domain contracts instead;
# hashing the complete session implementations would make unrelated VAD, speaker, or lifecycle
# changes invalidate AGC accuracy evidence.
ACCURACY_EVIDENCE_SOURCES = (
    "asr/native/audio-processing/meson.build",
    "asr/native/audio-processing/subprojects/webrtc-audio-processing.wrap",
    "asr/native/audio-processing/src/amphion_audio_processing.cpp",
    "asr/android/sdk/src/main/java/com/amphion/asr/internal/StreamingAgcIngress.kt",
    "asr/android/sdk/src/main/java/com/amphion/asr/internal/StreamingAgcProcessor.kt",
    "asr/android/sdk/src/main/java/com/amphion/asr/internal/NativeAgcBackend.kt",
    "asr/harmony/sdk/src/main/ets/com/amphion/asr/StreamingAgcIngress.ts",
    "asr/harmony/sdk/src/main/ets/com/amphion/asr/StreamingAgcProcessor.ts",
    "asr/harmony/sdk/src/main/ets/com/amphion/asr/NativeAgcBackend.ets",
    "asr/harmony/sdk/src/main/cpp/agc_bridge.cpp",
    "asr/tools/evaluate_automatic_agc_regression.py",
)


def source_hashes(root: Path = ROOT) -> dict:
    hashes = {}
    for relative_path in ACCURACY_EVIDENCE_SOURCES:
        source = root / relative_path
        if not source.is_file():
            raise FileNotFoundError(f"missing AGC evidence source: {relative_path}")
        hashes[relative_path] = hashlib.sha256(source.read_bytes()).hexdigest()
    return hashes


def check(report_path: Path = REPORT, root: Path = ROOT) -> bool:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    recorded = report.get("implementation_source_sha256")
    expected = source_hashes(root)
    if recorded == expected:
        print("[OK] automatic AGC evidence matches every accuracy-affecting source")
        return True

    print("[ERROR] automatic AGC accuracy-evidence fingerprints are stale", file=sys.stderr)
    recorded = recorded if isinstance(recorded, dict) else {}
    for relative_path in sorted(set(recorded) | set(expected)):
        if recorded.get(relative_path) != expected.get(relative_path):
            print(
                f"  {relative_path}: recorded={recorded.get(relative_path)} "
                f"current={expected.get(relative_path)}",
                file=sys.stderr,
            )
    print(
        "Rerun the complete normal-volume, SNR, long-audio, and low-volume evaluation "
        "and replace report.json with the evaluator-produced report.",
        file=sys.stderr,
    )
    return False


def check_runtime_inputs(
    report_path: Path,
    model_dir: Path,
    artifact_root: Path | None = None,
) -> bool:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    runtime = report.get("evaluation_runtime", {})
    expected_models = runtime.get("model_sha256", {})
    for name, expected in expected_models.items():
        path = model_dir / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            print(f"[ERROR] evaluation model does not match report: {path}", file=sys.stderr)
            return False
    expected_sherpa = runtime.get("sherpa_onnx_version")
    if expected_sherpa:
        try:
            import sherpa_onnx
        except ImportError:
            print("[ERROR] sherpa_onnx is required to verify the evaluation runtime", file=sys.stderr)
            return False
        if getattr(sherpa_onnx, "__version__", None) != expected_sherpa:
            print(
                f"[ERROR] sherpa_onnx version does not match report: "
                f"expected={expected_sherpa} actual={getattr(sherpa_onnx, '__version__', None)}",
                file=sys.stderr,
            )
            return False
    if artifact_root is not None:
        for name, expected in report.get("preserved_artifact_sha256", {}).items():
            path = artifact_root / name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                print(f"[ERROR] preserved evaluation artifact does not match report: {path}", file=sys.stderr)
                return False
    print("[OK] automatic AGC evaluation runtime inputs match the recorded evidence")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail when evidence is stale")
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--artifact-root", type=Path)
    args = parser.parse_args()
    valid = check()
    if args.artifact_root is not None and args.model_dir is None:
        parser.error("--artifact-root requires --model-dir")
    if args.model_dir is not None:
        valid = check_runtime_inputs(REPORT, args.model_dir, args.artifact_root) and valid
    return 0 if valid else 1


if __name__ == "__main__":
    sys.exit(main())
