## AmphionRuntime iOS Sample

最小可跑 SwiftUI Demo：按住按钮录音 → 流式 ASR → 实时 partial / final。

## 跑通步骤

1. 在 macOS 上安装 Xcode 15+
2. 编译 xcframework：
   ```bash
   bash asr/ios/build_xcframework.sh
   ```
   产物：`asr/ios/AmphionRuntime.xcframework`
3. 用 Xcode 打开 `asr/ios/Package.swift`（SPM 包）
4. 创建一个新的 SwiftUI App target，复制 `Sample/AmphionRuntimeSampleApp.swift` 与 `ContentView.swift` 进去
5. 给 Sample target 添加：
   - `NSMicrophoneUsageDescription` -> "本 demo 需要使用麦克风演示语音识别"
   - 依赖 SPM Library: `AmphionRuntime`
6. 把模型目录拷到设备 / 模拟器：
   - 真机：iTunes File Sharing 拖 demo/1.0.0/ 到 SampleApp
   - 模拟器：复制 demo/1.0.0/ 到 `~/Library/Developer/CoreSimulator/Devices/<device-uuid>/data/Containers/Data/Application/<app-uuid>/Documents/AsrModels/demo/1.0.0/`
7. Run → Allow Mic 权限 → 按住 "Press & hold to talk"

## 与 Android Sample 行为对照

| 行为 | Android | iOS Sample |
| --- | --- | --- |
| 按住录音 | OnTouchListener (ACTION_DOWN) | DragGesture(minimumDistance: 0).onChanged |
| 释放结束 | ACTION_UP/CANCEL | DragGesture .onEnded |
| 模型导入 | adb push 到 filesDir/AsrModels/demo/1.0.0 | iTunes File Sharing / 模拟器 cp |
| Hotwords 演示按钮 | "Update Hotwords" | "Update Hotwords" |

## 已知限制

- `MicRecorder` 只用了最简的 `installTap` + `AVAudioConverter`。生产环境建议：
  - 切到 AVAudioEngine.outputNode + AVAudioPCMBuffer 缓冲池
  - 处理硬件采样率（48k）→ 16k 的下采样质量
  - 录音中断（电话、Siri）的恢复逻辑
- ZIP 解压在 `ModelDownloader.unzip` 里是 stub；接 ZIPFoundation 后即可工作
