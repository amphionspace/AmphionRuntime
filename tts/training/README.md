# TTS 训练与模型导出

本目录保存 TTS 训练、离线推理和模型导出源码。平台 SDK、交付脚本和公共接口文档仍分别归入
`tts/android/`、`tts/harmony/`、`tts/tools/` 和 `tts/docs/`。

## Dingqiao LITS

[`dingqiao_lits/`](dingqiao_lits/) 是当前中英 TTS 训练与导出工程，其中 TN 源码通过私有
submodule 固定版本：

```bash
git submodule update --init \
  tts/training/dingqiao_lits/Dingqiao_Multilingual_Text_Normalization_for_TTS
```

训练数据、checkpoint、导出模型和本地构建产物不直接提交到 Git；跨机协作资产按
[`tools/assets/README.md`](../../tools/assets/README.md) 的清单和校验流程管理。
