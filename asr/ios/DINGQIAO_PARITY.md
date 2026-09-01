# iOS 鼎桥 SDK 对齐状态

本文以 `shared/api-spec/dingqiao-asr-parameters.json`、Android/Harmony 当前公共模型和
生命周期契约为基线。状态分为“已对齐”“部分对齐”“未对齐”，只有完成相应测试和设备门禁的能力
才能写成客户交付能力。

## 公共 API 与基础 ASR

| 能力 | 状态 | 当前实现与边界 |
| --- | --- | --- |
| 16 kHz 外部 PCM | 已对齐 | PCM16、mono、小端序、固定 640 字节/20 ms；非法帧显式报错 |
| 模型格式 | 已对齐 | 优先 Android/Harmony 的 `.ort` transducer 三件套，兼容 `.onnx` |
| `recognizerMode` | 已对齐 | start > create > continuous fallback；仅接受 short/long |
| 其余公共参数 | 已对齐解析 | `recognitionMode`、`vadBegin/vadEnd`、`maxAudioDuration`、partial、连续模式、hotwords、voiceprint 和 Speaker VAD 数值边界均按共享 schema |
| lifecycle | 已对齐状态机 | finish 前不产生 last；正常结束唯一 last 后唯一 complete；cancel 无新增 final/complete；重复 finish 幂等 |
| `onStart` 重入 | 已对齐 | session 发布后才派发，可在回调栈内 write/finish/cancel |
| unload | 已对齐 L2/L1 边界 | active engine 先 shutdown；finishing session 等 tail，listening session 按 cancel 语义关闭；L2 释放 ASR、ITN/标点与声纹 extractor 内存，保留磁盘模型和 embedding |
| 日志级别 | 已对齐 Swift 层 | `AmphionLogLevel` 与 `setLogLevel`；native 详细日志阈值仍需独立下传 |
| 设备 fingerprint | 已对齐 | SHA-256(uppercase(trim(SN)) + saltId)，大写 hex |
| diagnostics 兼容 API | 部分对齐 | normal build 的 configure 为 no-op、export 明确失败；Diagnostics schema v2 artifact 未实现 |

## 语音与增强能力

| 能力 | 状态 | 当前实现与边界 |
| --- | --- | --- |
| `vadBegin` | 已实现并有状态机单测 | 精确 sample deadline；ASR text/token 永久解除；固定高能量不直接当 speech；覆盖纯静音、稳态高能和变幅语音型信号 |
| `vadEnd` | 已实现 | 映射 native endpoint trailing silence；尚缺真机真实语料标定 |
| 声纹注册 | 已实现 | 1+ 个 3–8 秒 PCM/WAV；校验 16 kHz/16-bit/mono；安全生成 ID；embedding 持久化到 workPath |
| 声纹校验 | 已实现 | 每个有非空 ASR 证据和真实句段 PCM 的 final 独立计算 `speakerSimilarity`，不补假分数 |
| Speaker VAD | 核心公共语义已对齐 | 按 window/hop/threshold/consecutiveBelow 计算状态变化；逐 final 以真实句段 PCM 分数判断，非目标说话人发空 final 与 rejected 事件；可选 target-speaker 音频增强仍未接，因此 `targetSpeakerEnhancementApplied=false` |
| 声纹 + `vadBegin` | 部分对齐 | 默认 `minSegSec=0`，不延长等待；正数 minSegSec/一次性确认窗尚无 iOS 公共配置实现 |
| 离线说话人分离 | 部分对齐 | 公共 pyannote + eres2net、与 Android/Harmony 相同的 metadata-free powerset 解码、独立推理队列、10 秒 finish barrier、重叠说话 mask、speaker turns、utterance assignment/update/result；当前仅对末尾 10 秒做本地说话人编号，尚未移植滑窗 checkpoint、eres2net 跨窗全局聚类和完整 overlap 证据算法 |
| WeText ITN | 代码链路已对齐 | patched sherpa C API 从 tagger/verbalizer FST 创建 processor；Dingqiao final 固定先做 ITN；正式交付仍需冻结资源哈希和专项语料回归 |
| 自动标点 | 代码链路已对齐 | 真实 CT-Transformer native processor 在 ITN 后执行；支持 ORT/ONNX 公共布局；正式交付仍需冻结模型哈希和专项语料回归 |
| Police hotwords/LAC | 未对齐且显式门禁 | 公共 LAC encoder 已共享；iOS 尚缺 LAC runtime、词典/CRF 管线及车牌/警务词/派出所 FST 后处理；开启（含默认 true）会在 start 明确报 unsupported，设置 false 才运行，禁止静默 no-op |
| AGC2 + Silero VAD | 未对齐 | iOS native 音频前处理尚未进入与 ASR 相同 PCM 时间轴 |
| 离线授权 | 未对齐 | 兼容 API 会明确报未支持；iOS App identity、签名证书 digest 与设备 ID provider 契约尚未冻结，不会伪造授权成功 |
| Objective-C facade | 未对齐 | 当前为 Swift API；尚未提供稳定的 `NSObject/@objc` 封装 |

