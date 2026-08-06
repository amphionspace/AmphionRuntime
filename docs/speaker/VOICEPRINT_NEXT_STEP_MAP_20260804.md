# 机主识别下一阶段路线图

## Destination

在不破坏 `speakerSimilarity` 可选性和 session 生命周期契约的前提下，为轮流讲话尾音控制与重叠
目标说话人识别分别冻结可实现的架构、主指标、停止条件和真机 pilot；到达终点时，执行团队不再需要
猜测“继续调 verification、改 endpoint，还是引入目标语音提取”。

## Notes

- 本路线图负责消除决策不确定性，不直接交付生产实现。
- 默认输入为 16 kHz 单通道 PCM；若宿主能稳定提供多麦阵列原始通道，应重新评估波束形成路线。
- 客户 C1～C3 是固定回归证据，不是统计精度集；原始 WAV/日志保持外部只读，不提交仓库。
- 轨 A（句级 verification）、轨 B（轮流讲话过滤）、轨 C（重叠目标说话人 ASR）和生命周期门禁分别
  验收，禁止用一条轨的指标替代另一条。
- 每项耗时验证开始前必须写清要证伪的风险、预计耗时和停止条件；已有同 commit/设备/产物结果复用。
- 相关背景：
  [客户 C1～C3 证据](VOICEPRINT_CUSTOMER_CASE_EVIDENCE_20260804.md)、
  [评测最佳实践](VOICEPRINT_EVALUATION_BEST_PRACTICES.md)、
  [现有 verification pilot](VOICEPRINT_PILOT_PROGRESS_20260728.md)。

## Decisions so far

- [客户 C1～C3 证据](VOICEPRINT_CUSTOMER_CASE_EVIDENCE_20260804.md) — C1 是有界检测延迟内的非目标
  尾音泄漏；C2/C3 是单通道重叠内容归属问题，单一 final 分数和阈值不能同时解决。
- [声纹模型 A/B 与训练路线](VOICEPRINT_MODEL_AND_TRAINING_PLAN_20260728.md) — 轨 A 暂时保留当前
  ERes2Net、3 段 enrollment 和冻结工作点；DPDFNet、公开模型替换和质量规则未通过跨语料保护门。
- [Aidatatang Speaker VAD 评测](AIDATATANG_SPEAKER_VAD_EVAL.md) — 1.0 s/0.3 s 的离场检测能减少
  但不能消除非目标拖尾，阈值提高同时增加目标截断风险。
- [评测最佳实践](VOICEPRINT_EVALUATION_BEST_PRACTICES.md) — verification、轮流讲话过滤和重叠
  target-only ASR 是不同任务，必须使用不同真值与指标。
- `0.2.9 / 1ca9108` Harmony 真机逐窗时间线已经证明：`1500/500 ms` 的 Speaker VAD 判决延迟会让
  C1 非目标尾音进入同一 final；`1000/300 ms` 能让 C1 的“上海”目标短语单独放行且不泄漏“你好”。
- 同一短窗探针对 C2/C3 仍无法保留含“上海”的目标短语。SDK 生命周期和旧的宽松用例断言会 PASS，
  但精确业务门 FAIL；因此 C2/C3 不得继续归入 Speaker VAD 参数优化，必须进入 speaker-conditioned
  target speech extraction（TSE）可行性轨。离线 diarization 只作为不能恢复重叠语音的负对照。
- [重叠前端离线实验](VOICEPRINT_OVERLAP_FRONTEND_EXPERIMENT_20260804.md) — WeSep enrollment-conditioned
  TSE 与 RE-SepFormer 两路分离正对照都让 C1/C2/C3 逐条满足“含上海、无你好”，内容恢复可行性已证明；
  但 WeSep 峰值 RSS 约 1.94 GB，固定 4 秒 RE-SepFormer ONNX 仍为 83.6 MB/约 430 MB 且没有 target
  identity。公开大模型直接进 Harmony 的路线停止，下一阶段转为中文真实域小型 causal TSE 训练/蒸馏。
- 用户短期不投入训练后，补测 16 kHz Conv-TasNet：5.07M 参数、20.1 MB 固定 2 秒 ONNX，C1/C2/C3
  分块后逐条满足“含上海、无你好”；但 60 个 speaker-disjoint other-only test 中 8 个产生非空 false
  rescue，开放集 L2 已按冻结门失败。归因进一步证明 15/15 个误接收块的原始 other 分数在 separator 前
  已超过 `0.25`，统一增益不能消除任何一条；因此停止无训练盲分离真机扩展，不能用三条小样例覆盖该结论。
