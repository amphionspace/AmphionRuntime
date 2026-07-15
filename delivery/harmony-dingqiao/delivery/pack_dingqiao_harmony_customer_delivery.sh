#!/usr/bin/env bash
# 打包鼎桥纯血鸿蒙客户交付包（默认 ASR + TTS，也支持 ASR-only 和 SDK-only）。
# 该脚本收集 DevEco/Hvigor 已构建的 HAR/HAP、TTS 模型与文档，不负责启动 DevEco 构建。

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
VERSION="${AMPHION_RUNTIME_VERSION:-0.2.4}"
FINAL_OUT_ROOT=""
ASR_ONLY=false
SDK_ONLY=false
ALLOW_DIRTY=false

usage() {
  cat <<'EOF'
Usage: pack_dingqiao_harmony_customer_delivery.sh [--asr-only | --sdk-only] [--allow-dirty] [OUTPUT_DIR]

Options:
  --asr-only  Package the ASR SDK/demo without requiring TTS build artifacts.
  --sdk-only  Package only the self-contained ASR SDK HAR and documentation; no demo HAP.
  --allow-dirty  Permit a non-release package from a dirty worktree; recorded in provenance.
  -h, --help  Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --asr-only) ASR_ONLY=true; shift ;;
    --sdk-only) SDK_ONLY=true; shift ;;
    --allow-dirty) ALLOW_DIRTY=true; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "[ERROR] unknown argument: $1" >&2; usage >&2; exit 2 ;;
    *)
      [[ -z "$FINAL_OUT_ROOT" ]] || { echo "[ERROR] multiple output directories provided" >&2; exit 2; }
      FINAL_OUT_ROOT="$1"
      shift
      ;;
  esac
done

if [[ "$ASR_ONLY" == true && "$SDK_ONLY" == true ]]; then
  echo "[ERROR] --asr-only and --sdk-only are mutually exclusive" >&2
  exit 2
fi

FINAL_OUT_ROOT="${FINAL_OUT_ROOT:-$REPO_ROOT/build/dingqiao-harmony-delivery-$VERSION}"
OUT_ROOT="${FINAL_OUT_ROOT}.tmp.$$"
BACKUP_OUT_ROOT="${FINAL_OUT_ROOT}.backup.$$"
LOCK_DIR="${FINAL_OUT_ROOT}.lock"
LOCK_HELD=false
SIGNING_CONFIG="${HARMONY_SIGNING_CONFIG:-$REPO_ROOT/.secure/harmony-signing.json}"
BUILD_IDENTITY="$REPO_ROOT/delivery/harmony-dingqiao/build/smoke/build-identity.json"

GIT_DIRTY=false
if [[ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]]; then
  GIT_DIRTY=true
fi
if [[ "$GIT_DIRTY" == true && "$ALLOW_DIRTY" != true ]]; then
  echo "[ERROR] release packaging requires a clean worktree; commit/stash changes or pass --allow-dirty for a non-release package" >&2
  exit 1
fi
python3 - "$REPO_ROOT" "$VERSION" <<'PY'
import json
import re
import sys
from pathlib import Path

repo = Path(sys.argv[1])
version = sys.argv[2]
version_files = [
    "asr/harmony/oh-package.json5",
    "asr/harmony/sdk/oh-package.json5",
    "asr/harmony/sdk-police/oh-package.json5",
    "asr/harmony/sdk-dingqiao/oh-package.json5",
    "asr/harmony/sdk/src/main/cpp/types/libamphion_asr/oh-package.json5",
    "delivery/harmony-dingqiao/oh-package.json5",
    "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/oh-package.json5",
]
for relative in version_files:
    actual = json.loads((repo / relative).read_text(encoding="utf-8"))["version"]
    if actual != version:
        raise SystemExit(f"[ERROR] version mismatch: {relative}={actual}, delivery={version}")

