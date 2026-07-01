# AISHELL-3 热词 ASR 评测

本文沉淀 2026-06-30 使用 `aishell3_test_hotwords_500` 对 ASR 热词功能做的离线 A/B 实验。实验脚本为 `asr/tools/hotwords/01_eval_aishell3_hotwords.py`，机器可读结果在 `asr/tools/hotwords/results/aishell3_hotwords_eval/summary.json`，Markdown 结果在 `asr/tools/hotwords/results/aishell3_hotwords_eval/summary.md`，逐条结果在 `asr/tools/hotwords/results/aishell3_hotwords_eval/eval.jsonl`。

## 1. 要解决的问题

ASR 基础模型容易把低频人名、地名、店名、艺名、书名等专名识别成更常见的同音词。对业务来说，这类错误通常比普通虚词错误更严重：一句话整体听起来通顺，但关键实体错了，后续检索、派单、搜索、LLM 工具调用都会被带偏。

热词功能解决的是这个具体问题：业务在启动或会话更新时传入候选热词，解码器在搜索路径中提高这些词的分数，让同音或近音候选更容易保留下来并最终输出。

本实验同时观察一个副作用：热词需要使用 `modified_beam_search` 和热词图，可能增加 CPU 开销，也可能在没有负样本覆盖时带来误插入风险。因此最终结论必须同时看热词命中收益、整句 CER 和 RTF。

## 2. 数据与实验构造

测试集：`aishell3_test_hotwords_500`，本地路径通过环境变量 `AISHELL3_HOTWORDS_DIR` 指定。

| 项 | 值 |
| --- | --- |
| 样本数 | 500 |
| 说话人数 | 99 |
| 热词总数 | 619 |
| 每条样本热词数 p50 / p90 / max | 1 / 2 / 4 |
| 总时长 | 1737.970 秒 |
| 单条时长 p50 / p90 | 3.222 / 5.453 秒 |
| 音频格式 | 44.1 kHz wav，评测时重采样到 16 kHz |
| 标注来源 | supervisions_punc_hotwords.jsonl.gz 的 custom.hotwords |

实验系统：

| 系统 | 解码方式 | 热词 | 用途 |
| --- | --- | --- | --- |
| baseline_greedy | greedy_search | 无 | 模拟未开启热词功能的默认识别 |
| mbs_no_hotwords | modified_beam_search | 无 | 观察更宽搜索本身带来的影响 |
| hotwords_score_3 | modified_beam_search | 每条样本自己的 hotwords，score=3.0 | 模拟 Android public-demo / 警务增强当前推荐热词分数 |

模型配置：

| 配置项 | 值 |
| --- | --- |
| ASR 模型 | asr/tools/demo-model/zipformer_L_zh_en |
| 上游模型 | sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20 |
| bpe vocab | asr/tools/demo-model/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20/bpe.vocab |
| modeling unit | cjkchar+bpe |
| max active paths | greedy=4，modified_beam_search=8 |
| hotwords score | 3.0 |

## 3. 指标说明

| 指标 | 名词说明 | 解决或暴露的问题 | 计算口径 | 数值解读 |
| --- | --- | --- | --- | --- |
| 热词精确命中率 | 标注热词是否作为连续字符串出现在识别结果中 | 人名、地名、专名被识别成常见同音词 | 命中的热词数 / 标注热词总数 | 越高越好，是热词功能核心收益 |
| 样本全热词命中率 | 一条音频里的全部热词是否都命中 | 一句话含多个热词时，只命中部分仍会影响业务 | 全部热词命中的样本数 / 样本数 | 越高越好 |
| 热词片段最小 CER | 热词和识别文本中最相近片段的字符错误率 | 热词未完全命中时，判断是否更接近正确写法 | 每个热词与 hypothesis 所有近长子串取最小编辑距离后汇总 | 越低越好 |
| 整体 CER | 整句字符错误率 | 观察热词偏置是否损伤非热词上下文 | sum(edit_distance(reference, hypothesis)) / sum(reference_chars) | 越低越好 |
| RTF | 实时率，处理 1 秒音频需要多少秒 | 观察 modified_beam_search 和热词图带来的性能代价 | 解码耗时 / 音频时长 | 越低越好，小于 1 表示快于实时 |

## 4. 最终收益数据表格

工作点采用 `hotwords_score=3.0`：

