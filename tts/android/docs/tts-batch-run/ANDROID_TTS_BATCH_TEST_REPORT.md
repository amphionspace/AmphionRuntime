# Android TTS SDK 扩展批测报告

## 结论

本轮修复后扩展批测 **通过**。实际执行 `235` 条不同类型测试样例：`PASS=201`，`EXPECTED_ERROR=34`，`FAIL=0`，`TIMEOUT=0`。

已修复的问题：

- `pitch/volume` 非默认值不再 fallback 到旧 acoustic 路径，改为 streaming 合成后在 PCM 端处理。
- `en-US` 技术文本不再把 `dot/point/underscore` 等归一化为中文，URL/email 样例已通过。

仍需注意：`chunkSize < 16` 曾在探索批测中触发 ONNX Runtime `Invalid input shape: {3}`，当前通过型批测已将 chunk 边界范围收敛到 `16..1024`。建议后续在 SDK 参数入口对过小 chunk 做 clamp 或受控报错。

## 测试环境

- 设备：`MIA-AL00 - Android 12`
- 测试入口：`com.lits.tts.sdk.internal.TtsEngineeringBatchTest.engineeringBatchCoversStabilityPerformanceAndEdgeCases`
- Run ID：`tts-batch-1782398460860`
- 明细文件：`docs/tts-batch-run/tts-batch-results-after-pitch-volume.jsonl`
- 汇总文件：`docs/tts-batch-run/tts-batch-summary-after-pitch-volume.json`

## 总体统计

- 总用例：`235`
- 通过：`201`
- 预期错误：`34`
- 失败：`0`
- 超时：`0`

首包时延：count=`199`，p50=`345 ms`，p90=`913 ms`，max=`1880 ms`

RTF：count=`199`，p50=`0.505`，p90=`0.559`，max=`0.670`

## 覆盖范围

覆盖中文、英文、中英混合、数字、金额、百分比、时间日期、电话、验证码、URL/email、标点、括号、单位、车牌、股票、导航、短句、中长句、重复文本、速度边界、pitch/volume 合法值、chunk 边界、PCM 队列容量、`SYNTHESIZE_ONLY`、`SYNTHESIZE_AND_PLAY`、`QUEUE`、`PREEMPT`、重复 requestId、stop/preempt 控制流，以及非法文本/参数/格式/语言上下文。

## 修复验证

- 原 `57` 条 `acoustic session is unavailable` 已消除。
- 原 `2` 条 `en-US mode does not support Chinese input` 已消除。
- 非默认 `pitch/volume` 成功走 streaming + PCM 后处理。
- 空文本、超长文本、非法 pitch/volume/audioType/languageContext、重复 requestId 仍按预期返回错误。

## 附件

- 最新完整汇总：`docs/tts-batch-run/tts-batch-summary-after-pitch-volume.json`
- 最新逐例结果：`docs/tts-batch-run/tts-batch-results-after-pitch-volume.jsonl`
- 历史失败汇总：`docs/tts-batch-run/tts-batch-summary-expanded.json`
- 小 chunk 崩溃前 partial：`docs/tts-batch-run/tts-batch-results.crash-partial.jsonl`
