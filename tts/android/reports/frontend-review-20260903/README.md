# PR #187 审查收尾与真机复验

`e7910d697e05dedc0bd9a63f68548cc34842d166` 只为 instrumentation 增加 PCM 序号必须连续且有序的断言；SDK 运行代码和 JVM 用例没有变化。Release AAR SHA-256 与 `fcdfea97` 相同，因此复用此前 104 项（101 PASS / 3 原有 SKIP）本机结果，不重复执行。

新测试 APK 在 vivo V2505A / Android 16 通过：7 项温度、4 项日期、URL 边界，以及公共 SDK 的唯一 start、21 个非空 PCM 回调（序号 0–20）、唯一 complete、无 error 和 shutdown。总 PCM 1,112,064 字节，instrumentation 耗时 5.312 秒。见 [report.json](report.json)、[逐条结果](device-report.json)和[完整输出](device-test.log)。

审查意见处理：

- PCM 序号：采纳；原先仅在离线核对报告时验证，现已成为测试内的强制断言。保持完整的 native TN、文本/token 和回调检查。
- `!= false` 换为 `?: true`：二者都将文本末尾的 null 视为允许分段，属于非阻断的等价可读性建议。为保留已冻结的运行代码和二进制，不在本轮更改；已在 review thread 说明理由。

安装首次因屏幕锁定被系统取消，保留在 `non-canonical/`；唤醒屏幕、通过系统安装确认后成功。执行时将 APK 已有的 AndroidX EmptyActivity 显示在前台，没有关闭授权、修改系统冻结策略或延长超时。前台复现方法与运行边界见[前序真机记录](../frontend-device-20260903/README.md)。新 APK 安装后的哈希与构建一致；SDK/模型/签名/授权配置不变。

本轮没有补做完整发音语料、长稳压、后台强制冻结恢复或 Release AAR 独立宿主验收。最后一项已确认旧宿主入口缺少外置资源与授权初始化，应单独完善，不能作为当前 Debug instrumentation 通过的隐含结论。
