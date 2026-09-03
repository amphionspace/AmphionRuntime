# Android TTS 前端真机验收（2026-09-03）

本轮前端修复的 Android 门禁通过，来源提交 `fcdfea97ca5fb5ba7e437e84e810290505e44df6`。默认 JVM：104 项，101 PASS、3 项原有 SKIP；Release AAR 与测试 APK 构建通过。vivo V2505A / Android 16：7 项负温度、4 项日期、URL 分段和公共 SDK PCM 合成通过。详见 [report.json](report.json)、[逐条真机结果](device-report.json)和[完整 instrumentation 输出](device-test.log)。不代表完整发音语料或完整发布矩阵通过。

## 本轮发现和修复

首次使用 `530a41a2` 的 APK 验收时，7 项温度通过，但 `出生日期1998年2月09日` 的第 44 个 token 与参考值不同。原生 TN 的实际文本是“出生日期一九九八年二月九日”，测试错误地期待“零九日”。[原生输入输出](non-canonical/tn-trace.log)和[失败报告](non-canonical/device-report.json)均保留。

定位到无原生 TN 的前端路径中两个原有特判：它们在月份、日期前导零处主动加入汉字“零”，与原生规则以及现有分隔符日期（`1998-02-09`）的读法不同。`fcdfea97` 移除这两个特判，复用现有月份/日期数值转换；不是给 native 输出补零，也不是放宽 token 比较。原生路径本身没有因此更改读法；本次新真机用例暴露了前序本机参考的错误，不能把它描述为已证明的 native 回归。

改变：数字日期的补位零不发音，两条前端入口读法一致。

保持：年份逐位读、时钟“零五分”、序列号前导零、明确写成汉字的“零”、温度规则和完整技术 token 分段。模型、授权、并发和 SDK 生命周期未修改。

验证顺序：新增日期单测[红灯](non-canonical/calendar-padding-red.log) → 局部修复和相邻数字用例[通过](calendar-padding-green.log) → [默认 JVM 全套](unit-final.log) → [构建](build-final.log) → 当前二进制真机验收。逐用例结果见 [jvm-results.json](jvm-results.json)。3 项跳过仍是之前未提供输入的两套 golden/发音语料和原已 Ignore 的 Python golden 比较，没有新增跳过。

## 系统冻结现场与受控重试

同一最终 APK 首次合成运行在较长 URL 所在段停止推进。读取现场发现整个测试进程的 `cgroup.freeze=1`、`cgroup.events` 中 `frozen=1`，21 个线程全部停在 `get_signal`；测试计时线程也冻结。系统前台是桌面。将测试应用显示到前台后，原运行恢复并报告超时，不把该轮记作通过。

完整保留[冻结诊断](non-canonical/environment-freeze.json)、[线程状态](non-canonical/frozen-thread-state.log)、[逐项结果与已有回调](non-canonical/frozen-device-report.json)和[超时输出](non-canonical/frozen-device-test.log)。原生栈读取需要 root，未提权；定位依据是可读的进程冻结状态，不是猜测模型耗时。

唯一重试条件变化：利用 APK 已内置的 AndroidX EmptyActivity 保持测试进程在前台。APK、模型、输入、SDK 参数及 60 秒超时均未改变；没有关闭系统冻结策略。该轮约 5.6 秒结束，实际合成约 2.56 秒，证伪了“该文本必然令推理线程卡死”的判断。此结果只证明前台条件下的 SDK 契约，不证明系统强制冻结时仍能按时完成。

## 公共 SDK 结果和身份

- 7 项温度检查 native TN 确实执行、规范化文本准确且 token 数组相等。
- 4 项日期检查 native TN 执行且完整 token 数组相等，包含阿拉伯/汉字年份、前导零月份与十二月。
- URL 跨 50 字边界时仍为完整一段；公共合成实际产生 5 段，完整保留 `example.com/test`。
- 一个请求：1 次 start → 21 次非空 PCM 回调（序号 0–20，共 1,112,064 字节）→ 1 次 SYNTHESIS_COMPLETE，无 error；随后 shutdown 返回。
- [TN 与 SDK 分段轨迹](tn-and-sdk-trace.log)保留原生文本、真实分段和完成时间，未提交生成 PCM 或授权文本。

APK、Release AAR 同源于上述提交；SDK 3.0 / 模型 0.1.0，Android debug 测试签名与正常 TTS-only 授权不变。安装后的 APK SHA-256 与本机构建相同；[25 个模型/前端文件](model-files.json)与本机资源逐个哈希一致。此前传输产生的 AppleDouble 元数据不是运行输入，未删除或修改资源。旧二进制 PASS 不作为当前验收。后续仅 README/报告变更无需重跑。

## 复现

安装 report 对应的 APK，按前序说明将资源写入应用私有 workPath。在一个终端执行：

```bash
adb shell am instrument -w -r \
  -e class com.lits.tts.sdk.internal.NegativeTemperatureDeviceTest \
  -e workPath /data/user/0/com.lits.tts.sdk.test/files/tts-contract \
  com.lits.tts.sdk.test/androidx.test.runner.AndroidJUnitRunner
```

instrumentation 启动后，在另一终端立即打开已内置的测试 Activity，并保持其在前台直到结束：

```bash
adb shell 'am start -W -n com.lits.tts.sdk.test/androidx.test.core.app.InstrumentationActivityInvoker\$EmptyActivity'
```

保存新的 `frontend-contract-<timestamp>.json`，不要覆盖失败现场。未覆盖完整发音语料、超长技术 token 的全面性能测试、后台冻结后的恢复契约、长稳压、Harmony 真机及 Release AAR 宿主验收。CI 和全部 review threads 仍须按实际待合入 HEAD 检查，不能从本报告推断未来提交也已通过。
