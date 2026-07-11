# SDK 内置模型资产

> 本目录的内容由 `asr/tools/08_pack_sdk_assets.sh` 写入；不要手工放文件。

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
都是与 encoder ONNX 严格配对的、由 `asr/tools/08_pack_sdk_assets.sh` 一次性
写入的产物，与 git 走不同发布渠道易产生 sha256 错位。只有 `README.md` /
运行期生成的 `manifest.json` 与各级目录占位 `.gitkeep` 进 git。

## 离线 ONNX 图优化

打包时可显式启用 ONNX Runtime 离线图优化，优化后脚本会重写 `manifest.json`：

```bash
OPTIMIZE_ONNX_GRAPHS=1 \
OPTIMIZE_ONNX_LEVEL=extended \
PYTHON=.venv-onnxopt/bin/python \
bash asr/tools/08_pack_sdk_assets.sh
```

也可以对已打包目录直接执行：

```bash
.venv-onnxopt/bin/python asr/tools/optimize_onnx_graphs.py \
  --root asr/android/sdk/src/main/assets/amphion-models \
  --backup-dir outputs/asr-onnx-backup/android
```

建议 `.venv-onnxopt` 中安装与目标端 `libonnxruntime.so` 匹配的 `onnxruntime`
版本，并安装 `onnx` 用于校验 sherpa 模型 metadata 是否保留。若目标端仍使用
`onnxruntime 1.16.x/1.17.x`，venv 里还需要约束 `numpy<2`。默认优化级别是 `extended`；
`all` 可能写入宿主机/provider 特定 layout 转换，移动端发布前必须实机验证。
