# 选择 C2/C3 重叠前端

- 类型：`wayfinder:prototype`（HITL）
- 状态：closed / 无训练候选未通过开放集与资源门
- 未来训练路线仍依赖：`冻结 target-only 产品契约与成功门`
- 路线图：[机主识别下一阶段路线图](../VOICEPRINT_NEXT_STEP_MAP_20260804.md)

## Question

在 16 kHz 单通道、机主 embedding 已知的前提下，哪类前端能让 C2/C3 的 ASR 输出只保留目标内容，
且不会不可接受地伤害无重叠语音？原型应把以下候选放在同一冻结 trial 上比较：

1. diarization/turn attribution 作为“只适合非重叠”的负对照，明确它不能恢复同一采样中的被遮盖语音。
2. personalized VAD/target-activity detector：判断目标活动区间，但单独使用时不得宣称已分离重叠声音。
3. speaker-conditioned target speech extraction（主候选）：用 enrollment embedding 生成 target-only PCM，
   再复用现有 ASR 和句级 verification 作为二次保险。
4. 端到端 target-speaker ASR 作为高成本候选；只有分离前端达不到主门或端侧预算时才升级。
5. 若宿主可提供多麦原始通道，单列 beamforming/TSE 组合，不与单麦结果混报。

数据至少包含 target-only clean、非语音噪声、target→other 非重叠、受控重叠和真实设备重叠。C2/C3
没有独立源，适合作为固定黑盒回归；训练和客观分离指标必须另用 source-disjoint、逐说话人参考文本和
独立源音频的受控混音。主指标为 target CER/WER、non-target lexical insertion/leakage、无重叠退化、
coverage、RTF、峰值内存、包体与 final 延迟；SI-SDR 等音频指标只能作诊断。

票据应以“选定一个可进入真机 pilot 的前端”或“在冻结预算/门下没有可行候选”关闭，不得以单个
embedding score 提高或试听主观变好代替 target-only 文本门。

## 首个候选与当前缺口

短窗真机探针已经证明 C2/C3 的目标关键词仍随重叠段被丢弃，Speaker VAD 参数路线停止。主候选固定为
speaker-conditioned TSE，diarization 仅作负对照。当前 Harmony 包没有 TSE 权重；sherpa 的 offline
diarization 构建也被关闭，且即使开启也不能恢复同步重叠语音。

下一输入必须包含 target/other 独立源、对齐参考文本、enrollment、受控 SIR/SNR 和混合脚本。只有这些
输入到位后，才能比较 target CER/WER、非目标 lexical leakage、clean 退化和端侧 RTF；C2/C3 混合 WAV
继续保留为黑盒回归，但不能承担训练或客观分离指标。

## 2026-08-04 原型结果

公开 WeSep BSRNN+ECAPA 16 kHz TSE 已用 C1/C2/C3 实测，三条提取后 ASR 都包含“上海”且不包含
“你好”；C2 用 far/mid/near 三段 enrollment 分别运行，结果一致。它证明 enrollment-conditioned TSE
能解决当前黑盒症状，但主机峰值 RSS 约 1.94 GB、双向离线，资源门失败。

SpeechBrain RE-SepFormer 作为通用两路分离正对照，使用当前 ERes2Net 选流后也让三条通过。固定 4 秒
ONNX 与 PyTorch 数值对齐且主机 RTF 足够快，但仍为 83.6 MB/约 430 MB、8 kHz、非因果并存在跨块
permutation 风险。它只能证明“内容可恢复”和“模型图可导”，不能成为生产选择。

因此本票据不再寻找更多英语公开大模型。关闭它仍需：受控独立源数据、target-absent 与 clean 保护门、
一个 `<30 MB`/额外 RSS `<150 MB`/持续真机 RTF `<0.2`/有界 look-ahead 的 causal TSE 候选，以及
FP32→量化 ONNX parity。完整数据见
[重叠前端离线实验](../VOICEPRINT_OVERLAP_FRONTEND_EXPERIMENT_20260804.md)。

## 短期无训练分支的停止结果

16 kHz Conv-TasNet 的三条黑盒样例虽通过，但 speaker-disjoint 合成 L2 已触发 target-absent 停止门：
60 个 test other-only 中 9 个至少接收一块，8 个产生非空文本。冻结归因显示 15 个相关 accepted blocks
全部选择能量主导的非目标流，统一增益后 8 条文本一条未消失；15/15 个原始 other 块在进入 separator
前已经超过 `0.25`，不是 separator 或 RMS 才制造的过门。

1. C1 继续走 `1000/300 ms` Speaker VAD，不为已能解决的问题增加分离延迟。
2. C2/C3 在无训练路径保留原始 ASR/fallback，不让盲分离增强文本覆盖结果。
3. 不进入 Conv-TasNet 阈值/margin 搜索、L4 稳压或真机扩身份；RE-SepFormer 同样没有 target identity，
   不能作为规避该根因的替代。
4. 下一生产候选仍是 enrollment-conditioned、小型 causal TSE；Conv-TasNet 只保留为内容可恢复和
   teacher/负对照证据。

## 收口（2026-08-05）

当前分支限定为本机合成和无训练公开模型验证，已满足停止条件：公开 TSE 资源门失败，通用盲分离在
speaker-disjoint target-absent 门失败，且归因不能由 RMS、阈值或更多同类样本修复。因此本票据以
“冻结预算下没有无训练可行候选”关闭，不再等待本机实验。小型 causal、enrollment-conditioned TSE
属于需要产品契约、受控独立源数据和训练预算的新项目，必须另开范围后重启，不能保留为本分支待办。
