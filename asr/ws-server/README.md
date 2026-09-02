# Amphion ASR WebSocket 服务（Linux / Mac CPU 开发）

本服务提供真流式 ASR WebSocket 接口，底层使用 `sherpa-onnx` 在线 zipformer2 模型。开发阶段可在 Mac 上用 CPU 跑通全部功能；部署到 H20 时切换为 CUDA wheel、`provider=cuda` 和 fp32 模型。

## 本地运行（Mac CPU）

```bash
cd /path/to/amphion-runtime
uv venv .venv-asr-ws --python 3.11
uv pip install --python .venv-asr-ws/bin/python -e asr/ws-server

.venv-asr-ws/bin/python -m amphion_asr_ws \
  --provider=cpu \
  --manifest=asr/ws-server/deploy/manifest.local.cpu.json \
  --listen=127.0.0.1:8010 \
  --metrics-listen=127.0.0.1:9100 \
  --max-batch-size=8 \
  --max-wait-ms=10
```

单文件测试：

```bash
.venv-asr-ws/bin/python asr/ws-server/examples/ws_client.py \
  "/path/to/audio/sample.wav"
```

测试目录并生成报告：

```bash
.venv-asr-ws/bin/python asr/ws-server/examples/run_audio_suite.py \
  /path/to/audio \
  --output-dir asr/ws-server/reports/latest \
  --model-id amphion-zh-en-streaming_large_crctc_musan_zhcs_v6 \
  --model-version 1.0.0-iter-140000-avg-1-chunk-32-left-256 \
  --provider cpu
```

## WebSocket 协议

客户端先发送 JSON start 帧：

```json
{
  "type": "start",
  "trace_id": "optional-id",
  "audio_format": {
    "sample_rate": 16000,
    "encoding": "pcm_s16le",
    "channels": 1
  },
  "hotwords": "",
  "include_token_timestamps": false
}
```

之后发送二进制 PCM 帧，建议 100 ms 一帧。结束时发送：

```json
{"type":"stop"}
```

服务端返回 JSON 事件：`session_started`、`partial`、`endpoint`、`final`、`error`、`session_ended`。

## H20 CUDA 切换清单

1. 使用 GPU 镜像 `asr/ws-server/deploy/Dockerfile`，基础镜像为 `nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04`。
2. 安装 CUDA wheel：`sherpa-onnx==1.13.3+cuda12.cudnn9`。
3. 启动参数设为 `--provider=cuda`。
4. manifest 使用 `deploy/manifest.cuda.json`，模型文件选择 fp32：`encoder.onnx`、`decoder.onnx`、`joiner.onnx`。
5. 容器启动加 GPU 资源：`docker compose -f asr/ws-server/deploy/docker-compose.yml up`。
6. 用 `nvidia-smi` 确认模型加载后显存上升，避免 CPU-only wheel 静默回退。
7. 用 `examples/bench_concurrent.py` 做 50 路压测，调 `--max-batch-size` 和 `--max-wait-ms`。

## 设计约束

- CPU 和 CUDA 共用同一套 `DecodeScheduler`，所有连接通过 `decode_streams()` 批量解码。
- Mac CPU 测试用于验证协议、会话状态机、批量调度逻辑和功能正确性；50 路容量必须在 H20 上实测。
- 当前服务是单流 ASR，不做说话人分离、声纹跟踪或多人重叠分离。
