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
