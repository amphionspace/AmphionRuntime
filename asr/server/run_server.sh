#!/usr/bin/env bash
# 启动 AmphionRuntime 流式 ASR gRPC 服务端。
#
# 默认参数面向当前 gRPC 服务端：单进程 OnlineRecognizer + modified_beam_search。
# 关键参数支持环境变量覆盖，例如换端口/换模型：
#   PORT=50052 ./asr/server/run_server.sh
#   MANIFEST=/path/to/manifest.json ENDPOINT_RULE2=0.8 ./asr/server/run_server.sh
#
# 注意：decoding_method 固定 modified_beam_search，便于热词与 endpoint 调参口径稳定。
set -euo pipefail

# 仓库根：本脚本位于 <repo>/asr/server/ 下，bin 与 sherpa lib 据此推导，便于换机器。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

BIN="${BIN:-$REPO_ROOT/asr/server/build/asr_service}"
SHERPA_LIB="${SHERPA_LIB:-$REPO_ROOT/third_party/sherpa-onnx/build-linux/install/lib}"

# 可覆盖参数（默认即推荐生产值）
PORT="${PORT:-50051}"
MANIFEST="${MANIFEST:-/home/ubuntu/models/onnx/k2/260610/zhen/manifest.server.json}"
MAX_ACTIVE_PATHS="${MAX_ACTIVE_PATHS:-2}"
NUM_THREADS="${NUM_THREADS:-4}"
GRPC_THREADS="${GRPC_THREADS:-16}"
MAX_CONCURRENT_SESSIONS="${MAX_CONCURRENT_SESSIONS:-200}"
ENDPOINT_RULE1="${ENDPOINT_RULE1:-2.4}"
ENDPOINT_RULE2="${ENDPOINT_RULE2:-1.2}"
ENDPOINT_RULE3="${ENDPOINT_RULE3:-20.0}"

# fail-fast：缺二进制/lib/manifest 直接报错，避免起到一半才崩。
[[ -x "$BIN" ]] || { echo "[run] 找不到可执行: $BIN（先编译 asr_service）" >&2; exit 1; }
[[ -f "$SHERPA_LIB/libonnxruntime.so" ]] || { echo "[run] 找不到 onnxruntime: $SHERPA_LIB（先编 sherpa GPU）" >&2; exit 1; }
[[ -f "$MANIFEST" ]] || { echo "[run] 找不到 manifest: $MANIFEST" >&2; exit 1; }

echo "[run] listen=0.0.0.0:$PORT manifest=$MANIFEST beam=$MAX_ACTIVE_PATHS endpoint=r1=$ENDPOINT_RULE1/r2=$ENDPOINT_RULE2/r3=$ENDPOINT_RULE3"

# onnxruntime 运行期必须能找到 libonnxruntime.so。
export LD_LIBRARY_PATH="$SHERPA_LIB:${LD_LIBRARY_PATH:-}"

# exec：让服务进程取代本 shell，信号（tmux Ctrl-C / SIGTERM）直达，触发 5s 优雅关闭。
exec "$BIN" \
  --listen="0.0.0.0:$PORT" \
  --manifest="$MANIFEST" \
  --max_active_paths="$MAX_ACTIVE_PATHS" \
  --num_threads="$NUM_THREADS" \
  --grpc_threads="$GRPC_THREADS" \
  --max_concurrent_sessions="$MAX_CONCURRENT_SESSIONS" \
  --endpoint_rule1_min_trailing_silence="$ENDPOINT_RULE1" \
  --endpoint_rule2_min_trailing_silence="$ENDPOINT_RULE2" \
  --endpoint_rule3_min_utterance_length="$ENDPOINT_RULE3" \
  --decoding_method=modified_beam_search \
  --metrics_listen=
