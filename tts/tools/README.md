# TTS tools 目录说明

本目录只服务 TTS 产品线；license 签发 / 校验工具已统一迁移到仓库根目录 `tools/license/`，ASR 与 TTS 共用同一份 `amphion-license.lic` 和同一套签发逻辑。

下面统一用 `仓库根目录` 指代 amphion-runtime 仓库根目录。

## 这里放什么

- `verify_transsion_vocos24k_package.py`
  - 当前 Android v2 模型包完整性检查脚本

- `verify_lits_delivery_16k_package.py`
  - 历史 16 kHz HifiGAN 包检查脚本，仅用于旧包排障

- `android/`
  - Android SDK 资源生成、批测、交付打包与校验脚本
  - `pack_lits_tts_android_delivery.sh` 会生成含 AAR、sample APK、Android 源码快照、文档和 `VERSION.txt` 的交付包
  - `verify_lits_tts_android_delivery.sh` 校验交付目录 / zip 是否包含源码与必要合规文件

- `onnx-export/`
  - TTS ONNX 导出、量化和本地验证脚本

- `tn/`
  - Android / HarmonyOS TN 构建、ICU 裁剪和发音回归工具

- `tools/license/`（仓库根目录）
  - Amphion 统一离线 license 签发 / 校验工具
  - ASR / TTS 共用同一份 `amphion-license.lic`、同一套信封格式和同一把 `AMPHION_LICENSE_PUBLIC_KEY`

## 模型包固定位置

Android v2 使用下面这个模型包目录：

```text
tts/tools/trial-export/transsion_lits_en_zh_vocos24k_streaming_proto/0.1.0/
```

放好后目录应当长这样：

```text
amphion-runtime/
└── tts/
    └── tools/
        └── trial-export/
            └── transsion_lits_en_zh_vocos24k_streaming_proto/
                └── 0.1.0/
                    ├── manifest.json
                    ├── lits_hidden_encoder.onnx
                    ├── lits_stream_decoder_chunk.ort
                    ├── lits_stream_decoder_final.ort
                    ├── vocos_vocoder.onnx
                    └── ...
```

## 最小必要文件

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

可选参考文件：

- `onnx_streaming_smoke_hello_world.wav`

说明：

- Android 预检会把 `export_report.json` 和 `vocos_vocoder.export_report.json` 当作必需输入
- `onnx_streaming_smoke_hello_world.wav` 只是导出时附带的参考音频，不参与 Android SDK 构建

## 专有名词怎么改

如果你需要让专有名词、品牌词、缩写按指定读音合成，统一只改 TTS 模型包里的这两个词典：

- 中文专有名词：`tts/tools/trial-export/transsion_lits_en_zh_vocos24k_streaming_proto/0.1.0/chinese_lexicon.txt`
- 英文单词、缩写、品牌词：`tts/tools/trial-export/transsion_lits_en_zh_vocos24k_streaming_proto/0.1.0/cmudict.txt`

不要直接去改 `tts/android/sdk/src/main/assets/...`。这个位置是构建时自动同步出来的副本，不是词典源文件。

词典改完后，需要重新做预检和构建，确认更新后的词典已经重新打进 SDK：

- 先运行 `python ../../tts/tools/verify_transsion_vocos24k_package.py --model-dir ../tools/trial-export/transsion_lits_en_zh_vocos24k_streaming_proto/0.1.0`
- 再运行 `./gradlew :sdk:testDebugUnitTest :sdk:assembleRelease :sample:assembleDebug`

## Android

从 `tts/android` 执行：

```bash
python ../../tts/tools/verify_transsion_vocos24k_package.py --model-dir ../tools/trial-export/transsion_lits_en_zh_vocos24k_streaming_proto/0.1.0
./gradlew :sdk:testDebugUnitTest :sdk:assembleRelease :sample:assembleDebug
```

详细说明见：

- [../android/README.md](../android/README.md)
- [../android/docs/DELIVERY.md](../android/docs/DELIVERY.md)

Android 对外交付打包：

```bash
bash tts/tools/android/pack_lits_tts_android_delivery.sh 0.1.0
```

产物在 `../delivery/lits-tts-android-sdk-v0.1.0/`，其中 `demo/lits-tts-sample-debug.apk` 可直接安装验证，`android-src/TTS/` 是随包提供的 Android 源码快照。
