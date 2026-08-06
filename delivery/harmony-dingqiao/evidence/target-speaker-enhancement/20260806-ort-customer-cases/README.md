# 2026-08-06 正式 ORT 客户 C1/C2/C3 真机回归

本目录保存 Harmony 正式 `convtasnet_16k.ort`、三段声纹注册和客户 C1/C2/C3 固定输入的真机结果。
测试设备为 Mate 80 `VYG-AL30`，系统 `6.1.0.135`，载体只构建并安装 `ZH_EN` HAP。

运行目录：
[`20260806-161644-target-speaker-enhancement-a9db7454`](20260806-161644-target-speaker-enhancement-a9db7454)

- build identity 精确绑定代码提交 `6d0bac06715950ea95a664304b4ec57249f603f7`，提交后校验通过。
- 三条 `role=enrollment` WAV 一次性注册为同一个声纹，只回放三条 `role=case` WAV。
- 报告单列 `target_speaker_content_accuracy`：C1、C2、C3 覆盖完整，均满足最终文本包含“上海”且
  不包含“你好”。
- 生命周期为 `starts=3`、`finals=9`、`completes=3`、`errors=0`；每轮显式 `finish` 前没有
  `isLast`，结束后恰好一次 last、随后一次 complete，native stream 归零且无跨 session 回调。
- 20 ms 实时喂入共处理 22 块，最大耗时 `1630 ms`、P95 `1616 ms`、最大排队 `2`，实时门通过。
- 资源观察 `78.438 s`：峰值 RSS `819.062 MiB`，稳定窗口 RSS 变化 `-180.070 MiB`，线程变化
  `-3`，资源门通过。

输入身份记录在 `payload/corpus.json`，原始 WAV 由
`asr/test-fixtures/target-speaker-customer-cases/manifest.json` 固定；证据目录不重复提交 PCM 副本。
`hilog.txt` 只保留本测试应用进程的 43 行模型、回调和性能日志，不包含其他应用的整机活动。
