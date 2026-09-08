# 最终 ZIP 解包验收

结论：PASS_WITH_LIMITATIONS。验收输入为最终 ZIP，文件未修改。

ZIP：`Amphion-Harmony-ASR-Complete-0.3.13.zip`
SHA-256：`134d079e7501700e51df0ba1a9d7cf9cddef39cc3d8c5207a14ff0b30075ad2c`

设备：VYG-AL30 / OpenHarmony-6.1.1.120。

路径一：解压 ZIP，直接安装包内 Diagnostics Demo；核对四个 Debug HAR 与包内构建记录。
路径二：解压 ZIP 中 Demo 源码，使用自带正式 HAR，补入本地签名、授权后独立构建并安装。SDK/源码未修改；HAP 内 native 库与正式 HAR 一致。

| 路径 | 模式 | 轮数 | 结果 | 内存观察 |
|---|---|---:|---|---|
| diagnostics | customer-ptt | 3 | PASS | PASS |
| diagnostics | speaker-vad-turn | 2 | PASS | PASS |
| diagnostics | callback-api-reentrant | 3 | PASS | INCONCLUSIVE |
| diagnostics | finish-shutdown | 3 | PASS | INCONCLUSIVE |
| diagnostics | start-write | 3 | PASS | INCONCLUSIVE |
| diagnostics | start-write-reload | 3 | PASS | INCONCLUSIVE |
| diagnostics | cancel | 3 | PASS | INCONCLUSIVE |
| source | burst | 3 | PASS | INCONCLUSIVE |
| source | paced | 12 | PASS | PASS |
| source | vad-begin | 3 | PASS | INCONCLUSIVE |
| source | vad-begin-silence | 3 | PASS | INCONCLUSIVE |
| source | voiceprint | 3 | PASS | INCONCLUSIVE |
| source | voiceprint-fallback | 12 | PASS | PASS |
| source | voiceprint-vad-begin | 3 | PASS | INCONCLUSIVE |
| source | voiceprint-vad-begin-idle | 3 | PASS | INCONCLUSIVE |
| source | cancel | 3 | PASS | INCONCLUSIVE |
| source | cancel-full | 3 | PASS | INCONCLUSIVE |
| source | recreate | 3 | PASS | INCONCLUSIVE |
| source | reconfigure | 3 | PASS | INCONCLUSIVE |
| source | max-duration | 3 | PASS | PASS |
| source | edge | 3 | PASS | INCONCLUSIVE |
| source | reentrant | 3 | PASS | INCONCLUSIVE |
| source | start-cancel | 3 | PASS | INCONCLUSIVE |
| source | start-write | 3 | PASS | INCONCLUSIVE |
| source | start-write-reload | 3 | PASS | INCONCLUSIVE |
| source | speaker-vad-onstart | 3 | PASS | INCONCLUSIVE |
| source | callback-api-reentrant | 3 | PASS | INCONCLUSIVE |
| source | endpoint-reentrant | 3 | PASS | INCONCLUSIVE |
| source | finish-shutdown | 3 | PASS | INCONCLUSIVE |
| source | user-sequence | 3 | PASS | INCONCLUSIVE |
| source | numeric-edge | 3 | PASS | PASS |
| source | finish-shutdown-relicense | 3 | PASS | INCONCLUSIVE |

限制：源码版移除了内部资源探针，原始报告中的 native stream=0 不算实测；仅采用其公共 API/回调断言。短用例内存 INCONCLUSIVE 保留，不能据此声称长期无泄漏。此前短音频说话人切换的 endpoint 限制仍保留，本次使用两段真实连续轮次语料。未新增精度、断网抓包或外部故障注入验收。

一次未签名安装被拒绝，随后误启动的旧应用测试已停止并归档为 noncanonical，不计入上表。正式源码版结果绑定成功安装的已签名 HAP。

完整回调、逐轮结果、内存采样、hilog、输入映射和各报告 SHA-256 见 [report.json](report.json)。归档不包含原始 PCM、license 或签名私钥。
