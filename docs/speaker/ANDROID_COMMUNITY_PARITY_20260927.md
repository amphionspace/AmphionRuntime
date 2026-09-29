# Android Community-1 对齐

对齐基线：`main` 的 #221、#225，以及用户指定的 Harmony 修复 `42911432`。
后者作为独立提交保留在当前分支；本记录不表示已合入主线或正式发布。

## 范围与不变量

- 改变：Android 使用同一套离线 segmentation-3.0、masked WeSpeaker、PLDA/VBx，
  JNI 与 N-API 编译同一个 C++ 推理实现。按真实窗口 sample 位置重建时间线。
- 对齐：10 秒窗口、2 秒实际步长、最多两个待处理描述符、尾部右补零；
  冻结角色按窗口 ID 归属，保留身份锚点和跨边界上下文；10 秒音频粒度临时更新不消耗最终身份。
- 保持：原始 ASR 文本、UNKNOWN/重叠、已提交窗口冻结、取消后不新增公开结果、
  每个正常 session 唯一 last 后唯一 complete、初始静音决定不等待角色模型补尾。
- 完成音频进度必须排在该前缀所有 ASR final 后处理之后；不使用入队 PCM 时长冒充处理进度。
- 不包含：发布版本号、正式 ZIP/AAR 交付、通用身份精度承诺或对 Harmony 已知精度边界的额外修复。
- Android 公共时间字段仍为整数毫秒，native 重建保留双精度，公开边界按毫秒取整。

## 模型及构建

沿用 `delivery/harmony-dingqiao/delivery/community_diarization_1.json` 的三项模型资产和哈希。
恢复方式见同目录上级的 `docs/COMMUNITY_MODELS.md`。模型随 APK/AAR 打包；运行时不下载。
ERes2Net 保留用于声纹功能。角色分离不再调用 ERes2Net/CAMPPlus 的旧身份查询路径。

## 测试迁移

旧 `DiarizationForegroundLevelTest` 和部分 `DiarizationWindowFinalizationTest` 直接注入
ERes2Net 查询向量并反射访问旧 `committedRegistry`、旧的 RMS 准入状态，不能证明 Community 行为。
这些内部算法场景随引擎切换移除，未通过放宽阈值沿用；旧纯算法测试仍保留。
替代检查在 `CommunityDiarizationTest`、`CommunitySessionTest` 与共用 C++ 主机测试中覆盖：
真实窗口位置、分帧/排队等价、角色重新编号及裁剪后的身份归属、临时结果撤回、
取消时的迟到聚类、回调重入、初始静音收尾、ASR/推理不同完成次序下冻结结果一致。
`ProcessedAudioFenceTest` 检查处理进度不能越过 final 后处理。

句级断言按 Harmony 更新为：可信标点边界两侧可分别归属；词内不拆分，不吞 UNKNOWN 或重叠。
保留原 `sourceUtteranceId`，Demo 仍可展示原句与角色详情，临时阶段明确“暂定，可修正”。

## 验证

早期整段真机验收失败，**不能作为可用能力交付**；它不等于移植实现不一致。该轮运行代码冻结提交为 `62002e9a`，
基于 `1d815dfb` 加上 `42911432` 的 cherry-pick `94401c6d`。
证据位于本机 `~/.cache/amphion-runtime/diagnostics/android-community-parity-20260927/`。
原始音频与声学张量只留在私有本机目录，不提交仓库。

### 移植中发现的问题

Release 初轮 9 项适配层测试失败：新增 `ProcessedAudioObserver` 在核心 SDK 单独 R8
打包时被移除，适配层创建回调对象失败。已添加与现有 `ResultAudioTimeline` 同级的
consumer keep 规则；该问题由本次跨 AAR seam 引入，不归因于 Community 模型。
原失败日志已保存到证据目录 `build-evidence/android-community-final-build-tests.log`。
修复后 Debug/Release 单测全部通过，这项移植回归已关闭。


### 已通过的局部检查

- Android 核心 SDK：Debug 61、Release 60 项；鼎桥适配层：Debug/Release 各 126 项，
  共 373 项单测通过，无跳过。包含异步次序、取消、已提交冻结和 PCM 分帧等价检查。
- Debug Demo/test APK 与 Release AAR 构建通过。新 JNI 使用当前源码；ASR/ORT 依赖复用
  已有本地预构建库，此次不是完整 SDK 原生依赖的重新构建和正式发布溯源。
- Harmony Community 相关 24 项主机检查通过；共享源文件使用 Harmony CLT 编译参数通过
  C++ 语法检查。没有重建整套 Harmony HAP，也没有重复 Harmony 真机矩阵。
