# 声纹与最大音频时长发布门禁

本文定义 Harmony 鼎桥 SDK 声纹分数和 `maxAudioDuration` 的可重复测试流程。目标是证明原始症状
已修复、相邻生命周期没有回退，并留下可审计 artifact；不以 Demo UI 或文本准确率代替 SDK 契约。

2026-07-17 当前修复的完整执行记录见
[`VOICEPRINT_DURATION_REGRESSION_EVIDENCE_20260717.md`](./VOICEPRINT_DURATION_REGRESSION_EVIDENCE_20260717.md)。

## 1. 输入与环境

固定记录：

- Git commit；
- HAP 和交付 HAR 的 SHA-256；
- USB 设备序列号、型号和系统版本；
- 注册 WAV、识别 WAV 的 SHA-256；
- requested/effective `maxAudioDuration`、`vadBegin`、`vadEnd`；
- `enableVoiceprintVerification`、`enableSpeakerVad` 和 voiceprint ID 数量。

真机只使用 `ZH_EN` 测试 HAP。`voiceprint-fallback` 数据目录必须只包含：

```text
000_enroll.wav
001_recognize.wav
```

第一条用于注册，第二条必须是已确认满足以下红灯的识别语料：旧版本产生非空 endpoint final 但
`speakerSimilarity` 缺失。客户语料不得提交仓库；artifact 的 `payload/corpus.json` 和外部受控
存储中的 SHA-256 用于复播。

## 2. 阶段 A：修复前红灯

同一旧 HAP、同一输入、同一参数至少运行三轮：

```bash
python3 delivery/harmony-dingqiao/delivery/run_device_stress.py \
  --data-dir "$FALLBACK_CORPUS" \
  --mode voiceprint-fallback --cycles 3 --files 0 \
  --skip-build-install
```

预期旧版本失败原因为 `endpoint-final-missing-speaker-score`。如果没有稳定复现，不得继续宣称根因
已证明，应先检查语料顺序、声纹开关、ID、ASR 文本和实际 PCM 时长。

## 3. 阶段 B：主机确定性门禁

```bash
python3 -m unittest \
  asr.tools.tests.test_harmony_speaker_score_fallback \
  asr.tools.tests.test_harmony_effective_speech_buffer \
  asr.tools.tests.test_harmony_max_audio_duration_policy \
  asr.tools.tests.test_harmony_initial_silence_tracker \
  asr.tools.tests.test_harmony_rejected_final_lifecycle \
  asr.tools.tests.test_harmony_voiceprint_capability \
  delivery.harmony-dingqiao.delivery.test_run_device_stress -v
```

停止条件：

- 任一测试失败；
- strict 不再优先；
- 无 ASR 证据或短 PCM 也进入回退；
- `8000` 不再转换为 256000 字节；
- 缺省、非正数或非法值隐式启用时长限制。

随后运行仓库全部 Python 单测与 Android 同名生命周期单测，防止共享契约漂移：

```bash
python3 -m unittest discover -s asr/tools/tests -p 'test_*.py' -v
python3 -m unittest discover -s delivery/harmony-dingqiao/delivery -p 'test_*.py' -v

cd asr/android
./gradlew --no-daemon :sdk:testDebugUnitTest :sdk-dingqiao:testDebugUnitTest --console=plain
./gradlew --no-daemon :sdk:testReleaseUnitTest :sdk-dingqiao:testReleaseUnitTest \
  --rerun-tasks --console=plain
```

## 4. 阶段 C：构建身份

从当前 commit 隔离构建、签名、安装一次：

```bash
delivery/harmony-dingqiao/delivery/build_install_smoke.sh
shasum -a 256 \
  delivery/harmony-dingqiao/samples/dingqiao-demo/entry/build/default/outputs/default/*signed.hap
```

安装后其余模式统一使用 `--skip-build-install`，不得在矩阵中途替换 HAP。构建产物必须确认：

- 包含 `SpeakerScoreFallback`；
- 不包含 `MIN_MAX_AUDIO_DURATION_MS`；
- HAP/HAR 模型、native 库、license 和签名校验通过。

## 5. 阶段 D：问题定向真机门禁

### 声纹回退

```bash
python3 delivery/harmony-dingqiao/delivery/run_device_stress.py \
  --data-dir "$FALLBACK_CORPUS" \
  --mode voiceprint-fallback --cycles 6 --files 0 \
  --skip-build-install
```

必须满足：

- 6/6 SDK PASS；
- 第一条非空 endpoint final 均有 `speakerSimilarity`；
- 第 1 轮 cold、后续 warm 均通过；
- 显式 `finish` 前 `isLast=0`；
- 每轮一次 last、一次 complete，native stream 为 0。

### 8 秒上限

```bash
python3 delivery/harmony-dingqiao/delivery/run_device_stress.py \
  --data-dir "$TESTDATA" \
  --mode max-duration --cycles 2 --files 1 \
  --skip-build-install
```

第 0 轮 burst、第 1 轮 paced，都必须报告 `fedFrames=400`、一次 last、一次 complete、无 error。
paced 墙钟时间不得明显早于 8 秒。80 个迟到帧后计数不变。

### 声纹相邻不变量

```bash
python3 delivery/harmony-dingqiao/delivery/run_device_stress.py \
  --data-dir "$TESTDATA" \
  --mode voiceprint --cycles 7 --files 2 \
  --skip-build-install
```

短句允许无分数；门槛、长句、前置静音、低音量、多句和 alternate-source 必须按各自契约通过。
该模式不比较目标/非目标分数高低。

## 6. 阶段 E：完整 USB 回归

同一 HAP 至少覆盖：

```text
burst paced vad-begin vad-begin-silence
voiceprint voiceprint-fallback voiceprint-vad-begin voiceprint-vad-begin-idle
cancel cancel-full max-duration numeric-edge
edge reentrant start-cancel start-write start-write-reload
reconfigure recreate speaker-vad-onstart callback-api-reentrant
endpoint-reentrant user-sequence
```

每个模式保存独立目录，不能覆盖失败 artifact。生命周期模式只判断状态、归属、顺序、错误码和恢复；
不能通过放宽空结果率掩盖 final/last/complete 错误。至少一组运行超过 60 秒，用于区分模型驻留和持续
RSS 增长。

## 7. 结果分类

- **PASS**：当前 commit、HAP、设备和输入下所有契约成立。
- **FAIL**：SDK 或测试断言明确失败，必须修复或解释测试预期错误后原参数重跑。
- **INCONCLUSIVE**：HDC 断连、系统杀进程、资源观察不足等无法判断 SDK 的情况；不得记作 PASS。

短轮资源指标为 `INCONCLUSIVE` 不影响其生命周期结论；资源是否回退必须由超过 60 秒的长轮次决定。

## 8. 合入检查

1. 检查 PR 当前 HEAD 的全部 CI 和 review threads。
2. 确认 `CONTRACT_TESTS.md`、客户接口文档和实现对时长及分数可选性的描述一致。
3. 报告中列出已覆盖模式、轮数、设备、系统、commit、HAP 哈希、artifact 和未覆盖外部故障。
4. 不使用“覆盖所有边界”或“保证精度”表述；本门禁证明接口和生命周期不回退，声纹精度另走身份
   标注评测。
