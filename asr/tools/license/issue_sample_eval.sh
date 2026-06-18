#!/usr/bin/env bash
# 为内部评测 App（com.amphion.asr.sample）签发 amphion-license.lic。
# Debug 构建默认绑定 ~/.android/debug.keystore 证书。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
VENV="$ROOT/asr/tools/license/.venv"
PRIVATE_KEY="${AMPHION_LICENSE_PRIVATE_KEY:-$ROOT/.secure/amphion-license-private.pem}"
OUT="$ROOT/asr/android/sample/src/main/assets/amphion-license.lic"
CERT_SHA="${SAMPLE_EVAL_CERT_SHA256:-}"

if [[ ! -d "$VENV" ]]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q -r "$ROOT/asr/tools/license/requirements.txt"
fi

if [[ ! -f "$PRIVATE_KEY" ]]; then
  echo "私钥不存在: $PRIVATE_KEY" >&2
  exit 1
fi

if [[ -z "$CERT_SHA" ]]; then
  CERT_SHA=$(keytool -list -v -keystore "${HOME}/.android/debug.keystore" \
    -alias androiddebugkey -storepass android 2>/dev/null \
    | grep "SHA256:" | head -1 | sed 's/.*SHA256: //')
fi

mkdir -p "$(dirname "$OUT")"
"$VENV/bin/python" "$ROOT/asr/tools/license/issue_license.py" \
  --private-key "$PRIVATE_KEY" \
  --application-id com.amphion.asr.sample \
  --customer "Amphion Sample Eval" \
  --license-id "SAMPLE-EVAL-$(date +%Y)-001" \
  --expires 2099-12-31 \
  --install-tier LE_100K \
  --features ASR_ZH_EN,ASR_YUE_EN,TARGET_SPEAKER,HOTWORDS \
  ${CERT_SHA:+--cert-sha256 "$CERT_SHA"} \
  --out "$OUT"

echo "[ok] wrote $OUT (rebuild :sample before install)"
