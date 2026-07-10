#!/usr/bin/env bash
# 阶段 H.3：把 Android SDK 的 amphion-models 资产复制到 Harmony rawfile。

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SRC="$REPO_ROOT/asr/android/sdk/src/main/assets/amphion-models"
DST="$REPO_ROOT/asr/harmony/sdk/src/main/resources/rawfile/amphion-models"
VERIFY="$REPO_ROOT/asr/tools/verify_packed_model_assets.py"

if [[ ! -d "$SRC" ]]; then
  echo "[ERROR] 找不到 Android 模型资产：$SRC"
  echo "        请先按 Android 流程运行 asr/tools/08_pack_sdk_assets.sh"
  exit 1
fi

python3 "$VERIFY" --root "$SRC"

TMP_DST="${DST}.tmp.$$"
trap 'rm -rf "$TMP_DST"' EXIT
rm -rf "$TMP_DST"
mkdir -p "$(dirname "$DST")"
cp -R "$SRC" "$TMP_DST"
python3 "$VERIFY" --root "$TMP_DST"

rm -rf "$DST"
mv "$TMP_DST" "$DST"
trap - EXIT

echo "[DONE] Harmony rawfile assets -> $DST"
find "$DST" -maxdepth 3 -type f | sed "s#$REPO_ROOT/##" | sort | head -80

# TTS 模型同步已拆分到 tts/tools/harmony/pack_harmony_tts_assets.sh
