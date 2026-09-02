#!/bin/bash
# Duration evaluation pipeline:
#   1. Run inference on the eval filelist
#   2. Compare inferred audio duration against reference audio
#
# Usage:
#   ./eval_duration.sh <checkpoint> [infer_id]

export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$LD_LIBRARY_PATH"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EVAL_DIR="$REPO_ROOT/data_for_test/duration_eval"
EVAL_FILELIST="$EVAL_DIR/eval_filelist.txt"
REF_DIR="$EVAL_DIR/ref_audio"

TEST_CHECKPOINT="${1:?Usage: $0 <checkpoint> [infer_id]}"
INFER_ID=${2:-"duration_eval"}
INFER_DIR="$REPO_ROOT/infer_output/$INFER_ID"

echo "============================================"
echo "  Duration Evaluation Pipeline"
echo "============================================"
echo "  Eval filelist:  $EVAL_FILELIST"
echo "  Ref audio dir:  $REF_DIR"
echo "  Infer output:   $INFER_DIR"
echo "  Checkpoint:     $TEST_CHECKPOINT"
echo "============================================"

# Step 1: Run inference
echo ""
echo "[Step 1/2] Running inference..."
python inference_stream.py \
  --checkpoint "$TEST_CHECKPOINT" \
  --input_txt "$EVAL_FILELIST" \
  --output_dir "$INFER_DIR" \
  --output_txt "$INFER_DIR/meta.txt" \
  --output_sample_rate 24000 \
  --num_decoding_left_chunks -1 \
  --length_scale 1

# Step 2: Evaluate duration
echo ""
echo "[Step 2/2] Evaluating duration..."
python "$EVAL_DIR/eval_duration.py" \
  --ref_dir "$REF_DIR" \
  --infer_dir "$INFER_DIR" \
  --output "$INFER_DIR/duration_results.tsv"

echo ""
echo "Done. Results saved to: $INFER_DIR/duration_results.tsv"
