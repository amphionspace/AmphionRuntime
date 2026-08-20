# 固定热词真机评测

该评测是 demo 内部的显式诊断入口，默认不启用。正常启动 app 或交付 HAR 不会读取本地数据集，也不会自动运行评测。

固定样本位于 `delivery/fixtures/hotword_eval_200.jsonl`，SHA-256 记录在相邻的 `.sha256` 文件中。清单包含 200 个互不重复的录音：中文、英文各 100 条，clean/noise/RIR 等 8 个分层各 25 条。清单只保存数据集相对路径、参考文本和热词，不包含开发机绝对路径或音频。

每条音频依次运行两次：

1. `baseline`：不传调用方热词；
2. `hotword`：通过 `CreateEngineParams.extraParams['sysGeneralLexicon']` 传入该条固定热词。

两次都关闭 partial 和警务 final 后处理，直接比较解码热词的作用。ZH_EN 是同一个中英双语模型，Dingqiao engine selector 使用 `zh-CN`；报告仍按 fixture 的 `zh-CN`/`en-US` 分别计算 CER/WER。

运行：

```bash
python3 delivery/harmony-dingqiao/delivery/run_hotword_device_eval.py \
  --data-root /path/to/asr-zh-en-eval-20260804/extracted
```

runner 会校验固定清单哈希、把 200 条音频转换为 16 kHz mono PCM、构建并安装签名测试载体，然后等待 400 条设备结果。输出位于 `delivery/harmony-dingqiao/build/hotword-device-eval/<run-id>/`：

- `device-result.jsonl`：设备原始 A/B 文本、耗时和错误码；
- `details.jsonl`：逐条 CER/WER 编辑距离、热词命中和改善/退化分类；
- `report.json`、`report.md`：语言级汇总；
- `payload/`：本次固定 PCM 和设备 manifest（构建目录，不提交）。

调试或失败恢复可以使用 `--start-index` 和 `--max-cases`，但正式基线应运行全部 200 条。设备端只有在 ability 参数 `hotwordEval=true` 时才加载 `HotwordDeviceEval.ets`。

若确实需要重新抽样，显式运行 `generate_hotword_eval_fixture.py --data-root ...` 并评审清单及新哈希；日常复测不得重新生成清单。
