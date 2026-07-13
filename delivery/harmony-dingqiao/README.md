# Amphion HarmonyOS 鼎桥交付聚合层

本目录是面向鼎桥客户的纯血鸿蒙交付聚合层，本身不包含 SDK 源码，只整合：

- `samples/dingqiao-demo/`：验收 HAP，同时演示 ASR（鼎桥接口）与 TTS。
- `docs/`：集成、授权、隐私、NOTICE 与交付 SOP。
- `delivery/`：客户交付包打包脚本。

SDK 源码分别在：

- `asr/harmony/`：ASR HAR（`amphion_asr` / `amphion_police` / `amphion_dingqiao`）。
- `tts/harmony/`：TTS HAR（`amphion_tts`）。

demo 通过 `oh-package.json5` 的 `file:` 相对路径跨工程引用上述四个 HAR，与仓库内引用上游 `sherpa_onnx` HAR 的方式一致。

## 构建顺序

```bash
# 1) 共享 native（ASR + TTS 共用同一套 sherpa_onnx .so）
bash asr/tools/04_build_harmony_so.sh
bash asr/tools/05_package_har_libs.sh

# 2) 模型资源
bash asr/tools/08_pack_harmony_assets.sh          # ASR 模型 -> asr/harmony
bash tts/tools/harmony/pack_harmony_tts_assets.sh # TTS 模型 -> tts/harmony（可选）

# 3) 用 DevEco Studio 打开本目录 delivery/harmony-dingqiao/，构建 dingqiao_demo HAP
#    （会自动按 file: 依赖构建 asr/harmony 与 tts/harmony 的 HAR）
```

## 交付打包

```bash
bash delivery/harmony-dingqiao/delivery/pack_dingqiao_harmony_customer_delivery.sh
```

脚本只收集已构建产物（HAR/HAP/模型/文档），不负责启动 DevEco 构建。

## 真机压力测试

使用真实 WAV 语料执行连续会话、取消、自动结束、重配置、重建和错误边界测试：

```bash
python3 delivery/harmony-dingqiao/delivery/run_device_stress.py \
  --data-dir ~/Downloads/testdata --mode burst --cycles 200 --files 48
```

模式、门槛、artifact 结构和已验证基线见
[`docs/DEVICE_STRESS.md`](docs/DEVICE_STRESS.md)。

## 模型加载验收

使用独立进程冷启动测量 `createEngineAsync`，并记录设备、系统构建、模型源哈希、native/HAP
哈希、线程数和预热样本数：

```bash
python3 delivery/harmony-dingqiao/delivery/run_model_load_bench.py \
  --device <HDC_TARGET> --warmup-runs 2 --iterations 10
```

当前 `zhen` 配置、真机基线、comparison identity 规则和已拒绝方案见
[`docs/MODEL_LOAD_PERFORMANCE.md`](docs/MODEL_LOAD_PERFORMANCE.md)。

鼎桥 `zhen` 配置默认使用 4 个 ONNX Runtime worker。真机 A/B 表明它小幅降低冷加载 p50，并缩短持续识别耗时，代价是不到 4 MB 峰值 RSS；加载基准会把线程数写入 comparison identity，禁止与 2 线程报告直接套用门槛比较。

`zhen` 不执行创建阶段的静音预热：ORT Session 创建已经完成图初始化和权重预打包，真机测试中额外执行一次 800 ms 静音 decode 会让 engine ready 增加约 93 ms，而首次真实音频只减少约 9 ms。加载基准把预热样本数记录为 0，首轮真实音频延迟由设备压力测试单独守护。

## main 分支复现边界

PR 合入后，`main` 分支包含完整源码、交付工程、声纹模型和 sherpa-onnx patch 序列，可以在同样工具链下编译出功能等价的鸿蒙应用。ASR 大模型、签名证书、license、HAP/HAR 和 native 构建产物仍不入库，因此干净检出后不能只运行 DevEco 构建就得到带完整模型的已签名 HAP。

从干净 `main` 复现时需要先准备这些本地输入：

- 执行 `git submodule update --init third_party/sherpa-onnx`。
- 执行 `bash asr/tools/04_build_harmony_so.sh`；该脚本会调用 `asr/tools/apply_sherpa_patches.sh`，把 `third_party/patches/sherpa-amphion/` 下的 patch 应用到 sherpa-onnx，本分支不提交 submodule 本体改动。
- 执行 `bash asr/tools/05_package_har_libs.sh`，把已构建的 AArch64 native 库同步到 Harmony HAR 源目录。
- 执行 `bash asr/tools/08_pack_harmony_assets.sh`；默认直接读取 `asr/tools/demo-model/zhen`、`asr/tools/demo-model/yueen` 及标点/ITN/VAD 源文件，并用固定 ORT 1.16.3 构建环境预优化中英三图与标点图，不再依赖 Android assets。
- 配置 DevEco 签名后构建 `dingqiao_demo`；无签名配置时只能得到未签名或调试产物。
- 声纹模型 `eres2net.onnx` 已内置在 `amphion_dingqiao` HAR，SDK 会自动准备到工作目录，无需 Demo 或宿主导入。

在相同模型、签名和 SDK 环境下，`main` 可以编译出功能一致的应用；但 HAP 二进制不承诺字节级一致，签名、时间戳和构建元数据都会影响 hash。
