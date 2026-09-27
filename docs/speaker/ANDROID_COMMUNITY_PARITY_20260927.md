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

代码已移植，**真机验收失败，不能合入或作为可用能力交付**。运行代码冻结提交为 `62002e9a`，
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

后续跟踪：保持用户指定的 Harmony 方案，当前分支作为移植候选保留；增量身份聚类和设备积压
分别建立根因差分后再修复。没有通过增加固定人数、覆盖整句身份、吞 UNKNOWN 或放宽断言来结案。
