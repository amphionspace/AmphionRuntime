#!/usr/bin/env bash
# 打包鼎桥纯血鸿蒙客户交付包（默认 ASR + TTS，可显式选择 ASR-only）。
# 该脚本收集 DevEco/Hvigor 已构建的 HAR/HAP、声纹/TTS 模型与文档，不负责启动 DevEco 构建。

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
VERSION="${AMPHION_RUNTIME_VERSION:-0.1.0}"
FINAL_OUT_ROOT=""
ASR_ONLY=false

usage() {
  cat <<'EOF'
Usage: pack_dingqiao_harmony_customer_delivery.sh [--asr-only] [OUTPUT_DIR]

Options:
  --asr-only  Package the ASR SDK/demo without requiring TTS build artifacts.
  -h, --help  Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --asr-only) ASR_ONLY=true; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "[ERROR] unknown argument: $1" >&2; usage >&2; exit 2 ;;
    *)
      [[ -z "$FINAL_OUT_ROOT" ]] || { echo "[ERROR] multiple output directories provided" >&2; exit 2; }
      FINAL_OUT_ROOT="$1"
      shift
      ;;
  esac
done

FINAL_OUT_ROOT="${FINAL_OUT_ROOT:-$REPO_ROOT/build/dingqiao-harmony-delivery-$VERSION}"
OUT_ROOT="${FINAL_OUT_ROOT}.tmp.$$"
BACKUP_OUT_ROOT="${FINAL_OUT_ROOT}.backup.$$"
LOCK_DIR="${FINAL_OUT_ROOT}.lock"
LOCK_HELD=false
SIGNING_CONFIG="${HARMONY_SIGNING_CONFIG:-$REPO_ROOT/.secure/harmony-signing.json}"

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
mkdir -p "$OUT_ROOT/har" "$OUT_ROOT/demo" "$OUT_ROOT/models" "$OUT_ROOT/docs"
if [[ "$ASR_ONLY" != true ]]; then
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
if [[ "$ASR_ONLY" != true ]]; then
  # TTS 本就自包含(模型+.so 内置,无外部 HAR 依赖),直接拷。
  copy_har "$REPO_ROOT/tts/harmony/sdk/build/default/outputs/default" "$OUT_ROOT/har/amphion_tts.har"
fi

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

copy_optional "$REPO_ROOT/asr/android/sdk-dingqiao/src/main/assets/amphion-dingqiao/eres2net.onnx" "$OUT_ROOT/models/eres2net.onnx"
if [[ "$ASR_ONLY" != true ]]; then
  if [[ -d "$REPO_ROOT/tts/models/amphion-tts" ]]; then
    cp -R "$REPO_ROOT/tts/models/amphion-tts" "$OUT_ROOT/tts-models/"
  else
    echo "[WARN] missing optional TTS models: $REPO_ROOT/tts/models/amphion-tts"
  fi
fi

cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/DINGQIAO_INTEGRATION.md" "$OUT_ROOT/docs/"
cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/DINGQIAO_LICENSE_SCHEME.md" "$OUT_ROOT/docs/"
cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/customer/LICENSE.md" "$OUT_ROOT/docs/"
cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/customer/NOTICE" "$OUT_ROOT/docs/"
cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/PRIVACY.md" "$OUT_ROOT/docs/"
cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/CHANGELOG.md" "$OUT_ROOT/docs/"

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
