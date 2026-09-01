# Target Speaker ASR 调研期工具集

本目录是 [docs Target_speaker.md](../../android/docs/Target_speaker.md) 调研结论的执行版，落地"方案 A 工程化加固版"MVP，跑通 server 端 Python pipeline 并量化调研文档"已知未知"小节列的 5 项，输出可进入三端工程化或阶段 2/3 演进的决策证据。

不在本目录范围：

- 三端 Kotlin / Swift / gRPC 工程化（production 期开新分支单独立项，复刻 sherpa-onnx 上游 [SherpaOnnxSpeakerIdentification](../../../third_party/sherpa-onnx/android/SherpaOnnxSpeakerIdentification/) 模板）
- 流式 TS-ASR endpointing 嵌入（MVP 走"VAD 切段 + 段后 verify + 整段 decode"）
- 阶段 2/3 演进（PVAD / VoiceFilter-Lite 自训）
- 端到端 TS-ASR 路径（CONF-TSASR / TS-RNNT / DiCoW / Multitalker Parakeet 等已被调研排除，详见调研文档第 412-510 行）

## 目录布局

```
asr/tools/speaker/
├── README.md                       本文件
├── 00_download_models.sh           下载 silero_vad / 3D-Speaker ERes2Net / 中文 CampPlus
├── 01_enroll_target.py             多模板注册 → target_embedding.npy
├── 02_ts_asr_offline.py            加固版完整 pipeline，输入 wav，输出 [target]/[other] 标签转写
├── 03_eval.py                      ts_hw_test 全量评估：每条 cut 跑 verify + ASR，输出 jsonl
├── 04_check_zipformer_drc.py       扫 encoder onnx metadata，判断是否启用 DRC 训练
├── 04_eval_summary.py              读 03 输出 jsonl → 算 baseline / 方案 A 各阈值的 CER/WER/EER/FAR/FRR
├── 05_rtf_local.py                 主机 CPU 上 bench 声纹模型 RTF（量级参考）
├── 06_eval_speaker_vad_aidatatang.py
│                                   Aidatatang 500 人 speaker-VAD endpoint 收益评测
├── 07_eval_voiceprint_verification.py
│                                   speaker-disjoint clean/noisy pilot，dev 冻结阈值后评 test
├── 08_eval_quality_abstention.py   CPU-only 错误风险排序与 abstention 外部复验
├── 09_eval_threshold_stability.py  speaker-cluster bootstrap 阈值稳定性诊断
├── 10_eval_convtasnet_frontend.py  冻结 trial 的 Conv-TasNet → ERes2Net paired A/B
├── 11_eval_convtasnet_ablations.py 拆分 8 kHz 带宽与两人分离任务匹配的消融
├── 12_eval_overlap_rescue.py       Linux CPU 复验固定 2 秒 Conv-TasNet 选流/拼接/ASR 全链路
├── 13_eval_overlap_rescue_synthetic.py
│                                   正确 16 kHz checkpoint 的 speaker-disjoint 合成 L2
├── 14_diagnose_overlap_rescue_attribution.py
│                                   冻结 L2 的 oracle 选流、原始分数和 RMS 归因
├── 15_eval_c1_turn_transition_synthetic.py
│                                   C1 target→other、音量与调用方分帧冻结评测
├── ts_asr/
│   ├── __init__.py
│   ├── core.py                     调研文档第 5 节 5 段骨架函数
│   ├── dataset.py                  ts_hw_test cuts.jsonl.gz 加载 + 路径 rebase + 分桶迭代
│   └── metrics.py                  FAR / FRR / EER / 阈值扫描
├── data/                           target_embedding.npy 与测试集（.gitignore 排除）
├── models/                         下载的声纹 / VAD 模型（.gitignore 排除）
└── results/                        各脚本产物（.gitignore 排除）
```

## 加固点（与调研文档第 4.1 节对应）

阶段 1 方案 A 的 5 个加固点全部内置在 `ts_asr/core.py` 与 `02_ts_asr_offline.py` 里，参数化暴露给命令行。每一点都对应调研文档定量给出的失败域：

