#!/usr/bin/env bash
# 把 5 类资产打进 SDK assets，给 :sdk:assembleRelease 用。
#
# 资产清单（详见 asr/android/sdk/src/main/assets/amphion-models/README.md）：
#   1. zh-en/v1/      中英 streaming Zipformer transducer
#   2. yue-en/v1/     粤英 streaming Zipformer transducer
#   3. punct-zhen/v1/ CT-Transformer 中英标点
#   4. itn-zh/v1/     WeText 中文 ITN tagger + verbalizer fst
#   5. vad/v1/        silero VAD (silero_vad.onnx)
#
# 输入来源（每一项默认值都可被环境变量覆盖；不存在时报错）：
#
#   ZH_EN_DIR     默认 asr/tools/demo-model/zipformer_L_zh_en
#                 必须包含 encoder.int8.onnx / decoder.onnx / joiner.int8.onnx /
#                          tokens.txt / bbpe.vocab
#                 bbpe.vocab 是 sherpa-onnx ssentencepiece 库期望的「token + score」
#                 两列文本词表（非 google SentencePiece protobuf .model）。
#                 这是 byte-level BPE 模型让热词编码能命中 ASR token 的必要文件，
#                 缺失会让 modeling_unit=bbpe 路径在构造 bpe_encoder_ 时 segfault。
#                 如果只有 bbpe.model（protobuf），先跑 asr/tools/09_export_bbpe_vocab.py 转换
#   YUE_EN_DIR    默认 asr/tools/demo-model/zipformer_L_yue_en
#                 内容同上
#   PUNCT_DIR     默认 asr/tools/punct-model/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8
#                 必须包含 model.int8.onnx
#                 没有时会自动调用 asr/tools/00_push_punct_model.sh --no-push
#   ITN_DIR       默认 asr/tools/weitn-fsts
#                 必须包含 zh_itn_tagger.fst / zh_itn_verbalizer.fst
#                 没有时会自动调用 asr/tools/00_push_weitn_fsts.sh --no-push
#   VAD_FILE      默认 asr/tools/vad-model/silero_vad.onnx
#                 没有时会从 sherpa-onnx 官方 release 自动下载
#
# 用法：
#   bash asr/tools/08_pack_sdk_assets.sh
#   ZH_EN_DIR=/path/to/zh_en bash asr/tools/08_pack_sdk_assets.sh
#
# 输出：
#   - 把上述文件分别拷贝到
#     asr/android/sdk/src/main/assets/amphion-models/<bundle>/v1/
#   - 在 amphion-models/manifest.json 写一份运行期不读、仅供运维核对的清单
#     （含每份资产的 sha256 / size_bytes / source_path）
#
# 输出后下一步：
#   cd asr/android
#   ./gradlew :sdk:assembleRelease

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

ZH_EN_DIR="${ZH_EN_DIR:-${REPO_ROOT}/asr/tools/demo-model/zhen}"
YUE_EN_DIR="${YUE_EN_DIR:-${REPO_ROOT}/asr/tools/demo-model/yueen}"
PUNCT_DIR="${PUNCT_DIR:-${REPO_ROOT}/asr/tools/punct-model/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8}"
ITN_DIR="${ITN_DIR:-${REPO_ROOT}/asr/tools/weitn-fsts}"
VAD_FILE="${VAD_FILE:-${REPO_ROOT}/asr/tools/vad-model/silero_vad.onnx}"

FINAL_ASSET_ROOT="${REPO_ROOT}/asr/android/sdk/src/main/assets/amphion-models"
ASSET_ROOT="${FINAL_ASSET_ROOT}.tmp.$$"
BACKUP_ASSET_ROOT="${FINAL_ASSET_ROOT}.backup.$$"
LOCK_DIR="${FINAL_ASSET_ROOT}.lock"
LOCK_HELD=false

