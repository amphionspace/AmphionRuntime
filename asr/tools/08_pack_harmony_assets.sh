#!/usr/bin/env bash
# 直接组装 Harmony rawfile 模型，并在构建机上把 zhen/punct ONNX 预优化为 ORT。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

ZH_EN_DIR="${ZH_EN_DIR:-${REPO_ROOT}/asr/tools/demo-model/zhen}"
YUE_EN_DIR="${YUE_EN_DIR:-${REPO_ROOT}/asr/tools/demo-model/yueen}"
PUNCT_DIR="${PUNCT_DIR:-${REPO_ROOT}/asr/tools/punct-model/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8}"
ITN_DIR="${ITN_DIR:-${REPO_ROOT}/asr/tools/weitn-fsts}"
DEFAULT_VAD_FILE="${REPO_ROOT}/asr/tools/vad-model/silero_vad.onnx"
VAD_FILE="${VAD_FILE:-${DEFAULT_VAD_FILE}}"

FINAL_ASSET_ROOT="${REPO_ROOT}/asr/harmony/sdk/src/main/resources/rawfile/amphion-models"
ASSET_ROOT="${FINAL_ASSET_ROOT}.tmp.$$"
BACKUP_ASSET_ROOT="${FINAL_ASSET_ROOT}.backup.$$"
LOCK_DIR="${FINAL_ASSET_ROOT}.lock"
LOCK_HELD=false

CONVERTER="${SCRIPT_DIR}/convert_harmony_ort.py"
CONVERTER_REQUIREMENTS="${SCRIPT_DIR}/requirements-harmony-ort.txt"
CONVERTER_VENV="${HARMONY_ORT_VENV:-${REPO_ROOT}/.venv-harmony-ort-1.16.3}"
CONVERTER_PYTHON="${HARMONY_ORT_PYTHON:-${CONVERTER_VENV}/bin/python}"
ORT_CACHE_DIR="${HARMONY_ORT_CACHE_DIR:-${REPO_ROOT}/.cache/harmony-ort-1.16.3}"
VERIFY="${SCRIPT_DIR}/verify_packed_model_assets.py"
MANIFEST_BUILDER="${SCRIPT_DIR}/build_harmony_asset_manifest.py"

DEFAULT_VAD_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"
DEFAULT_VAD_SHA256="9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6"

usage() {
  cat <<'EOF'
Usage: bash asr/tools/08_pack_harmony_assets.sh [--zh-en-only]

Inputs can be overridden with ZH_EN_DIR, YUE_EN_DIR, PUNCT_DIR, ITN_DIR,
and VAD_FILE. The zhen input intentionally uses the FP32 decoder.onnx and
joiner.onnx with an INT8 encoder; decoder INT8 quantization causes severe
Chinese token deletion on the police corpus. Set HARMONY_ORT_PYTHON to reuse an
existing Python environment containing onnxruntime==1.16.3, onnx==1.15.0,
and numpy==1.26.4.

The script converts zhen encoder/decoder/joiner and punctuation to ARM CPU
Fixed-optimization ORT files, verifies a manifest v2, then atomically replaces
the Harmony amphion-models directory. --zh-en-only omits the unrelated Yue
model input and payload for a zh-en-only delivery.
EOF
}

ZH_EN_ONLY=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --zh-en-only) ZH_EN_ONLY=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[ERROR] unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

ok()   { printf "\033[32m[OK]\033[0m   %s\n" "$*"; }
info() { printf "\033[36m[INFO]\033[0m %s\n" "$*"; }
warn() { printf "\033[33m[WARN]\033[0m %s\n" "$*"; }
err()  { printf "\033[31m[ERR]\033[0m  %s\n" "$*" >&2; exit 1; }

ensure_file() {
  local file="$1"
  local hint="$2"
  [[ -f "$file" ]] || err "缺少文件 $file; $hint"
}

