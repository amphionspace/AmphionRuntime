# ASR 模型目录

默认布局（与 Android bundle 一致）：

```text
amphion-models/
  zh-en/v1/
    encoder.int8.onnx
    decoder.onnx
    joiner.int8.onnx
    tokens.txt
    bbpe.vocab
  punct-zhen/v1/model.int8.onnx
  itn-zh/v1/{zh_itn_tagger.fst,zh_itn_verbalizer.fst}
  vad/v1/silero_vad.onnx
```

构建前可从 Android assets 同步：

```bash
bash asr/tools/08_pack_harmony_assets.sh
```
