# Harmony 离线 ASR SDK 生命周期性能数据

**10 轮完整生命周期测试：PASS 10/10**

## 接口耗时

| 阶段 | p50 | p95 |
| --- | ---: | ---: |
| `setLicense()` | 23.5 ms | 27.8 ms |
| `prepareRuntime()` | 1.0 ms | 2.1 ms |
| 新进程首次 `createEngineAsync()` | 601.5 ms | 765.0 ms |
| 同配置模型复用 | 3.0 ms | 4.0 ms |
| `unloadModel()` | 49.5 ms | 55.6 ms |
| `unloadRuntime()` | <1 ms | 1.0 ms |

## 内存净增量

| 阶段 | VmRSS | RssAnon |
| --- | ---: | ---: |
| `setLicense()` / `prepareRuntime()` 后 | +7 MiB | +1 MiB |
| 首次模型加载后 | +88 MiB | +65 MiB |
| 推理阶段离散高水位 | +274.5 MiB | +96 MiB |
| `unloadModel()` 后 400 ms | +91 MiB | +77.5 MiB |
