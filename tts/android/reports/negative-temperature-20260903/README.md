# Android TTS 负温度回归（2026-09-03）

负温度修复已通过前序提交的针对性 JVM 和 Android 真机验证；旧测试入口已对齐，词典键集合复制导致的内存失败在同套回归中消失。**完整 JVM 剩 1 个数字测试组失败；最后的内存改动尚未完成真机回归，因为 Android 已断开。当前分支不具备完整发布或合入条件。** 机器可读结果见 [report.json](report.json)，前序真机逐条文本与回调见 [device-report.json](device-report.json)。

## 根因与范围

`气温 -24.5 度` 在 `LitsTnNormalizer.prepareInputForTn` 中先被通用负数规则改成 `气温 负24.5 度`，后续仅匹配 `-` 的温度规则无法识别。JVM 无 native TN 的测试还会逐位读数字，因此旧数字测试的第 2 条比较失败；带空格的温度范围同样受影响。

将原有温度规则抽为一个共享函数，在通用负数规则之前保护温度语义；保留 `encodeNormalized` 原有温度处理。空格不再改变温度读法，包括负号两侧、范围的“到”两侧。正温度、非温度负数、比分、英文入口未改；没有修改模型、资源、参数或授权策略。

Harmony 已检查：其 `DingqiaoTnNormalizer.prepareInput` 本来就先调用 `preprocessZhMixedInput`，不走 Android 此处的通用负号前置路径。本次不修改 Harmony，也不声称已完成跨平台全部温度边界验收。

后续两个独立提交：

- 分句测试改为实际合成调用的 `splitRawForStreaming`，严格比较原始文本与标点；英文标点与默认 50 字长度上限分开检查。包名中的 `LITS` 按现有技术 token 规则逐字母读，与普通小写单词读法分别断言，不改变发音实现。
- 完整回归在 `resources()` 的键集合相加处出现 `OutOfMemoryError`。这里只为求最大词长，无需复制或去重；改用惰性遍历，最大值与空集合默认值保持不变。没有增加测试堆内存，也没有改缓存策略；同套 97 项用例中该失败消失，原有词典和多音字用例继续通过。

## 验证

- 修复前：[unit-red.log](unit-red.log)，新增的前处理断言稳定失败，相邻数值场景通过。
- 修复后：[unit-green.log](unit-green.log)，7 种负温度写法及相邻数值场景通过。
- 第一阶段完整 JVM：[unit-regression.log](unit-regression.log)，96 项：88 通过、5 失败、3 跳过。
- 对齐旧测试入口后：[unit-current-path.log](unit-current-path.log)，97 项中剩数字组失败，另暴露词典键复制内存失败；完整失败栈保留在 `non-canonical/coverage-oom.xml`。
- 最终完整 JVM：[unit-final.log](unit-final.log)，97 项：93 通过、1 失败、3 跳过。数字组已越过负温度断言，停在日期断言；不能据此把整组标成通过。日志中的构建失败来自此组，之后单独完成了 APK/AAR 构建，没有忽略失败断言。
- vivo V2505A / Android 16：[device-test.log](device-test.log)，原生 TN 确实执行；7 种写法的规范化文本、token 序列通过。公共 SDK 在有效 TTS 测试授权下合成 1 个请求，顺序为 `start → 7 个非空 PCM 回调 → SYNTHESIS_COMPLETE`，无 error，随后 shutdown。
- Release AAR 编译通过，但本次真机验证对象是 Debug SDK instrumentation APK，不是 Release AAR 宿主验收。

最终代码、测试 APK、Release AAR 均基于 `429352527867841c62570db4db5a7c988fad39e7`，APK/AAR 已构建；安装时 `adb` 返回没有设备，当前二进制真机门禁待补。温度真机 PASS 属于内存修复前的 `70ac0301d0f8e3dc55a81e878412f7728e701bcb`，只作为前序证据，不作为最终二进制验收。后续仅 README/报告变更不影响这些二进制。各阶段 APK、AAR、模型 manifest 与真机报告 SHA-256 见 `report.json`。未提交授权文本或生成的 PCM。

## 复现入口

在 `tts/android/` 构建 `:sdk:assembleDebugAndroidTest` 并安装 `sdk-debug-androidTest.apk`。测试 APK 需要已有的 `lic/tts_only.lic` 测试授权，不能关闭授权校验。

将生成的 `external-resources/tts/` 放入测试应用私有工作目录的 `tts/` 子目录。例如：

```text
/data/user/0/com.lits.tts.sdk.test/files/tts-contract/tts/<model-id>/0.1.0/manifest.json
```

```bash
adb shell am instrument -w -r \
  -e class com.lits.tts.sdk.internal.NegativeTemperatureDeviceTest \
  -e workPath /data/user/0/com.lits.tts.sdk.test/files/tts-contract \
  com.lits.tts.sdk.test/androidx.test.runner.AndroidJUnitRunner
```

资源通过测试应用的 `run-as` 身份写入其私有目录，不放宽存储权限。失败的工作目录配置和未初始化授权现场保存在 `non-canonical/`；这些是测试接入失败，不是 PASS 证据。

## 剩余工作

1. 数字组中的日期 token 边界、版本号、路径/URL 比较需独立定位，保持发音断言，不用整体非空替代。
2. 默认 50 字长度限制可能落在英文单词或 URL 内部：诊断样例中 `example.com` 曾被拆成 `ex` 与 `ample.com`。本次只验证长度与文本不丢失，不宣称跨段发音正确；后续需单独处理技术 token 的长度边界。

未修改剩余数字组的期望、未新增跳过、未放宽断言，也未运行无关的长时或多语种压力测试。
