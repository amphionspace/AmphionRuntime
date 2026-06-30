#!/usr/bin/env bash
# 启动 AmphionRuntime 流式 ASR gRPC 服务端。
#
# 默认参数面向 260628 CTC chunk16 低首字配置：GPU DecodeEngine + greedy_search。
# 关键参数支持环境变量覆盖，例如换端口/换模型：
#   PORT=50052 ./asr/server/run_server.sh
#   MANIFEST=/path/to/manifest.json DECODING_METHOD=modified_beam_search ./asr/server/run_server.sh
#
# 注意：当前默认优先低首字。若切回 transducer，请同时覆盖 MANIFEST 和 DECODING_METHOD。
set -euo pipefail

# 仓库根：本脚本位于 <repo>/asr/server/ 下，bin 与 sherpa lib 据此推导，便于换机器。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

BIN="${BIN:-$REPO_ROOT/asr/server/build/asr_service}"

if [[ -z "${SHERPA_LIB:-}" ]]; then
  GPU_LIB="$REPO_ROOT/third_party/sherpa-onnx/build-linux-gpu/install/lib"
  CPU_LIB="$REPO_ROOT/third_party/sherpa-onnx/build-linux/install/lib"
  if [[ -f "$GPU_LIB/libonnxruntime.so" ]]; then
    SHERPA_LIB="$GPU_LIB"
  else
    SHERPA_LIB="$CPU_LIB"
  fi
fi

# 可覆盖参数（默认即推荐生产值）
PORT="${PORT:-50051}"
MANIFEST="${MANIFEST:-/home/ubuntu/models/onnx/k2/260628/ctc-chunk16-lc128/manifest.server.json}"
PROVIDER="${PROVIDER:-cuda}"
ENCODER_PRECISION="${ENCODER_PRECISION:-fp32}"
DECODE_WORKERS="${DECODE_WORKERS:-2}"
MAX_ACTIVE_PATHS="${MAX_ACTIVE_PATHS:-2}"
NUM_THREADS="${NUM_THREADS:-4}"
GRPC_THREADS="${GRPC_THREADS:-16}"
MAX_BATCH_SIZE="${MAX_BATCH_SIZE:-130}"
MAX_CONCURRENT_SESSIONS="${MAX_CONCURRENT_SESSIONS:-220}"
LOOP_INTERVAL_MS="${LOOP_INTERVAL_MS:-5}"
DECODING_METHOD="${DECODING_METHOD:-greedy_search}"
ENDPOINT_RULE1="${ENDPOINT_RULE1:-2.4}"
ENDPOINT_RULE2="${ENDPOINT_RULE2:-1.2}"
ENDPOINT_RULE3="${ENDPOINT_RULE3:-20.0}"

# fail-fast：缺二进制/lib/manifest 直接报错，避免起到一半才崩。
[[ -x "$BIN" ]] || { echo "[run] 找不到可执行: $BIN（先编译 asr_service）" >&2; exit 1; }
[[ -f "$SHERPA_LIB/libonnxruntime.so" ]] || { echo "[run] 找不到 onnxruntime: $SHERPA_LIB（先编 sherpa GPU）" >&2; exit 1; }
[[ -f "$MANIFEST" ]] || { echo "[run] 找不到 manifest: $MANIFEST" >&2; exit 1; }

echo "[run] listen=0.0.0.0:$PORT manifest=$MANIFEST provider=$PROVIDER precision=$ENCODER_PRECISION workers=$DECODE_WORKERS decoding=$DECODING_METHOD beam=$MAX_ACTIVE_PATHS batch=$MAX_BATCH_SIZE loop=${LOOP_INTERVAL_MS}ms endpoint=r1=$ENDPOINT_RULE1/r2=$ENDPOINT_RULE2/r3=$ENDPOINT_RULE3"

# onnxruntime 运行期必须能找到 libonnxruntime.so。
export LD_LIBRARY_PATH="$SHERPA_LIB:${LD_LIBRARY_PATH:-}"

# exec：让服务进程取代本 shell，信号（tmux Ctrl-C / SIGTERM）直达，触发 5s 优雅关闭。
exec "$BIN" \
  --listen="0.0.0.0:$PORT" \
  --manifest="$MANIFEST" \
  --provider="$PROVIDER" \
  --encoder_precision="$ENCODER_PRECISION" \
  --decode_workers="$DECODE_WORKERS" \
  --max_active_paths="$MAX_ACTIVE_PATHS" \
  --num_threads="$NUM_THREADS" \
  --grpc_threads="$GRPC_THREADS" \
  --max_batch_size="$MAX_BATCH_SIZE" \
  --max_concurrent_sessions="$MAX_CONCURRENT_SESSIONS" \
  --loop_interval_ms="$LOOP_INTERVAL_MS" \
  --endpoint_rule1_min_trailing_silence="$ENDPOINT_RULE1" \
  --endpoint_rule2_min_trailing_silence="$ENDPOINT_RULE2" \
  --endpoint_rule3_min_utterance_length="$ENDPOINT_RULE3" \
  --decoding_method="$DECODING_METHOD" \
  --metrics_listen=
