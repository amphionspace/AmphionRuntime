# NMNet 学生角色分离替换进度

2026-10-15，分支 `feat/nmnet-student-diarization`。状态：N-API/JNI、双端会话路由及五图资源已接入学生后端；Harmony 四个 Release HAR、Android 三个 Release AAR 构建通过。尚未通过正式交付验收。

## 范围和不变量

- 目标：替换 Community-1 分割、WeSpeaker、PLDA/VBx 为学生分割、ECAPA、历史 centroid AHC 与因果重叠重建。
- 固定输入：16 kHz、320000 float PCM + validSamples，20 秒窗口/2 秒步长；只用真实音频选样。50 chunk 压缩、最小支持数 4、距离阈值 0.67。
- 保持：ASR、原句/文字来源、公开 final/last/complete 顺序、cancel 关闭、generation 归属、已提交结果冻结和离线推理。
- 当前不处理：训练、量化、NPU 优化、公共人数扩容、客户精度结案。不能将宿主单人示例对照等同于客户多人精度验证。

## 当前已完成

1. `diarization/nmnet_v015_conformer/tools/export_sdk_onnx.py`：五图导出（学生 mel、NeSt、Conformer U-Net、ECAPA mel、ECAPA），opset 17，在 ORT 1.16.3 上对齐。
2. 学生权重 SHA-256 `f980c146e2c59f723e3808d4a76adb4731ccd674537d3aae3dc23ef445fab7c7`，前端 SHA-256 `f651f8d6255315657db026db9167c781f48287bc988d26e34940a7a0fa3ab398`。
3. `nmnet_diarization.{h,cpp}`：原生 ORT 全推理，按有效前缀运行 U-Net，各槽位仅选择真实 PCM，ECAPA 保留批次 padding 和相对长度。共享源码加入双端 CMake。
4. `nmnet_window.h`：有序滑窗、尾窗、不重复完整末窗、固定 PCM 清零和原 Python ECAPA 选样规则。
5. `nmnet_history.h`：历史支持数/向量和、centroid linkage、原簇支持数、小簇合并、固定身份、50 chunk 压缩。chunkIndex 防重复/乱序。
6. `nmnet_overlap.h` / `nmnet_session.h`：因果重叠提交、独立推理/角色提交进度、尾部 flush 和 cancel。此层输出内部身份；`nmnet_sdk_session.h` 按首次已提交活动帧映射公共身份，最多 1～4 人，超额身份输出 UNKNOWN，不强行归并。
7. `asr/tools/nmnet_native_probe.cpp` 与 `tools/verify_sdk_native.py`：宿主原生与原 Python 的真实音频对照。

## 定位到的实现细节

- 实际前端 checkpoint 配置为 15 层 `nemo.collections.asr.modules.TransformerEncoder`，feature stacking / RoPE / full attention；后端为 7 块 Conformer U-Net。不是两级 Conformer。
- 原 FlexAttention 不可直接通过 legacy ONNX 导出；导出 wrapper 保持权重，用显式 masked attention 替代并核对原始前向。
- Torch MultiheadAttention 导出会固化部分 reshape 长度；U-Net wrapper 同样采用显式注意力，验证动态尾窗，原推理模型未修改。
- 实际有效帧为 `ceil(floor(validSamples/160)/8)`，不能直接 `ceil(validSamples/1280)`。少于 160 个样本没有有效帧，原公共 Python 输出被全部屏蔽；native 跳过 all-masked attention，返回零证据。
- ECAPA 帧到样本映射的最后帧需覆盖剩余真实样本，不能漏掉非整 hop 的尾部。
- ECAPA 的 dB 特征使用 atol 0.01 dB / rtol 0.002，反映 ORT STFT 与 PyTorch FFT 的累积误差；串联后的 embedding 和概率仍使用 atol 0.0002 / rtol 0.002。报告记录实际误差，不把特征容差当成身份精度指标。

## 已有证据及范围

- 本地 `outputs/sdk-export-v8/report.json`：五图逐层与串联对照，涵盖完整窗、多种尾长、ECAPA 变长批次。五张模型已回下载至同目录。
- 本地 `outputs/sdk-native-parity-v1/report.json`：C++ 使用 ORT 1.16.3 编译链接通过，7 个长度的示例音频对照通过；非零 transport padding 不影响有效输出。最大分割概率绝对误差约 6.38e-6，最大 embedding 绝对误差约 4.45e-5。
- 20 秒示例（一个活跃槽位）服务器 CPU 测量：分割约 334 ms，ECAPA 约 1433 ms，不含模型初始化、历史聚类和 ASR 竞争。这不是手机性能，也不是稳态压力结论。
- `python -m unittest asr.tools.tests.test_nmnet_history_native -v`：4 项通过，内部涵盖随机距离、50/100 压缩边界、晚到角色、小簇、分帧无关、真实样本选取、提交前缀冻结及 session 顺序。
- 新增 C++ 主源码在 Linux g++ 上完成编译与 ORT 链接；Windows MinGW 对仓库 ORT 头的 SAL/调用约定兼容失败，未修改第三方头强行通过。
- v1～v7 原型日志保留在远端 `/222042021/lpl/tmp/amphion-student-*`，属于非 canonical 诊断。v6 仅三段神经图，不是完整候选；完整特征图使用 v8。

