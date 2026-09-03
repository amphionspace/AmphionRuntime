# Android TTS 前端后续回归（2026-09-03）

默认 JVM 套件已无失败：103 项，100 PASS、3 项原有 SKIP。Release AAR 和新增真机测试 APK 构建通过。**最终 Android 真机门禁未执行，PR 仍为草稿，不作发布或合入验收。** 当前结果见 [report.json](report.json)，逐用例状态见 [jvm-results.json](jvm-results.json)。[前序记录](../negative-temperature-20260903/README.md)保留原样，不用旧二进制真机 PASS 替代本轮验收。

## 独立修复与不变量

- `2faa6158`：年份先转成汉字后，月份规则仍只匹配阿拉伯数字年份，导致月份数字读法和 token 边界错误。匹配扩展到已经展开的年份；覆盖阿拉伯/汉字年份、前导零月份和十二月，两条前端入口均逐项比较完整 token 数组。未改通用数字或模型规则。
- 同一数字测试组拆出版本号、路径和 URL 独立断言。技术数字的逐位读法、分隔停顿及英文 `UNDERSCORE` 已由 `75e48aee` 引入，且由邻近技术文本测试约束；这里修正过期参考读法，补齐 URL 参考文本的数字读法，没有把 token 精确比较换成非空或宽松匹配。
- `cc2be67a`：实际运行的 `splitRawForStreaming` 不再于 50 字处拆断英文词、URL、版本号、文件路径和数字。50 字改为分段目标，普通无标点中文仍按 50 字切分；不可拆 token 可越过目标，SDK 原有 10000 字输入限制不变。标点和结束引号随前段保留；未修改模型、资源或旧的非运行时分句入口。
- `530a41a2`：扩展现有 instrumentation 用例，保留 7 项负温度 native TN 文本/token 断言，增加 4 项日期 token 断言及跨 50 字 URL 分段比较，公共 SDK 合成文本同时包含温度、日期和 URL。保留唯一 start、非空 PCM、唯一 complete、无 error 及 shutdown 检查。**新增用例仅构建通过，未在真机执行。**

## 本机证据

| 阶段 | 结果 | 日志 |
| --- | --- | --- |
| 日期新增用例，修复前 | FAIL | [calendar-red.log](calendar-red.log) |
| 日期同条件，修复后 | PASS | [calendar-green.log](calendar-green.log) |
| 数字/日期独立比较 | PASS | [numeric-contracts.log](numeric-contracts.log) |
| 日期阶段默认套件 | 101 项：98 PASS / 3 SKIP | [numeric-full.log](numeric-full.log) |
| 分段新增两用例，修复前 | 2 FAIL | [split-red.log](split-red.log) |
| 分段同条件，修复后 | PASS | [split-green.log](split-green.log) |
| 最终默认套件 | 103 项：100 PASS / 3 SKIP | [split-full.log](split-full.log) |
| Release AAR、Debug instrumentation APK | PASS | [build-final.log](build-final.log) |

JVM 套件使用测试词典及无 native TN 的前端路径，不能据此宣称 native TN 或合成质量已验证。3 项原有跳过分别是：未提供输入的 Android golden parity、未提供输入的 round15 发音语料，以及原已 `@Ignore` 的 Python golden badcase 比较。本轮未新增跳过或调整堆内存。

运行代码在 `cc2be67a` 后未变；后续 `530a41a2` 只扩展真机测试，因此复用本机通过证据，不重复跑未变更的 JVM 用例。APK/AAR 基于 `530a41a2270ccfd7eb16cf074838335685aa474b` 构建。SDK 版本 3.0、模型资源版本 0.1.0、Android debug 测试签名、正常 TTS-only 授权及外置资源组包规则均未改变。二进制和模型 manifest 校验值见 report；后续只改文档不使这些结果失效。

## 最小剩余真机门禁

设备重连后使用 report 对应测试 APK，模型按前序记录写入应用私有 workPath。不得复用旧 APK，不能关闭授权或放宽存储权限。执行：

```bash
adb shell am instrument -w -r \
  -e class com.lits.tts.sdk.internal.NegativeTemperatureDeviceTest \
  -e workPath /data/user/0/com.lits.tts.sdk.test/files/tts-contract \
  com.lits.tts.sdk.test/androidx.test.runner.AndroidJUnitRunner
```

保存应用私有目录下新生成的 `frontend-contract-<timestamp>.json`、完整 instrumentation 输出、设备/系统版本和二进制 SHA-256；失败现场不可覆盖。若运行代码、native 库、模型或测试 APK 内容改变，相关真机证据必须重建；仅文档变更不重跑。

未覆盖完整发音语料、超长技术 token 的端侧延迟/内存、长稳压、Harmony 真机和 Release AAR 宿主验收，不声称全场景完成。合入仍需当前 HEAD CI、全部 review threads 检查，以及约定的最终 Android SDK 真机门禁。
