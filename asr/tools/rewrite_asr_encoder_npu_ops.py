#!/usr/bin/env python3
"""Replace the operators Kirin NNRt refuses in the ASR encoder with exact equivalents.

Measured on a Mate 80 (NPU_ohos.boot.hardware.kirin9020_v2_0, MindSpore Lite
2.7.0): HiAI rejects a whole MindIR graph that contains `GatherElements`, with
`NNRt: Authentication failed, input model cannot run by npu`. The MindSpore Lite
NNRT delegate offloads whole models only, so one refused operator disqualifies
the entire encoder. Every other zipformer2 operator family probed on that device
was accepted, including the masked attention block.

`GatherElements(data, indices, axis=k)` is rewritten as

    Reshape(data, [-1])
    Gather(flat_data, Reshape(indices * stride_k + base, [-1]), axis=0)
    Reshape(picked, indices.shape)

`stride_k` is the row stride of the gathered axis and `base` holds the flattened
coordinates of every other axis, both constant once the batch dimension is
pinned. The index arithmetic therefore stays in the graph, so it works with the
runtime-computed relative-position indices this export uses. The rewrite is
bit-exact, not an approximation: it selects exactly the same elements, and only
the operator set changes. Negative indices are not handled; the verification
pass is what establishes that this export has none.

Usage:
  .venv-harmony-ort-1.16.3/bin/python asr/tools/rewrite_asr_encoder_npu_ops.py \
    --source .cache/asr-encoder-npu/encoder.dequantized.fp32.onnx \
    --output .cache/asr-encoder-npu/encoder.npu-ops.fp32.onnx --verify
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper, shape_inference


ROOT = Path(__file__).resolve().parents[2]
# Probed on device: accepted graphs contained every one of these. Kept as the
# record of what was actually measured, not as a vendor-published list.
REFUSED_OPERATORS = ("GatherElements", "LessOrEqual")
# Shape-dependent operators are not refused one by one: the whole dynamic-shape
# chain (Shape -> Gather -> Unsqueeze -> Concat -> Reshape) is rejected, because
# HiAI compiles a static IR. Every such chain in this export is constant once the
# batch dimension is pinned, so folding removes them instead of substituting.
SHAPE_ORIGIN = "Shape"


class RewriteError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fix_batch(model, batch: int) -> list[str]:
    """Pin every symbolic batch dimension so shapes become inferable."""
    pinned = []
    for value in model.graph.input:
        for dimension in value.type.tensor_type.shape.dim:
            if dimension.HasField("dim_param"):
                dimension.ClearField("dim_param")
                dimension.dim_value = batch
                pinned.append(value.name)
    return sorted(set(pinned))


def static_shapes(model) -> tuple[dict[str, tuple[int, ...]], dict[str, int]]:
    # This export derives the relative-position indices through Shape/Range/Concat
    # chains that onnx.shape_inference leaves symbolic. ONNX Runtime's symbolic
    # pass resolves them once the batch dimension is pinned.
    try:
        from onnxruntime.tools.symbolic_shape_infer import SymbolicShapeInference
        inferred = SymbolicShapeInference.infer_shapes(model, auto_merge=True, guess_output_rank=True)
    except Exception:
        inferred = shape_inference.infer_shapes(model, strict_mode=False, data_prop=True)
    shapes: dict[str, tuple[int, ...]] = {}
    dtypes: dict[str, int] = {}
    for collection in (inferred.graph.input, inferred.graph.value_info, inferred.graph.output):
        for value in collection:
            dims = value.type.tensor_type.shape.dim
            if dims and all(dimension.HasField("dim_value") and dimension.dim_value > 0 for dimension in dims):
                shapes[value.name] = tuple(dimension.dim_value for dimension in dims)
            dtypes[value.name] = value.type.tensor_type.elem_type
    for item in inferred.graph.initializer:
        shapes.setdefault(item.name, tuple(item.dims))
        dtypes.setdefault(item.name, item.data_type)
    return shapes, dtypes


def drop_identity_casts(model, dtypes: dict[str, int]) -> int:
    """Remove Cast nodes whose target type is the type they already carry.

    The export leaves 57 bool-to-bool casts in the mask path. They are no-ops in
    every runtime, but this accelerator refuses them, so they have to go.
    """
    graph = model.graph
    rename: dict[str, str] = {}
    kept = []
    for node in graph.node:
        target = next((attribute.i for attribute in node.attribute if attribute.name == "to"), None)
        source = dtypes.get(node.input[0]) if node.input else None
        if node.op_type == "Cast" and target is not None and source == target:
            rename[node.output[0]] = node.input[0]
        else:
            kept.append(node)
    if not rename:
        return 0

    def resolve(name: str) -> str:
        seen = set()
        while name in rename and name not in seen:
            seen.add(name)
            name = rename[name]
        return name

    for node in kept:
        node.input[:] = [resolve(value) for value in node.input]
    for value in graph.output:
        if value.name in rename:
            raise RewriteError("an identity cast produces a graph output; rename instead of dropping")
    del graph.node[:]
    graph.node.extend(kept)
    return len(rename)


def rewrite_softplus_guards(model) -> dict:
    """Replace the exported softplus overflow guard with the stable formulation.

    The export writes `log(1 + exp(z))` and then guards it with
    `where(log_result == +inf, z, log_result)`. The guard compares floats, which
    this accelerator refuses, and it exists only because the naive form
    overflows. `max(z, 0) + log(1 + exp(-|z|))` is the same function without the
    overflow, so the comparison disappears instead of being substituted.
    """
    graph = model.graph
    initializer = {item.name: item for item in graph.initializer}
    producer = {output: node for node in graph.node for output in node.output}

    def constant(name):
        if name not in initializer:
            return None
        return numpy_helper.to_array(initializer[name])

    def through_cast(name):
        node = producer.get(name)
        while node is not None and node.op_type == "Cast":
            name = node.input[0]
            node = producer.get(name)
        return name, node

    replacements: dict[int, list] = {}
    added = []
    matched = []
    for index, node in enumerate(graph.node):
        if node.op_type != "Where" or len(node.input) != 3:
            continue
        equal = producer.get(node.input[0])
        if equal is None or equal.op_type != "Equal":
            continue
        limit = constant(equal.input[1])
        if limit is None or limit.size != 1 or not np.isinf(limit.reshape(-1)[0]):
            continue
        logged_name, logged = through_cast(equal.input[0])
        if logged is None or logged.op_type != "Log":
            continue
        plus_one = producer.get(logged.input[0])
        if plus_one is None or plus_one.op_type != "Add":
            continue
        exponent = next((producer.get(value) for value in plus_one.input
                         if producer.get(value) is not None
                         and producer[value].op_type == "Exp"), None)
        if exponent is None:
            continue
        inner = exponent.input[0]
        fallback_name, _ = through_cast(node.input[1])
        safe_name, _ = through_cast(node.input[2])
        if fallback_name != inner or safe_name != logged_name:
            continue
        stem = node.name or f"softplus_guard_{index}"
        names = {key: f"{stem}_{key}" for key in
                 ("abs", "neg", "exp", "plus", "log", "relu", "one", "zero")}
        added += [numpy_helper.from_array(np.array(1.0, dtype=np.float32), names["one"]),
                  numpy_helper.from_array(np.array(0.0, dtype=np.float32), names["zero"])]
        replacements[index] = [
            helper.make_node("Abs", [inner], [names["abs"]], name=f"{stem}_abs"),
            helper.make_node("Neg", [names["abs"]], [names["neg"]], name=f"{stem}_neg"),
            helper.make_node("Exp", [names["neg"]], [names["exp"]], name=f"{stem}_exp"),
            helper.make_node("Add", [names["exp"], names["one"]], [names["plus"]], name=f"{stem}_plus"),
            helper.make_node("Log", [names["plus"]], [names["log"]], name=f"{stem}_log"),
            helper.make_node("Max", [inner, names["zero"]], [names["relu"]], name=f"{stem}_relu"),
            helper.make_node("Add", [names["relu"], names["log"]], [node.output[0]], name=f"{stem}_sum"),
        ]
        matched.append(stem)

    if not replacements:
        return {"rewrittenGuards": 0}
    kept = []
    for index, node in enumerate(graph.node):
        kept.extend(replacements.get(index, [node]))
    del graph.node[:]
    graph.node.extend(kept)
    graph.initializer.extend(added)
    # Drop whatever the guard left behind, repeatedly: Log, Add, Exp, Cast, Equal.
    live_outputs = {value.name for value in graph.output}
    while True:
        consumed = {value for node in graph.node for value in node.input} | live_outputs
        dead = [node for node in graph.node if node.output and not any(output in consumed for output in node.output)]
        if not dead:
            break
        survivors = [node for node in graph.node if node not in dead]
        del graph.node[:]
        graph.node.extend(survivors)
    surviving = {value for node in graph.node for value in node.input}
    remaining = [item for item in graph.initializer if item.name in surviving]
    del graph.initializer[:]
    graph.initializer.extend(remaining)
    return {"rewrittenGuards": len(matched)}


def canonicalise_constants(model) -> int:
    """Turn Constant nodes into initializers so folding can see through them."""
    graph = model.graph
    promoted = []
    kept = []
    for node in graph.node:
        value = next((attribute.t for attribute in node.attribute if attribute.name == "value"), None)
        if node.op_type == "Constant" and value is not None and len(node.output) == 1:
            tensor = onnx.TensorProto()
            tensor.CopyFrom(value)
            tensor.name = node.output[0]
            promoted.append(tensor)
        else:
            kept.append(node)
    del graph.node[:]
    graph.node.extend(kept)
    graph.initializer.extend(promoted)
    return len(promoted)


def fold_static_subgraph(model, shapes: dict[str, tuple[int, ...]]) -> dict:
    """Evaluate every Shape-rooted, input-independent node and store it as a constant.

    HiAI rejects the dynamic-shape chains this export carries even though each one
    is constant for a pinned batch. Folding them is not an optimisation here: it is
    what makes the graph expressible as the static IR the accelerator compiles.
    """
    import onnxruntime as ort

    graph = model.graph
    promoted = canonicalise_constants(model)
    constant = {item.name for item in graph.initializer}
    added = []
    for node in list(graph.node):
        if node.op_type != SHAPE_ORIGIN:
            continue
        if node.input[0] not in shapes or node.attribute:
            continue
        values = np.array(shapes[node.input[0]], dtype=np.int64)
        added.append(numpy_helper.from_array(values, node.output[0]))
        constant.add(node.output[0])
        node.op_type = "__folded__"
    graph.initializer.extend(added)

    foldable: list = []
    folded_outputs: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in graph.node:
            if node.op_type == "__folded__" or node in foldable:
                continue
            if node.input and all(value in constant for value in node.input if value):
                foldable.append(node)
                for value in node.output:
                    constant.add(value)
                    folded_outputs.add(value)
                changed = True

    live = {value for node in graph.node
            if node.op_type != "__folded__" and node not in foldable
            for value in node.input}
    live |= {value.name for value in graph.output}
    wanted = sorted(folded_outputs & live)
    evaluated = {}
    if wanted and foldable:
        needed = {value for node in foldable for value in node.input}
        subgraph = helper.make_graph(
            foldable, "folded", [],
            [helper.make_empty_tensor_value_info(name) for name in wanted],
            [item for item in graph.initializer if item.name in needed])
        helper_model = helper.make_model(subgraph, opset_imports=list(model.opset_import))
        helper_model.ir_version = model.ir_version
        session = ort.InferenceSession(helper_model.SerializeToString(),
                                       providers=["CPUExecutionProvider"])
        for name, value in zip(wanted, session.run(wanted, {})):
            evaluated[name] = value

    kept = [node for node in graph.node if node.op_type != "__folded__" and node not in foldable]
    del graph.node[:]
    graph.node.extend(kept)
    graph.initializer.extend(numpy_helper.from_array(value, name) for name, value in evaluated.items())
    surviving = {value for node in graph.node for value in node.input}
    remaining = [item for item in graph.initializer if item.name in surviving]
    del graph.initializer[:]
    graph.initializer.extend(remaining)
    return {"promotedConstantNodes": promoted,
            "foldedShapeNodes": len(added), "foldedConstantNodes": len(foldable),
            "materialisedTensors": len(evaluated),
            "materialisedBytes": int(sum(value.nbytes for value in evaluated.values()))}


def coordinate_base(data_shape: tuple[int, ...], indices_shape: tuple[int, ...],
                    axis: int) -> tuple[np.ndarray, int]:
    """Constant part of the flat index: every axis except the gathered one."""
    if len(indices_shape) != len(data_shape):
        raise RewriteError(f"indices rank {len(indices_shape)} does not match data rank {len(data_shape)}")
    axis = axis if axis >= 0 else axis + len(data_shape)
    if not 0 <= axis < len(data_shape):
        raise RewriteError(f"axis {axis} is out of range for rank {len(data_shape)}")
    strides = np.ones(len(data_shape), dtype=np.int64)
    for position in range(len(data_shape) - 2, -1, -1):
        strides[position] = strides[position + 1] * data_shape[position + 1]
    base = np.zeros(indices_shape, dtype=np.int64)
    for position, extent in enumerate(indices_shape):
        if position == axis:
            continue
        if extent > data_shape[position]:
            raise RewriteError("indices extend past the data shape on a non-gathered axis")
        coordinate = np.arange(extent, dtype=np.int64).reshape(
            [extent if other == position else 1 for other in range(len(indices_shape))])
        base = base + coordinate * strides[position]
    return base, int(strides[axis])


def rewrite(model, batch: int) -> dict:
    graph = model.graph
    pinned = fix_batch(model, batch)
    shapes, index_types = static_shapes(model)

    replacements: dict[int, list] = {}
    added = []
    rewritten = []
    for index, node in enumerate(graph.node):
        if node.op_type not in REFUSED_OPERATORS:
            continue
        if node.op_type == "LessOrEqual":
            stem = node.name or f"less_or_equal_{index}"
            replacements[index] = [
                helper.make_node("Greater", list(node.input), [f"{stem}_greater"], name=f"{stem}_greater"),
                helper.make_node("Not", [f"{stem}_greater"], [node.output[0]], name=f"{stem}_not"),
            ]
            rewritten.append({"node": stem, "substitution": "Greater+Not"})
            continue
        if node.op_type != "GatherElements":
            raise RewriteError(f"no rewrite is implemented for {node.op_type}")
        data, index_name = node.input[0], node.input[1]
        if data not in shapes or index_name not in shapes:
            raise RewriteError(f"{node.name}: gathered tensor or indices have no static shape")
        axis = next((attribute.i for attribute in node.attribute if attribute.name == "axis"), 0)
        data_shape, indices_shape = shapes[data], shapes[index_name]
        base, stride = coordinate_base(data_shape, indices_shape, axis)
        index_dtype = index_types.get(index_name, TensorProto.INT64)
        numpy_dtype = np.int32 if index_dtype == TensorProto.INT32 else np.int64
        stem = node.name or f"gather_elements_{index}"
        names = {key: f"{stem}_{key}" for key in
                 ("stride", "base", "flat_shape", "index_shape", "output_shape",
                  "flat_data", "scaled", "flat_index_nd", "flat_index", "picked")}
        added += [
            numpy_helper.from_array(np.array(stride, dtype=numpy_dtype), names["stride"]),
            numpy_helper.from_array(base.astype(numpy_dtype), names["base"]),
            numpy_helper.from_array(np.array([int(np.prod(data_shape))], dtype=np.int64),
                                    names["flat_shape"]),
            numpy_helper.from_array(np.array([int(np.prod(indices_shape))], dtype=np.int64),
                                    names["index_shape"]),
            numpy_helper.from_array(np.array(indices_shape, dtype=np.int64), names["output_shape"]),
        ]
        replacements[index] = [
            helper.make_node("Reshape", [data, names["flat_shape"]], [names["flat_data"]],
                             name=f"{stem}_flatten"),
            helper.make_node("Mul", [index_name, names["stride"]], [names["scaled"]],
                             name=f"{stem}_scale_index"),
            helper.make_node("Add", [names["scaled"], names["base"]], [names["flat_index_nd"]],
                             name=f"{stem}_offset_index"),
            helper.make_node("Reshape", [names["flat_index_nd"], names["index_shape"]],
                             [names["flat_index"]], name=f"{stem}_flatten_index"),
            helper.make_node("Gather", [names["flat_data"], names["flat_index"]], [names["picked"]],
                             axis=0, name=f"{stem}_gather"),
            helper.make_node("Reshape", [names["picked"], names["output_shape"]], [node.output[0]],
                             name=f"{stem}_restore"),
        ]
        rewritten.append({"node": stem, "axis": axis, "dataShape": list(data_shape),
                          "indicesShape": list(indices_shape)})

    if not replacements:
        raise RewriteError("no refused operator was found; nothing to rewrite")
    kept = []
    for index, node in enumerate(graph.node):
        kept.extend(replacements.get(index, [node]))
    del graph.node[:]
    graph.node.extend(kept)

    surviving = {value for node in graph.node for value in node.input}
    remaining = [item for item in graph.initializer if item.name in surviving]
    del graph.initializer[:]
    graph.initializer.extend(remaining)
    graph.initializer.extend(added)
    del graph.value_info[:]
    record = {"rewrittenNodes": rewritten, "pinnedBatchInputs": pinned,
              "addedIndexBytes": int(sum(numpy_helper.to_array(item).nbytes for item in added))}
    record["promotedConstantNodes"] = canonicalise_constants(model)
    record["softplusGuards"] = rewrite_softplus_guards(model)
    record["droppedIdentityCasts"] = drop_identity_casts(model, index_types)
    record["shapeFold"] = fold_static_subgraph(model, shapes)
    return record


def input_signature(graph) -> list[dict]:
    initializers = {item.name for item in graph.initializer}
    signature = []
    for value in graph.input:
        if value.name in initializers:
            continue
        tensor = value.type.tensor_type
        signature.append({
            "name": value.name,
            "dtype": TensorProto.DataType.Name(tensor.elem_type),
            "shape": [dimension.dim_value if dimension.HasField("dim_value") else dimension.dim_param
                      for dimension in tensor.shape.dim],
        })
    return signature


def fixed_shape_argument(signature: list[dict], batch: int) -> str:
    return ";".join(
        f"{item['name']}:" + ",".join(str(batch) if isinstance(dimension, str) else str(dimension)
                                      for dimension in item["shape"])
        for item in signature)


def synthetic_inputs(signature: list[dict], seed: int) -> dict:
    rng = np.random.default_rng(seed)
    feeds = {}
    for item in signature:
        shape = [1 if isinstance(dimension, str) else dimension for dimension in item["shape"]]
        if item["dtype"] == "FLOAT":
            feeds[item["name"]] = rng.standard_normal(shape, dtype=np.float32)
        elif item["dtype"] in ("INT64", "INT32"):
            feeds[item["name"]] = np.zeros(shape, dtype=np.int64 if item["dtype"] == "INT64" else np.int32)
        else:
            raise RewriteError(f"unhandled input dtype {item['dtype']} for {item['name']}")
    return feeds


def verify(source: Path, output: Path, signature: list[dict], seed: int) -> dict:
    import onnxruntime as ort

    feeds = synthetic_inputs(signature, seed)
    report = {"seed": seed, "onnxruntime": ort.__version__}
    produced = {}
    for label, path in (("source", source), ("rewritten", output)):
        session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        names = [item.name for item in session.get_outputs()]
        started = time.perf_counter()
        values = session.run(names, feeds)
        report[f"{label}_wall_ms"] = round((time.perf_counter() - started) * 1000, 3)
        produced[label] = dict(zip(names, values))
    worst = 0.0
    worst_name = ""
    for name, value in produced["source"].items():
        other = produced["rewritten"][name]
        difference = float(np.max(np.abs(value.astype(np.float64) - other.astype(np.float64))))
        if difference > worst:
            worst, worst_name = difference, name
    report["outputs"] = len(produced["source"])
    report["maxAbsDiffAcrossAllOutputs"] = worst
    report["worstOutput"] = worst_name
    report["bitExact"] = worst == 0.0
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path,
                        default=ROOT / ".cache/asr-encoder-npu/encoder.dequantized.fp32.onnx")
    parser.add_argument("--output", type=Path,
                        default=ROOT / ".cache/asr-encoder-npu/encoder.npu-ops.fp32.onnx")
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20261008)
    parser.add_argument("--inspect", action="store_true", help="report refused operators, write nothing")
    parser.add_argument("--verify", action="store_true", help="compare both graphs in onnxruntime")
    args = parser.parse_args()

    if not args.source.is_file():
        print(f"[ERROR] missing source: {args.source}", file=sys.stderr)
        return 1
    model = onnx.load(str(args.source))
    census = Counter(node.op_type for node in model.graph.node)
    record = {
        "schemaVersion": 1,
        "kind": "asr-encoder-npu-operator-rewrite",
        "refusedOperators": {name: census[name] for name in REFUSED_OPERATORS},
        "source": {"file": args.source.name, "sizeBytes": args.source.stat().st_size,
                   "sha256": sha256_file(args.source), "nodes": len(model.graph.node)},
        "scope": ("Bit-exact operator substitution for the device's refused operator set. It does not "
                  "prove that the rewritten graph compiles on NNRt, nor anything about accuracy."),
    }
    if args.inspect:
        print(json.dumps(record, indent=1))
        return 0

    record["rewrite"] = rewrite(model, args.batch)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, str(args.output))
    onnx.checker.check_model(str(args.output), full_check=False)
    remaining = Counter(node.op_type for node in
                        onnx.load(str(args.output), load_external_data=False).graph.node)
    leftover = {name: remaining[name] for name in REFUSED_OPERATORS if remaining[name]}
    signature = input_signature(model.graph)
    record["output"] = {"file": args.output.name, "sizeBytes": args.output.stat().st_size,
                        "sha256": sha256_file(args.output), "nodes": sum(remaining.values()),
                        "residualRefusedOperators": leftover}
    record["converterInputShape"] = fixed_shape_argument(signature, args.batch)
    if leftover:
        print(f"[ERROR] refused operators remain: {leftover}", file=sys.stderr)
        return 1
    if args.verify:
        record["verification"] = verify(args.source, args.output, signature, args.seed)
    provenance = args.output.with_suffix(args.output.suffix + ".provenance.json")
    provenance.write_text(json.dumps(record, indent=1) + "\n")
    print(json.dumps({"output": str(args.output), "provenance": str(provenance),
                      "rewrittenNodes": len(record["rewrite"]["rewrittenNodes"]),
                      "sizeBytes": record["output"]["sizeBytes"],
                      "verification": record.get("verification")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
