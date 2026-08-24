# Changelog

## 0.3.10 - 2026-08-24（Speaker VAD 交替说话与便携 Demo）

- 修复按住说话期间机主与非机主交替讲话时，异步 Speaker VAD 评分合并中间窗口导致返回机主的
  后续内容被丢弃的问题；评分窗口按顺序处理，并在拒绝非机主段后保留必要的边界音频继续判断。
- 保持 Speaker VAD 阈值、声纹模型和公共回调接口不变；显式 `finish` 前不产生 `isLast`，结束后仍为
  唯一 `isLast` 再唯一 `onComplete`。重叠说话的说话人分离不在本版本范围内。
- 完整交付包的已签名 Demo 内置不绑定设备的体验授权，并增加组包校验，确保 HAP 不会因设备白名单
  导致安装后“开始识别”不可用；正式 SDK 集成仍使用业务正式授权。
- 完整交付同时包含 Release SDK、Debug（Diagnostics）SDK、可直接安装的 Demo HAP 和可独立构建的
  Demo 源码。

## 0.3.9 - 2026-08-24（开放 Runtime 日志等级）

- 兼容适配层新增 `SpeechRecognizeSdk.setLogLevel(AmphionLogLevel)`，支持业务方在
  `prepareRuntime` 前将日志等级设置为 `INFO` 或 `DEBUG`。
- 设置为 `INFO` 后，Runtime 首次初始化成功时会在 Harmony hilog 输出
  `AmphionRuntime Harmony init done, version=0.3.9`，便于现场确认实际运行的 SDK 版本。
- 默认日志等级仍为 `WARN`，未调用新接口的既有集成行为保持不变；识别、声纹、Speaker VAD、
  生命周期与诊断采集逻辑均未修改。
- 目标说话人增强仍仅保留接口预留；0.3.9 不包含该能力所需模型，不能启用该参数。

## 0.3.8 - 2026-08-24（Speaker VAD 尾部时延与完整交付）

- 相对 0.3.7，优化 Speaker VAD 尾部时延：增加安全前缀预解码并批量执行说话人评分；既有阈值、
  候选选择、评分结果和 final 分段行为保持不变。
- 0.3.7 已交付机主与其他人交替讲话时的闪退修复；0.3.8 保留该修复并完成同场景真机回归，
  不作为 0.3.8 新增修复。
- 诊断能力改为编译期隔离的独立 Diagnostics SDK，并配套 Diagnostics Demo；完整记录 SDK 输入 PCM、
  结构化回调、有效配置、Runtime 指标和崩溃恢复 journal。普通 `debug` / `release` 构建关闭诊断采集。
  0.3.7 的 `DiagnosticOptions`、`DiagnosticMode` 和 `configureDiagnostics(...)` 保留为废弃兼容接口，
  但不再改变采集行为。
- 增加完整交付包，统一包含正式 SDK、Diagnostics SDK、已签名 Diagnostics Demo、可独立构建的 Demo
  源码、验收摘要及构建来源校验信息。
- 保持公共识别、声纹、Speaker VAD 与 `isFinal` / `isLast` / `onComplete` 接口契约不变。
- 目标说话人增强仍仅保留接口预留；0.3.8 不包含该能力所需模型，不能启用该参数。

## 0.3.7 - 2026-08-22（机主识别稳定性与新模型）

- **开启说话人 VAD 后机主识别闪退**：优化机主识别与说话人 VAD 同时运行时的任务处理顺序，
  避免识别过程中相互干扰导致应用崩溃。
- **长会议跨段识别可能丢字**：优化长语音分段衔接，保留必要的上下文，降低跨段位置漏字或结果中断的概率。
- **热词人名识别不准**：优化生僻人名和短人名热词的匹配与候选优先级，提高人名热词命中率。
- **初始静音超时后仍可能返回结果**：优化超时后的结果收口，避免会话已结束后继续返回迟到结果。
- **现场问题缺少有效日志**：Debug SDK 和 Debug Demo 默认提供完整诊断信息，并保留最近五分钟记录，
  便于复现后直接导出日志分析。
- **部分页面内容在小屏设备上显示不全**：优化 Demo 页面滚动，确保配置项和操作入口可以正常访问。
- 中英识别能力更新为本次交付的新模型；正式 SDK 与 Debug SDK 使用相同能力基线，Debug SDK 仅额外开启诊断能力。
- 目标说话人增强仍仅保留接口预留；0.3.7 不包含该能力所需模型，不能启用该参数。

