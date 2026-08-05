# 文档组织与索引

本目录用于沉淀 AmphionRuntime 的跨模块工程经验、排查记录、调优结论和交付流程。底层 `sherpa-onnx` 通过 `third_party/sherpa-onnx` submodule 引用上游 pinned tag，本目录里的工程结论默认以当前 pinned tag 为基准。

## 文档分层

| 位置 | 读者 | 职责 |
| --- | --- | --- |
| 根 `README.md` | 所有人 | 仓库是什么、有哪些模块、首次 clone 后从哪里开始 |
| 各模块 `README.md` | 模块使用者和维护者 | 该模块如何构建、运行、集成和自测 |
| `docs/` | 工程维护者 | 跨模块排障、调参、交付流程、复盘和文档索引 |
| `shared/docs/` | 发布和平台维护者 | 跨端发布流程、dashboard、release process 等流程性文档 |
| `asr/android/docs/` | Android ASR 维护者 | Android ASR SDK 的集成、隐私、授权、交付和 API 文档构建 |
| `asr/android/docs/customer/` | 客户集成方和交付人员 | 鼎桥 Android 客户可见接口、license 和模型说明 |
| `delivery/harmony-dingqiao/docs/` | 鼎桥 HarmonyOS 交付人员 | HarmonyOS ASR+TTS 聚合交付说明、隐私、授权和变更记录 |
| `reports/` | 验收和排障人员 | 自动化或设备端测试报告；默认不是接口契约来源 |

## 写作边界

- README 只放入口和结论，细节分析放到 `docs/` 或模块 `docs/`。
- 客户可见文档不得暴露内部路径、仓库 URL、非公开分支、`.secure/`、私钥、签名密码、客户 SN、完整 license payload 或 TODO/FIXME。
- 交付 Markdown 表格单元格只放原文或交付口径原文，不使用粗体、斜体或删除线包装。
- 接口契约以基线文档和项目内批注文档为准，不用当前实现行为反向改写接口。
- 自动生成报告可保留设备现象、脚本命令和实验数据，但要说明实验条件，不泛化为绝对结论。

## 文档污染防护

- 当前规则文档不得混入单次历史交付的版本号、固定到期日、SN 数量、zip 路径或本机绝对路径；这些信息只能进入明确标记为“历史交付记录”或“实验报告”的文档。
- 历史交付记录必须在标题或首段标明“历史归档 / 不作为当前规则”，并从当前 Delivery 主索引移到历史区。
- License 当前规则以 `docs/dingqiao-offline-license.md`、模块客户 `LICENSE.md` 和交付 Runbook 为准；正式设备白名单 license 默认不按 Android `applicationId` 或 HarmonyOS `bundleName` 限制宿主，包名只作签发记录。
- 客户可见文档和交付包内文档只能使用仓库相对路径、占位路径或基线文档名；不得出现 macOS/Linux 用户主目录绝对路径、`.secure/`、私钥路径、内部下载目录。
- 规则变更必须同步检查当前入口索引、客户文档、打包脚本注释、交付邮件模板和错误码表，避免同一交付口径在不同文档里分叉。

## 入口索引

### 模块入口

| 文档 | 说明 |
| --- | --- |
| ../README.md | 仓库总览、模块布局、首次 clone 和各端构建入口 |
| ../asr/android/README.md | Android ASR SDK、警务增强、鼎桥 demo 和样例构建入口 |
| ../asr/harmony/README.md | HarmonyOS ASR HAR、native 产物和资源同步入口 |
| ../asr/ws-server/README.md | ASR WebSocket 服务本地运行、协议和 H20 CUDA 切换清单 |
| ../delivery/harmony-dingqiao/README.md | 鼎桥 HarmonyOS ASR+TTS 交付聚合层构建和打包入口 |
| ../tts/android/README.md | Android TTS SDK 构建和样例入口 |
| ../tts/harmony/docs/BUILD.md | HarmonyOS TTS 构建入口 |

### 客户与交付契约

| 文档 | 说明 |
| --- | --- |
| ../asr/android/docs/customer/语音识别SDK接口-交付批注版.md | 鼎桥 ASR 客户接口契约；以 20260622 基线为准，只在增补项旁批注 |
| ../asr/android/docs/customer/语音识别SDK接口.md | Android 集成说明；跨平台契约以交付批注版为准 |
| ../asr/android/docs/customer/DINGQIAO_INTEGRATION.md | 鼎桥 Android 集成说明 |
| ../asr/android/docs/customer/DINGQIAO_VOICEPRINT_MODEL.md | 鼎桥 Android 声纹模型说明 |
| ../asr/android/docs/customer/LICENSE.md | 鼎桥 Android license 客户说明 |
| ../delivery/harmony-dingqiao/docs/DINGQIAO_INTEGRATION.md | 鼎桥 HarmonyOS 集成说明 |
| ../delivery/harmony-dingqiao/docs/DINGQIAO_LICENSE_SCHEME.md | 鼎桥 HarmonyOS 授权方案 |
| ../delivery/harmony-dingqiao/docs/customer/LICENSE.md | 鼎桥 HarmonyOS 客户 license 说明 |