| 加固点 | 实现位置 | 解决的失败域 |
| --- | --- | --- |
| 1 多模板注册（≥3 段，5-10s/段，不同语速距离） | `enroll()` 多段均值 + L2 单位化；`01_enroll_target.py` 强制 ≥3 段 | 短音频 EER 暴增、跨域漂移 |
| 2 最短切片 1.5s 门限 | `segment_score()` 入口判断 | 切片 < 2s 时 EER 升 2-3 倍 |
| 3 滑窗 2.5s/1.0s 多打分取 max | `segment_score()` 滑窗循环 | 重叠语音段 embedding 被污染 |
| 4 双阈值 HIGH 0.55 / LOW 0.25 起点 | `02_ts_asr_offline.py --threshold-high/-low`，必须 ROC 标定后回填 | 阈值 0.31 默认值不可信 |
| 5 整段流式 zipformer ASR | `asr_decode_full_segment()` AcceptWaveform + 0.5s tail + InputFinished + while ready: decode | 不需要再加非流式模型 |

## 快速开始

### 0. 准备 venv 与依赖

```bash
python -m venv .venv-speaker
source .venv-speaker/bin/activate
pip install sherpa-onnx onnx soundfile numpy librosa
```

### 1. 下载声纹与 VAD 模型

```bash
bash asr/tools/speaker/00_download_models.sh
# 国内访问慢可挂镜像：
# bash asr/tools/speaker/00_download_models.sh --mirror https://your-mirror/sherpa-onnx
```

### 2. 注册目标说话人

准备 ≥3 段 enrollment 音频，每段 5-10s，覆盖不同声学条件（语速 / 距离 / 设备 / 信道）：

```bash
python asr/tools/speaker/01_enroll_target.py \
  --speaker-model asr/tools/speaker/models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx \
  --enroll-wavs path/to/spk1.wav path/to/spk2.wav path/to/spk3.wav \
  --out asr/tools/speaker/data/target_embedding.npy
```

### 3. 跑离线 TS-ASR pipeline

`--asr-model-dir` 指向 `asr/tools/` 已经导出 + 量化好的流式 zipformer modelDir（4 文件命名见 [asr/tools/MODEL_LAYOUT.md](../MODEL_LAYOUT.md)）：

```bash
python asr/tools/speaker/02_ts_asr_offline.py \
  --asr-model-dir <已经验证过的流式 zipformer modelDir> \
  --speaker-model asr/tools/speaker/models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx \
  --silero-vad-model asr/tools/speaker/models/silero_vad.onnx \
  --target-embedding asr/tools/speaker/data/target_embedding.npy \
  --input path/to/test1.wav path/to/test2.wav \
  --out asr/tools/speaker/results/test_run.jsonl \
  --print-stdout
```

输出 JSONL 每行一段，关键字段：

| 字段 | 含义 |
| --- | --- |
| start_sec / end_sec / duration_sec | VAD 切出的段时间戳 |
| score | 滑窗多打分的余弦最大值；段长 < min_seg_sec 为 null |
| label | target / other / unknown / below_min_seg |
| text | label=target 时的 ASR 转写；其余为空 |
| asr_used | 是否真的跑了 ASR decode |

### 4. 检查流式 zipformer 是否带 DRC 训练

回答调研文档"已知未知 1"：决定整段推理 WER 是否锁死在流式上限。

```bash
python asr/tools/speaker/04_check_zipformer_drc.py \
  --asr-model-dir <你的流式 zipformer modelDir> \
  --out asr/tools/speaker/results/zipformer_drc_check.json
```

输出会直接给"启用 / 未启用 / 建议"。如果未启用且业务对 WER 敏感，决策门会建议"评估单独导出一份非流式 zipformer 做 verify 通过段离线复识"。

### 5. 量声纹模型 RTF（量级参考）

回答调研文档"已知未知 4"。注意：这是主机 CPU 量级，不是 Android 真机；Android arm64-v8a 一般比主机 CPU 慢 1.5-2.5 倍。真机精确 RTF 等 production SDK 工程化阶段加 trace 再量。

```bash
python asr/tools/speaker/05_rtf_local.py \
  --speaker-models \
    asr/tools/speaker/models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx \
    asr/tools/speaker/models/3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx \
  --bench-wav path/to/any_clean_speech.wav \
  --window-secs 1.0 2.5 5.0 \
  --warmup 2 --runs 10 \
  --out asr/tools/speaker/results/rtf_local.json
```

### 6. 评测（baseline vs 方案 A）