## 0.3.6 - 2026-08-20（回退至稳定模型）

- 最终交付恢复为 0.3.4 已使用的稳定中英识别模型，撤回 0.3.5 候选模型及其配套的警务热词裁剪
  实验配置；不交付后续警务增强与数字恢复候选模型。
- 保留既有 Harmony 警务文本增强、中文热词 UTF-8 长度修复和公共 API。
- 保留 0.3.5 的 Runtime 修复，包括 60 秒 endpoint 配置、长会议 continuous session、空 endpoint
  后刷新 stream、Speaker VAD 顺序换人收口及全部生命周期契约修复。
- 最终交付包为 `amphion-harmony-asr-sdk-v0.3.6-20260820-old-model.zip`，绑定 source commit
  `6fec66b6f6601e448902f9f35bd98683399ca2e1`，SHA-256 为
  `43b266c6dc0864b440b03bea717747539396846187521d1cf6a897f5a7ed7c2a`。
- 目标说话人增强仍仅保留接口预留；0.3.6 不包含该能力所需模型，不能启用该参数。

## 0.3.5 - 2026-08-20（新模型与长会话恢复）

- 默认中英识别模型升级为当前交付模型；模型身份、HAR 构建身份和交付 provenance 重新绑定，
  不复用 0.3.4 的旧模型产物。新模型的 AGC 专属精度基线仍待单独验收，不能用旧模型门禁代替。
- 新增 `endpointMaxUtteranceMs` 会话参数，长转写和会议场景把 native 单句上限从 20 秒提升到
  60 秒，并将该参数纳入 recognizer 复用键，避免不同 endpoint 配置错误复用同一实例。
- 空 native endpoint 后改为创建 fresh stream，缓解长会议中 encoder 状态逐步失效后持续有声无字；
  1286 秒真机语料的最后非空 final 从约 1087.74 秒推进到 1198.10 秒，last/complete、error 和
  stream 回收契约通过。但 1198.10 秒后的剩余尾段仍未恢复，本版本不宣称彻底关闭长会议问题。
- 加强 Speaker VAD 在 finish、拒绝结果和顺序换人场景下的 final 收口；被拒绝的 non-last 结果会
  发布空 final 清理 speculative partial，同时保持 finish 后唯一 last、唯一 complete。重叠说话仍
  不在能力范围内。
- 修复非 ASCII hotword 按字符数而不是 UTF-8 字节数分配 native buffer 的问题，避免中文热词截断。
- 保持公共 `isFinal` / `isLast` / `onComplete` / `cancel` 契约不变；PTT 尾字准确率、Speaker VAD
  重叠说话、远讲/SNR、警务词与专项 hotword 精度仍按已知问题清单继续跟踪。
- 目标说话人增强仍仅保留接口预留；0.3.5 不包含该能力所需模型，不能启用该参数。

## 0.3.4 - 2026-08-17（警务术语短 final 定向修复）

- 补齐客户 Harmony SDK 反馈与三星真人复测中的警务术语短 final 误识别，覆盖“签警情”、
  “签警单”、“设卡盘查”、“经纬度采集”、“治爆”、“勤指情平台”、“案结事了”、
  “拘传”、“羁押”和“警官”等已确认变体，并同步 Android 与 Harmony 规则。
- 新规则仅纠正完整短 final，同时补充正常长上下文保护样例；不改变 partial、ASR 模型、公共 API、
  声纹、Speaker VAD 或 `isFinal` / `isLast` / `onComplete` 生命周期语义。
- 目标说话人增强仍仅保留接口预留；0.3.4 不包含该能力所需模型，不能启用该参数。

## 0.3.3 - 2026-08-14（Speaker VAD 结果收口与警务词修复）

- Speaker VAD 的边界分段已确认“机主到他人”的顺序换人、但无法精确确定切点时，改用最后一个
  已确认机主窗口之前的保守前缀重新识别；若连安全前缀也无法证明，则拒绝本段不确定结果，避免把
  后说话人的开头文字返回给业务层。
- Speaker VAD 恢复遵循 `enablePartialResult`：开启时继续回调 speculative partial，目标说话人边界
  仅对 final 结果作保证；partial 可能暂时包含随后从 final 移除的非目标人文本，关闭该参数时仍
  不回调中间结果。
