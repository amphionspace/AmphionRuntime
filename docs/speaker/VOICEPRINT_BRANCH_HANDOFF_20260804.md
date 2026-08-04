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
- `asr/tools/speaker/ts_asr/core.py`：显式 aggregation、scipy 重采样、FP32 joiner 兼容和降噪 A/B 入口。
- `asr/android/sdk/.../EffectiveSpeechBuffer.kt`、`SessionImpl.kt` 和 Harmony 同名逻辑：评分样本选择与
  session 关联诊断；诊断不包含文本、声纹 ID 或音频内容。
- `docs/speaker/VOICEPRINT_PILOT_PROGRESS_20260728.md`：完整实验进展、指标和限制。
- `docs/speaker/VOICEPRINT_MODEL_AND_TRAINING_PLAN_20260728.md`：模型 A/B 与后续训练门禁。
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
此前 Linux 正式工具链和干净宿主编译通过，但没有签名或连接 Harmony 真机，不能写成真机验收通过。

2026-08-04 提交前复跑：声纹评测工具 23 项、Harmony 声纹评分/PCM 缓冲 28 项、初始静音/
final 生命周期/交付压力工具 28 项通过，脚本语法、Python 编译和 `git diff --check` 通过。本次容器
没有 `java`，Android Gradle 未重跑；Android Debug/Release 的历史通过记录见 pilot 进展文档，
合入门禁仍应在具备 JDK 17 和 Android SDK 34 的环境重新执行上述命令。

## 剩余工作、风险和建议流程

- 本阶段不再继续调 DPDFNet、全局阈值或规则型质量救援；重复同类合成 A/B 不会改变当前选择。
- 若继续限定本机合成数据，下一项应独立启动 embedding fine-tuning：使用 clean anchor、交通噪声、
  混响、距离、codec 和短语音增强，并严格隔离 source/speaker 的 train/dev/holdout。
- 成功门必须在固定 clean FAR 下比较 traffic FRR，并保护短时、低音量、方言和 ASR gated CER；
  还要验证 checkpoint 与 ONNX 导出分数一致。已参与本轮决策的 AISHELL-2/KeSpeech 不得再称 blind。
- overlap、反欺骗和声纹分数可选性的生命周期门禁继续独立验收，不用 verification 精度互相替代。
- 建议下一阶段先使用 `plan` 固化 fine-tuning 数据切分、损失函数、资源预算和停止条件，再用
  `implement` 落地训练与导出链路。
