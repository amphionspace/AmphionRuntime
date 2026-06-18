#!/usr/bin/env bash
# 从 asr/android 目录调用项目根下的批量评测脚本。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
exec bash "$ROOT/test_data/plate_enhance/run_kespeech_batch.sh" "$@"
