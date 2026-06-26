# ASR 服务端 GPU 并发压测与推荐参数

本文记录 Linux 流式 ASR 服务端（`asr/server`）在 NVIDIA H20 上的并发压测结论与推荐部署参数。压测口径为“模拟真实音频流”：客户端按 1x 实时速率（100ms 一帧、`time.sleep` 节流）推送音频，统计单进程能同时稳定承载多少路实时流。

## 一、结论速览

推荐生产配置（单进程）：

```bash
asr_service \
  --provider=cuda \
  --encoder_precision=fp32 \
  --decode_workers=2 \
  --max_active_paths=2 \
  --num_threads=4 \
  --grpc_threads=16 \
  --max_batch_size=130 \
  --max_concurrent_sessions=200 \
  --loop_interval_ms=5
```

在本机共享显存条件下，该配置可稳定支撑约 108 路并发实时流（RTF p50 ≤ 1.01），相比初始 int8 单引擎基线（约 37 路）提升约 2.9 倍。

实时性判定口径：

| 口径 | 阈值 | 含义 |
| --- | --- | --- |
| 严格实时 | rtf_p50 ≤ 1.01 | 解码耗时几乎不落后于音频时长，端到端延迟稳定 |
| 软实时 | rtf_p50 ≤ 1.05 | 轻微落后但可接受，延迟略升 |
| 失效 | rtf_p50 > 1.05 | 跟不上实时流，延迟持续累积 |

RTF（Real-Time Factor）= 单帧解码耗时 / 该帧音频时长；p50/p90 为该并发下所有帧的分位数。

## 二、测试环境

| 项 | 值 |
| --- | --- |
| GPU | NVIDIA H20，96GB；与其它 LLM 服务（vLLM/Triton）共享，可用显存约 6.5-7.5GB |
| CPU | 16 vCPU |
| 模型 | amphion-zh-en-streaming（zipformer2 transducer，chunk32-left256，中英混合） |
| 推理后端 | sherpa-onnx 1.13.1 + onnxruntime-gpu 1.24.4（CUDA 12 / cuDNN 9） |
| 解码方法 | modified_beam_search |
| 采样率 | 16000Hz，单声道，PCM_S16LE，帧长 100ms |
| 压测脚本 | `asr/server/bench/bench_concurrent.py`（客户端 1x 实时节流） |

## 三、关键结果

不同配置下的实时并发上限：

| 配置 | 精度 | 引擎数 | 束宽 | 严格实时(≤1.01) | 软实时(≤1.05) |
| --- | --- | --- | --- | --- | --- |
| 初始基线 | int8 | 1 | 4 | 低于 37 | 约 37 |
| 切 fp32 | fp32 | 1 | 4 | 约 44 | 约 52 |
| 多引擎 | fp32 | 2 | 4 | 约 80 | 约 96 |
| 多引擎 + 降束宽（推荐） | fp32 | 2 | 2 | 约 108 | 约 112 |

## 四、详细数据

每行一个并发档位：sess 为成功建立的会话数，fail 为失败数，gpu_mean/gpu_peak 为 GPU 利用率均值/峰值（%），mem_peak 为设备总显存占用峰值（MiB，含其它租户）。

int8 单引擎（初始基线）：

| 并发 | sess | fail | rtf_p50 | rtf_p90 | gpu_mean | gpu_peak | mem_peak |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 37 | 37 | 0 | 1.0144 | 1.0147 | 8.5 | 23 | 91917 |
| 44 | 44 | 0 | 1.1777 | 1.1779 | 8.5 | 22 | 92941 |

fp32 单引擎：

| 并发 | sess | fail | rtf_p50 | rtf_p90 | gpu_mean | gpu_peak | mem_peak |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 37 | 37 | 0 | 1.0049 | 1.0051 | 4.7 | 27 | 92945 |
| 44 | 44 | 0 | 1.0050 | 1.0052 | 5.0 | 29 | 92945 |
| 52 | 52 | 0 | 1.0462 | 1.0465 | 7.8 | 31 | 92945 |
| 60 | 60 | 0 | 1.1635 | 1.1638 | 6.8 | 30 | 92945 |

fp32 双引擎，束宽 4：

| 并发 | sess | fail | rtf_p50 | rtf_p90 | gpu_mean | gpu_peak | mem_peak |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 64 | 64 | 0 | 1.0049 | 1.0053 | 11.0 | 42 | 95717 |
| 80 | 80 | 0 | 1.0047 | 1.0051 | 13.1 | 45 | 95717 |
| 96 | 96 | 0 | 1.0382 | 1.0456 | 14.7 | 46 | 95717 |

fp32 双引擎，束宽 2（推荐）：

| 并发 | sess | fail | rtf_p50 | rtf_p90 | gpu_mean | gpu_peak | mem_peak |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 104 | 104 | 0 | 1.0046 | 1.0051 | 14.1 | 43 | 95707 |
| 108 | 108 | 0 | 1.0038 | 1.0041 | 14.2 | 50 | 96731 |
| 112 | 112 | 0 | 1.0117 | 1.0199 | 16.9 | 52 | 96747 |
| 120 | 0 | 120 | 失败（显存不足，拒绝建会话） | - | 10.8 | 51 | 97365 |

## 五、推荐参数与依据

