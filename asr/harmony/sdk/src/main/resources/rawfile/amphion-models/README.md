# Harmony SDK 内置模型资产

> 本目录由 `asr/tools/08_pack_harmony_assets.sh` 原子生成；不要手工放文件。

构建 HAR/HAP 前必须先运行上述脚本。脚本直接读取 `asr/tools/demo-model/zhen` 等
源模型，把中英 ASR 三图与标点图预优化成 ONNX Runtime 1.16.3 的 ARM/CPU ORT 格式，
写入 manifest v2 并完成 SHA-256 校验后，才会替换本目录。

## 目录布局

```
amphion-models/
├── manifest.json          # v2：源/输出 SHA、格式、转换器与 Harmony target
├── zh-en/v1/              # 中英流式 ASR
│   ├── encoder.int8.ort
│   ├── decoder.int8.ort
│   ├── joiner.int8.ort
│   ├── tokens.txt
│   └── bbpe.vocab
├── yue-en/v1/             # 粤英流式 ASR
│   ├── encoder.int8.onnx
│   ├── decoder.onnx
│   ├── joiner.int8.onnx
│   ├── tokens.txt
│   └── bbpe.vocab
├── punct-zhen/v1/         # CT-Transformer 中英标点
│   └── model.int8.ort
├── itn-zh/v1/             # WeText 中文 ITN
│   ├── zh_itn_tagger.fst
│   └── zh_itn_verbalizer.fst
└── vad/v1/                # silero VAD
    └── silero_vad.onnx
```

## 大小预算

| 资产 | 体积 (~MB) | 说明 |
| --- | --- | --- |
| zh-en | ~164 | zhen INT8 三图的 ORT 产物 |
| yue-en | ~175 | 保持 ONNX，decoder 为 FP32 |
| punct-zhen | ~72 | CT-Transformer INT8 ORT |
| itn-zh | ~1.3 | tagger + verbalizer FST |
| vad | ~0.7 | silero |

模型合计约 413 MB。Harmony rawfile 在 HAP 中按 Stored 方式打包，运行时优先使用
rawfile descriptor + mmap 直载，不会先整体复制到 `<filesDir>`；若平台不给 descriptor，
native loader 才回退到兼容的读取路径。

## 不入库

实际模型资产（`*.ort`, `*.onnx`, `*.fst`, `tokens.txt`, `bbpe.vocab`）走
`.gitignore`。它们必须由同一次 Harmony 打包生成，避免模型、词表和 manifest
跨发布渠道后 SHA 错位；git 只保留本说明与目录占位文件。