- TECNO KI8 / Android 13 上，两段真实 10 秒窗口（ES2011b 的 0 秒、172 秒起点）
  分段张量与参考完全相同；embedding 最大绝对差分别为 1.371e-6、7.749e-7，
  finite mask 一致。JNI 实际时间位置、关闭后重新加载也通过。
- Demo 两项界面契约测试通过：原句展示不被角色碎片拆坏，临时结果可修正，最终结果冻结，
  UNKNOWN/重叠/推断标签可见。这是受控回调测试，不是整段真实会议的界面验收。
- 非角色分离的真机生命周期对照 4 项通过：取消、重复 finish、onStart 同步写入后继续识别、
  onStart 同步写入后立即 finish。它们保护普通识别分支，不替代角色用例的收尾门禁。
- 测试 APK 未声明 INTERNET 权限；模型从包内安装，源码未引入服务调用。
  本轮未切换整台手机的 Wi-Fi/移动网络设置，不将其记作完整断网发布门禁。

### 600 秒公共 SDK 真机结果：FAIL

使用四人标注的 AMI ES2011b，16 kHz PCM16，20 ms 实时节奏，long 模式、vadEnd=800 ms、
maxSpeakers=4。设备与本地 WAV SHA-256 相同：
`55dd7dc0818fdebee5527e89ffa9ec281a5c2cef36010e5a41700a61cb3428db`。
APK 哈希与设备 fingerprint 见 `sdk-600s-owned-input/manifest.json`。
这不是客户会议原音，不能据此宣称客户原始问题已通过。

- 接口部分：28 条非 last final、43 次临时更新、4 个角色窗口；finish 前 last=0，
  之后唯一 last、唯一 complete，顺序正确。角色窗口文字与全部 final 文字守恒；
  已提交 source 没有被迟到更新改写。
- **阻断 A：停止后角色收尾超时。** 实际喂入约 644.6 秒，约 666.0 秒收到最终回调，
  最后一个角色窗口为 `FINISH_TIMEOUT`。推理积压是观测事实；还没有通过同条件性能差分
  把积压唯一归因到模型、设备调度或平台移植。不能延长超时掩盖，也不将接口结束判作验收通过。
- **阻断 B：多人身份未正确区分。** 前三个已定稿窗口只建立了一个身份，覆盖范围内已有
  多位标注人物。失败快照评分 DER=66.23%，误认 121.71 秒、漏检 168.09 秒；末尾降级也计入
  该数字，因此它不是正常完成时的模型精度结论。各身份召回和 UNKNOWN 明细见 `score.json`。
- 定位证据：两个声学窗口的 native 输出与参考相符；使用同一共用 C++ 聚类代码和参考张量，
  完整前缀可产生两个簇，裁剪到一个历史锚点和后续窗口后可收缩成一个簇。
  例如锚点 0 秒 + 150..270 秒的 2 秒网格得到两个簇，延至 274 秒得到一个簇。
  这是增量聚类敏感性的最小对照，**不是整段 Android/Harmony 会话逐窗口一致性证明**；
  还需保存实际提交时的 retained window IDs、hard labels 和身份票数，才能精确归因。
  代码与输出保存在 `oracle-prefix/`，未为此再跑十分钟黑盒。
- 因上述阻断，不继续扩大音频矩阵或生成正式交付包。首次测试目录归属 shell 导致启动失败，
  保存在 `sdk-600s/`；应用创建目录后才运行有效测试，未为此修改 SDK 权限逻辑。

后续范围以用户最新要求为准：保持指定 Harmony 方案，验证实现一致性，不针对低性能手机优化。
共享身份精度问题另行跟踪，设备吞吐不作为本次移植一致性的通过条件。没有增加固定人数、
覆盖整句身份、吞 UNKNOWN 或放宽精度断言。


## 同数据白盒对齐结论（最新）

本轮交付目标为实现对齐，不承诺 TECNO KI8 实时吞吐或完整会议精度通过。
基线仍为 `42911432`；没有混入后续 Harmony `8733a2ba` 的候选身份修复。
诊断与测试载体提交为 `ced69863`、`30835340`，最终补齐 Android 收尾等待 15 秒，
与该 Harmony 基线一致；推理看门狗仍为 10 秒。该常量修改不改变下列模型/聚类快照，
但快照也不能证明最终二进制的完整收尾验收通过。

### 数据与可比条件

