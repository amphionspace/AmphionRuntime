# 鼎桥 Android finish 后快喂丢句复盘

## 问题复述

表面现象是鼎桥 Android ASR SDK 在“读取 wav 文件后快速循环 `writeAudio`，随后调用 `finish`”时，部分音频没有任何错误回调，但 final 结果为空或丢尾字。

真正问题不是 native 解码线程没有消费完 `writeAudio` 队列，而是多个 final 经过异步后处理线程时，鼎桥封装层把“第一个在 finish 后回来的 final”误判为整段最后结果，提前关闭 session，导致后处理队列里尚未派发的真实语音 final 被丢弃。

## 现象

本问题在文件式快喂场景稳定复现；同一音频、同一引擎，仅改变喂入节奏和 `finish` 前等待时间，结果不同。

| 文件 | 实时 20ms 喂入 + 短等待 | 快喂 + 短等待 | 快喂 + 长等待 |
| --- | --- | --- | --- |
| 04_说话人跟踪_3人重叠71_生活建议.wav | 一般可用雨伞遮住，或把相机装在塑料袋里。 | 空 | 一般可用雨伞遮住，或把相机装在塑料袋里。 |
| 06_说话人跟踪_2人重叠71_流行歌曲口语.wav | 来个新长征路上的摇滚。 | 空 | 来个新长征路上的摇滚。 |
| 11_抗路噪_交通背景_行程提醒.wav | 假如大后天早上去机场。 | 空 | 假如大后天早上去机场。 |
| 01_说话人跟踪_3人重叠91_抗战历史长句.wav | 与此同时，欧美、澳等国众多华侨应征入伍，开拓欧亚各战场，同德意志法西斯浴血奋战。 | 与此同时，欧美、澳等国众多华侨应征入伍，开拓欧亚各战场，同德意志法西斯浴血奋战。 | 与此同时，欧美、澳等国众多华侨应征入伍，开拓欧亚各战场，同德意志法西斯浴血奋战。 |

修复前，04/06/11 在快喂 + 短等待下容易返回空 final；10/12 这类尾部词较短的场景可能表现为只丢最后一个字。

修复后，上述三种路径对 04/06/11/01 均输出全文，快喂 + 短等待不再丢弃真实语音 final。

## 根因层级

根因在 Android SDK 的跨线程 final 生命周期管理层，不在客户集成层，也不是单纯的尾部静音不足。

关键事实：

- `SessionImpl.acceptPcmShort` 和 `SessionImpl.stop` 都投递到同一个 `decoderHandler`，decoder 线程是串行 FIFO。因此，在同一业务线程按顺序 `writeAudio` 后再 `finish` 时，`stop` 对应的 decode/drain 不会越过前面的 PCM。
- `SessionImpl.drainDecoder` 可能在 native endpoint、VAD 主动 endpoint、手动 stop 时产生多个 final。
- final 并不是立即回调给业务方，而是先进入 `PostProcessor` 的独立线程做 ITN/标点，再由 callback 线程回调给 `DingqiaoRecognitionEngine`。
- `DingqiaoRecognitionEngine.deliverFinal` 原先用全局 `finishRequested` 判断 `isLast`。一旦业务方调用了 `finish`，后处理队列里第一个完成的 final 就会被当作最后结果。
- 原 `PostProcessor.close` 会 `removeCallbacksAndMessages(null)`，直接清掉尚未处理的 final。

问题链路：

```text
业务线程快速 writeAudio
  -> decoder 线程串行产出多个 final
  -> 多个 final 排入 PostProcessor
  -> 业务线程调用 finish，finishRequested=true
  -> PostProcessor 第一个 final 回来，被 DingqiaoRecognitionEngine 当作 isLast
  -> tearDownSession
  -> PostProcessor.close 清空队列
  -> 后续真实语音 final 被丢弃
```

因此，长等待可以规避问题：因为真实语音 final 在 `finish` 前已经处理并回调，此时 `finishRequested=false`，不会触发提前 teardown。

## 解决方案

修复原则是把“最后一个 final”的语义下沉到 ASR session 层，而不是由鼎桥封装层用全局 `finishRequested` 推断。

### 1. 在 `AsrResult` 中携带 `isLast`

`AsrResult` 增加默认字段：

```kotlin
public val isLast: Boolean = false
```

默认 false，保持 API 向后兼容。

### 2. 只在手动 stop/finish final 上标记 `isLast=true`

`SessionImpl.stop` 调用 `drainDecoder` 时传 `isLastFinal = true`。

native endpoint、VAD 主动 endpoint、speaker-VAD endpoint 产生的中间 final 仍保持 `isLast=false`。

### 3. 鼎桥层只在 `result.isLast` 时完成并关闭 session

`DingqiaoRecognitionEngine.deliverFinal` 和 `onFinalRejected` 改为使用 `result.isLast` 判断是否：

```text
maybeComplete(sessionId)
tearDownSession()
```

