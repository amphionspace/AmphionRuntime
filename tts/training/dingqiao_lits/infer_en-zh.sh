#!/bin/bash
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$LD_LIBRARY_PATH"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TEST_CHECKPOINT="./model_checkpoints/en-zh.ckpt"
INPUT_TXT="${1:?Usage: $0 <input_txt> [infer_id]}"

timestamp=$(date +%Y-%m-%d"_"%H-%M-%S)
INFER_ID=${2:-$timestamp}
left_chunks=-1

python inference_stream.py \
  --model_lang en-zh-dict \
  --checkpoint "$TEST_CHECKPOINT" \
  --input_txt "$INPUT_TXT" \
  --output_dir "./infer_output/$INFER_ID" \
  --output_txt "./infer_output/$INFER_ID/meta.txt" \
  --output_sample_rate 24000 \
  --num_decoding_left_chunks $left_chunks \
  --length_scale 1