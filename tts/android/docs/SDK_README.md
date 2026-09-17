# Lits TTS Android SDK 3.1

支持 Android 7.0 / API 24 及以上，arm64-v8a，离线中英文语音合成。

## 文件说明

| 路径 | 用途 |
| --- | --- |
| lits-dingqiao-tts-sdk-vocos24k-3.1.aar | SDK 代码、ONNX Runtime 和原生库 |
| external-resources/tts | 配套模型、词典、音素表和文本处理规则 |
| docs/INTEGRATION.md | 原有 Kotlin 接入示例和部署步骤 |
| docs/API.md | 接口、参数、回调、错误码与能力限制 |
| docs/PSEUDOCODE.md | 从初始化到释放的完整调用流程 |
| CHANGELOG.md | 当前版本更新说明 |
| LICENSE / NOTICE | 软件使用条件与第三方声明 |
| CHECKSUMS.txt | 当前包内文件的 SHA-256 校验值 |

## 接入顺序

1. 将 AAR 放到宿主 app/libs，按 [接入说明](docs/INTEGRATION.md) 添加依赖。
2. 将 external-resources/tts 完整复制到应用工作目录的 tts 子目录。
3. 提供已签发的 TTS-ONLY 或 ASR-TTS license 和真实设备 SN，初始化授权。
4. 设置工作目录，创建引擎、注册监听器，再提交文本。
5. 请求结束后根据应用生命周期停止或释放引擎。

AAR 不内置模型；本包不含授权文件、私钥、设备 SN 或测试 APK。使用现有授权，sdkMajor 仍为 1。
默认输出为 24000 Hz、16-bit、单声道 PCM；中英共用 speaker 1，温度 0、两步、50 帧流式。

完整示例见 [INTEGRATION.md](docs/INTEGRATION.md) 和 [PSEUDOCODE.md](docs/PSEUDOCODE.md)。

## 校验文件

在解压目录执行：

```bash
shasum -a 256 -c CHECKSUMS.txt
```