### Troubleshooting

| 文档 | 说明 |
| --- | --- |
| troubleshooting/dingqiao-finish-flush-postprocessor.md | 鼎桥 Android 快喂后 finish 空 final/丢尾字的根因：PostProcessor 队列被提前关闭，以及 isLast 语义修复和真机回归 |
| troubleshooting/dingqiao-create-engine-missing-so.md | 鼎桥 Android `createEngine` 找不到 sherpa native 库的根因、验包命令和交付门禁 |
| troubleshooting/zh-en-mixed-asr-tuning.md | 中英混合 ASR 在 Android 实机上纯英文不可用的深度分析：greedy vs beam、低电平、endpoint 切分 |
| troubleshooting/streaming-zipformer-cold-start.md | streaming zipformer 第一段被吞的根因：encoder left-context cold start，以及 800ms 静音 warmup 修复 |

### Debugging

| 文档 | 说明 |
| --- | --- |
| debugging/android-session-dump.md | Android sample 的 audio.wav + transcript.txt 落盘工具、adb pull、PC 离线对照方法 |

### Delivery

| 文档 | 说明 |
| --- | --- |
| android-sdk-delivery-runbook.md | Android ASR / TTS / License 三件套交付 Runbook：打包、验包、设备回归、license 策略、目录归档和交付门禁 |
| delivery-email-template.md | Android SDK 交付邮件模板：更新点、license 策略、测试数据、验证结论和复现说明 |
| delivery-zip-verification.md | 所有客户交付包的 zip-only 验证流程：以最终 zip 为唯一真相，生成 JSON/Markdown 验收报告 |
| dingqiao-offline-license.md | 鼎桥专网离线 license 当前前置清单：SN、App 标识记录、可选签名证书、授权范围、维护期和期限策略 |
| license-delivery-governance.md | SN、License 与交付批次治理方案：完整快照、显式策略、角色分离、最终 ZIP 门禁和可审计登记簿 |
| license-delivery-industry-practices.md | License 签发与交付方案的业界实践核对：密钥生命周期、签名证明、标识符保护和离线防回退差距 |

### 历史交付记录

| 文档 | 说明 |
| --- | --- |
| dingqiao-v0.2.7-delivery.md | 鼎桥 Android v0.2.7 历史交付归档；只用于追溯当时产物和验证，不作为当前 license 或交付规则 |

### Speaker（目标说话人 ASR 调研期）

| 文档 | 说明 |
| --- | --- |
| speaker/PIPELINE.md | TS-ASR 当前方案落地：模型选型、处理链路、lhotse 数据接入契约、决策门、下一步清单 |
| speaker/AIDATATANG_SPEAKER_VAD_EVAL.md | Aidatatang 500 人主说话人 VAD endpoint 评测：指标定义、场景问题、阈值扫描和结论 |

### ASR 功能评测

| 文档 | 说明 |
| --- | --- |
| asr/AISHELL3_HOTWORDS_EVAL.md | AISHELL-3 500 条热词 ASR 评测：最终收益表、指标定义、系统对比和限制 |

## 配套工具

| 工具 | 说明 |
| --- | --- |
| ../tools/delivery/generate_delivery_manifest.py | 扫描交付目录内的 zip，生成包含大小、SHA-256 和 verification 报告路径的 `MANIFEST.md` |
| ../tools/license/license_delivery.py | 正式商用 License 的计划、签发、最终 ZIP 验收和 Git 元数据登记统一入口 |
| ../asr/tools/decode_offline.py | 一次性投递 wav 到 sherpa-onnx Python OnlineRecognizer，观察模型上限 |
| ../asr/tools/decode_streaming.py | 模拟 Android streaming：100ms chunk、endpoint、encoder warmup、greedy/beam 对比 |

依赖：

```bash
python3 -m pip install --user sherpa-onnx
```

## 写作约定

- 优先记录「现象 -> 证据 -> 结论 -> 修复」。
- 表格中只放原文，不使用加粗或斜体。
- 命令尽量可复制运行。
- 具体设备、模型、dump 数据可以写进文档，但要说明它们是本次实验条件，不要泛化成绝对结论。
- README 只放入口和结论，细节分析放到本目录。
