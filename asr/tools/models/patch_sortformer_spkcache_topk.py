#!/usr/bin/env python3
"""把 spkcache_update 的 TopK_3 的 K 改成显式的一维长度 1 常量。

为什么要改：Android 链的 onnxruntime（sherpa 预构建 1.24.3）在加载这张图时报
`Node (/TopK_3) Op (TopK) [ShapeInferenceError] K input must be a one-dimensional tensor
of size 1.`，而鸿蒙用的 1.16.3 能加载。图本身是合规的——onnx 形状推断给出
`/Gather_output_0` rank=1 dims=[1]——所以这是新版运行时在自身图变换后重新校验时的差异，
不是模型缺陷。

改什么：`/TopK_3` 的 K 原本由 `Gather(Shape(/Where_13_output_0), [1])` 算出。
`/Where_13_output_0` 的形状是静态的 `[1, 188]`（188 即交付清单的 spkcacheLen），所以这个 K
在编译期就等于 188。本脚本把它替换成 initializer `int64[1] = [188]`，并删掉随之悬空的
`/Shape`、`/Gather`、`/Constant_80` 三个节点。

语义等价性由同目录的 verify 步骤保证：改前改后在同一组随机输入上逐字节比对全部输出。
算子、权重、其余结构一律不动。
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import numpy as np
import onnx
from onnx import helper, numpy_helper

TARGET_NODE = "/TopK_3"
DROPPED_NODES = ("/Shape", "/Gather", "/Constant_80")
K_NAME = "sortformer_spkcache_topk3_k"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def patch(source: Path, destination: Path) -> int:
    model = onnx.load(str(source))
    graph = model.graph

    topk = next((n for n in graph.node if n.name == TARGET_NODE), None)
    if topk is None:
        raise SystemExit(f"{TARGET_NODE} not found; the delivered graph changed")
    if len(topk.input) != 2:
        raise SystemExit(f"{TARGET_NODE} has {len(topk.input)} inputs, expected 2")

    data_name = topk.input[0]
    inferred = onnx.shape_inference.infer_shapes(model, strict_mode=False)
    shapes = {vi.name: vi for vi in list(inferred.graph.value_info) + list(inferred.graph.input)}
    info = shapes.get(data_name)
    if info is None:
        raise SystemExit(f"no inferred shape for {data_name}")
    dims = [d.dim_value if d.HasField("dim_value") else None for d in info.type.tensor_type.shape.dim]
    axis = next((a.i for a in topk.attribute if a.name == "axis"), -1)
    if axis < 0:
        axis += len(dims)
    if dims[axis] is None:
        raise SystemExit(f"{data_name} axis {axis} is dynamic; K cannot be made constant")
    k = int(dims[axis])

    # 每个被删节点的输出只有被删集合内的节点或该 TopK 在用，确认后再删。
    survivors = [n for n in graph.node if n.name not in DROPPED_NODES]
    dropped_outputs = {o for n in graph.node if n.name in DROPPED_NODES for o in n.output}
    for node in survivors:
        if node.name == TARGET_NODE:
            continue
        overlap = dropped_outputs.intersection(node.input)
        if overlap:
            raise SystemExit(f"{node.name} still consumes {sorted(overlap)}")
    if dropped_outputs.intersection(o.name for o in graph.output):
        raise SystemExit("a dropped node feeds a graph output")

    graph.initializer.append(
        numpy_helper.from_array(np.array([k], dtype=np.int64), name=K_NAME),
    )
    topk.input[1] = K_NAME
    del graph.node[:]
    graph.node.extend(survivors)

    onnx.checker.check_model(model)
    onnx.shape_inference.infer_shapes(model, strict_mode=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, str(destination))
    return k


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    before = sha256(args.source)
    k = patch(args.source, args.destination)
    print(f"K  = {k}  (was Gather(Shape(...), [1]))")
    print(f"源  {before}  {args.source}")
    print(f"产物 {sha256(args.destination)}  {args.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
