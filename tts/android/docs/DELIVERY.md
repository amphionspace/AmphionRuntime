# 从源码构建 SDK

本文面向第一次拿到源码工程的协作者，目标是从 0 构建出 Android TTS SDK AAR 和可安装验证 App。

当前交付模型：

| 项 | 值 |
| --- | --- |
| 模型 ID | `transsion_lits_en_zh_vocos24k_streaming_proto` |
| 模型版本 | `0.1.0` |
| 声码器 | `vocos` |
| 采样率 | 24000 Hz |
| 运行时格式 | ONNX + ORT |

最终产物：

```text
tts/android/sdk/build/outputs/aar/sdk-release.aar
tts/android/sample/build/outputs/apk/debug/sample-debug.apk
```

## 1. 最短路径

1. 准备 Android SDK、JDK 17、Python 3。
2. 把完整模型包复制到仓库根目录：

```text
tools/trial-export/transsion_lits_en_zh_vocos24k_streaming_proto/0.1.0/
```

3. 进入 Android 工程：

```bash
cd tts/android
```

4. 校验模型包并构建：

```bash
python ../../tts/tools/verify_transsion_vocos24k_package.py --model-dir ../../tools/trial-export/transsion_lits_en_zh_vocos24k_streaming_proto/0.1.0
./gradlew :sdk:testDebugUnitTest :sdk:assembleRelease :sample:assembleDebug
```

如果模型包在其他目录，可通过 Gradle 属性或环境变量覆盖：

```bash
./gradlew :sdk:assembleRelease -PLITS_TTS_MODEL_DIR=/path/to/transsion_lits_en_zh_vocos24k_streaming_proto/0.1.0
```

## 2. 环境前提

- JDK 17
- Android SDK
- Python 3
- 完整模型包 `transsion_lits_en_zh_vocos24k_streaming_proto/0.1.0`

工程内已包含 Gradle Wrapper、ONNX Runtime Java classes jar、`arm64-v8a` JNI 动态库、SDK 源码、单元测试和 sample App 源码。

## 3. Android SDK 路径

Gradle 必须能找到本机 Android SDK。二选一即可：

```properties
# tts/android/local.properties
sdk.dir=/Users/me/Library/Android/sdk
```

或设置：

```bash
export ANDROID_HOME=/Users/me/Library/Android/sdk
export ANDROID_SDK_ROOT=$ANDROID_HOME
```

## 4. 模型包清单

最少需要以下 17 个文件：

- `manifest.json`
- `export_report.json`
- `vocos_vocoder.export_report.json`
- `frontend_golden.json`
- `chinese_lexicon.txt`
- `chinese_lexicon.bin`
- `cmudict.txt`
- `cmudict.bin`
- `pinyin_2_bpmf.txt`
- `polychar.txt`
- `zh_en_symbols.json`
- `pinyin_to_tokens.json`
- `arpabet_to_tokens.json`
- `lits_hidden_encoder.onnx`
- `lits_stream_decoder_chunk.ort`
- `lits_stream_decoder_final.ort`
- `vocos_vocoder.onnx`

不需要 checkpoint，也不需要执行导出脚本。`onnx_streaming_smoke_hello_world.wav`、decoder 实验目录和 fp16 实验文件不参与正常 Android v2 构建。

Gradle 会在 `preBuild` 阶段把模型同步到：

```text
tts/android/sdk/src/main/assets/lits-models/tts/transsion_lits_en_zh_vocos24k_streaming_proto/0.1.0/
```

这个目录是构建时生成的，不要手动维护。

## 5. 正式交付包

裸 AAR 适合本地验证；正式对外交付请从仓库根目录执行：

```bash
bash tts/tools/android/pack_lits_tts_android_delivery.sh 0.1.0
```

正式打包要求工作区干净。只做本地预览时可显式放开：

```bash
LITS_TTS_ALLOW_DIRTY=1 bash tts/tools/android/pack_lits_tts_android_delivery.sh 0.1.0
```

如果模型包在外部目录：

