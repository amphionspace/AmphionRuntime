# AmphionRuntime Agent Instructions

## ASR 生命周期契约

- `isFinal=true` 表示一句话或一个 endpoint 的最终结果；`isLast=true` 只表示整个 session 的最后一条结果。不要把二者混用。
- 普通连续识别中，调用方执行 `finish(sessionId)` 之前不得出现 `isLast=true`。仅显式配置并命中 `vadBegin` 或 `maxAudioDuration` 时允许 SDK 自动结束。
- 每个正常结束的 session 必须恰好产生一次 `isLast=true`，之后恰好产生一次 `onComplete`；`cancel` 不得产生 final 或 complete。
- 每次自动结束都必须能归因到明确的终止条件。排查提前结束时，先记录 `finish` 调用、`vadBegin`、`maxAudioDuration`、写入 PCM 时长和完整回调时间线，不要先猜测模型问题。
- 初始起音属于多信号状态：VAD 或 ASR 的非空 text/token 任一确认语音后，必须永久解除本 session 的 `vadBegin`。声学 backstop 不能把“高于固定音量”直接等同于 speech：它只能先触发一次有界确认；持续活动还要满足语音型能量变化和过零率范围，才可解除计时，且不得伪造 speech 事件。
- 组合参数必须按能力的时间前置条件验收。启用声纹校验或 Speaker VAD 时，`vadBegin` 本身仍是纯静音等待；只有显式配置正数 `TargetSpeakerConfig.minSegSec` 时，初始等待窗内连续但未决的声学活动才允许获得不超过该值的一次性确认窗。默认 `minSegSec=0`，不延长等待。旧活动不能在确认窗末直接解除计时：必须仍有近期语音型活动，或强制刷新 ASR 得到非空 text/token。测试必须分别验证纯静音、稳态高能非语音、零散脉冲和真实语音，不能只检查参数解析。
- 异步回调只能根据当前结果携带的 `isLast` 决定是否完成会话；不得用全局 `finishRequested` 推断某条较早结果是最后一条。
- `onStart` 是会话已经可用的承诺，不只是底层 native 构造完成通知。SDK 对外回调前必须已经发布 session 并完成会话级配置；调用方允许在 `onStart` 内同步执行 `writeAudio`、`finish` 或 `cancel`，不得收到 `NOT_LISTENING`。
- 进程级 `unloadModel` / Runtime release 不得越过活跃 session 的 native 异步工作。session 只有在公开回调关闭、最后一个 in-flight native 调用返回且 stream 已关闭后才算 quiescent；释放等待期间不得创建新 session。重新设置授权触发 Runtime 替换时也必须遵守同一边界。

## 声纹结果契约

- 公共字段名是 `speakerSimilarity`。新增或修改示例、文档和测试时必须使用该名称。
- SDK 的职责是对已确认的语音产出声纹结果，业务方负责根据使用场景选择阈值并承担短句精度风险。
  `TargetSpeakerConfig.minSegSec` 默认且在鼎桥适配层固定为 `0`，SDK 不设置最短时长门槛；ASR 已产生
  非空 text/token 时，必须使用本句非空真实 PCM 尝试评分，不得仅因时长或内部质量判断省略分数。
  业务方自行根据音频时长、相似度和场景阈值决定是否采用。没有 ASR 语音证据、没有真实 PCM、
  声纹能力未启用、有效 ID 缺失或
  extractor 在技术上无法产生 embedding 时可以省略；不得填充假分数、复制上一句分数或补静音。
- 排查 `speakerSimilarity=undefined` 时，必须同时记录 `enableVoiceprintVerification`、`enableSpeakerVad`、`voiceprintIds` 数量、调用方传入和 SDK 生效后的 `vadBegin`、实际写入 PCM 时长以及该 final 的有效语音时长。缺少声纹开关或有效 ID 时不得归因为打分异常。
- 声纹测试至少覆盖：`minSegSec=0`、500 ms 短句、自定义正数门槛的边界、低音量、前置静音、非注册语料源和多句连续输入。有真实 PCM 的每个非空 final 都必须逐条核对分数，不能用“整轮至少一个分数”代替。生命周期门禁只判断出分资格、回调顺序和会话恢复；目标/非目标相似度精度及短句风险另走带身份标注的评测集，由业务方决定阈值和接受策略。
- 同时启用声纹校验和 Speaker VAD 时，必须区分 native stream 边界与公开 final 边界。token-only endpoint 被抑制时可以清理 Speaker VAD 当前流窗口，但不得丢弃声纹回退 PCM；测试至少覆盖两个各短于门槛、合并后达到门槛的 native segment。

