#!/usr/bin/env bash
# 打包鼎桥纯血鸿蒙客户交付包（ASR + TTS）。
# 该脚本收集 DevEco/Hvigor 已构建的 HAR/HAP、声纹/TTS 模型与文档，不负责启动 DevEco 构建。

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
VERSION="${AMPHION_RUNTIME_VERSION:-0.1.0}"
FINAL_OUT_ROOT="${1:-$REPO_ROOT/build/dingqiao-harmony-delivery-$VERSION}"
OUT_ROOT="${FINAL_OUT_ROOT}.tmp.$$"

rm -rf "$OUT_ROOT"
trap 'rm -rf "$OUT_ROOT"' EXIT
mkdir -p "$OUT_ROOT/har" "$OUT_ROOT/demo" "$OUT_ROOT/models" "$OUT_ROOT/tts-models" "$OUT_ROOT/docs"

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
  local har
  har="$(ls "$build_dir"/*.har 2>/dev/null | head -1 || true)"
  if [[ -n "$har" && -f "$har" ]]; then
    cp -v "$har" "$dst"
  else
    echo "[ERROR] no required .har in $build_dir" >&2
    exit 1
  fi
}

# ASR:交付"自包含" amphion_dingqiao.har(内部打包 amphion_asr/police/sherpa_onnx,file:./ 相对依赖)。
# 客户只需声明这一个 HAR,纯本地离线可解析,且 HAP 全量编译整链可解析(已真机验证)。
# 为何不发分层 HAR:各 HAR 用仓库本地 file: 路径互依赖,外部工程既装不上(死路径)、剥离后又编不过
# (幽灵依赖)——只有自包含两头都成立。详见 assemble_selfcontained_dingqiao_har.sh。
bash "$REPO_ROOT/delivery/harmony-dingqiao/delivery/assemble_selfcontained_dingqiao_har.sh" "$OUT_ROOT/har/amphion_dingqiao.har"
# TTS 本就自包含(模型+.so 内置,无外部 HAR 依赖),直接拷。
copy_har "$REPO_ROOT/tts/harmony/sdk/build/default/outputs/default" "$OUT_ROOT/har/amphion_tts.har"

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
"$SCRIPT_DIR/verify_demo_inputs.sh" --hap "$HAP_SRC"
copy_required "$HAP_SRC" "$OUT_ROOT/demo/dingqiao-demo.hap"

copy_optional "$REPO_ROOT/asr/android/sdk-dingqiao/src/main/assets/amphion-dingqiao/eres2net.onnx" "$OUT_ROOT/models/eres2net.onnx"
if [[ -d "$REPO_ROOT/tts/models/amphion-tts" ]]; then
  cp -R "$REPO_ROOT/tts/models/amphion-tts" "$OUT_ROOT/tts-models/"
else
  echo "[WARN] missing optional TTS models: $REPO_ROOT/tts/models/amphion-tts"
fi

cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/DINGQIAO_INTEGRATION.md" "$OUT_ROOT/docs/"
cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/DINGQIAO_LICENSE_SCHEME.md" "$OUT_ROOT/docs/"
cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/customer/LICENSE.md" "$OUT_ROOT/docs/"
cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/customer/NOTICE" "$OUT_ROOT/docs/"
cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/PRIVACY.md" "$OUT_ROOT/docs/"
cp -v "$REPO_ROOT/delivery/harmony-dingqiao/docs/CHANGELOG.md" "$OUT_ROOT/docs/"

(
  cd "$OUT_ROOT"
  find . -type f | sort | while read -r f; do
    shasum -a 256 "$f"
  done > "$OUT_ROOT/docs/checksum.txt"
)

rm -rf "$FINAL_OUT_ROOT"
mv "$OUT_ROOT" "$FINAL_OUT_ROOT"
trap - EXIT
echo "[DONE] $FINAL_OUT_ROOT"
