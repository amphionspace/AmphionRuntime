#!/usr/bin/env bash
# 把 TTS 模型复制到鸿蒙 amphion_tts HAR 的 rawfile。
# 约定源目录为 tts/models/amphion-tts，目标 tts/harmony/sdk/.../rawfile/amphion-tts。

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SRC="$REPO_ROOT/tts/models/amphion-tts"
DST="$REPO_ROOT/tts/harmony/sdk/src/main/resources/rawfile/amphion-tts"

if [[ ! -d "$SRC" ]]; then
  echo "[ERROR] 找不到 TTS 模型目录：$SRC"
  echo "        请先把 Kokoro/VITS 模型放入 tts/models/amphion-tts/<voiceId>/"
  exit 1
fi

mkdir -p "$DST"
# 复制模型内容到 rawfile，保留目录中的 README.md 说明文件。
cp -R "$SRC"/. "$DST"/

echo "[DONE] Harmony TTS rawfile assets -> $DST"
find "$DST" -maxdepth 3 -type f | sed "s#$REPO_ROOT/##" | sort | head -80