03_eval.py 跑 ts_hw_test cuts，对每条 cut 同时算 verify_score + ASR hypothesis（ASR 无条件跑，由下游 04_eval_summary.py 按阈值门控）。一次 ASR 同时支撑 baseline（不门控）与方案 A（按阈值门控）两条曲线。

```bash
# sanity（每桶 5 条，覆盖 6 个桶）
python asr/tools/speaker/03_eval.py \
  --cuts /path/to/ts_hw_test_cuts_all.jsonl.gz \
  --asr-model-dir asr/tools/demo-model/zipformer_L_zh_en \
  --speaker-model asr/tools/speaker/models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx \
  --out asr/tools/speaker/results/eval_sanity.jsonl \
  --max-n 30 --stratified

# 全量（host CPU 约 0.4s/cut，RTF 0.05；6555 条约 45 分钟。如遇 macOS 内存压力 SIGKILL，加 --resume + 分批跑）
python asr/tools/speaker/03_eval.py \
  --cuts /path/to/ts_hw_test_cuts_all.jsonl.gz \
  --asr-model-dir asr/tools/demo-model/zipformer_L_zh_en \
  --speaker-model asr/tools/speaker/models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx \
  --out asr/tools/speaker/results/eval_full.jsonl \
  --resume

# 汇总
python asr/tools/speaker/04_eval_summary.py \
  --jsonl asr/tools/speaker/results/eval_full.jsonl \
  --out-json asr/tools/speaker/results/eval_full_summary.json \
  --out-md   asr/tools/speaker/results/eval_full_summary.md
```

输出（参考 [results/eval_full_summary.md](results/eval_full_summary.md)）：

- 总体 baseline CER/WER（zh / en 分开） vs 方案 A 各阈值（@0.25/@0.40/@0.55）的 CER/WER + FAR/FRR
- verify_score 在 positive / negative 上的分布（min/p10/p50/p90/max/mean）
- EER + 阈值扫描（0.10~0.75 步 0.05）
- 按 sample_type × overlap_ratio 分桶（positive 0.1-0.2 / 0.2-0.3 / 0.3-0.5 / ≥0.5 + negative_distractor + negative_silence）
- 时延分布（每 stage p10/p50/p90/mean）+ pipeline 总 RTF

### 7. 评测目标说话人 VAD endpoint 收益

06_eval_speaker_vad_aidatatang.py 用多说话人样本构造 target + other 连续语音，离线复刻 Android `SpeakerVadConfig` 状态机，专门回答“目标人离场后，speaker-VAD 能否减少非目标人拖进同一个 utterance”的问题。当前跨机器默认语料是 OBS 上版本化的 AISHELL-3 子集：

```bash
python3 asr/tools/speaker/06_eval_speaker_vad_aidatatang.py \
  --dataset-dir ~/.cache/amphion-runtime/test-data/v1/aishell3_test_hotwords_500 \
  --speaker-model shared/models/asr/dingqiao/eres2net.onnx \
  --out-dir asr/tools/speaker/results/aidatatang_speaker_vad_eval \
  --thresholds 0.30 0.35 0.40 0.45 0.50 \
  --win-sec 1.0 \
  --hop-sec 0.3 \
  --consecutive-below 2
```

下述历史数字来自 Aidatatang 语料，不能与新的 AISHELL-3 运行直接比较：默认阈值 0.40 时，平均非目标泄露从 2.337s 降到 0.917s，降幅 60.74%；speaker endpoint 触发率 93.20%；target 确认率 99.00%；target 截断率 1.00%。完整指标定义、场景说明和限制见 [docs/speaker/AIDATATANG_SPEAKER_VAD_EVAL.md](../../../docs/speaker/AIDATATANG_SPEAKER_VAD_EVAL.md)。

### 8. 跑 speaker-disjoint clean/noisy pilot

`07_eval_voiceprint_verification.py` 从 Lhotse cut shards 流式选取带 speaker ID 的
独立 utterance，以不同 recording 做 enrollment/probe，并将 speaker 分成互不重叠的
dev/test。阈值只在 dev 选择，test 同时报告 clean 与合成交通噪声压力结果；如果提供
ASR modelDir，还会报告目标 CER 和被接受非目标文本泄漏。

