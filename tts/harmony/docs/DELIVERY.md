# Git 上传与模型交接

本文只回答两个问题：

1. 哪些文件应该进 Git 分支
2. 哪些文件应该单独发给负责人

## 1. Git 分支保留什么

HarmonyOS TTS 分支里，保留的是“能从源码重新构建出 SDK 的最小必要工程”，不是模型资产包。

应该进 Git 的内容：

```text
HarmonyOS/
├── README.md
└── AmphionRuntime/
    ├── AppScope/
    ├── docs/
    ├── sample/
    ├── hvigor/
    ├── sdk/
    ├── build-profile.json5
    ├── hvigorfile.ts
    ├── oh-package.json5
    └── README.md
```

同时，仓库根目录还需要保留：

```text
tools/README.md
tools/verify_lits_harmony_package.mjs
tools/trial-export/lits_delivery_16k_hifigan/1.0.0/.gitkeep
```

## 2. 不要上传什么

以下内容不要进 Git：

- `tools/trial-export/lits_delivery_16k_hifigan/1.0.0/` 里的真实 `.onnx/.json/.txt/.wav`
- `HarmonyOS/AmphionRuntime/.hvigor/`
- `HarmonyOS/AmphionRuntime/.ohos/`
- `HarmonyOS/AmphionRuntime/**/build/`
- `HarmonyOS/AmphionRuntime/verification/out/`
- 任何本机签名文件：`.p12`、`.cer`、`.p7b`
- 任何临时生成的签名配置或手工签名结果

原因很简单：

- 模型包是单独交付资产，不应进源码仓库
- `.hvigor/.ohos/build` 都是本机生成物
- 签名材料属于个人或设备环境，不属于 SDK 源码交付

## 3. 负责人单独接收什么

负责人单独接收完整模型包目录：

```text
LitsTtsSdk/tools/trial-export/lits_delivery_16k_hifigan/1.0.0/
```

至少包括：

- `manifest.json`
- `lits_acoustic.onnx`
- `hifigan_vocoder.onnx`
- `smoke_tokens.json`
- `frontend_golden.json`
- `chinese_lexicon.txt`
- `cmudict.txt`
- `pinyin_2_bpmf.txt`
- `polychar.txt`
- `zh_en_symbols.json`
- `pinyin_to_tokens.json`
- `arpabet_to_tokens.json`

如果已有，也建议一并发过去：

- `export_report.json`
- `onnx_smoke_hello_world.wav`

## 4. 最终交付物分别是什么

需要区分三类东西：

1. Git 分支交付物
   - 可从源码重建 HarmonyOS SDK 的工程

2. SDK 产物
   - `HarmonyOS/AmphionRuntime/sdk/build/default/outputs/default/sdk.har`

3. 本地验证产物
   - `HarmonyOS/AmphionRuntime/sample/build/default/outputs/default/sample-default-unsigned.hap`
   - 它只是验证 HAR 的宿主 HAP，不是最终 SDK 交付物

## 5. 当前交接口径

当前 HarmonyOS 工程已经满足：

- 有独立的 `HarmonyOS` 目录入口
- 有可构建的 HAR 工程
- 有真实 ONNX 推理和播放实现
- 有宿主 HAP 验证工程
- 文档写清了模型放置位置、构建方法、交付边界

当前仍需要接手人自己补的外部条件只有一个：

- 如果要在具体 HarmonyOS 真机安装 `sample` 做验证，需要使用该设备信任的调试签名重新签 HAP