## 离线能力边界

- 鼎桥 SDK 的正式交付能力必须完全离线运行。识别、声纹、Speaker VAD 和未来的角色分离均不得依赖公网、局域网服务或业务方配置服务 URL，不得上传 PCM、文本、embedding 或其他推理数据。
- 角色分离的目标形态必须是 SDK 内的端侧离线推理。当前基于 `SpeakerDiarizationConfig.serviceUrl` 的服务化实现属于未解决的遗留方案，不符合正式交付要求；在完成离线改造前，不得在 Demo、客户邮件、升级说明或发布声明中启用、推荐或宣称角色分离已经交付。
- 角色分离离线改造必须在断网条件下通过公共 SDK 功能和生命周期验收，并证明运行时没有网络请求。仅保留公共类型、回调或使用本机 URL 联调，不能作为离线能力完成的证据。

## Debug 哲学

Debug 的核心不是反复重现现象，而是缩短“假设—证伪”的反馈周期。重放现场只用于建立可靠基线和验证最终结果；基线成立后，必须深入内部状态并承担定位责任，不得以“安全起见”“再确认一次”或“多跑几轮”为由，用没有新增诊断信息的黑盒重放代替分析。

1. 先观察，再干预。先让内部状态可见，明确数据在哪一层开始偏离预期，再修改代码。不要仅凭外部症状猜测模型、并发或性能问题。
2. 找到第一个错误状态。沿数据链路逐层检查，定位最早出现异常的状态转换。外层的空回调、超时或卡顿通常只是结果，不是根因。
3. 用最小实验隔离变量。固定 PCM、参数和调用时序，每次只改变一个状态条件，例如保留旧 stream、soft reset 或创建 fresh stream。
4. 状态分叉优于重复长跑。在异常点保存必要状态，让相同后续输入分别通过正常路径和可疑路径。比较两者第一次产生差异的位置，比重复端到端实验更有诊断价值。
5. 白盒诊断，黑盒验收。定位阶段依靠内部指标、状态快照和局部差分；最终交付阶段才使用真实调用方、完整语料和公共 API 契约验收。不要用黑盒长跑代替白盒推理。
6. 证伪假设，而不是收集支持。每个实验都必须说明准备推翻哪个判断，以及出现什么结果后必须放弃当前方向。不能证伪假设的实验通常只是在增加日志和等待时间。
7. 修复状态机，不掩盖症状。修正产生错误状态的最内层状态转换，不在外层吞回调、补假文本、延长超时、增加重试或放宽断言来隐藏问题。
8. 从短闭环扩展到完整门禁。顺序是：最小复现红灯 → 根因状态差分 → 局部修复变绿 → 相邻不变量 → 一次完整端到端验收。长时实验是结案证据，不是主要搜索算法。

一句话：让状态可见，在最早分叉点用同输入证伪假设；局部证明根因，最后才用完整场景验收。

### ASR 跨 stream 边界排查

- 长会议无文字、空 endpoint 或边界丢词必须沿
  `acceptWaveform → decodeAsync → getResult → isEndpoint → dispatchFinal → reset/createStream`
  记录同一音频时间轴。至少包含 sample/frame 位置、stream identity/generation、transition
  原因、decode/ready 进度、text/token/timestamp、endpoint 命中原因、soft reset、hard restart
  和结果抑制原因。只看公开文本无法区分 native 解码、ITN 和适配层问题。
- 找到异常边界后，截取保留必要前序状态的最小 PCM，对同一后续输入分别走旧 stream、
  soft reset 和 fresh stream。结论必须指出第一个不同的 token/frame，不能只比较整段
  文字或 final 数量。
- hard restart 后如果确实需要声学上下文，补偿只能作用于被红灯证明的具体边界，
  并保持在 recognizer 内部。重放 PCM 不得进入下一个 public utterance 的
  `EffectiveSpeechBuffer`、`speakerPcmBuffers`、声纹评分、Speaker VAD、`vadBegin` 或
  duration/max-duration 计数。
- 不得在公共 `AsrResult` 暴露 overlap/replay 内部字段，也不得在适配层用字符串前后缀
  猜测去重。如果无法根据 native token timestamp/frame boundary 区分重放 token 与新 token，
  必须停止实现并重新设计 seam，不得用文本启发式补偿。
