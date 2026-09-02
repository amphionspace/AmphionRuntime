#!/bin/bash
# E2E inference: Dingqiao TN -> inference_stream.py
#
# Usage:
#   bash infer_e2e.sh <model_lang> <input_txt> [infer_id] [--spk_id N]
#
# Examples:
#   bash infer_e2e.sh en-zh-dict data_for_test/raw-en-zh.txt
#   bash infer_e2e.sh ar-en /path/to/raw_ar.txt ar_smoke
#   SPK_ID=1 ./infer_e2e.sh ar-en-dict /path/to/en.txt en_smoke
#   ./infer_e2e.sh ar-en-dict /path/to/en.txt en_smoke --spk_id 0

set -euo pipefail

export LD_LIBRARY_PATH="${CONDA_PREFIX:-}/lib:${LD_LIBRARY_PATH:-}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

MODEL_LANG="${1:?Usage: $0 <model_lang> <input_txt> [infer_id] [--spk_id N]}"
INPUT_TXT="${2:?Usage: $0 <model_lang> <input_txt> [infer_id] [--spk_id N]}"
TIMESTAMP="$(date +%Y-%m-%d_%H-%M-%S)"
INFER_ID="${3:-e2e_${MODEL_LANG}_${TIMESTAMP}}"
if [[ $# -ge 3 ]]; then
  shift 3
else
  shift 2
fi

SPK_ARGS=()
if [[ -n "${SPK_ID:-}" ]]; then
  SPK_ARGS=(--spk_id "$SPK_ID")
fi
while [[ $# -gt 0 ]]; do
  case "$1" in
    --spk_id)
      SPK_ARGS=(--spk_id "${2:?--spk_id requires a value}")
      shift 2
      ;;
    *)
      echo "Unknown argument: $1"
      echo "Usage: $0 <model_lang> <input_txt> [infer_id] [--spk_id N]"
      exit 1
      ;;
  esac
done

case "$MODEL_LANG" in
  en-zh|en-zh-dict|ar-en|ar-en-dict|bn-en|bn-en-dict|en-ru|en-ru-dict) ;;
  *)
    echo "Unsupported model_lang: $MODEL_LANG"
    exit 1
    ;;
esac

CKPT_DEFAULT="$REPO_ROOT/model_checkpoints/${MODEL_LANG%.dict}.ckpt"
if [[ "$MODEL_LANG" == *-dict ]]; then
  CKPT_DEFAULT="$REPO_ROOT/model_checkpoints/${MODEL_LANG/-dict/}.ckpt"
fi
CHECKPOINT="${CHECKPOINT:-$CKPT_DEFAULT}"

if [[ ! -f "$CHECKPOINT" ]]; then
  echo "Checkpoint not found: $CHECKPOINT"
  echo "Set CHECKPOINT=/path/to/model.ckpt and retry."
  exit 1
fi

OUT_DIR="$REPO_ROOT/infer_output/$INFER_ID"
mkdir -p "$OUT_DIR"

python "$REPO_ROOT/infer_e2e.py" \
  --model_lang "$MODEL_LANG" \
  --checkpoint "$CHECKPOINT" \
  --input_txt "$INPUT_TXT" \
  --output_dir "$OUT_DIR" \
  --output_txt "$OUT_DIR/meta.txt" \
  --keep_manifest \
  --output_sample_rate 24000 \
  --num_decoding_left_chunks 2 \
  --length_scale 1.0 \
  "${SPK_ARGS[@]}"