使用 Harmony 同一 AMI TS3003c 文件：原录音偏移 330 秒、长度 600 秒、16 kHz PCM16，
SHA-256 `2a2c3e05049ff410f06aaa0f15844857d7771255cbb78ac03f36bc57ba37516d`。
设备文件哈希一致。long 模式、20 ms 实时喂入、vadEnd=800 ms、maxSpeakers=4，
maxAudioDuration=8 小时、警务增强开启，并以前台 Activity 保持屏幕唤醒。
这修正了早期 Android 载体与 Harmony 的配置差异；数据不是客户原始会议。

私有证据根目录为 `~/.cache/amphion-runtime/diagnostics/android-community-whitebox-20260927/`。
模型张量来自 Harmony `cadence-comparison/events-120.ndjson` 的真实采集；
429 会话逻辑则由本分支生产代码回放这些输入。必须区分设备采集与主机回放，
不能把后者写成新一轮 Harmony 429 真机长跑。

### 一致性证据

- Android 真机采集的连续 170 个窗口，起点 0..338 秒、覆盖至 348 秒，与 Harmony 同位置
  张量比较：segmentation 完全一致；embedding 最大绝对差 2.384185791015625e-6，
  finite mask 全部一致。见 `ts3003c-window-parity.json`。
- 直接将 Harmony 429 首次异常提交的 62 个窗口张量交给 Android JNI：speakerCount 与
  全部 hard labels 完全一致。`capturedHarmonyCommitClusteringMatchesAndroid` 真机通过，
  见 `native-snapshot.log`、`native-snapshot-result.json`。
- 五次真实 Harmony 429 提交的窗口 ID、hard labels、活动区间与冻结身份作为精简测试 fixture，
  Android 身份映射及 registry 前后计数全部一致。fixture 不含原音、文本或 embedding。
- TS3003c Android 已采集三个提交：角色簇数量依次 2、1、1，冻结身份映射依次
  `[0,1]`、`[0]`、`[0]`。首段 ASR endpoint 与 Harmony 回放相差 80 ms，不能声称整个 ASR
  输出逐字逐时间戳相同；后两段结束位置均为 210780 / 323180 ms。

- 三次 Android 实际提交按各自 window IDs 取 Harmony 张量重新计算，全部 hard labels
  完全相等。第二次提交保留 63 个窗口得到 1 簇；唯一改为完整历史即得到 3 簇。
  见 `ts3003c-commit-parity.json`，这将共同问题定位到历史证据裁剪，而非 JNI 或展示编号。
- 最终 15 秒收尾配置下，Community、停止回退及窗口定稿相关 Debug/Release 单测通过，
  见 `final-parity-tests.log`；不因此宣称弱设备完整收尾通过。

### 鸿蒙是否有同样的问题

有。Harmony 429 的真实长会话快照也出现保留历史锚点后多个角色收缩成单簇，
并非仅 Android 慢设备超时造成。上游 `anchor-retention-state-fork.json` 用同一异常点证明：
保留 63 个窗口为 1 簇，完整 279 个历史窗口为 3 簇。最早偏离在裁剪后的聚类证据，
不是显示层编号；后续身份映射无法恢复已经丢失的簇。

同一 TS3003c 600 秒输入在 Harmony 429 生产状态机主机回放也得到 3 个最终身份，
DER=25.5448%，一位标注人物召回为 0；这只是辅助精度定位，不是新的设备正式验收。
后续 Harmony 候选修复仍有 cadence 相关精度失败，不能把它当作已解决方案直接移植。
这纠正了“旧 #221 数据通过，所以当前 Harmony 没有该问题”的推断。

### 停止条件与剩余范围

按用户“手机性能差，确保实现一致即可”的指示，主动停止这轮长跑；保留了完整已落盘
白盒张量、三次提交、回调、内存和线程现场。`runner.json` 标记 `USER_SCOPE_STOPPED`。
Instrumentation 的 `Process crashed` 来自主动作出的 force-stop，不是观测到的 SDK 自发崩溃。
因此本轮 600 秒公共 API 完整结束验收为未完成，不能记 PASS，也不继续为积压重复长跑。

ASR 原生依赖保留平台现有构建：Android ORT 1.24.3，Harmony ORT 1.16.3 带平台调度补丁。
角色分离共用算法与模型已对照，不能据此声称两端全部运行时和调度实现相同。
未采用试验性的 Android ASR idle-spin 配置，不重建或调优底层 ASR 线程池；该准备工作
不属于本次 canonical 产物。设备速度差异不作根因结论。

功能对齐与产品精度分别报告：本次局部对齐证据通过；共享身份误认仍是正式能力交付阻断项。
未生成正式交付包，未推送或合入 PR。
