## ASR gRPC 服务端（Linux）

AmphionRuntime 的 Linux 流式 ASR 服务端实现，基于 [sherpa-onnx cxx-api](../../third_party/sherpa-onnx/sherpa-onnx/c-api/cxx-api.h) + grpc++。

`sherpa-onnx` 通过仓库根的 `third_party/sherpa-onnx` git submodule 引用上游 pinned tag（首期 v1.13.1），公司侧不修改其源码。

## 设计目标

- 与 Android / iOS SDK 共用同一份模型 + manifest（[shared/api-spec/manifest.schema.json](../../shared/api-spec/manifest.schema.json)，错误码同步走 [shared/api-spec/errcodes.yaml](../../shared/api-spec/errcodes.yaml)）
- 双向流 gRPC 接口（[proto/asr.proto](proto/asr.proto)）
- 单实例并发：CPU 推理用线程池，I/O 用 grpc 异步
- 运维：健康检查 + Prometheus metrics + 优雅关闭

## 目录

```
asr/server/
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

依赖（Ubuntu 22.04 apt 自带版本即可，已验证）：

- gcc 11+ / clang 15+
- cmake 3.18+
- protoc 3.12+（libprotobuf-dev）
- grpc 1.30+（libgrpc++-dev，含 grpc_cpp_plugin）
- nlohmann/json 3.10+（nlohmann-json3-dev，manifest 解析）
- gflags（libgflags-dev）
- prometheus-cpp（可选，metrics；默认关闭，需 -DASR_ENABLE_PROMETHEUS=ON 才编入）

GPU(CUDA) 部署额外要求：宿主装 NVIDIA 驱动；sherpa-onnx 用 -DSHERPA_ONNX_ENABLE_GPU=ON 编译，
会拉取 onnxruntime-gpu 1.24.4（需 CUDA 12 + cuDNN 9）。并发压测结论与推荐参数见 [BENCHMARK.md](BENCHMARK.md)。

构建步骤（在 amphion-runtime 仓库根目录执行）：

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
mkdir -p asr/server/build && cd asr/server/build
cmake -DSHERPA_ONNX_DIR=$(realpath ../../../third_party/sherpa-onnx/build-linux/install) \
      -DCMAKE_BUILD_TYPE=Release ..
make -j$(nproc)
cd ../../..

# 3) 启动
./asr/server/build/asr_service \
    --listen=0.0.0.0:50051 \
    --manifest=/etc/asr-service/manifest.json \
    --num_threads=4 \
    --metrics_listen=0.0.0.0:9090
```

升级 sherpa-onnx 版本后，需要重新跑步骤 1 让 install 目录跟着 submodule HEAD 走（或者直接 `rm -rf third_party/sherpa-onnx/build-linux` 后再来）。

GPU 编译：把步骤 1 的 `-DSHERPA_ONNX_ENABLE_GPU=OFF` 改成 `ON`，install 目录建议用 `build-linux-gpu/install`，
步骤 2 的 `-DSHERPA_ONNX_DIR` 指向它；步骤 3 启动加 `--provider=cuda`（其余推荐参数见 BENCHMARK.md）。

## 启动参数

| flag | 默认 | 说明 |
| --- | --- | --- |
| --listen | 0.0.0.0:50051 | gRPC 监听地址 |
| --manifest | /etc/asr-service/manifest.json | 模型 manifest 路径 |
| --provider | cpu | 推理后端：cpu 或 cuda |
| --encoder_precision | auto | encoder/joiner 精度：auto/int8/fp16/fp32（cuda 推荐 fp32） |
| --decode_workers | 1 | 进程内 DecodeEngine 分片数（每分片独立 recognizer + worker，共享 CUDA context） |
| --max_active_paths | -1 | 覆盖 manifest 的 modified_beam_search 束宽；-1 用 manifest 值 |
| --decoding_method | 空 | 覆盖 manifest 的解码方法；空用 manifest 值 |
| --num_threads | 4 | 每个 recognizer 的 ORT intra-op 线程数 |
| --grpc_threads | 8 | gRPC 完成队列线程数，建议取 vCPU 数 |
| --max_batch_size | 64 | 单次批量解码 stream 上限 |
| --max_concurrent_sessions | 64 | 活跃 session 上限，超出以 RESOURCE_EXHAUSTED 拒绝 |
| --loop_interval_ms | 5 | 批量解码凑批等待窗口（ms） |
| --session_idle_timeout_sec | 300 | session 无音频多久自动断流 |
| --metrics_listen | 0.0.0.0:9090 | prometheus exporter 地址；空关闭（metrics 需编译期开启） |

## 容器部署

GPU（推荐，并发结论见 BENCHMARK.md）：

```bash
# 在仓库根目录构建（onnxruntime-gpu 需联网下载，宿主需 NVIDIA 驱动 + nvidia-container-toolkit）
docker build -t asr-service-gpu:1.1.0 -f asr/server/deploy/Dockerfile.gpu .
docker run --rm -it --gpus all -p 50051:50051 \
    -v /abs/path/model:/etc/asr-service/model:ro \
    -v /abs/path/manifest.json:/etc/asr-service/manifest.json:ro \
    asr-service-gpu:1.1.0
# 或：docker compose -f asr/server/deploy/docker-compose.gpu.yml up --build
```

CPU：把上面的 `Dockerfile.gpu` 换成 `Dockerfile`、去掉 `--gpus all` 即可。
注意 manifest.json 的 `model_dir` 要写成容器内路径 `/etc/asr-service/model`；fp32 路径需 model_dir 下存在非量化的 `encoder.onnx`/`decoder.onnx`/`joiner.onnx`。

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
