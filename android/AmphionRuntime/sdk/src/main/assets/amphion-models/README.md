# SDK 内置模型资产

> 本目录的内容由 `tools/asr/08_pack_sdk_assets.sh` 写入；不要手工放文件。

构建 AAR 之前必须把全部 5 类模型放到这里，否则 `assembleRelease` 出来的 AAR 在
设备上 first-run 会以 `ASSET_INSTALL_FAILED` 失败。

## 目录布局

```
amphion-models/
├── manifest.json          # 由 08_pack_sdk_assets.sh 自动生成；记录每份资产的 sha256
├── zh-en/v1/              # 中英流式 ASR
│   ├── encoder.int8.onnx
│   ├── decoder.onnx
│   ├── joiner.int8.onnx
│   └── tokens.txt
├── yue-en/v1/             # 粤英流式 ASR
│   ├── encoder.int8.onnx
│   ├── decoder.onnx
│   ├── joiner.int8.onnx
│   └── tokens.txt
├── punct-zhen/v1/         # CT-Transformer 中英标点
│   └── model.int8.onnx
├── itn-zh/v1/             # WeText 中文 ITN
│   ├── zh_itn_tagger.fst
│   └── zh_itn_verbalizer.fst
└── vad/v1/                # silero VAD
    └── silero_vad.onnx
```

## 大小预算

| 资产 | 体积 (~MB) | 说明 |
| --- | --- | --- |
| zh-en | 100~120 | encoder INT8 是大头 |
| yue-en | 100~120 | 同 zh-en |
| punct-zhen | 60~70 | CT-Transformer INT8 |
| itn-zh | 2~4 | tagger + verbalizer fst |
| vad | 2 | silero |

合计 ~270 MB；AAR 体积约 280 MB（含 native .so）。安装后首次启动会一次性
拷贝到 `<filesDir>/amphion-runtime/`，耗时 5~30s（视磁盘速度），之后启动秒开。

## 不入库

实际模型资产（`*.onnx`, `*.fst`, `tokens.txt`, `bbpe.vocab`）走 `.gitignore`：
都是与 encoder ONNX 严格配对的、由 `tools/asr/08_pack_sdk_assets.sh` 一次性
写入的产物，与 git 走不同发布渠道易产生 sha256 错位。只有 `README.md` /
运行期生成的 `manifest.json` 与各级目录占位 `.gitkeep` 进 git。
