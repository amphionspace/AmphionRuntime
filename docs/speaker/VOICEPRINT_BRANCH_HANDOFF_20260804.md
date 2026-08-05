# 声纹优化分支交接（2026-08-04）

## 目标与范围

分支 `docs/voiceprint-evaluation-plan` 的目标是用本机公开语料和合成退化数据定位、优化声纹校验，
同时保护 SDK 的 `speakerSimilarity` 可选性和 session 生命周期契约。本阶段不采集真实设备数据，
合成结果不得表述为真机、交通现场或商用 blind 结论。

## 当前状态

- 当前端侧基线仍为 `ERes2Net-base 3D-Speaker`，固定工作点为 `0.4343833029`。
- 当前选定配置是每个身份使用 3 段独立注册语音，分别提取 embedding 后求均值并归一化。
- 公共 SDK 仍接受至少 1 段注册样本；3 段是本机合成评测和调用方的推荐配置，不是接口新门槛。
- 低信噪比主要表现为 target score 下移。下调全局阈值虽能降低 FRR，但会提高 clean 或跨语料 FAR。
- Android/Harmony 评分选择要求 ASR 已有非空 text/token 语音证据；证据或真实 PCM 时长不足时保留
  识别结果并省略 `speakerSimilarity`，不填充、复制或补静音制造分数。
- 2026-07-29 客户 C1～C3 真实回放样例把下一阶段拆成两类不同问题：C1 是轮流讲话时 Speaker VAD
  决策延迟内的尾音泄漏；C2/C3 是单通道重叠语音的目标内容提取。现有句级 verification 优化不能
  回答“哪些字属于机主”，不得把 embedding fine-tuning 作为三类问题共同的默认下一步。
- 2026-08-04 已在 Harmony 真机 `7GK…5655` 上用 `origin/main@1ca9108`、SDK `0.2.9`、唯一 `ZH_EN`
  HAP 和实时 20 ms 喂入复现：`1500/500 ms` 基线为 C1/C2/C3 全失败；`1000/300 ms` 只让 C1 满足
  “含上海、无你好”，C2/C3 仍失败。诊断 HAP 已移除，设备恢复为无 debug 标记的 0.2.9 交付 HAP。
- WeSep TSE、RE-SepFormer 与 Conv-TasNet 两路分离都在主机离线让 C1/C2/C3 逐条通过严格文本门。
  固定 2 秒 Conv-TasNet ONNX 为 20.15 MB，桌面 ORT 1.16.3 中位 RTF 0.0583，曾是唯一进入 Mate 80
  真机资源 pilot 的无训练候选；后续开放集 L2 已命中 target-absent 停止条件，不再作为交付候选。
- 固定 2 秒 Conv-TasNet 已在 Mate 80 完成异步全链路：C1～C3、target-only/other-only、p95 RTF、
  同产物 RSS 基线和 ASR 生命周期门均通过；短期定位为高端机离线 opt-in pilot，不是默认实时能力。
  Linux 同口径复验入口为 `asr/tools/speaker/12_eval_overlap_rescue.py`，只覆盖算法/资源门，不替代
  Harmony `isLast/onComplete/cancel`。
- 正确 16 kHz Libri2Mix checkpoint 的 AISHELL-2 合成 L2 已完成：-5/0 dB test target CER 从
  `101.72%/63.96%` 降到 `24.65%/13.10%`，但 60 个 other-only 中 8 个产生非空 false rescue，
  target-only CER 也从 `2.96%` 微升到 `3.43%`。按冻结停止条件不再搜索 blind separator 选流规则，
  短期回退 C1-only，C2/C3 转 enrollment-conditioned causal TSE。
- 2026-08-05 冻结归因已把这 8 条错误定位到 ERes2Net 短块开放集工作点：15/15 个相关块的原始 other
  PCM 在 separator 前已超过 `0.25`；统一增益后仍为 8/60，15 个块全部选择能量主导非目标流，RMS
  boost p50/p95 仅 `1.00x/1.04x`。因此人数只影响失败率置信度，RMS/低能残留和 separator 推分不是根因。