DEFAULT_VAD_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"
DEFAULT_VAD_SHA256="a4a060cb50f7464b7e6da6a5df1c3a6b4c4a4ca1f0f5e7a2cf2a1d2e0fbe93d5"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      sed -n '2,40p' "$0"; exit 0 ;;
    *)
      echo "[ERROR] unknown argument: $1" >&2; exit 1 ;;
  esac
done

ok()   { printf "\033[32m[OK]\033[0m   %s\n" "$*"; }
info() { printf "\033[36m[INFO]\033[0m %s\n" "$*"; }
warn() { printf "\033[33m[WARN]\033[0m %s\n" "$*"; }
err()  { printf "\033[31m[ERR]\033[0m  %s\n" "$*" >&2; exit 1; }

ensure_file() {
  local path="$1"
  local hint="$2"
  [[ -f "$path" ]] || err "缺少文件 $path; $hint"
}

ensure_dir() {
  local path="$1"
  local hint="$2"
  [[ -d "$path" ]] || err "缺少目录 $path; $hint"
}

# -------- 1. 准备 PUNCT --------
if [[ ! -f "${PUNCT_DIR}/model.int8.onnx" ]]; then
  warn "没找到 ${PUNCT_DIR}/model.int8.onnx，尝试调用 asr/tools/00_push_punct_model.sh --no-push 拉一份缓存"
  bash "${SCRIPT_DIR}/00_push_punct_model.sh" --no-push
fi
ensure_file "${PUNCT_DIR}/model.int8.onnx" \
  "请检查 PUNCT_DIR 或先跑 bash asr/tools/00_push_punct_model.sh --no-push"

# -------- 2. 准备 ITN --------
if [[ ! -f "${ITN_DIR}/zh_itn_tagger.fst" || ! -f "${ITN_DIR}/zh_itn_verbalizer.fst" ]]; then
  warn "没找到 WeText fsts 在 ${ITN_DIR}，尝试调用 asr/tools/00_push_weitn_fsts.sh --no-push 编译一份"
  bash "${SCRIPT_DIR}/00_push_weitn_fsts.sh" --no-push
fi
ensure_file "${ITN_DIR}/zh_itn_tagger.fst" \
  "请检查 ITN_DIR 或先跑 bash asr/tools/00_push_weitn_fsts.sh --no-push"
ensure_file "${ITN_DIR}/zh_itn_verbalizer.fst" \
  "请检查 ITN_DIR 或先跑 bash asr/tools/00_push_weitn_fsts.sh --no-push"

# -------- 3. 准备 VAD --------
if [[ ! -f "${VAD_FILE}" ]]; then
  warn "没找到 ${VAD_FILE}，从 sherpa-onnx 官方 release 下载 silero_vad.onnx"
  mkdir -p "$(dirname "${VAD_FILE}")"
  if command -v curl >/dev/null 2>&1; then
    curl -L -f -o "${VAD_FILE}" "${DEFAULT_VAD_URL}"
  elif command -v wget >/dev/null 2>&1; then
    wget -O "${VAD_FILE}" "${DEFAULT_VAD_URL}"
  else
    err "需要 curl 或 wget 来下载 silero_vad.onnx"
  fi
fi
ensure_file "${VAD_FILE}" "请检查 VAD_FILE 路径是否正确"

# -------- 4. 准备 ASR （zh-en / yue-en） --------
ensure_dir "${ZH_EN_DIR}" \
  "请用 asr/tools/00_fetch_demo_model.sh 拉 demo 模型，或把自有模型目录设到 ZH_EN_DIR 环境变量"
ensure_dir "${YUE_EN_DIR}" \
  "请用 asr/tools/00_fetch_demo_model.sh 拉 demo 模型，或把自有模型目录设到 YUE_EN_DIR 环境变量"