- [C1 独立 target→other 合成复验](voiceprint-next-steps/SELECT_C1_TAIL_CONTAINMENT.md) — 冻结
  `0.35 / 1000/300 ms / 连续 2 窗` 在 60 个 test speaker 的实时 20 ms 主矩阵中把平均非目标音频
  泄漏降低 `53.24%`，但 `30/960` 行仍有非目标文本、`16/960` 行目标截断；target-only/other-only
  anchor 分别有 `1/60` 提前 endpoint 和 `2/60` 误确认。修复前 irregular/single-block 相对实时分帧的
  state mismatch 为 `13.33%/99.17%`；absolute replay 已降为 `0%/0%` 且 2340 条实时路径零漂移，
  但模型层失败完全保留，因此参数候选仍未通过正式默认门。
- [C1 buffered-tail 收尾](BUFFERED_TAIL_LINUX_COMPLETION_20260805.md) — 固定 600 ms 回退把 test
  非目标文本从 `30/960` 降到 `1/960`，但目标截断从 `16/960` 增至 `242/960`，短/中/长桶均超过
  `23%`；target-only/other-only anchor 失败也未消失。按冻结停止条件关闭 C1 无训练默认路线。

## Closure status

- [冻结 target-only 产品契约与成功门](voiceprint-next-steps/FREEZE_TARGET_ONLY_CONTRACT.md) — deferred；
  需要产品、业务风险和测试负责人选择，当前没有生产候选，不是本分支本机待办。
- [选择 C1 尾音控制架构](voiceprint-next-steps/SELECT_C1_TAIL_CONTAINMENT.md) — 参数候选和
  `buffered_tail_commit` 均已完成冻结重放并 FAIL；C1 无训练正式默认路线关闭，本票据不进入 SDK 实现。
- [选择 C2/C3 重叠前端](voiceprint-next-steps/SELECT_OVERLAP_FRONTEND.md) — 无训练候选已因开放集或资源门
  关闭；训练型 speaker-conditioned TSE 需要独立项目、受控数据和预算，不是本分支本机待办。

## Short-term no-training path

- C1：`1000/300 ms` 只保留为已知 C1 单例和研究证据，不改正式默认值。hop 调度修复保留，但参数与
  600 ms buffered-tail 都未通过业务门；当前没有无训练端侧默认候选。
- C2/C3：保留原始 ASR/fallback，不用 Conv-TasNet 或 RE-SepFormer 的不确定增强文本覆盖结果。当前没有
  通过 target-absent/open-set 门的无训练端侧候选。
- 不跑 Conv-TasNet L4 稳压或更多真机身份扩展；人数扩充只能收紧失败率估计，不能修复已经出现的
  target-absent 误接收。只有新立项的 enrollment-conditioned causal TSE 训练/蒸馏才可能改变结论。

## Deferred external gates

- [冻结真实设备双域 pilot](voiceprint-next-steps/FREEZE_REAL_DEVICE_PILOT.md) — 当前无候选，已关闭；未来
  训练路线产出新候选后必须以新 protocol 重新开票。

## Future work requiring a new scope

- **轨 A embedding fine-tuning 是否启动。** 只有真实设备、非重叠、跨 session 基线在受保护 clean FAR
  下仍显示 verification FRR/DCF 是主要瓶颈，才把 T2 从训练候选提升为下一实验；C1～C3 本身不是
  启动 embedding fine-tuning 的证据。
- **目标语音提取的生产模型与训练数据。** 公开模型已确认 C2/C3 的 target-only 文本存在可行空间，但都
  不满足资源/因果门。下一选择是以 WeSep/REAL-TSE recipe 为训练参考、用公开 offline 模型作 teacher，
  训练/蒸馏中文真实域小型 causal TSE；具体结构要等独立源受控集到位后冻结。2026-08-06 补充候选、
  causal/stateful 区分和服务器验证顺序见
  [Causal Target-Speaker TSE 开源模型图谱与端侧可用性结论](CAUSAL_TSE_MODEL_LANDSCAPE_20260806.md)。
- **生产接入和版本迁移。** 待架构、资源预算和真机 pilot 门冻结后再拆 Android/Harmony 实施；在此之前
  不承诺 0.2.9 或某个参数组合解决客户问题。
- **正式 blind 规模。** 由真实设备 pilot 的 speaker/session cluster 方差和关键失败桶决定，不提前按
  任意“准确率”反推人数或 trial 数。

## Out of scope

- 继续重复 DPDFNet、全局阈值、规则型质量救援或相同公开模型 A/B；现有合成证据已经达到停止条件。
- 用 C1～C3 三条样例计算 FAR/FRR、对外准确率或商用工作点。
- 反欺骗、回放/TTS/VC 检测；它们属于独立安全轨，不能由 target-only 结果代替。
- 在架构选择前执行完整发布真机矩阵、从头训练大型 TS-ASR 或重写现有 ASR。