- 2026-08-05 已完成冻结 `0.35 / 1000/300 ms / 连续 2 窗` 的 C1 target→other 合成矩阵：30 dev /
  60 test speaker、3060 行。test 实时 20 ms 主矩阵把平均非目标音频泄漏降低 `53.24%`、CER 从
  `14.09%` 降到 `4.17%`，但仍有 `30/960` 非目标文本、`16/960` 目标截断；target-only/other-only
  anchor 分别有 `1/60` 提前 endpoint 和 `2/60` 误确认。irregular/single-block 的 state mismatch 为
  `13.33%/99.17%`，所以该参数不升级为正式默认值。

## 已冻结决策

固定同一 probe 和阈值 `0.4343833029` 的 30 dev / 60 test speaker paired A/B：

| Enrollment | clean FAR / FRR | traffic 0 dB FAR / FRR |
| --- | ---: | ---: |
| 1 段 | 0.33% / 5.00% | 0% / 25.83% |
| 3 段 | 0.67% / 0% | 0% / 8.33% |

因此采用“3 段注册 + 固定阈值”，不修改在线 scorer。以下候选已否决：

- DPDFNet baseline：中型 paired A/B 的 5/0 dB FRR 从 `12%/40%` 退化到 `24%/43%`，平均增加
  约 `286.7 ms`；更大 DPDFNet 约 `746 ms`，无主指标收益。
- WHAM `sep_clean` 8 kHz Conv-TasNet：作为 ERes2Net 前端时，原阈值 clean/5/0 dB FRR
  退化到 `63%/83%/90%`；clean-dev 重校准后仍以 clean FAR `4.33%` 换取 0 dB FRR `29%`，
  不进入候选。带宽/人数消融中，单人 clean diagnostic EER 为 `0.17%→2.00%→4.17%`
  （原始/8 kHz 往返/Conv-TasNet），双人 0 dB 重叠为 `9%→16%→20%`，否定“只因人数错配”。
- probe-only 降噪、注册语音加噪、mean/median/whole window aggregation：均无稳定收益。
- 全局降阈值、quality logistic 和规则型救援：AISHELL-2 同域可改善 FRR，但 KeSpeech 或独立 holdout
  出现 FAR/FRR 回归，不能作为跨语料默认策略。
- CampPlus 中文模型约快 `2.59x`，但 0 dB 精度略差，只保留为性能受限候选；ERes2Net-200k、
  ERes2NetV2 和当前 WeSpeaker CAM++ 组合均不替换默认模型。

## 关键实现和文档

- `asr/tools/speaker/07_eval_voiceprint_verification.py`：speaker-disjoint clean/noisy pilot、固定阈值、
  paired enrollment、跨 session、score aggregation、可选 DPDFNet A/B；默认 3 段 enrollment。
- `asr/tools/speaker/08_eval_quality_abstention.py`：质量感知错误排序与 coverage/conditional error 报告。
- `asr/tools/speaker/09_eval_threshold_stability.py`：speaker-cluster bootstrap 阈值稳定性。
- `asr/tools/speaker/10_eval_convtasnet_frontend.py`：冻结旧 trial map 的 Conv-TasNet 前端 paired A/B。
- `asr/tools/speaker/11_eval_convtasnet_ablations.py`：拆分 8 kHz 带宽损失与双人分离任务匹配。
- `asr/tools/speaker/12_eval_overlap_rescue.py`：C1～C3 exact Linux 全链路复验。
- `asr/tools/speaker/13_eval_overlap_rescue_synthetic.py`：16 kHz checkpoint 的合成 L2 开放集/SIR 门。
- `asr/tools/speaker/14_diagnose_overlap_rescue_attribution.py`：冻结 L2 的 oracle 选流、raw-other score 与
  统一增益根因归因。
