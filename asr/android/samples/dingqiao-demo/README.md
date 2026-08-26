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

## Demo 功能与操作

- 主页提供对讲、执法记录、会议、近场和远场场景，并按场景锁定或建议录音源。
- 点击“开始识别”后，主状态卡、录音标记和停止按钮同时进入高亮录音态；停止后恢复待机色。
- 热词、声纹注册、声纹删除和调试记录从右上角菜单进入。
- 未注册声纹时开启“声纹校验”或“说话人 VAD”，Demo 会直接引导到注册页；注册成功后再开启对应能力。

### 声纹录制状态

声纹注册页会显示 100 ms 精度的录制计时和分段引导：

| 录制时长 | Demo 提示 | 处理建议 |
| --- | --- | --- |
| 小于 3 秒 | 时长不足 | 继续说话 |
| 3–8 秒 | 时长合格 | 可结束当前段 |
| 大于 8 秒 | 超过建议时长 | 结束并重新录制该段 |

录制或正在注册时，“注册声纹”按钮保持禁用。这些 3–8 秒提示是 Demo 引导，不会改变 SDK 的 `TargetSpeakerConfig.minSegSec=0` 契约；SDK 仍对已确认且具有真实 PCM 的语音按公共接口尝试声纹评分。

## 界面色彩

Demo 使用与 HarmonyOS 示例接近的蓝色主色和浅色卡片；红色表示正在录音或需要立即处理的状态，绿色状态点表示录音正在进行。

## 验证

```bash
cd asr/android
./gradlew --no-daemon \
  :samples:dingqiao-demo:testDebugUnitTest \
  :samples:dingqiao-demo:assembleDebug \
  --console=plain
```

真机安装：

```bash
adb -s <device-serial> install -r \
  samples/dingqiao-demo/build/outputs/apk/debug/dingqiao-demo-debug.apk
adb -s <device-serial> shell am start \
  -n com.amphion.dingqiao.demo/.MainActivity
```
