#include "flags.h"

namespace asr_service {

DEFINE_string(listen, "0.0.0.0:50051",
              "gRPC 服务监听地址，host:port");
DEFINE_string(metrics_listen, "0.0.0.0:9090",
              "Prometheus exporter 监听地址；空字符串关闭");
DEFINE_string(manifest, "/etc/asr-service/manifest.json",
              "模型 manifest.json 绝对路径；schema 与 shared/api-spec/manifest.schema.json 对齐");
DEFINE_string(provider, "cpu",
              "ONNX Runtime execution provider，例如 cpu 或 cuda");
DEFINE_string(encoder_precision, "auto",
              "encoder/joiner 精度选择：auto|int8|fp16|fp32；"
              "auto 在 cuda 下优先 fp16->fp32->int8，在 cpu 下优先 int8->fp32->fp16");
DEFINE_int32(num_threads, 4,
             "OnlineRecognizer 推理线程数（每 RPC 共享 OnlineRecognizer，但每条 stream 独立）");
DEFINE_int32(grpc_threads, 8,
             "gRPC server 完成队列线程数；建议 = CPU 核心数");
DEFINE_int32(decode_workers, 1,
             "单进程内 DecodeEngine 分片数（每分片独立 recognizer + worker 线程，共享 CUDA context）");
DEFINE_int32(max_concurrent_sessions, 64,
             "服务端同时活跃 session 上限；超出新连接以 RESOURCE_EXHAUSTED 拒绝");
DEFINE_int32(max_batch_size, 64,
             "DecodeEngine 单次批量解码的最大 stream 数");
DEFINE_int32(loop_interval_ms, 5,
             "DecodeEngine 凑批等待窗口，越大吞吐越好但延迟越高");
DEFINE_int32(session_idle_timeout_sec, 300,
             "session 多久没有音频帧自动断流，避免悬挂");
DEFINE_int32(max_active_paths, -1,
             "覆盖 manifest 的 max_active_paths（modified_beam_search 束宽）；-1 表示用 manifest 值");
DEFINE_string(decoding_method, "",
              "覆盖 manifest 的 decoding_method，例如 greedy_search / modified_beam_search；空表示用 manifest 值");

}  // namespace asr_service
