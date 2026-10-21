# 问题 #36：仅 UNKNOWN 副角色作废整句归属

2026-10-21。客户反馈「离线角色分离，角色1 和角色2 的话过一会全部显示为其他角色说的话」。`其他角色` 对应 SDK 的 `speakerIndex = -1`（见 `语音识别SDK接口.md`）。

**结论**：声学归属本身正确；展示句归属层把「仅 UNKNOWN 副角色」当成换人证据，作废了整句。两段掉档中的一段由本次修复闭合，另一段因含已知副角色不在本轮范围（见「未覆盖」）。

## 复现

| 项 | 值 |
| --- | --- |
| 输入 | `36问题语音.wav`，63.3 s，16 kHz 单声道（客户提供，不入库） |
| 代码 | `b56b240d`（= `main`） |
| 载体 | demo 0.3.24 diagnostics，设备 `7GK0226326015655` |
| 证据 | `.local/perf/issue36/20261021-010705-diarization-windows-99cdf37b` |

```bash
python3 delivery/harmony-dingqiao/delivery/run_device_stress.py \
  --installed-package --mode diarization-windows --enable-diarization \
  --data-dir <含该 wav 的目录> --files 0 --cycles 1 \
  --capture-diagnostics --sample-interval 1.0 --post-run-observe 20 \
  --timeout 1800 --output-root .local/perf/issue36
```

实际症状不是「过一会全部变成其他角色」，而是**连续发言中间的间歇掉档，掉档后恢复为同一人**，两个说话人都出现：

| 时间 | speaker | secondary |
| --- | --- | --- |
| 2.0–15.7 s | 0 | [] |
| **15.7–21.8 s** | **−1** | [0, 1, −1] |
| 21.8–23.7 s | 0 | [] |
| 25.2–35.3 s | 1 | [] |
| **35.3–38.8 s** | **−1** | [1, −1] |
| 38.8–41.4 s | 1 | [] |
| 43.0–60.5 s | 1 | [] |

两段 UNKNOWN 文本长 6120 ms 与 3480 ms，均超过 `MAX_UNKNOWN_BACKFILL_MS = 2500`，所以邻接补全也救不回来，`speakerInferred` 保持 `false`。

## 根因

声学时间线正确：两段掉档内每个 turn 的主角色都是对的人，重叠只占少数时长。

| 掉档 | 干净时长 | 重叠时长 | 干净占比 | 副角色来源 |
| --- | --- | --- | --- | --- |
| 1（15.7–21.8 s） | 5.23 s | 0.69 s | 88% | 含**已知** speaker 1 |
| 2（35.3–38.8 s） | 2.82 s | 0.66 s | 81% | **仅 −1（UNKNOWN）** |

`sentenceUtterances` 的展示句门禁用了一个无条件的 `overlap`：

```ts
const overlap = turns.some(turn => turn.overlap || turn.secondarySpeakerIds.length > 0);
const single = known.length === 1 && !overlap && bounded && ...
```

而同文件已有的 `blocksBackfill` 才是契约要求的规则 —— 已知副角色阻断、无来源 overlap 阻断、**仅 UNKNOWN 副角色允许**。两层规则自相矛盾，Android `DiarizationTranscriptState.kt` 逐行相同。

契约依据：

- `docs/engineering/ASR_CONTRACTS.md:10`「UNKNOWN、短暂声学覆盖空隙及副角色/重叠标签变化，**本身不构成主说话人换人的证据**」
- 同文件 `:13`「**仅 UNKNOWN 副角色可保留重叠标记后做推断**」
- `UNKNOWN_SPEAKER_BACKFILL.md`「仅 UNKNOWN / UNKNOWN_SECONDARY 副角色不证明主讲人换人，可保留原始重叠标记后推断」

故掉档 2 是**既有契约违反**；掉档 1 含已知副角色，按契约阻断是正确的。

## 修复

两端各改门禁一处，复用既有助手，不引入新语义：

| 文件 | 改动 |
| --- | --- |
| `SpeakerDiarizationTranscriptState.ts:523` | `!overlap` → `!turns.some(turn => this.blocksBackfill(turn))` |
| `DiarizationTranscriptState.kt:217` | 同上（`covered.any { blocksBackfill(...) }`） |

