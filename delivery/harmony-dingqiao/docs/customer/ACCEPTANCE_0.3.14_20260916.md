# HarmonyOS ASR SDK 0.3.14 最终 ZIP 验收报告

验收结论：**所列功能与生命周期通过**。四人重叠精度及多小时稳定性未通过本次验收；详见限制。

## 交付身份

| 项目 | 冻结值 |
|---|---|
| 完整 ZIP | `Amphion-Harmony-ASR-Complete-0.3.14.zip` |
| SHA-256 | `6de2391caf4bcc76fe37c93f33a81409b264d91ab2cf1a514ec11eed8a2d4870` |
| 字节数 | 1488380276 |
| SDK / Demo | 0.3.14 / 0.3.15（315） |
| 源码提交 | `1bdb516e708d0c939fe199dddee554af4fb9a6f8` |
| 交付分支 | `build/asr-delivery-20260916` |
| 能力及架构 | 中英 ZH_EN、ASR、arm64-v8a，模型内置 |
| 真机 | 鸿蒙验收设备（型号已脱敏），OpenHarmony 6.0.2.130 |
| 签名与授权 | 沿用现有测试签名；Demo 授权到期 2026-11-04，有设备绑定 |

五目录完整交付：Release SDK、Diagnostics SDK、已签名 Diagnostics Demo、独立 Demo 源码、文档及组包前证据。源码不含私钥或授权；本地构建测试仅补入既有授权及签名。客户应用需使用自身有效授权及签名。

## 已执行验证

| 验证 | 结果 | 证据及实际范围 |
|---|---|---|
| ZIP 完整性、内容校验 | PASS | 校验 48 个条目，包内 Diagnostics HAP 与构建身份一致 |
| SDK 组件来源 | PASS | 四个组件 HAR 和 HAP 绑定冻结输入；Release 使用内容完全相同的文档提交复用证明 |
| 主发布矩阵 | PASS | 同一 Diagnostics 构建，24 类、78 轮；包括 finish/cancel、超时、旧 session 迟到调用、回调重入及卸载后冷启动 |
| finish 兼容性 | PASS | callback-api-reentrant 3 轮、finish-shutdown 2 轮，根汇总和子报告保留 |
| Debug 专项 | PASS | Speaker VAD 2 轮、短语音 PTT 2 轮；另有 finish→shutdown→重授权→新 session 恢复 1 轮 |
| 最终 ZIP 内 Diagnostics Demo | PASS | AISHELL-4 四人 180 秒，30 个非空 final、2 个角色窗口、0 次角色降级、0 error |
| 最终 ZIP 源码 + Release HAR | PASS | 独立编译并明确安装 signed HAP；同一 180 秒输入，30 个非空 final、2 个角色窗口、0 次角色降级、0 error |
| 角色窗口与生命周期 | PASS | 两次完整包测试均 finish 前 last=0；唯一 last 后 complete；窗口累计文字不重复、末批标记及定稿保持符合断言 |
| 离线运行 | PASS（所列两次 ZIP 真机用例） | Wi-Fi 关闭、无 SIM、飞行模式开启；Demo 无 INTERNET 权限，模型来自包内。24 类矩阵不追溯宣称全部断网 |
| Android 共享回归 | PASS | 冻结源码上 SDK Debug/Release 共 339 项测试；只作为共享逻辑补充，不能替代鸿蒙真机 |

180 秒输入 SHA-256：`ca8dabf80f0471bb5967557f8f05669e30ca893880f34eb4df83bc77165cfbd2`。来源 AISHELL-4 `L_R003S01C02` 的 690–870 秒，16 kHz 单声道。角色标注用于确定输入为四人，不用功能测试代替精度评分。

独立源码构建产物 SHA-256：`9cf39c36d59ab65f722022855d1ab7aafc9ee9be8b1f6bec880268852e24d6a6`；包内 Release HAR SHA-256：`997d579b7ed7a5acd18585453c723a7a5b7a04fcd43cbcb9a5be4bee0d42c66f`。

## 资源与未覆盖条件

- 最终 ZIP 两次观察约 184–186 秒，RSS 增量分别 22.07 MiB（Diagnostics）、15.97 MiB（Release）。短测资源门禁 PASS；多小时泄漏、极端内存压力为 **INCONCLUSIVE / 未覆盖**。
- 64 MiB 是本轮短测 RSS 增量警戒值，不是长会议缓存上限，也不是内存不再增长的承诺。
- 源码版移除内部资源探针，其 `liveStreams=0` 是占位值，**不能作为 native stream 回收实测证据**；资源回收证据取自主矩阵 Diagnostics 构建。
- 未做逐系统调用网络追踪、断电、系统杀进程、权限撤销、来电及所有机型验证。无网络权限加实际断网运行证明本次流程可离线完成，不宣称观察了所有系统网络调用。

## 保留的失败现场

1. 首次 Speaker VAD 专项使用不匹配的输入：1.1 秒短句在 finish 前无 endpoint，约 24 秒 RSS 增量 74 MiB，判为 FAIL，现场保留。
2. 非目标声纹样本被正常过滤后无可统计时延，另一次专项 FAIL；换成独立同一说话人的注册语音和明确停顿后，契约与时延门禁通过。没有放宽全局资源或空结果阈值。
3. 解包验收准备脚本未创建空 rawfile 目录，准备失败；修正测试路径后独立构建通过，交付 ZIP 未因此更改。

## 接入及精度边界

- 角色结果按 `windowIndex` 累积，用 `sourceUtteranceId` 关联转写；`isSessionFinal` 表示角色末批。ASR 的 `isFinal/isLast` 不表示角色定稿。
- 不可靠角色为 `speakerIndex=-1`，Demo 显示“未能区分说话人”；中间角色允许修正，窗口定稿后不再回写。
- 四人重叠会议的角色准确率仍为 **OPEN**；本报告的 PASS 仅覆盖表中列出的功能及生命周期，不代表多人精度已达标。默认角色上限仍为 4，会议 Demo `vadEnd=800ms`。
- 不包含目标说话人增强模型；预留接口不能作为已交付能力启用。Diagnostics SDK 会记录 PCM 和文字，仅用于授权的问题定位。

## 证据位置

- 发布矩阵：`delivery/harmony-dingqiao/evidence/release-gate/20260916-1bdb516e-0.3.14/report.json`
- 最终 ZIP：`delivery/harmony-dingqiao/evidence/final-zip/20260916-0.3.14/report.json`
- 发布账本绑定 SDK 子 ZIP；本报告绑定完整 ZIP。脱敏报告、逐轮回调、资源采样、hilog、输入映射和哈希已归档，原始 PCM、授权与签名不进入仓库。
- 验收后仅补充测试断言、账本及外置文档，不改变上述 SDK、HAP、HAR 或 ZIP。
