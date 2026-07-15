# AmphionRuntime Agent Instructions

## ASR 生命周期契约

- `isFinal=true` 表示一句话或一个 endpoint 的最终结果；`isLast=true` 只表示整个 session 的最后一条结果。不要把二者混用。
- 普通连续识别中，调用方执行 `finish(sessionId)` 之前不得出现 `isLast=true`。仅显式配置并命中 `vadBegin` 或 `maxAudioDuration` 时允许 SDK 自动结束。
- 每个正常结束的 session 必须恰好产生一次 `isLast=true`，之后恰好产生一次 `onComplete`；`cancel` 不得产生 final 或 complete。
- 每次自动结束都必须能归因到明确的终止条件。排查提前结束时，先记录 `finish` 调用、`vadBegin`、`maxAudioDuration`、写入 PCM 时长和完整回调时间线，不要先猜测模型问题。
- 初始起音属于多信号状态：VAD 或 ASR 的非空 text/token 任一确认语音后，必须永久解除本 session 的 `vadBegin`。声学 backstop 不能把“高于固定音量”直接等同于 speech：它只能先触发一次有界确认；持续活动还要满足语音型能量变化和过零率范围，才可解除计时，且不得伪造 speech 事件。
- 组合参数必须按能力的时间前置条件验收。启用声纹校验或 Speaker VAD 时，`vadBegin` 本身仍是纯静音等待；初始等待窗内存在连续但未决的声学活动时，才允许使用不超过 `TargetSpeakerConfig.minSegSec` 的一次性确认窗。旧活动不能在确认窗末直接解除计时：必须仍有近期语音型活动，或强制刷新 ASR 得到非空 text/token。测试必须分别验证纯静音、稳态高能非语音、零散脉冲和真实语音，不能只检查参数解析。
- 异步回调只能根据当前结果携带的 `isLast` 决定是否完成会话；不得用全局 `finishRequested` 推断某条较早结果是最后一条。
- `onStart` 是会话已经可用的承诺，不只是底层 native 构造完成通知。SDK 对外回调前必须已经发布 session 并完成会话级配置；调用方允许在 `onStart` 内同步执行 `writeAudio`、`finish` 或 `cancel`，不得收到 `NOT_LISTENING`。

## 声纹结果契约

- 公共字段名是 `speakerSimilarity`。新增或修改示例、文档和测试时必须使用该名称。
- `speakerSimilarity` 是可选值。有效语音短于 `TargetSpeakerConfig.minSegSec`（默认 1.5 秒）时不可靠，SDK 应省略分数并保留识别结果；不得填充假分数或通过补静音绕过门槛。
- 排查 `speakerSimilarity=undefined` 时，必须同时记录 `enableVoiceprintVerification`、`enableSpeakerVad`、`voiceprintIds` 数量、调用方传入和 SDK 生效后的 `vadBegin`、实际写入 PCM 时长以及该 final 的有效语音时长。缺少声纹开关或有效 ID 时不得归因为打分异常。
- 声纹测试至少覆盖：小于门槛、恰好门槛、超过门槛、低音量、前置静音、非注册语料源和多句连续输入。生命周期门禁只判断分数可选性、回调顺序和会话恢复；目标/非目标相似度精度另走带身份标注的评测集。

## 缺陷处理流程

1. 先把用户症状转成可失败的断言。测试必须能捕获“提前 `isLast`”本身，而不是只验证进程未崩溃或最终出现过 complete。
2. 在修复前运行最小复现并确认红灯；保存输入 PCM、启动参数、按时间排序的回调和终止原因。
3. 定位产生错误状态的最内层状态机，修复根因；不要在外层吞回调或延时掩盖竞态。
4. 同时检查 Harmony 与 Android 的同名生命周期逻辑，避免两端语义漂移。
5. 修复后依次运行状态机单测、SDK 单测、Harmony 编译和当前 USB 设备真实音频压力测试；最后清除临时 debug 日志。

## 必须保留的测试门禁

- 状态机单测：纯静音达到 `vadBegin` 只超时一次；边界帧中语音优先；ASR text/token 永久解除计时；低噪声、短脉冲和被静音隔开的变幅脉冲不误判；稳态高能非语音最多获得一次确认窗并最终超时；语音型变化信号不受调用方分帧影响；旧活动只能触发 probe，不能直接永久解除计时。同一 PCM 以单个大块或多个小块写入必须得到相同决定，deadline 之后的样本不得回看并改变 deadline 处的结果。
- 标准真机 session：记录调用 `finish` 前的 `isLast` 数量，要求为 0；结束后要求总数为 1。
- `max-duration`：达到上限后恰好一次 last/complete，迟到音频帧不产生额外回调，随后可以启动新 session。
- `cancel`、`start-cancel`、`start-write`、重复 `finish`、回调内重入、非法 session/frame 和 `NaN` 参数必须分别验证，不得合并成单一“edge passed”。`start-write` 必须在 `onStart` 调用栈内同步写入多帧真实 PCM 缓存，不能延迟到回调返回后；还要分别覆盖继续识别和回调内立即 `finish`。
- `vad-begin`：使用真实语音和纯静音分别测试。真实语音不得自动结束；纯静音必须按配置结束。
- 声纹与 `vadBegin` 必须组合测试 1000 ms 入参、实时/突发喂入、直接起音/前置静音；前置静音与源文件自身静音之和必须小于 1000 ms，否则自动结束是正确结果。显式 `finish` 前不得有 `isLast`，足够长的有效语音必须出现带分数的 final。另用纯静音/稳态高能非语音验证有界自动结束。参数上层改大只能作为规避，不能替代此门禁。
- 长稳压：按采样率、时长和音量分层抽样，不只取随机文件；报告 callback 契约、空 final、native stream、RSS 和线程变化。
- 测试报告必须保留 `report.json`、逐轮结果、内存采样、hilog 和输入映射。失败 artifact 不得被后续运行覆盖。