```bash
python asr/tools/speaker/07_eval_voiceprint_verification.py \
  --cuts /path/to/aishell2/shards/*.jsonl.gz \
  --speaker-model /path/to/eres2net.onnx \
  --asr-model-dir /path/to/streaming-asr-model \
  --noise-cuts /path/to/traffic_noise_cuts.jsonl.gz \
  --snr-db 20 10 5 0 \
  --enroll-utterances 3 \
  --scan-all \
  --out-dir asr/tools/speaker/results/voiceprint-pilot
```

本地合成评测默认使用 3 段 enrollment。公共 SDK 仍兼容单段注册；3 段是当前评测推荐配置，
不是新的接口最低要求。对比注册段数时必须用 `--probe-start` 固定 probe 起点，并用
`--fixed-threshold` 复用同一工作点，避免把样本变化和阈值重选混在一起。

在 30 个 dev / 60 个 test speaker、120 个 target / 300 个 non-target trial 的 paired 数据上，
固定阈值 `0.4343833029` 的结果为：

| Enrollment | clean FAR / FRR | traffic 0 dB FAR / FRR |
| --- | ---: | ---: |
| 1 段 | 0.33% / 5.00% | 0% / 25.83% |
| 3 段 | 0.67% / 0% | 0% / 8.33% |

因此当前本机合成优化选择“3 段注册 + 保持固定阈值”，不通过下调全局阈值换取噪声 FRR。

跨语料复验时，使用 `--fixed-threshold <dev 阈值>` 固定前一语料 dev 选择的工作点；
当前语料的 EER 只作为诊断，不能反过来改部署阈值。

### 9. 在 Linux 复验重叠语音 rescue

`12_eval_overlap_rescue.py` 复刻 Mate 80 pilot 的平台无关部分：固定 2 秒 Conv-TasNet、0.5 秒交叠、
每块两路 ERes2Net 选流、cosine crossfade、ZH_EN ASR 重识别、target-only/other-only、RTF 与配对 RSS
门。先跑 `--mode baseline`，再用 `--mode full --baseline-report ...`；模型和音频只传路径并记录哈希，
不得提交仓库。完整目录约定、命令和判定规则见
[Conv-TasNet Linux 服务器复验](../../../docs/speaker/CONVTASNET_LINUX_REPRODUCTION.md)。
既有 8 kHz WHAM 实验的适用边界、exact 16 kHz 复验后的开放集扩展、选流消融和停止条件见
[Linux 下一轮实验决策](../../../docs/speaker/CONVTASNET_LINUX_NEXT_EXPERIMENT_20260804.md)。

`13_eval_overlap_rescue_synthetic.py` 使用既有三段 enrollment 的冻结 AISHELL-2 trial，构造
target-only、other-only 和 `-5/0/+5 dB` 全时双人重叠；同一 PCM 分别跑 raw ASR 与固定
`0.25` 逐块选流 rescue，报告 target CER、保守归因的 other lexical leakage、false rescue 和
false rejection。它用于 L2 开放集诊断，不替代上述 C1～C3 exact L1：

```bash
python asr/tools/speaker/13_eval_overlap_rescue_synthetic.py \
  --baseline-dir asr/tools/speaker/results/voiceprint_pilot_20260728_aishell2_enroll3_paired \
  --checkpoint /private/path/pytorch_model.bin \
  --separator-model /private/path/convtasnet_2s.onnx \
  --speaker-model /private/path/eres2net.onnx \
  --asr-model-dir /private/path/zh_en_streaming_model \
  --output-dir asr/tools/speaker/results/convtasnet-libri2mix16k-l2 \
  --threshold 0.25 --sir-db -5 0 5
```

本轮 checkpoint SHA256 为 `8d97f012…30adce`。本机导出 ONNX 为 `861a476e…80599`，与 Mate 80
冻结的 `f5b040d3…b7ab` 序列化身份不同；RMS 归一化后的 PyTorch/ONNX 两路相关系数均超过
`0.999999`，但报告仍明确标为 export variant，不能冒充 exact L1 parity。

`14_diagnose_overlap_rescue_attribution.py` 确定性重放上述 L2 artifact，不开放阈值参数。它使用合成
独立源做逐块 PIT SI-SDR oracle 选流，并用“两路共享同一 reconstruction gain”替代逐路 RMS 归一化，
只回答 separator、ERes2Net 选流和增益处理分别贡献了什么：