## 本轮桥接与构建结果

- Harmony：`nmnet_napi.cpp` 提供异步 load/process/finish/close，rawfile 直接加载五图；作业持有 native session 引用，close 不会释放在途计算。恢复共享 worker 原有 QoS，保持调用方的角色调度配置。
- Android：`nmnet_jni.cpp` 通过 AssetManager 加载五图；Kotlin wrapper 解析增量角色结果，单执行器按窗口顺序调用。测试用 factory 保留，cancel/cleanup 等待 load/process/flush quiescent。
- 双端客户端使用固定 320000 float、真实 validSamples、20 s 窗和 2 s 步长。精确完整末窗不重复推理，但始终 finish native overlap。Android 超时从旧分支 10 s 调整为 60 s，与 Harmony 一致；超时只降级并丢弃迟到结果，不假称中断 native。
- 会话仅以 `rolesCommittedThroughSample` 作为角色可提交进度。ASR 尾结果与角色 flush 共同完成会话；公开原句、UNKNOWN/重叠信息及提交窗口冻结机制保留。
- 移除当前构建的 Community-1/WeSpeaker/PLDA/VBx、旧分割资源依赖，保留 ERes2Net/CAMPPlus 声纹用途。共享历史源文件不删除。旧 Community 实现源码作为未路由的历史实现保留；不再注册 Community N-API。
- 包校验核对五图的大小/SHA-256、manifest 与许可说明，并拒绝旧角色模型混入。隔离 Harmony 构建同步 CJS 工具；Android/Harmony 交付清单使用学生图。
- 本机独立 CLT 26.0.0.851、JDK 17.0.20.1、Android NDK 26.3.11579264。Harmony 通过 CLT Hvigor 构建，不依赖 Studio。Android 使用 Gradle 8.6。
- 修复本地 Windows 工具链输入：上游 `c-api.h` 的符号链接文本按原目标实体化；FetchContent 使用短缓存目录。已有 Sherpa 库缺 ITN alignment 符号，因此从固定提交与 29 补丁重新编译 C API/JNI；Harmony 导出符号门禁通过。ASR 构建关闭 TTS，不改变 ASR 分支。Android AGC 从本仓库 Meson 源码编译；Android ORT 使用官方 Maven 1.24.3。

### 产物与证据

- Harmony：`asr/harmony/{sdk,sdk-police,sdk-dingqiao}/build/default/outputs/default/*.har`，以及 derived Sherpa 的 `sherpa_onnx.har`。
- Android：本轮为中英 ZH_EN 资源配置，`asr/android/{sdk,sdk-police,sdk-dingqiao}/build/outputs/aar/*-release.aar`。这是组件 AAR，调用方需配套组件，不能把鼎桥单个 AAR 宣称为自包含交付包。
- 实际产物路径、大小、SHA-256、源码指纹和测试汇总：`.local/harmony/nmnet-sdk-build-report.json`。源代码仍未提交，报告绑定工作树指纹，不冒充当前 HEAD 的正式 release。
- 最终构建日志：`.local/harmony/nmnet-sdk-build-6.log`、`android-final-build-test.log`；补齐 ASR assets 后仅重打 core 的日志为 `android-core-assets-build.log`。
- Android 鼎桥 Release 单测 142 项通过，包含分帧/延迟等价、取消等待在途 native、重入取消、ASR/角色先后顺序、尾部 barrier 和 salvage。
- 学生历史聚类 4 项、资源 5 项、路由 4 项通过；旧资源清理测试 4 项通过、1 项历史模型字节检查因源模型不存在跳过。路由测试包括精确 20 s 与短尾窗、flush 中取消、公共提交进度、身份容量及 UNKNOWN 重叠。
- 两个角色组件的实际 HAR/AAR 内五图校验通过，且无旧角色资源。旧 Community 专用 Harmony 集成夹具尚未全面迁移，未声称全仓测试通过；本轮新增学生路由测试是当前分支的定向证据。

