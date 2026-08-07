# Speaker VAD Enhance 最终对照证据

本目录补齐最终评估所用的 `main` Speaker VAD 真机基线：

- `main-default`：`main@1ca9108`，默认 `0.35 / 1500 ms / 500 ms`。
- `main-short-window`：同一基线，只把窗口/步长改为 `1000 ms / 300 ms` 的研究探针。

两组均使用 Mate 80、20 ms 实时写入以及
`asr/test-fixtures/target-speaker-customer-cases` 中的三段注册音频和 C1/C2/C3。每组保留
`report.json`、逐轮结果、内存、hilog 和输入哈希映射；PCM 未重复提交。

当前分支增强链路的对应证据位于：

- `../20260807-startup-optimization/content`：C1/C2/C3 内容、CPU、RSS 和实时块耗时。
- `../20260807-startup-optimization/preload`：最终签名 HAP 的预加载启动耗时。
- `../20260807-startup-optimization/cancel`：推理中取消后的瞬时资源峰值与恢复。
