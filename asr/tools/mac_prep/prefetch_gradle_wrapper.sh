#!/usr/bin/env bash
# 预下载 Gradle Wrapper 发行包（services.gradle.org 在代理/VPN 下常 SSL 失败）
#
# 用法:
#   bash asr/tools/mac_prep/prefetch_gradle_wrapper.sh
#   cd asr/android && ./gradlew :sdk:assembleRelease
#
set -euo pipefail

GRADLE_VERSION="8.6"
ZIP="gradle-${GRADLE_VERSION}-bin.zip"
# 与 gradle-wrapper.properties 中 distributionUrl 一致（腾讯镜像）
URL="https://mirrors.cloud.tencent.com/gradle/${ZIP}"

# 官方 URL 对应的 wrapper 缓存目录（若 properties 仍指向 services.gradle.org）
OFFICIAL_HASH_DIR="$HOME/.gradle/wrapper/dists/gradle-${GRADLE_VERSION}-bin/afr5mpiioh2wthjmwnkmdsd5w"

mkdir -p "$OFFICIAL_HASH_DIR"
TARGET="$OFFICIAL_HASH_DIR/$ZIP"

if [[ -f "$TARGET" ]]; then
  if unzip -t "$TARGET" >/dev/null 2>&1; then
    echo "[OK] Gradle $GRADLE_VERSION 已在 $TARGET"
    exit 0
  fi
  rm -f "$TARGET"
fi

rm -f "$OFFICIAL_HASH_DIR/${ZIP}.lck" "$OFFICIAL_HASH_DIR/${ZIP}.part"

echo "[INFO] 下载 $ZIP ..."
curl -L --fail --retry 5 -o "$TARGET" "$URL"
unzip -t "$TARGET" >/dev/null
echo "[OK] $TARGET ($(du -h "$TARGET" | awk '{print $1}'))"