```bash
python asr/tools/speaker/14_diagnose_overlap_rescue_attribution.py \
  --l2-result-dir asr/tools/speaker/results/convtasnet-libri2mix16k-l2 \
  --separator-model /private/path/convtasnet_2s.onnx \
  --speaker-model /private/path/eres2net.onnx \
  --asr-model-dir /private/path/zh_en_streaming_model \
  --output-dir asr/tools/speaker/results/convtasnet-libri2mix16k-l2-attribution
```

当前 450 条冻结重放的 PCM/选择漂移均为 0，最大 score 误差 `6.56e-7`。test other-only 的 8/60
false rescue 在共享增益反事实下仍为 8/60；15 个被接收块全部选择能量主导的非目标流，独立 RMS boost
p50/p95 仅 `1.00x/1.04x`。15/15 个块的原始 other PCM 在进入 separator 前已经超过 `0.25`，没有一块
是 separator 才推过门。因此 RMS/低能残留假设被证伪，根因位于冻结 ERes2Net 工作点的开放集误接收与
盲分离缺少 target identity 的组合；该结论不授权继续用 test 搜阈值。

`15_eval_c1_turn_transition_synthetic.py` 固定 `threshold=0.35`、`window=1.0s`、`hop=0.3s`、
连续低分窗 `2`，使用同一 speaker-disjoint AISHELL-2 enrollment/probe 构造 target→other 的
重叠/零间隔/静音间隔、音量和调用方分帧矩阵。默认 `--score-schedule absolute_samples` 复刻修复后的
Android/Harmony 绝对 PCM sample deadline；`--score-schedule legacy_per_call` 只用于重放修复前“每次
公开 `writeAudio` 最多触发一次打分”的历史结果：

```bash
python asr/tools/speaker/15_eval_c1_turn_transition_synthetic.py \
  --baseline-dir asr/tools/speaker/results/voiceprint_pilot_20260728_aishell2_enroll3_paired \
  --speaker-model /private/path/eres2net.onnx \
  --asr-model-dir /private/path/zh_en_streaming_model \
  --output-dir asr/tools/speaker/results/c1-turn-transition-absolute \
  --score-schedule absolute_samples
```

调度门通过后，用同一工具和冻结输入比较尾部提交策略；不改阈值，也不复用旧输出目录：

```bash
python asr/tools/speaker/15_eval_c1_turn_transition_synthetic.py \
  --baseline-dir asr/tools/speaker/results/voiceprint_pilot_20260728_aishell2_enroll3_paired \
  --speaker-model /private/path/eres2net.onnx \
  --asr-model-dir /private/path/zh_en_streaming_model \
  --output-dir asr/tools/speaker/results/c1-turn-transition-buffered-tail \
  --score-schedule absolute_samples \
  --publication-policy buffered_tail_commit
```

`buffered_tail_commit` 固定保留 `consecutiveBelow × hop = 600 ms` PCM。目标持续时 partial 只从已提交
前缀产生，稳态最多增加 600 ms；确认离场或 `finish` 时已有未决低分则丢弃尾部，并只重解码提交前缀；
clean `finish` 提交尾部，未确认目标则拒绝，`cancel` 直接丢弃且不产生 final/complete。该选项只做离线
架构实验，不修改 SDK 默认行为；若目标截断、非目标文本或 target-only/other-only anchor 任一仍失败，
停止该无训练 C1 默认路线，不在 test 上调整 holdback 或阈值。

2026-08-05 `legacy_per_call` 全量结果为 30 dev / 60 test speaker、3060 行；test 主矩阵 960 行。实时 20 ms
喂入时目标确认率 `100%`，平均非目标音频泄漏从 `0.973s` 降到 `0.455s`（降幅 `53.24%`），
session CER 从 `14.09%` 降到 `4.17%`，但仍有 `30/960` 行发布了可归因的非目标文本，且
`16/960` 行发生目标截断。独立 target-only anchor 中实时喂入 `1/60` 被提前 endpoint；
other-only anchor 中 `2/60` 被误确认。相对实时 20 ms，irregular 分帧的 state mismatch 为
`13.33%`，single-block 为 `99.17%`。因此该参数只能作为 C1 prototype 证据，未通过正式默认门；
结果目录保留 `trials.jsonl`、`summary.json`、`report.md` 和环境/模型哈希，不应用 test 重调阈值。

