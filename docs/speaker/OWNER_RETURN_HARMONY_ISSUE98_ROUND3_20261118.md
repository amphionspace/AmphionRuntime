# 鸿蒙 #98 第三轮：机主 → 非机主 → 机主，客户称 0.3.29 机主再说话仍"转写特别慢"

日期：2026-11-18。客户复测版本：鸿蒙 ASR SDK 0.3.29（跟踪表 2026-11-17 效果确认：不认可）。
附件：`问题合计 3/离线/问题98/SVID_20261117_164758_1.mp4`（78.7 s 录屏，无音轨）、
`smartChatVoiceTrans-20261117-164801-444.wav`（73.16 s，16 kHz 单声道，客户 App 落盘的 SDK 输入，
SHA-256 `6bcfbe814d5a0b5184a02f2730a3e156604e504f6aa1b3fa66b270e4141728a8`）、
`问题合计 3/鸿蒙声纹/enrollment_{near,mid,far}.wav`（7.6–7.8 s）。

## 一、录屏到底显示了什么

录屏全程是客户 App「小乔」。底部气泡是"已发布的机主 final + 当前句 partial"的累计文本（非机主被拒绝的句子
不进气泡，只会在被切掉前闪出一两个 partial 词，如 19 s 的"哦"、45 s 的"三个月"）。录屏无音轨，
用气泡文字与录音对齐：机主第一句"现在是测试机组转写比较慢的问题，现在说话的是机主本人"在录音 3.1–9.6 s，
录屏 14 s 已显示到"比较慢的问题"、17 s 显示到"机主本人"，可知录屏时间 ≈ 录音时间 + 7 s，且机主第一句
的 partial 是准实时的。

机主第二句（录音 42.0–49.2 s，对应录屏 49–56 s）的 partial 刷新：

| 录屏时间 | 气泡新增文字 | 这段话说出的录音时间 | 滞后 |
| --- | --- | --- | --- |
| 54–55 s | 不准非法扫描 | 42–43 s | ≈ 5 s |
| 58 s | 入侵公安云搜索等公安信 | 43.5–45 s | ≈ 6 s |
| 58 → 70 s | （不动） | | 积压 12 s |
| 70 s | 息共享查询应用系统扰乱 | 46–47.5 s | ≈ 16 s |
| 72 s | 系统的正常运行。现在是 | 48–49.2 s / 56.3 s | ≈ 16 s / 9 s |
| 76–79 s | 把我说的话丢掉了鸿蒙还是慢 | 56.3–59 s | ≈ 13 s |

结论：客户机上不是"机主第二句没有 final"，而是**解码整体落后实时**，在非机主说话的 28 s 内积压形成，
机主再开口时 partial 已晚 5 s，句尾晚到 16 s。这与 #100 安卓那种"句子被拒绝"是两类问题。

## 二、我们的鸿蒙机（HUAWEI Mate 80，VYG-AL30）同录音回放

载体：`delivery/harmony-dingqiao/delivery/run_device_stress.py --mode speaker-vad-turn --cycles 1 --pace-ms 20
--installed-package`，设备上已装的 Demo 身份 `version_name=0.3.29 / version_code=329`（与客户版本一致）。
三份注册样本注册为一个 ID（载体只取每份前 5 s），`enableSpeakerVad=true`、`enablePartialResult=true`、
`vadEnd=800`（SDK 默认；客户现场为 1600，载体该模式不可调）。两次运行（`20261117-235806`、
`20261118-000901`）结果逐条一致。

| 句 | 内容 | 有效语音 | final 相似度 / 门限 | 判定 | endpoint→final | 讲完到 final |
| --- | --- | --- | --- | --- | --- | --- |
| u1 | 机主第一句 | 6.7 s | 0.610 / 0.35 | 发布 | 67 ms | ≈ 1.4 s（含 0.8 s vadEnd） |
| u2 | 非机主插话"你随便啊哦" | 1.4 s | 0.449 / 0.35 | **发布（误放行）** | 1288 ms（换人切分前缀重解码） | — |
| u3、u4、u7 | 非机主 | 1.7–2.3 s | 0.176–0.345 / 0.45 | 拒绝 | ≤ 31 ms | — |
| 其余非机主 | 每 ~2 s 一次 pre-target 端点，13 次硬重启 | | | 拒绝（空 final） | | |
| u5 | 机主第二句 | 8.4 s | 0.603 / 0.35 | 发布 | 151 ms | ≈ 1.2 s |
| u6 | 机主第三句 | 9.2 s | 0.578 / 0.35 | 发布 | 92 ms | ≈ 1.1 s |
| u8 | 机主短句 | 3.4 s | 0.297 / 0.35 | 发布（流式已确认） | 43 ms | |

- 全程实时：输入 73 s，会话 73.7 s 结束；每跳声纹推理 median 118 ms、p90 152 ms、max 327 ms；
  `speculated` 15 次、`consumed` 8 次且 `waitMs=0`。