for f in encoder.int8.onnx decoder.onnx joiner.int8.onnx tokens.txt bbpe.vocab; do
  ensure_file "${ZH_EN_DIR}/${f}" "中英 ASR 缺 ${f}（bbpe.vocab 用 asr/tools/09_export_bbpe_vocab.py 从 bbpe.model 导出）"
  ensure_file "${YUE_EN_DIR}/${f}" "粤英 ASR 缺 ${f}（同上）"
done

# -------- 5. 在临时目录组装 SDK assets --------
cleanup_asset_publish() {
  rm -rf "$ASSET_ROOT"
  if [[ -e "$BACKUP_ASSET_ROOT" ]]; then
    if [[ ! -e "$FINAL_ASSET_ROOT" ]]; then
      mv "$BACKUP_ASSET_ROOT" "$FINAL_ASSET_ROOT"
    else
      rm -rf "$BACKUP_ASSET_ROOT"
    fi
  fi
  if [[ "$LOCK_HELD" == true ]]; then
    rm -rf "$LOCK_DIR"
    LOCK_HELD=false
  fi
}

mkdir -p "$(dirname "$FINAL_ASSET_ROOT")"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  err "另一个模型打包进程持有锁: $LOCK_DIR"
fi
LOCK_HELD=true
rm -rf "$ASSET_ROOT"
if [[ -e "$BACKUP_ASSET_ROOT" ]]; then
  if [[ ! -e "$FINAL_ASSET_ROOT" ]]; then
    mv "$BACKUP_ASSET_ROOT" "$FINAL_ASSET_ROOT"
  else
    rm -rf "$BACKUP_ASSET_ROOT"
  fi
fi
trap cleanup_asset_publish EXIT
trap 'cleanup_asset_publish; exit 130' INT TERM

info "在临时目录组装模型资产，验证通过后原子替换 ${FINAL_ASSET_ROOT}"
mkdir -p "$ASSET_ROOT"
if [[ -f "$FINAL_ASSET_ROOT/README.md" ]]; then
  cp "$FINAL_ASSET_ROOT/README.md" "$ASSET_ROOT/README.md"
fi
for sub in zh-en yue-en punct-zhen itn-zh vad; do
  local_dst="${ASSET_ROOT}/${sub}/v1"
  mkdir -p "${local_dst}"
  touch "${local_dst}/.gitkeep"
done

copy_one() {
  local src="$1"
  local dst="$2"
  cp "${src}" "${dst}"
  ok "copy ${src} -> ${dst}"
}

# zh-en
copy_one "${ZH_EN_DIR}/encoder.int8.onnx" "${ASSET_ROOT}/zh-en/v1/encoder.int8.onnx"
copy_one "${ZH_EN_DIR}/decoder.onnx"      "${ASSET_ROOT}/zh-en/v1/decoder.onnx"
copy_one "${ZH_EN_DIR}/joiner.int8.onnx"  "${ASSET_ROOT}/zh-en/v1/joiner.int8.onnx"
copy_one "${ZH_EN_DIR}/tokens.txt"        "${ASSET_ROOT}/zh-en/v1/tokens.txt"
copy_one "${ZH_EN_DIR}/bbpe.vocab"        "${ASSET_ROOT}/zh-en/v1/bbpe.vocab"

# yue-en
copy_one "${YUE_EN_DIR}/encoder.int8.onnx" "${ASSET_ROOT}/yue-en/v1/encoder.int8.onnx"
copy_one "${YUE_EN_DIR}/decoder.onnx"      "${ASSET_ROOT}/yue-en/v1/decoder.onnx"
copy_one "${YUE_EN_DIR}/joiner.int8.onnx"  "${ASSET_ROOT}/yue-en/v1/joiner.int8.onnx"
copy_one "${YUE_EN_DIR}/tokens.txt"        "${ASSET_ROOT}/yue-en/v1/tokens.txt"
copy_one "${YUE_EN_DIR}/bbpe.vocab"        "${ASSET_ROOT}/yue-en/v1/bbpe.vocab"

