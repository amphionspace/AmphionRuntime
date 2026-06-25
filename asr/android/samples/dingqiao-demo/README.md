# 鼎桥语音识别 Demo

内部开发默认依赖 `:sdk-dingqiao`；交付给客户的参考工程见
`asr/tools/delivery/pack_dingqiao_demo_source_delivery.sh`（纯 demo 模块 + fat AAR，无 SDK 源码）。

完整交付说明见 **[docs/DINGQIAO_DELIVERY.md](../docs/DINGQIAO_DELIVERY.md)**。

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
