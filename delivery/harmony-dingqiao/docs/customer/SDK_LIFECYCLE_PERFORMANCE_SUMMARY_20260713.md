# Harmony 离线 ASR SDK 生命周期性能数据

**10 轮完整生命周期测试：PASS 10/10**

| 接口 / 采样阶段 | 接口耗时 p50 | 接口耗时 p95 | VmRSS 净增量 | RssAnon 净增量 |
| --- | ---: | ---: | ---: | ---: |
| `setLicense()` 后 | 23.5 ms | 27.8 ms | +7 MiB | +1 MiB |
| `prepareRuntime()` 后 | 1.0 ms | 2.1 ms | +7 MiB | +1 MiB |
| 新进程首次 `createEngineAsync()` 后 | 601.5 ms | 765.0 ms | +88 MiB | +65 MiB |
| 同配置模型复用后 | 3.0 ms | 4.0 ms | — | — |
| 推理阶段离散高水位 | — | — | +274.5 MiB | +96 MiB |
| `unloadModel()`（内存为返回后 400 ms） | 49.5 ms | 55.6 ms | +91 MiB | +77.5 MiB |
| `unloadRuntime()` | <1 ms | 1.0 ms | — | — |
