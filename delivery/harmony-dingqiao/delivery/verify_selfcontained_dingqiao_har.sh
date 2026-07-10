#!/usr/bin/env bash
# Compile the demo as a clean customer host that depends only on the delivered ASR HAR.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SOURCE_PROJECT="$REPO_ROOT/delivery/harmony-dingqiao"
HAR="${1:?Usage: verify_selfcontained_dingqiao_har.sh HAR}"
DEVECO_HOME="${DEVECO_STUDIO_HOME:-/Applications/DevEco-Studio.app/Contents}"
NODE="$DEVECO_HOME/tools/node/bin/node"
HVIGOR="$DEVECO_HOME/tools/hvigor/bin/hvigorw.js"
OHPM="$DEVECO_HOME/tools/ohpm/bin/ohpm"
JAVA_HOME_VALUE="${JAVA_HOME:-$DEVECO_HOME/jbr/Contents/Home}"
WORK=""

cleanup() {
  [[ -z "$WORK" ]] || rm -rf "$WORK"
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT TERM

[[ -s "$HAR" ]] || { echo "[ERROR] missing self-contained HAR: $HAR" >&2; exit 1; }
tar tzf "$HAR" >/dev/null || { echo "[ERROR] invalid self-contained HAR: $HAR" >&2; exit 1; }
for tool in "$NODE" "$HVIGOR" "$OHPM"; do
  [[ -x "$tool" || -f "$tool" ]] || { echo "[ERROR] missing DevEco tool: $tool" >&2; exit 1; }
done
command -v rsync >/dev/null || { echo "[ERROR] rsync is required" >&2; exit 1; }
command -v python3 >/dev/null || { echo "[ERROR] python3 is required" >&2; exit 1; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/amphion-har-customer.XXXXXX")"
CUSTOMER_PROJECT="$WORK/customer"
ENTRY="$CUSTOMER_PROJECT/samples/dingqiao-demo/entry"
rsync -a \
  --exclude='build/' \
  --exclude='.hvigor/' \
  --exclude='.idea/' \
  --exclude='oh_modules/' \
  --exclude='oh-package-lock.json5' \
  "$SOURCE_PROJECT/" "$CUSTOMER_PROJECT/"
mkdir -p "$ENTRY/libs"
cp "$HAR" "$ENTRY/libs/amphion_dingqiao.har"

python3 - "$CUSTOMER_PROJECT/build-profile.json5" "$CUSTOMER_PROJECT/oh-package.json5" "$ENTRY/oh-package.json5" <<'PY'
import json
import sys
from pathlib import Path

profile_path = Path(sys.argv[1])
root_package_path = Path(sys.argv[2])
entry_package_path = Path(sys.argv[3])

profile = json.loads(profile_path.read_text(encoding="utf-8"))
profile["app"]["signingConfigs"] = []
for product in profile["app"].get("products", []):
    product.pop("signingConfig", None)
profile["modules"] = [module for module in profile["modules"] if module["name"] == "dingqiao_demo"]
profile_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")

root_package = json.loads(root_package_path.read_text(encoding="utf-8"))
root_package["dependencies"] = {}
root_package["devDependencies"] = {}
root_package_path.write_text(json.dumps(root_package, indent=2) + "\n", encoding="utf-8")

entry_package = json.loads(entry_package_path.read_text(encoding="utf-8"))
entry_package["dependencies"] = {"amphion_dingqiao": "file:./libs/amphion_dingqiao.har"}
entry_package_path.write_text(json.dumps(entry_package, indent=2) + "\n", encoding="utf-8")
PY

if ! (cd "$ENTRY" && "$OHPM" install --no-link --log_level warn) >"$WORK/ohpm.log" 2>&1; then
  tail -100 "$WORK/ohpm.log" >&2
  echo "[ERROR] customer host could not install the self-contained HAR" >&2
  exit 1
fi
[[ -d "$ENTRY/oh_modules/amphion_dingqiao" ]] || {
  echo "[ERROR] customer host dependency was not installed" >&2
  exit 1
}

if ! (
  export PATH="$DEVECO_HOME/tools/node/bin:$PATH"
  export DEVECO_SDK_HOME="$DEVECO_HOME/sdk"
  export JAVA_HOME="$JAVA_HOME_VALUE"
  cd "$CUSTOMER_PROJECT"
  "$NODE" "$HVIGOR" assembleHap --mode module \
    -p product=default \
    -p module=dingqiao_demo@default \
    -p buildMode=debug \
    --no-daemon --stacktrace
) >"$WORK/build.log" 2>&1; then
  tail -140 "$WORK/build.log" >&2
  echo "[ERROR] customer host could not compile with only the self-contained HAR" >&2
  exit 1
fi

HAP_COUNT="$(find "$ENTRY/build/default/outputs/default" -maxdepth 1 -type f -name '*.hap' | wc -l | tr -d ' ')"
[[ "$HAP_COUNT" -ge 1 ]] || { echo "[ERROR] customer host build produced no HAP" >&2; exit 1; }
echo "[OK] self-contained Dingqiao HAR installed and compiled in a clean customer host"
