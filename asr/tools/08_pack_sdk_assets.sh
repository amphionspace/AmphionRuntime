#!/usr/bin/env bash
# 把 5 类资产打进 SDK assets；中英 ASR 与标点预转换为 Android ORT 1.24.3。
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
#   bash asr/tools/08_pack_sdk_assets.sh --zh-en-only
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
CONVERTER="${SCRIPT_DIR}/convert_harmony_ort.py"
CONVERTER_REQUIREMENTS="${SCRIPT_DIR}/requirements-android-ort.txt"
CONVERTER_VENV="${ANDROID_ORT_VENV:-${REPO_ROOT}/.venv-android-ort-1.24.3}"
CONVERTER_PYTHON="${ANDROID_ORT_PYTHON:-${CONVERTER_VENV}/bin/python}"
ORT_CACHE_DIR="${ANDROID_ORT_CACHE_DIR:-${REPO_ROOT}/.cache/android-ort-1.24.3}"
VERIFY="${SCRIPT_DIR}/verify_packed_model_assets.py"
MANIFEST_BUILDER="${SCRIPT_DIR}/build_harmony_asset_manifest.py"

FINAL_ASSET_ROOT="${REPO_ROOT}/asr/android/sdk/src/main/assets/amphion-models"
ASSET_ROOT="${FINAL_ASSET_ROOT}.tmp.$$"
BACKUP_ASSET_ROOT="${FINAL_ASSET_ROOT}.backup.$$"
LOCK_DIR="${FINAL_ASSET_ROOT}.lock"
LOCK_HELD=false
ZH_EN_ONLY=false

DEFAULT_VAD_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"
DEFAULT_VAD_SHA256="a4a060cb50f7464b7e6da6a5df1c3a6b4c4a4ca1f0f5e7a2cf2a1d2e0fbe93d5"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      sed -n '2,40p' "$0"; exit 0 ;;
    --zh-en-only)
      ZH_EN_ONLY=true; shift ;;
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

