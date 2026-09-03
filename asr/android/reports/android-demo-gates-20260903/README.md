# Android Demo 门禁补测（2026-09-03）

PR #184 保留的三项真机门禁已通过。此目录是本次定向回归证据，不代表完整 SDK 发布矩阵。

## 冻结输入

- 源码：`37c96af9bba3b8c90bf3aa89a86609a61e0391d6`，SDK/Demo 版本 `0.3.4`。
- 设备：vivo V2505A，Android 16；设备标识不入库。
- 使用当前源码构建的 Debug Demo 和 instrumentation APK；手机安装包与本机产物 SHA-256 一致，见 `report.json`。
- 模型沿用已校验的 9 文件 Android 中英资产包；授权沿用同一份 Demo 授权，未放宽验签或修改系统安全校验。
- 语料为既有 `voiceprint-fallback` 测试集，映射与 SHA-256 见 `input-mapping.json`；不提交原始 PCM。
- 本证据提交仅增加报告，不改变运行源码、测试 APK、模型、签名或授权；沿用上述提交的真机结果，不重复验收。

## 结果

| 用例 | 结果 | 可观察断言 |
| --- | --- | --- |
| `v04b_verificationWithVadBegin_frontSilenceDoesNotEndEarly` | PASS | `vadBegin=1000 ms`，300 ms 前置静音 + 11.04 秒真实 PCM；finish 前无 last；1 条非空 final 带分数；唯一 last 后唯一 complete，无 error |
| `a11_vadBegin_initialSilenceAutoFinish` | PASS | `vadBegin=500 ms`，突发写入 700 ms 静音；空 last 后唯一 complete，无 speech 事件或 error |
| `a13_userSequenceStress_300Cycles` | PASS | 300 轮、900 个 session；300 个取消、600 个正常结束；耗时 266858 ms；正常会话 finish 前无 last，随后唯一 last/complete，旧调用不污染新会话 |

`sessions.json` 逐条统计 session；各模式 `.jsonl` 保留有序回调和结束调用记录。
正常旧 session 结束后，故意对其调用 `writeAudio/finish/cancel`，共得到 900 条预期的旧调用拒绝；
这些不是当前会话错误。每个正常 session 在 complete 之前无错误，新 session 无错误。

Demo 15 项单测 PASS（输入未变，复用 Gradle 缓存）；测试 APK 编译、Android AAR 与 samples 编译、
Harmony 生命周期、静态契约、AGC、双端资源一致性、脱敏及仓库结构 CI 均通过。
源码提交 CI 链接保存在 `report.json`。

## 非 canonical 失败与设备条件

`user-sequence-frozen*` 保留同一 APK 首次长测在第 3 轮的失败现场，不作为通过证据。
当时手机息屏，采样中 `cgroup.freeze=1`；系统把当前充电识别为 AC，
仅 USB 的保持亮屏设置未生效，导致 complete 超过测试的 20 秒等待期限。

只改变设备条件：保持前台、唤醒，并启用与实际充电来源匹配的保持亮屏设置。
同输入、同参数、同 APK 的 300 轮随后通过，26 次采样中冻结状态均为 0。
声纹短测也曾遇到息屏冻结，恢复后在同一次运行中通过；其耗时不用于性能结论。
结束后已恢复手机原来的保持亮屏设置。临时授权副本移至本机废纸篓，可恢复。

## 限制与证据范围

- RSS 采样范围 541796–632684 KiB，线程 55–60；仅约 4.5 分钟，长期泄漏判断为 `INCONCLUSIVE`。
- 未采集 native stream 数量；本次不声明 native 资源零泄漏。
- 不覆盖外部杀进程、USB 中断、完整发布矩阵或声纹身份识别精度。
- logcat 仅保留测试进程的 TestRunner 诊断；不提交识别文本、个人信息、授权、原始音频或未过滤系统日志。
- `sha256.json` 校验机器生成的报告、回调记录、逐 session 汇总和采样文件。