同日 `absolute_samples` 使用相同 baseline/trials、模型哈希、seed 和参数完成差分重放。2340 条实时路径
与 legacy 逐行一致；720 条 irregular/single-block 对照全部收敛到实时参考，两个模式的 state mismatch
均为 `0%`、exact endpoint match 均为 `100%`。严格门仍为 **FAIL**：上述 `16/960` 目标截断、
`30/960` 非目标文本、target-only `1/60` 提前 endpoint 和 other-only `2/60` 误确认均未改变。
因此 hop 调度根因已修复，剩余失败归属模型/窗口判决能力；随后冻结缓冲提交与尾部回退作为最后一个
候选，不再在同一 test 上调阈值。

同日 `buffered_tail_commit` 使用相同输入和时间线完成 3060 行重放，严格门仍为 **FAIL**。test 主矩阵
的平均非目标音频泄漏从 absolute 的 `0.455s` 降到 `0.133s`，发布非目标文本从 `30/960` 降到
`1/960`；代价是目标截断从 `16/960` 增至 `242/960`（`1.67% → 25.21%`），published CER 从
`4.17%` 微升到 `4.25%`。target-only `1/60` 提前 endpoint 和 other-only `2/60` 误确认也未消失，
分帧一致性保持 `100%`。按预先冻结的停止条件，不扩大 600 ms holdback、不改阈值，C1 无训练正式
默认路线关闭。

可用 `--denoiser-model <dpdfnet.onnx>` 做前端降噪 A/B；`--denoiser-scope all` 同时处理
enrollment/probe（默认），`probe` 只处理 probe。当前中型 paired 结果中，不降噪在
clean/5/0 dB 的 FAR/FRR 分别为 `0/1%`、`0/12%`、`0/40%`；DPDFNet baseline 为
`0/1%`、`0/24%`、`0/43%`，且平均增加约 `286.7 ms` 处理时间，因此不纳入推荐配置。

如果 recording ID 可解析 session，可用命名组 `session`（或第一个捕获组）强制 enrollment/probe
跨 session。例如 LibriSpeech 的 `speaker-chapter-utterance`：

```bash
python asr/tools/speaker/07_eval_voiceprint_verification.py \
  ... \
  --session-id-regex '^[^-]+-(?P<session>[^-]+)-'
```

该参数只保证提取出的 session ID 不相交；chapter/call ID 是否等同真实日期、设备或现场 session，
仍需由语料 provenance 证明。

WeSpeaker CAM++ release 的 metadata 为 `normalize_samples=0`，与本工具默认的
`[-1, 1]` float PCM 契约不同。即使显式使用 `--waveform-scale 32768`，当前 runtime/scorer
组合的同人/异人分数仍接近随机，因此不能作为替换候选。3D-Speaker 系列 metadata 为
`normalize_samples=1`，保持默认 `--waveform-scale 1`。完整模型 A/B 与训练路线见
[VOICEPRINT_MODEL_AND_TRAINING_PLAN_20260728.md](../../../docs/speaker/VOICEPRINT_MODEL_AND_TRAINING_PLAN_20260728.md)。

该模式只用于跑通评测链路和发现 clean→noise 退化。ASR corpus 通常没有跨日/session
真值，合成加噪也不包含真实设备、距离、混响、AGC 和风噪耦合，不能作为交通现场
blind test 或商用声明。

2026-07-28 至 2026-07-30 的 AISHELL-2 扩样、KeSpeech 外部固定阈值复验、paired enrollment
ablation 见 [VOICEPRINT_PILOT_PROGRESS_20260728.md](../../../docs/speaker/VOICEPRINT_PILOT_PROGRESS_20260728.md)。

### 9. 跑质量感知 abstention T0

该实验冻结原始 `speakerSimilarity` 和声纹阈值，只用 score 与线上可观测波形特征排序高风险决定。
condition/SNR 仅用于报告，不进入模型。AISHELL-2 用作开发集，KeSpeech 仅为 external diagnostic：

```bash
python asr/tools/speaker/08_eval_quality_abstention.py \
  --train-trials asr/tools/speaker/results/voiceprint_pilot_20260728_aishell2_large_traffic/trials.jsonl \
  --external-trials asr/tools/speaker/results/voiceprint_pilot_20260728_kespeech_external_traffic/trials.jsonl \
  --speaker-threshold 0.4343833029 \
  --abstain-budgets 0.05 0.10 0.20 \
  --out-dir asr/tools/speaker/results/voiceprint-quality-abstention
```

