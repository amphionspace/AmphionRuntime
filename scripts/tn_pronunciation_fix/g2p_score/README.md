# 本地 TN + G2P 打分工装(自建,离线,无需设备)

同事没有现成的"文本→拼音"打分工装,这里自建了一套,用于**端到端**验证 TN 修复
(而不只是看归一化文本)。

## 组成
- `g2p.py` —— **设备 G2P 的忠实移植**(Python)。直接复用设备同款词典/资源:
  `tts/tools/trial-export/.../{chinese_lexicon.txt, polyphone_phrases.txt,
  chinese_surname_lexicon.txt, polychar.txt}`,并移植了 `LitsTtsFrontend`
  的 `hanziChunkToPinyin`(最长匹配 + 姓氏多音字 + 逐字回退)与声调变调
  (三声/不/一/儿)。
- 归一化用**当前源码现编的 host `zh_tts`**(运行时读 rules_v2)。
- `score.py` —— 管线:`text → zh_tts(TN) → g2p.py(G2P) → 拼音`,与 golden_pinyin 比对。

## 保真度(已验证)
在 round15 集**纯汉字**条目上,`g2p.py(设备tnText)` 与设备 `actual_pinyin`
**逐 token 100% 一致**;polyphone-surname 类整体 91–93% 通过 —— 说明 G2P 移植忠实。

## 用法
1. 建 host zh_tts(见 dingqiao_lits 子模块 en/zh.cpp + host ICU 78.1)。
2. `python3 score.py <testset.jsonl>`(需能 import g2p;zh_tts 路径在脚本顶部)。

## 已知边界(打分时注意)
- 只对**中文拼音**打分;英文 ARPABET(EY1 等)、复杂符号未建模 → 这类条目已跳过。
- 残留阿拉伯数字/`幺`(phone 里的 1)等未完全建模 → **绝对通过率仅供参考,
  可靠信号是"某个 TN 改动前后的通过率变化(delta)"**。
- polyphone/多音字的对错属于 G2P,不是 TN 该修的。