- 保持目标人单独说话、明确边界后的后缀重放以及既有 `isFinal` / `isLast` / `onComplete` 生命周期
  语义不变；同时说话仍不在本次修复范围内，不宣称具备说话人分离能力。
- 补齐“签收警单”及“小乔”语义下多种设备端同音误识别的警务归一化，并同步 Android 与 Harmony
  规则和回归样例；警务增强仍只处理 final，不改变 partial 文本或生命周期回调顺序。
- 目标说话人增强仍仅保留接口预留；0.3.3 不包含该能力所需模型，不能启用该参数。

## 0.3.2 - 2026-08-13（自动增益、预加载与 Runtime 稳定性）

- `TargetSpeakerConfig.minSegSec` 默认并在鼎桥适配层固定为 `0`，取消 SDK 侧最短时长门槛和额外的
  `vadBegin` 声纹确认窗；音频时长、短句精度、业务阈值及是否采用分数由调用方判断。
- 声纹 final 不再把 `minSegSec` 当作出分质量门槛：已有非空 ASR text/token 时使用本句非空真实
  PCM 尝试计算 `speakerSimilarity`。SDK 负责出分，短句精度、业务阈值和接受策略由调用方承担；
  纯静音、空 PCM 和 extractor 技术上无法产生 embedding 时仍不伪造分数。
- 修复长音频 `finish -> shutdown -> setLicense` 与 native async decode 尾任务重叠时，旧 Runtime
  提前释放 recognizer 导致尾部结果丢失或 native 崩溃的问题。
- session 持有 Runtime lease 直到公开回调关闭、in-flight native 调用返回且 stream 关闭；释放等待期
  阻止新 session，重新授权成功回调等待旧 Runtime 安全释放。
- 新增 Runtime release gate 状态机测试和 `finish-shutdown-relicense` Mate 80 真机回归模式；识别、
  VAD、endpoint 及既有 `isLast -> onComplete` 语义保持不变。
- 新增默认启用的 WebRTC AGC2 自动增益，识别流使用增益后的 PCM，VAD、首段起音、声纹评分和
  Speaker VAD 仍使用原始 PCM，保持生命周期与说话人边界不被增益处理改变。
- `prepareRuntime()` 现在预加载默认中英模型并复用 recognizer pool，首次 `createEngine` 不再重复
  承担相同模型的冷加载；既有 License、Runtime 与 Model 生命周期接口保持不变。
- 修复连续 Speaker VAD 分段中上一说话人的尾音残留，清理 native stream 边界时继续保留声纹
  回退 PCM，避免短分段合并后的评分样本丢失。
- 修复 Harmony 适配层未向核心 ASR 透传警务热词的问题，并补齐 0.2.8 术语回归样例，警务文本增强开关
  与原有 final/last 回调顺序保持不变。
- 目标说话人增强仍仅保留接口预留；0.3.2 不包含该能力所需模型，不能启用该参数。

## 0.3.1 - 2026-08-07（异步 finish 兼容性修复）

- 修复 VAD `SPEECH_END` 回调内同步调用 `finish` 时的结果断层：当前带文本 endpoint final
  会直接成为唯一的 `isLast=true`，不再追加空 terminal final。
- 修复 PTT 调用方在已接受 `finish` 后立即调用 `shutdown` 导致 final/complete 丢失：
  SDK 保持 `isBusy=true` 直到完成，并在回调收敛后再释放引擎资源。
- 新增宿主端回归用例与 `callback-api-reentrant` / `finish-shutdown` USB 真机门禁，
  分别锁定非空 last 文本以及 last 后唯一 complete 的生命周期契约。
- 目标说话人增强仅保留接口预留；0.3.1 不包含该能力所需模型，不能启用该参数。

## 未发布 - 2026-08-05（Harmony 目标说话人增强接口预留）

- 新增默认关闭的 `enableTargetSpeakerEnhancement`，在现有 Speaker VAD/ASR 前执行 2 秒分块的
  双人语音分离、逐块声纹选流和 0.25 秒平滑拼接；客户接口不暴露具体模型和内部阈值。
- 新增 `targetSpeakerEnhancementApplied` 结果标记；保持单 session、单 ASR 回调链以及既有
  `isFinal/isLast/onComplete/cancel` 语义。
- 新增 C1/C2/C3 完整音频与推理中 cancel 后立即恢复的真机门禁；12 GB Mate 80 上文本、生命周期
  和 67 秒资源观察通过。
- Conv-TasNet 测试权重未提交、未默认进入商用 HAR；正式发布仍以书面商用授权或许可清晰的替换模型
  为硬门禁。

