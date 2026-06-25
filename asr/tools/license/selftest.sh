#!/usr/bin/env bash
# 兼容入口：统一 license 工具已迁移到 tools/license/。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
bash "$ROOT/tools/license/selftest.sh"