| 场景问题 | 指标 | 无热词 baseline | 开启热词 | 收益或代价 | 结论 |
| --- | --- | --- | --- | --- | --- |
| 人名、地名、专名被识别成常见同音词 | 热词精确命中率 | 76.41% | 96.12% | 提升 19.71 个百分点 | 核心收益成立 |
| 一句话中多个热词需要全部保留 | 样本全热词命中率 | 73.80% | 95.40% | 提升 21.60 个百分点 | 多热词样本收益明显 |
| 热词即使没完全命中，也希望更接近正确写法 | 热词片段最小 CER | 9.77% | 1.52% | 下降 8.25 个百分点 | 热词局部错误显著减少 |
| 开启热词是否破坏整句识别 | 整体 CER | 6.04% | 2.29% | 下降 3.74 个百分点 | 本正样本集上没有观察到整句劣化 |
| 热词解码需要更宽搜索路径 | 总 RTF | 0.029 | 0.042 | 增加 0.013 | CPU 开销增加但仍明显快于实时 |

系统对比如下：

| 系统 | 整体 CER | 热词精确命中率 | 样本全热词命中率 | 热词片段最小 CER | 总 RTF |
| --- | --- | --- | --- | --- | --- |
| baseline_greedy | 6.04% | 76.41% | 73.80% | 9.77% | 0.029 |
| mbs_no_hotwords | 5.82% | 77.06% | 74.60% | 9.38% | 0.041 |
| hotwords_score_3 | 2.29% | 96.12% | 95.40% | 1.52% | 0.042 |

对比说明：

- `mbs_no_hotwords` 相比 `baseline_greedy` 只带来很小收益：热词精确命中率提升 0.65 个百分点，整体 CER 下降 0.22 个百分点。
- `hotwords_score_3` 相比 `mbs_no_hotwords` 的额外收益显著：热词精确命中率再提升 19.06 个百分点，整体 CER 再下降 3.53 个百分点。
- 因此，本测试集上的主要收益来自热词偏置本身，不只是 beam search 变宽。

## 5. 结论与推荐

`hotwords_score=3.0` 在本测试集上是有效工作点：热词精确命中率从 76.41% 提升到 96.12%，样本全热词命中率从 73.80% 提升到 95.40%，同时整体 CER 从 6.04% 降到 2.29%。

这支持当前热词功能用于以下场景：

- 人名、地名、机构名、店名、艺名、书名等低频专名识别。
- 用户或业务系统能预先给出候选词清单。
- 下游强依赖实体字符串正确性，例如检索、问答、工单、指令执行或 LLM 工具调用。

需要注意：本实验只覆盖热词正样本，不包含“热词没有出现但被错误插入”的负样本。因此上线或交付前仍要补一组负样本评估，指标至少包括热词误插入率、非热词样本 CER 变化和高 score 下的幻听风险。

## 6. 复现实验

先准备官方中英 demo 模型：

```bash
bash asr/tools/00_fetch_demo_model.sh
```

运行评测：

```bash
export AISHELL3_HOTWORDS_DIR=<aishell3_test_hotwords_500目录>
python3 asr/tools/hotwords/01_eval_aishell3_hotwords.py \
  --dataset-dir "$AISHELL3_HOTWORDS_DIR" \
  --model-dir asr/tools/demo-model/zipformer_L_zh_en \
  --bpe-vocab asr/tools/demo-model/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20/bpe.vocab \
  --hotwords-scores 3.0 \
  --include-mbs-empty \
  --out-dir asr/tools/hotwords/results/aishell3_hotwords_eval
```

输出：

- `asr/tools/hotwords/results/aishell3_hotwords_eval/eval.jsonl`
- `asr/tools/hotwords/results/aishell3_hotwords_eval/summary.json`
- `asr/tools/hotwords/results/aishell3_hotwords_eval/summary.md`

## 7. 已知限制

- 本实验只覆盖热词正样本，不评估热词误插入率。
- 模型使用官方中英 demo zipformer，与具体客户交付模型可能有差异，正式交付需用目标模型复标。
- 开启热词组按 Android 当前行为同时切换到 `modified_beam_search`，本报告用 `mbs_no_hotwords` 单独观察 beam search 本身的影响。
- 评测在 macOS 主机 CPU 上运行，不代表 Android 真机 RTF。