## 0.3.0 - 2026-08-07（首次 PTT 音频无损与警务术语增强）

- `writeAudio` 改为先复制调用方 PCM，再按 session 串行异步送入识别器，不再在客户主线程同步执行
  native decode；冷加载超过录音起始时间时，首段音频也会完整排队处理，修复首次 PTT 无结果和开头丢字。
- `finish` 与已提交音频共用同一 FIFO 队列，保证先处理全部已接受 PCM，再产生唯一的 `isLast=true`
  和随后的 `onComplete`；`cancel` 仍立即停止接收新音频且不补发 final/complete。
- 加固首次冷加载、`unloadModel` 后重新冷加载以及 `onStart` 回调内同步 `writeAudio`、`finish`、
  `cancel` 的可用性，调用方无需等待 `onStart` 返回后再冲刷录音缓存。
- 更新警务术语和短句护栏，增强“情指行”“签收警单”“到场”“反馈”等场景；修复
  “我已到达现场”重复补前缀或被再次改写的问题，并保持 Android/Harmony 归一化结果一致。
- 声纹回退评分增加 ASR text/token 语音证据门禁；没有语音证据时不再仅凭累计 PCM 时长产生
  `speakerSimilarity`。Speaker VAD 的打分步长改为与调用方分帧方式无关。
- 真机门禁适配异步音频队列，补充冷加载缓存回放、回调内 API 重入、精确最大时长、
  cancel native stream 回收和首段静音/稳态噪声按实际处理 PCM 计时的验证。
- 目标说话人增强仅保留接口预留；0.3.0 不包含该能力所需模型，不能启用该参数。

## 0.2.9 - 2026-07-30（警务增强开关与交付追踪）

- Android 与 Harmony 鼎桥 Demo 均新增持久化“警务增强”开关，并在每次会话启动时通过
  `enablePoliceEnhancement` 固定本轮配置。默认开启；显式关闭时 final 返回原始 ASR 文本，
  不执行警务术语、车牌和派出所归一化，生命周期回调保持不变。
- Harmony 鼎桥适配层接入 `amphion_police`，自包含客户 HAR 同步内置该模块及资源，避免外部工程
  出现无法解析的本地依赖。

## 0.2.8 - 2026-07-18（警务术语增强与交付校验）

- 声纹严格有效语音不足 `minSegSec`，但 ASR 已确认非空 text/token 且当前句真实 PCM 达到门槛时，
  改用当前句 PCM 计算 `speakerSimilarity`；严格评分仍为主路径，短句、纯静音和空 terminal final
  不填充或复制分数。
- `maxAudioDuration` 移除 20000 ms 最小钳制；显式正有限值按调用值生效，`8000` 即在写入约
  8000 ms PCM 后自动结束，仍保留 28800000 ms 上限。
- 新增 `voiceprint-fallback` cold/warm 真机门禁、8 秒 burst/paced 精确帧数门禁，以及本次问题的
  根因复盘和发布测试流程。
- 基于 0.2.7 已使用的 260717 模型补齐警务术语后处理，增加易混词归一化以及“情指行”“登录”
  语境护栏，并同步 Harmony 与 Android 行为。
- Speaker VAD 默认参数延续 0.2.7：阈值 `0.35`、窗口 `1500 ms`、步长 `500 ms`。
- 中英 joiner 使用 FP32 `joiner.onnx` 生成运行时 ORT；交付校验固定 ONNX 源模型身份并核对
  运行时清单，避免转换产物差异影响版本确认。
- 交付模型门禁以 0.2.8 encoder、decoder、joiner 原始 ONNX MD5 为准；ORT 仅做文件完整性
  校验，不再参与模型版本判断。
- 组包脚本统一将输出目录转为绝对路径，修复使用相对输出目录时校验清单写入错误的问题。

## 0.2.6 - 2026-07-16（端点回调内结束兼容）

- 修复调用方在 `SPEECH_END`（`eventCode=3`）回调内同步调用 `finish()` 时，SDK 先返回带文本的
  `isLast=false` final、随后又返回空 `isLast=true` final 的兼容性回退。
- 当该端点回调只请求结束且没有更早排队的音频时，当前带文本 final 直接成为本 session 唯一的
  `isLast=true` 结果，随后仍只回调一次 `onComplete`。
