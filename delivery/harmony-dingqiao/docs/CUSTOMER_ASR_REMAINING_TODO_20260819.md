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

## 未关闭缺陷清单

| 缺陷 | 当前状态 | 影响与后续 |
| --- | --- | --- |
| BUG-02 约 20 秒 rule3 final | **代码已改，行为验收未关闭** | 鼎桥层已暴露 `endpointMaxUtteranceMs`，长会议 profile 设为 60 秒并纳入 recognizer 复用键。现有自动化验证参数解析和源码连线，仍需同一语料 20/60 秒的 native final 边界与 recognizer 不复用真机 A/B，不得仅凭源码测试宣称闭环。 |
| BUG-02 55/62 秒会话轮转边界 | **长会议 profile 已停用轮转，专项验收未关闭** | 当前长会议场景不再主动切 session，但还需在公共 SDK 回调上确认旧轮转点无帧空窗、`finish` 前 `isLast=0` 且结束后唯一 last/complete。 |
| 长会议后段有声无文字 | **部分缓解，未关闭** | `79fadfa` 把最后非空 final 从约 1087.74 秒推进到 1198.10 秒，但 1198.10–1286.143 秒仍无新 final。后续需定位更长寿命 recognizer/session 状态失效。 |
| 空 native endpoint 后 hard restart 边界丢 token | **已稳定复现，未修复** | 同一 33.44 秒 PCM 中 hard 路径稳定比 soft 路径少首 token“我”。后续只允许在 native recognizer 内部设计窄作用域 seam。 |
| PTT“签警情”错字 | **未关闭** | 补尾静音不能改变稳定错词，已排除单纯尾帧未解码。转入固定真值的模型/热词 CER 评测。 |
| Speaker VAD 重叠说话 | **未关闭，本轮不处理** | 本轮只关闭先后交替场景；重叠需 diarization/overlap 能力，不使用当前边界逻辑猜测归属。 |
| BUG-08 远讲/SNR/SourceType 退化 | **未关闭，本轮不处理** | 需带真值的分层 CER 评测，不与生命周期修复混合归因。 |
| BUG-09/10 警务词与专项 hotword 准确率 | **未关闭，本轮不处理** | 需在固定警务语料上比较 CER/WER 和相邻短句退化；不用 SDK 字符串硬改。 |
| 0.3.5 模型身份证数字缺失 | **回滚验证中** | 客户 App 留存的 6.62 秒 PCM 在 native 解码阶段未产生身份证数字 token，已排除 UI 和字符串后处理。0.3.6 回滚到 0.3.4 已交付模型，并以同一 PCM 的数字输出作为发布硬门禁；通过前不得交付。 |
| 回滚模型的 AGC 基线 | **复用旧模型证据，发布门禁待复核** | 0.3.6 恢复旧 encoder `0e86…`，此前绑定该模型的 AGC 证据重新适用；发布前仍需最小增量复核，不沿用 0.3.5 新模型 `ea36…` 的结论。 |

本清单是分支收口时的状态账本：“本轮不处理”只表示不进入本 PR，不表示缺陷已解决。

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

该 canonical 证据固定绑定以下验证对象，后续仅文档、证据索引或发布元数据提交不改变其结论：

- code-under-test：`79fadfa`（空 endpoint 后刷新失效 stream 的独立候选修复）；
- exact HAP：`/private/tmp/amphion-main-audit.zRqUJD/empty-boundary-builds/79fadfa-hard-current-head.hap`；
- HAP SHA-256：`2f4c8d1498da4b72f93a904cb6115a645c9bb883d8a21cc672130d335b9c2e6b`。

2026-08-20 收口时只做静态复核，没有重放音频：HAP 与报告路径存在且 SHA-256 匹配；报告为
`overall_status=PASS`，`lastFinalsBeforeFinish=0`，结束后唯一 `final-last -> complete`，`errors=0`，
`liveStreams=0`。PR 必须同时记录代码提交、HAP 哈希和报告路径，不能用后续文档提交的 HEAD
替代 code-under-test，也不能把这次“明显缓解”写成“完全解决”。

仍未关闭的证据：1198.10–1286.143 秒尾段在长 session 中没有新 final，但同一 88.043 秒 PCM
用 fresh engine 能产生 3 条非空 final（“来一次。中国人肯定出多。视频。”）。因此 stream cache
是一个已修根因，但还存在更长寿命的 recognizer/session 状态失效，不能把整项宣称为已解决。

### hard restart 边界丢 token 的后续诊断

固定 33.44 秒 PCM（SHA-256
`45d88c15f06a630b423d9ba520a0e7b53ddbef925b5b22ac2e69640be98a947a`）已建立稳定同输入 A/B。
两路在 757760 bytes / 11.84 秒命中相同的纯空 native endpoint：

- `79fadfa` 的 hard restart 路径在后续 final 输出“看不出来”；3 轮结果相同。
- soft reset 对照输出“我看不出来”；3 轮结果相同。
- 在 ITN 和鼎桥适配前的 native result 中，soft 路径首 token 为“我”、timestamp=0.24，
  hard 路径首 token 为“看”、timestamp=0.24。因此已证明差异产生于 native 解码层，
  不是适配层或字符串后处理问题。

hard 实时对照报告 SHA-256
`3b8d4952a8804200ca1797cdef8d0c1d75f46deff223b5e7d22f05e9ed573cd1`；soft 实时对照报告 SHA-256
`5b627cd6d64ad5d5416e92bfc697c4e7fd2625808171b2f8b6ee34e0ab16570b`。两路均满足 `finish` 前
`isLast=0`、结束后唯一 last/complete、无 error、stream 归零；该差异是文本完整性缺陷，
不是生命周期失败。

已否决两个窄化 reset 策略：“首次空 endpoint soft、连续空 endpoint hard”和“空 endpoint
hard、紧随的有文字 endpoint soft”均能修复 33 秒样本，但都在 486 秒上下文验证中丢失
“商品质量 / 案件巡查 / 红牛”尾段，因此已撤销，不得作为修复恢复。统一重放
640 ms PCM、公开 `overlapPrefixSamples` 和鼎桥字符串去重方案同样已否决，不属于
当前分支。

本分支收口结论：`79fadfa` 作为“空 endpoint 后刷新失效 stream”的独立候选修复保留，
它能显著缓解长会议无文字，但不关闭整个长会议问题，也不关闭 hard restart 边界丢 token。
后续只能在真实红灯对应的 native recognizer 内部设计窄作用域声学上下文 seam；如果无法
依据 token timestamp/native frame boundary 区分重放 token 与新 token，应停止实现，不得使用
字符串启发式或让 overlap PCM 进入公共 utterance、Speaker VAD 和声纹 PCM。只有局部
33 秒红绿和 486 秒上下文都通过后，才允许做一次完整 1286.143 秒最终验收。

## 后续工程项：真机门禁分层与批量化

该工程项不进入本 PR：PR 只运行 L0/L1 最小增量场景；nightly 或 merge queue 批量运行 L2；
发布前运行 L3 长会议和长稳压。执行载体应固定为单 HAP、单次安装，通过 scenario manifest
批量运行，多设备按场景分片并行。目标是复用同一二进制证据、减少重复构建与安装，同时保持
失败 artifact 不可覆盖；不得用门禁分层降低生命周期断言或把 L3 长跑下放为日常定位手段。

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