报告必须同时读取 coverage、target/non-target coverage、error capture 和 conditional FAR/FRR；
不能只报告 abstain 后下降的错误率。

### 10. 诊断 calibration threshold 稳定性

对 dev 的 target/enrollment speaker 整簇重采样；每轮重新选择阈值，再投到固定 test。该工具只回答
阈值选择对 calibration speaker 抽样是否敏感，不为产品自动选择阈值：

```bash
python asr/tools/speaker/09_eval_threshold_stability.py \
  --trials /path/to/session-disjoint/trials.jsonl \
  --iterations 500 --far-limit 0.05 \
  --out-dir asr/tools/speaker/results/voiceprint-threshold-bootstrap
```

### 11. 复验 Conv-TasNet 前端

Conv-TasNet 是两路语音分离前端，不是声纹 embedding 模型。该工具读取已完成的 baseline result，
逐条复用 speaker、enrollment、probe、noise 和 SNR；两路输出都交给 ERes2Net，并对 target 和
non-target 一律取最大相似度。checkpoint 使用 Asteroid 的 WHAM `sep_clean` 8 kHz 研究模型：

运行环境需自行提供 `torch`、`asteroid`、`scipy` 和 `sherpa-onnx`；这些只用于本机诊断，不加入
产品依赖。checkpoint 不进入仓库，可从模型卡
`https://huggingface.co/mpariente/ConvTasNet_WHAM_sepclean` 获取；本轮文件 SHA256 为
`db8de6c4d9075c484760dbe6106a544e3cd8f22b69f91868ecabc8b869f9a5a5`。输出目录必须为空或不存在，
避免后续运行覆盖已有成功/失败 artifact。

```bash
python asr/tools/speaker/10_eval_convtasnet_frontend.py \
  --baseline-dir asr/tools/speaker/results/voiceprint_pilot_20260730_medium_baseline \
  --conv-tasnet-model asr/tools/speaker/models/convtasnet_wham_sepclean.pt \
  --out-dir asr/tools/speaker/results/voiceprint-convtasnet \
  --device cuda:0
```

在 30 dev / 100 test speaker、1,320 个冻结 trial 上，ERes2Net baseline 的 clean/5/0 dB
FAR/FRR 为 `0/1%`、`0/12%`、`0/40%`。Conv-TasNet 使用原阈值时变为
`0.33/63%`、`0.33/83%`、`0.33/90%`；用 clean dev EER 重校准后仍为
`4.33/5%`、`4.33/23%`、`3.67/29%`。按 baseline dev FAR=0 约束选点时，test clean/5/0 dB
为 `0.67/26%`、`0.67/49%`、`0.67/59%`。因此该 checkpoint 不改善当前合成交通噪声声纹，
不纳入端侧候选。

该负结果只覆盖英文 WHAM 训练的 8 kHz 两人分离模型；不能外推为所有目标说话人提取模型均无效。
checkpoint 的研究数据许可也不满足直接商用分发结论。

### 12. 拆分 Conv-TasNet 的退化来源

下面的消融先对全部 1,320 条 trial 只执行 `16k→8k→16k`，再从 clean trial 中固定抽取每个
target 的一正一负，合成 260 条 0 dB 全时双人重叠。双人实验分别比较直接 16 kHz、8 kHz
往返、Conv-TasNet 三条路径；干扰人不允许是 enrolled target 或原 probe speaker：

```bash
python asr/tools/speaker/11_eval_convtasnet_ablations.py \
  --baseline-dir asr/tools/speaker/results/voiceprint_pilot_20260730_medium_baseline \
  --existing-convtasnet-dir \
    asr/tools/speaker/results/voiceprint_pilot_20260804_medium_convtasnet_wham_sepclean \
  --conv-tasnet-model asr/tools/speaker/models/convtasnet_wham_sepclean.pt \
  --out-dir asr/tools/speaker/results/voiceprint-convtasnet-ablations \
  --device cuda:0 --sir-db 0 --negatives-per-target 1
```

单人 clean diagnostic EER 从原始 16 kHz 的 `0.17%` 变为仅 8 kHz 往返的 `2.00%`，再变为
Conv-TasNet 的 `4.17%`。双人 0 dB 重叠 test diagnostic EER 依次为 `9%/16%/20%`；按各自
dev 阈值，FAR/FRR 为 `4%/11%`、`8%/21%`、`20%/22%`。因此 8 kHz 带宽是主要退化源之一，
但即使人数与两源分离任务匹配，该 checkpoint 仍比单纯带宽对照更差，不能把负结果只归因于
“输入只有一个人”。

