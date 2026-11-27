# 安卓机主识别：非机主语音漏出并与机主第二句并句（客户 #102）真机证据

日期：2026-11-24。设备：鼎桥安卓机 HUAWEI BRA-AL00（Android 12）。SDK：`main`（安卓 0.3.11，含 #100 修复）+ 本次修复。
客户附件：`Amphion_SmartQuiz_20261124_114244.wav`（43.4 s，16 kHz 单声道）、`enroll_samples_android.tar`
（near / mid / far 三份注册样本，6.7~7.5 s）、录屏 `SVID_20261124_114155_1.mp4`。证据目录 `~/amphion-evidence/20261124-issue102/`。

## 一、录音内容（主机侧独立标注）

能量分段 + `shared/models/asr/dingqiao/eres2net.onnx` 对三份注册样本取最大余弦：

| 时间 | 说话人 | 相似度 |
| --- | --- | --- |
| 1.7–17.1 s | 机主（报警陈述） | 0.72~0.77 |
| 17.8–30.2 s | 非机主（目击者补充） | 0.28~0.45，最后一段 27.3–30.2 s 为 0.45 |
| 30.7–35.8 s | 机主（登记联系方式 + 电话） | 0.74~0.79 |

非机主说完到机主开口只有 0.48 s，短于客户的 `vadEnd=1600`。按同样的 1.5 s 窗 / 0.5 s 跳滑窗：非机主期间
多数窗口 0.24~0.37，但 24.5 s 处 0.42、30.5 s 处（29.0–30.5，几乎全是非机主尾巴"主路开走了"）0.51；
单独给 29.07–30.24 s 的"主路开走了"打分为 0.506，机主自己的起头 30.72–31.50 s 为 0.583。

主机 ASR（同款模型、不开机主识别）整段转写与客户现象一致："文昌二楼"、"往北边的路主路开走了"、
"请把目击者的联系号码是幺三八零零二二三三四四"——"方式也登记一下我的电话"在 beam / greedy / blank penalty 下
都被删除，是声学模型对这段快速连读的识别错误，与机主识别无关。号码的中文数字由 SDK 的 ITN 后处理转成
`13800223344`（真机 final 已验证）；客户看到"幺三八…"说明其展示的是不做 ITN 的中间结果或未使用 final 文本。

## 二、真机复现（修复前，0.3.11）

用例 `DingqiaoCustomerBugEvidenceInstrumentedTest#bug100OwnerReturn_secondOwnerUtteranceIsPublished`，
`recognizerMode=long`、`enablePartialResult=true`、`enablePoliceEnhancement=true`、`vadEnd=1600`，三份样本注册为一个 ID，
20 ms 一帧实时喂入；仅机主识别与 Speaker VAD 两种模式结果相同。

| 段 | 时间 | 相似度 | 结果 |
| --- | --- | --- | --- |
| 机主第一句 | 2.0–17.5 s | 0.783 | 发布 |
| 非机主 4 段 | 19–28 s | 0.256 / 0.384 / 0.404 / 0.365 | 拒绝 |
| 非机主片段"到了事情的全。" | 22.0–22.9 s | **0.292** | **发布（漏出）** |
| "主要路主路开走了。好的，请把目击者的联系号码是13800223344。" | 28.9–36.2 s | 0.834 | 非机主尾巴与机主第二句并成一句发布 |

## 三、根因

1. **低分片段漏出**：鼎桥封装层把 `TargetSpeakerConfig.threshold` 设为 −1（"只打分不拒绝"），句级门
   `speakerFinalGateScore(threshold, confirmed)` 在"目标已确认"时就等于 −1。非机主 24~26 s 的一跳窗口打到 0.390 ≥ 0.35，
   状态机误把目标"重新确认"，随后 0.292 的片段按 −1 门限原样发布。鸿蒙 `Runtime.ets` 同一处用的是 Speaker VAD
   的 0.35 业务阈值，这是安卓独有的分叉。
2. **非机主尾巴并进机主句**：换人检测只在"机主 → 非机主"方向切句；"非机主 → 机主"方向只有连续两跳低分才强制端点。
   此处非机主最后一跳 0.243 之后下一跳就被抬到 0.479（见第一节：非机主尾巴本身就打 0.5），再没有切点，整句延续到机主
   说完、按 0.834 发布。这是 #100 记录的遗留项"机主句首 ≤1.5 s 非机主泄露"。
3. **丢字与误识**（"方式也登记一下我的电话"、"二路→二楼"）：模型识别错误，不开机主识别也一样。