## SDK 真实调用方验收

- 产品验收对象是 SDK 公共 API 和回调契约；demo/HAP 只是 USB 真机上的测试载体。UI 不崩溃、按钮可点击或识别文本正确，都不能替代 SDK 生命周期断言。
- 真实用户操作必须翻译成调用方时序：快速开始/取消/重启、`onStart` 内冲刷录音缓存、`finish` 后立即尝试下一 session、回调内重入、旧 session 迟到 `writeAudio/finish/cancel`、重复结束、运行中 shutdown 和失败后的下一轮恢复。
- 成功回调必须写成可观察的状态后置条件，并建立“回调 x 公共 API”重入矩阵。不得用一个带特殊补偿分支的 API（例如启动期 `cancel`）证明其他 API 也可用；首次使用还必须组合冷加载期间缓存、回调内同步回放和继续/立即结束两条路径。具体教训见 `delivery/harmony-dingqiao/docs/ONSTART_SESSION_PUBLICATION_POSTMORTEM.md`。
- 每条压力用例必须按 `sessionId` 保存有序回调轨迹，分别统计 start、final、`isLast`、complete 和 error。聚合总数相等不能证明没有串 session。
- cancel 生效后不得再新增 final/complete；取消前已经正常产生的非 last endpoint final 必须保留并计入快照，但取消前不得已有 `isLast` 或 complete。正常 session 必须只有一次 `isLast`，随后一次 complete；旧 session 的迟到调用不得终止或污染当前 session。
- 现实操作压力与精度评测分开。生命周期用例只检查状态、归属、顺序、错误码、资源回收和可恢复性，不用文本正确率决定 PASS；声纹只检查“应有分数/应省略分数”的接口契约，不比较相似度精度。
- `user-sequence`、`reentrant`、`start-cancel`、`start-write`、`edge` 和实时 `paced` 是发布前必跑门禁。至少一组运行超过 60 秒，以区分模型逐步驻留与持续内存泄漏。
- 不得声称“覆盖所有边界”。报告必须列出已覆盖的调用序列、轮数、设备/系统版本、未覆盖的外部故障，以及任何仅为 `INCONCLUSIVE` 的资源指标。

## PR 合入门禁

- 合入前必须拉取并检查 PR 的全部 review threads，包括 Copilot suggestion；不能只看 CI 结果或 review 摘要。
- 每条 suggestion 都要回到接口契约和根因层验证。有效问题必须修复并补回归测试；误报必须记录不采纳理由，不得机械照改。
- 推送修复后必须重新获取 review threads，确认旧评论已失效或已处理，并检查新提交是否产生新的有效建议。
- 只有当前 PR HEAD 的必需 CI、对应平台构建和约定的真机 SDK 门禁全部通过，且没有未处理的阻断评论，才允许合入主分支。

## 推荐验证命令

```bash
python3 -m unittest \
  asr.tools.tests.test_harmony_initial_silence_tracker \
  asr.tools.tests.test_harmony_rejected_final_lifecycle \
  delivery.harmony-dingqiao.delivery.test_run_device_stress -v

cd asr/android
./gradlew --no-daemon :sdk:testDebugUnitTest :sdk-dingqiao:testDebugUnitTest --console=plain
./gradlew --no-daemon :sdk:testReleaseUnitTest :sdk-dingqiao:testReleaseUnitTest --rerun-tasks --console=plain

python3 delivery/harmony-dingqiao/delivery/run_device_stress.py \
  --data-dir "$HOME/Downloads/testdata" \
  --mode vad-begin --cycles 100 --files 0

python3 delivery/harmony-dingqiao/delivery/run_device_stress.py \
  --data-dir "$HOME/Downloads/testdata" \
  --mode voiceprint-vad-begin --cycles 100 --files 0

python3 delivery/harmony-dingqiao/delivery/run_device_stress.py \
  --data-dir "$HOME/Downloads/testdata" \
  --mode user-sequence --cycles 300 --files 3
```

真机命令中的次数和语料数量可按耗时调整，但合入前至少要覆盖 `burst`、`paced`、`vad-begin`、`vad-begin-silence`、`voiceprint`、`voiceprint-vad-begin`、`voiceprint-vad-begin-idle`、`cancel`、`cancel-full`、`max-duration`、`edge`、`reentrant`、`start-cancel`、`start-write`、`user-sequence` 和 `numeric-edge`。任何模式失败都应先解释并修复，不能通过放宽全局空结果率掩盖生命周期错误。