## 决策门（参考 [plan](../../.cursor/plans/ts-asr_feasibility_on_sherpa-onnx_75e72f53.plan.md) 第 5 节）

跑完 03 + 05 后按以下结论分支：

- 整体 EER ≤ 5% AND 整体 FAR ≤ 5% AND 主机 CPU RTF（1s 窗）≤ 0.2 → 阶段 1 工程化加固版足够，开新 plan 进入三端工程化
- 重叠场景 FAR > 20% AND 切片 < 1.5s 占比 < 30% → 阶段 2 候选 b（OfflineSpeakerDiarization 当 F1）
- 重叠 FAR > 20% AND 实时性硬要求 → 阶段 2 候选 a（自训 PVAD 130K，单独立项）
- 整体 EER > 10% → 先排查注册质量 / 声学差距，再考虑换 embedding 模型
- zipformer 未启用 DRC AND 业务对 WER 敏感 → 评估"verify 通过段离线复识"加非流式模型
- 当前 ERes2Net 在目标设备上阻塞 RTF、冷启动或包体门限 → 单独评测中文 CampPlus；不得以主机 RTF 直接换默认模型

## 已知与未知（执行期跟踪）

ts_hw_test 6555 条 cuts 全量跑完，实测结果如下（完整 markdown 报告 [results/eval_full_summary.md](results/eval_full_summary.md)，原始 jsonl [results/eval_full.jsonl](results/eval_full.jsonl)）：

| 已知未知 | 实测 | 来源 | 决策 |
| --- | --- | --- | --- |
| zipformer 是否启用 DRC | 待 04_check_zipformer_drc.py 跑出 | 04 | 实测 RTF 0.053，未触发"WER 敏感 + 非流式复识"路径，本项可推迟 |
| 切片长度中位数 / p10 / p90 / <1.5s 占比 | median 5.19s / 1.14s min / 29.6s max / <1.5s 占 0.3% | dataset.stats() | 不触发"切片 < 1.5s 占比 > 30%"决策门，无需 PVAD 重切 |
| 重叠占比 | 0.1-0.2 22% / 0.2-0.3 16% / 0.3-0.5 35% / ≥0.5 22% | dataset.stats() | 这是合成强制重叠的 stress test，业务真实场景重叠可能更低 |
| eres2net 主机 CPU RTF（pipeline 总） | 0.053 | 03_eval.py timings | 通过决策门 0.20，端侧无瓶颈 |
| 中文 CampPlus 2.5s 单核 RTF | 0.0141（当前 ERes2Net 为 0.0365） | paired model A/B + 05 | 约快 2.59x，但 0 dB FRR 更高，只作性能备选 |
| positive vs negative score 中位数 | positive p50=0.54 / negative p50=0.10 | 04_eval_summary.py | 区分度足够，EER 7.36%，但未通过 ≤5% 决策门 |
| 推荐阈值 | EER 单阈值 0.26 / 双阈值 LOW 0.20 HIGH 0.30 | 04_eval_summary.py 阈值扫描 | PIPELINE.md 起点 LOW 0.25 / HIGH 0.55 偏严，建议改为 0.30 单阈值或 0.20/0.30 双阈值 |
| 整体 EER | 7.36% @thr=0.26 | 04_eval_summary.py | 不通过 PIPELINE.md "≤5%"决策门，但未到 "> 10%"红线；进多模板 ablation 优化 |
| baseline negative 鬼影率 | 54.27% (178/328) | 04_eval_summary.py | 这是方案 A 价值的来源；@0.30 降至 3.96% |
| baseline zh CER (positive) | 25.68% (3975 条) | 04_eval_summary.py | - |
| baseline en WER (positive) | 24.09% (2252 条) | 04_eval_summary.py | - |
| 方案 A @0.30 zh CER | 推算 27-28% | per-bucket 数据 | 加固点 4 优化阈值后净劣化 +2-3pp |
| 重叠 ≥0.5 桶 FRR @0.40 | 28.77% | 04_eval_summary.py | 6.7.3 节"持续重叠"退化的实测验证 |
