#!/usr/bin/env python3
"""Rewrite the pinned dynamic-quantised ASR encoder into an FP32 ONNX graph.

MindSpore Lite 2.7.0's ONNX frontend rejects `DynamicQuantizeLinear` and
`MatMulInteger`, so the delivered INT8 encoder cannot be converted to MindIR at
all. This tool folds each dynamic-quantisation group back into a plain MatMul so
the graph becomes convertible. It is an experiment input, not a delivery
artifact: FP32 weights are about four times the INT8 size, and FP32 inference is
not the shipped CPU path.

Each rewritten group has exactly this shape, verified for all 344 occurrences:

    X -> DynamicQuantizeLinear -> (x_q, x_scale, x_zp)
    MatMulInteger(x_q, W_q, x_zp, W_zp) -> int32
    Cast(to=float) -> Mul(cast_out, Mul(x_scale, W_scale)) -> Y

and becomes `MatMul(X, (W_q - W_zp) * W_scale) -> Y`, which is the arithmetic the
quantised group approximates once the activation scale cancels. Dequantising the
weights does not recover the accuracy the FP32 export would have had: the INT8
weights are already rounded, and activation quantisation error disappears.

Usage:
  .venv-harmony-ort-1.16.3/bin/python asr/tools/dequantize_asr_encoder.py \
    --source asr/tools/demo-model/amphion-zh-en-police-179m-1.4.0-chunk32-lc256-edge-transducer/encoder.int8.onnx \
    --output .cache/asr-encoder-npu/encoder.dequantized.fp32.onnx

--verify runs both graphs in onnxruntime on one synthetic chunk and records the
output deviation. --inspect reports the rewrite plan without writing a model.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = (ROOT / "asr/tools/demo-model"
                  / "amphion-zh-en-police-179m-1.4.0-chunk32-lc256-edge-transducer/encoder.int8.onnx")
PINNED_SOURCE_SHA256 = "04b89ee63a7f850b281db67d9a1aa05fd5112a8c748b8edcb398b744490178b0"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class RewriteError(RuntimeError):
    pass


class Group:
    """One dynamic-quantisation group that folds into a single MatMul."""

    __slots__ = ("matmul_integer", "quantize", "cast", "output_mul", "scales_mul",
                 "activation", "output", "weight_name", "zero_point_name", "scale_name")

    def __init__(self, matmul_integer, quantize, cast, output_mul, scales_mul,
                 activation: str, output: str, weight_name: str, zero_point_name: str, scale_name: str):
        self.matmul_integer = matmul_integer
        self.quantize = quantize
        self.cast = cast
        self.output_mul = output_mul
        self.scales_mul = scales_mul
        self.activation = activation
        self.output = output
        self.weight_name = weight_name
        self.zero_point_name = zero_point_name
        self.scale_name = scale_name


def plan(graph) -> tuple[list[Group], dict[str, int]]:
    """Match every MatMulInteger against the expected group, or fail loudly."""
    initializers = {item.name for item in graph.initializer}
    producer = {output: node for node in graph.node for output in node.output}
    consumers: dict[str, list] = defaultdict(list)
    for node in graph.node:
        for value in node.input:
            consumers[value].append(node)

    groups: list[Group] = []
    for node in graph.node:
        if node.op_type != "MatMulInteger":
            continue
        if len(node.input) != 4 or len(node.output) != 1:
            raise RewriteError(f"{node.name}: expected 4 inputs and 1 output")
        quantize = producer.get(node.input[0])
        if quantize is None or quantize.op_type != "DynamicQuantizeLinear":
            raise RewriteError(f"{node.name}: activation is not dynamically quantised")
        if node.input[2] != quantize.output[2]:
            raise RewriteError(f"{node.name}: activation zero point is not the quantiser's")
        if node.input[1] not in initializers or node.input[3] not in initializers:
            raise RewriteError(f"{node.name}: weight or weight zero point is not constant")
        casts = consumers[node.output[0]]
        if len(casts) != 1 or casts[0].op_type != "Cast":
            raise RewriteError(f"{node.name}: int32 output is not consumed by exactly one Cast")
        cast = casts[0]
        if any(attribute.name == "to" and attribute.i != TensorProto.FLOAT for attribute in cast.attribute):
            raise RewriteError(f"{cast.name}: Cast target is not float32")
        muls = consumers[cast.output[0]]
        if len(muls) != 1 or muls[0].op_type != "Mul":
            raise RewriteError(f"{cast.name}: cast output is not consumed by exactly one Mul")
        output_mul = muls[0]
        others = [value for value in output_mul.input if value != cast.output[0]]
        if len(others) != 1:
            raise RewriteError(f"{output_mul.name}: expected one scale input")
        scales_mul = producer.get(others[0])
        if scales_mul is None or scales_mul.op_type != "Mul":
            raise RewriteError(f"{output_mul.name}: combined scale is not a Mul of two scales")
        scale_names = [value for value in scales_mul.input if value != quantize.output[1]]
        if len(scale_names) != 1 or scale_names[0] not in initializers:
            raise RewriteError(f"{scales_mul.name}: weight scale is not a single constant")
        groups.append(Group(node, quantize, cast, output_mul, scales_mul,
                            quantize.input[0], output_mul.output[0],
                            node.input[1], node.input[3], scale_names[0]))

    stats = {
        "matmul_integer": sum(1 for node in graph.node if node.op_type == "MatMulInteger"),
        "dynamic_quantize_linear": sum(1 for node in graph.node if node.op_type == "DynamicQuantizeLinear"),
        "groups": len(groups),
    }
    if stats["groups"] != stats["matmul_integer"]:
        raise RewriteError("not every MatMulInteger matched the expected group")
    return groups, stats


def dequantize_weight(weight: np.ndarray, zero_point: np.ndarray, scale: np.ndarray) -> np.ndarray:
    if weight.dtype not in (np.int8, np.uint8):
        raise RewriteError(f"unexpected weight dtype {weight.dtype}")
    if scale.size != 1 or zero_point.size != 1:
        raise RewriteError("only per-tensor weight quantisation is handled")
    centred = weight.astype(np.float32) - np.float32(zero_point.reshape(-1)[0])
    return centred * np.float32(scale.reshape(-1)[0])


def rewrite(model, groups: list[Group]):
    graph = model.graph
    initializer = {item.name: item for item in graph.initializer}
    consumers: Counter = Counter()
    for node in graph.node:
        for value in node.input:
            consumers[value] += 1

    dropped = set()
    new_weights = []
    replacements = {}
    for index, group in enumerate(groups):
        weight = numpy_helper.to_array(initializer[group.weight_name])
        zero_point = numpy_helper.to_array(initializer[group.zero_point_name])
        scale = numpy_helper.to_array(initializer[group.scale_name])
        values = dequantize_weight(weight, zero_point, scale)
        name = f"{group.weight_name}_dequantized"
        new_weights.append(numpy_helper.from_array(values, name))
        replacements[id(group.matmul_integer)] = helper.make_node(
            "MatMul", [group.activation, name], [group.output],
            name=f"{group.matmul_integer.name or f'matmul_integer_{index}'}_dequantized")
        dropped.update({id(group.cast), id(group.output_mul)})
        # The quantiser and the scale product survive only if something outside
        # every rewritten group still reads them.
        for node, used in ((group.quantize, group.quantize.output),
                           (group.scales_mul, group.scales_mul.output)):
            if all(consumers[value] <= sum(1 for g in groups
                                           if value in (g.quantize.output[0], g.quantize.output[1],
                                                        g.quantize.output[2], g.scales_mul.output[0]))
                   for value in used):
                dropped.add(id(node))

    kept = []
    for node in graph.node:
        if id(node) in replacements:
            kept.append(replacements[id(node)])
        elif id(node) not in dropped:
            kept.append(node)
    del graph.node[:]
    graph.node.extend(kept)

    retired = {group.weight_name for group in groups}
    retired |= {group.zero_point_name for group in groups}
    retired |= {group.scale_name for group in groups}
    surviving_inputs = {value for node in graph.node for value in node.input}
    remaining = [item for item in graph.initializer
                 if item.name not in retired or item.name in surviving_inputs]
    del graph.initializer[:]
    graph.initializer.extend(remaining)
    graph.initializer.extend(new_weights)
    return {"rewritten_groups": len(groups), "removed_nodes": len(dropped),
            "added_weight_bytes": int(sum(numpy_helper.to_array(w).nbytes for w in new_weights))}


def input_signature(graph) -> list[dict]:
    initializers = {item.name for item in graph.initializer}
    signature = []
    for value in graph.input:
        if value.name in initializers:
            continue
        tensor = value.type.tensor_type
        dims = [dimension.dim_value if dimension.dim_value else dimension.dim_param
                for dimension in tensor.shape.dim]
        signature.append({"name": value.name,
                          "dtype": TensorProto.DataType.Name(tensor.elem_type),
                          "shape": dims})
    return signature


def fixed_shape_argument(signature: list[dict], batch: int) -> str:
    parts = []
    for item in signature:
        dims = [str(batch) if isinstance(dimension, str) else str(dimension)
                for dimension in item["shape"]]
        parts.append(f"{item['name']}:{','.join(dims)}")
    return ";".join(parts)


def synthetic_inputs(signature: list[dict], batch: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    feeds = {}
    for item in signature:
        shape = [batch if isinstance(dimension, str) else dimension for dimension in item["shape"]]
        if item["dtype"] == "FLOAT":
            # x is a log-mel chunk; cached states start at zero in a real stream,
            # but zeros would hide weight error, so every float input is random.
            feeds[item["name"]] = rng.standard_normal(shape, dtype=np.float32)
        elif item["dtype"] in ("INT64", "INT32"):
            dtype = np.int64 if item["dtype"] == "INT64" else np.int32
            feeds[item["name"]] = np.zeros(shape, dtype=dtype)
        else:
            raise RewriteError(f"unhandled input dtype {item['dtype']} for {item['name']}")
    return feeds


def verify(source: Path, output: Path, signature: list[dict], batch: int, seed: int) -> dict:
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    feeds = synthetic_inputs(signature, batch, seed)
    report = {"seed": seed, "batch": batch, "onnxruntime": ort.__version__}
    for label, path in (("int8", source), ("fp32", output)):
        session = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
        names = [item.name for item in session.get_outputs()]
        started = time.perf_counter()
        values = session.run(names, feeds)
        report[f"{label}_wall_ms"] = round((time.perf_counter() - started) * 1000, 3)
        report[f"{label}_outputs"] = {name: values[index] for index, name in enumerate(names)}
    first = report["int8_outputs"]["encoder_out"].astype(np.float64).reshape(-1)
    second = report["fp32_outputs"]["encoder_out"].astype(np.float64).reshape(-1)
    denominator = float(np.linalg.norm(first) * np.linalg.norm(second))
    report["encoder_out"] = {
        "elements": int(first.size),
        "max_abs_diff": float(np.max(np.abs(first - second))),
        "rms_diff": float(np.sqrt(np.mean((first - second) ** 2))),
        "int8_rms": float(np.sqrt(np.mean(first ** 2))),
        "cosine": float(np.dot(first, second) / denominator) if denominator else None,
    }
    states = [name for name in report["int8_outputs"] if name != "encoder_out"]
    worst = max(states, key=lambda name: float(np.max(np.abs(
        report["int8_outputs"][name].astype(np.float64) - report["fp32_outputs"][name].astype(np.float64)))))
    report["worst_state_output"] = {
        "name": worst,
        "max_abs_diff": float(np.max(np.abs(
            report["int8_outputs"][worst].astype(np.float64) - report["fp32_outputs"][worst].astype(np.float64)))),
    }
    del report["int8_outputs"], report["fp32_outputs"]
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=ROOT / ".cache/asr-encoder-npu/encoder.dequantized.fp32.onnx")
    parser.add_argument("--batch", type=int, default=1, help="value substituted for the dynamic batch dimension")
    parser.add_argument("--seed", type=int, default=20261008)
    parser.add_argument("--inspect", action="store_true", help="report the plan and signature, write nothing")
    parser.add_argument("--verify", action="store_true", help="compare both graphs in onnxruntime after writing")
    parser.add_argument("--allow-unpinned-source", action="store_true")
    args = parser.parse_args()

    if not args.source.is_file():
        print(f"[ERROR] missing source: {args.source}", file=sys.stderr)
        return 1
    source_sha256 = sha256_file(args.source)
    if source_sha256 != PINNED_SOURCE_SHA256 and not args.allow_unpinned_source:
        print(f"[ERROR] source SHA-256 {source_sha256} is not the pinned delivery encoder; "
              "pass --allow-unpinned-source to experiment with another export", file=sys.stderr)
        return 1

    model = onnx.load(str(args.source))
    groups, stats = plan(model.graph)
    signature = input_signature(model.graph)
    record = {
        "schemaVersion": 1,
        "kind": "asr-encoder-dequantized-fp32",
        "source": {"file": args.source.name, "sizeBytes": args.source.stat().st_size,
                   "sha256": source_sha256, "pinned": source_sha256 == PINNED_SOURCE_SHA256},
        "plan": stats,
        "inputs": signature,
        "converterInputShape": fixed_shape_argument(signature, args.batch),
        "scope": ("Graph rewrite only. Not an accuracy gate, not a delivery artifact, and no claim "
                  "about NNRt operator placement."),
    }
    if args.inspect:
        print(json.dumps(record, indent=1))
        return 0

    record["rewrite"] = rewrite(model, groups)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, str(args.output))
    onnx.checker.check_model(str(args.output), full_check=False)
    remaining = Counter(node.op_type for node in onnx.load(str(args.output), load_external_data=False).graph.node)
    record["output"] = {"file": args.output.name, "sizeBytes": args.output.stat().st_size,
                        "sha256": sha256_file(args.output),
                        "residualQuantOps": {name: remaining[name] for name
                                             in ("MatMulInteger", "DynamicQuantizeLinear") if remaining[name]}}
    if record["output"]["residualQuantOps"]:
        print(f"[ERROR] quantisation operators remain: {record['output']['residualQuantOps']}", file=sys.stderr)
        return 1
    if args.verify:
        record["verification"] = verify(args.source, args.output, signature, args.batch, args.seed)
    provenance = args.output.with_suffix(args.output.suffix + ".provenance.json")
    provenance.write_text(json.dumps(record, indent=1) + "\n")
    print(json.dumps({"output": str(args.output), "provenance": str(provenance),
                      "groups": record["rewrite"]["rewritten_groups"],
                      "sizeBytes": record["output"]["sizeBytes"],
                      "verification": record.get("verification", {}).get("encoder_out")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
