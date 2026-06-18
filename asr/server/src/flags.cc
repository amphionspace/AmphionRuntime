#include "flags.h"

namespace asr_service {

DEFINE_string(listen, "0.0.0.0:50051",
              "gRPC 服务监听地址，host:port");
DEFINE_string(metrics_listen, "0.0.0.0:9090",
              "Prometheus exporter 监听地址；空字符串关闭");
DEFINE_string(manifest, "/etc/asr-service/manifest.json",
              "模型 manifest.json 绝对路径；schema 与 shared/api-spec/manifest.schema.json 对齐");
DEFINE_int32(num_threads, 4,
             "OnlineRecognizer 推理线程数（每 RPC 共享 OnlineRecognizer，但每条 stream 独立）");
DEFINE_int32(grpc_threads, 8,
             "gRPC server 完成队列线程数；建议 = CPU 核心数");
DEFINE_int32(max_concurrent_sessions, 64,
             "服务端同时活跃 session 上限；超出新连接以 RESOURCE_EXHAUSTED 拒绝");
DEFINE_int32(session_idle_timeout_sec, 300,
             "session 多久没有音频帧自动断流，避免悬挂");

}  // namespace asr_service
