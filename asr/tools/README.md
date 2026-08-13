# AmphionRuntime 工具链总览

本目录是为「基于 sherpa-onnx 的 AmphionRuntime」准备的 工程辅助脚本与文档，覆盖阶段 A（模型导出与验证）和阶段 B（Android 原生层 .so 编译与打包）。Android 工程在 `asr/android/`。

## 想直接跑 demo？

第一次接触本工程，从 `QUICKSTART.md` 开始：一份从零基础 macOS 一气呵成跑到真机识别的端到端指南，含每一步的预估耗时、验证点、所有踩过的坑的故障排查。 文档已经按照真实跑通过的成功路径写。

```bash
open asr/tools/QUICKSTART.md   # 推荐入口
```

阶段 A（模型导出 / INT8 量化 / Linux 验证）跟阶段 B/C/D 完全解耦：你可以先用 demo 模型跑通工程链路，再把自己导出的模型替换进去。具体怎么换见 QUICKSTART 第 13 节。

## 锁定版本（重要）

| 项 | 版本 | 说明 |
| --- | --- | --- |
| sherpa-onnx | tag v1.13.1 | 锁死，不跟 master |
| onnxruntime (Android) | 1.24.3 | 来自 `csukuangfj/onnxruntime-libs` |
| icefall | 与你训练时一致 | 流式 zipformer recipe |
| AGP / Gradle / Kotlin | 8.4.0 / 8.6 / 1.9.22 | 详见 `ANDROID_TOOLCHAIN.md` |
| Android NDK | r26d (26.3.11579264) | 详见 `ANDROID_TOOLCHAIN.md` |
| Python | 3.10 / 3.11 | 阶段 A 使用 |

## 文档与脚本索引

| 文件 | 阶段 | 作用 |
| --- | --- | --- |
| `QUICKSTART.md` | 全流程 | 零基础 macOS → 真机跑通 demo 的端到端指南，含故障排查表 |
| `MODEL_LAYOUT.md` | A | 最终模型目录结构、tokens.txt、manifest.json 模板 |
| `01_export_to_onnx.md` | A | 用 icefall 现成脚本导出 encoder/decoder/joiner ONNX |
| `02_quantize_int8.md` | A | 用 onnxruntime.quantization 做动态 INT8 量化 |
| `03_verify_onnx.sh` | A | Linux 上跑流式识别，验证 ONNX 与 PyTorch 结果一致 |
| `00_fetch_demo_model.sh` | B 前置 | 下载 sherpa-onnx 官方双语 demo 模型，自动整理为 SDK 标准目录，可选 adb push 到设备 |
| `00_push_my_model.sh` | A 验证 | 把自己导出量化好的 ONNX 模型按 SDK 标准布局 push 到一台已装好 sample 的设备（含文件名/tokens.txt 校验） |
| `ANDROID_TOOLCHAIN.md` | B | 精确到版本号的 Android SDK/NDK/AGP/Gradle/Kotlin 安装清单 |
| `03_build_agc_native.sh` | B | 编译可选的 WebRTC AGC2 音频预处理库（host / Android / Harmony） |
| `ensure_agc_build_tools.sh` | A | 解析或在忽略目录中安装固定版本的 Meson/Ninja，避免不同 worktree 工具漂移 |
| `run_automatic_agc_release_gate.py` | A/B | 分阶段执行 AGC 静态、原症状和发布门禁，尽早阻断旧问题复现 |
| `sync_automatic_agc_evidence.py` | A | 只读校验 AGC 完整评测与实现源码的 SHA-256 绑定；实现变化后必须重跑评测，不能只改哈希 |
| `build_android_agc_release_gate.sh` | B | 在临时克隆中完整构建/验收 Android AAR，避免修改真实 sherpa submodule |
| `generate_android_test_summary.py` | B | 从四套 Gradle XML 生成发布证据所需的严格 Android 汇总 |
| `finalize_automatic_agc_release_gate.py` | B | 归档完整跨端证据并绑定、复核发布账本 |
| `04_build_android_so.sh` | B | 一键交叉编译 arm64-v8a（可选 armeabi-v7a）的 .so |
| `05_package_aar_libs.sh` | B | 把编出来的 .so 拷贝到 SDK 工程的 jniLibs/ 目录 |

## 推荐执行顺序

```bash
# ----- 阶段 A：在你训练所在的 Linux 机器上执行 -----
# A.1 导出 ONNX 三件套
#       请按 01_export_to_onnx.md 执行 icefall 自带的 export-onnx-streaming.py

# A.2 INT8 动态量化（encoder/joiner，decoder 不量化）
#       请按 02_quantize_int8.md 执行

# A.3 在 Linux 上验证 ONNX 模型识别效果（与 PyTorch 比对）
bash asr/tools/03_verify_onnx.sh \
    --exp-dir /path/to/icefall/exp \
    --onnx-dir /path/to/onnx-int8 \
    --tokens /path/to/tokens.txt \
    --bpe-model /path/to/bpe.model \
    --test-wav-scp /path/to/wav.scp \
    --test-text /path/to/text

# 之后整理为 MODEL_LAYOUT.md 描述的标准目录，准备分发

# ----- 阶段 B：在你的 macOS / Linux 工作机执行 -----
# B.1 安装工具链：见 ANDROID_TOOLCHAIN.md

# B.2 编 arm64-v8a 的 AGC2 与 ASR .so
export ANDROID_NDK=/path/to/ndk/26.3.11579264
bash asr/tools/03_build_agc_native.sh android-arm64-v8a
bash asr/tools/04_build_android_so.sh arm64-v8a
# 可选：bash asr/tools/04_build_android_so.sh armeabi-v7a

# B.3 拷贝到 SDK 工程的 jniLibs/
bash asr/tools/05_package_aar_libs.sh

# ----- 阶段 C / D：见 asr/android/ -----
# C：SDK 模块（com.amphion.asr）+ 公开 API + 内部实现 + 模型下载
# D：Sample App + 集成文档 + 隐私合规 + LICENSE/NOTICE
```

## 几个反复出现的概念

### 流式 chunk-based zipformer

我们假设你的 streaming zipformer 训练时使用 chunk-size = 32，left-context-chunks = 4（即 chunk-16-left-128 帧）。导出时这两个参数会被 fusion 进 ONNX，运行时无法改。如果你训练时用了不同参数，请在导出步骤里相应修改。

### tokens.txt

icefall recipe 一般生成 BPE，导出阶段会从 `bpe.model` 派生出 `tokens.txt`。该文件按行映射 token id 到字符串，sherpa-onnx 直接吃这一份；不需要再带 `bpe.model` 到端上。

### INT8 动态量化的范围

针对 transducer 的实践：encoder 用 INT8 收益最大、joiner 也建议 INT8、decoder 体积本身很小并且对精度敏感（embedding lookup + LSTM/Conv），保留 FP32。`02_quantize_int8.md` 会给精确的命令。

## 输出目录

阶段 A 的最终交付物（一个目录，整体打包，作为 1.0.0 版本模型）：

```
asr-streaming-zipformer-zh-en-1.0.0/
├── encoder.int8.onnx
├── decoder.onnx              # 不量化
├── joiner.int8.onnx
├── tokens.txt
├── bpe.model                 # 可选；端上不需要，留作调试
└── manifest.json             # SDK 用来下载校验的清单（结构见 MODEL_LAYOUT.md）
```

阶段 B 的最终交付物（按 ABI 一份，给 SDK 工程使用）：

```
build-android-arm64-v8a/install/lib/
├── libonnxruntime.so
└── libsherpa-onnx-jni.so
```
