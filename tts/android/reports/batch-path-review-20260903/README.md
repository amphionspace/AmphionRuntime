# 批测路径审查补充 — 2026-09-03

结论：PR #189 的路径校验补充 **PASS**。只修改测试入口，不改 SDK 或模型。

- 代码冻结在 `e5640ade95f3a002fd8f5ed16f3f68d5ccc89ddf`；之后仅文档/证据。
- 审查前，错误 workPath 会进入冷启动用例并在约 12 秒后以汇总失败结束；[红灯结果](baseline-red/results.jsonl)和[日志](baseline-red/device-test.log)单独保留，不计入修复版结果。
- 修复后，在启动页面之前检查 workPath 为已存在可读目录、licensePath 为已存在可读文件，并读取授权；SDK 继续负责目录内部的模型校验。
- 6 种错误输入（路径不存在、类型错误、不可读，分别作用于目录/授权文件）均在 0.012–0.013 秒内抛出明确的 IllegalArgumentException，未进入用例循环。日志中的 JUnit failure 是预期拒绝，详见 [expected-errors](expected-errors/) 和 [report.json](report.json)。
- 相邻正常冷启动保持相同语料和参数，[复验通过](valid-green/summary.json)，仪器测试 19.862 秒。SDK AAR 和宿主 APK 校验值未变，新测试 APK 的设备校验值与本地一致。
- 两个不可读夹具是独立新建的测试文件/空目录，测试时临时设为 000，之后恢复为 600/700；原模型目录、license 权限均未修改。
- Kotlin 1.9.22 本机标准库的 `readText$default` 字节码已使用 `Charsets.UTF_8`。显式写 UTF-8 仅提升可读性，不作为编码缺陷修复。

[report.json](report.json) 包含完整参数、APK/AAR/证据 SHA-256。正常输入下的初始化、逐例逻辑、语料及运行代码未变，复用[此前共享引擎/20 次 RTF](../batch-external-resources-20260903/README.md)、[严格公开回调门禁](../release-aar-host-20260903/README.md)和 104 项 JVM 结果（101 PASS、3 原有 SKIP）；不重复跑整轮矩阵。

本记录仍不代表全量发音语料、完整批测、播放、后台冻结恢复或长稳压验收。