resolve_joiner() {
  local model_dir="$1"
  local candidate="$model_dir/joiner.int8.onnx"
  if [[ ! -f "$candidate" ]]; then
    candidate="$model_dir/joiner.onnx"
  fi
  ensure_file "$candidate" "ASR 缺 joiner.int8.onnx 或 joiner.onnx"
  printf '%s\n' "$candidate"
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

for f in encoder.int8.onnx decoder.onnx tokens.txt bbpe.vocab; do
  ensure_file "${ZH_EN_DIR}/${f}" "中英 ASR 缺 ${f}（bbpe.vocab 用 asr/tools/09_export_bbpe_vocab.py 从 bbpe.model 导出）"
done
ZH_JOINER="$(resolve_joiner "$ZH_EN_DIR")"
if [[ "$ZH_EN_ONLY" != true ]]; then
  ensure_dir "${YUE_EN_DIR}" \
    "请用 asr/tools/00_fetch_demo_model.sh 拉 demo 模型，或把自有模型目录设到 YUE_EN_DIR 环境变量"
  for f in encoder.int8.onnx decoder.onnx tokens.txt bbpe.vocab; do
    ensure_file "${YUE_EN_DIR}/${f}" "粤英 ASR 缺 ${f}（同上）"
  done
  YUE_JOINER="$(resolve_joiner "$YUE_EN_DIR")"
fi

converter_environment_valid() {
  [[ -x "$CONVERTER_PYTHON" ]] && AMPHION_ORT_PROFILE=android "$CONVERTER_PYTHON" - <<'PY' >/dev/null 2>&1
import numpy
import onnx
import onnxruntime
assert numpy.__version__ == "2.0.2"
assert onnx.__version__ == "1.19.1"
assert onnxruntime.__version__ == "1.24.3"
assert "CPUExecutionProvider" in onnxruntime.get_available_providers()
PY
}

if ! converter_environment_valid; then
  if [[ -n "${ANDROID_ORT_PYTHON:-}" ]]; then
    err "ANDROID_ORT_PYTHON 不满足 Android ORT 1.24.3 固定转换环境"
  fi
  command -v uv >/dev/null 2>&1 || err "需要 uv 创建支持 onnxruntime 1.24.3 的 Python 3.12 环境"
  info "创建 Android ORT 1.24.3 构建环境: $CONVERTER_VENV"
  uv venv --python 3.12 "$CONVERTER_VENV"
  uv pip install --python "$CONVERTER_PYTHON" -r "$CONVERTER_REQUIREMENTS"
fi
converter_environment_valid || err "Android ORT 转换环境校验失败"

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
model_subdirs=(zh-en punct-zhen itn-zh vad)
if [[ "$ZH_EN_ONLY" != true ]]; then
  model_subdirs+=(yue-en)
fi
for sub in "${model_subdirs[@]}"; do
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

# zh-en 文本资产；三图在下方并行转换为 ORT
copy_one "${ZH_EN_DIR}/tokens.txt"        "${ASSET_ROOT}/zh-en/v1/tokens.txt"
copy_one "${ZH_EN_DIR}/bbpe.vocab"        "${ASSET_ROOT}/zh-en/v1/bbpe.vocab"

if [[ "$ZH_EN_ONLY" != true ]]; then
  # yue-en
  copy_one "${YUE_EN_DIR}/encoder.int8.onnx" "${ASSET_ROOT}/yue-en/v1/encoder.int8.onnx.mp3"
  copy_one "${YUE_EN_DIR}/decoder.onnx"      "${ASSET_ROOT}/yue-en/v1/decoder.onnx.mp3"
  copy_one "$YUE_JOINER"                     "${ASSET_ROOT}/yue-en/v1/joiner.int8.onnx.mp3"
  copy_one "${YUE_EN_DIR}/tokens.txt"        "${ASSET_ROOT}/yue-en/v1/tokens.txt"
  copy_one "${YUE_EN_DIR}/bbpe.vocab"        "${ASSET_ROOT}/yue-en/v1/bbpe.vocab"
fi

# itn
copy_one "${ITN_DIR}/zh_itn_tagger.fst"     "${ASSET_ROOT}/itn-zh/v1/zh_itn_tagger.fst"
copy_one "${ITN_DIR}/zh_itn_verbalizer.fst" "${ASSET_ROOT}/itn-zh/v1/zh_itn_verbalizer.fst"

# vad
copy_one "${VAD_FILE}" "${ASSET_ROOT}/vad/v1/silero_vad.onnx"

# -------- 6. Android ORT 1.24.3 转换与 manifest v2 --------
mkdir -p "$ASSET_ROOT/.conversion-metadata"
convert_one() {
  local final_output="$2"
  local converter_output="${final_output%.mp3}"
  AMPHION_ORT_PROFILE=android "$CONVERTER_PYTHON" "$CONVERTER" \
    --input "$1" --output "$converter_output" --metadata-output "$3" --cache-dir "$ORT_CACHE_DIR"
  mv "$converter_output" "$final_output"
}

info "并行预优化中英三图与标点（Android ORT 1.24.3 / ARM CPU；.mp3 为 aapt 免压缩传输后缀）"
pids=()
convert_one "${ZH_EN_DIR}/encoder.int8.onnx" "$ASSET_ROOT/zh-en/v1/encoder.int8.ort.mp3" \
  "$ASSET_ROOT/.conversion-metadata/zh-encoder.json" & pids+=("$!")
convert_one "${ZH_EN_DIR}/decoder.onnx" "$ASSET_ROOT/zh-en/v1/decoder.ort.mp3" \
  "$ASSET_ROOT/.conversion-metadata/zh-decoder.json" & pids+=("$!")
convert_one "$ZH_JOINER" "$ASSET_ROOT/zh-en/v1/joiner.int8.ort.mp3" \
  "$ASSET_ROOT/.conversion-metadata/zh-joiner.json" & pids+=("$!")
convert_one "${PUNCT_DIR}/model.int8.onnx" "$ASSET_ROOT/punct-zhen/v1/model.int8.ort.mp3" \
  "$ASSET_ROOT/.conversion-metadata/punct.json" & pids+=("$!")
conversion_failed=0
for pid in "${pids[@]}"; do
  if ! wait "$pid"; then conversion_failed=1; fi
done
[[ "$conversion_failed" -eq 0 ]] || err "至少一个 Android ONNX -> ORT 转换失败"

manifest_args=(
  --root "$ASSET_ROOT"
  --converted "zh-en/v1/encoder.int8.ort.mp3=$ASSET_ROOT/.conversion-metadata/zh-encoder.json"
  --converted "zh-en/v1/decoder.ort.mp3=$ASSET_ROOT/.conversion-metadata/zh-decoder.json"
  --converted "zh-en/v1/joiner.int8.ort.mp3=$ASSET_ROOT/.conversion-metadata/zh-joiner.json"
  --converted "punct-zhen/v1/model.int8.ort.mp3=$ASSET_ROOT/.conversion-metadata/punct.json"
  --copy "zh-en/v1/tokens.txt=${ZH_EN_DIR}/tokens.txt"
  --copy "zh-en/v1/bbpe.vocab=${ZH_EN_DIR}/bbpe.vocab"
  --copy "itn-zh/v1/zh_itn_tagger.fst=${ITN_DIR}/zh_itn_tagger.fst"
  --copy "itn-zh/v1/zh_itn_verbalizer.fst=${ITN_DIR}/zh_itn_verbalizer.fst"
  --copy "vad/v1/silero_vad.onnx=$VAD_FILE"
)
if [[ "$ZH_EN_ONLY" == true ]]; then
  manifest_args+=(--zh-en-only)
else
  manifest_args+=(
    --copy "yue-en/v1/encoder.int8.onnx.mp3=${YUE_EN_DIR}/encoder.int8.onnx"
    --copy "yue-en/v1/decoder.onnx.mp3=${YUE_EN_DIR}/decoder.onnx"
    --copy "yue-en/v1/joiner.int8.onnx.mp3=$YUE_JOINER"
    --copy "yue-en/v1/tokens.txt=${YUE_EN_DIR}/tokens.txt"
    --copy "yue-en/v1/bbpe.vocab=${YUE_EN_DIR}/bbpe.vocab"
  )
fi
AMPHION_ORT_PROFILE=android "$CONVERTER_PYTHON" "$MANIFEST_BUILDER" "${manifest_args[@]}"
rm -rf "$ASSET_ROOT/.conversion-metadata"

verify_args=(--root "${ASSET_ROOT}" --target-platform android)
if [[ "$ZH_EN_ONLY" == true ]]; then
  verify_args+=(--zh-en-only)
fi
python3 "${SCRIPT_DIR}/verify_packed_model_assets.py" "${verify_args[@]}"

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
