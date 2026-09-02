# Inference Quick Start

## Vocoder 更新（2026-06-22）

**由于性能问题，en-zh 推理默认不再使用 `afnas_pupuvocoder`，改为使用 [Vocos](https://github.com/gemelo-ai/vocos) 声码器。**

此前基于 AFNAS / PuPuVocoder 的路径在 CPU 推理时 RTF 过高，成为端到端延迟的主要瓶颈。Vocos 在相同 mel 条件下推理更快，因此 `inference_stream.py` 与 `infer_en-zh.sh` 已切换为 Vocos。

Vocos 相关文件均 vendored 在仓库内，无需依赖外部 `VOCOS` 仓库或 `afnas_pupuvocoder_*` 目录：

```
vocos/
├── vocoder.py        # 推理加载器
├── generator.ckpt    # generator 权重（仅 backbone + head，~38MB，git-lfs）
├── config.yaml       # 训练配置（用于还原 mel / 模型超参）
└── *.py              # vendored Vocos 模型代码
```

- 默认 checkpoint：`./vocos/generator.ckpt`
- 采样率：24 kHz，`n_mels=100`，`hop_size=384`
- `inference_stream.py` 固定使用 Vocos 声码器（默认 `./vocos/generator.ckpt`）

## 1) Clone with Git LFS (required)

This repo contains checkpoint files, so Git LFS is required.

```bash
# install git-lfs first (Ubuntu/Debian)
apt-get update && apt-get install -y git-lfs

git lfs install
git clone https://github.com/hhxxwwestrella/Multilingual_LITs.git
cd Multilingual_LITs
git lfs pull
```

## 2) Prepare environment

**不再需要安装 `espeak-ng`。** 推理走预计算的 ARPAbet / 拼音 token，不依赖 G2P。

```bash
conda create -n lits python=3.10.18
conda activate lits
pip install -r lits_requirements.txt
pip install ttsfrd==0.2.1 -f https://modelscope.oss-cn-beijing.aliyuncs.com/releases/repo.html
```

## 3) Input format (`wav_path|text`)

每行一条样本，字段用 `|` 分隔：

```text
output_name.wav|text_for_synthesis
```

也支持显式指定说话人：`wav_path|spk_id|text`（`spk_id`：0=英语，1=中文/非英语）。

**仅使用 `wav_path` 的文件名（不含路径）作为输出 wav 名。**

两字段格式下，脚本会根据内容自动选说话人：含汉字、阿拉伯文、孟加拉文，或匹配 `^[a-z]+[0-5]$` 的拼音音节 → `spk=1`，否则 → `spk=0`。

### en-zh：请直接提供 phoneme / 拼音 token

模型 `en-zh`（`--model_lang en-zh`）使用 `pinyin_direct_mixed_cleaners`，**不会**把普通英文单词或汉字自动转成音素。请在 manifest 里写好：

| 语言 | 输入形式 | 示例 |
|------|----------|------|
| 英语 | 大写 **ARPAbet** token，音节之间用 `/` 分词 | `HH AH0 L OW1 / W ER1 L D` |
| 中文 | 带声调数字的 **拼音**（小写，空格分音节） | `ni2 hao3 shi4 jie4` |
| 英中混合 | 同一段里混用 ARPAbet + 拼音；可用 `/` 分隔英文词 | `wo3 xi3 huan1 / M AH0 SH IY1 N / L ER1 N IH0 NG` |

### en-zh-dict：支持纯文本或 phoneme / 拼音 token

`infer_en-zh.sh` 默认使用 `--model_lang en-zh-dict`（`en_zh_dict_mixed_cleaners`）。在此模式下：

- **纯文本**：可直接写汉字或英文单词；汉字经字表转拼音，英文经**开源版 CMUdict G2P** 转 ARPAbet。
- **phoneme / 拼音 token**：若输入已是 ARPAbet 或带声调拼音，则与 `en-zh` 相同格式，会原样透传。

纯文本示例：

```text
test_plain_001.wav|你好世界
test_plain_002.wav|Hello world
test_plain_003.wav|我喜欢 machine learning
```

phoneme / 拼音示例（`en-zh` 必填；`en-zh-dict` 也可直接提供）：

纯英文（`mock_test_in_phones/test_en.txt`）：

```text
test_en_001.wav|HH AH0 L OW1 / W ER1 L D / .
test_en_002.wav|G UH1 D / M AO1 R N IH0 NG / EH1 V R IY0 W AH2 N / .
```

纯中文（`mock_test_in_phones/test_zh.txt`）：

```text
test_zh_001.wav|jin1 tian1 tian1 qi4 zhen1 hao3
test_zh_002.wav|wo3 xi3 huan1 xue2 xi2 xin1 zhi1 shi2
```

混合（建议三字段并设 `spk_id=1`，见 `mock_test_in_phones/test_en-zh.txt`）：

```text
test_mix_001.wav|1|wo3 xi3 huan1 / M AH0 SH IY1 N / L ER1 N IH0 NG
```

### 其他语种（ar-en / bn-en）

- **ar-en / bn-en**：阿拉伯语或孟加拉语字符（空格分字）+ 英文 ARPAbet，规则见 `lits/text/language_cleaners.py`。
- 可用 `infer_ar-en.sh` 或 `infer_benchmark.sh`（见下文）。

## 4) Streaming inference

### en-zh（2026-06-01 checkpoint + 2026-06-22 vocoder）

`model_checkpoints/en-zh.ckpt` 已于 **0601** 更新；声码器于 **0622** 从 AFNAS/PuPuVocoder 切换为 Vocos（见上文）。请使用仓库根目录脚本：

```bash
conda activate lits
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$LD_LIBRARY_PATH"

./infer_en-zh.sh <input_txt> [infer_id]
```

- 默认 acoustic checkpoint：`./model_checkpoints/en-zh.ckpt`
- 默认 vocoder：`vocos`（`./vocos/generator.ckpt`）
- 输出目录：`./infer_output/<infer_id>/`
- 元数据：`./infer_output/<infer_id>/meta.txt`
- 输出采样率：24 kHz

如需手动指定 vocoder checkpoint，可直接调用 `inference_stream.py`，例如：

```bash
python inference_stream.py \
  --model_lang en-zh-dict \
  --checkpoint ./model_checkpoints/en-zh.ckpt \
  --input_txt <input_txt> \
  --vocos_checkpoint ./vocos/generator.ckpt \
  --output_sample_rate 24000 \
  ...
```

## 5) End-to-End 推理（接入 Dingqiao TN 模块）

本节描述 **带文本归一化（TN）前端的端到端推理**，与上文第 3–4 节的「直接声学推理」不同：

| 路径 | 输入 | TN | 声学模型 |
|------|------|----|----------|
| `infer_en-zh.sh` / `inference_stream.py` | 已写好 phoneme / 拼音，或 `en-zh-dict` 下的纯文本 | **不做** | LITs + Vocos |
| **`infer_e2e.sh` / `infer_e2e.py`（本节）** | **原始文本**（含数字、货币、缩写等） | **Dingqiao TN** | LITs + Vocos |

典型流水线：

```text
原始句子 → Dingqiao TN（{zh,en,ar,bn,ru}_tts）→ manifest → inference_stream.py → wav
```

双语模型会按语种分段后分别调用对应 TN 二进制（例如 en-zh 对中文段走 `zh_tts`、英文段走 `en_tts`）。`en-zh-dict` 在 TN 之后还会由模型前端自动做 G2P（汉字字表 + CMUdict），无需手写 ARPAbet。

### 5.1) 环境

与第 2、4 节相同：

```bash
conda activate lits
export LD_LIBRARY_PATH="$CONDA_PREFIX/lib:$LD_LIBRARY_PATH"
```

### 5.2) 安装 TN 二进制

依赖：`build-essential`、`libicu-dev`（`apt install`）；`en-ru` 的 `ru_tts` 另需 MorphoDiTa（仓库已包含）。

在仓库根目录执行（编译 Dingqiao 子模块并安装到 `e2e_infer/bin/`）：

```bash
export ICU_ROOT="${ICU_ROOT:-$CONDA_PREFIX}"   # Conda 环境；系统 libicu 已装时可省略
bash install_e2e_tn.sh
```

验证：

```bash
echo '给我$10' | ./e2e_infer/bin/zh_tts
echo 'it cost me $10.' | ./e2e_infer/bin/en_tts
```

更新 TN 规则后重新执行 `bash install_e2e_tn.sh`。

### 5.3) 输入格式

支持两种写法（与 `inference_stream.py` manifest 兼容）：

**A. 纯原始文本**（每行一句，自动生成 utterance id）：

```text
给我$10
今天气温 25 摄氏度，北风 5-6 级。
```

**B. 已有 manifest**（只对其中的 `text` 字段做 TN，保留 `wav_path`）：

```text
demo-001.wav|给我$10
demo-002.wav|1|风扇转起来好凉快，11 千克苹果 it cost me $10
```

### 5.4) 运行 E2E 推理

```bash
# en-zh-dict（默认 checkpoint: model_checkpoints/en-zh.ckpt）
./infer_e2e.sh en-zh-dict data_for_test/raw-en-short.txt my_e2e_run

# 其他双语模型
./infer_e2e.sh ar-en /path/to/raw_ar.txt ar_e2e_run
./infer_e2e.sh bn-en /path/to/raw_bn.txt bn_e2e_run
./infer_e2e.sh en-ru /path/to/raw_ru.txt ru_e2e_run
```

自定义 checkpoint：`CHECKPOINT=/path/to/your.ckpt ./infer_e2e.sh en-zh-dict <input_txt>`

Python 直接调用（更多参数）：
python infer_e2e.py \
  --model_lang en-zh-dict \
  --checkpoint ./model_checkpoints/en-zh.ckpt \
  --input_txt data_for_test/raw-en-short.txt \
  --output_dir ./infer_output/e2e_test \
  --output_txt ./infer_output/e2e_test/meta.txt \
  --keep_manifest \
  --output_sample_rate 24000 \
  --num_decoding_left_chunks -1
```

输出目录结构：

```text
infer_output/<infer_id>/
  tn_manifest.txt    # TN 后的 manifest（wav|text）
  normalized.txt     # 仅归一化文本（--keep_manifest 时）
  meta.txt           # 合成结果列表
  *.wav              # 音频
```

### 5.5) 常用参数

| 参数 | 说明 |
|------|------|
| `--skip_tn` | 输入已是 TN 后的 manifest，跳过 TN 步骤 |
| `--tn_bin_dir` | TN 二进制目录（默认 `e2e_infer/bin`；`infer_e2e.py` 单独调用时可改） |
| `--ru_morph_model` | `ru_tts` 的 MorphoDiTa 模型路径 |
| `--limit N` | 只处理前 N 行（冒烟测试） |
| `--keep_manifest` | 保留 `tn_manifest.txt` / `normalized.txt` |
| 其余 `--length_scale`、`--n_timesteps` 等 | 原样转发给 `inference_stream.py` |

### 5.6) 与直接推理的区别

`infer_en-zh.sh` 不会处理 `$10` 这类未展开文本；`infer_e2e.sh en-zh-dict` 接受原始句子，先 TN 再 G2P 合成。已有 TN 结果时加 `--skip_tn`。