顺带修掉一个「吞掉未知信息」的问题（`ASR_CONTRACTS.md:12` 禁止）：原来 `single` 为真时 `secondarySpeakerIds` 被置空。现在新增 `observedSecondaries`（只统计副角色来源，与主角色分开），保留观察到的 UNKNOWN 标记；`overlap` 字段照旧发布。分开统计是必需的 —— 否则 bounded 补全路径（主角色为 UNKNOWN 被补全）会被误加副角色。

**走错过一次**：最初改在 `assignmentFor`，被 `test_whole_sentence_preserves_short_changes_overlap_and_unknown` 中 `assert.equal(fixed.speakerInferred,true)` 拦下 —— 该断言表明 UNKNOWN 的找回必须走补全层并打 `speakerInferred=true`，改在 `assignmentFor` 等于以「直接归属」宣告，违反契约第 13 行。已回退重做。

## 验证

同机、同音频、同参数重跑，证据 `.local/perf/issue36-fixed/20261021-014417-diarization-windows-838f7897`：

| 时间 | 修复前 | 修复后 |
| --- | --- | --- |
| 15.7–21.8 s | −1，secondary [0, 1, −1] | −1，secondary [0, 1, −1]（不变） |
| **35.3–38.8 s** | **−1**，secondary [1, −1] | **1**，secondary [−1] |

`-1` 句数 **2 → 1**。三处细节印证修复按设计工作：

1. 掉档 2 恢复为 speaker 1，其副角色恰为契约许可的「仅 UNKNOWN」。
2. secondary 由 `[1, −1]` 变为 `[−1]`：不确定性保留，未被吞掉。原先那个 `1` 是整句判 UNKNOWN 时把主角色一并塞入 participants 的产物。
3. 掉档 1 原样不动，其 `secondary` 含已知 speaker 1，阻断正确 —— 保护未被削弱。

`speakerInferred` 全程 `false` 正确：这些 token 本就落在该说话人的声学 turn 内，属直接归属而非补全。

单元测试：鸿蒙 551 全过，Android 142 全过。更新了 4 处期望，**同属一类 case**（主角色一致 + 副角色仅 UNKNOWN）：

| 测试 | 变化 |
| --- | --- |
| `test_whole_sentence_preserves_short_changes_overlap_and_unknown` | 该 case 拆为独立断言 |
| `test_itn_record_cannot_hide_a_short_speaker_change_overlap_or_unknown` | 同上 |
| `test_punctuation_replacing_english_space_preserves_speaker_boundaries` | 期望改为 S1，并**新增已知副角色仍为 UNKNOWN 的对照** |
| `DiarizationSentenceOutputTest.mixedAndOverlappingSentenceHasNoSingleOwner` | 拆出 `unidentifiedSecondaryKeepsTheUnanimousPrimary` |

真实已知换人（含 20 / 25 ms 短插话）、已知副角色重叠、主角色 UNKNOWN 这些 case 全部仍判 UNKNOWN，`overlap` 标记在所有情况下照旧发布。

## 未覆盖

- **掉档 1 仍为 UNKNOWN**。其 6.12 s 内有 0.65 s 被判为已知 speaker 1 的重叠，按契约必须阻断。要闭合它需要在投影层容忍「主角色一致 + 已知副角色占比很低」，属行为语义变更，本轮未做。
- **该 0.65 s 重叠疑为声学误检**。主持人独白中段出现角色二的概率很低；分割模型在 20.5–21.5 s 虚报了第二声道（`DIARIZATION_COMMUNITY_SAMPLES` 显示 channel 2 在 w8–w12 有 23–52 个干净帧，低于 118 阈值但非零）。未定位虚报原因，这与上一条是两条独立路线，后者更根本。
- **未做人工精度验收**。本轮只有单段客户音频的逐句归属对照，不是标注真值或 DER；不能据此宣称身份精度已修复。
- **Android 仅通过单元测试**，未装机验证。
- 工单文本另有两处与角色分离无关的差异：`40min`（预期 `四十分钟`，ITN）与 `积极配合`（预期 `谢谢配合`，识别错误）。
