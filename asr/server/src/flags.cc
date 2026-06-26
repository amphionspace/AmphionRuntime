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
DEFINE_int32(max_active_paths, -1,
             "覆盖 manifest 的 max_active_paths（modified_beam_search 束宽）；-1 表示用 manifest 值");
DEFINE_string(decoding_method, "",
              "覆盖 manifest 的 decoding_method，例如 greedy_search / modified_beam_search；空表示用 manifest 值");
DEFINE_double(endpoint_rule1_min_trailing_silence, 2.4,
              "endpoint 规则1：句尾静音阈值（秒）；纯静音兜底");
DEFINE_double(endpoint_rule2_min_trailing_silence, 1.2,
              "endpoint 规则2：已识别出内容后的句尾静音阈值（秒）；"
              "cascade 下主控喂给 vLLM 的句子颗粒");
DEFINE_double(endpoint_rule3_min_utterance_length, 20.0,
              "endpoint 规则3：单段最长语音强制切断（秒）");

}  // namespace asr_service
