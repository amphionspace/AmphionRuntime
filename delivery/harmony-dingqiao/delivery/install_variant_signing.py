#!/usr/bin/env python3
"""把本地签名材料装进隔离工作区的 build-profile.json5。

签名口令只存在于 .secure/ 下的配置里，不进仓库；这里只把它写进工作区的构建
配置，工作区用完即删。
"""
import argparse
import json
import re
from pathlib import Path

REQUIRED = ("certpath", "keyAlias", "keyPassword", "profile", "signAlg",
            "storeFile", "storePassword")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-profile", required=True, type=Path)
    parser.add_argument("--signing-config", required=True, type=Path)
    args = parser.parse_args()
    material = json.loads(args.signing_config.read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED if not material.get(k)]
    if missing:
        raise SystemExit(f"[ERROR] 签名配置缺少字段: {missing}")
    for key in ("certpath", "profile", "storeFile"):
        if not Path(material[key]).is_file():
            raise SystemExit(f"[ERROR] 签名材料不存在: {material[key]}")

    text = args.build_profile.read_text(encoding="utf-8")
    block = re.search(r"signingConfigs\s*:\s*\[(.*?)\]\s*,", text, re.S)
    if block is None:
        raise SystemExit(f"[ERROR] build-profile 里找不到 signingConfigs: {args.build_profile}")
    entries = ",\n".join(f"          {k}: '{material[k]}'" for k in REQUIRED)
    replacement = (
        "signingConfigs: [\n"
        "      {\n"
        "        name: 'default',\n"
        "        type: 'HarmonyOS',\n"
        "        material: {\n" + entries + ",\n"
        "        },\n"
        "      },\n"
        "    ],"
    )
    args.build_profile.write_text(
        text[:block.start()] + replacement + text[block.end():], encoding="utf-8")
    print("[OK] 隔离工作区的签名配置已装入")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
