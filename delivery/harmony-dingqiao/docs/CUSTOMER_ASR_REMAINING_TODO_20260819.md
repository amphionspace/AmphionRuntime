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

状态：**已有可证明的改善，但尚未完全关闭**。已排除 20 秒 rule3、55/62 秒 session 自动结束和
5 ms 注入积压。原文件从 1286.143 秒起连续 1254.217 秒为全零 PCM；有效排查范围固定为
0–1286.143 秒前缀。

已证明的根因层差分：空 endpoint 使用 soft reset 会保留 encoder cache，连续空段后会让后续真实
语音持续无 token。对固定 SHA-256 的 800–1286.143 秒短化语料，同为 5 ms pace：

- 修复前最后非空 final 仅覆盖到 402.56 秒，尾部约 83.6 秒无新文字；报告 SHA-256
  `548e498a84ea1f7c6bcbdca7c47b2daace528732ea07f415258721f908a813bf`。
- 空 endpoint 改为 fresh stream 后覆盖到 480.12 秒，尾部恢复“商品质量…案件巡查…红牛”等
  非空文字；报告 SHA-256
  `47752b6c30f77276081964885df389bb6b65d2f06d36aba3d11f1ab2e177284d`。

唯一一次完整实时修复后验收也越过旧停点：修复前最后非空 final 约 1087.74 秒，修复后推进到
1198.10 秒，并恢复两条非空 final；`finish` 前 `isLast=0`，结束后唯一 last/complete、无 error、
stream 归零。修复后报告：
`/private/tmp/amphion-main-audit.zRqUJD/real-pace-fixed-runs/20260820-001938-customer-transcription-c691bc3c/report.json`，
SHA-256 `b2e9ccab03947974c7fc7ecbfa374e06c9271eedd110bd8164a29cf25e1b5dd9`。

仍未关闭的证据：1198.10–1286.143 秒尾段在长 session 中没有新 final，但同一 88.043 秒 PCM
用 fresh engine 能产生 3 条非空 final（“来一次。中国人肯定出多。视频。”）。因此 stream cache
是一个已修根因，但还存在更长寿命的 recognizer/session 状态失效，不能把整项宣称为已解决。

下一步：

1. 使用新增的 `ENDPOINT`、`RESULT_SUPPRESSED`、`STREAM_TRANSITION` 指标，在最短上下文上记录
   stream generation、endpoint 来源、text/token、soft/hard restart、抑制原因与累计 PCM。
2. 从 1198.10 秒同一位置做局部 A/B：A 保留异常 recognizer/context，B 创建 fresh recognizer 后
   解码同一 PCM；确认失效归属后只修最内层状态机。
3. 只用短化实验完成红绿差分；完整 1286.143 秒实时语料仅在下一次根因修复后做一次最终验收，
   不通过反复长跑猜测。

停止条件：同一短化输入在异常 recognizer 上红、fresh recognizer 绿，并由内部状态指标解释差异；
最终同一前缀在真实 pace 下覆盖剩余可识别尾段，显式 `finish` 前 `isLast=0`，结束后唯一 last、
唯一 complete、无 error、native stream 归零。

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