runtime = (repo / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets").read_text(encoding="utf-8")
match = re.search(r"SDK_VERSION: string = '([^']+)'", runtime)
expected_runtime = f"{version}-harmony"
if match is None or match.group(1) != expected_runtime:
    actual = match.group(1) if match else "missing"
    raise SystemExit(f"[ERROR] runtime version mismatch: {actual}, expected={expected_runtime}")
PY
if [[ "$SDK_ONLY" != true ]]; then
  python3 "$SCRIPT_DIR/harmony_build_identity.py" --verify "$BUILD_IDENTITY"
fi

cleanup() {
  rm -rf "$OUT_ROOT"
  if [[ -e "$BACKUP_OUT_ROOT" ]]; then
    if [[ ! -e "$FINAL_OUT_ROOT" ]]; then
      mv "$BACKUP_OUT_ROOT" "$FINAL_OUT_ROOT"
    else
      rm -rf "$BACKUP_OUT_ROOT"
    fi
  fi
  if [[ "$LOCK_HELD" == true ]]; then
    rm -rf "$LOCK_DIR"
    LOCK_HELD=false
  fi
}

mkdir -p "$(dirname "$FINAL_OUT_ROOT")"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "[ERROR] another delivery packaging process holds lock: $LOCK_DIR" >&2
  exit 1
fi
LOCK_HELD=true
rm -rf "$OUT_ROOT"
if [[ -e "$BACKUP_OUT_ROOT" ]]; then
  if [[ ! -e "$FINAL_OUT_ROOT" ]]; then
    mv "$BACKUP_OUT_ROOT" "$FINAL_OUT_ROOT"
  else
    rm -rf "$BACKUP_OUT_ROOT"
  fi
fi
trap cleanup EXIT
trap 'cleanup; exit 130' INT TERM
mkdir -p "$OUT_ROOT/har" "$OUT_ROOT/docs"
if [[ "$SDK_ONLY" != true ]]; then
  mkdir -p "$OUT_ROOT/demo"
fi
if [[ "$ASR_ONLY" != true && "$SDK_ONLY" != true ]]; then
  mkdir -p "$OUT_ROOT/tts-models"
fi

copy_optional() {
  local src="$1"
  local dst="$2"
  if [[ -f "$src" ]]; then
    cp -v "$src" "$dst"
  else
    echo "[WARN] missing: $src"
  fi
}

copy_required() {
  local src="$1"
  local dst="$2"
  if [[ ! -f "$src" ]]; then
    echo "[ERROR] missing required artifact: $src" >&2
    exit 1
  fi
  cp -v "$src" "$dst"
}

# 从构建输出目录里取唯一的 .har（模块改名后产物名会变，glob 比写死文件名稳）。
copy_har() {
  local build_dir="$1"
  local dst="$2"
  local har=""
  local candidate
  for candidate in "$build_dir"/*.har; do
    [[ -f "$candidate" ]] || continue
    if [[ -n "$har" ]]; then
      echo "[ERROR] multiple .har files in $build_dir" >&2
      exit 1
    fi
    har="$candidate"
  done
  if [[ -z "$har" ]]; then
    echo "[ERROR] no required .har in $build_dir" >&2
    exit 1
  fi
  tar tzf "$har" >/dev/null || { echo "[ERROR] invalid HAR archive: $har" >&2; exit 1; }
  cp -v "$har" "$dst"
}

# ASR:交付"自包含" amphion_dingqiao.har(内部打包 amphion_asr/police/sherpa_onnx,file:./ 相对依赖)。
# 客户只需声明这一个 HAR,纯本地离线可解析,且 HAP 全量编译整链可解析(已真机验证)。
# 为何不发分层 HAR:各 HAR 用仓库本地 file: 路径互依赖,外部工程既装不上(死路径)、剥离后又编不过
# (幽灵依赖)——只有自包含两头都成立。详见 assemble_selfcontained_dingqiao_har.sh。
bash "$REPO_ROOT/delivery/harmony-dingqiao/delivery/assemble_selfcontained_dingqiao_har.sh" "$OUT_ROOT/har/amphion_dingqiao.har"
"$SCRIPT_DIR/verify_selfcontained_dingqiao_har.sh" "$OUT_ROOT/har/amphion_dingqiao.har"
if [[ "$ASR_ONLY" != true && "$SDK_ONLY" != true ]]; then
  # TTS 本就自包含(模型+.so 内置,无外部 HAR 依赖),直接拷。
  copy_har "$REPO_ROOT/tts/harmony/sdk/build/default/outputs/default" "$OUT_ROOT/har/amphion_tts.har"
fi

if [[ "$SDK_ONLY" != true ]]; then
  HAP_SRC=""
  for candidate in \
    "$REPO_ROOT/delivery/harmony-dingqiao/samples/dingqiao-demo/entry/build/default/outputs/default/dingqiao_demo-default-signed.hap" \
    "$REPO_ROOT/delivery/harmony-dingqiao/samples/dingqiao-demo/entry/build/default/outputs/default/entry-default-signed.hap"; do
    if [[ -f "$candidate" ]]; then
      HAP_SRC="$candidate"
      break
    fi
  done
  if [[ -z "$HAP_SRC" ]]; then
    echo "[ERROR] no signed Dingqiao demo HAP found" >&2
    exit 1
  fi
  if [[ ! -s "$SIGNING_CONFIG" ]]; then
    echo "[ERROR] customer packaging requires HARMONY_SIGNING_CONFIG or .secure/harmony-signing.json" >&2
    exit 1
  fi
  "$SCRIPT_DIR/verify_demo_inputs.sh" \
    --hap "$HAP_SRC" \
    --signing-config "$SIGNING_CONFIG"
  copy_required "$HAP_SRC" "$OUT_ROOT/demo/dingqiao-demo.hap"
fi

if [[ "$ASR_ONLY" != true && "$SDK_ONLY" != true ]]; then
  if [[ -d "$REPO_ROOT/tts/models/amphion-tts" ]]; then
    cp -R "$REPO_ROOT/tts/models/amphion-tts" "$OUT_ROOT/tts-models/"
  else
    echo "[WARN] missing optional TTS models: $REPO_ROOT/tts/models/amphion-tts"
  fi
fi

cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/DINGQIAO_INTEGRATION.md" "$OUT_ROOT/docs/"
cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/DINGQIAO_LICENSE_SCHEME.md" "$OUT_ROOT/docs/"
if [[ "$SDK_ONLY" == true ]]; then
  copy_required \
    "$REPO_ROOT/delivery/harmony-dingqiao/docs/语音识别SDK接口.md" \
    "$OUT_ROOT/docs/ASR_SDK_API_HARMONY.md"
else
  cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/语音识别SDK接口.md" "$OUT_ROOT/docs/"
fi
cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/customer/LICENSE.md" "$OUT_ROOT/docs/"
if [[ "$SDK_ONLY" != true ]]; then
  cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/customer/SDK_LIFECYCLE_PERFORMANCE_20260713.md" "$OUT_ROOT/docs/"
fi
cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/customer/SDK_LIFECYCLE_PERFORMANCE_SUMMARY_20260713.md" "$OUT_ROOT/docs/"
cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/customer/NOTICE" "$OUT_ROOT/docs/"
mkdir -p "$OUT_ROOT/docs/third-party"
cp -v "$REPO_ROOT/LICENSE" "$OUT_ROOT/docs/third-party/Apache-2.0.txt"
copy_required \
  "$REPO_ROOT/tts/harmony/sdk/src/main/cpp/third_party/onnxruntime/LICENSE" \
  "$OUT_ROOT/docs/third-party/ONNX-Runtime-MIT.txt"
cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/PRIVACY.md" "$OUT_ROOT/docs/"
cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/TROUBLESHOOTING.md" "$OUT_ROOT/docs/"
if [[ "$SDK_ONLY" != true ]]; then
  cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/MODEL_LOAD_PERFORMANCE.md" "$OUT_ROOT/docs/"
fi
cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/CHANGELOG.md" "$OUT_ROOT/docs/"
if [[ "$SDK_ONLY" == true ]]; then
  copy_required "$REPO_ROOT/delivery/harmony-dingqiao/docs/customer/README.md" "$OUT_ROOT/README.md"
fi

python3 - "$REPO_ROOT" "$OUT_ROOT" "$VERSION" "$ASR_ONLY" "$SDK_ONLY" "$GIT_DIRTY" "$BUILD_IDENTITY" <<'PY'
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

repo = Path(sys.argv[1])
out = Path(sys.argv[2])
version = sys.argv[3]
asr_only = sys.argv[4] == "true"
sdk_only = sys.argv[5] == "true"
git_dirty = sys.argv[6] == "true"
build_identity_path = Path(sys.argv[7])
build_identity = None
if not sdk_only:
    build_identity = json.loads(build_identity_path.read_text(encoding="utf-8"))


def run(*args: str) -> str:
    return subprocess.run(
        list(args), cwd=repo, check=True, text=True, stdout=subprocess.PIPE
    ).stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(relative: str) -> dict[str, object]:
    path = out / relative
    return {"path": relative, "size_bytes": path.stat().st_size, "sha256": sha256(path)}


manifest_path = repo / "asr/harmony/sdk/src/main/resources/rawfile/amphion-models/manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
source_hashes: dict[str, str] = {}
converter_ids: set[str] = set()
for bundle_name, entries in manifest["bundles"].items():
    for entry in entries:
        source_hash = entry.get("source_sha256")
        if source_hash:
            source_hashes[f"{bundle_name}/{entry['name']}"] = source_hash
        converter = entry.get("converter")
        if converter:
            converter_ids.add(converter)

patch_digest = hashlib.sha256()
patches = sorted((repo / "third_party/patches/sherpa-amphion").glob("*.patch"))
for patch in patches:
    patch_digest.update(patch.name.encode("utf-8"))
    patch_digest.update(b"\0")
    patch_digest.update(patch.read_bytes())

artifacts = [fingerprint("har/amphion_dingqiao.har")]
if not sdk_only:
    artifacts.append(fingerprint("demo/dingqiao-demo.hap"))
if not asr_only and not sdk_only:
    artifacts.append(fingerprint("har/amphion_tts.har"))

payload = {
    "schema_version": 1,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "delivery_version": version,
    "asr_only": asr_only,
    "sdk_only": sdk_only,
    "source": {
        "repository": run("git", "remote", "get-url", "origin"),
        "commit": run("git", "rev-parse", "HEAD"),
        "branch": run("git", "branch", "--show-current"),
        "worktree_dirty": git_dirty,
        "sherpa_submodule_commit": run("git", "-C", "third_party/sherpa-onnx", "rev-parse", "HEAD"),
        "sherpa_patch_series_sha256": patch_digest.hexdigest(),
    },
    "model": {
        "manifest_sha256": sha256(manifest_path),
        "manifest_version": manifest["manifest_version"],
        "converter_ids": sorted(converter_ids),
        "source_sha256": dict(sorted(source_hashes.items())),
    },
    "local_native": {
        "libsherpa-onnx-c-api.so": sha256(repo / "asr/harmony/sdk/src/main/cpp/libs/arm64-v8a/libsherpa-onnx-c-api.so"),
        "libonnxruntime.so": sha256(repo / "asr/harmony/sdk/src/main/cpp/libs/arm64-v8a/libonnxruntime.so"),
    },
    "artifacts": artifacts,
}
if build_identity is not None:
    payload["verified_build_identity"] = build_identity
(out / "docs/BUILD_PROVENANCE.json").write_text(
    json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
PY

(
  cd "$OUT_ROOT"
  find . -type f ! -path './docs/checksum.txt' | LC_ALL=C sort | while IFS= read -r f; do
    shasum -a 256 "$f"
  done > "$OUT_ROOT/docs/checksum.txt"
  shasum -a 256 -c docs/checksum.txt >/dev/null
)

if [[ -e "$FINAL_OUT_ROOT" ]]; then
  mv "$FINAL_OUT_ROOT" "$BACKUP_OUT_ROOT"
fi
if ! mv "$OUT_ROOT" "$FINAL_OUT_ROOT"; then
  [[ ! -e "$BACKUP_OUT_ROOT" ]] || mv "$BACKUP_OUT_ROOT" "$FINAL_OUT_ROOT"
  exit 1
fi
rm -rf "$BACKUP_OUT_ROOT"
rm -rf "$LOCK_DIR"
LOCK_HELD=false
trap - EXIT INT TERM
echo "[DONE] $FINAL_OUT_ROOT"