## 四、修复（安卓）

- `SessionImpl.prepareFinal`：机主识别开启时句级门限取 `max(调用方阈值, speakerVadThreshold)`，与鸿蒙对齐；
  "到了事情的全"（0.292）改为拒绝。
- 到达侧切分：`SpeakerTurnFinalizer` 记录目标确认前带语音的低分窗口数与确认窗口起点，新增 `resolveArrival`；
  `SessionImpl` 在 `TARGET_CONFIRMED` 且本会话已发布过机主 final 时，把确认窗口附近最后一个 ≥0.25 s 的静音谷之前
  的部分切为非机主前缀（`forceReject` 走 `onFinalRejected`），后缀作为机主开新流重放（`startSpeakerSuffixAsTarget`）。
  找不到静音谷时切在确认窗口起点，并要求前缀语音 ≥1.0 s；静音谷对齐时要求 ≥0.3 s；会话开头（未发布过机主 final）
  不启用，#97 短指令行为不变。
- 单测 `SpeakerTurnFinalizerTest` 新增 4 例（到达切分、静音谷对齐、取靠后的交接停顿、重置与离场互不干扰），
  `:sdk:testDebugUnitTest` 141/141。

## 五、真机复测（修复后，同设备、同参数）

| 录音 | 模式 | 机主 | 非机主 | 结论 |
| --- | --- | --- | --- | --- |
| #102 | 仅机主识别 / Speaker VAD | 第一句 0.783 发布；第二句 0.834 发布，文字完整 | 5 段拒绝（含原漏出的 0.292）；**"主路开走了"仍随机主第二句发布** | 低分漏出修复；并句部分见下 |
| #100 | 仅机主识别 / Speaker VAD | 第一句 0.722 发布，第二句 0.769 发布（64 字） | 13 段拒绝，含到达切分切出的 1.58 s 前缀（0.169） | **#100 遗留的句首 5 字泄露消除**，两模式 `OK (1 test)` |

#102 剩余的"主路开走了"（1.2 s）：单独打分 0.506，比机主自己的起头 0.583 只低 0.08，高于 0.35 阈值；两人之间的
停顿按 20 ms 能量判据只有约 0.12 s，不满足 0.25 s 的交接停顿要求。这段在当前声纹模型上与机主不可分，靶心打分和
静音谷都给不出可靠切点，属于模型能力边界；若现场要求更严，可按部署把 `speakerVadThreshold` 提到 0.5~0.55
（机主短句历史最低 0.525，会增加机主被拒的概率）。

## 六、复现命令

```bash
cd asr/android
./gradlew :samples:dingqiao-demo:assembleDebug :samples:dingqiao-demo:assembleDebugAndroidTest \
  -PdingqiaoDebugUseReleaseSigning=true --console=plain
adb install -r -t samples/dingqiao-demo/build/outputs/apk/debug/dingqiao-demo-debug.apk
adb install -r -t samples/dingqiao-demo/build/outputs/apk/androidTest/debug/dingqiao-demo-debug-androidTest.apk
adb push case.wav enroll-0.wav enroll-1.wav enroll-2.wav /data/local/tmp/bug102/
adb shell "run-as com.amphion.dingqiao.demo sh -c 'mkdir -p files/bug102 && cp /data/local/tmp/bug102/*.wav files/bug102/'"
D=/data/user/0/com.amphion.dingqiao.demo/files/bug102
adb shell am instrument -w -r \
  -e class com.amphion.dingqiao.demo.DingqiaoCustomerBugEvidenceInstrumentedTest#bug100OwnerReturn_secondOwnerUtteranceIsPublished \
  -e bug100CaseWav $D/case.wav -e bug100EnrollA $D/enroll-0.wav -e bug100EnrollB $D/enroll-1.wav -e bug100EnrollC $D/enroll-2.wav \
  -e bug100SpeakerVad false -e bug100VadEnd 1600 -e bug100FrameSleepMs 20 \
  -e bug100OwnerTexts '我要报一个警,请把目击者的联系' -e bug100OtherTexts '目击者,事情的全' \
  com.amphion.dingqiao.demo.test/androidx.test.runner.AndroidJUnitRunner
adb shell run-as com.amphion.dingqiao.demo cat files/customer_bug_gate/bug100-owner-return-target-only.jsonl
```

`adb logcat` 中 `AmphionMetrics kind=SPEAKER_TURN decision=contain-on-arrival / arrival-prefix-rejected / arrival-kept`
给出到达切分的判定与原因。