- 失败或被否决的原型可保留 artifact，但必须标记为 non-canonical，不得当作当前 HEAD
  的验收证据。完整长跑已经启动也不构成继续的理由；当结果不再影响技术决策时，
  应优雅中止并保留现有日志。

### 并发语义与状态归属

- 线程迁移、异步化、批处理、缓存、预计算、请求合并和 backpressure 等性能改造，不得改变
  相同输入在任意合法调度下的公开结果、状态归属和生命周期顺序。实现前必须列出需要保持的
  不变量，并用可控的延迟、乱序和分帧测试证明同步路径与异步路径在可观察语义上等价。
- 数据可以推测处理，但在相关边界决策提交前，其结果不得产生不可回滚的公开副作用，也不得
  污染其他 generation、stream、session 或 utterance。提交时必须根据稳定标识将结果唯一归属、
  丢弃或回滚；不得根据当前全局状态猜测迟到结果的归属。
- 对有序状态机输入，默认不得跳过、覆盖、合并或重排事件。只有证明该变换对所有下游状态
  可交换、幂等且保持可观察结果时才允许；“只关心最新值”不能作为证明。
- 并发相关测试必须比较不同延迟、分帧和合法调度下的结果，不得把“不等待某个 Future”、
  “队列长度为 1”等实现手段写成契约。测试应检查公开结果、数据归属、提交顺序和跨边界污染；
  Speaker VAD 至少以 `target → non-target → target` 和返回目标短语音覆盖这一要求。

## 缺陷处理流程

1. 先把用户症状转成可失败的断言。测试必须能捕获“提前 `isLast`”本身，而不是只验证进程未崩溃或最终出现过 complete。
2. 在修复前运行最小复现并确认一次稳定红灯；保存输入 PCM、启动参数、按时间排序的回调和终止原因。此后每次重放必须服务于一个明确的可证伪假设，并新增内部观测或只改变一个状态条件；否则停止重放，转向状态插桩、快照或局部差分。
3. 沿数据链路定位第一个错误状态及其最内层状态机，使用同输入的正常/可疑路径分叉证明根因，再实施局部修复；不要在外层吞回调或延时掩盖竞态。
4. 同时检查 Harmony 与 Android 的同名生命周期逻辑，避免两端语义漂移。
5. 修复后依次运行状态机单测、SDK 单测、Harmony 编译和当前 USB 设备真实音频压力测试；最后清除临时 debug 日志。

## 修复防退化

- 修改前必须分别写清“要改变的行为、必须保持不变的行为、明确不处理的范围”。涉及超时或结束条件时，至少把纯静音结束时间、真实语音不中断、噪声有界结束、分帧无关、final/last 顺序列为不变量。
- 缺陷修复不得夹带无关的参数解析、性能优化、引擎复用或生命周期重构。确需调整时拆成独立提交和独立验证，避免一个补丁同时改变多个状态边界而无法归因。
- 后续异常必须用修复前后同输入、同参数、同调用时序的差分测试或 commit 二分归因，并明确区分：本次修改引入的回归、原缺陷未修完整、以及被新时序暴露的既有缺陷。没有证据不得把三者混称为“新版本回归”。
- 每个修复至少包含一个能捕获原始症状的红灯用例和一个保护相邻不变量的用例。主场景变绿但 token-only、重复 text、回调内重入、纯静音或稳态噪声等同层分支未验证时，不得宣布根因已经解决。
- 性能路径与生命周期路径不能完全分开验收。首次冷加载、卸载后重载等场景必须组合真实调用方行为，例如加载期间持续缓存 PCM 并在 `onStart` 调用栈内同步回放；只测加载耗时或回调返回后的正常写入不足以证明 SDK 可用。

## 验证投入约束

- 单个问题的排查以“复现失败、证明根因、修复后同条件通过”为最小闭环。结论已由针对性用例和必要的相邻状态验证支撑后必须停止，不得为了追求轮数或“覆盖所有边界”继续运行无关模式、重复构建或长时间等待。
- 诊断阶段不得把重复播放同一音频当作默认进展。除首次建立基线和修复后的同条件验证外，每次重放前必须记录待证伪假设、新增观测或唯一变化的状态条件、放弃该方向的判据和停止条件；缺少其中任一项就不得启动重放。所谓稳妥、安全或偶现不能替代这些责任。
- 区分问题验证与发布回归：问题验证只跑能证伪当前假设的最小用例；完整真机矩阵仅在合入或交付门禁执行一次。已有且对应当前 commit、设备和构建产物的有效结果应复用，不重复执行。
- 开始耗时操作前先说明它要验证的具体风险、预计耗时和停止条件。优先用可控状态转换替代业务等待，例如测试卸载后冷启动时直接执行 `unloadModel`，不机械等待业务配置的五分钟。
- 当前 USB 问题验证只构建和安装一个使用中英 `ZH_EN` 的测试 HAP；不得为与问题无关的语种额外构建或安装 HAP。该限制只约束测试载体，不改变 SDK/HAR 对粤英等已声明能力的支持范围。

