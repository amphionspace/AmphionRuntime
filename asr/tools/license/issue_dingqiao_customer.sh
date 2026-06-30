#!/usr/bin/env bash
# 为鼎桥正式设备白名单签发 amphion-license.lic。
#
# 环境变量：
#   DINGQIAO_TRIAL_MONTHS=2          试用月数（默认 2）
#   DINGQIAO_DEVICE_ID_FILE=...      设备 SN 清单（一行一个；默认 .secure/dingqiao_tiassistant_sn.txt）
#   DINGQIAO_LICENSE_FEATURES=ASR,TTS 授权能力；鼎桥客户默认 ASR,TTS，供 ASR 和 TTS 共用同一份 license
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
VENV="$ROOT/tools/license/.venv"
PRIVATE_KEY="${AMPHION_LICENSE_PRIVATE_KEY:-$ROOT/.secure/amphion-license-private.pem}"
OUT="${1:-$ROOT/../delivery/com.tdtech.tiassistant.lic}"
DEVICE_ID_FILE="${DINGQIAO_DEVICE_ID_FILE:-$ROOT/.secure/dingqiao_tiassistant_sn.txt}"
TRIAL_MONTHS="${DINGQIAO_TRIAL_MONTHS:-2}"
FEATURES="${DINGQIAO_LICENSE_FEATURES:-ASR,TTS}"

if [[ ! -f "$PRIVATE_KEY" ]]; then
  echo "私钥不存在: $PRIVATE_KEY" >&2
  exit 1
fi

if [[ ! -f "$DEVICE_ID_FILE" ]]; then
  echo "设备 SN 清单不存在: $DEVICE_ID_FILE" >&2
  exit 1
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q -r "$ROOT/tools/license/requirements.txt"
fi

ISSUED="$(date +%Y-%m-%d)"
EXPIRES="$("$VENV/bin/python" -c "
import calendar
from datetime import date
months = int('${TRIAL_MONTHS}')
d = date.today()
y = d.year + (d.month + months - 1) // 12
m = (d.month + months - 1) % 12 + 1
day = min(d.day, calendar.monthrange(y, m)[1])
print(f'{y:04d}-{m:02d}-{day:02d}')
")"

mkdir -p "$(dirname "$OUT")"
"$VENV/bin/python" "$ROOT/tools/license/issue_license.py" \
  --private-key "$PRIVATE_KEY" \
  --customer "TD Tech / Dingqiao" \
  --license-id "DINGQIAO-TDTECH-$(date +%Y%m)-001" \
  --issued "$ISSUED" \
  --expires "$EXPIRES" \
  --install-tier LE_100K \
  --features "$FEATURES" \
  --device-id-file "$DEVICE_ID_FILE" \
  --out "$OUT"

echo "[ok] wrote $OUT (trial ${TRIAL_MONTHS} month(s): issued=$ISSUED expires=$EXPIRES features=$FEATURES devices=$(grep -cv '^[[:space:]]*\\(#\\|$\\)' "$DEVICE_ID_FILE"))"
