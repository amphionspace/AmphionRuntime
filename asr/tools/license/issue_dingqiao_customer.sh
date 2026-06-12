#!/usr/bin/env bash
# 为鼎桥正式 App（com.tdtech.tiassistant）签发 amphion-license.lic。
#
# 环境变量：
#   DINGQIAO_TRIAL_MONTHS=2          试用月数（默认 2）
#   DINGQIAO_DEVICE_SHA256=...       单机绑定指纹（SpeechRecognizeSdk.deviceLicenseFingerprint）
#   DINGQIAO_CUSTOMER_CERT_SHA256=... Release 证书 SHA-256（必填，或见下方默认）
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$ROOT/tools/license/.venv"
PRIVATE_KEY="${AMPHION_LICENSE_PRIVATE_KEY:-$ROOT/.secure/amphion-license-private.pem}"
OUT="${1:-$ROOT/../delivery/com.tdtech.tiassistant.lic}"
APP_ID="com.tdtech.tiassistant"
CERT_SHA="${DINGQIAO_CUSTOMER_CERT_SHA256:-6e9b5aaeef2797755cd3405952d9693e8db173c0a1733e38bf5bd16f9a6022e8}"
DEVICE_SHA="${DINGQIAO_DEVICE_SHA256:-}"
TRIAL_MONTHS="${DINGQIAO_TRIAL_MONTHS:-2}"

if [[ ! -f "$PRIVATE_KEY" ]]; then
  echo "私钥不存在: $PRIVATE_KEY" >&2
  exit 1
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
  --application-id "$APP_ID" \
  --customer "TD Tech / Dingqiao" \
  --license-id "DINGQIAO-TDTECH-$(date +%Y%m)-001" \
  --issued "$ISSUED" \
  --expires "$EXPIRES" \
  --install-tier LE_100K \
  --features ASR_ZH_EN,ASR_YUE_EN,TARGET_SPEAKER,HOTWORDS \
  --cert-sha256 "$CERT_SHA" \
  ${DEVICE_SHA:+--device-sha256 "$DEVICE_SHA"} \
  --out "$OUT"

echo "[ok] wrote $OUT (trial ${TRIAL_MONTHS} month(s): issued=$ISSUED expires=$EXPIRES device=${DEVICE_SHA:-none})"
