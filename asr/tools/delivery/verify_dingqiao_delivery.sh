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
  dingqiao_verify_aar_native_libs "$TARGET"
  dingqiao_verify_aar_speaker_model "$TARGET"
  dingqiao_verify_aar_asr_models "$TARGET"
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
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  python3 - "$TARGET" "$tmp" <<'PY'
import sys
import zipfile
from pathlib import Path

zip_path = sys.argv[1]
out_dir = Path(sys.argv[2])

with zipfile.ZipFile(zip_path) as z:
    aar_names = [
        name for name in z.namelist()
        if name.endswith(".aar") and "/aar/" in name
    ]
    if len(aar_names) != 1:
        print(
            f"[ERROR] expected exactly one customer AAR under aar/, found {len(aar_names)}",
            file=sys.stderr,
        )
        for name in aar_names:
            print(f"  - {name}", file=sys.stderr)
        sys.exit(1)

    aar_name = aar_names[0]
    (out_dir / "customer.aar").write_bytes(z.read(aar_name))

    apk_names = []
    for name in z.namelist():
        if not name.endswith(".apk"):
            continue
        parts = Path(name).parts
        if len(parts) == 3 and parts[1] == "demo":
            apk_names.append(name)
    if len(apk_names) != 1:
        print(
            f"[ERROR] expected exactly one Demo APK under demo/, found {len(apk_names)}",
            file=sys.stderr,
        )
        for name in apk_names:
            print(f"  - {name}", file=sys.stderr)
        sys.exit(1)

    apk_name = apk_names[0]
    (out_dir / "demo.apk").write_bytes(z.read(apk_name))
PY
  dingqiao_verify_aar_provenance "$tmp/customer.aar"
  dingqiao_verify_aar_native_libs "$tmp/customer.aar"
  dingqiao_verify_aar_speaker_model "$tmp/customer.aar"
  dingqiao_verify_aar_asr_models "$tmp/customer.aar"
  dingqiao_verify_apk_native_libs "$tmp/demo.apk"
  dingqiao_verify_apk_speaker_model "$tmp/demo.apk"
  dingqiao_verify_apk_asr_models "$tmp/demo.apk"
  exit 0
fi

if [[ -d "$TARGET" ]]; then
  TARGET_DIR="$TARGET"
  if [[ -f "$TARGET/VERSION.txt" ]]; then
    bash "$0" "$TARGET/VERSION.txt"
  fi
  shopt -s nullglob
  AARS=("$TARGET"/aar/*.aar)
  APKS=("$TARGET"/demo/*.apk)
  shopt -u nullglob
  if (( ${#AARS[@]} != 1 )); then
    fail "directory must contain exactly one aar/*.aar, found ${#AARS[@]}: $TARGET"
  fi
  if (( ${#APKS[@]} != 1 )); then
    fail "directory must contain exactly one demo/*.apk, found ${#APKS[@]}: $TARGET"
  fi
  bash "$0" "${AARS[0]}"
  dingqiao_verify_apk_native_libs "${APKS[0]}"
  dingqiao_verify_apk_speaker_model "${APKS[0]}"
  dingqiao_verify_apk_asr_models "${APKS[0]}"
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
