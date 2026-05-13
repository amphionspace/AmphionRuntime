## ASR gRPC 服务端（Linux）

公司流式 ASR 服务端实现，基于 [sherpa-onnx cxx-api](../../third_party/sherpa-onnx/sherpa-onnx/c-api/cxx-api.h) + grpc++。

`sherpa-onnx` 通过仓库根的 `third_party/sherpa-onnx` git submodule 引用上游 pinned tag（首期 v1.13.1），公司侧不修改其源码。

## 设计目标

- 与 Android / iOS SDK 共用同一份模型 + manifest（[shared/api-spec/manifest.schema.json](../../shared/api-spec/manifest.schema.json)，错误码同步走 [shared/api-spec/errcodes.yaml](../../shared/api-spec/errcodes.yaml)）
- 双向流 gRPC 接口（[proto/asr.proto](proto/asr.proto)）
- 单实例并发：CPU 推理用线程池，I/O 用 grpc 异步
- 运维：健康检查 + Prometheus metrics + 优雅关闭

## 目录

```
server/asr-service/
├── CMakeLists.txt
├── README.md
├── proto/
│   └── asr.proto
├── src/
│   ├── main.cc                # 进程入口 + grpc Server 启停
│   ├── asr_service.{h,cc}     # AsrService gRPC 实现
│   ├── recognizer_factory.{h,cc}  # 按 manifest 加载 OnlineRecognizer
│   ├── manifest.{h,cc}        # manifest.json 解析（与三端共用 schema）
│   ├── metrics.{h,cc}         # Prometheus exporter（活跃 session、RTF）
│   └── flags.{h,cc}           # gflags 解析
├── deploy/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── prometheus.yml
│   └── helm/                  # k8s Helm chart
└── bench/
    └── bench_concurrent.py    # gRPC 客户端压测
```

## 编译

依赖：

- gcc 11+ / clang 15+
- cmake 3.18+
- protoc 3.21+
- grpc 1.56+ (含 grpc_cpp_plugin)
- nlohmann/json （manifest 解析）
- prometheus-cpp （metrics）

构建步骤（在 sherpa-asr-sdk 仓库根目录执行）：

```bash
# 0) 第一次 clone 后初始化 submodule
git submodule update --init --recursive

# 1) 编译 sherpa-onnx 的 cxx-api 到 third_party/sherpa-onnx/build-linux/install
mkdir -p third_party/sherpa-onnx/build-linux
cd       third_party/sherpa-onnx/build-linux
cmake -DCMAKE_BUILD_TYPE=Release \
      -DSHERPA_ONNX_ENABLE_BINARY=OFF \
      -DSHERPA_ONNX_ENABLE_C_API=ON \
      -DSHERPA_ONNX_ENABLE_TTS=OFF \
      -DSHERPA_ONNX_ENABLE_PYTHON=OFF \
      -DSHERPA_ONNX_ENABLE_GPU=OFF \
      -DBUILD_SHARED_LIBS=ON \
      -DCMAKE_INSTALL_PREFIX=$(pwd)/install ..
make -j$(nproc) install
cd ../../..

# 2) 编译本服务（CMakeLists.txt 接口不变，只通过 -DSHERPA_ONNX_DIR 注入路径）
mkdir -p server/asr-service/build && cd server/asr-service/build
cmake -DSHERPA_ONNX_DIR=$(realpath ../../../third_party/sherpa-onnx/build-linux/install) \
      -DCMAKE_BUILD_TYPE=Release ..
make -j$(nproc)
cd ../../..

# 3) 启动
./server/asr-service/build/asr_service \
    --listen=0.0.0.0:50051 \
    --manifest=/etc/asr-service/manifest.json \
    --num_threads=4 \
    --metrics_listen=0.0.0.0:9090
```

升级 sherpa-onnx 版本后，需要重新跑步骤 1 让 install 目录跟着 submodule HEAD 走（或者直接 `rm -rf third_party/sherpa-onnx/build-linux` 后再来）。

## 关键约定

- 第一帧 `PcmRequest` 必须是 `SessionConfig`，否则服务端用 `INVALID_ARGUMENT (1001)` 关闭流
- 音频帧建议 100 ms 一个；过大延迟变高，过小 syscall 多
- `update_hotwords` 在两段话之间发；当前 utterance 的 partial 会被丢弃
- 服务端 5 分钟无数据自动断流，归 `SAMPLE_RATE_MISMATCH (3002)` / `DECODE_FAILED (3003)`

## 运维

- `/healthz` HTTP 端点（独立于 gRPC port），k8s liveness 用
- Prometheus metrics（默认 :9090/metrics）：
  - `asr_active_sessions{}` Gauge
  - `asr_partial_total{model_id}` Counter
  - `asr_final_total{model_id}` Counter
  - `asr_rtf{model_id, quantile}` Summary
  - `asr_decode_latency_ms{model_id, quantile}` Summary
  - `asr_error_total{model_id, code}` Counter

## 与三端 SDK 的对齐

| 维度 | Android | iOS | 服务端 |
| --- | --- | --- | --- |
| 模型 manifest | 同一份 manifest.json | 同 | 同 |
| tokens 协议 | 同 | 同 | 同 |
| 错误码段 | AsrErrorCode | AsrErrorCode | proto AsrError.code |
| 热词协议 | hotwords 字符串\n分隔 :score | 同 | HotwordSpec.words_text |
| 解码方法 | greedy / mod_beam_search | 同 | DecodingMethod enum |
