// 服务端命令行参数；所有 flag 都可以通过 env 变量同名大写覆盖（k8s 部署友好）。
#pragma once

#include <gflags/gflags.h>

namespace asr_service {

DECLARE_string(listen);
DECLARE_string(metrics_listen);
DECLARE_string(manifest);
DECLARE_string(provider);
DECLARE_string(encoder_precision);
DECLARE_int32(num_threads);
DECLARE_int32(grpc_threads);
DECLARE_int32(decode_workers);
DECLARE_int32(max_concurrent_sessions);
DECLARE_int32(max_batch_size);
DECLARE_int32(loop_interval_ms);
DECLARE_int32(session_idle_timeout_sec);
DECLARE_int32(max_active_paths);
DECLARE_string(decoding_method);

}  // namespace asr_service
