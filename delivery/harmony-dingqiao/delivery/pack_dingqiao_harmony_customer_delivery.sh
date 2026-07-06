#!/usr/bin/env bash
# 打包鼎桥纯血鸿蒙客户交付包（ASR + TTS）。
# 该脚本收集 DevEco/Hvigor 已构建的 HAR/HAP、声纹/TTS 模型与文档，不负责启动 DevEco 构建。

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
VERSION="${AMPHION_RUNTIME_VERSION:-0.1.0}"
OUT_ROOT="${1:-$REPO_ROOT/build/dingqiao-harmony-delivery-$VERSION}"

rm -rf "$OUT_ROOT"
mkdir -p "$OUT_ROOT/har" "$OUT_ROOT/demo" "$OUT_ROOT/models" "$OUT_ROOT/tts-models" "$OUT_ROOT/docs"

copy_if_exists() {
  local src="$1"
  local dst="$2"
  if [[ -f "$src" ]]; then
    cp -v "$src" "$dst"
  else
    echo "[WARN] missing: $src"
  fi
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
    echo "[WARN] no .har in $build_dir"
  fi
}

# 剥离交付 HAR 内部的 inter-HAR file: 依赖（amphion_*/sherpa_onnx），只保留 .so 依赖。
# 原因：源码里这些依赖是仓库本地 file: 路径，客户机上不存在，ohpm 安装会因死路径报错。
# 客户改为在自己工程 oh-package.json5 里平铺声明全部 HAR（见 DINGQIAO_INTEGRATION.md）。
strip_har_deps() {
  local har="$1"
  [[ -f "$har" ]] || return 0
  local tmp
  tmp="$(mktemp -d)"
  tar xzf "$har" -C "$tmp"
  python3 - "$tmp/package/oh-package.json5" <<'PY'
import sys, re
path = sys.argv[1]
text = open(path).read()
match = re.search(r'"dependencies"\s*:\s*\{(.*?)\}', text, re.S)
if match:
    items = re.findall(r'"[^"]+"\s*:\s*"[^"]+"', match.group(1))
    kept = [it for it in items if it.split(':', 1)[0].strip().endswith('.so"')]
    text = text[:match.start()] + '"dependencies":{' + ",".join(kept) + '}' + text[match.end():]
    open(path, "w").write(text)
PY
  ( cd "$tmp" && tar czf "$har" package )
  rm -rf "$tmp"
}

# DevEco/Hvigor 产物；ASR 三个 HAR 会做死路径剥离，sherpa_onnx / tts 无外部 HAR 依赖不需剥离。
copy_har "$REPO_ROOT/asr/harmony/sdk/build/default/outputs/default" "$OUT_ROOT/har/amphion_asr.har"
copy_har "$REPO_ROOT/asr/harmony/sdk-police/build/default/outputs/default" "$OUT_ROOT/har/amphion_police.har"
copy_har "$REPO_ROOT/asr/harmony/sdk-dingqiao/build/default/outputs/default" "$OUT_ROOT/har/amphion_dingqiao.har"
copy_har "$REPO_ROOT/tts/harmony/sdk/build/default/outputs/default" "$OUT_ROOT/har/amphion_tts.har"
# sherpa_onnx 是 amphion_asr 的运行时依赖，必须随包交付（客户内网无法从 ohpm 公共仓库拉取）。
copy_har "$REPO_ROOT/third_party/sherpa-onnx/harmony-os/SherpaOnnxHar/sherpa_onnx/build/default/outputs/default" "$OUT_ROOT/har/sherpa_onnx.har"

strip_har_deps "$OUT_ROOT/har/amphion_asr.har"
strip_har_deps "$OUT_ROOT/har/amphion_police.har"
strip_har_deps "$OUT_ROOT/har/amphion_dingqiao.har"

copy_if_exists "$REPO_ROOT/delivery/harmony-dingqiao/samples/dingqiao-demo/entry/build/default/outputs/default/entry-default-signed.hap" "$OUT_ROOT/demo/dingqiao-demo.hap"
copy_if_exists "$REPO_ROOT/delivery/harmony-dingqiao/samples/dingqiao-demo/entry/build/default/outputs/default/dingqiao_demo-default-signed.hap" "$OUT_ROOT/demo/dingqiao-demo.hap"

copy_if_exists "$REPO_ROOT/asr/android/sdk-dingqiao/src/main/assets/amphion-dingqiao/eres2net.onnx" "$OUT_ROOT/models/eres2net.onnx"
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

echo "[DONE] $OUT_ROOT"