- 进程 CPU：均值 2.44 核、p95 4.23 核、峰值 5.18 核（12 逻辑核，均值占整机 20%）。
- 载体判 FAIL 只因 p95 endpoint→final 1288 ms > 1000 ms 门槛，来源是 u2 的换人切分前缀重解码，
  与 0.3.29 变更记录里"换人切分句 1212 ms"同量级，不是客户说的十几秒。
- 精度旁证：u2 非机主 1.4 s 插话被流式窗口确认（0.462 / 0.404）后以 0.449 发布，属非机主漏放；
  主机侧该段对三份注册样本仅 0.21–0.25。

## 二之二、按客户主工程的下发口径再跑（2026-11-18 晚）

客户 `OfflineAmphionEngine.ets` 与我方 Demo 的声纹相关键逐项一致：`enableVoiceprintVerification=true`、`voiceprintIds=[1 个]`、
`enableSpeakerVad=true`、`speakerVadThreshold=0.35`；窗 1500 / 步 500 / 连续低分 2 客户不传、走 SDK 默认，与 Demo 显式值相同。
为对齐客户口径，载体 speaker-vad-turn 新增 `--speaker-vad-vad-end-ms / --speaker-vad-recognizer-mode / --speaker-vad-verification`，
同一录音在 Mate 80 上再跑两轮（`vadEnd=1600`、两开关同开）：

| 模式 | 机主三句 final | endpoint→final 最差 | 讲完到 final | 载体实时判定 |
| --- | --- | --- | --- | --- |
| long | 0.610 / 0.610 / 0.581，均发布 | 74 ms | 约 1.9 / 2.3 / 2.5 s（含 1.6 s vadEnd） | PASS |
| short | 0.610 / 0.601 / 0.573，均发布 | 109 ms | 同量级 | PASS |

运行目录 `device-runs/20261118-202532`（long）、`20261118-2029xx/2032xx`（short）。客户口径下仍无 5～16 s 滞后；
客户未列出的键（`enablePartialResult`、`maxAudioDuration`、`enableContinuousRecognition`、热词）与机型仍待确认。

## 三、判断

1. **SDK 逻辑层面，0.3.29 对这条录音没有"机主再说话慢"的缺陷**：机主三句 final 都在讲完后 1.1–1.4 s 内，
   其中 0.8 s 是 vadEnd 等待。
2. **客户机上的 5–16 s 滞后是算力积压**。同一 0.3.29 在 Mate 80 上平均吃 2.4 核、峰值 5.2 核；
   非机主说话期间每 500 ms 一次 1.5 s 窗声纹嵌入（0.3.29 把 extractor 线程 1 → 8）、每 ~2 s 一次
   pre-target 端点 + 识别流硬重启，持续 28 s。客户鸿蒙机型未知；若是 8 核以下的弱 SoC，这一负载
   足以让解码落后实时，表现恰好是"非机主说完机主再说时最慢"。
3. 客户 `vadEnd=1600` 会让每句 final 再晚 0.8 s，但解释不了十几秒。

## 四、需要客户提供

- 复测手机型号与系统版本（录屏看不出）。
- 复测时的 hilog（`hdc hilog | grep AmphionMetrics`），或 Diagnostics SDK 的诊断导出：
  `kind=UTTERANCE` 的 `endpointToFinalLatencyMs / utteranceE2eLatencyMs / rtf`、`kind=SPEAKER_VAD` 的
  `inferMs`、`kind=STREAM_TRANSITION` 次数，可以直接判定是 SDK 内部耗时还是整机被占满。
- 小乔启动参数：`enableSpeakerVad`、`vadEnd`、`recognizerMode`、是否同时开启角色分离。

## 五、我方可做的下一步（待客户数据确认后）

- 弱机降负载：声纹 extractor 线程按大核数封顶而不是固定 8；pre-target 端点后的硬重启改软重置或减少
  warm-up；非机主确认后降低打分跳频。
- 本机打包注意：默认 `.secure/harmony-signing.json` 指向的 `.secure/signing/asr-demo/certificate.cer`
  叶子证书 2026-09-15 已到期，`build_install_smoke.sh` 会拒绝；改用
  `HARMONY_SIGNING_CONFIG=.secure/harmony-signing-signing-project.json`（叶子证书有效至 2027-09-30，
  同 bundle，11-02 #92 分析时已这样用过）即可构建。`hdc shell taskset` 对应用进程无权限，无法在
  Mate 80 上用绑小核模拟弱机。

## 六、证据

`~/amphion-evidence/20261117-issue98-round3/`：`fixture/`（录音 + 注册音 + manifest，SHA 见
`fixture-sha256.txt`）、`device-runs/20261117-235806-speaker-vad-turn-bff9b3d2/`（report.json、hilog.txt、
memory.csv）、`device-runs/20261118-000901-speaker-vad-turn-b14db16e/`（重复运行）、`analyze.py`。