- Android 原工作区只有 ASR assets README，首次组件 AAR 缺 ASR 模型，不能端侧运行；已通过 `08_pack_sdk_assets.sh --zh-en-only` 补齐原有中英 ASR/标点/ITN/VAD 共 9 个资源并验证 manifest v2，未用 Harmony ORT 图冒充 Android 图。转换工具增加 Windows 文件锁，验证脚本复用指定 Python，5 项转换/跨进程锁测试通过。

### 尚未完成的验收与阻断

1. 后续已完成签名 HAP、USB 安装与中英引擎就绪检查（见下节）；仍未执行完整公共 SDK 生命周期、断网无请求、多人身份精度或可读性验收，不能宣称客户体验已通过或角色分离正式交付。
2. Harmony ORT/AGC 复用本机已有库；完整 release 源码 provenance 及最终冻结提交尚未验证。不得用此构建报告替代正式构建身份门禁。
3. 学生/NeSt 再分发授权尚未在仓库确认，仍是发布阻断；ECAPA 模型卡与 Apache-2.0 文本随资源打包。
4. 50 chunk 是压缩周期，不是历史丢弃上限。native overlap 仍保留历史 turns；本轮没有证明整体会话内存有界或手机稳态时延达标。

## 2026-10-15 签名、安装与本地候选包

- 使用现有有效证书（2027-09-24 到期）和包含当前测试设备的 provisioning 完成 Release / Diagnostics HAP 签名，官方签名工具验签通过；未依赖 DevEco Studio。
- 测试机 PSN-AL00 / API 22 已安装 Diagnostics 0.3.22，公开页面显示“默认中英模型已就绪”。仅证明安装、授权及启动，不证明学生角色分离精度或生命周期验收通过。
- 原 Demo 授权缺少当前开发者作用域 ODID；仅追加当前测试设备，保留原有效期和功能。临时设备诊断代码已移除，敏感标识与签名材料仅留本地安全目录。
- Demo 残留 Nemotron 实验模型和录音移至 `.local/harmony/legacy-demo-nemotron-resources`，不再进入 HAP，未删除原文件。
- 自包含 HAR 组装入口改为验证学生五图，取消旧 pyannote 源文件前置依赖；输入和输出均校验模型 manifest、哈希和旧资源缺失。
- 独立 Demo 源码首次编译因 MindIR 私有探针导入失败；组包裁剪规则现移除该探针及入口。新增源码转换回归通过，同输入独立宿主编译通过，无须改动 SDK 或重跑已通过的设备启动。
- 小型组包/资源检查 7 项通过，1 项因 Windows 无创建符号链接权限报环境错误；不宣称全绿。
- `build/nmnet-sdk-20261015/` 含自包含 HAR、两种签名 HAP、五目录候选 ZIP、SHA-256 和外置 `report.json` / `验收说明.md`。报告绑定最终 ZIP 和已安装 HAP；Release/Diagnostics 四组件分别记录源码指纹和哈希。
- 该包明确是未提交工作树的本地候选，不是正式客户发布：冻结提交、独立 API23 编译门禁、学生/NeSt 再分发授权及完整 SDK/身份/体验/断网验收仍阻断正式发布。源码包不含授权、签名配置、原始录音或本地构建缓存。

## 较早阶段记录（已被本轮路由和构建结果更新）

- 共享目录、Harmony rawfile、Android 生成 assets 的五图均通过真实文件大小和 SHA-256 验证。同步器先验证完整源集合，缺失/截断/同大小损坏不得覆盖已生成资源；同大小损坏缓存可以修复。
- 新资源/包内校验 5 项测试通过；既有 Community 资源检查 9 项通过、1 项因旧 INT8 模型本机缺失跳过；构建身份测试 18 项通过。Windows Git 标准输入改为 NUL 分隔，避免 CRLF 被当作文件名。
- 含统一五图文件名和资源路径常量的 OHOS arm64 native SDK 重新编译链接通过。公共 N-API/JNI 路由未切换，不能称为学生 SDK 推理验收通过。
- 真实 Hvigor 已执行新资源同步，完整 HAR 随后因旧 Community encoder 缺失失败（`.local/harmony/nmnet-harmony-resources-2.log`）。未绕过旧资源门禁。
- Android Gradle 资源任务在项目配置阶段因缺少 Android SDK 失败（`.local/harmony/nmnet-android-resources.log`）；共享同步器已直接执行，但不能写成 Gradle/AAR 构建通过。
- ECAPA 上游模型卡与 Apache-2.0 文本随资源同步；学生/NeSt 再分发许可仍是发布阻断项。未执行签名、USB SDK 生命周期、身份精度或体验验收。
