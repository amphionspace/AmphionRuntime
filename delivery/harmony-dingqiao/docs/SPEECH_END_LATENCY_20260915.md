# SPEECH_END 延迟定位

基线：`origin/main` 的 `502b3cc2`；修复分支：`fix/harmony-speech-end-latency`。

## 范围与不变量

- 改变：`vadEnd` 从 native VAD 已确认的语音尾边界计时，避免重复计算内部静音确认窗；
  已进入声学静音时，保留换人证据但把昂贵的细化放到结束事件之后。
  恢复起音时先处理待定换人边界，再允许新分数清理旧状态；真实 PCM 后缀由原有路径重放。
- 保持：纯静音 `vadBegin`、真实语音不中断、噪声有界结束、相同 PCM 的尾静音计时不受
  写入分帧影响、真实换人顺序和 PCM 归属、声纹出分资格、回调内 `finish/cancel`、
  正常结束唯一 last 后唯一 complete。
- 不处理：VAD 模型对背景声音的分类精度、背景运行调度、性能架构改造、交付组包。
  既有单个大块混合语音与静音的聚合问题独立跟踪，不作为此次现场根因。

## 现场证据

通过用户指定的 `lark-cli` 读取飞书文档（revision 178）和本节两个 WAV、两个日志。
原件保存在本地受限诊断目录，不提交客户 PCM、识别文本和身份信息。

| 场景 | 证据 | 结论 |
| --- | --- | --- |
| Speaker VAD 开启 | 最后 partial 14:14:57.631；departure 58.278；await-context 58.603；声学细化 59.216–15:00.719（1503ms）；ENDPOINT 00.942 | 切分细化阻塞有序音频处理，事件等待边界求解完成。不能通过跳过有序输入解决。 |
| 普通模式 | 最后 partial 14:34:28.521；native ENDPOINT 30.456，公开事件 30.460 | 1939ms 是 partial 到事件，不是真实停说到事件；适配层只增加约 4ms。 |

同模型、默认参数的 host native VAD 分析：开启 Speaker VAD 的录音只有一个已完成语音段，
尾边界 40032 samples（2502ms），检测状态在 44032 samples（2752ms）转为静音。
现有外层再累计 1600ms，在 69120 samples（4320ms）才会触发，较 native 尾边界多等 218ms。
这属于重复计算静音确认窗，与更长的说话人细化等待分别验证。

普通录音在 4.928s、6.336s 再次进入 native speech，故没有连续 1600ms 的声学静音窗口。
这是附属观测；目前不能仅凭日志区分背景真实语音和模型误判，不能宣称该录音应该在最后
partial 后固定 1600ms 结束。未改变 VAD 模型或阈值。

## 最小红灯与局部修复

- 原始生产 VAD 方法在相同 native timeline 上于 69120 samples 才结束，违反尾边界后
  1600ms（25600 samples）加一个 512-sample 判定窗的断言；同步、异步路径均失败。
- 原始生产 enqueue/evaluate 方法使用客户分数序列 `0.656, 0.621, 0.520, 0.245, 0.021`，
  在声学已静音时仍进入细化。修复后保持每个分数及 departure 证据，延后细化，不能直接提交
  未过滤的 speculative final。慢分数与快分数、恢复起音、事件内 finish 同时验证。
- Harmony 和 Android 的尾静音计时均读取 native segment 尾位置，segment 与检测器在同一
  reset 边界清零。Android 无 Harmony 的细化等待路径，保留其现有 Speaker VAD 生命周期。
- USB 基线：PSN-AL00 / OpenHarmony-6.0.2.130；同一客户录音，20ms 实时输入，
  普通 / Speaker VAD 分别为 **1802ms / 1799ms**，均 FAIL。事件内 finish 的 last/complete
  与非空文本、开启声纹的出分正常。
- USB 注册使用同一客户录音的前 3 秒真实 PCM，未重复或补静音；原注册素材未提供，
  本机分数较高，未命中现场 3 秒以上的分支。该分支以现场日志及生产方法分数序列差分验证，
  不宣称已用原客户声纹完成真机复现。
- main 的交付 Demo 版本为 313，低于设备已有的 314；仅交付 Demo 的 AppScope 对齐
  已安装版本 314 以保留设备数据。SDK 版本、授权、签名和模型不变。

待补：最终修复提交的 Harmony 构建和同条件 USB 差分、必要相邻公共 API 验收。
Host native VAD 结果仅用于定位，不能替代鸿蒙真机验收。
