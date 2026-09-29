# 缺陷定位与验证

路径均相对仓库根目录；本文件由根 AGENTS.md 按任务引用，所列约束仍须遵守。

## 最小闭环

1. 修改前写明要改变的行为、必须保持的不变量及不处理的范围。将用户症状转成可失败的断言，先确认一次稳定红灯，保存输入、参数、调用时序、回调和终止原因。
2. 沿数据链路定位第一个错误状态；用内部观测和同输入的正常/可疑状态分叉证伪根因。每次追加重放都必须说明假设、新观测或唯一变化、放弃判据及停止条件，不能用重复长跑替代分析。
3. 修复最内层状态转换，不用吞回调、补假结果、延时或放宽断言掩盖问题。不夹带无关参数、性能或生命周期重构；必要的不同根因修复拆为独立提交。检查 Android/Harmony 同名逻辑。
4. 依次验证原症状、相邻不变量、受影响 SDK 单测/平台构建/真实调用方；运行行为修复须完成相关 USB 真机验证，最后清除临时 debug 日志。发布完整矩阵见 [ASR_VALIDATION.md](ASR_VALIDATION.md)，只运行一次并复用有效证据。
5. 原用例与必要相邻检查通过、无已知相关退化后停止。附属问题记录症状、证据、影响、与主问题关系及状态；后续异常用同条件前后差分或 commit 二分区分新增回归、未修完整及既有缺陷。

超时或结束条件至少保护纯静音结束时间、真实语音不中断、噪声有界结束、分帧无关及 final/last 顺序。原症状用例之外至少有一个相邻不变量用例；同层 token-only、重复 text、回调重入、纯静音和稳态噪声按影响覆盖。

性能与生命周期须组合验证：冷加载期间缓存 PCM，在 onStart 调用栈内同步回放，覆盖继续识别和立即结束；卸载后重载使用可控操作，不机械等待业务空闲时间。

耗时操作开始前说明风险、预计耗时、输出、证据失效条件和停止条件。当前 USB 问题验证仅构建安装 ZH_EN 测试 HAP，不为无关语种增加测试载体；不改变 SDK/HAR 已声明的语种支持。

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
