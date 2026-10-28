#!/usr/bin/env python3
"""把本地签名材料装进隔离工作区的 build-profile.json5。

签名口令只存在于 .secure/ 下的配置里，不进仓库；这里只写进工作区的构建配置，
工作区用完即删。仓库里的 build-profile 的 signingConfigs 恒为空数组，由各出包
流程在自己的工作区里注入 —— 所以本脚本只应指向工作区副本。
"""
import argparse
import json
from pathlib import Path

REQUIRED = ("certpath", "keyAlias", "keyPassword", "profile", "signAlg",
            "storeFile", "storePassword")
CONFIG_NAME = "default"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-profile", required=True, type=Path)
    parser.add_argument("--signing-config", required=True, type=Path)
    args = parser.parse_args()

    material = json.loads(args.signing_config.read_text(encoding="utf-8"))
    missing = [key for key in REQUIRED if not material.get(key)]
    if missing:
        raise SystemExit(f"[ERROR] 签名配置缺少字段: {missing}")
    for key in ("certpath", "profile", "storeFile"):
        path = Path(material[key]).expanduser()
        if not path.is_file():
            raise SystemExit(f"[ERROR] 签名材料不存在: {key} -> {path}")

    try:
        profile = json.loads(args.build_profile.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SystemExit(
            f"[ERROR] build-profile 不是可解析的 JSON（含 JSON5 特有语法？）: "
            f"{args.build_profile}: {error}") from error

    app = profile.get("app")
    if not isinstance(app, dict) or not isinstance(app.get("products"), list):
        raise SystemExit(f"[ERROR] build-profile 结构不符预期: {args.build_profile}")

    app["signingConfigs"] = [{
        "name": CONFIG_NAME,
        "type": "HarmonyOS",
        "material": {key: str(Path(material[key]).expanduser()) if key in
                     ("certpath", "profile", "storeFile") else material[key]
                     for key in REQUIRED},
    }]
    for product in app["products"]:
        product["signingConfig"] = CONFIG_NAME

    args.build_profile.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] 工作区签名配置已装入（{len(app['products'])} 个 product）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
