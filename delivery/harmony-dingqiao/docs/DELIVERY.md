# HarmonyOS 交付 SOP

## 工程结构

| 目录 | 内容 |
| --- | --- |
| `asr/harmony/` | ASR HAR：`amphion_asr`、`amphion_police`、`amphion_dingqiao` |
| `tts/harmony/` | TTS HAR：`amphion_tts` |
| `delivery/harmony-dingqiao/` | 统一交付聚合层：demo HAP、docs、delivery 脚本 |

## 构建步骤

```bash
# 1) 共享 native（ASR + TTS 共用 sherpa_onnx .so）
bash asr/tools/04_build_harmony_so.sh
bash asr/tools/05_package_har_libs.sh

# 2) 模型资源
bash asr/tools/08_pack_harmony_assets.sh
bash tts/tools/harmony/pack_harmony_tts_assets.sh
```

然后在 DevEco Studio 中构建 HAR 与 HAP：

- `asr/harmony`：`sdk`、`sdk-police`、`sdk-dingqiao`
- `tts/harmony`：`sdk`
- `delivery/harmony-dingqiao`：`dingqiao_demo`（demo 通过 file: 依赖自动拉起上述 HAR）

## 客户包结构

```text
dingqiao-harmony-delivery-<version>/
├── har/
│   ├── amphion_asr.har
│   ├── amphion_police.har
│   ├── amphion_dingqiao.har
│   └── amphion_tts.har
├── demo/
│   └── dingqiao-demo.hap
├── models/
│   └── eres2net.onnx
├── tts-models/
│   └── amphion-tts/
└── docs/
    ├── DINGQIAO_INTEGRATION.md
    ├── DINGQIAO_LICENSE_SCHEME.md
    ├── LICENSE.md
    ├── NOTICE
    ├── PRIVACY.md
    ├── CHANGELOG.md
    └── checksum.txt
```

## 打包脚本

```bash
bash delivery/harmony-dingqiao/delivery/pack_dingqiao_harmony_customer_delivery.sh
```

脚本默认只收集已构建产物，不负责启动 DevEco 构建。

## 验收

| 项目 | 预期 |
| --- | --- |
| native 加载 | `libamphion_asr.so`、`libsherpa-onnx-c-api.so`、`libonnxruntime.so` 可加载 |
| 实时识别 | HAP demo 麦克风实时出 partial/final |
| final 增强 | final 走警务增强，中间结果保持 ASR 原文 |
| TTS 合成 | demo 输入文本可合成 PCM（`onData` 逐块回调），`SYNTHESIZE_AND_PLAY` 可内置播放 |
| 声纹 | 注册/删除接口可调用，embedding native 接入后返回相似度 |
| license | 接口保留，正式包注入鸿蒙公钥验签 |

## TTS

离线 TTS 为独立 SDK（`amphion_tts`），源码与 API 文档见 `tts/harmony/`。底层使用 `sherpa_onnx.OfflineTts`，模型默认从 `rawfile/amphion-tts/<voiceId>/` 读取，默认 voiceId 为 `kokoro-zh-en`。
