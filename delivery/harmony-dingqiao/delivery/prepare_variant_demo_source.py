#!/usr/bin/env python3
"""清理交付用的 demo 源码：剥掉只在内部模块里存在的依赖。

交付的源码只随附公共的自包含 amphion_dingqiao.har，客户没有 amphion_police
（它是该 HAR 的内部依赖）。源码里若还有 `from 'amphion_police'`，客户按文档独立
构建会在 Cannot find module 处失败 —— 0.3.24 的「修复三」就是这个缺陷。

这里按裸模块导入逐个核查，而不是只查某个已知模块名；并把只用于内部诊断的
SdkSelfTest 整体移除（它引用内部模块，且不属于客户示例）。
"""
import argparse
import re
import sys
from pathlib import Path

INTERNAL_MODULES = ("amphion_police",)
DROP_FILES = ("entry/src/main/ets/util/SdkSelfTest.ets",)
IMPORT_RE = re.compile(r"""\bfrom\s+['"]([A-Za-z_][A-Za-z0-9_]*)['"]""")
SHIPPED_MODULES = {"amphion_dingqiao", "amphion_asr"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo-source", required=True, type=Path)
    args = parser.parse_args()
    demo = args.demo_source / "samples/dingqiao-demo"
    if not demo.is_dir():
        raise SystemExit(f"[ERROR] 不是 demo 源码目录: {args.demo_source}")

    removed = []
    for relative in DROP_FILES:
        path = demo / relative
        if path.is_file():
            path.unlink()
            removed.append(relative)
    # 移除后仍可能有别处引用这些文件，顺带清掉对它们的 import。
    stem = {Path(r).stem for r in DROP_FILES}
    for source in demo.rglob("*.ets"):
        text = source.read_text(encoding="utf-8")
        kept = [l for l in text.split("\n")
                if not (l.lstrip().startswith("import ")
                        and any(f"/{s}'" in l or f"/{s}\"" in l for s in stem))]
        if len(kept) != len(text.split("\n")):
            source.write_text("\n".join(kept), encoding="utf-8")

    offenders = []
    for source in list(demo.rglob("*.ets")) + list(demo.rglob("*.ts")):
        for module in IMPORT_RE.findall(source.read_text(encoding="utf-8")):
            if module in INTERNAL_MODULES or (
                    module.startswith("amphion_") and module not in SHIPPED_MODULES):
                offenders.append(f"{source.relative_to(demo)} -> {module}")
    if offenders:
        print("[ERROR] 交付源码仍引用未随附的模块:", file=sys.stderr)
        for line in offenders:
            print(f"    {line}", file=sys.stderr)
        return 1
    print(f"[OK] 交付源码依赖自洽（移除 {len(removed)} 个内部诊断文件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
