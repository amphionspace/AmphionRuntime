#!/usr/bin/env bash
# 一次性初始化：从官方 SherpaOnnxAar 复制 gradlew / gradlew.bat / gradle-wrapper.jar
# 这三份文件是 Gradle Wrapper 的二进制资产，仓库里不直接维护副本，运行一次本脚本即可。
#
# 用法：
#   cd asr/android
#   bash init_gradle_wrapper.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SOURCE_DIR="$REPO_ROOT/third_party/sherpa-onnx/android/SherpaOnnxAar"

if [[ ! -f "$SOURCE_DIR/gradlew" ]]; then
  echo "[ERROR] 没有找到 $SOURCE_DIR/gradlew"
  echo "        请确认 sherpa-onnx 仓库完整、当前目录正确。"
  exit 1
fi

cd "$SCRIPT_DIR"

cp -fv "$SOURCE_DIR/gradlew"     ./gradlew
cp -fv "$SOURCE_DIR/gradlew.bat" ./gradlew.bat
cp -fv "$SOURCE_DIR/gradle/wrapper/gradle-wrapper.jar" ./gradle/wrapper/gradle-wrapper.jar

chmod +x ./gradlew

echo
echo "[DONE] Gradle wrapper 初始化完成。"
echo "[NEXT] 在本目录运行： ./gradlew :sdk:assembleRelease"
