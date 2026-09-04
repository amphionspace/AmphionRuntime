# Release AAR 独立宿主验收 — 2026-09-03

结论：本轮最小接入门禁 **PASS**。SDK 运行代码未改；使用与前端修复验收相同 SHA-256 的 Release AAR，在独立宿主中完成授权、外置模型加载和公开 API 合成。

## 冻结范围与结果

- 来源提交：`f1e069bfd75794abde3caaabb5cdf2f3ae9adac4`，基于已合入 PR #187 的 main `700a847a`。之后仅归档证据/修改文档。
- SDK 3.0，模型资源 0.1.0；vivo V2505A / Android 16 / API 36 / arm64-v8a。
- 宿主及测试 APK 使用 Android Debug 签名；宿主仅通过文件依赖消费 `sdk-release.aar`，没有依赖 SDK project 或访问 SDK 内部类。
- 正常授权策略 `ENFORCE`，公开状态断言为 `LICENSED`，开发未授权构建不能通过。license 未提交；资源目录读取后未清空。
- 25 个模型/前端文件均与此前已校验资源包 SHA-256 一致，无 AppleDouble 附加文件。
- 输入包含负温度、日期、跨 50 字符位置的 URL；完整文本和逐条回调在 [device-report.json](device-report.json)。
- 唯一 start → 21 个非空 PCM（序号 0–20）→ 唯一 SYNTHESIS_COMPLETE；所有回调均属于 `aar-frontend`，无 error/stop，shutdown 返回。
- PCM 共 1112064 bytes，24 kHz / 16-bit / mono。块数和耗时是观测值，不是写死的断言。
- 仪器测试 14.943 秒，包含拉起前台页面的等待；start → complete 为 2998 ms。不将启动等待解释为 SDK 模型加载或合成性能。

## 前台要求与非 canonical 现场

初版 Debug 页面未对外开放。测试进程在页面启动前被 vivo 冻结：cgroup.freeze=1 / frozen=1；未映射推理库、未产生测试报告。保存状态后结束该进程；日志中的 `Process crashed` 是这次主动终止的结果，不是 native 崩溃。

[non-canonical/startup-frozen-state.txt](non-canonical/startup-frozen-state.txt) 与 [运行日志](non-canonical/startup-frozen.log) 保留为非 canonical 诊断证据，不计入 SDK PASS/FAIL。

随后仅将 Debug 显示页面开放为可从外部正常启动，未更改 Release AAR、系统省电或安全设置。有效运行启动 instrumentation 后，显式执行 `am start -W --activity-single-top -n com.lits.tts.aarhost/.AarHostActivity`，在前台完成门禁。该显示页面不接受业务输入或触发 SDK 操作，Release 宿主不包含它。

## 证据和复用

- [report.json](report.json)：源码、两个 APK 与 AAR 校验值、已安装 APK 一致性、结果摘要及证据 SHA-256。
- [build.log](build.log)：当前源提交下成功构建的完整日志；`<WORKTREE>` 为脱敏工作目录。
- [device-test.log](device-test.log)：`OK (1 test)`。
- [model-files.json](model-files.json)：设备资源逐文件校验值。
- SDK / JVM 源码未变，Release AAR SHA-256 未变；复用[前端门禁](../frontend-review-20260903/README.md)及[104 项 JVM 结果](../frontend-device-20260903/jvm-results.json)（101 PASS、3 原有 SKIP），未重复执行。
- 复现步骤见[批测说明](../../docs/BATCH_TESTING.md#当前-release-aar-最小接入门禁)。只改文档/证据不使本轮二进制验收失效。

## 未覆盖

本轮不代替 token/发音正确性对照、完整发音语料、后台冻结恢复、长稳压、播放音质、客户正式签名接入或 ASR 门禁。旧 `AarStability1000DeviceTest` / `AarRtfAuditDeviceTest` 没有完整适配当前授权/外置资源流程，迁移为独立待办；不要对业务资源目录运行旧的默认清理逻辑。