```bash
LITS_TTS_MODEL_DIR=/path/to/transsion_lits_en_zh_vocos24k_streaming_proto/0.1.0 \
  bash tts/tools/android/pack_lits_tts_android_delivery.sh 0.1.0
```

交付包结构：

```text
delivery/lits-tts-android-sdk-v0.1.0/
├── aar/lits-tts-sdk-0.1.0.aar
├── demo/lits-tts-sample-debug.apk
├── android-src/TTS/
├── docs/
├── README.txt
└── VERSION.txt
```

`android-src/TTS/` 是从 git-tracked 源码生成的快照，并叠加本次构建使用的模型包，便于收包方从源码重建 AAR。它不会包含 `local.properties`、Gradle `build/` 产物、私钥、`.pem` 或生成的 `sdk/src/main/assets/`。

校验交付目录或 zip：

```bash
bash tts/tools/android/verify_lits_tts_android_delivery.sh ../delivery/lits-tts-android-sdk-v0.1.0/
bash tts/tools/android/verify_lits_tts_android_delivery.sh ../delivery/lits-tts-android-sdk-v0.1.0-YYYYMMDD.zip
```

## 6. AAR 自检

构建成功后，AAR 至少应包含：

- `classes.jar`
- `proguard.txt`
- `libs/onnxruntime-android-1.24.3-classes.jar`
- `jni/arm64-v8a/libonnxruntime.so`
- `jni/arm64-v8a/libonnxruntime4j_jni.so`
- `assets/lits-models/tts/transsion_lits_en_zh_vocos24k_streaming_proto/0.1.0/manifest.json`
- `assets/lits-models/tts/transsion_lits_en_zh_vocos24k_streaming_proto/0.1.0/lits_hidden_encoder.onnx`
- `assets/lits-models/tts/transsion_lits_en_zh_vocos24k_streaming_proto/0.1.0/lits_stream_decoder_chunk.ort`
- `assets/lits-models/tts/transsion_lits_en_zh_vocos24k_streaming_proto/0.1.0/lits_stream_decoder_final.ort`
- `assets/lits-models/tts/transsion_lits_en_zh_vocos24k_streaming_proto/0.1.0/vocos_vocoder.onnx`

## 7. 真机验收建议

- 安装 `sample-debug.apk` 后能进入页面。
- 首次加载模型成功，日志或页面展示 `model=transsion_lits_en_zh_vocos24k_streaming_proto`、`mode=streaming`。
- `zh-en` 和 `en-US` 都能合成。
- `SYNTHESIZE_ONLY` 能收到 `onData` 分片，`sampleRate=24000`。
- `SYNTHESIZE_AND_PLAY` 能直接播放，并收到 `SYNTHESIS_COMPLETE` 和 `PLAYBACK_COMPLETE`。
- 杀进程重启后模型不应重复全量解包；清应用数据后会重新解包。

## 8. 常见问题

### `SDK location not found`

Gradle 找不到 Android SDK。检查 `tts/android/local.properties`、`ANDROID_HOME` 或 `ANDROID_SDK_ROOT`。

### 模型包校验失败

优先检查目录是否为：

```text
tools/trial-export/transsion_lits_en_zh_vocos24k_streaming_proto/0.1.0/
```

再检查 17 个必需文件是否都存在。

### AAR 里缺模型或 JNI 库

优先检查：

- 构建前模型包是否已放到 `tools/trial-export/...`，或 `LITS_TTS_MODEL_DIR` 是否指向正确目录。
- `sdk/src/main/jniLibs/arm64-v8a/` 是否包含 `libonnxruntime.so` 和 `libonnxruntime4j_jni.so`。
- 构建日志里是否出现 `packLitsTtsSdkAssets`，且不是 `NO-SOURCE`。

## 9. 当前限制

- 当前只提供 `arm64-v8a` native 库。
- 当前只支持 `RunMode.OFFLINE`。
- `modelLoadOnCreate=false` 当前不支持。
- 普通 AAR 只能限制单进程内最多 3 个 engine 实例，不能可靠限制全设备跨 App 实例数。
