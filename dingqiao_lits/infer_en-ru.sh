# !/bin/bash
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$LD_LIBRARY_PATH"

# Make sure you have prepared the environment and data as described in `README.md`

# Activate your environment.
TEST_CHECKPOINT="/chenmingjie/xingwen/multiling_up-to-date/logs/train/en-ru_bs48_lr0.0003_20260609_073751/runs/2026-06-09_07-37-51/checkpoints/last.ckpt"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

INPUT_TXT=$1

timestamp=$(date +%Y-%m-%d"_"%H-%M-%S)

left_chunks=-1
# INFER_ID="en-zh_${left_chunks}chunks_left"
INFER_ID=${2:-$timestamp}

python inference_stream.py \
  --model_lang en-ru \
  --checkpoint $TEST_CHECKPOINT \
  --input_txt $INPUT_TXT \
  --output_dir ./infer_output/$INFER_ID \
  --output_txt ./infer_output/$INFER_ID/meta.txt \
  --output_sample_rate 24000 \
  --num_decoding_left_chunks $left_chunks