#!/usr/bin/env bash
# DevEco CLI entry point that always selects standalone Command Line Tools.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/harmony_env.sh"
if ! command -v devecocli >/dev/null; then
  echo '[ERROR] Install DevEco CLI: npm install -g @deveco/deveco-cli@1.3.0-stable' >&2
  exit 1
fi
exec devecocli "$@"
