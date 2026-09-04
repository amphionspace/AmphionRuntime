# 说话人窗口定稿

Harmony 与 Android 的鼎桥适配层按窗口发布 `onSpeakerDiarizationResult`。iOS 不在本次范围。
本变更直接替换旧的结束时返回整场全文的语义，调用方必须按批累积结果。

## 窗口与定稿

- 默认目标为 120 秒音频时间；到目标后等待第一个已有 ASR final 边界，不新增 ASR endpoint。
- 推理仍使用 10 秒窗口、2.5 秒 hop、1.5 秒右上下文。定稿等待覆盖该句末的固定推理窗口：
  `ceil((endpointMs + 1500) / 2500) * 2500`。ASR 或推理先完成不改变证据范围。
- 120 秒是控制身份修订等待和待处理数据量的工程默认值，尚不代表在所有语料上测得的最优精度。
  无句末、ASR 或推理积压时可能超过该值；不得丢帧或强制结束识别来维持时间上限。
- 只聚类本批的证据；保留整场已确认身份及其中心向量。不同已确认身份禁止合并，历史编号不重排。
- 每批结果中的主说话人、次说话人和未知 `-1` 均冻结。已发布的原始句子及证据从可修订状态移除。
  `finish` 只处理未定稿尾窗，不再重聚类历史全文。
- PCM 按 10 秒文件分块；推理完成后回收不再被排队任务或下一个推理窗引用的整块。
  输入快于推理时保留未消费音频，不能为了限量覆盖或丢弃任务。

## 回调关系

`onResult(isFinal=true)` 先发布原句和临时身份，`onSpeakerDiarizationUpdate` 可修订尚未定稿的句子。
`onSpeakerDiarizationResult` 发布批次后，同一原句不得再次被 update 或另一个批次改写。

`windowIndex` 从 0 连续递增；`windowBeginTime/windowEndTime` 使用会话音频时间。
`sourceUtteranceId` 指向原始 ASR 句子，可将原句替换为该批的安全分句。
ITN 导致字符与 token 不对应时保留完整原句，不猜测切分文本。

中间批次 `isSessionFinal=false`，不影响识别生命周期。正常结束保持唯一
`onResult(isLast=true)` → 尾批 `isSessionFinal=true` → 唯一 `onComplete`。
即使尾批为空也发出终结批次。降级批次保留文字并冻结未知身份；cancel 不新增结果或 complete。

## 验证范围

针对性用例检查冻结后不修订、未知定稿、单调原句编号、延迟回调、ASR/推理先后顺序、
A→B→A 跨窗身份、不同已确认身份不合并、并发 update 与定稿顺序、降级空尾批、PCM 分块回收。
五小时模拟音频时钟用于验证状态保留量；它不能替代真实模型和设备长时验收。

Harmony 真机使用 `run_device_stress.py --mode diarization-windows --pace-ms 20`，至少跨过一个
定稿边界，检查 batch 编号、重复原句、定稿后 update、唯一 terminal/last/complete、降级状态及资源变化。
`speakerWindowsHex` 保留逐批结果，其他报告继续保存回调、输入映射、内存采样和 hilog。
长时验证使用五小时真实 PCM、按实际速度喂入；该语料用于生命周期与资源测试，不作为分离精度评测集。
