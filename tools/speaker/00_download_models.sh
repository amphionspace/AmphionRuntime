#!/usr/bin/env bash
# 下载 TS-ASR 调研期所需的 3 个模型（不含 ASR；ASR 复用 tools/asr/ 已导出的流式 zipformer）：
#
#   1. silero_vad.onnx                                              ~1.8 MB
#      VAD 切段，行业标杆
#   2. 3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx   ~27  MB
#      声纹 embedding（中文优先），sherpa-onnx Android sample 默认款
#   3. wespeaker_en_voxceleb_CAM++.onnx                             ~28  MB
#      声纹 embedding（中英 / 通用），调研文档推荐做端侧 RTF 候选
#
# 都来自 sherpa-onnx 官方 releases（k2-fsa），不修改、不再分发。
#
# 用法：
#   bash tools/speaker/00_download_models.sh
#   bash tools/speaker/00_download_models.sh --only vad
#   bash tools/speaker/00_download_models.sh --mirror https://your-mirror.example/sherpa-onnx
#
# 环境变量：
#   SPEAKER_MIRROR  替代默认的 github 下载源；URL 末尾不带 /
#   SPEAKER_DEST    覆盖默认下载目录（默认 tools/speaker/models/）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEFAULT_DEST="$SCRIPT_DIR/models"
DEFAULT_BASE_VAD="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"
DEFAULT_BASE_SPK="https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models"

DEST="${SPEAKER_DEST:-$DEFAULT_DEST}"
ONLY=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --only)    ONLY="$2"; shift 2 ;;
    --mirror)  export SPEAKER_MIRROR="$2"; shift 2 ;;
    --dest)    DEST="$2"; shift 2 ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) echo "[ERROR] 未知参数: $1"; exit 1 ;;
  esac
done

mkdir -p "$DEST"

# 注意：避免使用 bash 4+ 的关联数组（declare -A），
# 因为 macOS 自带 /bin/bash 仍是 3.2，不支持，会把数组 key 当算术表达式求值。
# 这里改用普通索引数组 + case 函数，兼容 bash 3.2+。
ALL_NAMES=(
  "silero_vad.onnx"
  "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"
  "wespeaker_en_voxceleb_CAM++.onnx"
)

name_to_base() {
  case "$1" in
    silero_vad.onnx) echo "$DEFAULT_BASE_VAD" ;;
    *)               echo "$DEFAULT_BASE_SPK" ;;
  esac
}

kind_to_name() {
  case "$1" in
    vad)      echo "silero_vad.onnx" ;;
    eres2net) echo "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx" ;;
    campp)    echo "wespeaker_en_voxceleb_CAM++.onnx" ;;
    *)        return 1 ;;
  esac
}

declare -a TARGETS=()
if [[ -z "$ONLY" ]]; then
  TARGETS=("${ALL_NAMES[@]}")
else
  name="$(kind_to_name "$ONLY")" || { echo "[ERROR] --only 取值必须是: vad / eres2net / campp"; exit 1; }
  TARGETS=("$name")
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "[ERROR] 需要 curl"; exit 1
fi

download_one() {
  local fname="$1"
  local default_base; default_base="$(name_to_base "$fname")"
  local base="${SPEAKER_MIRROR:-$default_base}"
  local url="$base/$fname"
  local dst="$DEST/$fname"

  if [[ -f "$dst" ]]; then
    echo "[SKIP] $fname 已存在: $dst"
    return 0
  fi

  echo "[GET ] $url"
  # -L 跟随 redirect；--fail 让 4xx/5xx 返回非 0，避免下载到 html 错误页
  curl -fL --retry 3 --retry-delay 2 -o "$dst.part" "$url"
  mv "$dst.part" "$dst"

  local size
  size="$(du -h "$dst" | awk '{print $1}')"
  echo "[OK  ] $fname  $size"
}

echo "================================================"
echo "Dest:     $DEST"
echo "Mirror:   ${SPEAKER_MIRROR:-<github releases>}"
echo "Targets:  ${TARGETS[*]}"
echo "================================================"

for f in "${TARGETS[@]}"; do
  download_one "$f"
done

cat <<EOF

[DONE] 模型下载完毕。

目录布局：
  $DEST/
  ├── silero_vad.onnx
  ├── 3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx
  └── wespeaker_en_voxceleb_CAM++.onnx

下一步：
  1. 准备 enrollment 音频（≥3 段，每段 5-10s，单通道；不同语速/距离/设备）
  2. bash tools/speaker/01_enroll_target.py --help

注意：本目录 ($DEST) 已被 .gitignore 排除，不会进 git 历史。
      模型分发与 SDK 打包请走 tools/asr/08_pack_sdk_assets.sh 风格的独立流程，本调研不参与。
EOF
