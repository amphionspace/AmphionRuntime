#!/usr/bin/env python3
"""校验变体交付的验收证据，并返回可纳入包内的清单。

为什么证据绑定「源码提交」而不是「最终 ZIP 的哈希」：验收必须在组包前跑完，而组包
会产生新的 ZIP —— 用 ZIP 哈希绑定会形成循环。基线流程同样如此，其摘要开头即写明
「本摘要是组包前证据，不是最终 ZIP 的验收结论。最终 ZIP 的验收报告绑定其自身
SHA-256，另行外置」。本脚本因此只强校验提交一致，受测产物哈希作为信息项记录。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

SHA256_RE_LEN = 64
REQUIRED_KEYS = ("schema_version", "variant", "source_commit", "summary_sha256", "reports")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acceptance-dir", required=True, type=Path)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args(argv)

    root = args.acceptance_dir
    manifest_path = root / "acceptance-manifest.json"
    summary_path = root / "ACCEPTANCE-SUMMARY.md"
    for path in (manifest_path, summary_path):
        if not path.is_file():
            raise SystemExit(f"[ERROR] 验收证据缺少 {path.name}: {root}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED_KEYS if k not in manifest]
    if missing:
        raise SystemExit(f"[ERROR] 验收清单缺少字段: {missing}")
    if manifest["schema_version"] != 1:
        raise SystemExit(f"[ERROR] 验收清单 schema_version 必须为 1")
    if manifest["variant"] != args.variant:
        raise SystemExit(
            f"[ERROR] 验收证据的变体与本次出包不符: "
            f"{manifest['variant']} != {args.variant}")
    if manifest["source_commit"] != args.source_commit:
        raise SystemExit(
            f"[ERROR] 验收证据的源码提交与本次出包不符 —— 证据必须在同一提交上跑出来:\n"
            f"        证据: {manifest['source_commit']}\n"
            f"        出包: {args.source_commit}")

    actual_summary = sha256(summary_path)
    if manifest["summary_sha256"] != actual_summary:
        raise SystemExit(
            f"[ERROR] 摘要指纹与清单不符（摘要被改过？）:\n"
            f"        清单: {manifest['summary_sha256']}\n"
            f"        实际: {actual_summary}")

    reports = manifest["reports"]
    if not isinstance(reports, list) or not reports:
        raise SystemExit("[ERROR] 验收清单至少要有一份报告")
    for entry in reports:
        path = root / entry["path"]
        if not path.is_file():
            raise SystemExit(f"[ERROR] 验收报告缺失: {entry['path']}")
        actual = sha256(path)
        if entry["sha256"] != actual:
            raise SystemExit(
                f"[ERROR] 验收报告指纹不符: {entry['path']}\n"
                f"        清单: {entry['sha256']}\n        实际: {actual}")
        if entry.get("status") not in ("PASS", "MEASURED"):
            raise SystemExit(
                f"[ERROR] 验收报告 {entry['mode']} 的判定不是 PASS/MEASURED: "
                f"{entry.get('status')}")

    waived = manifest.get("waived_modes") or []
    for entry in waived:
        if not entry.get("reason"):
            raise SystemExit(f"[ERROR] 豁免模式 {entry.get('mode')} 未写原因")

    print(f"[OK] 验收证据有效：{len(reports)} 份报告，{len(waived)} 项豁免，"
          f"提交 {args.source_commit[:12]}")
    for entry in reports:
        print(f"     {entry['mode']:28s} {entry.get('status')}  {entry['sha256'][:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
