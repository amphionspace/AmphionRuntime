# 完整发音语料对照基线 — 2026-09-03

结论：675 条采集完成，但严格音素对照 **未通过**：380 条完全一致、295 条存在差异、0 条执行错误。56.30% 是与这份历史 golden 的整句音素序列完全匹配率，不是音频质量评分，也不等于确认了 295 个 SDK 缺陷。

本轮只新增报告门禁与基线证据，SDK、模型和 golden 均未修改。

## 为什么不能看 instrumentation 的 OK

既有 `PronunciationRound15FrontendDeviceTest` 最后只断言读到了数据；当前实际报告有 295 条差异，仍返回 `OK (1 test)`。这个返回值只能说明采集完成。

新增 `tts/tools/android/check_pronunciation_report.py` 要求预期条数完整、全部匹配、fail/error 均为 0，才返回 0；不加容错比例、不丢弃不匹配样例。7 项本机测试覆盖全匹配、实际 295 差异、执行错误、条数不足/超出、空集、缺字段和统计不一致。对本次真实 summary 返回 exit 1，正确阻止误放行。

```bash
python3 tts/tools/android/check_pronunciation_report.py \
  --summary tts/android/reports/pronunciation-corpus-20260903/device-summary.json \
  --expected-total 675
```

预期输出为 FAIL；不要将它包装成成功。完整部署/采集流程见[批测说明](../../docs/BATCH_TESTING.md#5-运行发音正确性批测)。

## 分类结果

| 类别 | 条数 | 完全一致 | 有差异 |
| --- | ---: | ---: | ---: |
| en-core | 60 | 60 | 0 |
| frontend-rules-technical | 90 | 53 | 37 |
| known-regression | 10 | 7 | 3 |
| mixed-zh-en | 80 | 49 | 31 |
| polyphone-surname-proper | 110 | 90 | 20 |
| symbols-unicode-failsoft | 75 | 30 | 45 |
| tn-numeric-date-money-unit | 170 | 52 | 118 |
| zh-core | 80 | 39 | 41 |

## 差异分流，尚未豁免

[triage.json](triage.json) 保存了所有 295 条差异的分组 ID，仅用于安排排查，不改总差异数：

- 15 条负温度旧答案冲突：golden 仍包含“负”的 `fu4`，而实际是“零下”的 `ling2 xia4`。当前“零下”契约已经由 PR #187 的[负温度门禁](../frontend-review-20260903/README.md)确认，不应为了匹配旧答案撤销修复；这些行仍可能同时包含其他差异。
- 110 条末尾音调数字不同、其余符号序列一致，需按变调/分词上下文核查，不能直接认定哪一侧正确。
- 170 条其他音素序列差异，混有文本规范化、多音字、技术片段等问题。值得优先定位的样例包括：
  - `v3-parity-zh-core-002`：音量“调到”的 `tiao2/diao4` 差异。
  - `v3-parity-frontend-rules-technical-002`：路径里的斜杠及 `.pcm` 与“或”/“厘米”的差异。
  - `v3-parity-known-regression-001`：股票代码 600519 的逐位读法与数值读法差异。
  - `v3-parity-known-regression-009`：“串行”与 requestId 的读法差异。

以上是候选定位方向，不是已完成的根因判断。后续用相同文本、参数和前端阶段输出隔离首个分叉，不重复播放或盲目批量修改词典。

## 冻结与证据

- 门禁代码提交：`f6e84fd6ec39973db2f31adb3eed2d9a5e77a5bf`；设备执行时 main 为 `45e4398b7a64a2a41fcfcb059946ca193ef0d3a9`。
- 复用已安装 SDK 测试 APK，构建来源 `e7910d69`；从该提交到执行时 main 的 SDK 源码没有差异，APK SHA-256 与手机一致。无需重新构建或安装。
- vivo V2505A / Android 16，前台 AndroidX EmptyActivity，`useTn=true`，外置资源版本 0.1.0，SDK 3.0。
- APK 中打包的 675 条语料与仓库源文件 SHA-256 一致。测试 14.525 秒；没有合成或保存 PCM。
- [device-results.jsonl](device-results.jsonl)：完整 675 条期望/实际音素、tokens 和首次差异。
- [device-summary.json](device-summary.json)：手机原始统计和示例；两份原始文件的 SHA-256 均与手机文件一致。
- [device-test.log](device-test.log)、[checker-tests.log](checker-tests.log)、[checker-result.log](checker-result.log) 分别保留采集结束、门禁自身单测和真实报告被拒绝的证据。
- [report.json](report.json) 区分采集完成、门禁实现验证通过和发音严格对照失败，记录源码、语料、二进制及证据哈希。

此基线不替代公开 SDK 合成/生命周期门禁、主观发音听测、全量稳定性、后台恢复或长稳压；此前的局部契约通过仍有效，但不能扩写成完整发音验收通过。
