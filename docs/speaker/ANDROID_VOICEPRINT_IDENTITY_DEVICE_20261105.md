# 安卓真机：声纹身份接线后的客户 4 条录音对比（2026-11-05）

分支 `feat/android-voiceprint-identity`（接线提交 `42aadc37`），一加 PHK110（Android 16），debug 构建以 release 证书签名。
与鸿蒙 0.3.27 同一套算法与常量（CAM++ 嵌入、并入阈值 0.50、最小段 0.5 s、嵌入取前 3 s）。

## 结论

| 录音 | 参考人数 | 声纹身份 DER | 混淆 | 同一次运行·模型槽位 DER | 混淆 | 独立 model 臂 DER |
|---|---:|---:|---:|---:|---:|---:|
| 100350-257（6.2 min） | 2 | **1.77%** | 0.0% | 3.01% | 1.2% | 3.01% |
| 102010-230（3.3 min） | 1 | 13.50% | 0.0% | 13.50% | 0.0% | 13.50% |
| **111223-816（2.7 min，工单录音）** | 2 | **5.66%** | **0.9%** | 25.91% | **23.5%** | 26.29% |
| recording-a / 会议-离线-无角色4（2.8 min） | 3 | **2.58%** | 0.0% | 6.44% | 4.6% | 6.44% |
| **时长加权合计** | | **5.63%** | | **12.02%** | | **12.11%** |

- 独立 model 臂合计 12.11%，与 0.3.26 两端真机记录的 12.10% 一致——评分链路、设备与模型都对得上。
- 声纹身份把 4 条的混淆压到 0.0 / 0.0 / 0.9 / 0.0%，整体 DER 12.0% → 5.6%；工单录音 `111223-816` 的
  23.5% 混淆是客户"三个角色依次讲话、角色归属错乱"的直接量化，接线后为 0.9%。
- 102010-230 两臂完全相同：错误全是漏检（参考只有 1 人、UEM 受限），与身份无关；鸿蒙同条 13.50%。
- RTF：声纹臂 0.087~0.099，model 臂 0.100~0.110（不同轮次、同机，差异在噪声内；嵌入计算未抬高 RTF）。

## 两个必须一并说明的现象

1. **声纹臂的漏检略高**（111223-816：3.9% 对 2.3%）。短于 0.5 s 的段按设计不赋身份，报 `speakerIndex=-1`
   （四条分别 31 / 12 / 18 / 13 段，全部短于 0.5 s），评分时按无角色计入漏检，而 model 臂把它们按槽位报出。
   这是精度换稳定的既定取舍（鸿蒙同一规则），不是回归。
2. **`speakerIndex` 与 `modelSpeakerIndex` 在 model 模式下也不完全相同**（4 条分别 30 / 2 / 12 / 6 段，
   累计 0.7~10.9 s）。差异**只出现在重叠区间**：模型侧主身份取该区间内排序首个槽位，而公开主身份套用
   "优先延续上一段"的规则，被换下的槽位进了 `secondarySpeakerIndexes`。鸿蒙 `SpeakerTimeline.ts` 同一定义。
   文档里"model 模式下两者相同"应读作"非重叠区间相同"，接口文档已据此改写。

## 方法

- 载体：`DiarizationDerInstrumentedTest`，`-e derAsset <wav> -e derIdentityMode voiceprint|model -e derFrameSleepMs 20`
  （实时速率，`recognizerMode=long`，`maxSpeakers=4`），录音经 `-PdingqiaoEvalAudioDir` 外挂进测试包。
  每条录音在设备侧落 `files/diarization-der/<wav>.json`（各窗口的 `speakerTurns`，每段带 `speakerIndex`、
  `modelSpeakerIndex`、`secondarySpeakerIndexes`、`overlap`）。
- 评分：`asr/tools/speaker/23_score_diarization_scenarios.py` 口径（10 ms 栅格、collar 0、计重叠、Hungarian），
  参考为客户 4 条的人工 RTTM + UEM（`customer-inputs-20261030/dq5-diar-eval-20261027/official-scorer`，不入库）。
  假设段 = 主身份 + 每个 secondary 各一段；`speakerIndex=-1` 的段不计入假设。
- "同一次运行·模型槽位"列用的是 voiceprint 运行文件里的 `modelSpeakerIndex`，与声纹列来自同一次推理、同一批音频，
  是严格的 A/B；"独立 model 臂"是 `derIdentityMode=model` 另跑的一轮，用来交叉验证。
- 原始结果 JSON（只含时间与编号，无文本、无路径）：`docs/speaker/evidence/android-identity-20261105/`。

## 运行器坑

成功一轮后**紧接着**起下一轮 `am instrument`，instrumentation 会立刻结束且无结果（首轮之后连续 7 条全空），
隔几分钟再起就正常；`am force-stop` 不是原因。处置：下一轮前轮询 `pidof` 等上一轮进程完全退出，再多等 8 s。

## 未覆盖

- 只测了客户 4 条（与鸿蒙相同的材料）；AliMeeting 28 场的安卓真机数字未跑。
- release（R8）构建未覆盖；发热对照臂（`DqThermalLongRunTest -e identityMode model`）未跑。
- 嵌入在块提交回调里同步计算，本次 RTF 未见抬高，但 2 小时长跑的内存高水位未测。
