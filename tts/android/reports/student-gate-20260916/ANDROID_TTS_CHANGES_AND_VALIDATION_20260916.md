# Android TTS 本轮修改、测试与 155 条发音差异完整说明

记录日期：2026-09-16

分支：`feat/android-tts-student-10000-temp0`

对比基线：`b84710f7615edddc9f2a4f2a3b6cbab465ddbda4`

代码状态：本文与基线之后的本轮代码、测试修改一起归档提交；以包含本文的 Git 提交为准。

验证设备：TECNO KI8，Android 13，arm64-v8a。

## 1. 范围和结论

本文完整记录这轮“适配旧测试、排查批测问题、逐条核对 155 条发音差异”的修改，附上全部 155 条原文、旧标注、实际拼音、判定理由和处理意见。此前更换模型、UI、旋转、FP16 回退等历史工作不计入本轮修改。

本轮修改集中在三个方面：

1. **文本前处理**：修复数字路径、时间前导零、整数转换、技术标识符、部分读音及序数上下文问题。
2. **引擎结束状态**：修复完成或报错后立即停止／销毁时，又多报一次 STOP 的竞态。
3. **测试与记录**：让工程批测使用当前模型和授权资源，新增真正执行队列／抢占／停止／销毁的压力测试，并逐条判定发音差异。

155 条差异的主分类为：17 条前处理缺陷、34 条标注错误、18 条输入日期无效或自相矛盾、86 条读法或标注口径差异。主分类互斥，但一条可能兼有两个问题，附录逐条列出。

**验收状态：不能宣布所有测试通过。** 当前工作区 JVM 测试通过；手机上的 1000 场景长稳已按用户要求停止，已落盘的 208 个场景全部通过；未完成全部 1000 场景。155 条中的 17 条序数修复已做 JVM 回归，尚未安装到手机；原始发音标注没有被整批覆盖。

## 2. 模型和运行配置

本轮沿用以下配置，修改发生在前处理、引擎状态和测试代码中：

| 项目 | 配置 |
| --- | --- |
| 模型 | 当前流式 student，`dingqiao_intmeanflow_student_0010000_streaming_matched50_vocos24k` |
| 温度 | 0 |
| 应用使用的 speaker | 1 |
| 输出 | Vocos，24 kHz |
| 模型 token 表 | 173 项；本轮未改映射或权重 |
| 推理方式 | 整句条件编码、各 flow step 独立 KV 缓存 |
| 默认推理块 | 50 帧 |
| 当前导出模型的可用块 | 均匀块，至少 40 帧；小于 40 的配置仍应按不支持处理 |

本轮的“块兼容适配”是把旧成功测试补成当前模型可运行的输入，并保留原输入作为负例；没有把 16／32 帧静默伪装成受支持，也没有新增一种模型导出格式。

## 3. 前处理具体改了什么

TN 指文本归一化，例如把数字和时间转换成要读出的文字。G2P 指文字到读音／模型 token 的转换。

| 修改 | 原问题 | 本轮行为与原因 | 实现位置 |
| --- | --- | --- | --- |
| 数字路径 | 提前替换 `/18/` 中的数字，把原路径切开，剩余 `/` 可能被底层 TN 读成“或” | 将路径作为完整技术标识符处理，统一转换数字和分隔符，保留每一个斜杠 | `LitsTnNormalizer.kt` |
| 时间前导零 | `3:05`、`5 点 05 分` 的零可能丢失，空格或阿拉伯小时造成规则不一致 | 保留“零五分”，同时覆盖数字／中文小时与空格形式 | `LitsTnNormalizer.kt` |
| 整数读法 | 112 等内部“一十”丢字；旧小整数转换遇到千位可能越界；重复转换逻辑不一致 | 新增共享 `MandarinCardinal`，按万分组，保留内部“一”，处理跨组零；10～19 只在整个数词开头省略“一” | 新增 `MandarinCardinal.kt`，TN 和 G2P 调用它 |
| build 编号 | `build 20260702` 可能被当成数量展开 | 按标识符逐位读“二零二六零七零二”；普通数量继续按数值读 | `LitsTnNormalizer.kt` |
| 订单 ID | `订单 ID 是 A12B11` 没有走完整的编号保护规则 | 扩展 ID 语境，数字段按“一二”“一一”逐位处理 | `LitsTnNormalizer.kt` |
| PCM 缩写 | 底层 `cm` 单位规则可能把 `audio.pcm` 的后缀变成“p厘米” | 在进入该规则前保护为 `P C M` 字母读法 | `LitsTnNormalizer.kt` |
| 语境读音 | “音量调到”“串行”“只终止”需要更明确的语境读音 | 增加这三个短语的默认读音；模型显式词典仍优先。“调到北京”的“调”不受音量短语规则影响 | `LitsTtsFrontend.kt` |
| 技术英文词 | `callback`、`emoji`、`requestId` 可能退回逐字母拼读 | 增加明确的英语音素读法 | `LitsTtsFrontend.kt` |
| 轻声前的“一” | 后字轻声掩盖本调，影响“一”的变调判断 | 判断“一”时参考后字的本调，例如“稍等一下” | `LitsTtsFrontend.kt` |
| 小数开头的“一” | “一点二三”可能按“一点水果”的数量结构变调 | 小数 `1.x` 保留 `yi1`，普通“一点水果”仍按数量短语处理 | `LitsTtsFrontend.kt` |
| 序数上下文 | `第 100 轮` 被空格拆块后，“一”看不到“第”；同一个长序数内部也可能丢上下文 | G2P 带入完整上下文，跨空白及同一数词保留“第”；标点和其他词终止该上下文 | `LitsTtsFrontend.kt` |

### 3.1 序数修复对应的 17 条

- 11 条是多音字／姓氏样例末尾的“第 100～110 轮”，问题在序数“一”，不是样例中的姓氏。
- 6 条是分数样例末尾的“第 104／116／128／140／152／164 次”。
- 修复前，格式空格会改变序数读法；修复后有无空格遵循同一规则。
- 新增单测覆盖普通空格、制表符、同一长序数的内部“一”，以及普通数量和标点边界。
- 使用真机已记录的 TN 文本重新跑 155 条 JVM G2P，恰好只有这 17 条发生变化。
- 其中 16 条恢复匹配原标注。`v3-parity-tn-numeric-date-money-unit-115` 还存在旧标注漏字：116 标成“一百十六”，正确展开为“一百一十六”。

这里的 17 是受影响样例数，对应一类上下文缺陷，不是 17 个独立代码故障。

## 4. 引擎结束状态修复

### 4.1 现象和根因

1000 场景长稳首次尝试中，第 0 条请求已收到 `SYNTHESIS_COMPLETE`。随后切换语言、销毁旧引擎时，该请求又收到 STOP，测试在第 1 场景发现违规并停止。

根因是：回调已经告诉调用方“结束了”，但后台工作线程还没执行完 `finally`，引擎仍把该请求当成可取消的当前任务。完成通知与任务结束状态没有同步提交。

### 4.2 修改

修改 `TextToSpeechEngineImpl.kt`：

- 在进入调用方完成／错误回调之前，先在取消操作共用的锁下提交终止状态。
- 完成、错误和停止只能有一个最终终止结果。
- `stop`／`shutdown` 不再将已经通知结束的当前请求列入取消列表。
- `isBusy` 不再把已经通知结束的当前请求当成忙碌。
- 底层 worker 的存活和 native 资源释放仍单独追踪，不能因为回调结束就提前释放正在使用的 native 资源。
- 引入内部可注入的回调执行器供确定性测试使用；生产默认执行器保持原有行为。

### 4.3 必须保留的行为

“只合成”模式的 `SYNTHESIS_COMPLETE` 是最终结果；“合成并播放”模式中的这个事件只是合成阶段结束，音频可能仍在播放，仍应允许用户停止。后者以 `PLAYBACK_COMPLETE` 作为正常终止。

新增对照测试先复现以下失败，再验证修复：

1. 完成回调内立即 stop／shutdown，不能再收到 STOP。
2. 错误回调内立即 shutdown，不能再收到 STOP。
3. 合成并播放模式中，合成完成后仍能停止播放。

修复前两个失败用例均已保存；修复后相关 7 个取消／生命周期测试全部通过。

## 5. 测试适配改了什么

### 5.1 工程批测：235 → 252

`TtsEngineeringBatchTest.kt` 新增 `modelProfile=intmeanflow-student`，默认旧 profile 保留，未知 profile 会拒绝。

原 235 条批测中，有 17 条成功场景使用 16／32 帧，当前导出模型不支持。这 17 条分别拆成：

- 原参数负例：确认返回不支持的错误码。
- 相同文本和其他参数、块改为 40 帧的成功用例。

因此总数增加到 252。不是删除失败样例，也不是只改测试期望后停止验证合成。

测试初始化读取显式 `workPath`、`licensePath`、可选 `deviceIdPath`，检查授权成功；适配当前外置模型资源和设备 SN，不依赖旧资源路径或受限的系统序列号接口。

### 5.2 新增 1000 场景 Release-AAR 压力测试

新增 `AarStudentStabilityDeviceTest.kt`，profile 为 `student-public-api-v1`。旧 1000 条夹具中部分操作名实际落入普通单次合成，不能据此声称测过抢占和队列；新测试真实执行这些操作。

10 类场景各循环 100 次：中文、英文、中英混合、长文本、排队、抢占、停止、销毁重建、播放、非法输入后恢复。完整运行计划包含 1700 个请求。

覆盖均匀块 40／50／64／75／100／150／200，语速 0.8／1／1.2，音量 0.5／1，以及 PCM 队列容量 1／32。取消类动作在首个数据回调内触发，检查被取消请求、队列请求、替代请求和恢复请求各自的事件。

每个请求保留回调顺序、时间线、参数和统计，检查终止后回调、PCM 序号与格式、队列先后、错误码和恢复能力。每秒采样 RSS、峰值 RSS、线程、文件描述符和堆内存；这些采样本身不构成“无泄漏”或“低于 200 MB”的判定。首个失败即停止并保存现场。

### 5.3 修正两个测试假设

1. **播放开始和合成完成的先后不固定。** 两个线程并行，短音频可能先合成完才开始播放。测试检查 start 在前、播放完成在后、中间两个事件各一次；`API.md` 同步说明。
2. **错误发生阶段不同。** 非法文本／音量在启动前拒绝；模型块兼容性在 worker 启动后检查。测试分别核对对应事件和错误码。

### 5.4 发音检查工具

- 仅对完整模型 token（包含声调）完全相同的拼音别名做等价化，避免如 `mu4/m4` 的反查名称造成假差异；没有全局忽略声调。
- 真机输出新增实际 TN 文本，保留原标注与实际 token，便于判断错误发生在哪一层。
- JVM 发音检查读取真实 manifest；二进制词典为可选加速文件，当前文本词典即可运行，不再强制要求旧 `.bin` 文件或写死旧模型参数。
- 发音采集测试执行成功只表示数据收集成功；必须另看匹配／不匹配统计，不能把 `OK (1 test)` 当成语料全部正确。

## 6. 155 条核对结果怎样使用

| 主分类 | 条数 | 处理 |
| --- | ---: | --- |
| 前处理缺陷 | 17 | 序数上下文代码已修；已做同输入 JVM 回归 |
| 标注错误 | 34 | 逐条记录应改位置，例如缺十、缺一、跨逗号变调；原始文件保留 |
| 输入无效或矛盾 | 18 | 包含不存在的日期及日期与星期矛盾；建议重建有效日期样例，旧输入保留作容错测试 |
| 读法／标注口径差异 | 86 | 记录可接受读法及原因；尚未据此放宽自动验收 |

“可接受”是本次文本和代码核对的判断，不是音频听感结论。三声连读受分组影响，书面拼音又可能保留本调，所以不能把所有声调差异视为同一类错误。具体依据和例外见附录。

当前并未生成一个把实际输出直接当正确答案的新 golden 文件。后续若修订验收集，应逐条保留修改理由，并显式列出有限候选，不能全局删除声调、标点或数词单位来提高通过率。

## 7. 验证结果与对应版本

| 测试 | 结果 | 适用版本／限制 |
| --- | --- | --- |
| 原始工程 235 条 | 184 PASS、34 EXPECTED_ERROR、17 FAIL、0 TIMEOUT | 适配前；17 个失败均是旧块大小 |
| 适配后工程 252 条 | 201 PASS、51 EXPECTED_ERROR、0 FAIL、0 TIMEOUT | 第一轮前处理修复；早于终止竞态与序数修复 |
| reviewed 发音 675 条真机检查 | 520 匹配、155 不匹配、0 执行错误 | 第一轮前处理修复后；严格拼音门禁仍未全过 |
| 终止竞态对照测试 | 修复前两个失败，修复后相关 7 项通过 | 确定性回调重入验证 |
| 终止竞态修复后真机短跑 | 30 场景／51 请求通过 | 手机安装版本；早于序数修复 |
| 终止竞态修复后 API 真机测试 | 6 项通过 | API、生命周期、可变块；早于序数修复 |
| 155 条同输入 JVM G2P 回归 | 只有 17 条发生变化；16 条匹配旧标注，1 条兼有旧标注漏字 | 使用真机记录的 TN 文本，不是新 JNI／真机语料运行 |
| 当前工作区完整 JVM 单测 | 142 项：138 通过、4 项原有跳过、0 失败 | 包含序数修复 |
| 1000 场景完整压力测试 | 按用户要求停止：208 PASS、0 FAIL，未完成 1000 条 | 已停止运行的测试包早于序数修复 |

