# Privacy

HarmonyOS SDK 为端侧离线识别 SDK。

- SDK 不主动联网。
- SDK 不上传音频、文本或设备信息。
- 录音由业务 App 通过 `AudioCapturer` 自行完成，SDK 只接收 PCM 数据。
- 模型文件在应用包或应用私有目录中使用。
