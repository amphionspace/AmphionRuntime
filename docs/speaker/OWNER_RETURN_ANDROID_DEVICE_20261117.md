# 安卓机主识别：机主 → 非机主 → 机主，机主第二次发言丢失（客户 #100）真机证据

日期：2026-11-17。设备：鼎桥安卓机 HUAWEI BRA-AL00（Android 12，`HUAWEIBRA-AL00/104.2.0.380SP60C700`）。
SDK：`main` 工作区（安卓 0.3.10 冻结点 `d9d1e8fd` 之后无运行逻辑改动）+ 本次修复。

## 一、先核对：客户证据是不是我们的软件

- 客户附件 `问题合计 3/离线/问题100/SVID_20261117_172346_1.mp4`（2 分 54 秒）逐 3 秒抽帧 58 张，
  全程是客户 App「小乔」（`com.tdtech.tiassistant`，设备上 2026-11-09 更新）界面，没有鼎桥语音识别 Demo。
  录像只能证明现象，不能定位到 SDK。
- 同目录 `Amphion_SmartQuiz_20261117_173125.wav`（64.44 s，16 kHz 单声道 s16）与
  `问题合计 3/安卓声纹/Amphion_vp-enroll-*.wav` 三份注册样本是客户 App 落盘的 SDK 输入与注册音
  （命名不是本仓库任何代码产生的）。格式与 SDK 输入一致，可直接回放。
- 因此用我们自己的 Demo 测试包在鼎桥机上回放这组音频，以 SDK 公共回调判定。

SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| `Amphion_SmartQuiz_20261117_173125.wav` | `372e8fbbd727424847fc401e31356f78ac2cccf0c2d681b90a766d93327147f1` |
| `Amphion_vp-enroll-1794905011293_20261117_164339.wav` | `4500d02ceeac4f362a4e86ccb2e3c3414a3b9f53f2579333bed2651c44d8ab86` |
| `Amphion_vp-enroll-1794905020667_20261117_164349.wav` | `5a32efb3088a44c9f0386363f8f8cdcae58328c1090f2467ffe3c0b5ccbf8925` |
| `Amphion_vp-enroll-1794905030490_20261117_164359.wav` | `e36a6f74177df8c6560c7a7f005fcb37453da4264aabacdd723deff07613d896` |

## 二、录音内容（主机侧独立标注）

能量分段 + `shared/models/asr/dingqiao/eres2net.onnx` 对三份注册样本取最大余弦：

| 时间 | 时长 | 对注册样本最大相似度 | 说话人 |
| --- | --- | --- | --- |
| 1.5–19.3 s（三段） | 15.2 s | 0.728 / 0.681 / 0.664 | 机主（朗读"八不准"） |
| 19.9–42.2 s（四段） | 20.0 s | 0.209 / 0.091 / 0.083 / −0.002 | 非机主 |
| 42.9–56.7 s | 13.8 s | 0.790 | 机主（继续朗读） |

非机主结束到机主再开口只有 0.7 s，短于客户 `vadEnd=1600`。主机 `decode_streaming.py` 不开机主识别
时三段文字均可正常识别（机主第二段 65 字）。

## 三、真机复现（修复前）

用例：`DingqiaoCustomerBugEvidenceInstrumentedTest#bug100OwnerReturn_secondOwnerUtteranceIsPublished`，
参数 `recognizerMode=long`、`enablePartialResult=true`、`enablePoliceEnhancement=true`、`vadEnd=1600`、
`enableVoiceprintVerification=true`、三份样本注册为一个 ID（多模板）、20 ms 一帧实时喂入。
先不开机主识别跑一遍做参照（整段 268 字、2 条 final），再开机主识别。

| 模式 | 机主第一句 | 非机主 | 机主第二句 | 结论 |
| --- | --- | --- | --- | --- |
| 仅机主识别（`enableSpeakerVad=false`） | 发布，0.722 | 与机主第二句并成一句 | **整句 0.427 被拒，文字丢失** | 复现 |
| Speaker VAD（`enableSpeakerVad=true`） | 发布，0.722 | 11 句全部拒绝 | **0.754 仍被拒，文字丢失** | 复现 |

时间线（`AmphionMetrics`）：机主第一句在 19.35 s 处被正确切分（`split cutSample=309600 left=0.648 right=0.202`）；
随后后缀流带着"离场后待确认"标志：

- 仅机主识别：非机主 23 s 期间 30 次 `pre_target_ignored`，不切句；机主回来后 `target_confirmed 0.480`
  但没有切点，直到 64.4 s 收尾才出一条 final，整句（非机主 23 s + 机主 14 s）0.427，按待确认门限 0.45 拒绝。
- Speaker VAD：非机主期间每 ~1.5 s 一次 `pre_target_endpoint`，11 句拒绝；机主回来 `target_confirmed 0.480`，
  final 0.754，但 `svRejectCurrentUtterance` 因待确认标志恒为 true，仍走 `onFinalRejected`。

## 四、根因

1. `svAwaitingTargetAfterDeparture` 在换人切分时置 true，只在 `prepareFinal` 发布一条机主 final 之后清除；
   而它又使 `svRejectCurrentUtterance = true`，`shouldRejectSpeakerVadFinal` 对 `rejectCurrent=true`
   一律拒绝，清除点永远到不了。鸿蒙 `8ca5f2c4`（0.3.28）在 `restartRejectedSpeakerTurn` 清除；安卓同日
   `e81070c0` 未带上这一段。