# punct
copy_one "${PUNCT_DIR}/model.int8.onnx" "${ASSET_ROOT}/punct-zhen/v1/model.int8.onnx"

# itn
copy_one "${ITN_DIR}/zh_itn_tagger.fst"     "${ASSET_ROOT}/itn-zh/v1/zh_itn_tagger.fst"
copy_one "${ITN_DIR}/zh_itn_verbalizer.fst" "${ASSET_ROOT}/itn-zh/v1/zh_itn_verbalizer.fst"

# vad
copy_one "${VAD_FILE}" "${ASSET_ROOT}/vad/v1/silero_vad.onnx"

# -------- 6. 写一份 manifest.json，仅供运维核对（运行期不读） --------
sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

size_of() {
  if [[ "$(uname)" == "Darwin" ]]; then
    stat -f '%z' "$1"
  else
    stat -c '%s' "$1"
  fi
}

write_entry() {
  local sub="$1"
  local rel_files=("${@:2}")
  printf '    "%s": [\n' "${sub}"
  local n=${#rel_files[@]}
  local i=0
  for f in "${rel_files[@]}"; do
    local p="${ASSET_ROOT}/${sub}/${f}"
    local sha
    sha="$(sha256_of "$p")"
    local sz
    sz="$(size_of "$p")"
    printf '      {"name": "%s", "size_bytes": %s, "sha256": "%s"}' "${f}" "${sz}" "${sha}"
    i=$((i+1))
    if [[ $i -lt $n ]]; then printf ','; fi
    printf '\n'
  done
  printf '    ]'
}

MANIFEST="${ASSET_ROOT}/manifest.json"
{
  echo '{'
  echo '  "manifest_version": 1,'
  echo '  "bundles": {'
  write_entry "zh-en/v1"      encoder.int8.onnx decoder.onnx joiner.int8.onnx tokens.txt bbpe.vocab
  echo ','
  write_entry "yue-en/v1"     encoder.int8.onnx decoder.onnx joiner.int8.onnx tokens.txt bbpe.vocab
  echo ','
  write_entry "punct-zhen/v1" model.int8.onnx
  echo ','
  write_entry "itn-zh/v1"     zh_itn_tagger.fst zh_itn_verbalizer.fst
  echo ','
  write_entry "vad/v1"        silero_vad.onnx
  echo
  echo '  }'
  echo '}'
} >"${MANIFEST}"

python3 "${SCRIPT_DIR}/verify_packed_model_assets.py" --root "${ASSET_ROOT}"
if [[ "${OPTIMIZE_ONNX_GRAPHS:-0}" == "1" ]]; then
  info "离线优化 ONNX graphs: level=${OPTIMIZE_ONNX_LEVEL:-extended}"
  "${PYTHON:-python3}" "${SCRIPT_DIR}/optimize_onnx_graphs.py" \
    --root "${ASSET_ROOT}" \
    --level "${OPTIMIZE_ONNX_LEVEL:-extended}"
fi

if [[ -e "$FINAL_ASSET_ROOT" ]]; then
  mv "$FINAL_ASSET_ROOT" "$BACKUP_ASSET_ROOT"
fi
if ! mv "$ASSET_ROOT" "$FINAL_ASSET_ROOT"; then
  [[ ! -e "$BACKUP_ASSET_ROOT" ]] || mv "$BACKUP_ASSET_ROOT" "$FINAL_ASSET_ROOT"
  exit 1
fi
rm -rf "$BACKUP_ASSET_ROOT" "$LOCK_DIR"
LOCK_HELD=false
trap - EXIT INT TERM
ASSET_ROOT="$FINAL_ASSET_ROOT"
ok "manifest 写到 ${ASSET_ROOT}/manifest.json"

info "下一步：cd asr/android && ./gradlew :sdk:assembleRelease"
info "       AAR 输出：asr/android/sdk/build/outputs/aar/sdk-release.aar"
