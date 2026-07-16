#!/usr/bin/env bash
# Compile the demo as a clean customer host that depends only on the delivered ASR HAR.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
SOURCE_PROJECT="$REPO_ROOT/delivery/harmony-dingqiao"
ZH_EN_ONLY=false
if [[ "${1:-}" == "--zh-en-only" ]]; then
  ZH_EN_ONLY=true
  shift
fi
HAR="${1:?Usage: verify_selfcontained_dingqiao_har.sh [--zh-en-only] HAR}"
[[ $# -eq 1 ]] || { echo "[ERROR] unexpected arguments" >&2; exit 2; }
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

python3 - \
  "$HAR" \
  "$REPO_ROOT/asr/harmony/sdk/src/main/resources/rawfile/amphion-models/manifest.json" \
  "$REPO_ROOT/asr/harmony/sdk-police/src/main/resources/rawfile/amphion-police" \
  "$REPO_ROOT/asr/harmony/sdk-dingqiao/src/main/resources/rawfile/amphion-dingqiao/eres2net.onnx" \
  "$REPO_ROOT/asr/harmony/sdk/src/main/cpp/libs/arm64-v8a/libsherpa-onnx-c-api.so" \
  "$REPO_ROOT/asr/harmony/sdk/src/main/cpp/libs/arm64-v8a/libonnxruntime.so" \
  "$ZH_EN_ONLY" \
  "$SCRIPT_DIR" <<'PY'
import sys
import tarfile
import json
import hashlib
import importlib.util
from pathlib import Path
import shutil
import tempfile

har = Path(sys.argv[1])
police_root = Path(sys.argv[3])
zh_en_only = sys.argv[7] == "true"
script_dir = Path(sys.argv[8])
expected = {
    "package/src/main/resources/rawfile/amphion-dingqiao/eres2net.onnx": Path(sys.argv[4]),
    "package/_bundled/amphion_asr/libs/arm64-v8a/libsherpa-onnx-c-api.so": Path(sys.argv[5]),
    "package/_bundled/amphion_asr/libs/arm64-v8a/libonnxruntime.so": Path(sys.argv[6]),
    "package/_bundled/sherpa_onnx/libs/arm64-v8a/libsherpa-onnx-c-api.so": Path(sys.argv[5]),
    "package/_bundled/sherpa_onnx/libs/arm64-v8a/libonnxruntime.so": Path(sys.argv[6]),
}
with tarfile.open(har, "r:gz") as package:
    manifest_member = package.extractfile(
        "package/_bundled/amphion_asr/src/main/resources/rawfile/amphion-models/manifest.json"
    )
    if manifest_member is None:
        raise SystemExit("[ERROR] self-contained HAR is missing model manifest")
    embedded_manifest = json.loads(manifest_member.read())
    local_manifest = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    if zh_en_only:
        allowed = {"zh-en/v1", "punct-zhen/v1", "itn-zh/v1", "vad/v1"}
        local_manifest["bundles"] = {
            name: entries
            for name, entries in local_manifest["bundles"].items()
            if name in allowed
        }
    if embedded_manifest != local_manifest:
        raise SystemExit("[ERROR] self-contained HAR model manifest differs from expected delivery selection")
    for member_name, local_path in expected.items():
        member = package.extractfile(member_name)
        if member is None:
            raise SystemExit(f"[ERROR] self-contained HAR is missing {member_name}")
        if member.read() != local_path.read_bytes():
            raise SystemExit(
                f"[ERROR] self-contained HAR entry differs from verified local artifact: {member_name}"
            )
    if zh_en_only:
        module_path = script_dir / "sanitize_public_har_payload.py"
        spec = importlib.util.spec_from_file_location("sanitize_public_har_payload", module_path)
        if spec is None or spec.loader is None:
            raise SystemExit(f"[ERROR] cannot load public HAR sanitizer: {module_path}")
        sanitizer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sanitizer)
        with tempfile.TemporaryDirectory() as directory:
            package_root = Path(directory) / "package"
            public_police_root = package_root / sanitizer.POLICE_RELATIVE_ROOT
            shutil.copytree(police_root, public_police_root)
            sanitizer.sanitize_payload(package_root)
            police_manifest = json.loads(
                (public_police_root / "manifest.json").read_text(encoding="utf-8")
            )
    else:
        police_manifest = json.loads((police_root / "manifest.json").read_text(encoding="utf-8"))
    embedded_police_manifest_name = (
        "package/_bundled/amphion_police/src/main/resources/rawfile/amphion-police/manifest.json"
    )
    embedded_police_manifest = package.extractfile(embedded_police_manifest_name)
    if embedded_police_manifest is None:
        raise SystemExit("[ERROR] self-contained HAR is missing police manifest")
    if json.loads(embedded_police_manifest.read()) != police_manifest:
        raise SystemExit("[ERROR] self-contained HAR police manifest differs from public selection")
    for relative, expected_sha256 in police_manifest["files"].items():
        member_name = f"package/_bundled/amphion_police/src/main/resources/rawfile/amphion-police/{relative}"
        member = package.extractfile(member_name)
        if member is None:
            raise SystemExit(f"[ERROR] self-contained HAR is missing police asset: {member_name}")
        if hashlib.sha256(member.read()).hexdigest() != expected_sha256:
            raise SystemExit(f"[ERROR] self-contained HAR police asset differs from Android: {member_name}")
    if zh_en_only and any("yue-en" in member.name.lower() for member in package.getmembers()):
        raise SystemExit("[ERROR] zh-en-only HAR still contains Yue model content")
print("[OK] self-contained HAR ASR/voiceprint models, police assets, and native libraries match local artifacts")
PY

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

python3 - \
  "$CUSTOMER_PROJECT/build-profile.json5" \
  "$CUSTOMER_PROJECT/oh-package.json5" \
  "$ENTRY/oh-package.json5" \
  "$ENTRY/src/main/ets/entryability/EntryAbility.ets" \
  "$CUSTOMER_PROJECT/hvigor/hvigor-config.json5" <<'PY'
import json
import sys
from pathlib import Path

profile_path = Path(sys.argv[1])
root_package_path = Path(sys.argv[2])
entry_package_path = Path(sys.argv[3])
entry_ability_path = Path(sys.argv[4])
hvigor_config_path = Path(sys.argv[5])

# Generate this ignored DevEco file so the clean-host check never depends on workstation state.
hvigor_config_path.parent.mkdir(parents=True, exist_ok=True)
hvigor_config_path.write_text(
    json.dumps(
        {
            "modelVersion": "5.0.0",
            "dependencies": {},
            "execution": {},
            "logging": {},
            "debugging": {},
            "nodeOptions": {},
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)

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

# The repository demo contains headless internal diagnostics that intentionally import lower-layer
# modules. A customer host only receives the public self-contained HAR, so verify that boundary with
# the normal UI ability and public amphion_dingqiao API only.
entry_ability_path.write_text("""import { UIAbility } from '@kit.AbilityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { window } from '@kit.ArkUI';
import deviceInfo from '@ohos.deviceInfo';
import { LicenseDeviceIdProvider, SpeechRecognizeSdk } from 'amphion_dingqiao';

class CustomerDeviceIdProvider implements LicenseDeviceIdProvider {
  getDeviceSerial(_context: Context): string | undefined {
    const deviceId = deviceInfo.ODID;
    return deviceId.length > 0 ? deviceId : undefined;
  }
}

export default class EntryAbility extends UIAbility {
  onCreate(): void {
    SpeechRecognizeSdk.init(this.context, new CustomerDeviceIdProvider());
    SpeechRecognizeSdk.setWorkPath(`${this.context.filesDir}/dingqiao_work`);
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    windowStage.loadContent('pages/Index', (err: BusinessError): void => {
      if (err.code !== 0) return;
    });
  }
}
""", encoding="utf-8")
PY

rm -f \
  "$ENTRY/src/main/ets/util/DeviceStressTest.ets" \
  "$ENTRY/src/main/ets/util/ModelLoadBench.ets" \
  "$ENTRY/src/main/ets/util/SdkSelfTest.ets"

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