## 最终交付冻结与证据复用

- 最终真机验收前，必须先确认并冻结代码、版本号、授权、签名方式和组包规则。
- 真机验收、Release SDK、Debug SDK 和完整交付包必须绑定同一最终提交。
- 组包脚本变更必须先通过小型测试或模拟输入验证，不得直接反复生成大型正式产物。
- 只有运行代码、HAP 或 HAR 内容发生变化时，才重新执行相关真机验收；仅文档、说明或不影响二进制的组包调整不得触发重复验收。
- 当前提交、设备和二进制一致的有效证据必须复用，不得以“保险”或“最终确认”为由重复运行。
- 耗时任务开始前必须说明验证目标、预计耗时、输出产物、结果失效条件和停止条件。
- 进入最终组包阶段后冻结交付范围，不得加入无关修复、扩大测试范围或追加非必要门禁；新问题另开提交处理。
- 若后续修改会使已有验收失效，必须先说明修改原因和需要重跑的最小范围，不得默认全部重跑。

## 必须保留的测试门禁

- 状态机单测：纯静音达到 `vadBegin` 只超时一次；边界帧中语音优先；ASR text/token 永久解除计时；低噪声、短脉冲和被静音隔开的变幅脉冲不误判；稳态高能非语音最多获得一次确认窗并最终超时；语音型变化信号不受调用方分帧影响；旧活动只能触发 probe，不能直接永久解除计时。同一 PCM 以单个大块或多个小块写入必须得到相同决定，deadline 之后的样本不得回看并改变 deadline 处的结果。
- 标准真机 session：记录调用 `finish` 前的 `isLast` 数量，要求为 0；结束后要求总数为 1。
- `max-duration`：达到上限后恰好一次 last/complete，迟到音频帧不产生额外回调，随后可以启动新 session。
- `cancel`、`start-cancel`、`start-write`、重复 `finish`、回调内重入、非法 session/frame 和 `NaN` 参数必须分别验证，不得合并成单一“edge passed”。`start-write` 必须在 `onStart` 调用栈内同步写入多帧真实 PCM 缓存，不能延迟到回调返回后；还要分别覆盖继续识别和回调内立即 `finish`。
- `vad-begin`：使用真实语音和纯静音分别测试。真实语音不得自动结束；纯静音必须按配置结束。
- 声纹与 `vadBegin` 必须组合测试 1000 ms 入参、实时/突发喂入、直接起音/前置静音；前置静音与源文件自身静音之和必须小于 1000 ms，否则自动结束是正确结果。显式 `finish` 前不得有 `isLast`，足够长的有效语音必须出现带分数的 final。另用纯静音/稳态高能非语音验证有界自动结束。参数上层改大只能作为规避，不能替代此门禁。
- `voiceprint-fallback` 必须使用能在旧版本稳定产生“非空 endpoint final 但分数缺失”的双文件语料，分别覆盖 cold/warm extractor；第一条非空 final 必须带分数，显式 `finish` 前不得有 `isLast`。该模式不得配置短 `maxAudioDuration`，避免把声纹样本选择与自动结束混成一个断言。
- Harmony finish 兼容性发布必须运行 `delivery/harmony-dingqiao/delivery/run_finish_compat_release_gate.py`。
  `callback-api-reentrant` 的 `SPEECH_END -> finish` 必须返回带非空文本的唯一 last；
  `finish-shutdown` 必须在同一 commit、设备和 HAP/HAR 上返回唯一 last 后唯一 complete。
  根汇总 `report.json` 和两个子模式完整 artifact 必须保留。
- Runtime 释放竞态修复必须用 `finish-shutdown-relicense` 重放完整调用序列：整段 PCM 入队后
  `finish -> shutdown -> setLicense -> prepareRuntime`。要求 `finish` 前 `isLast=0`，之后恰好一次
  last/complete、无 error、native stream 归零，并验证 Runtime 重建后的下一 session 可恢复。
