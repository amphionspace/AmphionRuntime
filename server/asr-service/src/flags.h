// 服务端命令行参数；所有 flag 都可以通过 env 变量同名大写覆盖（k8s 部署友好）。
#pragma once

#include <gflags/gflags.h>

namespace asr_service {

DECLARE_string(listen);
DECLARE_string(metrics_listen);
DECLARE_string(manifest);
DECLARE_int32(num_threads);
DECLARE_int32(grpc_threads);
DECLARE_int32(max_concurrent_sessions);
DECLARE_int32(session_idle_timeout_sec);

}  // namespace asr_service
