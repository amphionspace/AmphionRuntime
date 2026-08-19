# 鼎桥客户 ASR 剩余 TODO（2026-08-19）

## 本轮已关闭的真机证据

- Speaker VAD 先后交替：`speaker-vad-turn` 的 C1-alternating 在设备 `7GK0226326015655`
  通过；两个目标人句子均保留，干扰句“你好”被拒绝，显式 `finish` 前 `isLast=0`，结束后唯一
  last/complete。报告：`/private/tmp/amphion-main-audit.zRqUJD/runs/20260819-233658-speaker-vad-turn-8d8dcc26/report.json`，
  SHA-256 `5c17230b43ea3ed2c61763f04c5a7d237bdb02f457da48788f6d012693be9638`。
- BUG-01 Runtime 释放竞态：同设备 `finish-shutdown-relicense` 通过；唯一 last/complete、无 error、
  native stream 归零，relicense 后下一 session 恢复成功。报告：
  `/private/tmp/amphion-main-audit.zRqUJD/runs/20260819-233739-finish-shutdown-relicense-a4e00ed5/report.json`，
  SHA-256 `1115b4fdba854fa84124710cfe384ad9860cadaccf93ad53d4f526c7f03c6fed`。

以上只关闭用户指定的交替场景和 BUG-01 生命周期场景；Speaker VAD 重叠说话仍明确不处理。

## 长会议后段无 final

现状：已排除 20 秒 rule3 和 55/62 秒 session 自动结束，但客户长会议的连续上下文在累计约
1088 秒后仍只产生 partial，不再产生非空 final。原文件从 1286.143 秒起连续 1254.217 秒为
全零 PCM；真正需要继续定位的是此前 198.4 秒非零音频。该 198 秒单独启动新 session 时能识别
“什么录音？”，说明问题依赖前序连续状态，不能归因为这段语料完全不可识别。

下一步：

1. 对 SHA-256 固定的 0–1286.143 秒前缀以真实 20 ms pace 运行一次，记录每条 final 对应的累计
   `pcmBytesAccepted`、队列深度、in-flight decode、partial/final 时间线和 `finish` 排队时长。
2. 若真实 pace 仍在约 1088 秒停止 final，二分裁剪前序上下文，得到能稳定触发状态退化的最短前缀；
   在 Runtime 最内层状态机修复，并用同输入、同调用时序做 main/修复版差分。
3. 若只有 5 ms 注入失败，则把问题归为测试背压：为载体增加“已接受 PCM / 已完成 decode”进度，
   `finish` 超时从处理进度判定，不把人为积压作为产品死锁；不得跳过未处理 PCM 或提前发 complete。

停止条件：同一前缀在真实 pace 下，旧停点之后至少出现一个非空 final；显式 `finish` 前
`isLast=0`，结束后唯一 last、唯一 complete、native stream 归零。

## PTT “签警情”错字

现状：立即松手录音在 finish 前补 0/500 ms 静音均稳定输出“电警情”；另一录音补 200/1000 ms
均稳定输出“天警情情”。SDK 内部还固定补 1280 ms 解码尾部，因此当前证据否定“松手过快导致尾帧
未解码”，继续增加静音不是有效修复。

下一步：把两段固定 SHA-256 语料加入带真值的模型评测，比较当前模型、候选模型及业务热词的
token posterior/CER。只有模型或热词策略在不降低相邻警务短句准确率时才能交付；不得在 SDK 中
按结果字符串硬改，也不得用重复上一条结果或假文本补齐。

## 明确不进入本轮

- Speaker VAD 重叠说话；本轮只验收先后交替说话。
- 远讲/SNR/SourceType、警务词整体准确率、hotword 专项。
