# 鸿蒙端侧会话在第一个语音段处死亡：ArkTS 拒绝 napi_create_typedarray

**影响范围：任何带停顿的真实会话。** 会话起得来、VAD 能检出语音、partial 能出，
但第一个完整语音段产出时原生层抛 `9001: Error: Invalid parameter`，
`handleAsrError` 调 `tearDownSession()`，此后 `writeAudio` 全是 NOT_LISTENING、
`finish` 必然失败。**现网基线包同样中招** —— 不是本轮换模型或裁剪引入的。

## 根因

`Vad.front()` 必须把语音段的样本物化成 `Float32Array`。原生 wrapper 里：

```cpp
Napi::ArrayBuffer arrayBuffer = Napi::ArrayBuffer::New(env, /*bytes*/);   // 成功
Napi::Float32Array float32Array =
    Napi::Float32Array::New(env, segment->n, arrayBuffer, 0);             // 抛
```

插桩实测（`n=42496`，缓冲区 `169984` 字节 = 4 × 42496，尺寸完全正确）：

```
VADFRONT n=42496 start=4192 nonnull=1
VADFRONT step=arraybuffer-ok bytes=169984
          ← typedarray-ok 没有打印
```

**ArkTS 的 `napi_create_typedarray` 即使在尺寸正确的 ArrayBuffer 上也返回
`napi_invalid_arg`**，到 ArkTS 层表现为一个没有 code 的 `Error: Invalid parameter`。
外部缓冲路径和复制路径都走这一步，所以两条路都不可用 —— 在鸿蒙上 `front()`
根本不可能工作。

排错过程中验证并排除的（留档以免重复）：

- 不是帧长：`feedPcmFile` 用固定 640 字节缓冲 + `fill(0)`，每次 `writeAudio` 都是满帧
- 不是采样率：44.1 kHz 的 AISHELL-3 与原生 16 kHz 的会议音频都失败
- 不是空段：实测 `n=42496`，非空且非零
- 不是外部缓冲独有：改 `front(false)` 走复制路径同样抛
- 不是生命周期/license：demo self-test 62/62 全过，license `features=ASR,TTS`

## 修法

我方 SDK 的两个 `front()` 调用点（`Runtime.ets` 的 `advanceVadGate` 与
`advanceVadGateAsync`）**只读 `segment.start` 与 `segment.samples.length`，
从不碰样本数据**。所以不去修 typed array，而是绕开它：

| 补丁 | 内容 |
|---|---|
| `0034-fix-harmony-copy-vad-speech-segments.patch` | `front()` 不再 alias 原生内存：显式拒绝空段，空样本视图用 1 个 float 兜底（0 字节 ArrayBuffer 同样被拒），一律复制 |
| `0035-feat-harmony-vad-front-meta.patch` | 新增 `voiceActivityDetectorFrontMeta` / `Vad.frontMeta()`，只返回 `{start, n}` 并释放段，不构造 Float32Array |

`Runtime.ets` 两处改用 `frontMeta()`。`front()` 保留原样，供真的需要样本的调用方
（在鸿蒙上它仍然不可用，这是上游/平台问题，值得单独上报）。

## 验证

修复前后同一台设备、同一语料、同一参数：

| | 修复前 | 修复后 |
|---|---|---|
| 会话 | FAIL，3 partial 后报错，finals=0 | PASS，finals=1，finalChars=13，errors=0 |
| 60 条连跑 | 未能进行 | 60/60 全过，空 final 率 0.000 |

两个交付包的端侧基线见 `docs/asr/HARMONY_TWO_VARIANT_PACKAGING.md`。

## 顺带修掉的可观测性缺口

SDK 的 `onError` 文本原先只在 **start 阶段**失败时才进 stress 结果行；会话中途的
原生错误既不进 hilog 也不进结果行 —— 这正是这个缺陷长期没被发现的原因。现在：

- `DeviceStressTest.ets` 把首个错误文本附到所有失败路径的 `detail` 上
- `Runtime.ets` 的音频写入捕获点把异常文本、NAPI code 与调用栈打到 hilog
  （`AmphionAsrAccept` tag）

这两处是定位本缺陷的全部依据，建议保留。

## 另外发现

`build_install_smoke.sh` 只验到「引擎就绪」，**从不验证真的识别一句话**。
正因如此，一个让所有真实会话失败的缺陷能通过全部出包门禁。建议在冒烟里加一条
端到端识别断言（跑一条已知音频、断言 final 非空）。
