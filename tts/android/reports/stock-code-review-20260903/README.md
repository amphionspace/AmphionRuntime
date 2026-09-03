# PR #191 审查收尾

`1278a02ec95537731d4351f868d2a7f596a32d9e` 只补充 `StockCodeDeviceTest` 缺少 `workPath` 时的诊断提示，SDK 运行代码、正常参数路径和授权不变。

- 采纳缺参提示建议：vivo V2505A / Android 16 缺参立即抛出带 `Pass -e workPath ...` 的异常；这是预期拒绝，instrumentation 本身应返回失败。
- 同一新 APK 正常传参：7 项原生 TN 和完整 token 对照通过，2.08 秒。已安装 APK 与构建 SHA-256 一致。
- 不采纳本 PR 抽取 stock/room/plate/id-tail 共享规则的建议：这是跨规则结构调整，超出此次股票代码根因修复；两入口已有完整回归，保留已冻结的运行代码。
- Release AAR 哈希仍为 `72174502b6fc9420d148a23b965b119dff9874c0fe39bd64812b4abe0c42622c`；复用[前序公开 SDK、JVM 与 675 条对照](../stock-code-20260903/README.md)，不重复无运行变化的验证。全量发音仍未通过。

首次及紧接着的安装在锁屏解除完成前被系统取消；系统确认解锁后正常安装成功。两次中止日志保留在 `non-canonical/`，没有更改安全设置。构建与运行日志、逐项结果、哈希见本目录及 [report.json](report.json)。
