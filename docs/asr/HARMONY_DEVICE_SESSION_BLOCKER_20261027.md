# 端侧真实音频会话失败：9001 Invalid parameter（阻塞端侧验收）

**结论先行：当前这台设备上，SDK 无法完成一次真实音频识别会话。该现象在未改动的
基线包上同样复现，与四川话换模型、与警务后处理裁剪均无关。** 因此包 A / 包 B 的
端侧逐项基线（时延、功耗、分档准确率）目前测不出来。

## 现象

```
trace = start > event-1 > partial > partial > partial
        > error-1002200011(RECOGNITION_ERROR)
        > error-1002200010 ×3 (NOT_LISTENING)
        > error-1002200004 (FINISH_FAILED)
detail = finish-contract-9001:_Error:_Invalid_parameter
```

- 会话能起，VAD 能检出语音（audioStartToSpeechBeginMs ≈ 563 ms）
- partial 能出（首个非空 ≈ 1571–2274 ms，取决于语料）
- 随后原生层抛 `9001: Error: Invalid parameter`（`AsrErrorCode.NATIVE_CRASH`）
- `handleAsrError` 调 `tearDownSession()`，所以后续 `writeAudio` 全是 NOT_LISTENING，
  `finish` 必然失败 —— 这些是**次生错误**，不是根因

## 复现矩阵

| 包 | 语料 | 模式 | 结果 |
|---|---|---|---|
| A 基线（main 094ba3b1，零改动） | aishell3_test_hotwords_500（44.1 kHz） | paced | FAIL，3 partial 后报错 |
| A 基线 | aishell3_test_hotwords_500 | burst | FAIL，0 partial 即报错 |
| A 基线 | dingqiao-meeting-20260918（原生 16 kHz，108 s） | paced | FAIL，4 partial 后报错，errors=8197 |
| B 四川话/无后处理 | aishell3_test_hotwords_500 | paced | FAIL，同一错误文本 |

与采样率无关（44.1 kHz 与原生 16 kHz 都失败），与模型无关（police 1.4.0 与四川话都失败），
与警务后处理无关（开与裁剪都失败）。

## 已排除

- **SDK 生命周期正常**：demo self-test 在包 A 上 62/62 全过，在包 B 上 34/34 全过
  （差的 28 项是按资产变体跳过的警务后处理用例）。启停、重入、取消、license、
  声纹错误码、`writeAudio` 错误尺寸拒绝等全部符合契约。
- **license 正常**：self-test `unloadRuntime retains activated license | status=0 features=ASR,TTS`。
- **帧长不是原因**：`feedPcmFile` 用固定 640 字节缓冲 + `fill(0)`，每次 `writeAudio`
  都是满帧，尾部短读被补零。宿主侧 PCM 不是 640 的整数倍（`103360 % 640 = 320`）
  这一点本身不触发错误。
- **不是我方出包改动引入**：基线包 A 构建自 main `094ba3b1`，不含本轮任何改动。

## 定位到的位置

错误文本形如 `${error.code}: ${error.message}` 且不含 `audio dispatch failed:` 前缀，
说明来自原生回调 `onError`（`SpeechRecognizeSdk.ets` 的 `DingqiaoAsrCallback.onError`
→ `handleAsrError`），而不是音频分发器的包装错误。

上游候选在 `asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets`：
`acceptPcmFloatNow` / `acceptPcmFloatNowAsync`（行 1600 / 1621）捕获异常后以
`AsrErrorCode.NATIVE_CRASH` 上报，这两处包的是 AGC ingress（`agcIngress.accept` /
`acceptAsync`）。`Error: Invalid parameter` 是 NAPI BusinessError 的文本形态。

**下一步建议**：在 `Runtime.ets:1600/1621` 两处把被捕获异常的 NAPI 侧 code 一并带出，
或让 `--capture-diagnostics` 的导出路径在 debug 载体上可用（本次导出失败：
`carrier did not export an identified diagnostic run`），即可定位到具体 NAPI 调用。

## 顺带修掉的可观测性缺口

SDK 的 `onError` 文本原先只在 **start 阶段**失败时才进结果行（`detail=start-<msg>`）；
会话中途的原生错误既不进 hilog 也不进结果行，这类失败在宿主侧完全不可定位。
现在 `DeviceStressTest.ets` 把首个错误文本附到所有失败路径的 `detail` 上 ——
上面那条 `9001: Error: Invalid parameter` 就是靠这个拿到的。

## 当前能确认的端侧数字（不构成基线）

以下来自失败会话，仅作参考，**不可用于验收**：

| | 包 A 基线 | 包 B 四川话/无后处理 |
|---|---|---|
| speech begin 时延 | ≈ 563 ms | ≈ 563 ms |
| 首个非空 partial | 1571–1633 ms | ≈ 1616 ms |
| 峰值 RSS | 400–422 MB | 358 MB |
| self-test | 62/62 | 34/34（警务组按变体跳过） |

包 B 的峰值 RSS 明显低于包 A，与裁掉 30 MB LAC 人名模型 + 3 个 FST 的预期一致，
但这是失败会话的采样，不能当作内存基线。
