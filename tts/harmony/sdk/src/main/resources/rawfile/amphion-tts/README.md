# TTS 模型目录

默认布局（Kokoro 中英双语）：

```text
amphion-tts/
  kokoro-zh-en/
    model.onnx
    voices.bin
    tokens.txt
    espeak-ng-data/
    lexicon-us-en.txt
    lexicon-zh.txt
    date-zh.fst
    phone-zh.fst
    number-zh.fst
```

`TextToSpeechSdk` 默认按 `voiceId` 查找 `rawfile/amphion-tts/<voiceId>/`，其中 `espeak-ng-data/` 会在创建引擎时解包到应用沙箱，其余文件由 sherpa_onnx 直接按 rawfile 相对路径读取。

构建前可把模型放到 `tts/models/amphion-tts/`，再运行：

```bash
bash tts/tools/harmony/pack_harmony_tts_assets.sh
```
