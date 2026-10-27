#!/usr/bin/env python3
"""改写隔离构建工作区里 demo 应用的 bundleName 与显示名。

bundleName 绑定在 HarmonyAppProvision profile 里，所以换 bundleName 必须同时换成
对应 bundleName 的签名材料，否则签名校验不通过。换 bundleName 的用途是让变体包与
基线包在同一台设备上共存 —— 同 bundleName 的两个 HAP 会互相覆盖。

只能作用于隔离构建工作区，不得指向仓库本体。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

LABEL_KEYS = ("app_name", "EntryAbility_label")


def rewrite_bundle(project: Path, bundle: str) -> None:
    path = project / "AppScope/app.json5"
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(r'("bundleName"\s*:\s*")[^"]+(")',
                             lambda m: m.group(1) + bundle + m.group(2), text, count=1)
    if count != 1:
        raise SystemExit(f"[ERROR] 未在 {path} 找到 bundleName")
    path.write_text(updated, encoding="utf-8")
    print(f"[OK] bundleName -> {bundle}")


def rewrite_version_name(project: Path, version_name: str) -> None:
    """变体包的 versionName 要与交付版本号一致，否则打包的版本一致性校验会失败。

    versionCode 不动：它按 minor*100+patch 推进，变体与基线共用同一数字版本，
    变体标识只体现在 versionName 的后缀上。
    """
    path = project / "AppScope/app.json5"
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(r'("versionName"\s*:\s*")[^"]+(")',
                             lambda m: m.group(1) + version_name + m.group(2), text, count=1)
    if count != 1:
        raise SystemExit(f"[ERROR] 未在 {path} 找到 versionName")
    path.write_text(updated, encoding="utf-8")
    print(f"[OK] versionName -> {version_name}")


def rewrite_label(project: Path, label: str) -> None:
    path = project / "AppScope/resources/base/element/string.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    hit = 0
    for entry in data.get("string", []):
        if entry.get("name") in LABEL_KEYS:
            entry["value"] = label
            hit += 1
    if hit == 0:
        raise SystemExit(f"[ERROR] 未在 {path} 找到 {' / '.join(LABEL_KEYS)}")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] 显示名 -> {label}（{hit} 处）")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path,
                        help="隔离工作区里的 delivery/harmony-dingqiao 目录")
    parser.add_argument("--bundle-name", default="")
    parser.add_argument("--label", default="")
    parser.add_argument("--version-name", default="")
    args = parser.parse_args(argv)
    if not (args.project / "AppScope/app.json5").is_file():
        raise SystemExit(f"[ERROR] 不是 demo 工程目录: {args.project}")
    if args.bundle_name:
        rewrite_bundle(args.project, args.bundle_name)
    if args.label:
        rewrite_label(args.project, args.label)
    if args.version_name:
        rewrite_version_name(args.project, args.version_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