| 参数 | 推荐值 | 依据 |
| --- | --- | --- |
| --provider | cuda | 走 GPU 推理 |
| --encoder_precision | fp32 | int8(QDQ) 在 onnxruntime CUDA EP 上算子常回退 CPU 并产生 GPU<->CPU 拷贝；切 fp32 后单引擎严格实时由约 37 升到约 44。CUDA 下 auto 在无 fp16 文件时也会落到 fp32 |
| --decode_workers | 2 | 单 worker 线程在 16 vCPU 上串行化所有 per-stream CPU 工作（fbank、beam search），是主瓶颈；开 2 个独立分片（各自 recognizer + worker，共享同一 CUDA context）把解码并行度翻倍，同束宽下严格实时约 44 升到约 80。再加分片受可用显存制约，收益递减 |
| --max_active_paths | 2 | modified_beam_search 束宽由 4 降到 2，per-stream CPU 成本约减半，中英文识别文本无明显差异，严格实时约 80 升到约 108 |
| --num_threads | 4 | 每个 recognizer 的 ORT intra-op 线程数 |
| --grpc_threads | 16 | 取 vCPU 数，保证 gRPC I/O 不成为瓶颈 |
| --max_batch_size | 130 | 单次批量解码 stream 上限，需为目标并发预留余量 |
| --max_concurrent_sessions | 200 | 准入上限，超出以 RESOURCE_EXHAUSTED 拒绝，防止过载雪崩 |
| --loop_interval_ms | 5 | 凑批等待窗口，越大吞吐越高但单帧延迟越高 |

## 六、瓶颈分析（第一性原理）

全程 GPU 利用率均值约 14%、峰值约 50%，说明瓶颈不在 GPU 算力，而在两点：

1. 可用显存。本机 H20 与其它 LLM 服务共享，可用仅约 6.5-7.5GB；并发到 120 起新建会话因显存不足被拒。独占 GPU 时该上限会显著抬高，瓶颈随之转回 CPU。
2. per-stream CPU。流式 chunk 很小，单次解码 GPU 负载轻，真正吃满的是每条流的特征提取与 beam search。因此提升手段是 CPU 并行（多分片）与降低 per-stream CPU 成本（fp32 避免 int8 回退、降束宽），而非堆 GPU。

由此推导出的优化路径与上文“关键结果”一致：fp32 → 多引擎 → 降束宽。

## 七、已验证不可取的方案

| 方案 | 结论 |
| --- | --- |
| greedy_search 配批量引擎 | 当前 sherpa-onnx 的批量解码接口 `SherpaOnnxDecodeMultipleOnlineStreams` 仅实现 modified_beam_search，greedy 会触发断言退出，不能用于批量引擎 |
| onnxconverter_common 转 fp16 | 转换出的 fp16 图在并发批量解码下严重劣化（cast-storm，大量 fp32<->fp16 转换），吞吐反降并触发 DEADLINE_EXCEEDED。如需 fp16 应从 PyTorch checkpoint 原生导出，本期不做 |

## 八、复现步骤

1. 编译（GPU）

```bash
# 编 sherpa-onnx（GPU），install 到 third_party/sherpa-onnx/build-linux-gpu/install
mkdir -p third_party/sherpa-onnx/build-linux-gpu && cd third_party/sherpa-onnx/build-linux-gpu
cmake -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=ON \
      -DSHERPA_ONNX_ENABLE_GPU=ON -DSHERPA_ONNX_ENABLE_C_API=ON \
      -DSHERPA_ONNX_ENABLE_PYTHON=OFF -DSHERPA_ONNX_ENABLE_TESTS=OFF \
      -DSHERPA_ONNX_ENABLE_BINARY=OFF -DSHERPA_ONNX_ENABLE_PORTAUDIO=OFF \
      -DSHERPA_ONNX_ENABLE_TTS=OFF -DCMAKE_INSTALL_PREFIX=$(pwd)/install ..
make -j"$(nproc)" install
cd ../../..

# 编 asr_service
mkdir -p asr/server/build && cd asr/server/build
cmake -DCMAKE_BUILD_TYPE=Release \
      -DSHERPA_ONNX_DIR=$(realpath ../../../third_party/sherpa-onnx/build-linux-gpu/install) ..
make -j"$(nproc)"
cd ../../..
```

2. 启动（推荐参数见第一节）

```bash
LD_LIBRARY_PATH=third_party/sherpa-onnx/build-linux-gpu/install/lib \
asr/server/build/asr_service \
  --listen=0.0.0.0:50051 --manifest=/path/to/manifest.json \
  --provider=cuda --encoder_precision=fp32 --decode_workers=2 \
  --max_active_paths=2 --num_threads=4 --grpc_threads=16 \
  --max_batch_size=130 --max_concurrent_sessions=200
```

manifest 的 model_dir 下需同时存在非量化的 `encoder.onnx` / `decoder.onnx` / `joiner.onnx`（fp32 路径所需）与 `tokens.txt`。

3. 压测

```bash
cd asr/server/bench
python bench_concurrent.py --target=localhost:50051 --wav-dir=/path/to/wavs \
  --concurrency=108 --duration=60 --report=report.json
```

容器化部署见 `deploy/Dockerfile.gpu` 与 `deploy/docker-compose.gpu.yml`。
