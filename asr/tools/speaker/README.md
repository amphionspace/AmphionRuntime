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
├── 00_download_models.sh           下载 silero_vad / 3D-Speaker eres2net / CAM++
├── 01_enroll_target.py             多模板注册 → target_embedding.npy
├── 02_ts_asr_offline.py            加固版完整 pipeline，输入 wav，输出 [target]/[other] 标签转写
├── 03_eval.py                      ts_hw_test 全量评估：每条 cut 跑 verify + ASR，输出 jsonl
├── 04_check_zipformer_drc.py       扫 encoder onnx metadata，判断是否启用 DRC 训练
├── 04_eval_summary.py              读 03 输出 jsonl → 算 baseline / 方案 A 各阈值的 CER/WER/EER/FAR/FRR
├── 05_rtf_local.py                 主机 CPU 上 bench 声纹模型 RTF（量级参考）
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
    asr/tools/speaker/models/wespeaker_en_voxceleb_CAM++.onnx \
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

## 决策门（参考 [plan](../../.cursor/plans/ts-asr_feasibility_on_sherpa-onnx_75e72f53.plan.md) 第 5 节）

跑完 03 + 05 后按以下结论分支：

- 整体 EER ≤ 5% AND 整体 FAR ≤ 5% AND 主机 CPU RTF（1s 窗）≤ 0.2 → 阶段 1 工程化加固版足够，开新 plan 进入三端工程化
- 重叠场景 FAR > 20% AND 切片 < 1.5s 占比 < 30% → 阶段 2 候选 b（OfflineSpeakerDiarization 当 F1）
- 重叠 FAR > 20% AND 实时性硬要求 → 阶段 2 候选 a（自训 PVAD 130K，单独立项）
- 整体 EER > 10% → 先排查注册质量 / 声学差距，再考虑换 embedding 模型
- zipformer 未启用 DRC AND 业务对 WER 敏感 → 评估"verify 通过段离线复识"加非流式模型
- 主机 CPU RTF（1s 窗）> 0.3 → 优先换 CAM++ INT8 替代 eres2net

## 已知与未知（执行期跟踪）

ts_hw_test 6555 条 cuts 全量跑完，实测结果如下（完整 markdown 报告 [results/eval_full_summary.md](results/eval_full_summary.md)，原始 jsonl [results/eval_full.jsonl](results/eval_full.jsonl)）：

| 已知未知 | 实测 | 来源 | 决策 |
| --- | --- | --- | --- |
| zipformer 是否启用 DRC | 待 04_check_zipformer_drc.py 跑出 | 04 | 实测 RTF 0.053，未触发"WER 敏感 + 非流式复识"路径，本项可推迟 |
| 切片长度中位数 / p10 / p90 / <1.5s 占比 | median 5.19s / 1.14s min / 29.6s max / <1.5s 占 0.3% | dataset.stats() | 不触发"切片 < 1.5s 占比 > 30%"决策门，无需 PVAD 重切 |
| 重叠占比 | 0.1-0.2 22% / 0.2-0.3 16% / 0.3-0.5 35% / ≥0.5 22% | dataset.stats() | 这是合成强制重叠的 stress test，业务真实场景重叠可能更低 |
| eres2net 主机 CPU RTF（pipeline 总） | 0.053 | 03_eval.py timings | 通过决策门 0.20，端侧无瓶颈 |
| CAM++ 主机 CPU RTF | 待 ablation 跑 | 05 / 03 切换 model | 预期减半至 0.025，非阻塞，可后置 |
| positive vs negative score 中位数 | positive p50=0.54 / negative p50=0.10 | 04_eval_summary.py | 区分度足够，EER 7.36%，但未通过 ≤5% 决策门 |
| 推荐阈值 | EER 单阈值 0.26 / 双阈值 LOW 0.20 HIGH 0.30 | 04_eval_summary.py 阈值扫描 | PIPELINE.md 起点 LOW 0.25 / HIGH 0.55 偏严，建议改为 0.30 单阈值或 0.20/0.30 双阈值 |
| 整体 EER | 7.36% @thr=0.26 | 04_eval_summary.py | 不通过 PIPELINE.md "≤5%"决策门，但未到 "> 10%"红线；进多模板 ablation 优化 |
| baseline negative 鬼影率 | 54.27% (178/328) | 04_eval_summary.py | 这是方案 A 价值的来源；@0.30 降至 3.96% |
| baseline zh CER (positive) | 25.68% (3975 条) | 04_eval_summary.py | - |
| baseline en WER (positive) | 24.09% (2252 条) | 04_eval_summary.py | - |
| 方案 A @0.30 zh CER | 推算 27-28% | per-bucket 数据 | 加固点 4 优化阈值后净劣化 +2-3pp |
| 重叠 ≥0.5 桶 FRR @0.40 | 28.77% | 04_eval_summary.py | 6.7.3 节"持续重叠"退化的实测验证 |
