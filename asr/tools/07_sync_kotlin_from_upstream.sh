#!/usr/bin/env bash
# 把 third_party/sherpa-onnx submodule 内 SherpaOnnxAar 的 Kotlin 桥接文件
# 同步到 asr/android/sdk/src/main/java/com/k2fsa/sherpa/onnx/。
#
# 何时使用：
#   - 第一次拉仓库后，确认 submodule 的 Kotlin 已经被搬到 SDK 工程内（通常已经在了，只做对账）
#   - 升级 sherpa-onnx submodule tag 后，把可能改过的桥接文件刷新到 SDK 工程内
#
# 用法：
#   bash asr/tools/07_sync_kotlin_from_upstream.sh           # 实际同步
#   bash asr/tools/07_sync_kotlin_from_upstream.sh --check   # 只 diff 不写入，CI 用

set -euo pipefail

MODE="apply"
if [[ "${1:-}" == "--check" ]]; then
  MODE="check"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SHERPA_ROOT="$REPO_ROOT/third_party/sherpa-onnx"
# 上游 Kotlin 真实源在 sherpa-onnx/kotlin-api/；SherpaOnnxAar/.../ 下都是 symlink 指过来。
SRC_DIR="$SHERPA_ROOT/sherpa-onnx/kotlin-api"
DST_DIR="$REPO_ROOT/asr/android/sdk/src/main/java/com/k2fsa/sherpa/onnx"

if [[ ! -d "$SRC_DIR" ]]; then
  echo "[ERROR] 找不到上游 Kotlin 源目录：$SRC_DIR"
  echo "        请确认 third_party/sherpa-onnx submodule 已经初始化："
  echo "        git submodule update --init --recursive"
  exit 1
fi

# SDK 实际只用以下 5 个文件；其他上游 .kt 涉及 TTS / KWS / Speaker 等不需要的能力，跳过。
FILES=(
  OnlineRecognizer.kt
  OnlineStream.kt
  Vad.kt
  FeatureConfig.kt
  HomophoneReplacerConfig.kt
)

mkdir -p "$DST_DIR"

DIFF_COUNT=0
for f in "${FILES[@]}"; do
  if [[ ! -f "$SRC_DIR/$f" ]]; then
    echo "[WARN] upstream 缺失 $f，跳过；可能是上游重构了文件名"
    continue
  fi
  if [[ ! -f "$DST_DIR/$f" ]] || ! cmp -s "$SRC_DIR/$f" "$DST_DIR/$f"; then
    DIFF_COUNT=$((DIFF_COUNT+1))
    if [[ "$MODE" == "check" ]]; then
      echo "[DIFF] $f differs"
      diff -u "$DST_DIR/$f" "$SRC_DIR/$f" 2>&1 | head -30 || true
    else
      echo "[SYNC] $f"
      cp -f "$SRC_DIR/$f" "$DST_DIR/$f"
    fi
  fi
done

echo
if [[ "$MODE" == "check" ]]; then
  if [[ $DIFF_COUNT -gt 0 ]]; then
    echo "[FAIL] $DIFF_COUNT Kotlin bridge file(s) out of sync with upstream."
    echo "       Run: bash asr/tools/07_sync_kotlin_from_upstream.sh"
    exit 2
  fi
  echo "[OK] Kotlin bridge files are in sync with submodule HEAD."
else
  echo "[DONE] Synced $DIFF_COUNT file(s) into $DST_DIR"
fi
