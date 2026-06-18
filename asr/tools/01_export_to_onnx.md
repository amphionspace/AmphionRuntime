# 阶段 A.1：把 streaming Zipformer Transducer 导出成 ONNX 三件套

## 背景假设

- 你用 icefall 训练的，模型在 `egs/<dataset>/ASR/zipformer/exp/` 下，最后一份 average 权重已生成，例如 `pretrained.pt`。
- 训练时 streaming 参数是 `--causal 1 --chunk-size 16 --left-context-frames 128`（即 chunk-16-left-128，与 sherpa-onnx 主流模型一致）。如果不是这套参数，下面的命令需要相应调整。
- BPE/SentencePiece 词表在 `data/lang_bpe_<vocab>/bpe.model`（icefall 默认布局）。
- 这一份导出脚本会同时生成 `tokens.txt`，无需自己再写。

## 一、准备 icefall 环境

如果你还没装 icefall，按你训练时的 commit 装：

```bash
# 你已经训练过模型，理论上已经装好；这里给一个干净环境的步骤
conda create -n icefall_export python=3.10 -y
conda activate icefall_export

pip install torch==2.1.2 torchaudio==2.1.2 --index-url https://download.pytorch.org/whl/cpu
pip install k2==1.24.4.dev20240223+cpu.torch2.1.2 -f https://k2-fsa.github.io/k2/cpu.html
pip install -r https://raw.githubusercontent.com/k2-fsa/icefall/master/requirements.txt
pip install onnx==1.17.0 onnxruntime==1.18.1 onnxoptimizer==0.3.13

# clone icefall（用你训练时一样的 commit）
git clone https://github.com/k2-fsa/icefall
cd icefall
git checkout <your-training-commit>
export PYTHONPATH=$PWD:$PYTHONPATH
```

注：`k2`、`torch`、`onnx` 的版本如果与你训练环境一致，直接跳过这一步。`onnx` 必须 ≥ 1.17，避免后续量化时遇到 opset 兼容问题；`onnxruntime` 用 1.18.x 做导出和量化（运行时端上是 1.24.3，二者无 ABI 冲突）。

## 二、用 icefall 自带 export-onnx-streaming.py

icefall 流式 zipformer recipe 自带一个 `export-onnx-streaming.py` 脚本，路径是 `icefall/egs/<dataset>/ASR/zipformer/export-onnx-streaming.py`。

以 `librispeech` 为例（中英混合的话路径里改成你实际的 dataset 名，例如 `wenetspeech` / `multi_zh_en`）：

```bash
cd icefall/egs/librispeech/ASR

# 1) 准备一份 average 权重；icefall 训练完之后通常这步已做过
./zipformer/export.py \
  --exp-dir zipformer/exp \
  --tokens data/lang_bpe_500/tokens.txt \
  --epoch 30 --avg 9 \
  --jit 0

# 2) 实际导出 ONNX 三件套
./zipformer/export-onnx-streaming.py \
  --exp-dir zipformer/exp \
  --tokens data/lang_bpe_500/tokens.txt \
  --epoch 30 --avg 9 \
  --use-averaged-model 1 \
  --num-encoder-layers "2,2,3,4,3,2" \
  --downsampling-factor "1,2,4,8,4,2" \
  --feedforward-dim "512,768,1024,1536,1024,768" \
  --num-heads "4,4,4,8,4,4" \
  --encoder-dim "192,256,384,512,384,256" \
  --query-head-dim 32 \
  --value-head-dim 12 \
  --pos-head-dim 4 \
  --pos-dim 48 \
  --encoder-unmasked-dim "192,192,256,256,256,192" \
  --cnn-module-kernel "31,31,15,15,15,31" \
  --decoder-dim 512 --joiner-dim 512 \
  --causal 1 --chunk-size 16 --left-context-frames 128
```

关键参数说明（必须与训练时一致，否则 ONNX 是错的）：

