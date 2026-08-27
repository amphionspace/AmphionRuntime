# ASR 热词评测工具

本目录用于维护 ASR 热词词典转换与热词收益评测脚本。

## 工具清单

| 路径 | 职责 |
| --- | --- |
| build_hotwords.py | 把业务 CSV 热词词典转换成 sherpa-onnx hotwords.txt |
| sample.csv | build_hotwords.py 的输入示例 |
| 01_eval_aishell3_hotwords.py | 在 AISHELL-3 热词测试集上跑无热词 vs 开启热词 A/B |

## AISHELL-3 热词收益评测

测试集默认从 OBS 下载到
`~/.cache/amphion-runtime/test-data/v1/aishell3_test_hotwords_500/`：

```bash
python3 asr/tools/test_data.py fetch aishell3-hotwords-500
```

先准备官方中英 demo 模型：

```bash
bash asr/tools/00_fetch_demo_model.sh
```

运行评测：

```bash
python3 asr/tools/hotwords/01_eval_aishell3_hotwords.py \
  --dataset-dir ~/.cache/amphion-runtime/test-data/v1/aishell3_test_hotwords_500 \
  --model-dir asr/tools/demo-model/zipformer_L_zh_en \
  --bpe-vocab asr/tools/demo-model/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20/bpe.vocab \
  --hotwords-scores 3.0 \
  --include-mbs-empty \
  --out-dir asr/tools/hotwords/results/aishell3_hotwords_eval
```

默认工作点 `hotwords_score=3.0` 的最终收益数据表格：

| 场景问题 | 指标 | 无热词 baseline | 开启热词 | 收益或代价 | 结论 |
| --- | --- | --- | --- | --- | --- |
| 人名、地名、专名被识别成常见同音词 | 热词精确命中率 | 76.41% | 96.12% | 提升 19.71 个百分点 | 核心收益成立 |
| 一句话中多个热词需要全部保留 | 样本全热词命中率 | 73.80% | 95.40% | 提升 21.60 个百分点 | 多热词样本收益明显 |
| 热词即使没完全命中，也希望更接近正确写法 | 热词片段最小 CER | 9.77% | 1.52% | 下降 8.25 个百分点 | 热词局部错误显著减少 |
| 开启热词是否破坏整句识别 | 整体 CER | 6.04% | 2.29% | 下降 3.74 个百分点 | 本正样本集上没有观察到整句劣化 |
| 热词解码需要更宽搜索路径 | 总 RTF | 0.029 | 0.042 | 增加 0.013 | CPU 开销增加但仍明显快于实时 |

完整指标定义、场景说明、系统对比和限制见 `docs/asr/AISHELL3_HOTWORDS_EVAL.md`。