675 条旧标注此前有 439 匹配／236 差异；后来的 520／155 同时包含前处理修复和等价拼音别名比较规则的影响，因此不能将增加的 81 条全部表述为独立运行时缺陷修复。

### 7.1 1000 场景快照

运行 ID：`student-stability-1789424250056`。用户要求暂停长稳，已停止测试宿主并保存现有结果。共落盘 208 个场景，208 PASS、0 FAIL；状态为 `STOPPED_BY_USER`。被中断的在途场景、正常退出清理和余下场景未验收，不能算完整长稳通过。中断记录见 `stability-stopped-summary.json`。

首次长跑（修复前）在第 1 场景捕获“完成后 STOP”，不是完整通过。当前运行结果也不能替代最新序数修复的真机验收。

### 7.2 手机、工作区与推送状态

- 手机示例包已包含第一轮前处理修复和终止竞态修复。
- 最新序数上下文修改已在工作区完成，并通过 JVM 验证；尚未装到手机。
- 以上本轮修改与本文一并归档到当前分支；提交记录以 Git 为准。
- 模型、温度和 speaker 不因本轮测试与文档整理发生变化。

## 8. 文件清单

以下路径以 `tts/android/` 为根，便于按功能审查。

| 文件 | 作用 |
| --- | --- |
| `sdk/src/main/java/com/lits/tts/sdk/internal/LitsTnNormalizer.kt` | 时间、路径、标识符、PCM 保护及共享整数转换 |
| `sdk/src/main/java/com/lits/tts/sdk/internal/MandarinCardinal.kt`（新增） | 共享中文整数转换 |
| `sdk/src/main/java/com/lits/tts/sdk/internal/LitsTtsFrontend.kt` | 技术词读音、语境词、变调与序数上下文 |
| `sdk/src/main/java/com/lits/tts/sdk/internal/TextToSpeechEngineImpl.kt` | 终止状态与 stop／shutdown 竞态修复 |
| `sdk/src/test/java/com/lits/tts/sdk/internal/LitsTtsFrontendTest.kt` | 前处理回归及相邻行为保护 |
| `sdk/src/test/java/com/lits/tts/sdk/internal/TextToSpeechEngineCancellationTest.kt` | 结束／错误回调内重入及播放可停止验证 |
| `sdk/src/test/java/com/lits/tts/sdk/internal/PronunciationRound15FrontendCorrectnessTest.kt` | 当前资源适配与拼音别名等价化 |
| `sdk/src/androidTest/java/com/lits/tts/sdk/internal/PronunciationRound15FrontendDeviceTest.kt` | 保存实际 TN 文本与原始／实际读音 |
| `sdk/src/androidTest/java/com/lits/tts/sdk/internal/TtsEngineeringBatchTest.kt` | 当前资源授权与 student 批测 profile |
| `aarHost/src/androidTest/java/com/lits/tts/aarhost/AarLicensedExternalResourcesRule.kt` | 测试设备 SN 提供方式 |
| `aarHost/src/androidTest/java/com/lits/tts/aarhost/AarStudentStabilityDeviceTest.kt`（新增） | 1000 场景 Release-AAR 压力测试 |
| `sample/src/androidTest/java/com/lits/tts/sample/ApiAuditDeviceTest.kt` | 并行播放事件顺序的正确断言 |
| `docs/API.md` | 播放事件先后语义说明 |
| `docs/BATCH_TESTING.md` | 外置资源、student profile、长稳及发音检查说明 |
| `reports/full-batch-20260916/` | 适配前原始批测结果 |
| `reports/student-gate-20260916/` | 本轮验证、逐条核对 JSON／Markdown 与本文 |

## 9. 证据位置

本机工作区 `outputs/tts-student-gate-20260916/` 下保留：

| 路径 | 内容 |
| --- | --- |
| `engineering-student-final/` | 252 条逐条结果与汇总 |
| `pronunciation-final/` | 675 条真机 TN／拼音结果 |
| `remaining-pronunciation-review.json` | 序数修复前的 155 条原始差异 |
| `terminal-race-unit-red/` | 引擎终止竞态修复前失败断言 |
| `terminal-race/` | 终止竞态修复阶段的构建件、单测与哈希记录 |
| `terminal-race-pilot.log`、`api-terminal-race.log` | 终止竞态修复后的真机短跑／API 结果 |
| `student-1000-terminal-race.log` | 已按用户要求停止的长稳入口日志 |
| `ordinal-unit-red/` | 序数修复前的失败断言 |
| `pronunciation-audit/host-after-ordinal/` | 155 条修复后的 JVM 拼音结果 |
| `pronunciation-audit/unit-all/`、`verification.json` | 当前完整 JVM 结果及变化范围检查 |

仓库内的 `pronunciation-adjudication-155.json` 与附录按相同 ID 一一对应，适合后续修订标注时保留审查记录。不同阶段的构建件哈希不能混用；终止竞态阶段的产物不包含后来的序数修复。

## 10. 未完成和已知限制

- 1000 场景长稳已按用户要求停止，仅保存 208 条通过的部分结果；不能称完整稳定性通过。
- 最新序数修复未重新安装／跑真机 JNI 与完整 675 条，也未做主观音质试听。
- 34 条标注错误、18 条输入问题和 86 条口径差异已逐条说明，尚未覆盖旧 golden 或实现新的多候选验收集。
- pitch 的实际变调效果仍是此前记录的独立问题；参数被接受不等于效果已验证。
- RSS 低于 200 MB 的目标未达成；压力测试内存采样包含测试宿主，不能据此宣称满足目标或没有泄漏。
- Harmony 未改动，未声明 Harmony 构建或设备测试通过；本轮结论适用于 Android。
- 本轮未改变模型权重、173-token 映射或底层流式缓存算法，不能把这些前处理结论推广为模型音质已验收。

## 附录：155 条发音差异逐条核对全文

以下完整保留本轮核对结果，避免只提供分类数字而缺少单条判断依据。

## 155 条发音差异逐条核对

范围：原真机 reviewed-675 结果中的 155 条差异。按原文语义、归一化文本、完整拼音串和代码核对；不是 155 段音频的听感测评，也未重新逐条审查其余 520 条。

### 结论

| 主分类 | 条数 |
| --- | ---: |
| 标注错误 | 34 |
| 语料内容无效或自相矛盾 | 18 |
| 读法／标注口径差异 | 86 |
| 前处理缺陷 | 17 |

主分类互斥，但一条可能兼有多个问题，见各条“附加问题”。保留原始标注，未把实际输出整批回填为正确答案；“可接受读法”尚未用于放宽自动验收。

### 已修复与验证

17 条涉及序数“一”的上下文：空格拆块使“第 100 轮”与“第一百轮”的处理不同；同一个序数内部的“一”也要保留上下文。修复前对照单测失败，修复后通过。155 条使用真机已记录的 TN 文本重新运行 JVM G2P：16 条与原标注一致，剩下那条同时存在旧标注漏字（116 → 一百十六）。这不等于 JNI/TN 真机重跑或主观音质通过。

### 判定依据