- 保留回调重入隔离与 FIFO 顺序；`writeAudio -> finish` 已排队时不会跳过待处理音频，也不使用全局
  `finishRequested` 把较早的异步 final 误标为 last。

## 0.2.5 - 2026-07-16（生命周期回归防护与交付证据）

- 修复 `onStart` 会话发布门禁的跨 session 代次隔离，旧 session 的迟到 started 信号不能解锁新 session。
- 将同一 generation 校验扩展到全部 native 回调，并在客户 listener 返回后复检；回调内 cancel/restart 时，旧 final/error/stopped 不再污染新 session。
- `maxAudioDuration` 改为仅在显式传入有限值时启用；缺省或非法值不再隐式触发 20 秒自动结束。
- 增加 `speaker-vad-onstart`、`numeric-edge` 和 `max-duration` 真机门禁，覆盖声纹运行期开关、非法数值参数和显式最大时长自动结束。
- 增加历史生命周期问题闭环说明、客户脱敏验证摘要和机器可读证据，并在组包与 CI 中执行脱敏检查。
- 发布包、`amphion_dingqiao` HAR、核心 ASR/Police HAR 和 Demo HAP 的版本统一为 0.2.5。

## 0.1.0 - hotfix 2026-07-15（声纹与首段超时组合边界）

- 修复底层 session 构造同步触发 `onStart` 时，鼎桥适配层尚未发布 session，调用方在 `onStart` 内冲刷录音缓存会收到 `1002200010 NOT_LISTENING`、导致首次识别失败的问题。
- `onStart` 现在只在 session 已保存且目标说话人配置完成后对外发送；新增 32/88 帧回调内同步写入门禁，并保留 `onStart` 内取消能力。
- 修复 `vadBegin=1000` 下 VAD/流式 ASR 暂未暴露起音、停止刷新却已有文本时，真实首句被错误标成 `isLast=true` 的竞态。
- 声纹校验或 Speaker VAD 开启时，纯静音仍按 `vadBegin` 结束；初始窗内存在连续未决声学活动时才使用一次默认 1.5 秒确认窗，窗末只接受近期语音型活动或 ASR text/token，避免旧脉冲永久解除计时。
- 声学 backstop 使用固定 20 ms 窗、连续活动、能量变化和过零率联合判定；不依赖调用方分帧，不把稳态高能非语音永久当作 speech，也不伪造 speech 事件。
- Core SDK 在首段计时 armed 时按固定 20 ms slice 推进 ASR/VAD 决策，避免大块输入中 deadline 之后的音频回看并改变之前的超时结果。
- 增加 `voiceprint-vad-begin` 与 `voiceprint-vad-begin-idle` 真机模式，分别验证真实语音在显式 `finish` 前无 `isLast`，以及纯静音/稳态高能非语音仍有界自动结束。
- 明确 `vadBegin` 上限是 10000 ms，调用方传入 60000 ms 并不代表等待 60 秒。

## 0.1.0 - hotfix 2026-07-14（跨端参数与 VAD 前端点）

- Android 与 Harmony 补齐 `vadBegin`：仅显式传入时启用，按底层实际处理的 PCM 时长计时，真实起音优先于阈值边界。
- 首段持续静音达到阈值后正常返回一个空的 last final 和一次 `onComplete`，不发送 speech 事件或错误；结束后可立即启动下一会话。
- 补齐 `recognitionMode`、`recognizerMode`、`locate`、`maxAudioDuration` 上限和 `NO_MIC_PERMISSION=1002200012` 兼容契约；`sessionGeneralLexicon` 仍明确为 V1 不支持。
- 增加 USB 真机 `vad-begin` 模式，使用真实 WAV 验证起音事件，并在 SDK 自测中覆盖持续静音自动结束。

## 0.1.0 — hotfix 2026-07-13（License / Runtime / Model 生命周期）

- `setLicense` 只执行离线授权校验与缓存，不再隐式拉起 Runtime。
- 新增 `prepareRuntime` / `unloadRuntime` 和 `unloadModel`，形成 License、Runtime、Model 三层控制；`unloadRuntime` 保留已验证授权，模型未卸载时跟随释放。
- `createEngineAsync` / `createEngine` 在模型未加载时加载，同语言、同配置已加载时复用。
- 新增 HarmonyOS 客户接口文档和十轮全流程耗时、SDK 净内存报告及甲方简版摘要，并纳入客户交付包。

## 0.1.0 - hotfix 2026-07-13（声纹模型与生命周期）

