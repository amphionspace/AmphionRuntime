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
BACKUP_DST="${DST}.backup.$$"
LOCK_DIR="${DST}.lock"
LOCK_HELD=false

cleanup() {
  rm -rf "$TMP_DST"
  if [[ -e "$BACKUP_DST" ]]; then
    if [[ ! -e "$DST" ]]; then
      mv "$BACKUP_DST" "$DST"
    else
      rm -rf "$BACKUP_DST"
    fi
  fi
  if [[ "$LOCK_HELD" == true ]]; then
    rm -rf "$LOCK_DIR"
    LOCK_HELD=false
  fi
}

mkdir -p "$(dirname "$DST")"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "[ERROR] 另一个 Harmony 模型同步进程持有锁: $LOCK_DIR" >&2
  exit 1
fi
LOCK_HELD=true
rm -rf "$TMP_DST"
if [[ -e "$BACKUP_DST" ]]; then
  if [[ ! -e "$DST" ]]; then
    mv "$BACKUP_DST" "$DST"
  else
    rm -rf "$BACKUP_DST"
  fi
fi
trap cleanup EXIT
trap 'cleanup; exit 130' INT TERM
cp -R "$SRC" "$TMP_DST"
python3 "$VERIFY" --root "$TMP_DST"

if [[ -e "$DST" ]]; then
  mv "$DST" "$BACKUP_DST"
fi
if ! mv "$TMP_DST" "$DST"; then
  [[ ! -e "$BACKUP_DST" ]] || mv "$BACKUP_DST" "$DST"
  exit 1
fi
rm -rf "$BACKUP_DST" "$LOCK_DIR"
LOCK_HELD=false
trap - EXIT INT TERM

echo "[DONE] Harmony rawfile assets -> $DST"
find "$DST" -maxdepth 3 -type f | sed "s#$REPO_ROOT/##" | sort | head -80

# TTS 模型同步已拆分到 tts/tools/harmony/pack_harmony_tts_assets.sh