这样即使业务方已经调用 `finish`，后处理队列里早先产生的中间 final 也不会被误判为最后结果。

### 4. `PostProcessor.close` 不再清空已排队 final

`PostProcessor.close` 改为停止接收新任务，但让 close 前已入队的 final 自然处理并回调。

这是一层兜底：即便后续又出现早 close 路径，也尽量不吞掉已经产生的 final。

## 相关代码位置

| 文件 | 作用 |
| --- | --- |
| asr/android/sdk/src/main/java/com/amphion/asr/AsrResult.kt | 增加 `isLast` 字段 |
| asr/android/sdk/src/main/java/com/amphion/asr/internal/SessionImpl.kt | stop/finish final 标记 `isLast=true`，中间 endpoint final 保持 false |
| asr/android/sdk/src/main/java/com/amphion/asr/internal/PostProcessor.kt | close 不再清空已排队 final |
| asr/android/sdk-dingqiao/src/main/java/com/amphion/dingqiao/DingqiaoRecognitionEngine.kt | 只根据 `result.isLast` 触发 complete 和 teardown |
| asr/android/samples/dingqiao-demo/src/androidTest/java/com/amphion/dingqiao/demo/DingqiaoFinishFlushRegressionTest.kt | 设备端回归测试 |

## 回归验证

本问题必须做真机验证，因为需要覆盖 Android native 库加载、模型加载、PostProcessor 线程、Dingqiao callback 封装和实际音频语料。

### 构建 SDK 和 demo

```bash
cd asr/android

./gradlew :sdk:assembleDebug :sdk-dingqiao:assembleDebug --console=plain

./gradlew \
  :samples:dingqiao-demo:assembleDebug \
  :samples:dingqiao-demo:assembleDebugAndroidTest \
  -PdingqiaoUseFatAar=true \
  -PdingqiaoFatAarPath=/path/to/dingqiao-asr-preview.aar \
  -PdingqiaoDemoAssetDir=/path/to/demo-license-assets \
  -PdingqiaoEvalAudioDir=/path/to/audio \
  --console=plain
```

说明：

- `dingqiaoUseFatAar=true` 用于验证与客户交付形态一致的 fat AAR。
- `dingqiaoDemoAssetDir` 只用于本地验证时注入 demo license asset，不应把本地临时 license 写入仓库。
- 正式交付包仍必须从干净工作区构建；脏工作区合成的 AAR 只能作为本地预览。

### 安装并运行回归测试

```bash
DEV=<device-id>

adb -s "$DEV" install -r -t samples/dingqiao-demo/build/outputs/apk/debug/dingqiao-demo-debug.apk
adb -s "$DEV" install -r -t samples/dingqiao-demo/build/outputs/apk/androidTest/debug/dingqiao-demo-debug-androidTest.apk

adb -s "$DEV" shell am instrument -w \
  -e class 'com.amphion.dingqiao.demo.DingqiaoFinishFlushRegressionTest' \
  com.amphion.dingqiao.demo.test/androidx.test.runner.AndroidJUnitRunner
```

预期：

```text
OK (2 tests)
```

回归报告可从 app 私有目录拉取：

```bash
adb -s "$DEV" shell run-as com.amphion.dingqiao.demo \
  cat files/eval_reports/finish_flush_regression.tsv
```

### 跑 24 条实时语料 baseline

```bash
adb -s "$DEV" shell am instrument -w \
  -e class 'com.amphion.dingqiao.demo.DingqiaoAudioCorpusInstrumentedTest' \
  com.amphion.dingqiao.demo.test/androidx.test.runner.AndroidJUnitRunner
```

预期：

```text
OK (1 test)
```

## 预防措施

- 任何涉及 `finish`、`stop`、endpoint、post-process、callback 线程的改动，都必须跑 `DingqiaoFinishFlushRegressionTest`。
- 不要用全局会话状态推断某个 final 是否是最后结果；最后结果语义应随 final 自身流转。
- 关闭异步后处理线程时，不要清空已产生但尚未派发的 final。若必须中断，应明确这会丢结果，并只用于 `cancel` 或 error 路径。
- 文件式离线测试不能只跑实时喂入；必须包含快喂 + 短等待，因为客户批处理音频常采用这种调用方式。
- fat AAR 设备验证必须检查 native 库是否进入 APK。纯 project 依赖构建可能不能代表客户交付形态。

## 已知边界

- 本修复解决的是 final 生命周期竞态，不替代尾部静音右上下文补偿；`appendFinalTailSilence` 仍用于减少真实尾字截断。
- `cancel` 语义仍应是无 final、无 complete；不应通过排空 post-process 队列改变 cancel 行为。
- speaker-VAD 被拒绝的 final 同样使用 `result.isLast` 判定是否结束会话；重叠语音下是否需要调整 speaker-VAD 阈值，是另一个问题，不应与本竞态混在一起。
