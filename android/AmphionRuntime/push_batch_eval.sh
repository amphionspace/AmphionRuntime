#!/usr/bin/env bash
# 从 android/AmphionRuntime 目录调用项目根下的 push 脚本。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
exec bash "$ROOT/test_data/plate_enhance/push_batch_eval.sh" "$@"
