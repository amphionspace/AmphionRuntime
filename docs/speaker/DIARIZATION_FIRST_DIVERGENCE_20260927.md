# 四人短录音首个偏离层

这份记录把现有四人短录音沿 SDK 诊断链路复核一遍，目的是确定下一次修复应作用在哪一层。它不是当前交付证据：现场运行提交为 `4d4727f1`，不等于当前基线 `f5bd3867`，原始录音和完整诊断只保留在本机缓存。

现场目录：`~/.cache/amphion-runtime/diagnostics/four-speaker-collapse-20260927-165102/device-fixed/`。输入 SHA-256 为 `f13ad95b225a88c64161ff9a01770d07718f547c97445b7b6bb61ae146f739e7`，录音时长 19.58 秒。公开结果和指标文件都明确标记 `FAIL_IDENTITY_EXPERIENCE`。

| 阶段 | 证据 | 判定 | 首个偏离 |
| --- | --- | --- | --- |
| input | `AUDIO_FIRST_FRAME`、6 个窗口的 PCM 范围与 exact PCM 校验 | PASS | 否 |
| asr | 4 条 ASR 对齐原句，`DIARIZATION_ASR_PROCESSED` 持续推进 | 已观测，正确性未裁定 | 未证实 |
| segmentation | 6 个 `DIARIZATION_COMMUNITY_WINDOW`，窗口起点和 real range 连续 | 已观测，精度未验证 | 未证实 |
| embedding | 18 条 `DIARIZATION_COMMUNITY_SAMPLES`，每个窗口有样本选择 | 已观测，可分性未验证 | 未证实 |
| clustering | 最终 `DIARIZATION_COMMUNITY_COMMIT` 的 `visibleClusters=[true]`、`clusterToFrozenId=[0]` | FAIL | **首个已观察到的身份塌缩，非已证明根因** |
| identity freeze | 注册表只冻结一个 cluster；没有发生额外的 SDK 编号漂移 | PASS（状态层） | 继承前一层错误 |
| sdk alignment | `DIARIZATION_PUBLIC_RESULT.speakerCount=1`，5 个 turns 中只有 speaker 0 和 UNKNOWN | PASS（传递层） | 传递了错误结果 |
| caller display | 事件日志没有调用方最终 payload | UNVERIFIED | 不能由 SDK 日志证明 |

同一现场的相邻门禁没有掩盖这个问题：`maxPending=0`、`maxInFlight=1`、最大音频延迟 480 ms、finish 到 complete 752 ms，且 `noEarlyLast`、`oneLastThenOneComplete`、`noError` 均通过。也就是说，生命周期和实时队列通过不能替代身份精度通过。

当时的下一步是在 `clustering` 层用同一 PCM、同一窗口和同一 embedding 做状态分叉：保留当前聚类输入，分别比较现有 Community/VBx 路径与候选约束的第一次 `visibleClusters`、`hard`、`trainingIndices` 和身份映射差异。只有证明第二个、第三个和第四个独立声学段在聚类输入中有可用支持，才可以修改身份冻结或展示层；在此之前不能强制建组、复制文本身份或隐藏 UNKNOWN。修复必须回到当前基线构建并重新跑这份四人输入，同时保护单人、两人换人、短插话、overlap 和生命周期门禁。

## 当前状态（2026-09-28）

同一 PCM 在 `f850a7cc` 已输出四人，主机同张量重放与真机一致。旧单组现场已被 PR #233 的行为覆盖，不能继续当作当前 HEAD 根因证据。当前公开 AISHELL-4 四人片段仍输出两人，且上游 VBx 在同一训练向量上也塌缩为两组；后续定位及资源红灯见 [当前推进记录](DIARIZATION_E2E_PROGRESS_20260928.md)。阶段日志存在本身不证明前置阶段通过，上表已撤销原先对分割和 embedding 的过强 PASS。
