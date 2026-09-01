## AmphionRuntime iOS Sample

单页 SwiftUI Demo：通过与 Android/Harmony 同名的鼎桥兼容 API，点击按钮录音或回放
仓库固定 WAV → 流式 ASR → 实时 partial / final。音频固定为 16 kHz、16-bit、mono、小端序，
并按 640 字节（20 ms）调用 `writeAudio`。固定 WAV 入口用于模拟器确定性验证，不依赖麦克风。

## 跑通步骤

1. 在 macOS 上安装完整 Xcode；SDK 支持 iOS 13+，本 SwiftUI Sample 的部署目标为 iOS 15+
2. 编译 xcframework：
   ```bash
   bash asr/ios/build_xcframework.sh
   ```
   产物：`asr/ios/AmphionRuntime.xcframework`
3. 用 Xcode 打开 `asr/ios/Sample/AmphionRuntimeSample.xcodeproj`
4. 选择 iPhone Simulator 或开发者签名的 iPhone；工程已经配置本地 SPM 依赖和
   `NSMicrophoneUsageDescription`
5. 把模型目录拷到设备 / 模拟器：
   - 真机：iTunes File Sharing 拖 demo/1.0.0/ 到 SampleApp
   - 模拟器：复制 demo/1.0.0/ 到 `~/Library/Developer/CoreSimulator/Devices/<device-uuid>/data/Containers/Data/Application/<app-uuid>/Documents/AsrModels/demo/1.0.0/`
   - 增强能力公共模型放到 `Documents/AsrModels/shared/dingqiao/`：
     `eres2net.onnx`、`pyannote-segmentation-3.0.onnx` 及 LICENSE
   - final 后处理资源放到 `Documents/AsrModels/shared/`：
     `punct-zhen/v1/model.int8.ort`（或 `.onnx`）及
     `itn-zh/v1/{zh_itn_tagger.fst,zh_itn_verbalizer.fst}`
6. Run → Allow Mic 权限 → 点击“开始识别”；Demo 默认选中与 Android 一致的“对讲 / 通话”场景，
   不设置 `vadBegin`，会一直保持识别直到用户点击红色停止按钮。只有显式切到“点击+VAD”时才注入
   `vadBegin=5000`，纯静音约 5 秒后按配置自动结束。声纹能力先点击“录制声纹”，录满 3–8 秒后注册。

命令行构建模拟器 Debug App：

```bash
xcodebuild \
  -project asr/ios/Sample/AmphionRuntimeSample.xcodeproj \
  -scheme AmphionRuntimeSample \
  -sdk iphonesimulator \
  -configuration Debug \
  CODE_SIGNING_ALLOWED=NO build
```

Demo 覆盖的客户 API 主链路：

```text
SpeechRecognizeSdk.setWorkPath / setModelDirectory
  → prepareRuntime
  → createEngine(CreateEngineParams)
  → startListening(StartParams)
  → writeAudio(640-byte PCM frames)
  → finish 或 cancel
  → onResult(isFinal/isLast) / onComplete
```

## 与 Android Sample 行为对照

| 行为 | Android | iOS Sample |
| --- | --- | --- |
| 开始/结束录音 | 蓝色开始、红色“识别中 · 点击结束” | 默认 PTT 手动结束；顶部、结果卡和红色停止按钮同步显示识别状态 |
| 模型导入 | adb push 到 filesDir/AsrModels/demo/1.0.0 | iTunes File Sharing / 模拟器 cp |
| 取消当前 session | `cancel(sessionId)` | `cancel(sessionId)` |
| 固定音频回放 | instrumentation fixture | `回放固定 WAV`；沿用页面当前声纹/Speaker VAD/说话人分离配置 |

## 已知限制

- `MicRecorder` 只用了最简的 `installTap` + `AVAudioConverter`。生产环境建议：
  - 切到 AVAudioEngine.outputNode + AVAudioPCMBuffer 缓冲池
  - 处理硬件采样率（48k）→ 16k 的下采样质量
  - 录音中断（电话、Siri）的恢复逻辑
- ZIP 解压在 `ModelDownloader.unzip` 里是 stub；接 ZIPFoundation 后即可工作
- Demo 已提供 `vadBegin`、声纹注册/校验、Speaker VAD 和说话人分离入口；只有公共模型真实存在
  且声纹已注册时才允许开启，状态徽标会区分“可用 / 待录入 / 模型未就绪”。
- 自动标点/ITN 在资源真实加载后按 `ITN → 标点` 处理 final；页面分别显示两项资源状态。
- Police LAC、正式离线授权和 Diagnostics v2 仍未达到客户交付标准；页面保持“运行时未接入”
  状态，不会用绿色开关伪装成功。