- 语料原文决定数值、序数、日期与标识符的语义；旧标注不能把十三秒改成一三秒，或漏掉一百一十三中的一。无效日期要标为输入问题。
- [普通话语音教学：一的数量结构与序数结构](https://wenxueyuan.ruc.edu.cn/UploadFile/20140703/20140703092245142.pdf)区分了一与位数词结合的变调、序数用法。这里以序数上下文不因格式空格丢失作为代码不变量。
- [晋中学院：音变教学](https://wxy.jzxy.edu.cn/uploads/zwx/file/20180409/1rnlf6h7km.pdf)说明三声连读受语义分组影响；多音节不能只按相邻字符机械判断唯一调串。
- [山西财贸职业技术学院：上声变调](https://www.sxftc.edu.cn/cjc/info/1228/2998.htm)区分书面本调标注与实际语流变调。旧数据混用两种口径，所以声调不同不能一律视作读错。

### 逐条结果

#### 001. v3-parity-zh-core-015

**原文：** 会议安排在 2026 年 7 月 16 日星期四。

**TN：** 会议安排在 二零二六年 七 月 十六 日星期四。

**判断：标注错误。** 日期中的 16 应按数值读；旧拼音把日期数字逐位拼读，缺少十位单位。

**标注：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 yi1 liu4 ri4 xing1 qi1 si4`

**修复前实际：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 shi2 liu4 ri4 xing1 qi1 si4`

**处理：** 修订日期读法标注；无效日期改为有效日期另建样例，保留旧样例作容错输入。

#### 002. v3-parity-zh-core-025

**原文：** 会议安排在 2026 年 7 月 26 日星期四。

**TN：** 会议安排在 二零二六年 七 月 二十六 日星期四。

**判断：语料内容无效或自相矛盾。** 日期中的 26 应按数值读；旧拼音把日期数字逐位拼读，缺少十位单位。

**附加问题：** 2026-07-26 是星期日，原文写星期四；同时存在日期数字拼音标注错误。

**标注：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 er4 liu4 ri4 xing1 qi1 si4`

**修复前实际：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 er4 shi2 liu4 ri4 xing1 qi1 si4`

**处理：** 修订日期读法标注；无效日期改为有效日期另建样例，保留旧样例作容错输入。

#### 003. v3-parity-zh-core-035

**原文：** 会议安排在 2026 年 7 月 36 日星期四。

**TN：** 会议安排在 二零二六年 七 月 三十六 日星期四。

**判断：语料内容无效或自相矛盾。** 日期中的 36 应按数值读；旧拼音把日期数字逐位拼读，缺少十位单位。

**附加问题：** 7 月没有 36 日。原文无效，同时存在上述拼音标注错误；TTS 不负责擅自改写用户日期。

**标注：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 san1 liu4 ri4 xing1 qi1 si4`

**修复前实际：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 san1 shi2 liu4 ri4 xing1 qi1 si4`

**处理：** 修订日期读法标注；无效日期改为有效日期另建样例，保留旧样例作容错输入。

#### 004. v3-parity-zh-core-045

**原文：** 会议安排在 2026 年 7 月 46 日星期四。

**TN：** 会议安排在 二零二六年 七 月 四十六 日星期四。

**判断：语料内容无效或自相矛盾。** 日期中的 46 应按数值读；旧拼音把日期数字逐位拼读，缺少十位单位。

**附加问题：** 7 月没有 46 日。原文无效，同时存在上述拼音标注错误；TTS 不负责擅自改写用户日期。

**标注：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 si4 liu4 ri4 xing1 qi1 si4`

**修复前实际：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 si4 shi2 liu4 ri4 xing1 qi1 si4`

**处理：** 修订日期读法标注；无效日期改为有效日期另建样例，保留旧样例作容错输入。

#### 005. v3-parity-zh-core-055

**原文：** 会议安排在 2026 年 7 月 56 日星期四。

**TN：** 会议安排在 二零二六年 七 月 五十六 日星期四。

**判断：语料内容无效或自相矛盾。** 日期中的 56 应按数值读；旧拼音把日期数字逐位拼读，缺少十位单位。

**附加问题：** 7 月没有 56 日。原文无效，同时存在上述拼音标注错误；TTS 不负责擅自改写用户日期。

**标注：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 wu3 liu4 ri4 xing1 qi1 si4`

**修复前实际：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 wu3 shi2 liu4 ri4 xing1 qi1 si4`

**处理：** 修订日期读法标注；无效日期改为有效日期另建样例，保留旧样例作容错输入。

#### 006. v3-parity-zh-core-065

**原文：** 会议安排在 2026 年 7 月 66 日星期四。

**TN：** 会议安排在 二零二六年 七 月 六十六 日星期四。

**判断：语料内容无效或自相矛盾。** 日期中的 66 应按数值读；旧拼音把日期数字逐位拼读，缺少十位单位。

**附加问题：** 7 月没有 66 日。原文无效，同时存在上述拼音标注错误；TTS 不负责擅自改写用户日期。

**标注：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 liu4 liu4 ri4 xing1 qi1 si4`

**修复前实际：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 liu4 shi2 liu4 ri4 xing1 qi1 si4`

**处理：** 修订日期读法标注；无效日期改为有效日期另建样例，保留旧样例作容错输入。

#### 007. v3-parity-zh-core-075

**原文：** 会议安排在 2026 年 7 月 76 日星期四。

**TN：** 会议安排在 二零二六年 七 月 七十六 日星期四。

**判断：语料内容无效或自相矛盾。** 日期中的 76 应按数值读；旧拼音把日期数字逐位拼读，缺少十位单位。

**附加问题：** 7 月没有 76 日。原文无效，同时存在上述拼音标注错误；TTS 不负责擅自改写用户日期。

**标注：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 qi1 liu4 ri4 xing1 qi1 si4`

**修复前实际：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 qi1 shi2 liu4 ri4 xing1 qi1 si4`

**处理：** 修订日期读法标注；无效日期改为有效日期另建样例，保留旧样例作容错输入。

#### 008. v3-parity-zh-core-016

**原文：** 本次订单金额为 17234.56 元，优惠 8.8 折。

**TN：** 本次订单金额为 一万七千二百三十四点五六 元,优惠 八点八 折。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `ben3 ci4 ding4 dan1 jin1 e2 wei2 yi1 wan4 qi1 qian1 er4 bai3 san1 shi2 si4 dian2 wu3 liu4 yuan2 you1 hui4 ba1 dian3 ba1 zhe2`

**修复前实际：** `ben3 ci4 ding4 dan1 jin1 e2 wei2 yi2 wan4 qi1 qian1 er4 bai3 san1 shi2 si4 dian2 wu3 liu4 yuan2 you1 hui4 ba1 dian3 ba1 zhe2`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 009. v3-parity-zh-core-058

**原文：** 验证码是 A9B8C7-59，请不要告诉别人。

**TN：** 验证码是 A九,B八,C七,杠五九,请不要告诉别人。

**判断：标注错误。** 59 后有逗号。旧标注把逗号后的请(qing3)与前面的九(jiu3)连做三声变调，标成 jiu2；当前在标点处断开，jiu3 正确。五九内部 wu2 jiu3 合理。

**标注：** `yan4 zheng4 ma3 shi4 EY1 jiu3 B IY1 ba1 S IY1 qi1 gang4 wu2 jiu2 qing3 bu2 yao4 gao4 su4 bie2 ren2`

**修复前实际：** `yan4 zheng4 ma3 shi4 EY1 jiu3 B IY1 ba1 S IY1 qi1 gang4 wu2 jiu3 qing3 bu2 yao4 gao4 su4 bie2 ren2`

**处理：** 修订跨标点变调标注；保留前处理的标点边界。

#### 010. v3-parity-mixed-zh-en-012

**原文：** Go go go，13 秒后开始录音。

**TN：** Go go go,十三 秒后开始录音。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `G OW1 G OW1 G OW1 yi1 san1 miao3 hou4 kai1 shi3 lu4 yin1`

**修复前实际：** `G OW1 G OW1 G OW1 shi2 san1 miao3 hou4 kai1 shi3 lu4 yin1`

**处理：** 修订数词拼音标注，保留当前 TN。

#### 011. v3-parity-mixed-zh-en-020

**原文：** Go go go，21 秒后开始录音。

**TN：** Go go go,二十一 秒后开始录音。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `G OW1 G OW1 G OW1 er4 yi1 miao3 hou4 kai1 shi3 lu4 yin1`

**修复前实际：** `G OW1 G OW1 G OW1 er4 shi2 yi1 miao3 hou4 kai1 shi3 lu4 yin1`

**处理：** 修订数词拼音标注，保留当前 TN。

#### 012. v3-parity-mixed-zh-en-028

**原文：** Go go go，29 秒后开始录音。

**TN：** Go go go,二十九 秒后开始录音。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `G OW1 G OW1 G OW1 er4 jiu2 miao3 hou4 kai1 shi3 lu4 yin1`

**修复前实际：** `G OW1 G OW1 G OW1 er4 shi2 jiu2 miao3 hou4 kai1 shi3 lu4 yin1`

**处理：** 修订数词拼音标注，保留当前 TN。

#### 013. v3-parity-mixed-zh-en-036

**原文：** Go go go，37 秒后开始录音。

**TN：** Go go go,三十七 秒后开始录音。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `G OW1 G OW1 G OW1 san1 qi1 miao3 hou4 kai1 shi3 lu4 yin1`

**修复前实际：** `G OW1 G OW1 G OW1 san1 shi2 qi1 miao3 hou4 kai1 shi3 lu4 yin1`

**处理：** 修订数词拼音标注，保留当前 TN。

#### 014. v3-parity-mixed-zh-en-044

**原文：** Go go go，45 秒后开始录音。

**TN：** Go go go,四十五 秒后开始录音。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `G OW1 G OW1 G OW1 si4 wu2 miao3 hou4 kai1 shi3 lu4 yin1`

**修复前实际：** `G OW1 G OW1 G OW1 si4 shi2 wu2 miao3 hou4 kai1 shi3 lu4 yin1`

**处理：** 修订数词拼音标注，保留当前 TN。

#### 015. v3-parity-mixed-zh-en-052

**原文：** Go go go，53 秒后开始录音。

**TN：** Go go go,五十三 秒后开始录音。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `G OW1 G OW1 G OW1 wu3 san1 miao3 hou4 kai1 shi3 lu4 yin1`

**修复前实际：** `G OW1 G OW1 G OW1 wu3 shi2 san1 miao3 hou4 kai1 shi3 lu4 yin1`

**处理：** 修订数词拼音标注，保留当前 TN。

#### 016. v3-parity-mixed-zh-en-060

**原文：** Go go go，61 秒后开始录音。

**TN：** Go go go,六十一 秒后开始录音。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `G OW1 G OW1 G OW1 liu4 yi1 miao3 hou4 kai1 shi3 lu4 yin1`

**修复前实际：** `G OW1 G OW1 G OW1 liu4 shi2 yi1 miao3 hou4 kai1 shi3 lu4 yin1`

**处理：** 修订数词拼音标注，保留当前 TN。

#### 017. v3-parity-mixed-zh-en-068

**原文：** Go go go，69 秒后开始录音。

**TN：** Go go go,六十九 秒后开始录音。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `G OW1 G OW1 G OW1 liu4 jiu2 miao3 hou4 kai1 shi3 lu4 yin1`

**修复前实际：** `G OW1 G OW1 G OW1 liu4 shi2 jiu2 miao3 hou4 kai1 shi3 lu4 yin1`

**处理：** 修订数词拼音标注，保留当前 TN。

#### 018. v3-parity-mixed-zh-en-076

**原文：** Go go go，77 秒后开始录音。

**TN：** Go go go,七十七 秒后开始录音。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `G OW1 G OW1 G OW1 qi1 qi1 miao3 hou4 kai1 shi3 lu4 yin1`

**修复前实际：** `G OW1 G OW1 G OW1 qi1 shi2 qi1 miao3 hou4 kai1 shi3 lu4 yin1`

**处理：** 修订数词拼音标注，保留当前 TN。

#### 019. v3-parity-tn-numeric-date-money-unit-014

**原文：** 订单金额 15234.56 元，优惠 8.8 折。

**TN：** 订单金额 一万五千二百三十四点五六 元,优惠 八点八 折。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `ding4 dan1 jin1 e2 yi1 wan4 wu3 qian1 er4 bai3 san1 shi2 si4 dian2 wu3 liu4 yuan2 you1 hui4 ba1 dian3 ba1 zhe2`

**修复前实际：** `ding4 dan1 jin1 e2 yi2 wan4 wu3 qian1 er4 bai3 san1 shi2 si4 dian2 wu3 liu4 yuan2 you1 hui4 ba1 dian3 ba1 zhe2`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 020. v3-parity-tn-numeric-date-money-unit-018

**原文：** 版本 v3.0.19 与 build 20260702 对齐。

**TN：** 版本 v三点零点一九 与 build 二零二六零七零二 对齐。

**判断：读法／标注口径差异。** 版本数字与后面的与连读时可发生三声变调；旧标注保留数字本调或不同韵律分组。当前没有增删版本数字。是否在版本号后停顿需由统一韵律规则决定，不能只以这一份拼音串判错。

**标注：** `ban2 ben3 V IY1 san1 dian3 ling2 dian3 yi1 jiu3 yu3 B IH1 L D er4 ling2 er4 liu4 ling2 qi1 ling2 er4 dui4 qi2`

**修复前实际：** `ban2 ben3 V IY1 san1 dian3 ling2 dian3 yi1 jiu2 yu3 B IH1 L D er4 ling2 er4 liu4 ling2 qi1 ling2 er4 dui4 qi2`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 021. v3-parity-tn-numeric-date-money-unit-034

**原文：** 速度 80km/h，距离目的地 35.5 公里。

**TN：** 速度 八十千米每小时,距离目的地 三十五点五 公里。

**判断：读法／标注口径差异。** 小数附近的三声连读或一百的一变调，与旧标注本调／分组口径不同；数值和单位未改变。mu4/m4 是相同模型 token 的反查别名，不是把目读成另一个声音。

**标注：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 mu4 di4 di4 san1 shi2 wu3 dian2 wu3 gong1 li3`

**修复前实际：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 m4 di4 di4 san1 shi2 wu2 dian2 wu3 gong1 li3`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 022. v3-parity-tn-numeric-date-money-unit-050

**原文：** 订单金额 51234.56 元，优惠 8.8 折。

**TN：** 订单金额 五万一千二百三十四点五六 元,优惠 八点八 折。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `ding4 dan1 jin1 e2 wu3 wan4 yi1 qian1 er4 bai3 san1 shi2 si4 dian2 wu3 liu4 yuan2 you1 hui4 ba1 dian3 ba1 zhe2`

**修复前实际：** `ding4 dan1 jin1 e2 wu3 wan4 yi4 qian1 er4 bai3 san1 shi2 si4 dian2 wu3 liu4 yuan2 you1 hui4 ba1 dian3 ba1 zhe2`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 023. v3-parity-tn-numeric-date-money-unit-054

**原文：** 版本 v3.0.55 与 build 20260702 对齐。

**TN：** 版本 v三点零点五五 与 build 二零二六零七零二 对齐。

**判断：读法／标注口径差异。** 版本数字与后面的与连读时可发生三声变调；旧标注保留数字本调或不同韵律分组。当前没有增删版本数字。是否在版本号后停顿需由统一韵律规则决定，不能只以这一份拼音串判错。

**标注：** `ban2 ben3 V IY1 san1 dian3 ling2 dian3 wu3 wu3 yu3 B IH1 L D er4 ling2 er4 liu4 ling2 qi1 ling2 er4 dui4 qi2`

**修复前实际：** `ban2 ben3 V IY1 san1 dian3 ling2 dian3 wu2 wu2 yu3 B IH1 L D er4 ling2 er4 liu4 ling2 qi1 ling2 er4 dui4 qi2`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 024. v3-parity-tn-numeric-date-money-unit-058

**原文：** 速度 80km/h，距离目的地 59.5 公里。

**TN：** 速度 八十千米每小时,距离目的地 五十九点五 公里。

**判断：读法／标注口径差异。** 小数附近的三声连读或一百的一变调，与旧标注本调／分组口径不同；数值和单位未改变。mu4/m4 是相同模型 token 的反查别名，不是把目读成另一个声音。

**标注：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 mu4 di4 di4 wu3 shi2 jiu3 dian2 wu3 gong1 li3`

**修复前实际：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 m4 di4 di4 wu3 shi2 jiu2 dian2 wu3 gong1 li3`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 025. v3-parity-tn-numeric-date-money-unit-078

**原文：** 版本 v3.0.79 与 build 20260702 对齐。

**TN：** 版本 v三点零点七九 与 build 二零二六零七零二 对齐。

**判断：读法／标注口径差异。** 版本数字与后面的与连读时可发生三声变调；旧标注保留数字本调或不同韵律分组。当前没有增删版本数字。是否在版本号后停顿需由统一韵律规则决定，不能只以这一份拼音串判错。

**标注：** `ban2 ben3 V IY1 san1 dian3 ling2 dian3 qi1 jiu3 yu3 B IH1 L D er4 ling2 er4 liu4 ling2 qi1 ling2 er4 dui4 qi2`

**修复前实际：** `ban2 ben3 V IY1 san1 dian3 ling2 dian3 qi1 jiu2 yu3 B IH1 L D er4 ling2 er4 liu4 ling2 qi1 ling2 er4 dui4 qi2`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 026. v3-parity-tn-numeric-date-money-unit-090

**原文：** 版本 v3.0.91 与 build 20260702 对齐。

**TN：** 版本 v三点零点九一 与 build 二零二六零七零二 对齐。

**判断：读法／标注口径差异。** 版本数字与后面的与连读时可发生三声变调；旧标注保留数字本调或不同韵律分组。当前没有增删版本数字。是否在版本号后停顿需由统一韵律规则决定，不能只以这一份拼音串判错。

**标注：** `ban2 ben3 V IY1 san1 dian3 ling2 dian3 jiu3 yi1 yu3 B IH1 L D er4 ling2 er4 liu4 ling2 qi1 ling2 er4 dui4 qi2`

**修复前实际：** `ban2 ben3 V IY1 san1 dian3 ling2 dian2 jiu3 yi1 yu3 B IH1 L D er4 ling2 er4 liu4 ling2 qi1 ling2 er4 dui4 qi2`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 027. v3-parity-tn-numeric-date-money-unit-094

**原文：** 速度 80km/h，距离目的地 95.5 公里。

**TN：** 速度 八十千米每小时,距离目的地 九十五点五 公里。

**判断：读法／标注口径差异。** 小数附近的三声连读或一百的一变调，与旧标注本调／分组口径不同；数值和单位未改变。mu4/m4 是相同模型 token 的反查别名，不是把目读成另一个声音。

**标注：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 mu4 di4 di4 jiu3 shi2 wu3 dian2 wu3 gong1 li3`

**修复前实际：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 m4 di4 di4 jiu3 shi2 wu2 dian2 wu3 gong1 li3`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 028. v3-parity-tn-numeric-date-money-unit-099

**原文：** 电量 100% ，预计还能使用 30 分钟。

**TN：** 电量 百分之一百 ,预计还能使用 三十 分钟。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `dian4 liang4 bai3 fen1 zhi1 yi1 bai3 yu4 ji4 hai2 neng2 shi3 yong4 san1 shi2 fen1 zhong1`

**修复前实际：** `dian4 liang4 bai3 fen1 zhi1 yi4 bai3 yu4 ji4 hai2 neng2 shi3 yong4 san1 shi2 fen1 zhong1`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 029. v3-parity-tn-numeric-date-money-unit-100

**原文：** 股票 600519 今日上涨 101.23% ，请播报。

**TN：** 股票 六零零五一九 今日上涨 百分之一百零一点二三 ,请播报。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `gu3 piao4 liu4 ling2 ling2 wu3 yi1 jiu3 jin1 ri4 shang4 zhang2 bai3 fen1 zhi1 yi1 bai3 ling2 yi1 dian3 er4 san1 qing3 bo1 bao4`

**修复前实际：** `gu3 piao4 liu4 ling2 ling2 wu3 yi1 jiu3 jin1 ri4 shang4 zhang2 bai3 fen1 zhi1 yi4 bai3 ling2 yi1 dian3 er4 san1 qing3 bo1 bao4`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 030. v3-parity-tn-numeric-date-money-unit-103

**原文：** 请加入 1/2 杯牛奶和 3/4 杯水，第 104 次。

**TN：** 请加入 二分之一 杯牛奶和 四分之三 杯水,第 一百零四 次。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi1 bai3 ling2 si4 ci4`

**修复前实际：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi4 bai3 ling2 si4 ci4`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi1 bai3 ling2 si4 ci4`

**仍匹配原始标注：** 是

#### 031. v3-parity-tn-numeric-date-money-unit-106

**原文：** 速度 80km/h，距离目的地 107.5 公里。

**TN：** 速度 八十千米每小时,距离目的地 一百零七点五 公里。

**判断：读法／标注口径差异。** 小数附近的三声连读或一百的一变调，与旧标注本调／分组口径不同；数值和单位未改变。mu4/m4 是相同模型 token 的反查别名，不是把目读成另一个声音。

**标注：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 mu4 di4 di4 yi1 bai3 ling2 qi1 dian2 wu3 gong1 li3`

**修复前实际：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 m4 di4 di4 yi4 bai3 ling2 qi1 dian2 wu3 gong1 li3`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 032. v3-parity-tn-numeric-date-money-unit-110

**原文：** 订单金额 111234.56 元，优惠 8.8 折。

**TN：** 订单金额 十一万一千二百三十四点五六 元,优惠 八点八 折。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `ding4 dan1 jin1 e2 shi2 yi1 wan4 yi1 qian1 er4 bai3 san1 shi2 si4 dian2 wu3 liu4 yuan2 you1 hui4 ba1 dian3 ba1 zhe2`

**修复前实际：** `ding4 dan1 jin1 e2 shi2 yi2 wan4 yi4 qian1 er4 bai3 san1 shi2 si4 dian2 wu3 liu4 yuan2 you1 hui4 ba1 dian3 ba1 zhe2`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 033. v3-parity-tn-numeric-date-money-unit-111

**原文：** 电量 112% ，预计还能使用 30 分钟。

**TN：** 电量 百分之一百一十二 ,预计还能使用 三十 分钟。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `dian4 liang4 bai3 fen1 zhi1 yi1 bai3 yi1 shi2 er4 yu4 ji4 hai2 neng2 shi3 yong4 san1 shi2 fen1 zhong1`

**修复前实际：** `dian4 liang4 bai3 fen1 zhi1 yi4 bai3 yi4 shi2 er4 yu4 ji4 hai2 neng2 shi3 yong4 san1 shi2 fen1 zhong1`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 034. v3-parity-tn-numeric-date-money-unit-112

**原文：** 股票 600519 今日上涨 113.23% ，请播报。

**TN：** 股票 六零零五一九 今日上涨 百分之一百一十三点二三 ,请播报。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `gu3 piao4 liu4 ling2 ling2 wu3 yi1 jiu3 jin1 ri4 shang4 zhang2 bai3 fen1 zhi1 yi1 bai3 yi1 shi2 san1 dian3 er4 san1 qing3 bo1 bao4`

**修复前实际：** `gu3 piao4 liu4 ling2 ling2 wu3 yi1 jiu3 jin1 ri4 shang4 zhang2 bai3 fen1 zhi1 yi4 bai3 yi4 shi2 san1 dian3 er4 san1 qing3 bo1 bao4`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 035. v3-parity-tn-numeric-date-money-unit-114

**原文：** 版本 v3.0.115 与 build 20260702 对齐。

**TN：** 版本 v三点零点一一五 与 build 二零二六零七零二 对齐。

**判断：读法／标注口径差异。** 版本数字与后面的与连读时可发生三声变调；旧标注保留数字本调或不同韵律分组。当前没有增删版本数字。是否在版本号后停顿需由统一韵律规则决定，不能只以这一份拼音串判错。

**标注：** `ban2 ben3 V IY1 san1 dian3 ling2 dian3 yi1 yi1 wu3 yu3 B IH1 L D er4 ling2 er4 liu4 ling2 qi1 ling2 er4 dui4 qi2`

**修复前实际：** `ban2 ben3 V IY1 san1 dian3 ling2 dian3 yi1 yi1 wu2 yu3 B IH1 L D er4 ling2 er4 liu4 ling2 qi1 ling2 er4 dui4 qi2`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 036. v3-parity-tn-numeric-date-money-unit-115

**原文：** 请加入 1/2 杯牛奶和 3/4 杯水，第 116 次。

**TN：** 请加入 二分之一 杯牛奶和 四分之三 杯水,第 一百一十六 次。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**附加问题：** 这一条同时有标注错误：116 标成一百十六，缺少中间的一。前处理修复后仍与原始标注不匹配。

**标注：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi1 bai3 shi2 liu4 ci4`

**修复前实际：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi4 bai3 yi4 shi2 liu4 ci4`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi1 bai3 yi1 shi2 liu4 ci4`

**仍匹配原始标注：** 否；原标注另有漏字，见附加问题

#### 037. v3-parity-tn-numeric-date-money-unit-118

**原文：** 速度 80km/h，距离目的地 119.5 公里。

**TN：** 速度 八十千米每小时,距离目的地 一百一十九点五 公里。

**判断：标注错误。** 119.5 应读一百一十九点五，旧标注漏了百后面的一；当前数值展开正确。一的表层变调与本调另属标注口径，mu4/m4 是相同模型 token 的别名。

**标注：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 mu4 di4 di4 yi1 bai3 shi2 jiu2 dian2 wu3 gong1 li3`

**修复前实际：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 m4 di4 di4 yi4 bai3 yi4 shi2 jiu2 dian2 wu3 gong1 li3`

**处理：** 补回标注缺失的一，并在新标注中区分本调和实际送模型的变调。

#### 038. v3-parity-tn-numeric-date-money-unit-123

**原文：** 电量 124% ，预计还能使用 30 分钟。

**TN：** 电量 百分之一百二十四 ,预计还能使用 三十 分钟。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `dian4 liang4 bai3 fen1 zhi1 yi1 bai3 er4 shi2 si4 yu4 ji4 hai2 neng2 shi3 yong4 san1 shi2 fen1 zhong1`

**修复前实际：** `dian4 liang4 bai3 fen1 zhi1 yi4 bai3 er4 shi2 si4 yu4 ji4 hai2 neng2 shi3 yong4 san1 shi2 fen1 zhong1`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 039. v3-parity-tn-numeric-date-money-unit-124

**原文：** 股票 600519 今日上涨 125.23% ，请播报。

**TN：** 股票 六零零五一九 今日上涨 百分之一百二十五点二三 ,请播报。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `gu3 piao4 liu4 ling2 ling2 wu3 yi1 jiu3 jin1 ri4 shang4 zhang2 bai3 fen1 zhi1 yi1 bai3 er4 shi2 wu2 dian3 er4 san1 qing3 bo1 bao4`

**修复前实际：** `gu3 piao4 liu4 ling2 ling2 wu3 yi1 jiu3 jin1 ri4 shang4 zhang2 bai3 fen1 zhi1 yi4 bai3 er4 shi2 wu2 dian3 er4 san1 qing3 bo1 bao4`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 040. v3-parity-tn-numeric-date-money-unit-127

**原文：** 请加入 1/2 杯牛奶和 3/4 杯水，第 128 次。

**TN：** 请加入 二分之一 杯牛奶和 四分之三 杯水,第 一百二十八 次。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi1 bai3 er4 shi2 ba1 ci4`

**修复前实际：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi4 bai3 er4 shi2 ba1 ci4`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi1 bai3 er4 shi2 ba1 ci4`

**仍匹配原始标注：** 是

#### 041. v3-parity-tn-numeric-date-money-unit-130

**原文：** 速度 80km/h，距离目的地 131.5 公里。

**TN：** 速度 八十千米每小时,距离目的地 一百三十一点五 公里。

**判断：读法／标注口径差异。** 小数附近的三声连读或一百的一变调，与旧标注本调／分组口径不同；数值和单位未改变。mu4/m4 是相同模型 token 的反查别名，不是把目读成另一个声音。

**标注：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 mu4 di4 di4 yi1 bai3 san1 shi2 yi1 dian2 wu3 gong1 li3`

**修复前实际：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 m4 di4 di4 yi4 bai3 san1 shi2 yi1 dian2 wu3 gong1 li3`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 042. v3-parity-tn-numeric-date-money-unit-135

**原文：** 电量 136% ，预计还能使用 30 分钟。

**TN：** 电量 百分之一百三十六 ,预计还能使用 三十 分钟。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `dian4 liang4 bai3 fen1 zhi1 yi1 bai3 san1 shi2 liu4 yu4 ji4 hai2 neng2 shi3 yong4 san1 shi2 fen1 zhong1`

**修复前实际：** `dian4 liang4 bai3 fen1 zhi1 yi4 bai3 san1 shi2 liu4 yu4 ji4 hai2 neng2 shi3 yong4 san1 shi2 fen1 zhong1`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 043. v3-parity-tn-numeric-date-money-unit-136

**原文：** 股票 600519 今日上涨 137.23% ，请播报。

**TN：** 股票 六零零五一九 今日上涨 百分之一百三十七点二三 ,请播报。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `gu3 piao4 liu4 ling2 ling2 wu3 yi1 jiu3 jin1 ri4 shang4 zhang2 bai3 fen1 zhi1 yi1 bai3 san1 shi2 qi1 dian3 er4 san1 qing3 bo1 bao4`

**修复前实际：** `gu3 piao4 liu4 ling2 ling2 wu3 yi1 jiu3 jin1 ri4 shang4 zhang2 bai3 fen1 zhi1 yi4 bai3 san1 shi2 qi1 dian3 er4 san1 qing3 bo1 bao4`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 044. v3-parity-tn-numeric-date-money-unit-138

**原文：** 版本 v3.0.139 与 build 20260702 对齐。

**TN：** 版本 v三点零点一三九 与 build 二零二六零七零二 对齐。

**判断：读法／标注口径差异。** 版本数字与后面的与连读时可发生三声变调；旧标注保留数字本调或不同韵律分组。当前没有增删版本数字。是否在版本号后停顿需由统一韵律规则决定，不能只以这一份拼音串判错。

**标注：** `ban2 ben3 V IY1 san1 dian3 ling2 dian3 yi1 san1 jiu3 yu3 B IH1 L D er4 ling2 er4 liu4 ling2 qi1 ling2 er4 dui4 qi2`

**修复前实际：** `ban2 ben3 V IY1 san1 dian3 ling2 dian3 yi1 san1 jiu2 yu3 B IH1 L D er4 ling2 er4 liu4 ling2 qi1 ling2 er4 dui4 qi2`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 045. v3-parity-tn-numeric-date-money-unit-139

**原文：** 请加入 1/2 杯牛奶和 3/4 杯水，第 140 次。

**TN：** 请加入 二分之一 杯牛奶和 四分之三 杯水,第 一百四十 次。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi1 bai3 si4 shi2 ci4`

**修复前实际：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi4 bai3 si4 shi2 ci4`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi1 bai3 si4 shi2 ci4`

**仍匹配原始标注：** 是

#### 046. v3-parity-tn-numeric-date-money-unit-142

**原文：** 速度 80km/h，距离目的地 143.5 公里。

**TN：** 速度 八十千米每小时,距离目的地 一百四十三点五 公里。

**判断：读法／标注口径差异。** 小数附近的三声连读或一百的一变调，与旧标注本调／分组口径不同；数值和单位未改变。mu4/m4 是相同模型 token 的反查别名，不是把目读成另一个声音。

**标注：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 mu4 di4 di4 yi1 bai3 si4 shi2 san1 dian2 wu3 gong1 li3`

**修复前实际：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 m4 di4 di4 yi4 bai3 si4 shi2 san1 dian2 wu3 gong1 li3`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 047. v3-parity-tn-numeric-date-money-unit-147

**原文：** 电量 148% ，预计还能使用 30 分钟。

**TN：** 电量 百分之一百四十八 ,预计还能使用 三十 分钟。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `dian4 liang4 bai3 fen1 zhi1 yi1 bai3 si4 shi2 ba1 yu4 ji4 hai2 neng2 shi3 yong4 san1 shi2 fen1 zhong1`

**修复前实际：** `dian4 liang4 bai3 fen1 zhi1 yi4 bai3 si4 shi2 ba1 yu4 ji4 hai2 neng2 shi3 yong4 san1 shi2 fen1 zhong1`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 048. v3-parity-tn-numeric-date-money-unit-148

**原文：** 股票 600519 今日上涨 149.23% ，请播报。

**TN：** 股票 六零零五一九 今日上涨 百分之一百四十九点二三 ,请播报。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `gu3 piao4 liu4 ling2 ling2 wu3 yi1 jiu3 jin1 ri4 shang4 zhang2 bai3 fen1 zhi1 yi1 bai3 si4 shi2 jiu2 dian3 er4 san1 qing3 bo1 bao4`

**修复前实际：** `gu3 piao4 liu4 ling2 ling2 wu3 yi1 jiu3 jin1 ri4 shang4 zhang2 bai3 fen1 zhi1 yi4 bai3 si4 shi2 jiu2 dian3 er4 san1 qing3 bo1 bao4`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 049. v3-parity-tn-numeric-date-money-unit-151

**原文：** 请加入 1/2 杯牛奶和 3/4 杯水，第 152 次。

**TN：** 请加入 二分之一 杯牛奶和 四分之三 杯水,第 一百五十二 次。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi1 bai2 wu3 shi2 er4 ci4`

**修复前实际：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi4 bai2 wu3 shi2 er4 ci4`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi1 bai2 wu3 shi2 er4 ci4`

**仍匹配原始标注：** 是

#### 050. v3-parity-tn-numeric-date-money-unit-154

**原文：** 速度 80km/h，距离目的地 155.5 公里。

**TN：** 速度 八十千米每小时,距离目的地 一百五十五点五 公里。

**判断：读法／标注口径差异。** 小数附近的三声连读或一百的一变调，与旧标注本调／分组口径不同；数值和单位未改变。mu4/m4 是相同模型 token 的反查别名，不是把目读成另一个声音。

**标注：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 mu4 di4 di4 yi1 bai2 wu3 shi2 wu2 dian2 wu3 gong1 li3`

**修复前实际：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 m4 di4 di4 yi4 bai2 wu3 shi2 wu2 dian2 wu3 gong1 li3`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 051. v3-parity-tn-numeric-date-money-unit-159

**原文：** 电量 160% ，预计还能使用 30 分钟。

**TN：** 电量 百分之一百六十 ,预计还能使用 三十 分钟。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `dian4 liang4 bai3 fen1 zhi1 yi1 bai3 liu4 shi2 yu4 ji4 hai2 neng2 shi3 yong4 san1 shi2 fen1 zhong1`

**修复前实际：** `dian4 liang4 bai3 fen1 zhi1 yi4 bai3 liu4 shi2 yu4 ji4 hai2 neng2 shi3 yong4 san1 shi2 fen1 zhong1`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 052. v3-parity-tn-numeric-date-money-unit-160

**原文：** 股票 600519 今日上涨 161.23% ，请播报。

**TN：** 股票 六零零五一九 今日上涨 百分之一百六十一点二三 ,请播报。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `gu3 piao4 liu4 ling2 ling2 wu3 yi1 jiu3 jin1 ri4 shang4 zhang2 bai3 fen1 zhi1 yi1 bai3 liu4 shi2 yi1 dian3 er4 san1 qing3 bo1 bao4`

**修复前实际：** `gu3 piao4 liu4 ling2 ling2 wu3 yi1 jiu3 jin1 ri4 shang4 zhang2 bai3 fen1 zhi1 yi4 bai3 liu4 shi2 yi1 dian3 er4 san1 qing3 bo1 bao4`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 053. v3-parity-tn-numeric-date-money-unit-163

**原文：** 请加入 1/2 杯牛奶和 3/4 杯水，第 164 次。

**TN：** 请加入 二分之一 杯牛奶和 四分之三 杯水,第 一百六十四 次。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi1 bai3 liu4 shi2 si4 ci4`

**修复前实际：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi4 bai3 liu4 shi2 si4 ci4`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi1 bai3 liu4 shi2 si4 ci4`

**仍匹配原始标注：** 是

#### 054. v3-parity-tn-numeric-date-money-unit-166

**原文：** 速度 80km/h，距离目的地 167.5 公里。

**TN：** 速度 八十千米每小时,距离目的地 一百六十七点五 公里。

**判断：读法／标注口径差异。** 小数附近的三声连读或一百的一变调，与旧标注本调／分组口径不同；数值和单位未改变。mu4/m4 是相同模型 token 的反查别名，不是把目读成另一个声音。

**标注：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 mu4 di4 di4 yi1 bai3 liu4 shi2 qi1 dian2 wu3 gong1 li3`

**修复前实际：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 m4 di4 di4 yi4 bai3 liu4 shi2 qi1 dian2 wu3 gong1 li3`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

#### 055. v3-parity-polyphone-surname-proper-014

**原文：** 单于姓单，单独处理时不能读错，第 15 轮。

**TN：** 单于姓单,单独处理时不能读错,第 十五 轮。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 yi1 wu3 lun2`

**修复前实际：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 shi2 wu3 lun2`

**处理：** 修订数词拼音标注，保留当前 TN。

#### 056. v3-parity-polyphone-surname-proper-026

**原文：** 单于姓单，单独处理时不能读错，第 27 轮。

**TN：** 单于姓单,单独处理时不能读错,第 二十七 轮。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 er4 qi1 lun2`

**修复前实际：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 er4 shi2 qi1 lun2`

**处理：** 修订数词拼音标注，保留当前 TN。

#### 057. v3-parity-polyphone-surname-proper-038

**原文：** 单于姓单，单独处理时不能读错，第 39 轮。

**TN：** 单于姓单,单独处理时不能读错,第 三十九 轮。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 san1 jiu3 lun2`

**修复前实际：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 san1 shi2 jiu3 lun2`

**处理：** 修订数词拼音标注，保留当前 TN。

#### 058. v3-parity-polyphone-surname-proper-050

**原文：** 单于姓单，单独处理时不能读错，第 51 轮。

**TN：** 单于姓单,单独处理时不能读错,第 五十一 轮。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 wu3 yi1 lun2`

**修复前实际：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 wu3 shi2 yi1 lun2`

**处理：** 修订数词拼音标注，保留当前 TN。

#### 059. v3-parity-polyphone-surname-proper-062

**原文：** 单于姓单，单独处理时不能读错，第 63 轮。

**TN：** 单于姓单,单独处理时不能读错,第 六十三 轮。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 liu4 san1 lun2`

**修复前实际：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 liu4 shi2 san1 lun2`

**处理：** 修订数词拼音标注，保留当前 TN。

#### 060. v3-parity-polyphone-surname-proper-074

**原文：** 单于姓单，单独处理时不能读错，第 75 轮。

**TN：** 单于姓单,单独处理时不能读错,第 七十五 轮。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 qi1 wu3 lun2`

**修复前实际：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 qi1 shi2 wu3 lun2`

**处理：** 修订数词拼音标注，保留当前 TN。

#### 061. v3-parity-polyphone-surname-proper-086

**原文：** 单于姓单，单独处理时不能读错，第 87 轮。

**TN：** 单于姓单,单独处理时不能读错,第 八十七 轮。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 ba1 qi1 lun2`

**修复前实际：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 ba1 shi2 qi1 lun2`

**处理：** 修订数词拼音标注，保留当前 TN。

#### 062. v3-parity-polyphone-surname-proper-098

**原文：** 单于姓单，单独处理时不能读错，第 99 轮。

**TN：** 单于姓单,单独处理时不能读错,第 九十九 轮。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 jiu2 jiu3 lun2`

**修复前实际：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 jiu3 shi2 jiu3 lun2`

**处理：** 修订数词拼音标注，保留当前 TN。

#### 063. v3-parity-polyphone-surname-proper-099

**原文：** 区老师住在区庄附近，第 100 轮。

**TN：** 区老师住在区庄附近,第 一百 轮。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `ou1 lao3 shi1 zhu4 zai4 ou1 zhuang1 fu4 jin4 di4 yi1 bai3 lun2`

**修复前实际：** `ou1 lao3 shi1 zhu4 zai4 ou1 zhuang1 fu4 jin4 di4 yi4 bai3 lun2`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `ou1 lao3 shi1 zhu4 zai4 ou1 zhuang1 fu4 jin4 di4 yi1 bai3 lun2`

**仍匹配原始标注：** 是

#### 064. v3-parity-polyphone-surname-proper-100

**原文：** 曾参和曾老师都在名单里，第 101 轮。

**TN：** 曾参和曾老师都在名单里,第 一百零一 轮。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `zeng1 shen1 he2 zeng1 lao3 shi1 dou1 zai4 ming2 dan1 li3 di4 yi1 bai3 ling2 yi1 lun2`

**修复前实际：** `zeng1 shen1 he2 zeng1 lao3 shi1 dou1 zai4 ming2 dan1 li3 di4 yi4 bai3 ling2 yi1 lun2`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `zeng1 shen1 he2 zeng1 lao3 shi1 dou1 zai4 ming2 dan1 li3 di4 yi1 bai3 ling2 yi1 lun2`

**仍匹配原始标注：** 是

#### 065. v3-parity-polyphone-surname-proper-101

**原文：** 解经理正在解释合同，第 102 轮。

**TN：** 解经理正在解释合同,第 一百零二 轮。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `xie4 jing1 li3 zheng4 zai4 jie3 shi4 he2 tong5 di4 yi1 bai3 ling2 er4 lun2`

**修复前实际：** `xie4 jing1 li3 zheng4 zai4 jie3 shi4 he2 tong5 di4 yi4 bai3 ling2 er4 lun2`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `xie4 jing1 li3 zheng4 zai4 jie3 shi4 he2 tong5 di4 yi1 bai3 ling2 er4 lun2`

**仍匹配原始标注：** 是

#### 066. v3-parity-polyphone-surname-proper-102

**原文：** 音乐响起以后，乐队开始排练，第 103 轮。

**TN：** 音乐响起以后,乐队开始排练,第 一百零三 轮。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `yin1 yue4 xiang2 qi2 yi3 hou4 yue4 dui4 kai1 shi3 pai2 lian4 di4 yi1 bai3 ling2 san1 lun2`

**修复前实际：** `yin1 yue4 xiang2 qi2 yi3 hou4 yue4 dui4 kai1 shi3 pai2 lian4 di4 yi4 bai3 ling2 san1 lun2`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `yin1 yue4 xiang2 qi2 yi3 hou4 yue4 dui4 kai1 shi3 pai2 lian4 di4 yi1 bai3 ling2 san1 lun2`

**仍匹配原始标注：** 是

#### 067. v3-parity-polyphone-surname-proper-103

**原文：** 长大以后要去长安旅行，第 104 轮。

**TN：** 长大以后要去长安旅行,第 一百零四 轮。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `zhang3 da4 yi3 hou4 yao4 qu4 chang2 an1 lv3 xing2 di4 yi1 bai3 ling2 si4 lun2`

**修复前实际：** `zhang3 da4 yi3 hou4 yao4 qu4 chang2 an1 lv3 xing2 di4 yi4 bai3 ling2 si4 lun2`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `zhang3 da4 yi3 hou4 yao4 qu4 chang2 an1 lv3 xing2 di4 yi1 bai3 ling2 si4 lun2`

**仍匹配原始标注：** 是

#### 068. v3-parity-polyphone-surname-proper-104

**原文：** 薄荷味很淡，薄书记也在现场，第 105 轮。

**TN：** 薄荷味很淡,薄书记也在现场,第 一百零五 轮。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `bo4 he5 wei4 hen3 dan4 bo2 shu1 ji4 ye3 zai4 xian4 chang3 di4 yi1 bai3 ling2 wu3 lun2`

**修复前实际：** `bo4 he5 wei4 hen3 dan4 bo2 shu1 ji4 ye3 zai4 xian4 chang3 di4 yi4 bai3 ling2 wu3 lun2`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `bo4 he5 wei4 hen3 dan4 bo2 shu1 ji4 ye3 zai4 xian4 chang3 di4 yi1 bai3 ling2 wu3 lun2`

**仍匹配原始标注：** 是

#### 069. v3-parity-polyphone-surname-proper-105

**原文：** 任先生负责本次任务，第 106 轮。

**TN：** 任先生负责本次任务,第 一百零六 轮。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `ren2 xian1 sheng1 fu4 ze2 ben3 ci4 ren4 wu4 di4 yi1 bai3 ling2 liu4 lun2`

**修复前实际：** `ren2 xian1 sheng1 fu4 ze2 ben3 ci4 ren4 wu4 di4 yi4 bai3 ling2 liu4 lun2`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `ren2 xian1 sheng1 fu4 ze2 ben3 ci4 ren4 wu4 di4 yi1 bai3 ling2 liu4 lun2`

**仍匹配原始标注：** 是

#### 070. v3-parity-polyphone-surname-proper-106

**原文：** 朴老师介绍朴素的设计，第 107 轮。

**TN：** 朴老师介绍朴素的设计,第 一百零七 轮。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `piao2 lao3 shi1 jie4 shao4 pu3 su4 de5 she4 ji4 di4 yi1 bai3 ling2 qi1 lun2`

**修复前实际：** `piao2 lao3 shi1 jie4 shao4 pu3 su4 de5 she4 ji4 di4 yi4 bai3 ling2 qi1 lun2`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `piao2 lao3 shi1 jie4 shao4 pu3 su4 de5 she4 ji4 di4 yi1 bai3 ling2 qi1 lun2`

**仍匹配原始标注：** 是

#### 071. v3-parity-polyphone-surname-proper-107

**原文：** 秘鲁客户咨询秘书安排，第 108 轮。

**TN：** 秘鲁客户咨询秘书安排,第 一百零八 轮。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `bi4 lu3 ke4 hu4 zi1 xun2 mi4 shu1 an1 pai2 di4 yi1 bai3 ling2 ba1 lun2`

**修复前实际：** `bi4 lu3 ke4 hu4 zi1 xun2 mi4 shu1 an1 pai2 di4 yi4 bai3 ling2 ba1 lun2`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `bi4 lu3 ke4 hu4 zi1 xun2 mi4 shu1 an1 pai2 di4 yi1 bai3 ling2 ba1 lun2`

**仍匹配原始标注：** 是

#### 072. v3-parity-polyphone-surname-proper-108

**原文：** 重庆火锅很好吃，重量也很足，第 109 轮。

**TN：** 重庆火锅很好吃,重量也很足,第 一百零九 轮。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `chong2 qing4 huo3 guo1 hen2 hao3 chi1 zhong4 liang4 ye2 hen3 zu2 di4 yi1 bai3 ling2 jiu3 lun2`

**修复前实际：** `chong2 qing4 huo3 guo1 hen2 hao3 chi1 zhong4 liang4 ye2 hen3 zu2 di4 yi4 bai3 ling2 jiu3 lun2`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `chong2 qing4 huo3 guo1 hen2 hao3 chi1 zhong4 liang4 ye2 hen3 zu2 di4 yi1 bai3 ling2 jiu3 lun2`

**仍匹配原始标注：** 是

#### 073. v3-parity-polyphone-surname-proper-109

**原文：** 银行行长正在整理行程，第 110 轮。

**TN：** 银行行长正在整理行程,第 一百一十 轮。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `yin2 hang2 hang2 zhang3 zheng4 zai4 zheng2 li3 xing2 cheng2 di4 yi1 bai3 yi1 shi2 lun2`

**修复前实际：** `yin2 hang2 hang2 zhang3 zheng4 zai4 zheng2 li3 xing2 cheng2 di4 yi4 bai3 yi4 shi2 lun2`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `yin2 hang2 hang2 zhang3 zheng4 zai4 zheng2 li3 xing2 cheng2 di4 yi1 bai3 yi1 shi2 lun2`

**仍匹配原始标注：** 是

#### 074. v3-parity-tn-numeric-date-money-unit-000

**原文：** 编号 1 的房间是 204，温度 -24.5 度。

**TN：** 编号 一 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 yi1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 yi1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

#### 075. v3-parity-tn-numeric-date-money-unit-012

**原文：** 编号 13 的房间是 204，温度 -24.5 度。

**TN：** 编号 十三 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 shi2 san1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 shi2 san1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

#### 076. v3-parity-tn-numeric-date-money-unit-024

**原文：** 编号 25 的房间是 204，温度 -24.5 度。

**TN：** 编号 二十五 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 er4 shi2 wu3 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 er4 shi2 wu3 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

#### 077. v3-parity-tn-numeric-date-money-unit-036

**原文：** 编号 37 的房间是 204，温度 -24.5 度。

**TN：** 编号 三十七 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 san1 shi2 qi1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 san1 shi2 qi1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

#### 078. v3-parity-tn-numeric-date-money-unit-048

**原文：** 编号 49 的房间是 204，温度 -24.5 度。

**TN：** 编号 四十九 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 si4 shi2 jiu3 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 si4 shi2 jiu3 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

#### 079. v3-parity-tn-numeric-date-money-unit-060

**原文：** 编号 61 的房间是 204，温度 -24.5 度。

**TN：** 编号 六十一 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 liu4 shi2 yi1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 liu4 shi2 yi1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

#### 080. v3-parity-tn-numeric-date-money-unit-072

**原文：** 编号 73 的房间是 204，温度 -24.5 度。

**TN：** 编号 七十三 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 qi1 shi2 san1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 qi1 shi2 san1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

#### 081. v3-parity-tn-numeric-date-money-unit-084

**原文：** 编号 85 的房间是 204，温度 -24.5 度。

**TN：** 编号 八十五 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 ba1 shi2 wu3 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 ba1 shi2 wu3 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

#### 082. v3-parity-tn-numeric-date-money-unit-096

**原文：** 编号 97 的房间是 204，温度 -24.5 度。

**TN：** 编号 九十七 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 jiu3 shi2 qi1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 jiu3 shi2 qi1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

#### 083. v3-parity-tn-numeric-date-money-unit-108

**原文：** 编号 109 的房间是 204，温度 -24.5 度。

**TN：** 编号 一百零九 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 yi1 bai3 ling2 jiu3 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 yi4 bai3 ling2 jiu3 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

#### 084. v3-parity-tn-numeric-date-money-unit-120

**原文：** 编号 121 的房间是 204，温度 -24.5 度。

**TN：** 编号 一百二十一 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 yi1 bai3 er4 shi2 yi1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 yi4 bai3 er4 shi2 yi1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

#### 085. v3-parity-tn-numeric-date-money-unit-132

**原文：** 编号 133 的房间是 204，温度 -24.5 度。

**TN：** 编号 一百三十三 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 yi1 bai3 san1 shi2 san1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 yi4 bai3 san1 shi2 san1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

#### 086. v3-parity-tn-numeric-date-money-unit-144

**原文：** 编号 145 的房间是 204，温度 -24.5 度。

**TN：** 编号 一百四十五 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 yi1 bai3 si4 shi2 wu3 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 yi4 bai3 si4 shi2 wu3 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

#### 087. v3-parity-tn-numeric-date-money-unit-156

**原文：** 编号 157 的房间是 204，温度 -24.5 度。

**TN：** 编号 一百五十七 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 yi1 bai2 wu3 shi2 qi1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 yi4 bai2 wu3 shi2 qi1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

#### 088. v3-parity-tn-numeric-date-money-unit-168

**原文：** 编号 169 的房间是 204，温度 -24.5 度。

**TN：** 编号 一百六十九 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 yi1 bai3 liu4 shi2 jiu3 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 yi4 bai3 liu4 shi2 jiu3 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

#### 089. v3-parity-tn-numeric-date-money-unit-001

**原文：** 今天是 2026 年 7 月 2 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 二 日,下午 三点零五分 开会。

**判断：读法／标注口径差异。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 er4 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 er4 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

#### 090. v3-parity-tn-numeric-date-money-unit-013

**原文：** 今天是 2026 年 7 月 14 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 十四 日,下午 三点零五分 开会。

**判断：读法／标注口径差异。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 shi2 si4 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 shi2 si4 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

#### 091. v3-parity-tn-numeric-date-money-unit-025

**原文：** 今天是 2026 年 7 月 26 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 二十六 日,下午 三点零五分 开会。

**判断：读法／标注口径差异。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 er4 shi2 liu4 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 er4 shi2 liu4 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

#### 092. v3-parity-tn-numeric-date-money-unit-037

**原文：** 今天是 2026 年 7 月 38 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 三十八 日,下午 三点零五分 开会。

**判断：语料内容无效或自相矛盾。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**附加问题：** 原文为 7 月 38 日，不是有效日期；不把这些输入当正常日期发音验收。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 san1 shi2 ba1 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 san1 shi2 ba1 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

#### 093. v3-parity-tn-numeric-date-money-unit-049

**原文：** 今天是 2026 年 7 月 50 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 五十 日,下午 三点零五分 开会。

**判断：语料内容无效或自相矛盾。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**附加问题：** 原文为 7 月 50 日，不是有效日期；不把这些输入当正常日期发音验收。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 wu3 shi2 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 wu3 shi2 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

#### 094. v3-parity-tn-numeric-date-money-unit-061

**原文：** 今天是 2026 年 7 月 62 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 六十二 日,下午 三点零五分 开会。

**判断：语料内容无效或自相矛盾。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**附加问题：** 原文为 7 月 62 日，不是有效日期；不把这些输入当正常日期发音验收。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 liu4 shi2 er4 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 liu4 shi2 er4 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

#### 095. v3-parity-tn-numeric-date-money-unit-073

**原文：** 今天是 2026 年 7 月 74 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 七十四 日,下午 三点零五分 开会。

**判断：语料内容无效或自相矛盾。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**附加问题：** 原文为 7 月 74 日，不是有效日期；不把这些输入当正常日期发音验收。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 qi1 shi2 si4 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 qi1 shi2 si4 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

#### 096. v3-parity-tn-numeric-date-money-unit-085

**原文：** 今天是 2026 年 7 月 86 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 八十六 日,下午 三点零五分 开会。

**判断：语料内容无效或自相矛盾。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**附加问题：** 原文为 7 月 86 日，不是有效日期；不把这些输入当正常日期发音验收。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 ba1 shi2 liu4 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 ba1 shi2 liu4 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

#### 097. v3-parity-tn-numeric-date-money-unit-097

**原文：** 今天是 2026 年 7 月 98 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 九十八 日,下午 三点零五分 开会。

**判断：语料内容无效或自相矛盾。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**附加问题：** 原文为 7 月 98 日，不是有效日期；不把这些输入当正常日期发音验收。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 jiu3 shi2 ba1 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 jiu3 shi2 ba1 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

#### 098. v3-parity-tn-numeric-date-money-unit-109

**原文：** 今天是 2026 年 7 月 110 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 一百一十 日,下午 三点零五分 开会。

**判断：语料内容无效或自相矛盾。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**附加问题：** 原文为 7 月 110 日，不是有效日期；不把这些输入当正常日期发音验收。；旧标注还把 110 写成一百十，漏了一；应为一百一十。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 yi1 bai3 shi2 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 yi4 bai3 yi4 shi2 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

#### 099. v3-parity-tn-numeric-date-money-unit-121

**原文：** 今天是 2026 年 7 月 122 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 一百二十二 日,下午 三点零五分 开会。

**判断：语料内容无效或自相矛盾。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**附加问题：** 原文为 7 月 122 日，不是有效日期；不把这些输入当正常日期发音验收。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 yi1 bai3 er4 shi2 er4 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 yi4 bai3 er4 shi2 er4 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

#### 100. v3-parity-tn-numeric-date-money-unit-133

**原文：** 今天是 2026 年 7 月 134 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 一百三十四 日,下午 三点零五分 开会。

**判断：语料内容无效或自相矛盾。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**附加问题：** 原文为 7 月 134 日，不是有效日期；不把这些输入当正常日期发音验收。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 yi1 bai3 san1 shi2 si4 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 yi4 bai3 san1 shi2 si4 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

#### 101. v3-parity-tn-numeric-date-money-unit-145

**原文：** 今天是 2026 年 7 月 146 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 一百四十六 日,下午 三点零五分 开会。

**判断：语料内容无效或自相矛盾。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**附加问题：** 原文为 7 月 146 日，不是有效日期；不把这些输入当正常日期发音验收。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 yi1 bai3 si4 shi2 liu4 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 yi4 bai3 si4 shi2 liu4 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

#### 102. v3-parity-tn-numeric-date-money-unit-157

**原文：** 今天是 2026 年 7 月 158 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 一百五十八 日,下午 三点零五分 开会。

**判断：语料内容无效或自相矛盾。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**附加问题：** 原文为 7 月 158 日，不是有效日期；不把这些输入当正常日期发音验收。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 yi1 bai2 wu3 shi2 ba1 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 yi4 bai2 wu3 shi2 ba1 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

#### 103. v3-parity-tn-numeric-date-money-unit-169

**原文：** 今天是 2026 年 7 月 170 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 一百七十 日,下午 三点零五分 开会。

**判断：语料内容无效或自相矛盾。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**附加问题：** 原文为 7 月 170 日，不是有效日期；不把这些输入当正常日期发音验收。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 yi1 bai3 qi1 shi2 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 yi4 bai3 qi1 shi2 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

#### 104. v3-parity-tn-numeric-date-money-unit-005

**原文：** 路径 /sdcard/test/6/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠六,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 liu4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 liu4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

#### 105. v3-parity-tn-numeric-date-money-unit-017

**原文：** 路径 /sdcard/test/18/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠一八,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 yi1 ba1 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 yi1 ba1 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

#### 106. v3-parity-tn-numeric-date-money-unit-029

**原文：** 路径 /sdcard/test/30/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠三零,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 san1 ling2 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 san1 ling2 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

#### 107. v3-parity-tn-numeric-date-money-unit-041

**原文：** 路径 /sdcard/test/42/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠四二,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 si4 er4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 si4 er4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

#### 108. v3-parity-tn-numeric-date-money-unit-053

**原文：** 路径 /sdcard/test/54/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠五四,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 wu3 si4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 wu3 si4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

#### 109. v3-parity-tn-numeric-date-money-unit-065

**原文：** 路径 /sdcard/test/66/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠六六,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 liu4 liu4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 liu4 liu4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

#### 110. v3-parity-tn-numeric-date-money-unit-077

**原文：** 路径 /sdcard/test/78/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠七八,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 qi1 ba1 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 qi1 ba1 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

#### 111. v3-parity-tn-numeric-date-money-unit-089

**原文：** 路径 /sdcard/test/90/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠九零,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 jiu3 ling2 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 jiu3 ling2 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

#### 112. v3-parity-tn-numeric-date-money-unit-101

**原文：** 路径 /sdcard/test/102/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠一零二,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 yi1 ling2 er4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 yi1 ling2 er4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

#### 113. v3-parity-tn-numeric-date-money-unit-113

**原文：** 路径 /sdcard/test/114/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠一一四,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 yi1 yi1 si4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 yi1 yi1 si4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

#### 114. v3-parity-tn-numeric-date-money-unit-125

**原文：** 路径 /sdcard/test/126/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠一二六,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 yi1 er4 liu4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 yi1 er4 liu4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

#### 115. v3-parity-tn-numeric-date-money-unit-137

**原文：** 路径 /sdcard/test/138/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠一三八,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 yi1 san1 ba1 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 yi1 san1 ba1 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

#### 116. v3-parity-tn-numeric-date-money-unit-149

**原文：** 路径 /sdcard/test/150/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠一五零,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 yi1 wu3 ling2 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 yi1 wu3 ling2 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

#### 117. v3-parity-tn-numeric-date-money-unit-161

**原文：** 路径 /sdcard/test/162/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠一六二,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 yi1 liu4 er4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 yi1 liu4 er4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

#### 118. v3-parity-tn-numeric-date-money-unit-011

**原文：** 坐标 N22.12 E113.11，导航继续。

**TN：** 坐标 北纬二十二点一二 东经一百一十三点一一,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 er4 dong1 jing1 yi1 bai3 shi2 san1 dian3 yi1 yi1 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 er4 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 yi1 yi1 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

#### 119. v3-parity-tn-numeric-date-money-unit-023

**原文：** 坐标 N22.24 E113.23，导航继续。

**TN：** 坐标 北纬二十二点二四 东经一百一十三点二三,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 er4 si4 dong1 jing1 yi1 bai3 shi2 san1 dian3 er4 san1 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 er4 si4 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 er4 san1 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

#### 120. v3-parity-tn-numeric-date-money-unit-035

**原文：** 坐标 N22.36 E113.35，导航继续。

**TN：** 坐标 北纬二十二点三六 东经一百一十三点三五,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**附加问题：** 旧标注还跨逗号把末位三声音节与导航的导做变调；当前在逗号停止连读，保留末位三声。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 san1 liu4 dong1 jing1 yi1 bai3 shi2 san1 dian3 san1 wu2 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 san1 liu4 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 san1 wu3 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

#### 121. v3-parity-tn-numeric-date-money-unit-047

**原文：** 坐标 N22.48 E113.47，导航继续。

**TN：** 坐标 北纬二十二点四八 东经一百一十三点四七,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 si4 ba1 dong1 jing1 yi1 bai3 shi2 san1 dian3 si4 qi1 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 si4 ba1 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 si4 qi1 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

#### 122. v3-parity-tn-numeric-date-money-unit-059

**原文：** 坐标 N22.60 E113.59，导航继续。

**TN：** 坐标 北纬二十二点六零 东经一百一十三点五九,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**附加问题：** 旧标注还跨逗号把末位三声音节与导航的导做变调；当前在逗号停止连读，保留末位三声。；点五九／点九五的三声组合另有分组差异：A+BC 与 AB+C 不能一律要求同一个表层调串。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 liu4 ling2 dong1 jing1 yi1 bai3 shi2 san1 dian2 wu2 jiu2 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 liu4 ling2 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 wu2 jiu3 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

#### 123. v3-parity-tn-numeric-date-money-unit-071

**原文：** 坐标 N22.72 E113.71，导航继续。

**TN：** 坐标 北纬二十二点七二 东经一百一十三点七一,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 qi1 er4 dong1 jing1 yi1 bai3 shi2 san1 dian3 qi1 yi1 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 qi1 er4 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 qi1 yi1 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

#### 124. v3-parity-tn-numeric-date-money-unit-083

**原文：** 坐标 N22.84 E113.83，导航继续。

**TN：** 坐标 北纬二十二点八四 东经一百一十三点八三,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 ba1 si4 dong1 jing1 yi1 bai3 shi2 san1 dian3 ba1 san1 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 ba1 si4 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 ba1 san1 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

#### 125. v3-parity-tn-numeric-date-money-unit-095

**原文：** 坐标 N22.96 E113.95，导航继续。

**TN：** 坐标 北纬二十二点九六 东经一百一十三点九五,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**附加问题：** 旧标注还跨逗号把末位三声音节与导航的导做变调；当前在逗号停止连读，保留末位三声。；点五九／点九五的三声组合另有分组差异：A+BC 与 AB+C 不能一律要求同一个表层调串。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian2 jiu3 liu4 dong1 jing1 yi1 bai3 shi2 san1 dian2 jiu2 wu2 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian2 jiu3 liu4 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 jiu2 wu3 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

#### 126. v3-parity-tn-numeric-date-money-unit-107

**原文：** 坐标 N22.108 E113.107，导航继续。

**TN：** 坐标 北纬二十二点一零八 东经一百一十三点一零七,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 ling2 ba1 dong1 jing1 yi1 bai3 shi2 san1 dian3 yi1 ling2 qi1 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 ling2 ba1 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 yi1 ling2 qi1 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

#### 127. v3-parity-tn-numeric-date-money-unit-119

**原文：** 坐标 N22.120 E113.119，导航继续。

**TN：** 坐标 北纬二十二点一二零 东经一百一十三点一一九,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**附加问题：** 旧标注还跨逗号把末位三声音节与导航的导做变调；当前在逗号停止连读，保留末位三声。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 er4 ling2 dong1 jing1 yi1 bai3 shi2 san1 dian3 yi1 yi1 jiu2 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 er4 ling2 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 yi1 yi1 jiu3 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

#### 128. v3-parity-tn-numeric-date-money-unit-131

**原文：** 坐标 N22.132 E113.131，导航继续。

**TN：** 坐标 北纬二十二点一三二 东经一百一十三点一三一,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 san1 er4 dong1 jing1 yi1 bai3 shi2 san1 dian3 yi1 san1 yi1 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 san1 er4 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 yi1 san1 yi1 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

#### 129. v3-parity-tn-numeric-date-money-unit-143

**原文：** 坐标 N22.144 E113.143，导航继续。

**TN：** 坐标 北纬二十二点一四四 东经一百一十三点一四三,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 si4 si4 dong1 jing1 yi1 bai3 shi2 san1 dian3 yi1 si4 san1 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 si4 si4 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 yi1 si4 san1 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

#### 130. v3-parity-tn-numeric-date-money-unit-155

**原文：** 坐标 N22.156 E113.155，导航继续。

**TN：** 坐标 北纬二十二点一五六 东经一百一十三点一五五,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**附加问题：** 旧标注还跨逗号把末位三声音节与导航的导做变调；当前在逗号停止连读，保留末位三声。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 wu3 liu4 dong1 jing1 yi1 bai3 shi2 san1 dian3 yi1 wu2 wu2 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 wu3 liu4 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 yi1 wu2 wu3 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

#### 131. v3-parity-tn-numeric-date-money-unit-167

**原文：** 坐标 N22.168 E113.167，导航继续。

**TN：** 坐标 北纬二十二点一六八 东经一百一十三点一六七,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 liu4 ba1 dong1 jing1 yi1 bai3 shi2 san1 dian3 yi1 liu4 qi1 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 liu4 ba1 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 yi1 liu4 qi1 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

#### 132. v3-parity-frontend-rules-technical-003

**原文：** 命令 adb shell am start -n demo/4 不应读乱。

**TN：** 命令 adb shell am start 杠n demo斜杠四 不应读乱。

**判断：读法／标注口径差异。** 这里的 am 是 adb shell 的命令名，不是 I am 中的英语动词。拼读 A M 可以准确传达命令；旧标注把它读成英语单词 am，只能作为另一种读法选择。

**标注：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L AE1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 si4 bu4 ying1 du2 luan4`

**修复前实际：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L EY1 EH1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 si4 bu4 ying1 du2 luan4`

**处理：** 保留命令上下文的字母读法；若扩充候选，只针对这些命令样例，不影响普通英语。

#### 133. v3-parity-frontend-rules-technical-013

**原文：** 命令 adb shell am start -n demo/14 不应读乱。

**TN：** 命令 adb shell am start 杠n demo斜杠一四 不应读乱。

**判断：读法／标注口径差异。** 这里的 am 是 adb shell 的命令名，不是 I am 中的英语动词。拼读 A M 可以准确传达命令；旧标注把它读成英语单词 am，只能作为另一种读法选择。

**标注：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L AE1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 yi1 si4 bu4 ying1 du2 luan4`

**修复前实际：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L EY1 EH1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 yi1 si4 bu4 ying1 du2 luan4`

**处理：** 保留命令上下文的字母读法；若扩充候选，只针对这些命令样例，不影响普通英语。

#### 134. v3-parity-frontend-rules-technical-023

**原文：** 命令 adb shell am start -n demo/24 不应读乱。

**TN：** 命令 adb shell am start 杠n demo斜杠二四 不应读乱。

**判断：读法／标注口径差异。** 这里的 am 是 adb shell 的命令名，不是 I am 中的英语动词。拼读 A M 可以准确传达命令；旧标注把它读成英语单词 am，只能作为另一种读法选择。

**标注：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L AE1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 er4 si4 bu4 ying1 du2 luan4`

**修复前实际：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L EY1 EH1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 er4 si4 bu4 ying1 du2 luan4`

**处理：** 保留命令上下文的字母读法；若扩充候选，只针对这些命令样例，不影响普通英语。

#### 135. v3-parity-frontend-rules-technical-033

**原文：** 命令 adb shell am start -n demo/34 不应读乱。

**TN：** 命令 adb shell am start 杠n demo斜杠三四 不应读乱。

**判断：读法／标注口径差异。** 这里的 am 是 adb shell 的命令名，不是 I am 中的英语动词。拼读 A M 可以准确传达命令；旧标注把它读成英语单词 am，只能作为另一种读法选择。

**标注：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L AE1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 san1 si4 bu4 ying1 du2 luan4`

**修复前实际：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L EY1 EH1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 san1 si4 bu4 ying1 du2 luan4`

**处理：** 保留命令上下文的字母读法；若扩充候选，只针对这些命令样例，不影响普通英语。

#### 136. v3-parity-frontend-rules-technical-043

**原文：** 命令 adb shell am start -n demo/44 不应读乱。

**TN：** 命令 adb shell am start 杠n demo斜杠四四 不应读乱。

**判断：读法／标注口径差异。** 这里的 am 是 adb shell 的命令名，不是 I am 中的英语动词。拼读 A M 可以准确传达命令；旧标注把它读成英语单词 am，只能作为另一种读法选择。

**标注：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L AE1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 si4 si4 bu4 ying1 du2 luan4`

**修复前实际：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L EY1 EH1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 si4 si4 bu4 ying1 du2 luan4`

**处理：** 保留命令上下文的字母读法；若扩充候选，只针对这些命令样例，不影响普通英语。

#### 137. v3-parity-frontend-rules-technical-053

**原文：** 命令 adb shell am start -n demo/54 不应读乱。

**TN：** 命令 adb shell am start 杠n demo斜杠五四 不应读乱。

**判断：读法／标注口径差异。** 这里的 am 是 adb shell 的命令名，不是 I am 中的英语动词。拼读 A M 可以准确传达命令；旧标注把它读成英语单词 am，只能作为另一种读法选择。

**标注：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L AE1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 wu3 si4 bu4 ying1 du2 luan4`

**修复前实际：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L EY1 EH1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 wu3 si4 bu4 ying1 du2 luan4`

**处理：** 保留命令上下文的字母读法；若扩充候选，只针对这些命令样例，不影响普通英语。

#### 138. v3-parity-frontend-rules-technical-063

**原文：** 命令 adb shell am start -n demo/64 不应读乱。

**TN：** 命令 adb shell am start 杠n demo斜杠六四 不应读乱。

**判断：读法／标注口径差异。** 这里的 am 是 adb shell 的命令名，不是 I am 中的英语动词。拼读 A M 可以准确传达命令；旧标注把它读成英语单词 am，只能作为另一种读法选择。

**标注：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L AE1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 liu4 si4 bu4 ying1 du2 luan4`

**修复前实际：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L EY1 EH1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 liu4 si4 bu4 ying1 du2 luan4`

**处理：** 保留命令上下文的字母读法；若扩充候选，只针对这些命令样例，不影响普通英语。

#### 139. v3-parity-frontend-rules-technical-073

**原文：** 命令 adb shell am start -n demo/74 不应读乱。

**TN：** 命令 adb shell am start 杠n demo斜杠七四 不应读乱。

**判断：读法／标注口径差异。** 这里的 am 是 adb shell 的命令名，不是 I am 中的英语动词。拼读 A M 可以准确传达命令；旧标注把它读成英语单词 am，只能作为另一种读法选择。

**标注：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L AE1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 qi1 si4 bu4 ying1 du2 luan4`

**修复前实际：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L EY1 EH1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 qi1 si4 bu4 ying1 du2 luan4`

**处理：** 保留命令上下文的字母读法；若扩充候选，只针对这些命令样例，不影响普通英语。

#### 140. v3-parity-frontend-rules-technical-083

**原文：** 命令 adb shell am start -n demo/84 不应读乱。

**TN：** 命令 adb shell am start 杠n demo斜杠八四 不应读乱。

**判断：读法／标注口径差异。** 这里的 am 是 adb shell 的命令名，不是 I am 中的英语动词。拼读 A M 可以准确传达命令；旧标注把它读成英语单词 am，只能作为另一种读法选择。

**标注：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L AE1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 ba1 si4 bu4 ying1 du2 luan4`

**修复前实际：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L EY1 EH1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 ba1 si4 bu4 ying1 du2 luan4`

**处理：** 保留命令上下文的字母读法；若扩充候选，只针对这些命令样例，不影响普通英语。

#### 141. v3-parity-symbols-unicode-failsoft-003

**原文：** ＡＢＣ１２３ 已经转换完成，编号 4。

**TN：** ABC一二三 已经转换完成,编号 四。

**判断：读法／标注口径差异。** 全角 ABC123 已正确转为半角标识符。标识符中的 123 逐位读一二三合理；旧标注读一百二十三也能表达数字，但不能作为唯一强制读法。

**标注：** `EY1 B IY1 S IY1 yi1 bai3 er4 shi2 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 si4`

**修复前实际：** `EY1 B IY1 S IY1 yi1 er4 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 si4`

**处理：** 按标识符逐位读的现有规则保留；数量词与标识符分别验收。

#### 142. v3-parity-symbols-unicode-failsoft-013

**原文：** ＡＢＣ１２３ 已经转换完成，编号 14。

**TN：** ABC一二三 已经转换完成,编号 十四。

**判断：读法／标注口径差异。** 全角 ABC123 已正确转为半角标识符。标识符中的 123 逐位读一二三合理；旧标注读一百二十三也能表达数字，但不能作为唯一强制读法。

**标注：** `EY1 B IY1 S IY1 yi1 bai3 er4 shi2 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 shi2 si4`

**修复前实际：** `EY1 B IY1 S IY1 yi1 er4 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 shi2 si4`

**处理：** 按标识符逐位读的现有规则保留；数量词与标识符分别验收。

#### 143. v3-parity-symbols-unicode-failsoft-023

**原文：** ＡＢＣ１２３ 已经转换完成，编号 24。

**TN：** ABC一二三 已经转换完成,编号 二十四。

**判断：读法／标注口径差异。** 全角 ABC123 已正确转为半角标识符。标识符中的 123 逐位读一二三合理；旧标注读一百二十三也能表达数字，但不能作为唯一强制读法。

**标注：** `EY1 B IY1 S IY1 yi1 bai3 er4 shi2 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 er4 shi2 si4`

**修复前实际：** `EY1 B IY1 S IY1 yi1 er4 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 er4 shi2 si4`

**处理：** 按标识符逐位读的现有规则保留；数量词与标识符分别验收。

#### 144. v3-parity-symbols-unicode-failsoft-033

**原文：** ＡＢＣ１２３ 已经转换完成，编号 34。

**TN：** ABC一二三 已经转换完成,编号 三十四。

**判断：读法／标注口径差异。** 全角 ABC123 已正确转为半角标识符。标识符中的 123 逐位读一二三合理；旧标注读一百二十三也能表达数字，但不能作为唯一强制读法。

**标注：** `EY1 B IY1 S IY1 yi1 bai3 er4 shi2 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 san1 shi2 si4`

**修复前实际：** `EY1 B IY1 S IY1 yi1 er4 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 san1 shi2 si4`

**处理：** 按标识符逐位读的现有规则保留；数量词与标识符分别验收。

#### 145. v3-parity-symbols-unicode-failsoft-043

**原文：** ＡＢＣ１２３ 已经转换完成，编号 44。

**TN：** ABC一二三 已经转换完成,编号 四十四。

**判断：读法／标注口径差异。** 全角 ABC123 已正确转为半角标识符。标识符中的 123 逐位读一二三合理；旧标注读一百二十三也能表达数字，但不能作为唯一强制读法。

**标注：** `EY1 B IY1 S IY1 yi1 bai3 er4 shi2 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 si4 shi2 si4`

**修复前实际：** `EY1 B IY1 S IY1 yi1 er4 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 si4 shi2 si4`

**处理：** 按标识符逐位读的现有规则保留；数量词与标识符分别验收。

#### 146. v3-parity-symbols-unicode-failsoft-053

**原文：** ＡＢＣ１２３ 已经转换完成，编号 54。

**TN：** ABC一二三 已经转换完成,编号 五十四。

**判断：读法／标注口径差异。** 全角 ABC123 已正确转为半角标识符。标识符中的 123 逐位读一二三合理；旧标注读一百二十三也能表达数字，但不能作为唯一强制读法。

**标注：** `EY1 B IY1 S IY1 yi1 bai3 er4 shi2 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 wu3 shi2 si4`

**修复前实际：** `EY1 B IY1 S IY1 yi1 er4 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 wu3 shi2 si4`

**处理：** 按标识符逐位读的现有规则保留；数量词与标识符分别验收。

#### 147. v3-parity-symbols-unicode-failsoft-063

**原文：** ＡＢＣ１２３ 已经转换完成，编号 64。

**TN：** ABC一二三 已经转换完成,编号 六十四。

**判断：读法／标注口径差异。** 全角 ABC123 已正确转为半角标识符。标识符中的 123 逐位读一二三合理；旧标注读一百二十三也能表达数字，但不能作为唯一强制读法。

**标注：** `EY1 B IY1 S IY1 yi1 bai3 er4 shi2 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 liu4 shi2 si4`

**修复前实际：** `EY1 B IY1 S IY1 yi1 er4 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 liu4 shi2 si4`

**处理：** 按标识符逐位读的现有规则保留；数量词与标识符分别验收。

#### 148. v3-parity-symbols-unicode-failsoft-073

**原文：** ＡＢＣ１２３ 已经转换完成，编号 74。

**TN：** ABC一二三 已经转换完成,编号 七十四。

**判断：读法／标注口径差异。** 全角 ABC123 已正确转为半角标识符。标识符中的 123 逐位读一二三合理；旧标注读一百二十三也能表达数字，但不能作为唯一强制读法。

**标注：** `EY1 B IY1 S IY1 yi1 bai3 er4 shi2 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 qi1 shi2 si4`

**修复前实际：** `EY1 B IY1 S IY1 yi1 er4 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 qi1 shi2 si4`

**处理：** 按标识符逐位读的现有规则保留；数量词与标识符分别验收。

#### 149. v3-parity-symbols-unicode-failsoft-005

**原文：** 货币符号 ¥6.00、$6.99、€6 同时出现。

**TN：** 货币符号 六元、六点九九美元、六欧元 同时出现。

**判断：读法／标注口径差异。** 人民币金额 .00 可以省略，六元与六点零零元表达同一金额。美元金额的小数仍完整；点九九美中的多个三声有不同停连分组，不能把单个表层调串视为唯一答案。

**标注：** `huo4 bi4 fu2 hao4 liu4 dian3 ling2 ling2 yuan2 liu4 dian2 jiu2 jiu2 mei3 yuan2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**修复前实际：** `huo4 bi4 fu2 hao4 liu4 yuan2 liu4 dian3 jiu2 jiu2 mei3 yuan2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**处理：** 接受明确的等值金额读法；把金额内容正确性与自然连读韵律分开评价。

#### 150. v3-parity-symbols-unicode-failsoft-015

**原文：** 货币符号 ¥16.00、$16.99、€16 同时出现。

**TN：** 货币符号 十六元、十六点九九美元、十六欧元 同时出现。

**判断：读法／标注口径差异。** 人民币金额 .00 可以省略，六元与六点零零元表达同一金额。美元金额的小数仍完整；点九九美中的多个三声有不同停连分组，不能把单个表层调串视为唯一答案。

**标注：** `huo4 bi4 fu2 hao4 shi2 liu4 dian3 ling2 ling2 yuan2 shi2 liu4 dian2 jiu2 jiu2 mei3 yuan2 shi2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**修复前实际：** `huo4 bi4 fu2 hao4 shi2 liu4 yuan2 shi2 liu4 dian2 jiu2 jiu2 mei3 yuan2 shi2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**处理：** 接受明确的等值金额读法；把金额内容正确性与自然连读韵律分开评价。

#### 151. v3-parity-symbols-unicode-failsoft-025

**原文：** 货币符号 ¥26.00、$26.99、€26 同时出现。

**TN：** 货币符号 二十六元、二十六点九九美元、二十六欧元 同时出现。

**判断：读法／标注口径差异。** 人民币金额 .00 可以省略，六元与六点零零元表达同一金额。美元金额的小数仍完整；点九九美中的多个三声有不同停连分组，不能把单个表层调串视为唯一答案。

**标注：** `huo4 bi4 fu2 hao4 er4 shi2 liu4 dian3 ling2 ling2 yuan2 er4 shi2 liu4 dian2 jiu2 jiu2 mei3 yuan2 er4 shi2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**修复前实际：** `huo4 bi4 fu2 hao4 er4 shi2 liu4 yuan2 er4 shi2 liu4 dian3 jiu2 jiu2 mei3 yuan2 er4 shi2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**处理：** 接受明确的等值金额读法；把金额内容正确性与自然连读韵律分开评价。

#### 152. v3-parity-symbols-unicode-failsoft-035

**原文：** 货币符号 ¥36.00、$36.99、€36 同时出现。

**TN：** 货币符号 三十六元、三十六点九九美元、三十六欧元 同时出现。

**判断：读法／标注口径差异。** 人民币金额 .00 可以省略，六元与六点零零元表达同一金额。美元金额的小数仍完整；点九九美中的多个三声有不同停连分组，不能把单个表层调串视为唯一答案。

**标注：** `huo4 bi4 fu2 hao4 san1 shi2 liu4 dian3 ling2 ling2 yuan2 san1 shi2 liu4 dian2 jiu2 jiu2 mei3 yuan2 san1 shi2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**修复前实际：** `huo4 bi4 fu2 hao4 san1 shi2 liu4 yuan2 san1 shi2 liu4 dian3 jiu2 jiu2 mei3 yuan2 san1 shi2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**处理：** 接受明确的等值金额读法；把金额内容正确性与自然连读韵律分开评价。

#### 153. v3-parity-symbols-unicode-failsoft-045

**原文：** 货币符号 ¥46.00、$46.99、€46 同时出现。

**TN：** 货币符号 四十六元、四十六点九九美元、四十六欧元 同时出现。

**判断：读法／标注口径差异。** 人民币金额 .00 可以省略，六元与六点零零元表达同一金额。美元金额的小数仍完整；点九九美中的多个三声有不同停连分组，不能把单个表层调串视为唯一答案。

**标注：** `huo4 bi4 fu2 hao4 si4 shi2 liu4 dian3 ling2 ling2 yuan2 si4 shi2 liu4 dian2 jiu2 jiu2 mei3 yuan2 si4 shi2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**修复前实际：** `huo4 bi4 fu2 hao4 si4 shi2 liu4 yuan2 si4 shi2 liu4 dian3 jiu2 jiu2 mei3 yuan2 si4 shi2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**处理：** 接受明确的等值金额读法；把金额内容正确性与自然连读韵律分开评价。

#### 154. v3-parity-symbols-unicode-failsoft-055

**原文：** 货币符号 ¥56.00、$56.99、€56 同时出现。

**TN：** 货币符号 五十六元、五十六点九九美元、五十六欧元 同时出现。

**判断：读法／标注口径差异。** 人民币金额 .00 可以省略，六元与六点零零元表达同一金额。美元金额的小数仍完整；点九九美中的多个三声有不同停连分组，不能把单个表层调串视为唯一答案。

**标注：** `huo4 bi4 fu2 hao4 wu3 shi2 liu4 dian3 ling2 ling2 yuan2 wu3 shi2 liu4 dian2 jiu2 jiu2 mei3 yuan2 wu3 shi2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**修复前实际：** `huo4 bi4 fu2 hao4 wu3 shi2 liu4 yuan2 wu3 shi2 liu4 dian3 jiu2 jiu2 mei3 yuan2 wu3 shi2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**处理：** 接受明确的等值金额读法；把金额内容正确性与自然连读韵律分开评价。

#### 155. v3-parity-symbols-unicode-failsoft-065

**原文：** 货币符号 ¥66.00、$66.99、€66 同时出现。

**TN：** 货币符号 六十六元、六十六点九九美元、六十六欧元 同时出现。

**判断：读法／标注口径差异。** 人民币金额 .00 可以省略，六元与六点零零元表达同一金额。美元金额的小数仍完整；点九九美中的多个三声有不同停连分组，不能把单个表层调串视为唯一答案。

**标注：** `huo4 bi4 fu2 hao4 liu4 shi2 liu4 dian3 ling2 ling2 yuan2 liu4 shi2 liu4 dian2 jiu2 jiu2 mei3 yuan2 liu4 shi2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**修复前实际：** `huo4 bi4 fu2 hao4 liu4 shi2 liu4 yuan2 liu4 shi2 liu4 dian3 jiu2 jiu2 mei3 yuan2 liu4 shi2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**处理：** 接受明确的等值金额读法；把金额内容正确性与自然连读韵律分开评价。
