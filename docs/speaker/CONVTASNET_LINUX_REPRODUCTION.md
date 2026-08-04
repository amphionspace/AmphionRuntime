# Conv-TasNet 全链路 Linux 服务器复验

> 本文给出 exact 16 kHz 配对复验的执行命令。为什么既有 8 kHz WHAM 实验并非错误、下一轮怎样扩展到
> 开放集、应如何解释结果和何时停止，见
> [`CONVTASNET_LINUX_NEXT_EXPERIMENT_20260804.md`](CONVTASNET_LINUX_NEXT_EXPERIMENT_20260804.md)。

## 1. 复验目标

Linux 复验与 Mate 80 真机使用同一组平台无关断言：

- 固定 2 秒 Conv-TasNet ONNX 能创建 session，输出为有限的 `[1,2,32000]`；
- 2 秒块、0.5 秒交叠，每块两路都用三段 enrollment 聚合的 ERes2Net 重新选流；
- 每路只计算一个完整 2 秒 embedding，阈值固定为 `0.25`；
- 低置信块静音，cosine crossfade 拼接后重新送入同一套 ZH_EN ASR；
- C1/C2/C3 最终文本必须“含上海、无你好”；
- target-only 必须保留，other-only 必须全部拒绝且 ASR 文本为空；
- separator p95 RTF `<0.35`；相对 `ASR + ERes2Net` 常驻基线的 peak RSS 增量 `<250 MiB`。

Linux 不能证明 Harmony SDK 的 `finish` 前无 `isLast`、一次 `isLast` 后一次 `onComplete`、`cancel`
无回调等公共 API 契约。Linux 报告会把该项固定写为 `NOT_APPLICABLE`，真机证据仍以
[`CONVTASNET_HARMONY_FULL_CHAIN_20260804.md`](CONVTASNET_HARMONY_FULL_CHAIN_20260804.md) 为准。

## 2. 输入目录

模型和音频不提交 Git。在服务器建立一个私有目录，固定文件名如下：

```text
cases/
├── 000_enrollment_far.wav
├── 001_enrollment_mid.wav
├── 002_enrollment_near.wav
├── 101_C1.wav
├── 102_C2.wav
├── 103_C3.wav
├── 201_target_only.wav
└── 202_other_only.wav
```

约束：单通道 WAV；脚本接受其他采样率但会统一重采样到 16 kHz。三段 enrollment 和 target-only 必须
来自同一注册身份；other-only 必须是有身份标注的非注册说话人，不能用噪声代替。

Mate 80 使用的固定 Conv-TasNet ONNX 身份为：

- 大小 `20,147,162 bytes`；
- SHA-256 `f5b040d383007319c67bd2e1862cc6b6b2ac9bef5101581f30c0c00200b3b7ab`；
- 输入 `[1,32000]`，输出 `[1,2,32000]`，opset 17。

服务器运行前必须先核对模型哈希。脚本默认使用
[`CONVTASNET_LINUX_INPUT_HASHES_20260804.json`](CONVTASNET_LINUX_INPUT_HASHES_20260804.json) 自动校验
八段输入，并内置真机使用的 separator、ERes2Net、ZH_EN encoder/decoder/joiner/tokens 哈希；任一不同
会在模型加载前失败。报告仍会逐文件记录实际哈希。不得用同名不同模型覆盖结果而仍与真机数字比较。

## 3. 环境

推荐使用 Python 3.10/3.11 新建独立环境，不复用训练环境：

```bash
python3 -m venv .venv-overlap-rescue
source .venv-overlap-rescue/bin/activate
python -m pip install --upgrade pip
python -m pip install \
  'numpy<2' \
  'onnxruntime==1.16.3' \
  sherpa-onnx \
  soundfile \
  scipy
```

`onnxruntime==1.16.3` 用于对齐 Harmony separator runtime。`sherpa-onnx` wheel 可能自带不同 ORT；报告会
记录 Python 包版本，因此声纹/ASR 的绝对耗时只能在相同环境间比较。Linux 服务器必须使用 CPU
Execution Provider；CUDA 结果不能用于判断 Harmony CPU 预算。

## 4. 两次配对运行

先跑 `ASR + ERes2Net` 常驻基线：

```bash
python asr/tools/speaker/12_eval_overlap_rescue.py \
  --mode baseline \
  --case-dir /private/path/cases \
  --speaker-model /private/path/eres2net.onnx \
  --asr-model-dir /private/path/zh_en_streaming_model \
  --output-dir /private/path/results/linux-baseline \
  --cycles 1 \
  --speaker-threads 2 \
  --asr-threads 2
```

再以独立进程跑完整链路，并引用刚才的基线报告：

```bash
python asr/tools/speaker/12_eval_overlap_rescue.py \
  --mode full \
  --case-dir /private/path/cases \
  --separator-model /private/path/convtasnet_2s.onnx \
  --speaker-model /private/path/eres2net.onnx \
  --asr-model-dir /private/path/zh_en_streaming_model \
  --baseline-report /private/path/results/linux-baseline/report.json \
  --output-dir /private/path/results/linux-full \
  --cycles 1 \
  --separator-threads 4 \
  --speaker-threads 2 \
  --asr-threads 2 \
  --threshold 0.25 \
  --write-enhanced-wav
```

输出目录必须为空，避免覆盖失败 artifact。每次运行至少保留：

- `report.json`：模型/输入哈希、逐块选流和分数、文本、RTF、门禁状态、环境版本；
- `memory.csv`：`/proc/self/status` 的 RSS/HWM/VmData/线程时间线；
- 可选 `cycle-*-enhanced.wav`：只存放在受控服务器目录，不提交仓库。

如果暂时没有负例，可加 `--skip-negative` 先跑 C1～C3，但整体状态会是 `INCONCLUSIVE`，不能当作完整
PASS。脚本返回码只区分执行/门禁失败；`INCONCLUSIVE` 会写入报告并返回 0，便于先收集证据。

## 5. 结果判定

完整 PASS 必须同时满足：

1. `overall_status == "PASS"`；
2. C1/C2/C3 三条 `status == "PASS"`；
3. target-only 和 other-only 均为 PASS；
4. `separator.p95_rtf < 0.35`；
5. `memory.peak_rss_delta_mb < 250` 且 `memory.gate_status == "PASS"`；
6. `failures` 为空；
7. 模型与输入哈希与预期一致。

与真机比较时优先比较选流序列和文本门，其次比较 RTF/RSS量级。x86 Linux 的绝对 RTF/RSS 不能按固定
比例换算成 ARM；它的价值是复现算法、定位输入/模型漂移并为后续长稳压提供更快的回归环境。

## 6. 稳压

单轮通过后再开新输出目录运行 `--cycles 30 --post-observe-seconds 15`。停止条件：任一 case 失败、出现
非有限输出、p95 RTF 超门、peak RSS 增量超门或进程异常。`memory.csv` 至少覆盖 60 秒后才能讨论慢泄漏；
不足 60 秒只报告峰值，不宣布内存斜率通过。

## 7. 回传清单

把以下文本产物放回本分支的评测结果目录或发给复核者；不要上传模型和客户音频：

- baseline/full 两份 `report.json`；
- baseline/full 两份 `memory.csv`；
- `uname -a`、`lscpu`、`free -h`；
- 运行命令和 Git commit；
- 若失败，保留首次失败目录，不用后续重跑覆盖。
