"""按角色解析模型文件名，兼容 ONNX / ORT 与各种量化命名。

同一个模型在不同环节有不同文件名：上游候选包是 encoder.int8.onnx + decoder.onnx +
joiner.onnx，Harmony 载体转换后是 encoder.int8.ort + decoder.ort + joiner.int8.ort，
安卓载体又可能是未量化的 encoder.onnx。评测器不该要求调用方先建软链接对齐命名 ——
按角色给候选名列表，取第一个存在的。
"""
import os

CANDIDATES = {
    "tokens": ["tokens.txt"],
    "encoder": ["encoder.onnx", "encoder.int8.onnx", "encoder.ort", "encoder.int8.ort"],
    "decoder": ["decoder.onnx", "decoder.int8.onnx", "decoder.ort", "decoder.int8.ort"],
    "joiner": ["joiner.onnx", "joiner.int8.onnx", "joiner.ort", "joiner.int8.ort"],
    "bpe_vocab": ["bbpe.vocab"],
}


def resolve(models_dir, role):
    for name in CANDIDATES[role]:
        path = os.path.join(models_dir, name)
        if os.path.exists(path):
            return path
    raise SystemExit(
        f"[ERROR] {models_dir} 下找不到 {role}，试过: {', '.join(CANDIDATES[role])}")


def transducer_paths(models_dir):
    """返回 OnlineRecognizer.from_transducer 需要的四个路径 + bbpe 词表。"""
    return {role: resolve(models_dir, role) for role in CANDIDATES}