| 参数 | 含义 |
| --- | --- |
| `--num-encoder-layers` 等 6 个 | 你训练时 `train.py` 里的网络结构参数。如果不记得了，到 exp 目录的 `tensorboard` 或最早一份 `train.log` 里找 |
| `--causal 1` | 必须为 1，否则导出的是非因果模型，端上跑不了流式 |
| `--chunk-size 16 --left-context-frames 128` | 与训练时一致；这两个参数会被 fuse 进 ONNX，运行时不能改 |

如果你的 recipe 是 wenetspeech / multi_zh_en，命令同形，路径里替换 `librispeech` 即可。

## 三、产物核对

执行成功后，`zipformer/exp/` 下会多出这些文件：

```
encoder-epoch-30-avg-9-chunk-16-left-128.onnx
decoder-epoch-30-avg-9-chunk-16-left-128.onnx
joiner-epoch-30-avg-9-chunk-16-left-128.onnx
tokens.txt          # 与你 --tokens 输入的内容一致
```

按 `MODEL_LAYOUT.md` 的固定命名要求，重命名为：

```bash
cd zipformer/exp

# 先把原文件保留一份方便回滚
mv encoder-epoch-30-avg-9-chunk-16-left-128.onnx encoder.onnx
mv decoder-epoch-30-avg-9-chunk-16-left-128.onnx decoder.onnx
mv joiner-epoch-30-avg-9-chunk-16-left-128.onnx  joiner.onnx
```

`tokens.txt` 是直接复制过来的，不需要改。

## 四、健壮性自检

```bash
python3 - <<'PY'
import onnx
for name in ["encoder.onnx", "decoder.onnx", "joiner.onnx"]:
    m = onnx.load(name)
    onnx.checker.check_model(m)
    print(name, "ok, opset", m.opset_import[0].version,
          "ir_version", m.ir_version,
          "inputs", [(i.name, [d.dim_value for d in i.type.tensor_type.shape.dim]) for i in m.graph.input],
          "outputs", [o.name for o in m.graph.output])
PY
```

预期：

- opset 版本 ≥ 14
- encoder 的 input 大致是：`x [N, T, 80]`、`x_lens [N]` 以及若干 cached_states（`cached_len_*` / `cached_avg_*` / `cached_key_*` / `cached_val_*` / `cached_val2_*` / `cached_conv1_*` / `cached_conv2_*`）
- decoder 的 input 是 `y [N, context_size]`，输出是 decoder embedding
- joiner 的 input 是 encoder output + decoder output，输出 logit

如果 cached_states 的形状里有 dynamic dim（`-1` 或没有 dim_value），不要紧；运行时会按 chunk 维度填进去。

## 五、产物大小预期

参考 streaming zipformer-bilingual-zh-en（你的模型规模也大致如此）：

| 文件 | 大小（FP32） | 大小（INT8） |
| --- | --- | --- |
| encoder.onnx | 130 ~ 160 MB | 35 ~ 50 MB |
| decoder.onnx | 1 ~ 3 MB | 不量化 |
| joiner.onnx | 8 ~ 16 MB | 3 ~ 6 MB |

如果偏差超过 30%，先确认导出参数是否正确、再继续往下走。

## 六、常见坑

1. 导出时报 `KeyError: 'encoder_embed.0.bias'`：训练时网络结构参数和导出命令里的 `--num-encoder-layers` 不一致。回 `train.log` 找正确值。
2. 导出脚本卡在第一次 `torch.onnx.export`：内存不够；torch 导出会做一次完整 trace，至少需要 16 GB RAM。
3. 导出后 `onnx.checker.check_model` 报 `Op: ScaledDotProductAttention`：torch 2.1+ 默认的 SDPA 算子在 onnx<1.17 时不被识别；升级 onnx 到 1.17+。
4. `tokens.txt` 第一行不是 `<blk> 0`：极少出现；如果你的 recipe 有自定义 special tokens，请手动把 `<blk>` 调到 id=0。
