# Dingqiao finish flush main-branch validation

日期：2026-06-26

分支：fix/dingqiao-finish-flush-main

基线：origin/main d7e80010df64b8b5a4467f38348a146b0416b11d

说明：本报告记录本机验证结果。预览 AAR 由当前分支 classes.jar 与已交付 AAR 的 native/assets 组合而成，仅用于本机验证，不是正式客户交付物。

## 变更摘要

| 区域 | 结果 |
| --- | --- |
| finish/isLast | AsrResult 增加 isLast，SessionImpl 仅在手动 stop/finish final 上标记 isLast=true，中间 endpoint final 为 false |
| Dingqiao teardown | DingqiaoRecognitionEngine 改用 result.isLast 触发 maybeComplete + tearDownSession，不再用全局 finishRequested 把第一个 post-processed final 当作最后结果 |
| PostProcessor close | close 不再清空已排队 final；close 标记前已入队的 final 会自然处理并回调 |
| LicenseInfo | getLicenseInfo 可回落到 AmphionRuntime 当前生效的 asset license 状态 |
| License error code | app/cert/device 失配对外区分为 1002200036、1002200037、1002200033 |
| Worktree build | dingqiao_build_provenance.sh 支持 git worktree |
| Local validation asset | dingqiao-demo 支持 -PdingqiaoDemoAssetDir 注入本机验证用 app assets |

## 验证环境

| 项目 | 值 |
| --- | --- |
| 设备 | 4EE***062 |
| 音频 | /Users/boxp/Downloads/audio |
| 临时 demo license | /tmp/dq_demo_assets_main/amphion-license.lic |
| 预览 AAR | /tmp/dq_fix_preview/dingqiao-asr-v0.2.8-mainfix-preview.aar |
| 预览 AAR SHA-256 | 6e9d36315c37c515525ee8f0dbafc0a143c591fb476ae2bb3f34696b300e0630 |
| demo APK SHA-256 | 27650d62372d005ef16f1c1427490dad5da799f3688483050ac611542e7382eb |
| androidTest APK SHA-256 | 71d308267836f487154196e16cf0eee7f0a856eff6855c6d8424c2b181a06b24 |

## 验证命令与结果

| 验证项 | 结果 |
| --- | --- |
| SDK 编译 | ./gradlew :sdk:assembleDebug :sdk-dingqiao:assembleDebug 通过 |
| demo/androidTest 编译 | :samples:dingqiao-demo:assembleDebug :samples:dingqiao-demo:assembleDebugAndroidTest 通过 |
| release AAR 编译 | :sdk:assembleRelease :sdk-police:assembleRelease :sdk-dingqiao:assembleRelease 通过 |
| finish flush 回归 | DingqiaoFinishFlushRegressionTest 2 tests 通过 |
| 24 条实时语料 | DingqiaoAudioCorpusInstrumentedTest 1 test 通过 |
| lint | 修改文件无 IDE lint 错误 |

## 关键回归结果

| 文件 | realtime | fast short settle | fast long settle |
| --- | --- | --- | --- |
| 04_说话人跟踪_3人重叠71_生活建议.wav | 一般可用雨伞遮住，或把相机装在塑料袋里。 | 一般可用雨伞遮住，或把相机装在塑料袋里。 | 一般可用雨伞遮住，或把相机装在塑料袋里。 |
| 06_说话人跟踪_2人重叠71_流行歌曲口语.wav | 来个新长征路上的摇滚。 | 来个新长征路上的摇滚。 | 来个新长征路上的摇滚。 |
| 11_抗路噪_交通背景_行程提醒.wav | 假如大后天早上去机场。 | 假如大后天早上去机场。 | 假如大后天早上去机场。 |
| 01_说话人跟踪_3人重叠91_抗战历史长句.wav | 与此同时，欧美、澳等国众多华侨应征入伍，开拓欧亚各战场，同德意志法西斯浴血奋战。 | 与此同时，欧美、澳等国众多华侨应征入伍，开拓欧亚各战场，同德意志法西斯浴血奋战。 | 与此同时，欧美、澳等国众多华侨应征入伍，开拓欧亚各战场，同德意志法西斯浴血奋战。 |

结论：修复后，快喂 + 短等待路径不再丢弃真实语音 final；实时语料 baseline 无回归。
