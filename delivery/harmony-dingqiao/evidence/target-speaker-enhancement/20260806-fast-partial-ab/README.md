# Harmony 目标说话人增强首字延迟 A/B（2026-08-06）

## 结论

在 Mate 80（VYG-AL30，HarmonyOS 6.1.0.135）上，使用同一正式 ZH_EN HAP、同一代码
`115afa33205cf2865b66bc7d18fbbae9761f3a89`，按 20 ms 实时喂入相同 C1/C2/C3：

| 用例 | 普通 ASR 首个非空 partial | 增强默认快速 partial | 增量 |
|---|---:|---:|---:|
| C1 | 2136 ms | 2375 ms | +239 ms |
| C2 | 2010 ms | 2139 ms | +129 ms |
| C3 | 2079 ms | 2164 ms | +85 ms |
| 中位数 | 2079 ms | 2164 ms | **+85 ms** |
| 平均值 | 2075 ms | 2226 ms | **+151 ms** |

“首字”严格定义为从第一帧 `writeAudio` 前记录时间，到首个非空 `isFinal=false` 回调；没有把 final
混入该指标。普通与增强两轮 `corpus.json` 中 C1/C2/C3 的源 WAV SHA-256 和转换后 PCM SHA-256
逐条相同。增强轮 35 个 partial 全部为 `targetSpeakerEnhancementApplied=false`，增强 ASR 没有公开
partial；全部 final 均为 `targetSpeakerEnhancementApplied=true`。

因此，默认快速通道已经消除原来“必须等待 2 秒分块再开始 ASR”的额外等待。当前真机可归因的
首字损耗是中位数 85 ms、平均 151 ms；首个增强 session 的最大增量 239 ms，后两条为 85～129 ms。
样本只有三条，适合作为本批固定客户语料的交付结论，不外推为所有设备和语料的统计上限。

## 内容与生命周期

- 普通基线、增强 C1/C2/C3 均为 PASS；增强 final 的内容门禁 3/3 PASS（含“上海”、不含“你好”）。
- 每个正常增强 session 在显式 `finish` 前 `isLast` 为 0，结束后恰好一次 last、一次 complete、0 error。
- 增强 session 的 `onStart` 观察到 2 个 stream；显式 `enablePartialResult=false` 的 onStart/cancel
  路径只观察到 1 个 stream；结束后均为 0。
- 专用 reentrant 用例在首个 preview partial 内同步 `writeAudio` 一帧并 `finish`，输入采样数一致，
  恰好一次 last/complete、0 error。`onStart` 内 continue/finish/cancel 3/3 PASS，推理中 cancel 后
  立即恢复 1/1 PASS。

## 证据目录

- `baseline/`：普通 ASR C1/C2/C3，20 ms paced。
- `enhanced/`：目标说话人增强 C1/C2/C3，20 ms paced。
- `reentrant/`：preview partial 回调内同步 write + finish。
- `onstart/`：`onStart` 内 continue / finish / cancel。
- `cancel/`：推理中 cancel 后立即启动恢复 session。

每个目录保留 `report.json`、`result.txt`、`memory.csv`、`hilog.txt`、`inventory.json` 和
`corpus.json`。`corpus.json` 只保存输入映射和哈希；PCM 使用已入库固定语料，不在证据目录重复保存。
