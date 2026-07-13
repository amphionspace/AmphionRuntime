# 声纹模型说明（eres2net.onnx）- 纯血鸿蒙

面向鼎桥集成与 Demo 验收。声纹能力使用单个 `eres2net.onnx` 模型（约 38 MB），已内置在 `amphion_dingqiao.har`，行为与 Android 鼎桥 SDK 对齐，宿主无需单独分发或导入模型。

## 1. 模型准备

宿主只需配置可写工作目录：

```ts
SpeechRecognizeSdk.init(context);
SpeechRecognizeSdk.setWorkPath(`${context.filesDir}/dingqiao_work`);
SpeechRecognizeSdk.prepareRuntime(callback);
```

SDK 会把 HAR 内的模型幂等准备到 `{setWorkPath}/eres2net.onnx`。`prepareRuntime()` 会做一次尽力准备；注册声纹、预加载声纹和启用声纹识别时都会重试，因此声纹准备失败不会阻断纯 ASR 运行时。

## 2. 生命周期

| 资源 | 创建/加载时机 | 释放时机 |
| --- | --- | --- |
| HAR 内置 `eres2net.onnx` | 应用安装 | 应用卸载 |
| 工作目录模型副本 | 首次 `prepareRuntime()` 或首次使用声纹 | 应用数据清理；`unloadModel()` 不删除 |
| 内存声纹 extractor | 注册/显式预加载时同步加载；普通声纹识别后台加载；Speaker VAD 启动前同步加载 | `unloadModel()` / `unloadRuntime()` |
| 已注册声纹 embedding | `registerVoiceprint()` | `deleteVoiceprint()` 或应用数据清理 |

这样可以让 L1 `prepareRuntime()` 保持“运行时就绪、不加载推理权重”的语义；约 38 MB 的 extractor 只在声纹真正使用时进入 L2，并和 ASR 模型一起由 `unloadModel()` 卸载。磁盘模型和 embedding 属于持久状态，不应跟随内存模型周期删除。

普通 `enableVoiceprintVerification` 会在 ASR 会话启动后后台加载 extractor，ASR 音频写入和中间结果不等待；如果模型在 ASR final 产生时仍未就绪，只延后 final 和 `onComplete`，模型就绪后立即完成声纹打分。`enableSpeakerVad` 需要在流式阶段持续打分，因此冷态 `startListening()` 会同步等待 extractor。`preloadVoiceprintModel()` 仍是可选同步接口，可用于提前消除 final 等待或 Speaker VAD 冷启动，不是普通声纹识别的必需调用。

## 3. 注册约束

- 至少 1 条样本，不限制样本数量上限；多段样本只是质量建议。
- 每条样本为 16 kHz、16 bit、单声道 PCM/WAV，时长 3~8 秒。
- 注册成功后返回声纹 ID，并把 embedding 保存到 `{workPath}/voiceprints/`。

## 4. 验收

1. 安装并首次打开 Demo，无“导入声纹模型”入口。
2. 声纹注册页录制任意正数段样本；录制 1 段后“注册声纹”即可点击。
3. 注册成功后开启“声纹校验”，final 结果携带 `speakerSimilarity`。
4. 冷态开启普通“声纹校验”时 ASR 可立即开始；只有 final 必要时等待模型。冷态开启 Speaker VAD 时启动会等待模型就绪。
5. 调用 `unloadModel()` 后再次启用声纹，模型可重新加载，已注册声纹仍存在。

常见错误：`1002200020` 通常表示工作目录不可写、内置资源损坏或存储空间不足；`1002200024` 表示传入的声纹 ID 不存在。
