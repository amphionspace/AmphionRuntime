#!/usr/bin/env bash
# Build the generic zh-en HarmonyOS ASR SDK-only delivery.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/pack_dingqiao_harmony_customer_delivery.sh" --sdk-only "$@"
