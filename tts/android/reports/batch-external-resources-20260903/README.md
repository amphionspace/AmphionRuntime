# 批测授权与外置资源迁移 — 2026-09-03

结论：本轮入口迁移回归 **PASS**。旧版确实忽略传入的 license，并清空 workPath；修复后同条件冷启动合成通过，资源完整保留。SDK 运行代码未改。

## 范围与冻结点

- 基线 main：`927abb90b40859eca5b51ecff6f69c799cd9d856`（已合入 PR #188）。
- 修复/测试代码：`cf12e1c30623e18ef93736456c48684893f528ba`；后续仅更新文档和归档证据。
- 仅修改 `AarStability1000DeviceTest`、`AarRtfAuditDeviceTest` 的初始化，复用一条 TestRule，去掉四处旧资源目录初始化/清理。
- 正常 ENFORCE 授权，要求公开状态为 LICENSED；显式读取 workPath / licensePath，不创建或删除模型目录。
- 语料、每例断言、RTF 的 3 次预热/20 次测量/超时、SDK 和宿主运行代码均不变。
- vivo V2505A / Android 16；SDK 3.0、模型 0.1.0、原有 Debug 签名。两个已安装 APK 校验值均与本地一致，Release AAR 与 PR #188 校验值相同。详见 [report.json](report.json)。

## 红绿对照与相邻验证

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| 旧版冷启动，第 0 条 / 1 例 | FAIL：1002300012，no license provided；模型副本和保护标记被删 | [基线报告](baseline-red/summary.json)、[逐例结果](baseline-red/results.jsonl)、[资源现场](baseline-red/resource-deletion.txt) |
| 修复版，相同参数与语料 | PASS：1 start / 7 PCM / 1 complete | [报告](cold-green/summary.json)、[逐例结果](cold-green/results.jsonl) |
| 共享引擎相邻 2 例，第 1–2 条 | 2 PASS、0 FAIL | [报告](shared-green/summary.json)、[逐例结果](shared-green/results.jsonl) |
| 原有中等文本纯合成 RTF | 20 条测量全部完成、有非空 PCM、无 error | [报告](rtf-green/summary.json)、[逐例结果](rtf-green/results.jsonl) |
| 缺少 workPath / licensePath | 均在批测前明确拒绝，无静默 fallback | [workPath](expected-errors/missing-workpath.log)、[licensePath](expected-errors/missing-license.log) |
| 全部检查后资源对照 | 25 个模型文件 SHA-256 匹配，保护标记保留 | [资源校验](resources-after.json) |

缺参运行中的 JUnit failure 是预期拒绝，不是正向用例失败。旧版红灯单独保留为非 canonical 基线，未覆盖或冒充修复版证据。

红灯只使用新建的专用 `files/batch-setup-regression-20260903` 模型副本；既有 `files/tts-contract` 和私有授权文件没有被清理。红灯后从同一源重新部署副本，再用相同参数复验。输入 JSONL 的索引、SHA-256 和参数均记录在 report.json；RTF 文本与既有测试源码一致，不提交 PCM 或授权内容。

## 复现与证据复用

部署方式见[批测说明](../../docs/BATCH_TESTING.md)。本轮冷启动对照使用：

```text
class=com.lits.tts.aarhost.AarStability1000DeviceTest
inputAsset=android_v3_sdk_stability_100_cases_improved_v2.jsonl
caseStart=0
caseLimit=1
workPath=/data/user/0/com.lits.tts.aarhost/files/batch-setup-regression-20260903
licensePath=/data/user/0/com.lits.tts.aarhost/files/tts_only.lic
```

相邻用例仅改 caseStart=1 / caseLimit=2；RTF 使用 `AarRtfAuditDeviceTest#auditMediumSynthesizeOnlyRtf20`。缺参测试分别省略 workPath、licensePath，必须得到对应的 IllegalArgumentException。所有正向运行通过正常 `am start` 保持宿主在前台，未修改系统冻结/省电/安全策略。

SDK/JVM 源码及 Release AAR 未变，复用[104 项 JVM 结果](../frontend-device-20260903/jvm-results.json)（101 PASS、3 原有 SKIP）及[严格公开回调门禁](../release-aar-host-20260903/README.md)，不重复跑已通过的运行代码验收。证据文件 SHA-256 在根 report.json，构建日志中的本机路径已替换为 `<WORKTREE>`。

## 未覆盖与剩余工作

本轮不是完整 100/424/1000 条批测、完整 RTF/播放矩阵、发音语料、后台冻结恢复或长稳压；不能由短时资源采样推断无泄漏，也不比较本轮与旧版 RTF。RTF warmup 沿用原代码，不额外宣称其返回值全部被断言。

其他历史 probe 类尚未迁移；继续推进前应按实际使用入口逐项选择，勿运行整个旧测试包。旧批测的回调断言粒度和完整矩阵验收属于后续独立工作，不在这次初始化修复中夹带。
