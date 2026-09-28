#!/usr/bin/env python3
"""Split the locked Community WeSpeaker graph without changing its weights.

Offline preparation only. Requires onnx==1.19.1; SDK inference never uses Python.
The manifest binds the source and both graph outputs. Existing files are not
overwritten so an unsuccessful export remains distinguishable from a valid one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / 'delivery/harmony-dingqiao/delivery/community_diarization_1.json'


def verify(path: Path, expected: dict) -> None:
    data = path.read_bytes()
    if len(data) != expected['sizeBytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
        raise ValueError(f'model identity mismatch: {path}')


def export(source: Path, output: Path, manifest: Path) -> None:
    import onnx

    spec = json.loads(manifest.read_text())
    recipe = spec['embeddingGraphSplit']
    if onnx.__version__ != recipe['onnxVersion']:
        raise ValueError(f"use onnx=={recipe['onnxVersion']} for reproducible graph bytes")
    verify(source, recipe['source'])
    output.mkdir(parents=True, exist_ok=False)
    cut = recipe['splitPoint']
    graphs = [(['fbank'], [cut]), ([cut, 'masks'], ['embeddings'])]
    for expected, (inputs, outputs) in zip(spec['files'][:2], graphs):
        target = output / expected['file']
        onnx.utils.extract_model(str(source), str(target), inputs, outputs)
        verify(target, expected)
    record = {'source': recipe['source'], 'graphs': spec['files'][:2],
              'onnxVersion': onnx.__version__, 'splitPoint': cut,
              'manifestSha256': hashlib.sha256(manifest.read_bytes()).hexdigest()}
    (output / 'export.json').write_text(json.dumps(record, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path, help='new output directory')
    parser.add_argument('--manifest', type=Path, default=MANIFEST)
    args = parser.parse_args()
    export(args.source, args.output, args.manifest)
