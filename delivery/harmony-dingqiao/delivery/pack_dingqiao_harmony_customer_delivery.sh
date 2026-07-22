#!/usr/bin/env bash
# 打包 HarmonyOS 客户交付包（默认 ASR + TTS，可选择 ASR-only 或 SDK-only）。
# 该脚本收集 DevEco/Hvigor 已构建的 HAR/HAP、TTS 模型与文档，不负责启动 DevEco 构建。

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
VERSION="${AMPHION_RUNTIME_VERSION:-0.2.8}"
FINAL_OUT_ROOT=""
ASR_ONLY=false
SDK_ONLY=false
ALLOW_DIRTY=false

usage() {
  cat <<'EOF'
Usage: pack_dingqiao_harmony_customer_delivery.sh [--asr-only|--sdk-only] [--allow-dirty] [OUTPUT_DIR]

Options:
  --asr-only  Package the ASR SDK/demo without requiring TTS build artifacts.
  --sdk-only  Package only the zh-en ASR HAR and public customer documents.
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

FINAL_OUT_ROOT="${FINAL_OUT_ROOT:-$REPO_ROOT/build/amphion-harmony-asr-sdk-$VERSION}"
if [[ "$FINAL_OUT_ROOT" != /* ]]; then
  FINAL_OUT_ROOT="$PWD/$FINAL_OUT_ROOT"
fi
OUT_ROOT="${FINAL_OUT_ROOT}.tmp.$$"
BACKUP_OUT_ROOT="${FINAL_OUT_ROOT}.backup.$$"
LOCK_DIR="${FINAL_OUT_ROOT}.lock"
LOCK_HELD=false
SIGNING_CONFIG="${HARMONY_SIGNING_CONFIG:-$REPO_ROOT/.secure/harmony-signing.json}"
BUILD_IDENTITY="$REPO_ROOT/delivery/harmony-dingqiao/build/smoke/build-identity.json"

GIT_DIRTY=false
# Unrelated diagnostics and local customer notes do not affect the SDK-only payload. Gate release
# reproducibility on the exact source inputs consumed below so user work elsewhere is preserved.
RELEASE_INPUTS=(
  LICENSE
  asr/harmony/sdk
  asr/harmony/sdk-dingqiao
  third_party/sherpa-onnx
  third_party/patches/sherpa-amphion
  delivery/harmony-dingqiao/delivery/assemble_selfcontained_dingqiao_har.sh
  delivery/harmony-dingqiao/delivery/check_customer_delivery_redaction.py
  delivery/harmony-dingqiao/delivery/create_normalized_tar.py
  delivery/harmony-dingqiao/delivery/dingqiao_zh_en_model_md5.json
  delivery/harmony-dingqiao/delivery/filter_zh_en_model_payload.py
  delivery/harmony-dingqiao/delivery/pack_dingqiao_harmony_customer_delivery.sh
  delivery/harmony-dingqiao/delivery/sanitize_public_har_payload.py
  delivery/harmony-dingqiao/delivery/validate_asr_sdk_delivery.py
  delivery/harmony-dingqiao/delivery/verify_dingqiao_model_md5.py
  delivery/harmony-dingqiao/delivery/verify_selfcontained_dingqiao_har.sh
  delivery/harmony-dingqiao/docs/customer/LICENSE.md
  delivery/harmony-dingqiao/docs/customer/SDK_LIFECYCLE_PERFORMANCE_SUMMARY_20260713.md
  delivery/harmony-dingqiao/docs/customer/ASR_LIFECYCLE_ASSURANCE_20260716.md
  delivery/harmony-dingqiao/docs/customer/ASR_LIFECYCLE_ASSURANCE_EVIDENCE_20260716.json
  delivery/harmony-dingqiao/docs/customer/NOTICE
  delivery/harmony-dingqiao/docs/customer/DINGQIAO_ASR_INTEGRATION.md
  delivery/harmony-dingqiao/docs/customer/DINGQIAO_ASR_LICENSE_SCHEME.md
  delivery/harmony-dingqiao/docs/customer/ASR_TROUBLESHOOTING.md
  delivery/harmony-dingqiao/docs/PRIVACY.md
  delivery/harmony-dingqiao/docs/语音识别SDK接口.md
  tts/harmony/sdk/src/main/cpp/third_party/onnxruntime/LICENSE
)
if [[ -n "$(git -C "$REPO_ROOT" status --porcelain -- "${RELEASE_INPUTS[@]}")" ]]; then
  GIT_DIRTY=true
fi
if [[ "$GIT_DIRTY" == true && "$ALLOW_DIRTY" != true ]]; then
  echo "[ERROR] release packaging requires a clean worktree; commit/stash changes or pass --allow-dirty for a non-release package" >&2
  exit 1
fi
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
if [[ "$SDK_ONLY" == true ]]; then
  mkdir -p "$OUT_ROOT/license"
fi
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

# ASR:交付"自包含" amphion_dingqiao.har(内部打包 amphion_asr/sherpa_onnx,file:./ 相对依赖)。
# 客户只需声明这一个 HAR,纯本地离线可解析,且 HAP 全量编译整链可解析(已真机验证)。
# 为何不发分层 HAR:各 HAR 用仓库本地 file: 路径互依赖,外部工程既装不上(死路径)、剥离后又编不过
# (幽灵依赖)——只有自包含两头都成立。详见 assemble_selfcontained_dingqiao_har.sh。
if [[ "$SDK_ONLY" == true ]]; then
  bash "$REPO_ROOT/delivery/harmony-dingqiao/delivery/assemble_selfcontained_dingqiao_har.sh" \
    --zh-en-only "$OUT_ROOT/har/amphion_dingqiao.har"
  "$SCRIPT_DIR/verify_selfcontained_dingqiao_har.sh" \
    --zh-en-only "$OUT_ROOT/har/amphion_dingqiao.har"
else
  bash "$REPO_ROOT/delivery/harmony-dingqiao/delivery/assemble_selfcontained_dingqiao_har.sh" \
    "$OUT_ROOT/har/amphion_dingqiao.har"
  "$SCRIPT_DIR/verify_selfcontained_dingqiao_har.sh" \
    "$OUT_ROOT/har/amphion_dingqiao.har"
fi
python3 - "$OUT_ROOT/har/amphion_dingqiao.har" "$VERSION" <<'PY'
import json
import sys
import tarfile

with tarfile.open(sys.argv[1], "r:gz") as package:
    metadata = json.loads(package.extractfile("package/oh-package.json5").read())
if metadata.get("version") != sys.argv[2]:
    raise SystemExit(
        f"[ERROR] HAR version {metadata.get('version')} does not match delivery version {sys.argv[2]}"
    )
print(f"[OK] HAR version matches delivery version {sys.argv[2]}")
PY
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
  python3 - "$HAP_SRC" "$VERSION" <<'PY'
import json
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as package:
    metadata = json.loads(package.read("pack.info"))
version = metadata["summary"]["app"]["version"]["name"]
if version != sys.argv[2]:
    raise SystemExit(f"[ERROR] HAP version {version} does not match delivery version {sys.argv[2]}")
print(f"[OK] HAP version matches delivery version {sys.argv[2]}")
PY
  copy_required "$HAP_SRC" "$OUT_ROOT/demo/dingqiao-demo.hap"
fi

if [[ "$ASR_ONLY" != true && "$SDK_ONLY" != true ]]; then
  if [[ -d "$REPO_ROOT/tts/models/amphion-tts" ]]; then
    cp -R "$REPO_ROOT/tts/models/amphion-tts" "$OUT_ROOT/tts-models/"
  else
    echo "[WARN] missing optional TTS models: $REPO_ROOT/tts/models/amphion-tts"
  fi
fi

cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/customer/LICENSE.md" "$OUT_ROOT/docs/"
cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/customer/SDK_LIFECYCLE_PERFORMANCE_SUMMARY_20260713.md" "$OUT_ROOT/docs/"
cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/customer/ASR_LIFECYCLE_ASSURANCE_20260716.md" "$OUT_ROOT/docs/"
cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/customer/ASR_LIFECYCLE_ASSURANCE_EVIDENCE_20260716.json" "$OUT_ROOT/docs/"
cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/customer/NOTICE" "$OUT_ROOT/docs/"
mkdir -p "$OUT_ROOT/docs/third-party"
cp -v "$REPO_ROOT/LICENSE" "$OUT_ROOT/docs/third-party/Apache-2.0.txt"
cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/PRIVACY.md" "$OUT_ROOT/docs/"
python3 - "$OUT_ROOT/docs/CHANGELOG.md" "$VERSION" <<'PY'
import sys
from pathlib import Path

Path(sys.argv[1]).write_text(f"""# Change log

## {sys.argv[2]}

- Deliver the HarmonyOS zh-en offline ASR SDK with the existing public compatibility API.
- Exclude industry-specific preset hotwords, resources, and text post-processing.
- Include an ASR-only four-calendar-month evaluation license without app, certificate, or device binding.
""", encoding="utf-8")
PY

if [[ "$SDK_ONLY" == true ]]; then
  cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/customer/DINGQIAO_ASR_INTEGRATION.md" \
    "$OUT_ROOT/docs/INTEGRATION.md"
  cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/customer/DINGQIAO_ASR_LICENSE_SCHEME.md" \
    "$OUT_ROOT/docs/LICENSE_SCHEME.md"
  cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/语音识别SDK接口.md" "$OUT_ROOT/docs/ASR_SDK_API_HARMONY.md"
  python3 - "$OUT_ROOT/docs/ASR_SDK_API_HARMONY.md" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
old_language = "支持 `zh-CN`、`zh-en`、`zh_en`、`zh-yue`、`zh_yue`"
new_language = "本中英交付支持 `zh-CN`、`zh-en`、`zh_en`；粤英需使用对应模型包"
if old_language not in text:
    raise SystemExit("[ERROR] public API language contract source changed")
text = text.replace(old_language, new_language)
text = text.replace(
    "普通 Demo 可使用 ODID 签发体验授权，但 ODID 与 SN 不可混用。",
    "普通应用可与签发方约定 ODID，但 ODID 与 SN 不可混用。",
)
path.write_text(text, encoding="utf-8")
PY
  cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/customer/ASR_TROUBLESHOOTING.md" \
    "$OUT_ROOT/docs/TROUBLESHOOTING.md"
  cp -v "$REPO_ROOT/tts/harmony/sdk/src/main/cpp/third_party/onnxruntime/LICENSE" \
    "$OUT_ROOT/docs/third-party/ONNX-Runtime-MIT.txt"
  python3 - "$OUT_ROOT/README.md" "$VERSION" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
version = sys.argv[2]
path.write_text(f"""# Amphion HarmonyOS 离线 ASR SDK {version}

本包为 SDK-only 交付，包含一个自包含 HAR、四个月体验授权和客户文档；不包含 Demo HAP、粤英模型、独立 TTS SDK 或 TTS 模型。
本交付内置 `zh-en` 中英识别模型，并保留声纹、标点、ITN 和 VAD；不包含行业专用热词、资源或文本后处理。
为保持现有公共接口不变，HAR 内部模块名和类型名中的兼容标识保持原样。

| 路径 | 内容 |
| --- | --- |
| `har/amphion_dingqiao.har` | HarmonyOS API 12+、`arm64-v8a` 离线 ASR SDK |
| `license/amphion-license.lic` | ASR-only、四个月、无包名和设备绑定的体验授权 |
| `docs/INTEGRATION.md` | 集成入口与调用顺序 |
| `docs/ASR_SDK_API_HARMONY.md` | 完整公开 API 契约 |
| `docs/ASR_LIFECYCLE_ASSURANCE_20260716.md` | 生命周期修复保证、时序图和验证摘要 |
| `docs/LICENSE.md` | 商用授权接入 |
| `docs/TROUBLESHOOTING.md` | 故障排查与日志采集 |
| `docs/third-party/` | 第三方开源许可证 |
| `docs/checksum.txt` | 全部交付文件 SHA-256 清单 |

开始集成前请在本目录执行：

```bash
shasum -a 256 -c docs/checksum.txt
```

授权文件 `amphion-license.lic` 不绑定应用包名、签名证书或设备；从签发日起四个自然月内有效。
""", encoding="utf-8")
PY

  LICENSE_SRC="${HARMONY_ASR_LICENSE_FILE:-$REPO_ROOT/../delivery/amphion-harmony-asr-eval.lic}"
  copy_required "$LICENSE_SRC" "$OUT_ROOT/license/amphion-license.lic"
else
  cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/DINGQIAO_INTEGRATION.md" "$OUT_ROOT/docs/"
  cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/DINGQIAO_LICENSE_SCHEME.md" "$OUT_ROOT/docs/"
  cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/语音识别SDK接口.md" "$OUT_ROOT/docs/"
  cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/customer/SDK_LIFECYCLE_PERFORMANCE_20260713.md" "$OUT_ROOT/docs/"
  cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/MODEL_LOAD_PERFORMANCE.md" "$OUT_ROOT/docs/"
fi

python3 - "$REPO_ROOT" "$OUT_ROOT" "$VERSION" "$ASR_ONLY" "$SDK_ONLY" "$GIT_DIRTY" "$BUILD_IDENTITY" <<'PY'
import hashlib
import json
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

repo = Path(sys.argv[1])
out = Path(sys.argv[2])
version = sys.argv[3]
asr_only = sys.argv[4] == "true"
sdk_only = sys.argv[5] == "true"
git_dirty = sys.argv[6] == "true"
build_identity = json.loads(Path(sys.argv[7]).read_text(encoding="utf-8"))


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
with tarfile.open(out / "har/amphion_dingqiao.har", "r:gz") as archive:
    delivered_manifest_bytes = archive.extractfile(
        "package/_bundled/amphion_asr/src/main/resources/rawfile/amphion-models/manifest.json"
    ).read()
delivered_manifest = json.loads(delivered_manifest_bytes)
model_policy = json.loads(
    (repo / "delivery/harmony-dingqiao/delivery/dingqiao_zh_en_model_md5.json")
    .read_text(encoding="utf-8")
)
approved_onnx_md5 = model_policy["onnx_files_md5"]
converter_ids: set[str] = set()
sdk_bundles = {"zh-en/v1", "punct-zhen/v1", "itn-zh/v1", "vad/v1"}
selected_bundles = set(delivered_manifest["bundles"])
if sdk_only and selected_bundles != sdk_bundles:
    raise SystemExit(f"[ERROR] delivered SDK-only model bundles are {sorted(selected_bundles)}")
for bundle_name in sorted(selected_bundles):
    entries = manifest["bundles"][bundle_name]
    for entry in entries:
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
        "bundles": sorted(selected_bundles),
        "manifest_sha256": hashlib.sha256(delivered_manifest_bytes).hexdigest(),
        "source_manifest_sha256": sha256(manifest_path),
        "manifest_version": delivered_manifest["manifest_version"],
        "converter_ids": sorted(converter_ids),
        "model_id": model_policy["model_id"],
        "onnx_md5": dict(sorted(approved_onnx_md5.items())),
    },
    "local_native": {
        "libsherpa-onnx-c-api.so": sha256(repo / "asr/harmony/sdk/src/main/cpp/libs/arm64-v8a/libsherpa-onnx-c-api.so"),
        "libonnxruntime.so": sha256(repo / "asr/harmony/sdk/src/main/cpp/libs/arm64-v8a/libonnxruntime.so"),
    },
    "artifacts": artifacts,
}
if not sdk_only:
    payload["verified_build_identity"] = build_identity
if sdk_only:
    payload["languages"] = ["zh-en"]
    payload["capabilities"] = [
        "asr",
        "voiceprint",
        "punctuation",
        "itn",
        "vad",
    ]
    payload["excluded_capabilities"] = ["industry-text-enhancement"]
(out / "docs/BUILD_PROVENANCE.json").write_text(
    json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
PY

python3 "$SCRIPT_DIR/check_customer_delivery_redaction.py" \
  "$OUT_ROOT/docs" "$OUT_ROOT/har/amphion_dingqiao.har"

(
  cd "$OUT_ROOT"
  find . -type f ! -path './docs/checksum.txt' | LC_ALL=C sort | while IFS= read -r f; do
    shasum -a 256 "$f"
  done > "$OUT_ROOT/docs/checksum.txt"
  shasum -a 256 -c docs/checksum.txt >/dev/null
)
if [[ "$SDK_ONLY" == true ]]; then
  python3 "$SCRIPT_DIR/validate_asr_sdk_delivery.py" "$OUT_ROOT" --version "$VERSION"
fi

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
