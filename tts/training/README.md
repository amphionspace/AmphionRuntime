# TTS 训练与模型导出

本目录保存 TTS 训练、离线推理和模型导出源码。平台 SDK、交付脚本和公共接口文档仍分别归入
`tts/android/`、`tts/harmony/`、`tts/tools/` 和 `tts/docs/`。

## Dingqiao LITS

[`dingqiao_lits/`](dingqiao_lits/) 是当前中英 TTS 训练与导出工程，其中 TN（文本归一化）
源码、规则和测试已直接纳入本仓库：
[`Dingqiao_Multilingual_Text_Normalization_for_TTS/`](dingqiao_lits/Dingqiao_Multilingual_Text_Normalization_for_TTS/)。
普通 `git clone` 即可获取，无需初始化 TN submodule 或申请原私有仓库的权限。

迁入来源与版本见 [TN_SOURCE.md](TN_SOURCE.md)。后续 TN 修改直接在本仓库提交。

训练数据、checkpoint、导出模型和本地构建产物不直接提交到 Git；跨机协作资产按
[`tools/assets/README.md`](../../tools/assets/README.md) 的清单和校验流程管理。
