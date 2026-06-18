#!/usr/bin/env bash
# 校验交付目录或 fat AAR 的构建溯源是否与当前仓库一致。
#
# 用法:
#   bash asr/tools/delivery/verify_dingqiao_delivery.sh path/to/VERSION.txt
#   bash asr/tools/delivery/verify_dingqiao_delivery.sh path/to/dingqiao-asr-v*.aar
#   bash asr/tools/delivery/verify_dingqiao_delivery.sh path/to/amphion-dingqiao-*-customer/
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=dingqiao_build_provenance.sh
source "$SCRIPT_DIR/dingqiao_build_provenance.sh"

REPO_ROOT="$(dingqiao_repo_root_from_script)"
AR_ROOT="$(dingqiao_ar_root_from_repo "$REPO_ROOT")"
TARGET="${1:?usage: verify_dingqiao_delivery.sh <VERSION.txt|*.aar|delivery-dir>}"

fail() { echo "[FAIL] $*" >&2; exit 1; }
ok() { echo "[OK] $*"; }

if [[ -f "$TARGET" && "$TARGET" == *.aar ]]; then
  dingqiao_verify_aar_provenance "$TARGET"
  tmp="$(mktemp -d)"
  unzip -q "$TARGET" "META-INF/amphion-dingqiao-build.properties" -d "$tmp"
  echo "--- AAR META-INF/amphion-dingqiao-build.properties ---"
  cat "$tmp/META-INF/amphion-dingqiao-build.properties"
  rm -rf "$tmp"
  exit 0
fi

if [[ -f "$TARGET" && "$TARGET" == *.zip ]]; then
  py="$SCRIPT_DIR/dingqiao_zip_utf8.py"
  python3 "$py" verify "$TARGET"
  exit 0
fi

if [[ -d "$TARGET" ]]; then
  if [[ -f "$TARGET/VERSION.txt" ]]; then
    bash "$0" "$TARGET/VERSION.txt"
    TARGET_DIR="$TARGET"
  elif [[ -f "$TARGET/aar/"*.aar ]]; then
    AAR="$(echo "$TARGET"/aar/*.aar | head -1)"
    bash "$0" "$AAR"
    TARGET_DIR="$TARGET"
  else
    fail "directory missing VERSION.txt or aar/*.aar: $TARGET"
  fi
  [[ -f "$TARGET_DIR/docs/NOTICE" ]] || fail "missing docs/NOTICE (third-party open source notices)"
  ok "docs/NOTICE present"
  exit 0
fi

[[ -f "$TARGET" ]] || fail "not found: $TARGET"

get_field() {
  local key="$1"
  grep -E "^${key}=" "$TARGET" | head -1 | cut -d= -f2- || true
}

COMMIT_FULL="$(get_field git_commit_full)"
COMMIT_SHORT="$(get_field git_commit)"
SDK_VER="$(get_field sdk_version)"
BC_VER="$(get_field buildconfig_sdk_version)"

[[ -n "$SDK_VER" ]] || fail "VERSION.txt missing sdk_version"
GRADLE_VER="$(dingqiao_read_sdk_version "$AR_ROOT")"
[[ "$SDK_VER" == "$GRADLE_VER" ]] || fail "VERSION.txt sdk_version=$SDK_VER != gradle.properties=$GRADLE_VER"

if [[ -n "$COMMIT_FULL" ]]; then
  git -C "$REPO_ROOT" cat-file -e "$COMMIT_FULL" 2>/dev/null || \
    fail "git_commit_full=$COMMIT_FULL not found in local repo (fetch/pull or wrong checkout)"
  ok "git commit exists locally: $COMMIT_FULL"
else
  fail "VERSION.txt missing git_commit_full (repack with updated scripts)"
fi

if [[ -n "$BC_VER" && "$BC_VER" != "$SDK_VER" ]]; then
  fail "buildconfig_sdk_version=$BC_VER != sdk_version=$SDK_VER"
fi

echo "--- $TARGET ---"
cat "$TARGET"
ok "delivery VERSION.txt consistent with repo gradle.properties"
