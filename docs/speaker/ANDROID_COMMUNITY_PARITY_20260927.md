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

进行中。证据位于本机 `~/.cache/amphion-runtime/diagnostics/android-community-parity-20260927/`。
原始音频与声学张量只留在私有本机目录，不提交仓库。

### 移植中发现的问题

Release 初轮 9 项适配层测试失败：新增 `ProcessedAudioObserver` 在核心 SDK 单独 R8
打包时被移除，适配层创建回调对象失败。已添加与现有 `ResultAudioTimeline` 同级的
consumer keep 规则；该问题由本次跨 AAR seam 引入，不归因于 Community 模型。
原失败日志保留在本机 `/tmp/android-community-final-build-tests.log`，需以修复后 Release 结果结案。
