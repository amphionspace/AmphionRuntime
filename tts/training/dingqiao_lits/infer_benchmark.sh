#!/bin/bash
#
# CPU benchmark wrapper for inference_stream_benchmark.py
# Adds NUMA binding, thread control, and warmup on top of the original inference logic.
#
# Usage:
#   bash infer_benchmark.sh <model_lang> <input_txt> [infer_id]
#
# Environment overrides (optional):
#   NUMA_NODE=0        which NUMA node to bind (default: 0)
#   NUM_THREADS=26     intra-op thread count  (default: physical cores on target NUMA node)
#   WARMUP_RUNS=3      warmup iterations before real measurement (default: 3)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MODEL_LANG=${1:-}
INPUT_TXT=${2:-}

if [ -z "$MODEL_LANG" ] || [ -z "$INPUT_TXT" ]; then
  echo "Usage: $0 <model_lang> <input_txt> [infer_id]"
  echo "Supported model_lang: ar-en | bn-en | en-ru | en-zh"
  exit 1
fi

case "$MODEL_LANG" in
  ar-en|bn-en|en-ru|en-zh)
    ;;
  *)
    echo "Unsupported model_lang: $MODEL_LANG"
    echo "Supported model_lang: ar-en | bn-en | en-ru | en-zh"
    exit 1
    ;;
esac

TEST_CHECKPOINT="$REPO_ROOT/model_checkpoints/${MODEL_LANG}.ckpt"
if [ ! -f "$TEST_CHECKPOINT" ]; then
  echo "Checkpoint not found: $TEST_CHECKPOINT"
  exit 1
fi

timestamp=$(date +%Y-%m-%d"_"%H-%M-%S)
left_chunks=-1
INFER_ID=${3:-"bench_$timestamp"}

if [ "$MODEL_LANG" = "bn-en" ]; then
  AFNAS_FRONTEND_SR=22050
else
  AFNAS_FRONTEND_SR=24000
fi

# ---------- NUMA & thread configuration ----------
NUMA_NODE=${NUMA_NODE:-0}

if [ -z "${NUM_THREADS:-}" ]; then
  # Auto-detect physical cores on the target NUMA node.
  # lscpu -p gives "CPU,Core,Socket,Node,..."; count unique physical cores on our node.
  NUM_THREADS=$(lscpu -p=CPU,CORE,NODE 2>/dev/null \
    | grep -v '^#' \
    | awk -F, -v node="$NUMA_NODE" '$3==node {print $2}' \
    | sort -un | wc -l)
  # Fallback if detection fails
  if [ "$NUM_THREADS" -le 0 ] 2>/dev/null; then
    NUM_THREADS=26
  fi
fi

WARMUP_RUNS=${WARMUP_RUNS:-3}

echo "============================================"
echo "  CPU Benchmark Configuration"
echo "============================================"
echo "  NUMA node:        $NUMA_NODE"
echo "  Threads (intra):  $NUM_THREADS"
echo "  Warmup runs:      $WARMUP_RUNS"
echo "  Model lang:       $MODEL_LANG"
echo "  Input txt:        $INPUT_TXT"
echo "  Checkpoint:       $TEST_CHECKPOINT"
echo "============================================"

export OMP_NUM_THREADS=$NUM_THREADS
export MKL_NUM_THREADS=$NUM_THREADS
export OPENBLAS_NUM_THREADS=$NUM_THREADS

exec numactl --cpunodebind="$NUMA_NODE" --membind="$NUMA_NODE" \
  python "$REPO_ROOT/inference_stream_benchmark.py" \
    --model_lang "$MODEL_LANG" \
    --checkpoint "$TEST_CHECKPOINT" \
    --input_txt "$INPUT_TXT" \
    --output_dir "./infer_output/$INFER_ID" \
    --output_txt "./infer_output/$INFER_ID/meta.txt" \
    --vocoder_dir "$REPO_ROOT/afnas_pupuvocoder_mix22050_24k_100band" \
    --afnas_frontend_sr "$AFNAS_FRONTEND_SR" \
    --output_sample_rate 24000 \
    --num_decoding_left_chunks "$left_chunks" \
    --text_normalization off \
    --warmup_runs "$WARMUP_RUNS" \
    --num_threads "$NUM_THREADS"
