# Speaker VAD Enhance 启动优化真机证据

- 设备：Mate 80，HarmonyOS 6.1.0.135
- 语料：`asr/test-fixtures/target-speaker-customer-cases`
- 最终签名 HAP SHA-256：`7b4aa60a5f4512a42027befea6b436674e913445e9fe1ba087f96f4c2be4b1d6`

目录说明：

- `pre-fix`：修复前 200 ms 热启动门禁红灯。
- `reload`：修复后热复用以及 `unloadModel` / `unloadRuntime` 真实冷重载。
- `cancel`：推理中取消和下一轮恢复。
- `content`：C1/C2/C3 内容及生命周期回归。
- `preload`：最终 HAP 显式预加载后 19 ms 启动门禁。

每组保留 `report.json`、逐轮 `result.txt`、`memory.csv`、`hilog.txt`、输入清单和哈希映射。
PCM 未重复提交；源 WAV 已在上述测试语料目录中入库，可按 `payload/corpus.json` 的 SHA-256
复核输入一致性。
