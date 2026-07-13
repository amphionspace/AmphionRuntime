# HarmonyOS 离线 ASR SDK 故障排查

## 1. HAR 无法安装或编译

确认宿主只声明自包含 HAR：

```json5
{
  "dependencies": {
    "amphion_dingqiao": "file:./libs/amphion_dingqiao.har"
  }
}
```

不要再导入或声明 `amphion_asr`、`amphion_police`、`sherpa_onnx`。当前交付要求 HarmonyOS
API 12 或更高版本，只包含 `arm64-v8a` native 库，不支持 x86_64 模拟器。

解压 SDK ZIP 后先验证文件未损坏：

```bash
shasum -a 256 -c docs/checksum.txt
```

## 2. `1002200030`：授权文件不可读

- `setLicense()` 需要应用可读的绝对路径，不能直接传 rawfile 资源名。
- 如 license 随宿主应用保存为 rawfile，应先复制到应用私有目录，再传复制后的路径。
- 正式 license 由安全渠道单独下发，不在 SDK ZIP 中。

## 3. `1002200031`：授权无效

常见原因包括文件被修改、签名不正确、缺少 ASR 能力、SDK 主版本不符或维护期不覆盖当前
SDK 发布日期。不要编辑 license JSON；保留完整回调 message 并联系我方核对签发记录。

## 4. `1002200033`：设备或宿主证书不匹配

- 签发使用硬件 SN，但运行时传入 ODID，或反向混用。
- 当前设备不在白名单，或 `LicenseDeviceIdProvider` 返回空值。
- 普通三方 App 无法取得 `ohos.permission.sec.ACCESS_UDID`，因此读不到硬件 SN。
- license 绑定了宿主签名证书，但当前 HAP 使用了其他证书，或系统未返回证书摘要。

按 SN 签发的正式 license 必须在可读取同一 SN 的系统/预置宿主中验证。不要用普通 Demo
HAP 代替正式宿主做 SN 授权验收。

## 5. `ENGINE_NOT_INITIALIZED` 或创建引擎失败

严格按以下顺序调用：

```text
init → setLicense 成功 → prepareRuntime.onReady → createEngineAsync.onSuccess
```

`setLicense()` 不再隐式准备 Runtime。调用 `unloadRuntime()` 后，授权仍保留，但必须再次
`prepareRuntime()`；调用 `unloadModel()` 后必须重新创建 engine。卸载前先结束会话并
`shutdown()` 所有 engine，不要与正在执行的创建/识别并发卸载。

## 6. `No graph was found in the protobuf` 或模型加载失败

- 确认使用本交付中的原始 `amphion_dingqiao.har`，且 checksum 校验通过。
- 清理宿主的 `oh_modules` 和旧构建缓存后重新 `ohpm install`、重新构建。
- 不要拆包替换 `.ort`、`.onnx`、词表、manifest 或 native `.so`；这些文件必须成套匹配。
- 确认真机为 arm64，系统 API 版本符合要求。

## 7. 实际识别断续、漏字或与离线基准差异明显

首先保存并回放宿主实际写入 SDK 的 PCM。输入必须满足：

- PCM S16LE、16000 Hz、16 bit、单声道。
- 每次 `writeAudio()` **严格 640 字节（20 ms）**，不接受 1280 字节。
- 帧连续、按时间顺序写入，不丢帧、不重复、不并发乱序。
- 收音结束调用 `finish()`，不能直接停止采集后遗留尾部缓存。

如果保存下来的 PCM 本身卡顿，问题位于 AudioCapturer、线程调度、缓冲区复用或宿主写帧
链路，而不是模型精度。不要用录音页面的主线程承担持续音频搬运。

## 8. `NOT_LISTENING`

只在 `startListening()` 成功并收到 `onStart` 后写入音频。确认 `sessionId` 完全一致；
`finish()`、`cancel()`、自动结束或 `shutdown()` 后不要继续写旧会话。

## 9. 声纹没有 `speakerSimilarity`

- `enableVoiceprintVerification=true` 时必须提供至少一个有效 `voiceprintIds`。
- 多个有效 ID 会将 embedding 求平均后作为一个目标；不存在的 ID 会跳过，但不能全部无效。
- 过短的有效语音可能无法提取可靠 embedding；约 1.5 秒以下的有效语音可能没有相似度。
- 声纹样本必须是 16 kHz、16 bit、单声道 PCM WAV，每段 3 到 8 秒。

## 10. 日志采集

复现前清空日志，复现后立即导出：

```bash
hdc shell hilog -r
hdc shell hilog -x > hilog.txt
```

请同时提供：SDK ZIP 的 checksum、设备型号、HarmonyOS 版本、宿主 bundleName、错误码和
message、调用顺序，以及问题音频对应的原始 PCM/WAV。不要在日志中提交明文 SN 或 license。
