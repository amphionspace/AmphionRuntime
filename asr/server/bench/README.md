## asr-service 压测

`bench_concurrent.py` 模拟 N 路并发流式识别，输出：

| 指标 | 含义 |
| --- | --- |
| sessions | 总完成 session 数 |
| failures | 失败 session 数 |
| audio_seconds | 累计推理音频时长（秒） |
| first_partial_ms | 首包延迟分位数 |
| final_ms | final 延迟分位数 |
| rtf | RTF（decode_time / audio_duration）分位数 |

## 准备

1. 装依赖：
   ```bash
   pip install grpcio grpcio-tools protobuf psutil
   ```
2. 生成 python proto stub（一次性）：
   ```bash
   cd /path/to/sherpa-onnx
   python -m grpc_tools.protoc -I asr/server/proto \
       --python_out=asr/server/bench \
       --grpc_python_out=asr/server/bench \
       asr/server/proto/asr.proto
   ```
3. 准备 WAV：把任意 16k mono WAV 放到 `shared/regression-set/short/`（或自指定）

## 跑压测

```bash
python asr/server/bench/bench_concurrent.py \
    --target=localhost:50051 \
    --wav-dir=shared/regression-set/short \
    --concurrency=16 \
    --duration=60 \
    --report=/tmp/bench-report.json
```

## 容量规划参考

```
单实例 4 vCPU / 4 GB / arm64:
  - 单流 RTF (greedy):   ~0.20
  - 单流 RTF (mod_beam): ~0.35
  - 并发上限:            ~50（CPU 跑满前的可用并发）
  - 内存峰值:            ~700 MB / pod
```

实际数字以你公司压测报告为准。建议每次模型 / SDK 升级都重跑压测并归档到 [bench/reports/](reports/) 目录。
