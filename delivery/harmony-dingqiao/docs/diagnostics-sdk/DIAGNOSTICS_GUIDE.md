# Amphion ASR Diagnostics SDK

Diagnostics HAR 与普通交付使用相同模块名、Bundle Name、版本和公开识别接口。客户只需替换四个 HAR，原有 startListening、writeAudio、finish、cancel、shutdown 和回调代码不需要修改。

## 唯一开关

诊断能力只由编译模式控制：

- diagnostics：诊断全开，自动采集结构化事件、识别文本、公共 writeAudio 输入 PCM、SDK/队列指标、现有 Runtime hilog 和资源状态。
- debug：诊断硬关闭。
- release：诊断硬关闭。

没有运行时模式、音频开关或文本开关，也不需要客户修改业务代码。构建命令为：

    bash delivery/harmony-dingqiao/delivery/pack_diagnostics_sdk.sh

产物位于：

    delivery/harmony-dingqiao/build/diagnostics-sdk/Amphion-ASR-Diagnostics-SDK.zip

默认交付包只构建并包含四个 diagnostics HAR，不依赖本机应用签名。需要同时附带已签名的诊断 Demo 时，使用：

    INCLUDE_SIGNED_DEMO=true bash delivery/harmony-dingqiao/delivery/pack_diagnostics_sdk.sh

此时 Demo 的 Bundle Name、证书和签名 Profile 必须互相匹配。

## 采集行为

- 音频采集点位于参数校验通过后、进入异步和 native 队列前，因此 WAV 与客户实际调用 writeAudio 的有效 PCM 一致。
- writeAudio 只写入有界内存，不进行同步文件 I/O。
- 单 session 滚动保留最近 5 分钟音频；达到上限后丢弃最旧 PCM，识别本身不受影响。
- 活跃 session 每 5 秒生成一次崩溃恢复 journal。
- session 结束后自动写入应用沙箱；也可以调用 exportDiagnostics 主动导出最新快照。
- 诊断目录总上限 200 MB，最多保留最近 3 个 run，超限自动删除最旧 run。

主动导出接口：

    SpeechRecognizeSdk.exportDiagnostics({
      onSuccess: (path: string): void => console.info(`diagnostics=${path}`),
      onError: (code: number, message: string): void => console.error(`${code}: ${message}`)
    });

## 从设备收集

连接手机后执行：

    python3 tools/collect_asr_diagnostics.py --device auto --last 1 --note "问题描述"

工具默认读取 main 当前随包 Demo 的 com.amphion.asr.harmony.demo，并通过 bm dump 自动识别 HAP module。客户应用使用其他 Bundle Name 时传入 --bundle；多 HAP 应用同时传入 --module。

工具会校验 manifest、WAV 和结构化事件，过滤无关 session，脱敏 hilog，生成 ZIP 和 SHA-256。默认保留异常 session；没有异常时只保留最新 session。需要完整 run 时传入 --include-all-sessions。

## 诊断包内容

- manifest.json、summary.json、effective-config.json
- build-identity.json、model-manifest.json、native-state.json
- events.ndjson、callbacks.ndjson、resource-samples.csv
- 每个 session 的 timeline.json、result.json、sdk-input.wav 和 sdk-input.json
- 崩溃恢复场景的 crash-recovery.json

summary 会标记无 final、空 final、提前 isLast、自动结束、回调错误、PCM 时长、截断状态、回调延迟和下一轮可用性。已有非空 final 后，finish 触发的空 isLast 冲刷不会误报 empty-final；整个 session 从未产生有效 final 时仍会标记 empty-final。

## 对识别链路的影响

诊断接入只观察公开输入、公开回调、队列计数和已有 Runtime metrics。它不修改模型、解码、VAD、热词、警务后处理、声纹算法或 session 状态机。普通 debug/release 构建不会安装观察器，也不会复制音频、创建诊断事件或执行诊断文件 I/O。
