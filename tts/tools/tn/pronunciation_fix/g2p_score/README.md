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
1. 建 host zh_tts（见 `tts/training/dingqiao_lits` 子模块 en/zh.cpp + host ICU 78.1）。
2. `python3 score.py <testset.jsonl>`。默认从仓库构建目录读取 `zh_tts`，也可通过
   `ZH_TTS=/path/to/zh_tts` 覆盖。

## 已知边界(打分时注意)
- 只对**中文拼音**打分;英文 ARPABET(EY1 等)、复杂符号未建模 → 这类条目已跳过。
- 残留阿拉伯数字/`幺`(phone 里的 1)等未完全建模 → **绝对通过率仅供参考,
  可靠信号是"某个 TN 改动前后的通过率变化(delta)"**。
- polyphone/多音字的对错属于 G2P,不是 TN 该修的。

## v2: FULL pipeline (Kotlin frontend layer added)
`frontend.py` ports the Kotlin `LitsTnNormalizer` pre-processing (NFKC clean +
`prepareInputForTn`: percent/coord/room/stock/km-h/clock-colon/year/tech-ascii/
VIN/serial protectors + `FrontendRuleSet` from frontend_rules.json). Pipeline is
now: `text -> frontend.py (Kotlin layer) -> zh_tts (native rules_v2) -> g2p.py`.

Validated: G2P port is token-identical to device on pure-hanzi. FULL-pipeline
score vs golden: round15 69%, hardcases-500 46%.

### What the full pipeline revealed
Most number normalization lives in the **Kotlin layer**, not rules_v2. Several
native-rule fixes I made were redundant (Kotlin already does year/km-h/stock/
room/coord) or defeated by Kotlin (slash-date `2008/08/08` is mangled by Kotlin's
path rule; bare `km/h` -> `km斜杠h` by the tech-ascii rule). So the remaining real
TN bugs are largely in the **Kotlin layer (LitsTnNormalizer.kt)**, and this
harness now scores that layer too.

## Rebuilding the host zh_tts (one command)
The harness needs a host (macOS) `zh_tts` native TN binary. It's not committed
(it's a build artifact). Rebuild it self-contained:

```bash
tts/tools/tn/pronunciation_fix/g2p_score/build_host_zh_tts.sh
# -> writes tts/training/dingqiao_lits/build/host-tn/zh_tts (gitignored); auto-downloads ICU 78.1
```

`score_all.py` / `score.py` read `$ZH_TTS`, falling back to that default path, so
after building just run `python3 score_all.py`. With no arguments, `score_all.py`
uses the tracked round15 fixture; additional JSONL fixtures can be passed as positional
arguments. `g2p.py`, `frontend.py`, and `en_score.py` read the synchronized model package
under `tts/tools/trial-export/`; use `$TTS_MODEL_DIR` only when validating another package.
Rebuild only when the C++ engine
(tts_normalizer_engine.cpp / zh.cpp) changes — rules_v2 JSON is loaded at runtime.
Requires the TN submodule checked out (git submodule update --init …).
