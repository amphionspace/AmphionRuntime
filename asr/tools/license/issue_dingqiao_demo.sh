#!/usr/bin/env bash
# 为鼎桥 Demo（com.amphion.dingqiao.demo）签发 amphion-license.lic。
#
# 商务策略：Demo 为限期试用（默认自签发日起 2 个月），绑定 demo 包名 + 签名。
# Demo APK 不绑定设备 SN；正式 SDK license 单独下发并绑定 SN 清单。
#
# 私钥默认：仓库根 .secure/amphion-license-private.pem（不进 git）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
VENV="$ROOT/tools/license/.venv"
PRIVATE_KEY="${AMPHION_LICENSE_PRIVATE_KEY:-$ROOT/.secure/amphion-license-private.pem}"
OUT="$ROOT/asr/android/samples/dingqiao-demo/src/main/assets/amphion-license.lic"
CERT_SHA="${DINGQIAO_DEMO_CERT_SHA256:-}"
TRIAL_MONTHS="${DINGQIAO_DEMO_TRIAL_MONTHS:-2}"

if [[ ! -f "$PRIVATE_KEY" ]]; then
  echo "私钥不存在: $PRIVATE_KEY" >&2
  echo "先生成: cd tools/license && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  echo "       .venv/bin/python gen_keypair.py --out-private $PRIVATE_KEY" >&2
  exit 1
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q -r "$ROOT/tools/license/requirements.txt"
fi

if [[ -z "$CERT_SHA" ]]; then
  KEYSTORE="$ROOT/asr/android/keystore/dingqiao-demo-release.jks"
  if [[ -f "$KEYSTORE" ]]; then
    CERT_SHA=$(keytool -list -v -keystore "$KEYSTORE" -alias dingqiao-demo -storepass "${DINGQIAO_KEYSTORE_PASS:-dingqiao2026}" 2>/dev/null \
      | grep "SHA256:" | head -1 | sed 's/.*SHA256: //')
  fi
fi

ISSUED="$(date +%Y-%m-%d)"
EXPIRES="$("$VENV/bin/python" -c "
from datetime import date
import calendar
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
  --application-id com.amphion.dingqiao.demo \
  --customer "Dingqiao Demo" \
  --license-id "DINGQIAO-DEMO-$(date +%Y%m)-001" \
  --issued "$ISSUED" \
  --expires "$EXPIRES" \
  --install-tier LE_100K \
  --features ASR \
  ${CERT_SHA:+--cert-sha256 "$CERT_SHA"} \
  --out "$OUT"

echo "[ok] wrote $OUT (trial ${TRIAL_MONTHS} month(s): issued=$ISSUED expires=$EXPIRES devices=none)"
