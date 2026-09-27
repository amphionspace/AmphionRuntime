# 四人长录音角色分离：断开声学段建档验证

状态：**候选修复已在 Mate80 长录音上验证局部归属改善，整体身份精度仍未通过，PR 暂不合入。**

## 输入与证据

- 原始录音：123.8 秒、16 kHz、mono，PCM SHA-256 `c381622174402fd0f7a6d61466e8b736c9ba09419d482e22a4b5d182cb7eb178`。
- MOSS 仅接收原音，未提供人数、SDK 标签或答案；输出是辅助标注，不是人工真值。对应归档和输入映射在对象存储包中。
- Mate80 设备：`7GK0226326015655`。本轮保持 10 秒逻辑窗口、160000 samples native 输入、2 秒 hop、10 秒预览、120 秒定稿和既有 timeout。

## 最早错误状态

ASR 已产生完整的 u8 文本和 token，声学分割也在同一 native channel 捕获了两个连续的干净说话段：28.78–32.30 秒对应 MOSS S03，35.34–38.50 秒对应 MOSS S02。旧实现把一个 10 秒窗口内同一 channel 的不相邻活动池化为一个 embedding，随后聚类把 u8 归到了前一段身份。这是**声学 embedding 证据范围错误**，发生在 SDK 文本对齐和展示之前；不是标点、ITN 或 finish 生命周期问题。

同输入的旧手机结果中 u8 为 speaker 2。ASR token、声学分割和公共 speakerTurns 均存在，因此排除了“ASR 漏词”作为该片段的首因；队列 pending 最大 0、in-flight 最大 1，也排除了长时积压作为该片段首因。

## 最小修复

- 保留原有整窗 embedding 兼容字段，同时对每个不相邻的 clean run 单独提取 embedding。
- overlap 活动作为不可训练 run 记录并保持 UNKNOWN，不能因整窗或混合向量回退成已知身份。
- 沿用既有 20% 训练资格；短 run 不参与建档并保持 UNKNOWN，不降低阈值、不按句子多数角色覆盖。
- 聚类只用合格 run 建立身份，再将结果按 run 的 frame 范围回写；未知、overlap、已提交窗口冻结和 generation 归属保持原语义。
- evidence spool 增加 `run-embeddings.f32`、`run-ranges.f32`，按窗口前缀快照读取，避免迟到结果污染后续窗口。
- 未改变模型、窗口、hop、预览/定稿周期、timeout、公共回调顺序或 final/last/complete 语义。

## 真机结果

最新 overlap 保护代码构建并安装后的 Mate80 长录音回放（`device-replay-overlap-guard/20260927-192219-diarization-windows-494c8673`）结果：

| 检查 | 结果 |
|---|---|
| SDK 生命周期 | PASS；1 start、23 个非空 final、1 last、1 complete、0 error、0 空 final |
| 处理性能 | diarization inference 65505.91 ms，RTF 0.5291；finish 到角色结果 903 ms |
| 队列与内存 | pending 0、in-flight 1、音频延迟无增长；RSS 头/尾 602.449/599.496 MiB，峰值 617.164 MiB，线程 71→72 |
| u8 归属 | 从旧结果 speaker 2 改为 speaker 0，与同一 MOSS S02 的 u6、u11、u21 一致 |
| 其他主讲人 | S01/S03/S04 的长段编号保持稳定；UNKNOWN 和 overlap 仍被保留 |

87.38–91.58 秒的 u18 横跨 MOSS S02/S03 的边界，当前仍显示为同一公共 ID；这属于混合/边界证据不足的独立精度限制，不能称为本次已修复。短句、UNKNOWN 和 overlap 的保守输出也不能被计为四人身份通过。

## 回归与门禁

- 原生 / spool / 在线角色分离单测 34 项通过。
- Harmony HAR 构建通过：`amphion_asr@default`、`amphion_dingqiao@default` debug。
- 当前 PR #232 的 GitHub CI 正在最新提交上运行；官方隔离脚本的 HAR 发布步骤仍引用工作区路径，未完成自动安装。本轮改用同一签名配置和当前 HAR 构建并安装 HAP，再完成上述长回放；HAP 安装身份和结果保存在回放目录。
- 因为 87 秒混合边界和此前 19.58 秒短会话身份红灯仍在，PR #232 保持 draft，禁止合入。后续应先在同一在线状态回放中解决混合段身份证据，再补最小真机对照。
