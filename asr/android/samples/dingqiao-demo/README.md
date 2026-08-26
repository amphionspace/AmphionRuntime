# 鼎桥语音识别 Demo

内部开发默认依赖 `:sdk-dingqiao`；交付给客户的参考工程见
`asr/tools/delivery/pack_dingqiao_demo_source_delivery.sh`（纯 demo 模块 + fat AAR，无 SDK 源码）。

完整交付说明见 **[docs/DINGQIAO_DELIVERY.md](../docs/DINGQIAO_DELIVERY.md)**。

## 0.3.11 场景模式

- 点击 + VAD、短语音 PTT：显式使用 `recognizerMode=short`。
- 长语音、填单、会议纪要：显式使用 `recognizerMode=long`，固定时长只做 native
  stable-prefix 压缩，不形成公开 Rule3 final。
- 会议纪要当前是完全离线的长语音识别 Demo，不接入 Harmony 实验性的联网说话人分离服务。

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