- `asr/tools/speaker/15_eval_c1_turn_transition_synthetic.py`：冻结 C1 target→other、音量、分帧和
  target-only/other-only anchor；复刻当前 Android/Harmony 每次公开写入最多一次打分的调度。
- `asr/tools/speaker/ts_asr/core.py`：显式 aggregation、scipy 重采样、FP32 joiner 兼容和降噪 A/B 入口。
- `asr/android/sdk/.../EffectiveSpeechBuffer.kt`、`SessionImpl.kt` 和 Harmony 同名逻辑：评分样本选择与
  session 关联诊断；诊断不包含文本、声纹 ID 或音频内容。
- `docs/speaker/VOICEPRINT_PILOT_PROGRESS_20260728.md`：完整实验进展、指标和限制。
- `docs/speaker/VOICEPRINT_MODEL_AND_TRAINING_PLAN_20260728.md`：模型 A/B 与后续训练门禁。
- `docs/speaker/VOICEPRINT_CUSTOMER_CASE_EVIDENCE_20260804.md`：C1～C3 固定症状、离线复算、阈值
  无解证明和仍缺的真机时间线。
- `docs/speaker/VOICEPRINT_NEXT_STEP_MAP_20260804.md`：下一阶段路线图、决策前沿、阻塞关系和停止条件。
- `docs/speaker/TARGET_SPEAKER_EXTRACTION_RESEARCH_20260804.md`：2026 年公开 TSE 权重、一手来源、许可和
  Go/No-Go 矩阵。
- `docs/speaker/VOICEPRINT_OVERLAP_FRONTEND_EXPERIMENT_20260804.md`：WeSep/RE-SepFormer/Conv-TasNet
  逐例文本、声纹分数、RTF/RSS、模型哈希、ONNX parity 与停止理由。
- `docs/speaker/SHORT_TERM_EDGE_FRONTEND_DECISION_20260804.md`：当前真机预算、候选分级、短期接入形态和
  下一轮真机停止条件。
- `docs/speaker/CONVTASNET_HARMONY_FULL_CHAIN_20260804.md`：C1～C3 全链路、负向门、资源基线、评分 A/B
  和实验后恢复证据。
- `docs/speaker/CONVTASNET_LINUX_REPRODUCTION.md`：Linux 配对基线/完整链路命令、输入约定和回传清单。
- `docs/speaker/CONVTASNET_LINUX_NEXT_EXPERIMENT_20260804.md`：澄清 8 kHz WHAM 负结果与 16 kHz 按需
  救援是两个实验问题，并冻结下一轮开放集、SIR、选流消融、解释矩阵和停止条件。
- `asr/tools/speaker/README.md`：工具使用与推荐配置。

实验目录位于 `asr/tools/speaker/results/voiceprint_pilot_*`，按仓库规则忽略，不提交 Git。每个正式目录
应保留 `trials.jsonl`、`summary.json`、`report.md` 和 artifact hash；失败结果不得被后续运行覆盖。

## 验证命令

```bash
python3 -m unittest \
  asr.tools.speaker.test_voiceprint_pilot \
  asr.tools.speaker.test_quality_abstention \
  asr.tools.speaker.test_threshold_stability -v

python3 -m unittest \
  asr.tools.tests.test_harmony_speaker_score_fallback \
  asr.tools.tests.test_harmony_effective_speech_buffer -v

cd asr/android
./gradlew --no-daemon :sdk:testDebugUnitTest :sdk-dingqiao:testDebugUnitTest --console=plain
./gradlew --no-daemon :sdk:testReleaseUnitTest :sdk-dingqiao:testReleaseUnitTest \
  --rerun-tasks --console=plain
```

Harmony 命令行构建和自包含 HAR 验证所需的 `asr/harmony/hvigor/hvigor-config.json5` 已纳入仓库。
2026-08-04 已完成签名 HAP 构建、安装和 C1～C3 真机回放；这证明当前 USB 设备上的调用链和回调证据，
不等于完成全部发布真机矩阵或证明离线 TSE 候选可在 Harmony 运行。