2. 安卓 `e81070c0` 为 #97 短指令在仅机主识别模式下忽略 pre-target 端点，非机主连续说话不切句；
   鸿蒙的处理是"静音里的 pre-target 不端点"，而不是整个模式不端点。
3. 离场判定没有鸿蒙 `4657dba1`（0.3.29）的语音证据要求，机主停口后的静音窗口可凑出假离场（本录音未触发，
   同名逻辑一并对齐）。

## 五、修复

- `SessionImpl.restartStreamAfterUtterance` / `hardRestartStream`：新流为新进入，清除待确认标志
  （`leaveSpeakerTurnUtterance`）。
- `SessionImpl.maybeTriggerSpeakerVadEndpoint`：pre-target 端点两种模式一致，但只在该跳窗口有 VAD 语音时触发
  （`pre_target_silent` 不端点）；两跳低分都在静音里不构成离场（`departure_silent`）。
- `SpeakerTurnFinalizer.observeScore(…, speechWasActive)`、`hasSpeechBearingLowScore`、
  `hasPendingDeparture`、`hasPendingFinishDeparture` 与鸿蒙对齐；单测新增 5 例。

## 六、真机复测（修复后，同设备、同录音、同参数）

| 模式 | 机主第一句 | 非机主 | 机主第二句 | 生命周期 |
| --- | --- | --- | --- | --- |
| 仅机主识别 | 发布，0.722，83 字 | 11 句拒绝，最高 0.282 | **发布，0.754，68 字** | last/complete 各 1，无错误 |
| Speaker VAD | 发布，0.722，83 字 | 11 句拒绝，最高 0.282 | **发布，0.754，68 字** | 同上 |

断言：机主两句的关键片段均在发布文本中，非机主三个片段均不在；两种模式 `OK (1 test)`。
`:sdk:testDebugUnitTest` 129/129 通过。Demo APK SHA-256
`752c0f326de5da0a1b44c8f4de05ad4909cbb93db75855e2a29ef3d7b0419a6f`（debug 构建、发布证书签名，仅用于复测）。

## 七、已知限制与遗留

- **句首泄露**：机主紧接非机主开口，机主第二句句首带了非机主最后约 1.5 s 的 5 个字。pre-target
  端点每 ~1.5 s 一次，泄露上限就是一次打分延迟；要消除需要"非机主 → 机主"方向的回归切分，未实现。
- **出字慢（另立跟踪）**：机主第一句被切分后，19 s 前缀的干净重解码耗时 12.4 s（`prefix-published decodeMs=12434`，
  其中 `FINAL_TAIL scope=speaker-prefix decodeDurationMs=6218`），之后解码一直落后实时约 12 s：两句机主
  final 分别在讲完后约 20 s / 17 s 回调（修复前第一句同为 20 s）。这是鸿蒙 #98 第二轮同类问题在安卓上的
  形态，本次未处理。
- **注册样本长度**：客户三份样本 8.26 / 8.44 / 8.90 s，安卓 `registerVoiceprint` 上限 8 s，直接注册返回
  `VOICEPRINT_SAMPLE_DURATION`；复测裁到 7.9 s（语音在 7.9 s 前结束）。客户 App 如何注册成功需确认。
- 录音经 instrumentation 参数外挂，不入库；设备上须放到应用私有目录（`/data/user/0/<pkg>/files/…`），
  `/sdcard/...` 路径应用进程读不到（`sample not found`）。

## 八、复现命令

```bash
cd asr/android
./gradlew :samples:dingqiao-demo:assembleDebug :samples:dingqiao-demo:assembleDebugAndroidTest \
  -PdingqiaoDebugUseReleaseSigning=true --console=plain
adb install -r -t samples/dingqiao-demo/build/outputs/apk/debug/dingqiao-demo-debug.apk
adb install -r -t samples/dingqiao-demo/build/outputs/apk/androidTest/debug/dingqiao-demo-debug-androidTest.apk
adb push <case.wav> <enroll-0..2.wav> /data/local/tmp/bug100/
adb shell "run-as com.amphion.dingqiao.demo sh -c 'mkdir -p files/bug100 && cp /data/local/tmp/bug100/*.wav files/bug100/'"
D=/data/user/0/com.amphion.dingqiao.demo/files/bug100
adb shell am instrument -w -r \
  -e class com.amphion.dingqiao.demo.DingqiaoCustomerBugEvidenceInstrumentedTest#bug100OwnerReturn_secondOwnerUtteranceIsPublished \
  -e bug100CaseWav $D/case.wav -e bug100EnrollA $D/enroll-0.wav -e bug100EnrollB $D/enroll-1.wav -e bug100EnrollC $D/enroll-2.wav \
  -e bug100SpeakerVad false -e bug100VadEnd 1600 -e bug100FrameSleepMs 20 \
  -e bug100OwnerTexts '<机主片段1>,<机主片段2>' -e bug100OtherTexts '<非机主片段>' \
  com.amphion.dingqiao.demo.test/androidx.test.runner.AndroidJUnitRunner
adb shell run-as com.amphion.dingqiao.demo cat files/customer_bug_gate/bug100-owner-return-target-only.jsonl
```
