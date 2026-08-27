# 声纹模型说明（eres2net.onnx）- 纯血鸿蒙

面向鼎桥集成与 Demo 验收。声纹能力使用单个 `eres2net.onnx` 模型（约 38 MB），已内置在 `amphion_dingqiao.har`，行为与 Android 鼎桥 SDK 对齐，宿主无需单独分发或导入模型。

## 1. 模型准备

宿主只需配置可写工作目录：

```ts
SpeechRecognizeSdk.init(context);
SpeechRecognizeSdk.setWorkPath(`${context.filesDir}/amphion_asr_work`);
SpeechRecognizeSdk.prepareRuntime(callback);
```

SDK 直接通过资源管理器加载 HAR 内模型，不复制到 `{setWorkPath}`。`setWorkPath` 只保存已注册的 embedding；`prepareRuntime()` 会准备 Runtime 和默认中英 ASR 模型，但不读取或加载声纹模型。

## 2. 生命周期

| 资源 | 创建/加载时机 | 释放时机 |
| --- | --- | --- |
| HAR 内置 `eres2net.onnx` | 应用安装 | 应用卸载 |
| 内存声纹 extractor | 注册/显式预加载时同步加载；普通声纹识别与 Speaker VAD 会话启动后后台加载 | `unloadModel()` / `unloadRuntime()` |
| 已注册声纹 embedding | `registerVoiceprint()` | `deleteVoiceprint()` 或应用数据清理 |

这样可以让约 38 MB 的 extractor 只在声纹真正使用时进入内存，并和 ASR 模型一起由 `unloadModel()` 确定性卸载。`prepareRuntime()` 预加载默认中英 ASR 模型时不会顺带加载 extractor；HAR 模型和 workPath 中的 embedding 属于持久状态，不跟随内存模型周期删除。

`enableVoiceprintVerification` 和 `enableSpeakerVad` 都会在 ASR 会话启动后后台加载 extractor，ASR 音频写入和中间结果不等待。模型就绪前 Speaker VAD 保持 fail-open；如果模型在 ASR final 产生时仍未就绪，只延后 final 和 `onComplete`，模型就绪后立即完成声纹打分。`preloadVoiceprintModel()` 仍是可选同步接口，可用于确保首帧即具备 Speaker VAD 打分能力或提前消除 final 等待，不是声纹识别的必需调用。

注册、显式预加载和声纹识别都属于 L2，调用前必须先完成 `setLicense()` 和 `prepareRuntime()`。`unloadRuntime()` 保留已验证授权；重新 `prepareRuntime()` 后可继续使用，无需再次 `setLicense()`。

## 3. 注册约束

- 至少 1 条样本，不限制样本数量上限；多段样本只是质量建议。
- 每条样本为标准 WAV 文件，采用 16 kHz、16 bit、单声道 PCM 编码，时长 3~8 秒。
- SDK 不限制已注册声纹条数；持久化数量只受宿主工作目录可用空间约束。
- 注册成功后返回声纹 ID，并把 embedding 保存到 `{workPath}/voiceprints/`。

## 4. 验收

1. 安装并首次打开 Demo，无“导入声纹模型”入口。
2. 声纹注册页录制任意正数段样本；录制 1 段后“注册声纹”即可点击。
3. 注册成功后开启“声纹校验”，严格有效语音达到 `minSegSec` 时使用严格样本评分；严格样本不足，
   但 ASR 有非空 text/token 时，使用本句非空真实 PCM 尝试评分，不因短句质量判断省略结果。SDK
   负责出分，短句风险和业务阈值由调用方承担；没有语音证据、没有真实 PCM 或 extractor 技术上
   无法产生 embedding 时仍返回识别结果，但可以省略相似度。
4. 冷态开启普通“声纹校验”或 Speaker VAD 时 ASR 均可立即开始；Speaker VAD 在模型就绪前保持 fail-open，只有 final 必要时等待模型。
5. 调用 `unloadModel()` 后再次启用声纹，模型可重新加载，已注册声纹仍存在。

常见错误：`1002200020` 通常表示工作目录不可写、内置资源损坏或存储空间不足；`1002200024` 表示传入的声纹 ID 不存在。
