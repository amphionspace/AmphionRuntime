#!/usr/bin/env bash
# 为鼎桥 Demo（com.amphion.dingqiao.demo）签发 amphion-license.lic。
# 私钥默认：仓库根 .secure/amphion-license-private.pem（不进 git）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="$ROOT/tools/license/.venv"
PRIVATE_KEY="${AMPHION_LICENSE_PRIVATE_KEY:-$ROOT/.secure/amphion-license-private.pem}"
OUT="$ROOT/android/AmphionRuntime/sample-dingqiao-demo/src/main/assets/amphion-license.lic"
CERT_SHA="${DINGQIAO_DEMO_CERT_SHA256:-}"

if [[ ! -f "$PRIVATE_KEY" ]]; then
  echo "私钥不存在: $PRIVATE_KEY" >&2
  echo "先生成: cd tools/license && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  echo "       .venv/bin/python gen_keypair.py --out-private $PRIVATE_KEY" >&2
  exit 1
fi

if [[ -z "$CERT_SHA" ]]; then
  KEYSTORE="$ROOT/android/AmphionRuntime/keystore/dingqiao-demo-release.jks"
  if [[ -f "$KEYSTORE" ]]; then
    CERT_SHA=$(keytool -list -v -keystore "$KEYSTORE" -alias dingqiao-demo -storepass "${DINGQIAO_KEYSTORE_PASS:-dingqiao2026}" 2>/dev/null \
      | grep "SHA256:" | head -1 | sed 's/.*SHA256: //')
  fi
fi

mkdir -p "$(dirname "$OUT")"
"$VENV/bin/python" "$ROOT/tools/license/issue_license.py" \
  --private-key "$PRIVATE_KEY" \
  --application-id com.amphion.dingqiao.demo \
  --customer "Dingqiao Demo" \
  --license-id "DINGQIAO-DEMO-$(date +%Y)-001" \
  --expires 2099-12-31 \
  --install-tier LE_100K \
  --features ASR_ZH_EN,ASR_YUE_EN,TARGET_SPEAKER,HOTWORDS \
  ${CERT_SHA:+--cert-sha256 "$CERT_SHA"} \
  --out "$OUT"

echo "[ok] wrote $OUT"