## Demo 对齐

- 使用 Android/Harmony 相同的蓝色主色、浅色页面和卡片层级。
- 场景覆盖点击+VAD、对讲、执法记录、表单、会议；录音源覆盖近场、远场、通话。
- 默认场景与 Android 一致为“对讲 / 通话”，不注入 `vadBegin`；“点击+VAD”页面明确提示
  5 秒纯静音自动结束，避免把显式起音门禁误认为 SDK 断线。
- 普通录音使用顶部红点、红色录音卡和红色停止按钮；声纹录制单独显示 0.1 秒级时长、3 秒合格
  边界和 8 秒自动结束。
- 能力行显示“可用 / 待录入 / 模型未就绪 / 运行时未接入”，缺能力时禁用而不是静默降级。
- Demo 自动保存注册返回的 voiceprint ID，并在开启声纹校验/Speaker VAD 时写入同名
  `voiceprintIds` 参数。

## 已完成验证

- `build_xcframework.sh` 在隔离 worktree 应用了 23 个 Amphion sherpa patches，构建出 device
  arm64 和 simulator arm64/x86_64 XCFramework；canonical submodule 未被修改。
- 固定 ONNX Runtime 1.17.1 归档 SHA-256：
  `8406c942426551f826a73cb968afbe6dbe04cef899e2fe9c17a7ed775cba69f7`。
- iOS Simulator XCTest：21 tests passed；其中真实加载公共 metadata-free pyannote 模型并执行
  160000 samples powerset 推理，防止误接 sherpa metadata diarization API 后再次崩溃。
- Sample 已在 iPhone 17 Pro / iOS 26.5 Simulator 启动；patched provider 配置未再出现旧的
  `Unsupported string ... Fallback to cpu` 警告。
- 默认 PTT 麦克风路径静置 8 秒后仍保持 `start=1、last=0、complete=0`，主动结束后恰好
  `last=1、complete=1`；切换“点击+VAD”后纯静音约 5 秒按配置自动得到唯一 last/complete。
- 最终 Demo 固定 WAV + 说话人分离验证：start=1、final=2、last=1、complete=1；输出 4 个
  speaker turns，并在页面显示带说话人标签的 final；finish 前观测到 last=0。
- 使用本机已从 OSS 获取、未写入 Git 的原始 CT-Transformer ONNX 与 WeText FST 做真实加载；
  Demo 能力徽标显示 ITN/标点可用，固定 WAV final 从中文数词转换为数字并补句末标点，生命周期仍为
  start=1、final=2、last=1、complete=1。

## 客户交付前仍必须完成

1. Police/LAC 与正式离线授权；把已验证的 ITN/标点资源纳入正式 iOS 组包并冻结来源、版本和哈希。
2. Diagnostics schema v2 独立构建和脱敏导出。
3. Speaker VAD target-speaker filtering、完整增量 diarization 算法与长期资源门禁。
4. 当前代码/版本/签名/模型冻结后，在真实 iPhone 执行标准 finish、max-duration、cancel、
   start-write/start-cancel、回调重入、vad-begin 真实语音/纯静音、声纹、Speaker VAD、diarization、
   unload/reload、来电/蓝牙/锁屏恢复；按 sessionId 保存完整回调轨迹。

在以上门禁完成前，本分支是“可运行的 iOS 对齐开发版”，不是可声明与 Android/Harmony 完全等价的
正式客户交付包。
