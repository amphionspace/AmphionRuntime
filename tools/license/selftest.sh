#!/usr/bin/env bash
# 端到端自测：gen_keypair -> issue_license -> verify_license。
# 真实跑一遍签发 / 验签闭环（不依赖 Android），用于回归密码学链路与参数兼容性。
set -euo pipefail
cd "$(dirname "$0")"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PRIV="$TMP/test-private.pem"
LIC="$TMP/com.amphion.demo.lic"
APP="com.amphion.demo"
SN="SN-001"
DEVICE_FILE="$TMP/devices.txt"
printf '%s\n' "$SN" > "$DEVICE_FILE"

echo "== 1) 生成密钥对 =="
python3 gen_keypair.py --out-private "$PRIV" --force >/dev/null
PUB_B64="$(python3 - "$PRIV" <<'PY'
import sys, base64
from cryptography.hazmat.primitives import serialization
priv = serialization.load_pem_private_key(open(sys.argv[1], "rb").read(), password=None)
der = priv.public_key().public_bytes(
    serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
)
print(base64.b64encode(der).decode())
PY
)"

echo "== 2) 签发 license =="
python3 issue_license.py --private-key "$PRIV" --application-id "$APP" \
  --customer "Demo Co." --license-id AMP-DEMO-0001 --expires 2099-01-01 \
  --install-tier LE_10K --features ASR,TTS --device-id-file "$DEVICE_FILE" --out "$LIC" >/dev/null

echo "== 3) ASR 正确校验（期望 OK）=="
python3 verify_license.py --license "$LIC" --public-key-b64 "$PUB_B64" \
  --application-id "$APP" --device-id "$SN" --required-feature ASR >/dev/null
echo "[ok] ASR license 校验通过"

echo "== 4) TTS 正确校验（期望 OK）=="
python3 verify_license.py --license "$LIC" --public-key-b64 "$PUB_B64" \
  --application-id "$APP" --device-id "$SN" --required-feature TTS >/dev/null
echo "[ok] TTS license 校验通过"

echo "== 5) 不同 applicationId + 正确设备（期望 OK）=="
python3 verify_license.py --license "$LIC" --public-key-b64 "$PUB_B64" \
  --application-id com.wrong.app --device-id "$SN" --required-feature ASR >/dev/null
echo "[ok] 不再按 applicationId 限制 license"

echo "== 6) 错误设备 SN（期望 FAIL 6007）=="
if python3 verify_license.py --license "$LIC" --public-key-b64 "$PUB_B64" \
    --application-id "$APP" --device-id SN-999 >/dev/null 2>&1; then
  echo "!! 预期设备不匹配失败但通过了，自测不通过"; exit 1
fi
echo "[ok] 正确地拒绝了不匹配的设备 SN"

echo "== 7) 过期校验（期望 FAIL 6006）=="
EXPLIC="$TMP/expired.lic"
python3 issue_license.py --private-key "$PRIV" --application-id "$APP" \
  --expires 2000-01-01 --device-id-file "$DEVICE_FILE" --out "$EXPLIC" >/dev/null
if python3 verify_license.py --license "$EXPLIC" --public-key-b64 "$PUB_B64" \
    --application-id "$APP" --device-id "$SN" >/dev/null 2>&1; then
  echo "!! 预期过期失败但通过了，自测不通过"; exit 1
fi
echo "[ok] 正确地拒绝了过期 license"

echo "== selftest 全部通过 =="
