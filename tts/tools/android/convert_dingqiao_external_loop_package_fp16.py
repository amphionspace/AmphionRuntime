#!/usr/bin/env python3
"""Convert the Dingqiao external-loop ONNX package to shared-policy mixed FP16.

The source package is copied to a separate output directory first. The shared
LITS precision policy controls the training precision, public IO dtype, FP16
initializer conversion, and FP32 operator block list.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
from onnxruntime.transformers.float16 import DEFAULT_OP_BLOCK_LIST, convert_float_to_float16


ROOT = Path(__file__).resolve().parents[3]
PACKAGE_NAME = "dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop"
DEFAULT_INPUT_DIR = ROOT / "tts" / "android" / "external-resources" / "tts" / PACKAGE_NAME / "0.1.0"
DEFAULT_OUTPUT_DIR = ROOT / "tts" / "android" / "build" / "fp16-experiments" / PACKAGE_NAME / "0.1.0"
DEFAULT_POLICY_CONFIG = (
    ROOT / "tts" / "training" / "dingqiao_lits" / "configs" / "precision" / "mixed_fp16.yaml"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--policy-config",
        type=Path,
        default=DEFAULT_POLICY_CONFIG,
        help="Shared LITS precision policy used by training and ONNX conversion.",
    )
    parser.add_argument(
        "--op-block-list",
        default=None,
        help="Override policy ONNX op block list as a comma-separated string.",
    )
    parser.add_argument(
        "--fp16-io",
        action="store_true",
        help="Convert public graph inputs/outputs to FP16 too; default keeps IO as FP32.",
    )
    return parser.parse_args()


def load_policy(path: Path) -> dict[str, object]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to read the shared precision policy.") from exc

    policy = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(policy, dict):
        raise ValueError(f"precision policy must be a mapping: {path}")
    onnx_policy = policy.get("onnx")
    if not isinstance(onnx_policy, dict):
        raise ValueError(f"precision policy has no onnx mapping: {path}")
    if policy.get("trainer_precision") != "16-mixed":
        raise ValueError(
            "This converter produces FP16 ONNX and requires trainer_precision=16-mixed; "
            f"got {policy.get('trainer_precision')!r} from {path}"
        )
    block_list = onnx_policy.get("op_block_list")
    if not isinstance(block_list, list) or not all(isinstance(item, str) for item in block_list):
        raise ValueError(f"onnx.op_block_list must be a list of strings: {path}")
    for key in ("keep_io_types", "force_fp16_initializers"):
        if not isinstance(onnx_policy.get(key), bool):
            raise ValueError(f"onnx.{key} must be boolean: {path}")
    return policy


def resolve_op_block_list(policy: dict[str, object], override: str | None) -> list[str]:
    if override is not None:
        return [item.strip() for item in override.split(",") if item.strip()]
    onnx_policy = policy["onnx"]
    assert isinstance(onnx_policy, dict)
    return list(onnx_policy["op_block_list"])


def sort_graph_nodes(graph: onnx.GraphProto) -> None:
    available = {item.name for item in graph.input}
    available.update(item.name for item in graph.initializer)
    remaining = list(graph.node)
    ordered: list[onnx.NodeProto] = []
    while remaining:
        ready: list[onnx.NodeProto] = []
        waiting: list[onnx.NodeProto] = []
        for node in remaining:
            if all(not name or name in available for name in node.input):
                ready.append(node)
            else:
                waiting.append(node)
        if not ready:
            unresolved = [(node.name, list(node.input)) for node in waiting[:3]]
            raise RuntimeError(f"unable to topologically sort converted graph: {unresolved}")
        ordered.extend(ready)
        for node in ready:
            available.update(name for name in node.output if name)
        remaining = waiting
    del graph.node[:]
    graph.node.extend(ordered)


def concrete_shape(shape: list[object]) -> list[int]:
    values: list[int] = []
    for index, value in enumerate(shape):
        if isinstance(value, int) and value > 0:
            values.append(value)
            continue
        name = str(value).lower()
        if "batch" in name:
            values.append(1)
        elif "channel" in name:
            values.append(100)
        elif "speaker" in name:
            values.append(64)
        elif "frame" in name or "length" in name or "sample" in name:
            values.append(32)
        elif index == 0:
            values.append(1)
        else:
            values.append(32)
    return values


def random_inputs(session: ort.InferenceSession) -> dict[str, np.ndarray]:
    inputs: dict[str, np.ndarray] = {}
    for index, info in enumerate(session.get_inputs()):
        shape = concrete_shape(list(info.shape))
        if info.type == "tensor(int64)":
            if "length" in info.name.lower():
                values = np.asarray([shape[-1]], dtype=np.int64)
            elif "speaker" in info.name.lower():
                values = np.zeros(shape, dtype=np.int64)
            else:
                values = np.arange(np.prod(shape), dtype=np.int64).reshape(shape) % 128
        elif info.type == "tensor(int32)":
            values = np.zeros(shape, dtype=np.int32)
        elif info.type == "tensor(bool)":
            values = np.zeros(shape, dtype=np.bool_)
        else:
            rng = np.random.default_rng(20260717 + index)
            values = rng.standard_normal(shape).astype(np.float32)
            if info.name == "t":
                values.fill(0.5)
            elif info.name == "dt":
                values.fill(0.5)
        inputs[info.name] = values
    return inputs


def adapt_inputs(inputs: dict[str, np.ndarray], session: ort.InferenceSession) -> dict[str, np.ndarray]:
    adapted = {}
    for info in session.get_inputs():
        value = inputs[info.name]
        if info.type == "tensor(float16)" and value.dtype == np.float32:
            value = value.astype(np.float16)
        adapted[info.name] = value
    return adapted


def output_metrics(base: list[np.ndarray], converted: list[np.ndarray]) -> dict[str, object]:
    result: dict[str, object] = {}
    for index, (left, right) in enumerate(zip(base, converted)):
        left = np.asarray(left)
        right = np.asarray(right)
        if np.issubdtype(left.dtype, np.floating):
            diff = np.abs(left.astype(np.float32) - right.astype(np.float32))
            result[str(index)] = {
                "shape": list(left.shape),
                "mean_abs": float(diff.mean()),
                "max_abs": float(diff.max()),
                "rms": float(np.sqrt(np.mean(diff * diff))),
            }
        else:
            result[str(index)] = {
                "shape": list(left.shape),
                "equal": bool(np.array_equal(left, right)),
            }
    return result


def effective_block_list(op_block_list: list[str]) -> list[str] | None:
    if op_block_list == ["__default__"]:
        return None
    return list(dict.fromkeys([
        *(DEFAULT_OP_BLOCK_LIST if "__default__" in op_block_list else []),
        *(item for item in op_block_list if item != "__default__"),
    ]))


def convert_one(
    source: Path,
    target: Path,
    op_block_list: list[str],
    keep_io_types: bool,
    force_fp16_initializers: bool,
) -> dict[str, object]:
    model = onnx.load(str(source))
    converted = convert_float_to_float16(
        model,
        keep_io_types=keep_io_types,
        op_block_list=effective_block_list(op_block_list),
        force_fp16_initializers=force_fp16_initializers,
    )
    sort_graph_nodes(converted.graph)
    onnx.save(converted, str(target))
    onnx.checker.check_model(str(target))

    base_session = ort.InferenceSession(str(source), providers=["CPUExecutionProvider"])
    converted_session = ort.InferenceSession(str(target), providers=["CPUExecutionProvider"])
    inputs = random_inputs(base_session)
    base_outputs = base_session.run(None, inputs)
    converted_outputs = converted_session.run(None, adapt_inputs(inputs, converted_session))
    return {
        "source": str(source),
        "target": str(target),
        "source_bytes": source.stat().st_size,
        "target_bytes": target.stat().st_size,
        "inputs": [item.name for item in base_session.get_inputs()],
        "outputs": [item.name for item in base_session.get_outputs()],
        "metrics": output_metrics(base_outputs, converted_outputs),
    }


def update_manifest(
    output_dir: Path,
    reports: list[dict[str, object]],
    op_block_list: list[str],
    keep_io_types: bool,
    force_fp16_initializers: bool,
    policy: dict[str, object],
) -> None:
    manifest_path = output_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["precision"] = "mixed_fp16_io_fp32" if keep_io_types else "fp16_io"
    manifest["fp16_converter"] = "onnxruntime.transformers.float16"
    manifest["fp16_force_initializers"] = force_fp16_initializers
    manifest["fp16_keep_io_types"] = keep_io_types
    manifest["fp16_op_block_list"] = op_block_list
    manifest["precision_policy"] = policy["name"]
    manifest["training_precision"] = policy["trainer_precision"]
    manifest["precision_alignment"] = "shared_policy_fp16_export"
    manifest["streaming_mel_cache_len"] = 16
    manifest["fp16_conversion"] = [Path(item["target"]).name for item in reports]
    for item in manifest.get("files", []):
        path = output_dir / item["name"]
        if path.is_file():
            item["size_bytes"] = path.stat().st_size
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    args.policy_config = args.policy_config.resolve()
    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()
    policy = load_policy(args.policy_config)
    if not (input_dir / "manifest.json").is_file():
        raise FileNotFoundError(f"manifest not found: {input_dir / 'manifest.json'}")
    if output_dir.exists():
        shutil.rmtree(output_dir)
    shutil.copytree(input_dir, output_dir)

    op_block_list = resolve_op_block_list(policy, args.op_block_list)
    onnx_policy = policy["onnx"]
    assert isinstance(onnx_policy, dict)
    keep_io_types = bool(onnx_policy["keep_io_types"]) and not args.fp16_io
    force_fp16_initializers = bool(onnx_policy["force_fp16_initializers"])
    manifest = json.loads((input_dir / "manifest.json").read_text(encoding="utf-8"))
    model_names = [item["name"] for item in manifest.get("files", []) if item["name"].endswith(".onnx")]
    reports = []
    for name in model_names:
        source = input_dir / name
        if not source.is_file():
            raise FileNotFoundError(f"manifest model not found: {source}")
        reports.append(
            convert_one(
                source,
                output_dir / name,
                op_block_list,
                keep_io_types=keep_io_types,
                force_fp16_initializers=force_fp16_initializers,
            )
        )
        print(f"converted={name}")

    update_manifest(
        output_dir,
        reports,
        op_block_list,
        keep_io_types=keep_io_types,
        force_fp16_initializers=force_fp16_initializers,
        policy=policy,
    )
    report_path = output_dir / "fp16_conversion_report.json"
    report_path.write_text(json.dumps({
        "converter": "onnxruntime.transformers.float16",
        "force_fp16_initializers": force_fp16_initializers,
        "io_types": "float32_preserved" if keep_io_types else "float16",
        "keep_io_types": keep_io_types,
        "op_block_list": op_block_list,
        "policy_config": str(args.policy_config),
        "precision_policy": policy["name"],
        "training_precision": policy["trainer_precision"],
        "precision_alignment": "shared_policy_fp16_export",
        "models": reports,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"output_dir={output_dir}")
    print(f"report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
