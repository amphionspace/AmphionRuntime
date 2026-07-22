#!/usr/bin/env bash
# Issue the generic HarmonyOS ASR evaluation license: four calendar months,
# ASR-only, with no application, certificate, install-tier, or device binding.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
VENV="$ROOT/tools/license/.venv"
PRIVATE_KEY="${AMPHION_LICENSE_PRIVATE_KEY:-$ROOT/.secure/amphion-license-private.pem}"
OUT="${1:-$ROOT/../delivery/amphion-harmony-asr-eval.lic}"
source "$ROOT/asr/tools/license/ensure_python.sh"

[[ -f "$PRIVATE_KEY" ]] || { echo "license private key not found: $PRIVATE_KEY" >&2; exit 1; }
ensure_license_python "$VENV" "$ROOT/tools/license/requirements.txt"
PYTHON="$VENV/bin/python"

ISSUED="$(date +%Y-%m-%d)"
EXPIRES="$($PYTHON - "$ISSUED" <<'PY'
import calendar
import sys
from datetime import date

issued = date.fromisoformat(sys.argv[1])
month_index = issued.month - 1 + 4
year = issued.year + month_index // 12
month = month_index % 12 + 1
day = min(issued.day, calendar.monthrange(year, month)[1])
print(date(year, month, day).isoformat())
PY
)"

mkdir -p "$(dirname "$OUT")"
"$PYTHON" "$ROOT/tools/license/issue_license.py" \
  --private-key "$PRIVATE_KEY" \
  --customer "Amphion HarmonyOS ASR Evaluation" \
  --license-id "HARMONY-ASR-EVAL-$(date +%Y%m%d)" \
  --issued "$ISSUED" \
  --expires "$EXPIRES" \
  --device-id-salt-id "" \
  --features ASR \
  --out "$OUT"

echo "[ok] generic HarmonyOS ASR license: issued=$ISSUED expires=$EXPIRES app=unbound device=unbound"
