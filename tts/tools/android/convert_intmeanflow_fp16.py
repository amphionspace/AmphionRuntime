#!/usr/bin/env python3
"""Make a separate mixed-FP16 student package, preserving FP32 timing and cache IO.

Only Conv/MatMul/Gemm are eligible for FP16. Duration prediction and decoder
position calculations stay FP32. Run numerical and target-device validation
before using the result: CPU providers can promote FP16 operators back to FP32.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import onnx
from onnxruntime.transformers.float16 import convert_float_to_float16

from convert_dingqiao_external_loop_package_fp16 import sort_graph_nodes

HALF_OPS = {"Conv", "MatMul", "Gemm"}


def protected_nodes(model: onnx.ModelProto, filename: str) -> set[str]:
    producers = {output: node for node in model.graph.node for output in node.output}
    protected: set[str] = set()

    def protect(value: str) -> None:
        node = producers.get(value)
        if node is None or node.name in protected:
            return
        protected.add(node.name)
        # Shape depends on dimensions, not the precision of the tensor's values.
        if node.op_type != "Shape":
            for source in node.input:
                protect(source)

    if filename == "lits_hidden_encoder.onnx":
        protect("mel_length")
    return protected


def repair_generated_casts(model: onnx.ModelProto) -> None:
    producers = {output: node for node in model.graph.node for output in node.output}
    for node in model.graph.node:
        if node.op_type != "Cast" or not node.name.endswith("_cast_to_fp32_node"):
            continue
        prior = producers.get(node.input[0])
        if prior is not None and prior.op_type == "Cast" and prior.name.endswith("_cast_to_fp16_node"):
            # The converter inserts FP32 -> FP16 -> FP32 between adjacent
            # blocked nodes. Bypass that unintended rounding; a large attention
            # sentinel would otherwise become infinity and 0 * inf becomes NaN.
            node.input[0] = prior.input[0]

    seen: dict[tuple[str, ...], onnx.NodeProto] = {}
    nodes = []
    for node in model.graph.node:
        key = tuple(node.output)
        previous = seen.get(key)
        if previous is not None:
            if node.op_type != "Cast" or node.SerializeToString() != previous.SerializeToString():
                raise ValueError(f"Conflicting converted producers for {key}")
            continue  # Identical casts can be inserted for multiple consumers.
        seen[key] = node
        nodes.append(node)
    del model.graph.node[:]
    model.graph.node.extend(nodes)
    sort_graph_nodes(model.graph)


def convert_model(model: onnx.ModelProto, filename: str) -> tuple[onnx.ModelProto, dict]:
    blocked = sorted({node.op_type for node in model.graph.node} - HALF_OPS)
    protected = protected_nodes(model, filename)
    converted = convert_float_to_float16(
        model, keep_io_types=True, op_block_list=blocked,
        node_block_list=sorted(protected), force_fp16_initializers=False,
    )
    repair_generated_casts(converted)
    onnx.checker.check_model(converted)
    return converted, {"fp32_ops": blocked, "fp32_nodes": sorted(protected)}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def convert_package(source: Path, target: Path) -> dict:
    manifest = json.loads((source / "manifest.json").read_text())
    if manifest.get("stream_decoder_cache", {}).get("mode") != "intmeanflow_absolute_kv_v1":
        raise ValueError("Expected an exported cached IntMeanFlow student package")
    if manifest.get("precision", "fp32") != "fp32":
        raise ValueError("Input must be the original FP32 package")
    if target.exists():
        raise FileExistsError(f"Refusing to replace existing output: {target}")
    shutil.copytree(source, target)
    reports = []
    for entry in manifest["files"]:
        name = entry["name"]
        if not name.endswith(".onnx"):
            continue
        original = source / name
        converted, policy = convert_model(onnx.load(original), name)
        onnx.save(converted, target / name)
        reports.append({"name": name, "source_sha256": sha256(original),
                        "sha256": sha256(target / name), "source_bytes": original.stat().st_size,
                        "bytes": (target / name).stat().st_size, **policy})
    manifest["model_id"] += "_fp16"
    manifest["precision"] = "mixed_fp16_io_fp32"
    manifest["precision_policy"] = "fp16_linear_fp32_duration_positions_v1"
    manifest["source_manifest_sha256"] = sha256(source / "manifest.json")
    manifest["notes"] = manifest.get("notes", "") + " Mixed FP16 candidate; target-device validation required."
    for entry in manifest["files"]:
        entry["size_bytes"] = (target / entry["name"]).stat().st_size
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    report = {"precision_policy": manifest["precision_policy"], "graphs": reports}
    (target / "fp16_conversion.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(convert_package(args.input_dir.resolve(), args.output_dir.resolve()), indent=2))


if __name__ == "__main__":
    main()
