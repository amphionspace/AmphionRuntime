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

推荐使用自动验收入口代替手工构建：

```bash
# 只检查模型、native、license 和已有 HAP
delivery/harmony-dingqiao/delivery/verify_demo_inputs.sh \
  --hap delivery/harmony-dingqiao/samples/dingqiao-demo/entry/build/default/outputs/default/dingqiao_demo-default-signed.hap

# 构建、检查 HAP、覆盖安装到唯一 USB 设备，并等待页面进入“引擎就绪”
HARMONY_SIGNING_CONFIG=.secure/harmony-signing.json \
  delivery/harmony-dingqiao/delivery/build_install_smoke.sh
```

本地签名文件结构见 `delivery/harmony-dingqiao/delivery/harmony-signing.example.json`，应放在 `.secure/` 下并执行 `chmod 600`。构建脚本只在构建期间临时注入签名配置，退出时恢复仓库文件。设备绑定 license 默认读取 `.secure/current_usb_device_sn.txt`；也可通过 `DINGQIAO_DEVICE_ID_FILE` 指定清单。脚本不会输出口令或明文设备标识。

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

脚本默认只收集已构建产物，不负责启动 DevEco 构建。HAR、signed HAP 或 HAP 内必需资源缺失时会直接失败，不再生成残缺交付包。

## main 分支复现说明

`main` 合入后可以复现功能一致的鸿蒙应用源码与构建流程，但模型、签名、license、HAP/HAR 和 native 构建产物不会入库。干净检出后请先执行：

```bash
git submodule update --init third_party/sherpa-onnx
bash asr/tools/04_build_harmony_so.sh
bash asr/tools/05_package_har_libs.sh
bash asr/tools/08_pack_harmony_assets.sh
```

其中 `04_build_harmony_so.sh` 会自动调用 `apply_sherpa_patches.sh`，把 `third_party/patches/sherpa-amphion/` 中的 patch 应用到 sherpa-onnx；不要提交 `third_party/sherpa-onnx` 的本地工作区改动或 submodule 指针。`08_pack_harmony_assets.sh` 需要本机已有 `asr/android/sdk/src/main/assets/amphion-models/` 模型源文件。

构建 signed HAP 还需要本机 DevEco 签名配置；无签名配置时只能生成未签名或调试产物。即使输入相同，HAP 的签名、时间戳和构建元数据也会影响 hash，因此交付验收以功能和清单一致为准，不承诺字节级一致。

## 验收

| 项目 | 预期 |
| --- | --- |
| native 加载 | `libamphion_asr.so`、`libsherpa-onnx-c-api.so`、`libonnxruntime.so` 可加载 |
| 实时识别 | HAP demo 麦克风实时出 partial/final |
| final 增强 | final 走警务增强，中间结果保持 ASR 原文 |
| TTS 合成 | demo 输入文本可合成 PCM（`onData` 逐块回调），`SYNTHESIZE_AND_PLAY` 可内置播放 |
| 声纹 | 注册/删除接口可调用，embedding native 接入后返回相似度 |
| license | 接口保留，正式包注入鸿蒙公钥验签 |

故障指纹和现场采集命令见 [`TROUBLESHOOTING.md`](./TROUBLESHOOTING.md)。

## TTS

离线 TTS 为独立 SDK（`amphion_tts`），源码与 API 文档见 `tts/harmony/`。底层使用 `sherpa_onnx.OfflineTts`，模型默认从 `rawfile/amphion-tts/<voiceId>/` 读取，默认 voiceId 为 `kokoro-zh-en`。
