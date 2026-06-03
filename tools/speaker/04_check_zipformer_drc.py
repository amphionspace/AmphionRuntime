#!/usr/bin/env python3
"""检查流式 zipformer encoder 是否启用 dynamic right-context (DRC) 训练。

为什么要查（对应 plan 第 4 节"已知未知 1"）：
  - sherpa-onnx 流式 onnx 模型整段推理时 WER 锁定在流式模型上限
  - ACL 2025 industry track 论文 (arxiv 2506.14434) 提出训练时加 dynamic right-context，
    推理时调大 right-context frames 数能逼近非流式精度
  - 模型是否带这个 trick，决定"再加非流式模型"是不是有意义

判定规则（启发式）：
  1. encoder.onnx 的 metadata_props 里若出现以下任一 key，视为启用 DRC：
     right_context_len / right_context_frames / dynamic_right_context / use_drc / drc
  2. metadata.model_type 字符串若包含 "drc" 或 "dynamic"，视为启用
  3. encoder 输入 shape 里若有名为 right_context_* 的 tensor 且 dim 不是 0/常数，
     可作为辅助证据
  4. 否则视为"未启用"，整段推理 WER = 流式上限

输出：
  - tools/speaker/results/zipformer_drc_check.json，含全部 metadata、判定、建议下一步

为什么不直接用 sherpa-onnx 读：
  - sherpa-onnx 当前版本（v1.13.1）只读 left_context_len，不读 right_context_*；
    用 onnxruntime 直接读 ModelProto.metadata_props 才能拿到全部字段
  - 本脚本只读 metadata，不实例化 session，对环境要求低（不需要 sherpa-onnx 包）

用法：
  python tools/speaker/04_check_zipformer_drc.py \
    --asr-model-dir tools/asr/demo-model/asr-streaming-zipformer-zh-en-1.0.0/ \
    --out tools/speaker/results/zipformer_drc_check.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


DRC_KEY_HINTS = (
    "right_context_len",
    "right_context_frames",
    "dynamic_right_context",
    "use_drc",
    "drc",
)
DRC_MODEL_TYPE_HINTS = ("drc", "dynamic")


def load_metadata(encoder_path: Path) -> Dict[str, Any]:
    try:
        import onnx
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "需要 `pip install onnx` 来读 metadata_props（不需要 onnxruntime）"
        ) from e

    model = onnx.load(str(encoder_path), load_external_data=False)
    meta_props = {p.key: p.value for p in model.metadata_props}

    inputs: List[Dict[str, Any]] = []
    for inp in model.graph.input:
        shape = []
        try:
            for d in inp.type.tensor_type.shape.dim:
                if d.dim_param:
                    shape.append(d.dim_param)
                elif d.HasField("dim_value"):
                    shape.append(int(d.dim_value))
                else:
                    shape.append("?")
        except Exception:
            shape = ["<unknown>"]
        inputs.append({"name": inp.name, "shape": shape})

    outputs: List[Dict[str, Any]] = []
    for out in model.graph.output:
        shape = []
        try:
            for d in out.type.tensor_type.shape.dim:
                if d.dim_param:
                    shape.append(d.dim_param)
                elif d.HasField("dim_value"):
                    shape.append(int(d.dim_value))
                else:
                    shape.append("?")
        except Exception:
            shape = ["<unknown>"]
        outputs.append({"name": out.name, "shape": shape})

    return {
        "metadata_props": meta_props,
        "inputs": inputs,
        "outputs": outputs,
        "ir_version": model.ir_version,
        "opset_imports": [
            {"domain": op.domain or "ai.onnx", "version": op.version}
            for op in model.opset_import
        ],
    }


def judge_drc(meta_props: Dict[str, str], inputs: List[Dict[str, Any]]) -> Dict[str, Any]:
    matched_keys = [k for k in meta_props if k.lower() in DRC_KEY_HINTS]
    model_type = meta_props.get("model_type", "")
    matched_model_type = [
        h for h in DRC_MODEL_TYPE_HINTS if h in model_type.lower()
    ]
    matched_input_names = [
        i["name"] for i in inputs if "right_context" in i["name"].lower()
    ]

    # 至少命中一类
    drc_enabled = bool(matched_keys or matched_model_type or matched_input_names)

    return {
        "drc_enabled": drc_enabled,
        "matched_metadata_keys": matched_keys,
        "matched_model_type_hints": matched_model_type,
        "matched_input_names_with_right_context": matched_input_names,
        "model_type_value": model_type,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--asr-model-dir",
        type=Path,
        required=True,
        help="ASR modelDir，含 encoder.int8.onnx 或 encoder.onnx",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("tools/speaker/results/zipformer_drc_check.json"),
    )
    args = parser.parse_args()

    cands = [
        args.asr_model_dir / "encoder.int8.onnx",
        args.asr_model_dir / "encoder.onnx",
    ]
    encoder_path = next((p for p in cands if p.is_file()), None)
    if encoder_path is None:
        print(
            f"[ERROR] 未找到 encoder onnx：{cands}",
            file=sys.stderr,
        )
        return 2

    meta = load_metadata(encoder_path)
    judge = judge_drc(meta["metadata_props"], meta["inputs"])

    report = {
        "encoder_path": str(encoder_path),
        **meta,
        "drc_judgment": judge,
        "advice": (
            "已启用 DRC：可调大 right-context frames 数评估整段推理 WER 是否逼近非流式"
            if judge["drc_enabled"]
            else "未启用 DRC：整段推理 WER 锁定在流式上限；如业务对 WER 敏感，需要单独导出非流式模型"
        ),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    print("=" * 56)
    print(f"encoder         : {encoder_path}")
    print(f"model_type      : {judge['model_type_value']!r}")
    print(f"drc_enabled     : {judge['drc_enabled']}")
    if judge["matched_metadata_keys"]:
        print(f"  metadata keys : {judge['matched_metadata_keys']}")
    if judge["matched_model_type_hints"]:
        print(f"  type hints    : {judge['matched_model_type_hints']}")
    if judge["matched_input_names_with_right_context"]:
        print(f"  input names   : {judge['matched_input_names_with_right_context']}")
    print(f"advice          : {report['advice']}")
    print("=" * 56)
    print(f"\n[OK] full report -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
