#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 SentencePiece byte-level BPE 的 `.model`（Google protobuf）导出成 sherpa-onnx
自带 ssentencepiece 库期望的 `.vocab`（文本 `<token> <score>` 两列）。

为什么不能直接打 .model：
  sherpa-onnx 没有引入 Google sentencepiece C++（因 protobuf 依赖问题），自己写了
  一个简化版 byte-level SentencePiece 编码器，只认两列空格分隔的纯文本词表；
  喂 protobuf 进去会在 darts trie build 阶段直接 SIGSEGV。

参考 sherpa-onnx 官方脚本 `scripts/export_bpe_vocab.py`：
  https://github.com/k2-fsa/sherpa-onnx/blob/master/scripts/export_bpe_vocab.py

用法：
  python tools/asr/09_export_bbpe_vocab.py \
    tools/asr/demo-model/zipformer_L_zh_en/bbpe.model \
    tools/asr/demo-model/zipformer_L_zh_en/bbpe.vocab

  或者批量：
  python tools/asr/09_export_bbpe_vocab.py --batch tools/asr/demo-model
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import sentencepiece as spm
except ImportError:
    print(
        "缺 sentencepiece。建议建临时 venv：\n"
        "  python3 -m venv .venv-tools && .venv-tools/bin/pip install sentencepiece\n"
        "  .venv-tools/bin/python tools/asr/09_export_bbpe_vocab.py ...",
        file=sys.stderr,
    )
    sys.exit(1)


def export_one(model_path: Path, vocab_path: Path) -> None:
    sp = spm.SentencePieceProcessor()
    sp.load(str(model_path))
    with vocab_path.open("w", encoding="utf-8") as fout:
        for i in range(sp.get_piece_size()):
            piece = sp.id_to_piece(i)
            score = sp.get_score(i)
            fout.write(f"{piece} {score}\n")
    print(f"[OK] {model_path} -> {vocab_path}  ({sp.get_piece_size()} pieces)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch", type=Path, default=None,
                        help="批量模式：遍历该目录下所有 zipformer_*/bbpe.model 并产出同目录 bbpe.vocab")
    parser.add_argument("inputs", nargs="*", type=Path,
                        help="单文件模式：<bbpe.model> <bbpe.vocab>")
    args = parser.parse_args()

    if args.batch is not None:
        if not args.batch.is_dir():
            print(f"[FAIL] batch 目录不存在：{args.batch}", file=sys.stderr)
            return 1
        any_done = False
        for model_path in sorted(args.batch.glob("zipformer_*/bbpe.model")):
            vocab_path = model_path.with_suffix(".vocab")
            export_one(model_path, vocab_path)
            any_done = True
        if not any_done:
            print(f"[WARN] {args.batch} 下没找到 zipformer_*/bbpe.model", file=sys.stderr)
            return 1
        return 0

    if len(args.inputs) != 2:
        parser.error("非 batch 模式需要两个参数：<bbpe.model> <bbpe.vocab>")
    model_path, vocab_path = args.inputs
    if not model_path.is_file():
        print(f"[FAIL] 输入不存在：{model_path}", file=sys.stderr)
        return 1
    export_one(model_path, vocab_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
