#!/usr/bin/env python3
"""把警务后处理资产从隔离构建工作区裁掉，只留解码期热词表。

用于「四川话 / 无警务后处理」交付包：后处理既不执行，其 FST 与 LAC 人名模型
也不进 HAP（约 36 MB，其中 LAC encoder 占 30 MB）。

必须保留 hotwords.json —— 它是 PoliceEngineConfig.effectiveHotwords 的唯一数据源，
而该包仍保留解码期热词偏置。裁剪后在 manifest 里打上 variant 标记，SDK 据此
判定后处理不可用（见 PoliceAssets.postprocessingAvailable）。

只能作用于隔离构建工作区，不得指向仓库本体。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

KEEP = frozenset({"hotwords.json", "manifest.json"})
VARIANT = "hotwords-only"
RELATIVE_ROOT = Path("asr/harmony/sdk-police/src/main/resources/rawfile/amphion-police")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def trim(root: Path) -> int:
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"[ERROR] 警务资产 manifest 不存在: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files")
    if not isinstance(files, dict) or "hotwords.json" not in files:
        raise SystemExit("[ERROR] 警务资产 manifest 缺少 files/hotwords.json")
    if manifest.get("variant") == VARIANT:
        print("[INFO] 警务资产已是裁剪态，跳过")
        return 0

    hotwords = root / "hotwords.json"
    if not hotwords.is_file():
        raise SystemExit(f"[ERROR] 热词表不存在，无法裁剪: {hotwords}")
    actual = sha256_of(hotwords)
    if actual != files["hotwords.json"]:
        raise SystemExit(
            f"[ERROR] 热词表指纹与 manifest 不符: {actual} != {files['hotwords.json']}")

    removed_bytes = 0
    removed_files = 0
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir():
            if not any(path.iterdir()):
                path.rmdir()
            continue
        if path.relative_to(root).as_posix() in KEEP:
            continue
        removed_bytes += path.stat().st_size
        removed_files += 1
        path.unlink()

    survivors = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    if survivors != sorted(KEEP):
        raise SystemExit(f"[ERROR] 裁剪后残留文件不符预期: {survivors}")

    manifest["files"] = {"hotwords.json": files["hotwords.json"]}
    manifest["variant"] = VARIANT
    manifest["variant_note"] = (
        "后处理资产（LAC 人名、术语/派出所/车牌 FST 与词典）已移除；"
        "仅保留解码期热词表。后处理在运行时不可用。")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")

    print(f"[OK] 警务后处理资产已裁剪: 移除 {removed_files} 个文件, "
          f"{removed_bytes / 1048576:.1f} MB；保留 hotwords.json "
          f"({manifest.get('hotword_counts')})")
    return removed_bytes


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path,
                        help="隔离构建工作区的 repo 根目录")
    args = parser.parse_args(argv)
    root = (args.repo_root / RELATIVE_ROOT).resolve()
    if not root.is_dir():
        raise SystemExit(f"[ERROR] 警务资产目录不存在: {root}")
    trim(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
