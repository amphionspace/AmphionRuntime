#!/usr/bin/env python3
"""兼容入口：统一 license 工具已迁移到 tools/license/。"""
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
runpy.run_path(str(ROOT / "tools/license/issue_license.py"), run_name="__main__")