2026-08-04 提交前复跑：声纹评测工具 23 项、Harmony 声纹评分/PCM 缓冲 28 项、初始静音/
final 生命周期/交付压力工具 28 项通过，脚本语法、Python 编译和 `git diff --check` 通过。本次容器
没有 `java`，Android Gradle 未重跑；Android Debug/Release 的历史通过记录见 pilot 进展文档，
合入门禁仍应在具备 JDK 17 和 Android SDK 34 的环境重新执行上述命令。

2026-08-05 L2 归因后复跑 speaker 工具 55 项全部通过；新增文件 `ruff check`、Python 编译、
`git diff --check` 和 450 条 artifact 有限值/唯一性/冻结重放审计通过。最终 ignored artifact 的
`summary.json` / `trials.jsonl` SHA256 分别为 `23e2a7d6…235f` / `37530ca1…f508`。

2026-08-05 C1 全量 ignored artifact 为
`asr/tools/speaker/results/voiceprint_pilot_20260805_c1_turn_transition_full/`；3060 条唯一性、有限值、
60 对 test speaker-disjoint 配对和哈希完整性审计通过。`summary.json` / `trials.jsonl` SHA256 分别为
`76504b16…3858` / `37f7d2a3…d1c7`。该结果只覆盖本机合成 Speaker VAD 调度，不替代真机生命周期门。

2026-08-05 已实现 Android/Harmony 绝对 PCM sample 的 Speaker VAD hop 调度，并把工具 15 默认切换为
`absolute_samples`，同时保留 `legacy_per_call` 重放修复前结果。Android Debug/Release 两模块、Harmony
两份 HAR 编译和 31 项相邻状态测试通过。本机缺少上述 ignored baseline/trials，尚未生成修复后 3060 行
业务结果；当前 USB 设备也不在本地授权清单，真机构建/安装在 license 校验前停止且未改白名单。

## 剩余工作、风险和建议流程

- 本阶段不再继续调 DPDFNet、全局阈值或规则型质量救援；重复同类合成 A/B 不会改变当前选择。
- C1～C3 当前 0.2.9 真机基线和严格业务红灯已经捕获；下一步先冻结 target-only 产品契约，并补齐
  带 target/other 独立源、对齐文本、enrollment 和受控 SIR/SNR 的中文真实域小集。
- C1 参数上限已在冻结合成集失败；Android/Harmony 的绝对 PCM hop 调度已实现。下一最小实验是在保留
  artifact 的 Linux 服务器使用同一输入做 `absolute_samples` 差分重放且不改阈值；模型层 anchor 仍
  失败时，再比较“缓冲提交 + 尾部回退/重解码”，同时保护 partial、目标连续语音和 final/last 生命周期。
- C2/C3 的固定 2 秒 Conv-TasNet 已在扩大到 60 个 test 非注册身份后触发开放集停止门；不再跑 30 轮
  稳压、真机扩身份、阈值/margin 搜索，也不以无 target identity 的 RE-SepFormer 规避同一根因。
- 长期下一实现候选仍应是 `<30 MB`、额外 RSS `<150 MB`、有界 look-ahead 的中文真实域 causal TSE，
  主门为 target CER/WER 与 non-target lexical leakage。
- embedding fine-tuning 改为条件分支：只有真实设备非重叠基线证明在受保护 clean FAR 下 verification
  FRR/DCF 仍是主瓶颈时才启动。若启动，仍须使用 clean anchor、交通噪声、混响、距离、codec 和
  短语音增强，严格隔离 source/speaker/session，并验证 checkpoint/ONNX/platform score parity。
- overlap、反欺骗和声纹分数可选性的生命周期门禁继续独立验收，不用 verification 精度互相替代。
- 具体票据、阻塞关系和退出条件见 `docs/speaker/VOICEPRINT_NEXT_STEP_MAP_20260804.md`；每次只推进
  一个已解除阻塞的决策，不在路线尚未冻结时直接开始生产实现或完整发布矩阵。