ensure_dir() {
  local directory="$1"
  local hint="$2"
  [[ -d "$directory" ]] || err "缺少目录 $directory; $hint"
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

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
  err "另一个 Harmony 模型打包进程持有锁: $LOCK_DIR"
fi
LOCK_HELD=true
trap cleanup_asset_publish EXIT
trap 'cleanup_asset_publish; exit 130' INT TERM

if [[ ! -f "${PUNCT_DIR}/model.int8.onnx" ]]; then
  warn "没找到标点模型，尝试拉取本地缓存"
  bash "${SCRIPT_DIR}/00_push_punct_model.sh" --no-push
fi

if [[ ! -f "${ITN_DIR}/zh_itn_tagger.fst" || ! -f "${ITN_DIR}/zh_itn_verbalizer.fst" ]]; then
  warn "没找到 WeText FST，尝试编译本地缓存"
  bash "${SCRIPT_DIR}/00_push_weitn_fsts.sh" --no-push
fi

if [[ "$VAD_FILE" == "$DEFAULT_VAD_FILE" && -f "$VAD_FILE" ]] &&
   [[ "$(sha256_of "$VAD_FILE")" != "$DEFAULT_VAD_SHA256" ]]; then
  warn "默认 VAD 缓存 SHA-256 不匹配，将重新下载"
  rm -f "$VAD_FILE"
fi

if [[ ! -f "$VAD_FILE" ]]; then
  warn "没找到 VAD 模型，从 sherpa-onnx release 下载"
  mkdir -p "$(dirname "$VAD_FILE")"
  VAD_DOWNLOAD="${VAD_FILE}.download.$$"
  rm -f "$VAD_DOWNLOAD"
  if command -v curl >/dev/null 2>&1; then
    curl -L -f -o "$VAD_DOWNLOAD" "$DEFAULT_VAD_URL"
  elif command -v wget >/dev/null 2>&1; then
    wget -O "$VAD_DOWNLOAD" "$DEFAULT_VAD_URL"
  else
    err "需要 curl 或 wget 下载 silero_vad.onnx"
  fi
  mv "$VAD_DOWNLOAD" "$VAD_FILE"
fi

if [[ "$VAD_FILE" == "$DEFAULT_VAD_FILE" ]] &&
   [[ "$(sha256_of "$VAD_FILE")" != "$DEFAULT_VAD_SHA256" ]]; then
  err "默认 silero_vad.onnx SHA-256 校验失败"
fi

ensure_dir "$ZH_EN_DIR" "请设置 ZH_EN_DIR 或准备 asr/tools/demo-model/zhen"
ensure_file "${ZH_EN_DIR}/encoder.int8.onnx" "zhen 缺 encoder.int8.onnx"
ensure_file "${ZH_EN_DIR}/joiner.onnx" "zhen 缺 FP32 joiner.onnx"
ensure_file "${ZH_EN_DIR}/tokens.txt" "zhen 缺 tokens.txt"
ensure_file "${ZH_EN_DIR}/bbpe.vocab" "zhen 缺 bbpe.vocab"
ensure_file "${ZH_EN_DIR}/decoder.onnx" "zhen 缺 FP32 decoder.onnx"
ZH_DECODER="${ZH_EN_DIR}/decoder.onnx"

if [[ "$ZH_EN_ONLY" != true ]]; then
  ensure_dir "$YUE_EN_DIR" "请设置 YUE_EN_DIR 或准备 asr/tools/demo-model/yueen"
  for file in encoder.int8.onnx decoder.onnx joiner.int8.onnx tokens.txt bbpe.vocab; do
    ensure_file "${YUE_EN_DIR}/${file}" "yueen 缺 ${file}"
  done
fi
ensure_file "${PUNCT_DIR}/model.int8.onnx" "请检查 PUNCT_DIR"
ensure_file "${ITN_DIR}/zh_itn_tagger.fst" "请检查 ITN_DIR"
ensure_file "${ITN_DIR}/zh_itn_verbalizer.fst" "请检查 ITN_DIR"
ensure_file "$VAD_FILE" "请检查 VAD_FILE"

converter_environment_valid() {
  [[ -x "$CONVERTER_PYTHON" ]] && "$CONVERTER_PYTHON" - <<'PY' >/dev/null 2>&1
import numpy
import onnx
import onnxruntime
assert numpy.__version__ == "1.26.4"
assert onnx.__version__ == "1.15.0"
assert onnxruntime.__version__ == "1.16.3"
assert "CPUExecutionProvider" in onnxruntime.get_available_providers()
PY
}

if ! converter_environment_valid; then
  if [[ -n "${HARMONY_ORT_PYTHON:-}" ]]; then
    err "HARMONY_ORT_PYTHON 不满足 onnxruntime==1.16.3、onnx==1.15.0、numpy==1.26.4、CPU EP"
  fi
  info "创建固定的构建期 ORT 转换环境: $CONVERTER_VENV"
  python3 -m venv "$CONVERTER_VENV"
  "$CONVERTER_PYTHON" -m pip install --disable-pip-version-check -r "$CONVERTER_REQUIREMENTS"
fi
converter_environment_valid || err "ORT 转换环境校验失败"

rm -rf "$ASSET_ROOT"
if [[ -e "$BACKUP_ASSET_ROOT" ]]; then
  if [[ ! -e "$FINAL_ASSET_ROOT" ]]; then
    mv "$BACKUP_ASSET_ROOT" "$FINAL_ASSET_ROOT"
  else
    rm -rf "$BACKUP_ASSET_ROOT"
  fi
fi

info "在临时目录直接组装 Harmony 模型资产"
mkdir -p "$ASSET_ROOT/.conversion-metadata"
if [[ -f "$FINAL_ASSET_ROOT/README.md" ]]; then
  cp "$FINAL_ASSET_ROOT/README.md" "$ASSET_ROOT/README.md"
fi
bundles=(zh-en punct-zhen itn-zh vad yue-en)
for bundle in "${bundles[@]}"; do
  mkdir -p "$ASSET_ROOT/$bundle/v1"
  touch "$ASSET_ROOT/$bundle/v1/.gitkeep"
done

copy_one() {
  local source="$1"
  local destination="$2"
  cp "$source" "$destination"
  ok "copy $(basename "$source") -> ${destination#"$ASSET_ROOT/"}"
}

copy_one "${ZH_EN_DIR}/tokens.txt" "$ASSET_ROOT/zh-en/v1/tokens.txt"
copy_one "${ZH_EN_DIR}/bbpe.vocab" "$ASSET_ROOT/zh-en/v1/bbpe.vocab"
if [[ "$ZH_EN_ONLY" != true ]]; then
  copy_one "${YUE_EN_DIR}/encoder.int8.onnx" "$ASSET_ROOT/yue-en/v1/encoder.int8.onnx"
  copy_one "${YUE_EN_DIR}/decoder.onnx" "$ASSET_ROOT/yue-en/v1/decoder.onnx"
  copy_one "${YUE_EN_DIR}/joiner.int8.onnx" "$ASSET_ROOT/yue-en/v1/joiner.int8.onnx"
  copy_one "${YUE_EN_DIR}/tokens.txt" "$ASSET_ROOT/yue-en/v1/tokens.txt"
  copy_one "${YUE_EN_DIR}/bbpe.vocab" "$ASSET_ROOT/yue-en/v1/bbpe.vocab"
fi
copy_one "${ITN_DIR}/zh_itn_tagger.fst" "$ASSET_ROOT/itn-zh/v1/zh_itn_tagger.fst"
copy_one "${ITN_DIR}/zh_itn_verbalizer.fst" "$ASSET_ROOT/itn-zh/v1/zh_itn_verbalizer.fst"
copy_one "$VAD_FILE" "$ASSET_ROOT/vad/v1/silero_vad.onnx"

convert_one() {
  local source="$1"
  local destination="$2"
  local metadata="$3"
  "$CONVERTER_PYTHON" "$CONVERTER" \
    --input "$source" \
    --output "$destination" \
    --metadata-output "$metadata" \
    --cache-dir "$ORT_CACHE_DIR"
}

info "并行预优化 zhen 三图与 punctuation（ARM CPU / Fixed / Nchwc disabled）"
pids=()
convert_one "${ZH_EN_DIR}/encoder.int8.onnx" \
  "$ASSET_ROOT/zh-en/v1/encoder.int8.ort" \
  "$ASSET_ROOT/.conversion-metadata/zh-encoder.json" &
pids+=("$!")
convert_one "$ZH_DECODER" \
  "$ASSET_ROOT/zh-en/v1/decoder.ort" \
  "$ASSET_ROOT/.conversion-metadata/zh-decoder.json" &
pids+=("$!")
convert_one "${ZH_EN_DIR}/joiner.onnx" \
  "$ASSET_ROOT/zh-en/v1/joiner.int8.ort" \
  "$ASSET_ROOT/.conversion-metadata/zh-joiner.json" &
pids+=("$!")
convert_one "${PUNCT_DIR}/model.int8.onnx" \
  "$ASSET_ROOT/punct-zhen/v1/model.int8.ort" \
  "$ASSET_ROOT/.conversion-metadata/punct.json" &
pids+=("$!")

conversion_failed=0
for pid in "${pids[@]}"; do
  if ! wait "$pid"; then
    conversion_failed=1
  fi
done
[[ "$conversion_failed" -eq 0 ]] || err "至少一个 ONNX -> ORT 转换失败"

manifest_args=(
  --root "$ASSET_ROOT"
  --converted "zh-en/v1/encoder.int8.ort=$ASSET_ROOT/.conversion-metadata/zh-encoder.json"
  --converted "zh-en/v1/decoder.ort=$ASSET_ROOT/.conversion-metadata/zh-decoder.json"
  --converted "zh-en/v1/joiner.int8.ort=$ASSET_ROOT/.conversion-metadata/zh-joiner.json"
  --converted "punct-zhen/v1/model.int8.ort=$ASSET_ROOT/.conversion-metadata/punct.json"
  --copy "zh-en/v1/tokens.txt=${ZH_EN_DIR}/tokens.txt"
  --copy "zh-en/v1/bbpe.vocab=${ZH_EN_DIR}/bbpe.vocab"
  --copy "itn-zh/v1/zh_itn_tagger.fst=${ITN_DIR}/zh_itn_tagger.fst"
  --copy "itn-zh/v1/zh_itn_verbalizer.fst=${ITN_DIR}/zh_itn_verbalizer.fst"
  --copy "vad/v1/silero_vad.onnx=$VAD_FILE"
)
if [[ "$ZH_EN_ONLY" == true ]]; then
  manifest_args+=(--zh-en-only)
fi
if [[ "$ZH_EN_ONLY" != true ]]; then
  manifest_args+=(
    --copy "yue-en/v1/encoder.int8.onnx=${YUE_EN_DIR}/encoder.int8.onnx"
    --copy "yue-en/v1/decoder.onnx=${YUE_EN_DIR}/decoder.onnx"
    --copy "yue-en/v1/joiner.int8.onnx=${YUE_EN_DIR}/joiner.int8.onnx"
    --copy "yue-en/v1/tokens.txt=${YUE_EN_DIR}/tokens.txt"
    --copy "yue-en/v1/bbpe.vocab=${YUE_EN_DIR}/bbpe.vocab"
  )
fi
"$CONVERTER_PYTHON" "$MANIFEST_BUILDER" "${manifest_args[@]}"

rm -rf "$ASSET_ROOT/.conversion-metadata"
verify_args=(--root "$ASSET_ROOT")
if [[ "$ZH_EN_ONLY" == true ]]; then
  verify_args+=(--zh-en-only)
fi
"$CONVERTER_PYTHON" "$VERIFY" "${verify_args[@]}"

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

ok "Harmony manifest v2 assets -> $FINAL_ASSET_ROOT"
find "$FINAL_ASSET_ROOT" -maxdepth 3 -type f \
  | sed "s#${REPO_ROOT}/##" \
  | sort \
  | head -80
