# 鼎桥语音识别 Demo

内部开发默认依赖 `:sdk-dingqiao`；交付给客户的参考工程见
`asr/tools/delivery/pack_dingqiao_demo_source_delivery.sh`（纯 demo 模块 + fat AAR，无 SDK 源码）。

完整交付说明见 **[docs/DINGQIAO_DELIVERY.md](../docs/DINGQIAO_DELIVERY.md)**。

## HarmonyOS 0.3.11 场景模式

- 点击 + VAD、短语音 PTT：显式使用 `recognizerMode=short`。
- 长语音、填单、会议纪要：显式使用 `recognizerMode=long`，固定时长只做 native
  stable-prefix 压缩，不形成公开 Rule3 final。
- 会议纪要启用端侧离线 Speaker Diarization，按稳定的零基 speaker index 显示“说话人 N”，支持
  增量 revision、重叠说话标记与最终聚类回写；PCM 不上传网络。
- 完整模型身份、生命周期和发布门禁见 `../../docs/HARMONY_0.3.11_PARITY.md`。

## 快速构建（内部）

```bash
cd asr/android
./gradlew :samples:dingqiao-demo:assembleDebug
```

与交付 Demo APK 对齐（fat AAR）：

```bash
./gradlew :samples:dingqiao-demo:assembleRelease \
  -PdingqiaoUseFatAar=true \
  -PdingqiaoFatAarPath=build/dingqiao-delivery/dingqiao-asr-v<版本>.aar
```

## 声纹模型

声纹模型已内置在交付 AAR 中，Demo 首次启动会自动准备到工作目录，不需要手动 push `eres2net.onnx`。

## 真机专项的语料前提

通过 `-PdingqiaoEvalAudioDir=/path/to/audio` 把验收 WAV 加入 instrumentation APK。
随包的 `000_enroll.wav` / `001_recognize.wav` 只用于声纹回退门禁，不能证明单次起音或同人身份。

| 用例 | 必需输入 |
| --- | --- |
| `a11a_vadEnd800_publishesEndBeforeAnotherNativeEndpoint` | 显式传入 `-e singleSpeechAsset <文件名.wav>`；输入应为已核对的单次连续语音，不能含会触发重新起音的内部停顿。 |
| `v04d_voiceprintIdsReserveVadBeginGrace_forOnStartSpeakerVad` | 显式传入 `-e speakerVadAsset <文件名.wav>`；识别与 `_声纹.wav` 注册样本须为同一说话人的不同发言，不使用重叠音频。加入用例固定的 300 ms 前置静音后，须核对原生 VAD 的首次语音确认在 1000 ms 内；仅检查首次概率越阈值不够，还须计入默认 250 ms 连续语音确认。默认 `minSegSec=0` 不延长初始等待窗。 |
| `v06_speakerVad_overlapRuns` | 文件名含“重叠”的音频与同前缀的目标说话人 `_声纹.wav`；须记录双方身份及实际重叠区间。可用带身份标注的录音确定性混音，但不能把混音写成客户原录音。 |

保留输入来源、身份标注、SHA-256、裁剪/重采样/混音参数及语音区间核对记录。缺少合格输入时，该项验收不完整，不能换用任意 WAV 或降低结果断言。`singleSpeechAsset` 同样可以通过 Gradle 的 `android.testInstrumentationRunnerArguments.singleSpeechAsset` 属性传入。