- 长稳压：按采样率、时长和音量分层抽样，不只取随机文件；报告 callback 契约、空 final、native stream、RSS 和线程变化。
- 测试报告必须保留 `report.json`、逐轮结果、内存采样、hilog 和输入映射。失败 artifact 不得被后续运行覆盖。
- 发布矩阵完成后必须用 `archive_release_gate_evidence.py` 生成新的、不可覆盖的脱敏证据目录；
  保留 canonical PASS 和非 canonical 失败现场，不提交原始 PCM。发布账本必须通过
  `attach-evidence` 记录根 `report.json` 路径与 SHA-256，并用 `verify-evidence` 校验。
- SDK-only 打包不得把“Git 输入看起来干净”等同于“已构建 HAR 来自当前源码”。打包前必须验证
  `harmony_build_identity.py`；中英裁剪仍要绑定 `amphion_asr`、`amphion_police`、
  `amphion_dingqiao` 和 `sherpa_onnx` 四个 HAR，provenance 必须记录 source fingerprint 和
  component HAR 哈希。

## SDK 真实调用方验收

- 产品验收对象是 SDK 公共 API 和回调契约；demo/HAP 只是 USB 真机上的测试载体。UI 不崩溃、按钮可点击或识别文本正确，都不能替代 SDK 生命周期断言。
- 真实用户操作必须翻译成调用方时序：快速开始/取消/重启、`onStart` 内冲刷录音缓存、`finish` 后立即尝试下一 session、回调内重入、旧 session 迟到 `writeAudio/finish/cancel`、重复结束、运行中 shutdown 和失败后的下一轮恢复。
- 成功回调必须写成可观察的状态后置条件，并建立“回调 x 公共 API”重入矩阵。不得用一个带特殊补偿分支的 API（例如启动期 `cancel`）证明其他 API 也可用；首次使用还必须组合冷加载期间缓存、回调内同步回放和继续/立即结束两条路径。具体教训见 `delivery/harmony-dingqiao/docs/ONSTART_SESSION_PUBLICATION_POSTMORTEM.md`。
- 每条压力用例必须按 `sessionId` 保存有序回调轨迹，分别统计 start、final、`isLast`、complete 和 error。聚合总数相等不能证明没有串 session。
- cancel 生效后不得再新增 final/complete；取消前已经正常产生的非 last endpoint final 必须保留并计入快照，但取消前不得已有 `isLast` 或 complete。正常 session 必须只有一次 `isLast`，随后一次 complete；旧 session 的迟到调用不得终止或污染当前 session。
- 现实操作压力与精度评测分开。生命周期用例只检查状态、归属、顺序、错误码、资源回收和可恢复性，不用文本正确率决定 PASS；声纹只检查“应有分数/应省略分数”的接口契约，不比较相似度精度。
- `user-sequence`、`reentrant`、`start-cancel`、`start-write`、`start-write-reload`、`edge` 和实时 `paced` 是发布前必跑门禁。`start-write-reload` 必须在每轮结束后执行 `shutdown -> unloadModel -> createEngine`，验证首次冷加载和业务空闲卸载后的重新冷加载具有相同的 `onStart` 可用性。至少一组运行超过 60 秒，以区分模型逐步驻留与持续内存泄漏。
- 不得声称“覆盖所有边界”。报告必须列出已覆盖的调用序列、轮数、设备/系统版本、未覆盖的外部故障，以及任何仅为 `INCONCLUSIVE` 的资源指标。

## PR 合入门禁

- 缺陷只有在 canonical branch 包含根因修复和回归测试后才能关闭。demo、交付、客户或实验分支上的
  修复只能作为候选证据，不能视为主线已修复；若暂不能回流主线，必须保留明确的跟踪项和阻塞原因。
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

python3 delivery/harmony-dingqiao/delivery/run_finish_compat_release_gate.py \
  --data-dir "$HOME/Downloads/testdata"

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

真机命令中的次数和语料数量可按耗时调整，但合入前至少要覆盖 `burst`、`paced`、`vad-begin`、`vad-begin-silence`、`voiceprint`、`voiceprint-fallback`、`voiceprint-vad-begin`、`voiceprint-vad-begin-idle`、`cancel`、`cancel-full`、`max-duration`、`edge`、`reentrant`、`start-cancel`、`start-write`、`start-write-reload`、`user-sequence` 和 `numeric-edge`。任何模式失败都应先解释并修复，不能通过放宽全局空结果率掩盖生命周期错误。
