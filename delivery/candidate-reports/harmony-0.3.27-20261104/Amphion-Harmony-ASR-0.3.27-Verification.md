# Amphion HarmonyOS ASR 0.3.27 验收状态（未发布候选）

| 项 | 值 |
|---|---|
| 版本 / 版本日期 | 0.3.27 / 2026-11-04 |
| 源码提交 | `1ac8d93f95473a8b8c0b16e71151c57e1647fab9`（分支 `release/harmony-0.3.27`，未合入 main） |
| 完整 ZIP | `Amphion-Harmony-ASR-Complete-0.3.27.zip`，1939583071 字节，SHA-256 `0408b5577ebe4a8d94fbb3c76b8a3c1f092207b9fd24b0d0c5f8a399b59efd0c` |
| Release 子包 | `amphion-harmony-asr-sdk-v0.3.27-20261104.zip`，390468432 字节，`9a136daa…` |
| Diagnostics 子包 | `Amphion-ASR-Diagnostics-SDK.zip`，773934394 字节，`7496f8ed…` |
| 基线 | 客户实际收到的 0.3.26（源码 `927bda6e`，ZIP `860d731f…`，带 speaker-vad-turn 豁免） |
| 状态 | **未发布候选**（`published: false`）：`speaker-vad-turn` 按豁免处理；按用户授权可带披露豁免交付 |
| 真机 | HUAWEI VYG-AL30，HarmonyOS 7.0.0.109，arm64-v8a（序列号见外置最终报告） |

## 本版改动（相对客户已收到的 0.3.26）

1. **角色归属改由声纹身份决定，默认开启。** 新增 `SpeakerDiarizationConfig.speakerIdentityMode`
   （`'voiceprint'` 默认 / `'model'` 回退）与 `SpeakerTurn.modelSpeakerIndex`；嵌入取每段前 3 s，并入阈值 0.50。
   客户 4 条现网录音留一法 34/34（0.3.26 链路 28/34）；真机 6 例工单复现修复 4 例，余 2 例由说话人自身声纹
   相似度（0.546 / 0.523）解释。
2. **静音不再被转写出"嗯"。** 非空文本需独立声学证据（−74 dBFS 发布门限或 VAD 确认）才发布；客户 52.2 s
   近静音复现文件被丢弃，现场 90 段 + 公开 500 条 0 误丢；真机 A/B 无回归（真机不复现原现象）。
3. 版本 0.3.27 / versionCode 327；原生库与 0.3.26 逐字节相同；模型文件集合不变（声纹模型 CAM++ 自 0.3.26 随包）。

## 通过项

| 验证 | 结果 |
|---|---|
| Release 子包门禁（布局、校验和、脱敏 16 文件/1 HAR、自包含 HAR 与本地产物一致、干净主机安装编译、HAR 版本、模型清单与 MD5） | PASS |
| API 23 编译兼容 | PASS，54 个公开 TypeScript 文件 |
| 完整 ZIP（`checksums.txt` 50/50，身份与 Diagnostics 子包一致，无探针/语料/内部路径） | PASS |
| 真机 `customer-ptt`（Diagnostics 构建） | PASS，12/12，空 final 率 0.000，原生流 0 泄漏，内存 PASS（增长 8.21 MiB、峰值 417.5 MiB） |
| 真机 `diarization-windows`（客户录音 4 条 ≥ 120 s，声纹默认开启） | PASS，4/4，角色结果数 4/2/2/2，结束到最终结果 1114~2416 ms，RTF 0.255~0.271，内存 advisory INCONCLUSIVE（峰值 878.2 MiB、HWM 915.4 MiB） |
| 最终 ZIP 内 Demo HAP 装回复测（`--installed-package`，versionName 0.3.27 / versionCode 327） | PASS，12/12，空 final 率 0.000，内存 PASS（增长 13.27 MiB、峰值 421.2 MiB） |
| 主机回归 | 鸿蒙门禁 500 项、交付工具 270 项、仓库布局/可观测性/版本检查 PASS |

## 代价与未覆盖

- `speaker-vad-turn` 未执行（夹具在本机不可重建；本版未改机主识别代码；0.3.26 实跑 6/6 归属通过）。
- 143.8 分钟长跑：净自发热 +2.2 °C、无降频；RSS 饱和型约 805 MB、HWM 1044 MB；无 `'model'` 对照臂，
  声纹的发热增量未隔离；接近 1 GB 的高水位未归因。
- 角色分离已知限制：3 人会议多报成 4 人（5 场中 3 场）、1 秒级短发言抖动、5 人以上超标称、客户录音
  `111223-816` 仍约 22% 混淆。
- "嗯"门禁挡不住普通房间噪声幻觉；客户复现文件为立体声左声道全零，SDK 实际输入形态待客户确认。
- Android 端本轮不重建、不交付。功耗 USB 下不可测。

## 外置交付材料

- `delivery/harmony-dingqiao/evidence/acceptance/20261104-1ac8d93f-0.3.27/FINAL-ZIP-ACCEPTANCE.md`（绑定 ZIP 哈希，含机型与序列号）
- 同目录 `REDACTION.md`、脱敏报告副本、`ACCEPTANCE-SUMMARY.md`、`acceptance-manifest.json`、
  `CALLER_CHANGE_CHECKLIST_0.3.27.md`、`交付邮件-0.3.27-20261104.md`（草稿，未发送）

## 取代关系

同版本早前两次冻结未交付：`316135a4`（Release 子包被自包含 HAR 校验与交付校验拦下）、`b84bb51d`
（装回的 Demo HAP 版本号仍为 0.3.26）。三轮 SDK 源码、构建输入与原生库完全相同，真机结论一致。
