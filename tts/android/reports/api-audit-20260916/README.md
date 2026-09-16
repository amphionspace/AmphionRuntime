# Android TTS API 实测（2026-09-16）

设备：TECNO KI8 / Android 13。当前 matched50 学生模型、FP32、温度 0、speaker 1。
结论：核心接口与播放生命周期通过本次测试；音调参数存在实际效果缺陷，尚未修复。
这不是所有边界、所有音频通道或发音正确率验收。

## 本次验证

- SDK JVM 单测：129 项，125 通过、4 跳过，明细见 `report.json`。
  JVM 测试中有模拟合成器，不能据此判断真实模型音质。
- 真机：修复后的 `ApiAuditDeviceTest` 4 项、`TtsLifecycleDeviceTest` 1 项、
  `VariableChunkDeviceTest` 1 项全部通过；见 `device-result.log`。
- 前一轮的两种布局资源检查通过；Activity 重建测试在设备锁屏状态下未完成，
  后续结束该进程，原因未完全隔离，本轮不将其计为通过。
- 未运行旧版 200+ 工程批测、1000 条长稳压和完整发音语料。
  部分旧测试仍依赖旧资源路径/模型参数，不能原样当成当前模型验收。

| 能力 | 本轮证据 |
| --- | --- |
| `init` / 授权 | 已签发设备授权校验有效 |
| `listVoices` | 同步返回两条语言记录、一个唯一音色；异步英文查询及主线程回调通过 |
| `createEngine` | 同步中文、异步英文加载；同一 speaker 1 合成通过 |
| `setWorkPath` | 创建前可设置，已有引擎时修改被拒绝 |
| `setListener` / `speak` | 24 kHz / 16 bit / mono；有序流式 PCM、开始及唯一合成完成 |
| 错误输入 | 空文本、非法音频格式、非法音量、重复 requestId；随后正常请求恢复 |
| `QUEUE` | 前一个请求完成后才开始后一个 |
| `PREEMPT` | 从音频回调提交抢占；旧请求一次 stop、无 complete/error，新请求完成 |
| `stop` | 当前请求及排队请求各一次 stop，之后可重新合成，无多余错误 |
| `isBusy` | 初始空闲、提交排队后忙碌；销毁后明确拒绝查询 |
| `shutdown` | 合成中/播放中安全释放，创建新引擎恢复；已销毁引擎拒绝 speak |
| 内部播放 | STREAM_MUSIC、PCM 队列 1/32；开始写音频、合成完成、播放完成；不返回 onData |
| 分块 | 50、75、100、150 均完成真实模型合成，PCM 总长度一致 |
| `speed` | 同句 0.8 / 1.0 / 1.2 分别 6.720 / 5.600 / 4.656 秒 |
| `volume` | 0.5 与基准逐采样比对，误差不超过 1；0 输出全零 PCM |
| `pitch` | 接口接受，但 1.2 未产生正确升调，见下方未解决问题 |

`getLicenseInfo`、重新签发/切换授权、其他 Android STREAM 路由、所有参数组合与
资源不足等外部故障未做本轮真机覆盖。保留此前记录的 ONLINE 等不支持项。

## 已修复：播放结束标记在队列满时丢失

原 `AndroidPcmPlayer` 在 producer 的 finally 中使用非阻塞 `offer(END_OF_STREAM)`。
若最后一块 PCM 尚占满队列，结束标记会丢失。播放线程消耗剩余音频后继续等待，
导致缺少 PLAYBACK_COMPLETE、请求无法自然结束。本次容量 1 的真实播放复现超时。
它不限于容量 1；任何队列满的结束时刻都可能触发。

修复：结束标记按原顺序等待入队，保留已有 PCM；等待期间检查取消状态并响应中断。
没有加长完成超时、丢弃音频或伪造播放完成。

`StreamingPlaybackEndTest` 的满队列结束通知测试修复前失败，修复后通过；取消等待
用例也通过。随后容量 1 和 32 的真实播放均收到完整完成回调，原生命周期测试通过。
Harmony 对应实现使用 `PcmChunkQueue.close()` 的独立 closed 状态，不通过有限容量
队列投递结束标记，因此没有同一处丢标记逻辑。本次未改 Harmony，也未进行其构建/真机验收。

## 未解决：pitch 没有有效改变音高

`PcmSynthesizer.kt` 的 `applyPitch` 先把采样点数缩成原来的 1/pitch，随后又重采样
回原长度；两次时间缩放基本抵消，主要留下插值/滤波变化。不能以波形字节改变判为升调成功。

真实模型同一句、温度 0，对比 pitch=1 与 1.2：

- 音频都为 5.600 秒。
- librosa pYIN 共识别出 393 个共同有声帧，逐帧基频比中位数为 **1.0**。
- 两段波形相关系数约 **0.9936**。

代码与测量均表明当前实现不符合预期升调效果。此问题与播放结束标记无关，尚未修复；
API 文档已标注。默认 pitch=1 不经过这段处理，本次没有改动默认音频算法。
后续需要独立实现保时长的音高变换，再验证真实音高比例及流式块边界。

## 对应测试与复现

已有测试：

- `sdk/src/test/.../TextToSpeechSdkTest.kt`：公开接口、回调、错误、排队/抢占/停止。
- `sdk/src/test/.../TextToSpeechEngineCancellationTest.kt`：取消与 native 工作退出时序。
- `sample/src/androidTest/.../TtsLifecycleDeviceTest.kt`：真实模型停止/销毁后恢复。
- `sample/src/androidTest/.../VariableChunkDeviceTest.kt`：真实模型分块参数。
- `sample/src/androidTest/.../SampleScreenDeviceTest.kt`：两种布局、Activity 重建。

本次新增 `ApiAuditDeviceTest.kt`（真实参数、接口与播放）和
`StreamingPlaybackEndTest.kt`（满队列结束通知回归）。

使用本地已配置模型/公钥的构建流程生成 sample 及其 instrumentation APK，安装后运行：

```sh
adb shell am instrument -w -r \
  -e class com.lits.tts.sample.ApiAuditDeviceTest,com.lits.tts.sample.TtsLifecycleDeviceTest,com.lits.tts.sample.VariableChunkDeviceTest \
  com.lits.tts.studentdemo.test/androidx.test.runner.AndroidJUnitRunner
```

测试读取 sample 私有目录 `files/tts-provisioning/` 和 `files/lits-tts-work/`。
逐请求结果/PCM 写到 `files/api-audit/`。导出后可使用 numpy、librosa 运行：

```sh
python tts/tools/android/analyze_api_audit_audio.py --input-dir /path/to/exported-api-audit
```

本机完整日志、修复后 APK/AAR、PCM/WAV 位于父工作区
`outputs/tts-api-audit-20260916/`。音频用于试听，未进行系统性主观音质评分。
