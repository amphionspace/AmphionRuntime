#!/usr/bin/env python3
"""把 CMake 的 node-addon-api FetchContent 指向已打补丁的本地源。

交叉编译工具链把 find_program 限制在 find-root 内，CMake 因此探不到系统 git
（表现为 GIT_VERSION_STRING=''），FetchContent 的 git 克隆必然失败。给它一个
现成的源目录就不需要 git 了。
"""
import argparse
from pathlib import Path

ANCHOR = "include(FetchContent)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cmake", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    args = parser.parse_args()
    text = args.cmake.read_text(encoding="utf-8")
    if ANCHOR not in text:
        raise SystemExit(f"[ERROR] 未找到 {ANCHOR}: {args.cmake}")
    override = (f'set(FETCHCONTENT_SOURCE_DIR_NODE_ADDON_API '
                f'"{args.source.resolve()}" CACHE PATH "" FORCE)\n')
    args.cmake.write_text(text.replace(ANCHOR, override + ANCHOR, 1), encoding="utf-8")
    print(f"[OK] node-addon-api 指向本地源: {args.source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