- 声纹模型内置到 `amphion_dingqiao.har` 并由 SDK 直接加载，Demo 和宿主不再导入模型。
- 声纹注册与 Android 对齐：至少 1 条 3~8 秒样本，不限制样本数量上限。
- 明确生命周期：`prepareRuntime()` 不读取声纹模型；`unloadModel()` 确定性卸载内存 extractor，但保留 HAR 模型和已注册 embedding。
- 普通 final 声纹校验改为 N-API 后台加载 extractor，ASR 启动、音频写入和中间结果不等待；只有 final 必要时等待。Speaker VAD 因流式打分仍在冷启动时同步加载。

## 0.1.0 — hotfix 2026-07-12（Harmony ASR 冷加载）

- `zhen` encoder/INT8 decoder/joiner 与标点模型在构建期转换为 ARM CPU ORT 格式，运行时关闭重复图优化并直接使用 rawfile 映射模型字节。
- recognizer 与标点异步并行加载；transducer Session 采用 encoder 关键 lane 与 decoder/joiner 辅助 lane，相同配置使用 single-flight 与进程内 pool。
- 鼎桥配置使用 4 个 ORT worker，并跳过收益不足的 800 ms eager warmup。
- 新增独立进程 `createEngineAsync` 加载基准，固定设备构建、模型源哈希、HAP/native hash、线程数、预热样本和标点状态。
- 真机 `zhen` 冷加载 p50 从 3884.5 ms 降至 774.5 ms，p95 为 810.25 ms；pool hit 为 0–1 ms。48 轮真实音频回归通过。

## 0.1.0 — hotfix 2026-07-10（授权、模型与真机验收）

- `SpeechRecognizeSdk.init` 支持宿主注入 `deviceIdProvider`；普通 Demo 使用 ODID，特权宿主保留硬件 SN 路径。
- 模型打包和 signed HAP 增加强制 manifest 路径、大小、SHA-256 校验。
- signed HAP 增加 profile、bundle/module 和预期证书链校验；客户包支持显式 `--asr-only` 模式，并在仅依赖自包含 ASR HAR 的干净宿主中执行编译验收。
- Sherpa Harmony NAPI 捕获 recognizer 创建异常并转成 ArkTS 错误，避免无效 ONNX 导致 `SIGABRT`。
- 新增一键预检和 USB 真机 smoke，完成标准为页面进入“引擎就绪”。

## 0.1.0 — hotfix 2026-07-08（声纹 ASR 崩溃）

- 修复：开启「声纹校验」启动识别时 native abort 崩溃。`amphion_asr` 的 `Runtime.ets`
  `createSpeakerExtractor` 对绝对路径模型（`${workPath}/eres2net.onnx`）不再传 `resourceManager`，
  避免 sherpa 走 rawfile-only 加载器打不开文件系统绝对路径而崩溃；与 `SpeakerEnroller` 的
  `startsWith('/')` 判定对齐。注册路径本就正确，故此前「注册成功、识别崩溃」。
- 说明：`eres2net.onnx` 为合法 ONNX（非 `.pth`），无需重导；模型文件不变。

## 0.1.0

- 新增纯血鸿蒙 SDK：ASR 工程 `asr/harmony`（`amphion_asr` / `amphion_police` / `amphion_dingqiao`）、TTS 工程 `tts/harmony`（`amphion_tts`）。
- 新增统一交付聚合层 `delivery/harmony-dingqiao/`：同时演示 ASR + TTS 的 `amphion_asr_demo` HAP、交付文档与打包脚本。
- 新增核心 ASR ArkTS API 映射：`AmphionRuntime`、`AsrEngine`、`AsrSession`、`AsrConfig`、`AsrCallback`、`AmphionMetrics`。
- 新增鼎桥接口映射：`SpeechRecognizeSdk`、`SpeechRecognitionEngine`、`RecognitionListener`、错误码与 640 字节 PCM 帧契约。
- 新增离线 TTS ArkTS API：`TextToSpeechSdk`、`TextToSpeechEngine`、`TtsCreateEngineParams`、`SpeakParams`，底层走 `sherpa_onnx.OfflineTts`。
- TTS 支持 `SYNTHESIZE_AND_PLAY` 内置播放：`AudioRenderer` writeData 拉模型 + `CircularBuffer`，与 `onData` 流式 PCM 并行。
- 新增 HarmonyOS native 构建脚本、ASR/TTS rawfile 模型同步脚本与客户交付打包脚本。
