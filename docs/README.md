# 工程经验文档

本目录用于沉淀 amphion-runtime（基于 sherpa-onnx）公司工程链路中的细节经验、排查记录和调优结论。底层 sherpa-onnx 通过 `third_party/sherpa-onnx` submodule 引用上游 pinned tag，本目录里的所有结论默认以该 pinned tag 为基准。

## 与 README 的职责划分

| 位置 | 职责 |
| --- | --- |
| 根 README / 各模块 README | 面向新用户：项目是什么、如何构建、如何运行、如何集成 |
| docs/ | 面向工程维护者：为什么这样配置、踩过哪些坑、如何复盘问题、如何调参 |
| shared/docs/ | 跨端发布流程、dashboard、release process 等流程性文档 |
| asr/android/docs/ | Android SDK 的集成、隐私、API 文档构建等模块内文档 |

这里的文档可以包含具体实验数据、设备现象、脚本命令和调参经验，不要求像 README 一样短。

## 文档索引

### Troubleshooting

| 文档 | 说明 |
| --- | --- |
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
| dingqiao-v0.2.7-delivery.md | 鼎桥 Android v0.2.7 最终交付口径：Demo 不绑 SN，正式 SDK license 绑 SN 并供 ASR/TTS 共用 |
| dingqiao-offline-license.md | 鼎桥专网离线 license 交付前置清单：SN、App 标识、签名证书、授权范围、维护期和组包路径 |

### Speaker（目标说话人 ASR 调研期）

| 文档 | 说明 |
| --- | --- |
| speaker/PIPELINE.md | TS-ASR 当前方案落地：模型选型、处理链路、lhotse 数据接入契约、决策门、下一步清单 |

## 配套工具

| 工具 | 说明 |
| --- | --- |
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

