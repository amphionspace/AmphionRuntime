# Harmony 离线 ASR SDK 生命周期性能报告

**测试类型：10 次独立进程全流程**

**测试日期：2026-07-13**

## 1. 结论摘要

- 使用同一签名 HAP，连续执行 10 次“停止旧进程 → 拉起新进程 → 完整生命周期测试”，结果为 **PASS 10/10**。
- 每次均执行：`setLicense()` → `prepareRuntime()` → 模型加载 → 真实 PCM Session → 同模型复用 → `unloadModel()` → `unloadRuntime()`。
- 10 次测试进程内的接口链路加固定观察等待，p50 为 **2.409 秒**，p95 为 **2.593 秒**；从首轮基线到末轮汇总的实测批次墙钟为 **41.514 秒（约 42 秒）**。
- `setLicense()`：p50 **23.5 ms**，p95 **27.8 ms**。
- 首次 `prepareRuntime()`：p50 **1.0 ms**，p95 **2.1 ms**；幂等调用 10/10 均低于 1 ms。
- 每个新进程首次 `createEngineAsync()`：p50 **601.5 ms**，p95 **765.0 ms**。
- 同配置模型复用：p50 **3.0 ms**，p95 **4.0 ms**。
- `unloadModel()`：p50 **49.5 ms**，p95 **55.6 ms**。
- `unloadRuntime()`：p50 低于 **1 ms**，p95 **1 ms**。
- 推理离散采样高水位 p50：VmRSS **398.5 MiB**、RssAnon **166 MiB**；相对各轮接口前基线分别为 **+274.5 MiB**、**+96 MiB**。
- `unloadModel()` 返回后 400 ms 的 p50：VmRSS **215 MiB**、RssAnon **148 MiB**；相对各轮接口前基线仍为 **+91 MiB**、**+77.5 MiB**。
- Runtime 接口目前提供的是授权后的逻辑生命周期门禁和 ready 状态，不承担模型加载，也不能在进程存活期间卸载 native `.so`。因此其耗时和动态内存增量较小，符合当前实现。

> 本报告验证接口链路、阶段耗时和进程内存，不验证 CER 或识别文本准确率。

## 2. 测试耗时说明

本次补测从第一轮接口前基线到第十轮结果汇总，实测跨时 41.514 秒，交付复测可按约 42 秒估算。其中：

- 每次测试固定包含 `unloadModel()` 返回后 400 ms 和 `unloadRuntime()` 返回后 800 ms 的内存观察等待。
- 十轮固定等待合计 12 秒。
- 批次墙钟还包含进程停止、重新拉起、轮间调度和主机轮询结果的开销。
- 不包含 HAP 构建、安装、报告生成及测试结束后的额外空闲回收观察。

从每个进程的“接口前基线采样”到结果汇总，单轮范围为 2.301～2.726 秒；这不是单次业务识别延迟，其中包含 1.2 秒固定观察等待。

## 3. 测试环境

| 项目 | 测试配置 |
| --- | --- |
| 设备 | HUAWEI Mate 70 Pro（PLR-AL00） |
| 系统 | HarmonyOS 6.1.0.117，API 23，arm64 |
| 模型 | INT8 encoder/joiner + FP32 decoder（ONNX Runtime） |
| Prepack | off（`DisablePrepacking=1`） |
| 测试方式 | Headless Demo；每轮强制停止旧进程并拉起新进程 |
| 独立进程数 | 10 |
| 每进程 Session 数 | 1 |
| PCM 输入 | 16 kHz、16-bit、单声道；不按实时速度限速，以最大吞吐写入 SDK |
| 测试语料 | 10 轮重复同一条 1.62 秒 PCM |
| 语料 ID | `zhaidatatang_G0002_T0055G0002S0183` |
| 参考文本 | `你能识别多音字吗` |
| 内存来源 | `/proc/self/status` 的 VmRSS、RssAnon、RssFile |
| 换算方式 | 1024 KiB = 1 MiB，四舍五入到整数 MiB |
| 统计方式 | p95 使用线性插值；原始 0 ms 按“低于 1 ms”解释 |

## 4. 每轮实际执行序列

```text
停止旧进程并拉起新进程
→ 采集调用 SDK 接口前的进程基线
→ SpeechRecognizeSdk.init()
→ setLicense()
→ prepareRuntime() 首次调用
→ prepareRuntime() 幂等调用
→ createEngineAsync()（当前进程首次模型加载）
→ startListening()
→ writeAudio()
→ finish() / onComplete
→ engine.shutdown()
→ createEngineAsync()（同配置模型复用）
→ engine.shutdown()
→ unloadModel()
→ 立即采样
→ 等待 400 ms 后采样
→ unloadRuntime()
→ 立即采样
→ 等待 800 ms 后采样
```

十次测试均使用同一个已安装 HAP。应用私有文件、系统文件页缓存和设备全局状态不会因进程重启而被清空，因此这是“进程冷启动”，不是每轮恢复出厂式的设备冷启动。

## 5. API 层级和当前资源边界

| 层级 | 加载接口 | 卸载接口 | 当前实现的实际职责 |
| --- | --- | --- | --- |
| License | `setLicense()` | — | 离线授权校验并缓存有效授权；不再隐式调用 `prepareRuntime()` |
| Runtime | `prepareRuntime()` | `unloadRuntime()` | 授权后的状态校验、生命周期门禁和 ready 状态；不创建模型 Session |
| Model | `createEngineAsync()` / `createEngine()` | `unloadModel()` | 创建引擎并加载模型；同配置模型已加载时直接复用 |

需要特别说明：

1. `prepareRuntime()` 已从 `setLicense()` 的调用时序中拆出，但当前仍是**逻辑层拆分**，不是大型 native Runtime 资源的物理拆分。
2. 主要 ONNX Runtime Session、模型权重和推理资源在 `createEngineAsync()` / `createEngine()` 阶段创建。
3. native `.so` 随应用进程装载，当前 `unloadRuntime()` 不能在进程存活期间将其真正卸载。
4. 因此，`prepareRuntime()` 和 `unloadRuntime()` 很快并不等于 SDK Runtime 总体积为零。

## 6. 十轮阶段耗时

### 6.1 汇总

| 阶段 | min | mean | p50 | p95 | max |
| --- | ---: | ---: | ---: | ---: | ---: |
| 基线采样至结果汇总，含 1.2 秒固定等待 | 2301 ms | 2424.0 ms | 2408.5 ms | 2592.8 ms | 2726 ms |
| `setLicense()` | 22 ms | 24.1 ms | 23.5 ms | 27.8 ms | 30 ms |
| `prepareRuntime()` 首次调用 | <1 ms | 1.0 ms | 1.0 ms | 2.1 ms | 3 ms |
| `prepareRuntime()` 幂等调用 | <1 ms | <1 ms | <1 ms | <1 ms | <1 ms |
| `createEngineAsync()`：新进程首次模型加载 | 563 ms | 626.3 ms | 601.5 ms | 765.0 ms | 882 ms |
| 第 2～10 轮模型加载，OS 文件页缓存已热 | 563 ms | 597.9 ms | 601.0 ms | 614.8 ms | 622 ms |
| `startListening()` | 18 ms | 20.7 ms | 20.5 ms | 24.1 ms | 25 ms |
| `finish()` | 192 ms | 199.9 ms | 200.5 ms | 206.7 ms | 208 ms |
| Session 开始至 `onComplete` | 420 ms | 512.5 ms | 526.5 ms | 558.3 ms | 561 ms |
| Session 开始至首次 `onResult` | 126 ms | 211.4 ms | 223.5 ms | 255.1 ms | 269 ms |
| RTF | 0.259 | 0.316 | 0.325 | 0.345 | 0.346 |
| 首个 Engine `shutdown()` | <1 ms | <1 ms | <1 ms | <1 ms | <1 ms |
| `createEngineAsync()`：同配置模型复用 | 3 ms | 3.3 ms | 3.0 ms | 4.0 ms | 4 ms |
| 复用 Engine `shutdown()` | <1 ms | <1 ms | <1 ms | <1 ms | <1 ms |
| `unloadModel()` | 41 ms | 48.7 ms | 49.5 ms | 55.6 ms | 56 ms |
| `unloadRuntime()` | <1 ms | 0.2 ms | <1 ms | 1.0 ms | 1 ms |

### 6.2 耗时解读

- 第一轮模型加载为 882 ms；第 2～10 轮为 563～622 ms。每轮都是新进程首次建模，但后续轮次受系统文件页缓存影响。
- `finish()` 包含尾部解码，不是单纯的状态切换耗时。
- 本轮 `onComplete` 均在 `finish()` 调用期间完成；毫秒整数时钟不能可靠拆分更小的回调差值。
- RTF 和 Session 耗时基于 PCM 最大吞吐写入，不代表用户实时讲话时的端到端墙钟等待。
- 10 个样本的 p95 适合描述本次测试，不应直接作为长期 SLA 上界。

## 7. 十轮阶段内存

### 7.1 口径

- **VmRSS**：进程总驻留内存，包括匿名页和文件映射页。
- **RssAnon**：匿名驻留内存，是观察进程匿名内存压力的主要指标，但不等同于 SDK 独占内存。
- “相对基线”按每一轮当前采样值减去该轮接口前进程基线，再对差值做统计。
- 十轮接口前基线 p50：VmRSS 124 MiB，RssAnon 70 MiB。

### 7.2 VmRSS

| 采样阶段 | 绝对值 p50 | 相对该轮基线 p50 | 绝对值 p95 | 绝对值 max |
| --- | ---: | ---: | ---: | ---: |
| 调用 SDK 接口前基线 | 124 MiB | 0 MiB | 125 MiB | 125 MiB |
| SDK `init()` 后 | 124 MiB | 0 MiB | 125 MiB | 125 MiB |
| `setLicense()` 前 | 125 MiB | +1 MiB | 126 MiB | 126 MiB |
| `setLicense()` 返回 | 131 MiB | +7 MiB | 132.6 MiB | 133 MiB |
| `prepareRuntime()` 首次返回 | 131 MiB | +7 MiB | 132.6 MiB | 133 MiB |
| `prepareRuntime()` 幂等返回 | 131 MiB | +7 MiB | 132.6 MiB | 133 MiB |
| 模型首次加载返回 | 212.5 MiB | +88 MiB | 223 MiB | 223 MiB |
| `startListening()` 返回 | 223.5 MiB | +99.5 MiB | 234 MiB | 234 MiB |
| `finish()` 返回 | 398.5 MiB | +274 MiB | 408.9 MiB | 412 MiB |
| `onComplete` 后 | 398.5 MiB | +274.5 MiB | 408.9 MiB | 412 MiB |
| 首个 Engine `shutdown()` 返回 | 398.5 MiB | +274.5 MiB | 408.9 MiB | 412 MiB |
| 同配置模型复用返回 | 399.5 MiB | +275 MiB | 409.9 MiB | 413 MiB |
| 复用 Engine `shutdown()` 返回 | 399.5 MiB | +275 MiB | 409.9 MiB | 413 MiB |
| `unloadModel()` 立即返回 | 215 MiB | +91 MiB | 218.1 MiB | 219 MiB |
| `unloadModel()` 返回后 400 ms | 215 MiB | +91 MiB | 219.1 MiB | 220 MiB |
| `unloadRuntime()` 立即返回 | 215 MiB | +91 MiB | 219.6 MiB | 220 MiB |
| `unloadRuntime()` 返回后 800 ms | 215 MiB | +91 MiB | 219.6 MiB | 220 MiB |

### 7.3 RssAnon

| 采样阶段 | 绝对值 p50 | 相对该轮基线 p50 | 绝对值 p95 | 绝对值 max |
| --- | ---: | ---: | ---: | ---: |
| 调用 SDK 接口前基线 | 70 MiB | 0 MiB | 71 MiB | 71 MiB |
| SDK `init()` 后 | 70 MiB | 0 MiB | 71 MiB | 71 MiB |
| `setLicense()` 前 | 71 MiB | 0 MiB | 71 MiB | 71 MiB |
| `setLicense()` 返回 | 71 MiB | +1 MiB | 72 MiB | 72 MiB |
| `prepareRuntime()` 首次返回 | 71 MiB | +1 MiB | 72 MiB | 72 MiB |
| `prepareRuntime()` 幂等返回 | 71 MiB | +1 MiB | 72 MiB | 72 MiB |
| 模型首次加载返回 | 135 MiB | +65 MiB | 146 MiB | 146 MiB |
| `startListening()` 返回 | 144.5 MiB | +74 MiB | 157 MiB | 157 MiB |
| `finish()` 返回 | 166 MiB | +96 MiB | 174.2 MiB | 180 MiB |
| `onComplete` 后 | 166 MiB | +96 MiB | 174.2 MiB | 180 MiB |
| 首个 Engine `shutdown()` 返回 | 166 MiB | +96 MiB | 174.2 MiB | 180 MiB |
| 同配置模型复用返回 | 167 MiB | +97 MiB | 175.2 MiB | 181 MiB |
| 复用 Engine `shutdown()` 返回 | 167 MiB | +97 MiB | 175.2 MiB | 181 MiB |
| `unloadModel()` 立即返回 | 147.5 MiB | +77.5 MiB | 149.6 MiB | 150 MiB |
| `unloadModel()` 返回后 400 ms | 148 MiB | +77.5 MiB | 149.6 MiB | 150 MiB |
| `unloadRuntime()` 立即返回 | 148 MiB | +77.5 MiB | 149.6 MiB | 150 MiB |
| `unloadRuntime()` 返回后 800 ms | 148 MiB | +77.5 MiB | 149.6 MiB | 150 MiB |

## 8. 十轮逐轮耗时

### 8.1 Runtime 与模型加载

| 轮次 | 全链路含等待 | setLicense | prepareRuntime | 模型首次加载 |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 2726 ms | 30 ms | 3 ms | 882 ms |
| 2 | 2409 ms | 24 ms | <1 ms | 590 ms |
| 3 | 2408 ms | 22 ms | 1 ms | 563 ms |
| 4 | 2406 ms | 23 ms | 1 ms | 602 ms |
| 5 | 2312 ms | 25 ms | 1 ms | 601 ms |
| 6 | 2420 ms | 22 ms | 1 ms | 604 ms |
| 7 | 2427 ms | 25 ms | <1 ms | 604 ms |
| 8 | 2430 ms | 23 ms | 1 ms | 622 ms |
| 9 | 2301 ms | 23 ms | 1 ms | 599 ms |
| 10 | 2401 ms | 24 ms | 1 ms | 596 ms |

### 8.2 模型复用与卸载

| 轮次 | 模型复用 | unloadModel | unloadRuntime |
| ---: | ---: | ---: | ---: |
| 1 | 4 ms | 43 ms | <1 ms |
| 2 | 3 ms | 46 ms | <1 ms |
| 3 | 4 ms | 51 ms | <1 ms |
| 4 | 3 ms | 41 ms | <1 ms |
| 5 | 3 ms | 51 ms | <1 ms |
| 6 | 3 ms | 56 ms | 1 ms |
| 7 | 3 ms | 51 ms | <1 ms |
| 8 | 4 ms | 55 ms | <1 ms |
| 9 | 3 ms | 48 ms | 1 ms |
| 10 | 3 ms | 45 ms | <1 ms |

### 8.3 Session

| 轮次 | startListening | finish | Session 至 complete | 首次结果 | RTF |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 22 ms | 205 ms | 555 ms | 223 ms | 0.343 |
| 2 | 23 ms | 208 ms | 536 ms | 223 ms | 0.331 |
| 3 | 18 ms | 196 ms | 561 ms | 269 ms | 0.346 |
| 4 | 18 ms | 197 ms | 525 ms | 226 ms | 0.324 |
| 5 | 20 ms | 198 ms | 421 ms | 126 ms | 0.260 |
| 6 | 19 ms | 201 ms | 527 ms | 235 ms | 0.325 |
| 7 | 23 ms | 201 ms | 534 ms | 238 ms | 0.330 |
| 8 | 21 ms | 200 ms | 520 ms | 224 ms | 0.321 |
| 9 | 25 ms | 192 ms | 420 ms | 127 ms | 0.259 |
| 10 | 18 ms | 201 ms | 526 ms | 223 ms | 0.325 |

## 9. 十轮逐轮内存

每个单元格格式为 `VmRSS / RssAnon`，单位均为 MiB。

### 9.1 加载链路

| 轮次 | 接口前基线 | setLicense 后 | prepareRuntime 后 | 模型加载后 | Session 创建后 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 125 / 70 | 133 / 71 | 133 / 72 | 213 / 135 | 222 / 143 |
| 2 | 125 / 71 | 132 / 72 | 132 / 72 | 223 / 146 | 234 / 157 |
| 3 | 124 / 70 | 131 / 71 | 131 / 71 | 211 / 134 | 222 / 144 |
| 4 | 124 / 70 | 131 / 71 | 131 / 71 | 211 / 135 | 221 / 144 |
| 5 | 124 / 70 | 131 / 71 | 131 / 71 | 213 / 135 | 226 / 146 |
| 6 | 124 / 71 | 132 / 72 | 132 / 72 | 211 / 134 | 222 / 145 |
| 7 | 124 / 70 | 131 / 71 | 131 / 71 | 222 / 146 | 233 / 156 |
| 8 | 124 / 70 | 131 / 71 | 131 / 71 | 212 / 136 | 221 / 144 |
| 9 | 124 / 70 | 131 / 71 | 131 / 71 | 212 / 134 | 225 / 144 |
| 10 | 124 / 71 | 132 / 72 | 132 / 72 | 223 / 146 | 234 / 157 |

### 9.2 推理与卸载链路

| 轮次 | 推理离散高水位 | 模型复用后 | unloadModel 返回 | unloadModel 后 400 ms | unloadRuntime 后 800 ms |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 400 / 166 | 400 / 167 | 217 / 150 | 218 / 150 | 218 / 150 |
| 2 | 396 / 165 | 397 / 166 | 213 / 146 | 213 / 146 | 213 / 146 |
| 3 | 397 / 166 | 398 / 167 | 215 / 148 | 215 / 148 | 215 / 148 |
| 4 | 398 / 166 | 399 / 167 | 215 / 149 | 216 / 149 | 211 / 144 |
| 5 | 405 / 166 | 406 / 167 | 219 / 147 | 220 / 147 | 220 / 148 |
| 6 | 398 / 167 | 399 / 168 | 212 / 146 | 213 / 146 | 213 / 146 |
| 7 | 396 / 164 | 397 / 165 | 214 / 148 | 215 / 148 | 215 / 148 |
| 8 | 399 / 167 | 400 / 168 | 215 / 148 | 215 / 149 | 216 / 149 |
| 9 | 405 / 167 | 406 / 168 | 217 / 145 | 218 / 146 | 219 / 146 |
| 10 | 412 / 180 | 413 / 181 | 214 / 147 | 214 / 148 | 215 / 148 |

“推理离散高水位”取测试代码设置的若干阶段采样点中的最大值，不是高频采样器捕获的瞬态绝对峰值。

## 10. 卸载与延迟回收

独立进程十轮中：

- `unloadModel()` API 调用 p50 为 49.5 ms。
- API 返回时，VmRSS 从模型复用后的 p50 399.5 MiB 降至 215 MiB。
- API 返回后 400 ms，VmRSS p50 为 215 MiB，RssAnon p50 为 148 MiB。
- 随后 `unloadRuntime()` 的调用和 800 ms 等待未产生稳定可见的额外下降，符合其当前主要是逻辑状态复位的实现。

按每轮峰值与 `unloadModel()` 后 400 ms 做配对差值，VmRSS 回落的 p50 为 183.5 MiB，RssAnon 回落的 p50 为 18.5 MiB，RssFile 回落的 p50 为 165 MiB。可见短窗口内释放主体是模型文件映射页，匿名驻留内存回落较少。

第 10 个测试进程在 12:45:02.784 完成测试；设备于 12:45:17.368 自动记录 Ark idle Full GC。保持同一进程空闲至 12:47:31 再采样，内存为：

| 采样点 | VmRSS | RssAnon | RssFile |
| --- | ---: | ---: | ---: |
| 第 10 轮 `unloadRuntime()` 后 800 ms | 215 MiB | 148 MiB | 67 MiB |
| 继续空闲约 2 分 28 秒后 | 146 MiB | 77 MiB | 69 MiB |
| 第 10 轮接口前基线 | 124 MiB | 71 MiB | — |

这是测试完成后的附加观察，不属于固定 800 ms 的正式采样阶段。自动 Full GC 与内存回落在时间上相关，但仅凭本次数据不能把回落严格归因于 GC、N-API finalizer、native allocator 或 ONNX Runtime arena 中的某一项。可以确认的是：

- 800 ms 内存不会立即回到接口前基线。
- 空闲后匿名内存从 148 MiB 回落至 77 MiB，说明短时驻留并非全部永久保留。
- 十轮短测不足以判断是否存在长期泄漏；如甲方验收关注卸载后的即时水位，应预先约定固定等待窗口和采样方法。

## 11. 补充：同一进程连续 10 轮装卸

为观察不重启进程时的高频装卸行为，另执行了同一进程内 10 个模型/Session 周期：

| 指标 | 结果 |
| --- | ---: |
| 端上从进程拉起到汇总 | 17.68 秒 |
| 模型池清空后重新加载 p50 / p95 | 682.0 / 895.7 ms |
| 同配置模型复用 p50 / p95 | 3.5 / 6.8 ms |
| `unloadModel()` p50 / p95 | 50.5 / 56.1 ms |
| 第 1 轮卸载后 400 ms | 220 / 151 MiB（VmRSS / RssAnon） |
| 第 10 轮卸载后 400 ms | 292 / 223 MiB（VmRSS / RssAnon） |
| 后续空闲复测 | 约 150 / 80 MiB（VmRSS / RssAnon） |

17.68 秒是整组十轮任务耗时，其中包含十次 400 ms 和最后一次 800 ms、合计 4.8 秒的固定观察等待，不代表单个业务 Session 耗时。

该补充测试显示：同一进程高频连续装卸时，400 ms 窗口内存在明显内存高水位累积；后续空闲又出现显著回落。此现象可能与延迟 GC/finalizer、native allocator 保留和 ONNX Runtime 内存池有关，当前数据不能进一步归因，也不能据此直接判定或排除长期泄漏。

## 12. 测量边界

1. **接口前基线不是不含 SDK 的空白 Demo。** 测试代码采样前已经静态 import SDK，HAR 及 native 依赖的映射可能已进入进程。
2. **相对基线变化不是 SDK 独占内存。** 它扣除了采样前已经存在的 Demo、ArkUI/ArkTS Runtime 等开销，但仍可能包含 GC、allocator、文件页缓存和测试进程历史状态变化。
3. **完整 SDK 静态映射体积需要对照 HAP。** 应使用相同工程和页面分别制作“不链接 SDK”与“链接 SDK”两个载体，再比较稳定 PSS/RSS。
4. **十轮重复同一条 PCM。** PASS 10/10 只表示生命周期链路完成并收到 final/complete，不代表识别正确率验证通过。
5. **进程冷不等于设备冷。** 强制停止进程不会清除系统文件页缓存，因此第 2～10 轮模型加载比第一轮稳定且更快。
6. **内存是固定阶段的离散采样。** 本报告不宣称捕获到所有瞬态峰值。
7. **只有 10 个样本。** p50/p95 可用于本次交付复核，不应直接作为长期 SLA。

## 13. 验证项汇总

| 验证项 | 结果 |
| --- | --- |
| `setLicense()` 不再隐式调用 `prepareRuntime()` | 通过 |
| 10 个独立进程完整生命周期 | PASS 10/10 |
| `prepareRuntime()` 不加载模型 | 通过 |
| `prepareRuntime()` 幂等调用 | PASS 10/10 |
| 新进程首次创建模型 Engine | PASS 10/10 |
| 同配置模型复用 | PASS 10/10 |
| 真实 PCM Session 与 complete 回调 | PASS 10/10 |
| `unloadModel()` 调用完成 | PASS 10/10 |
| 同进程卸载后再次加载 | PASS 9/9（补充连续装卸测试） |
| `unloadRuntime()` 调用完成 | PASS 10/10 |
| `unloadRuntime()` 后状态负向验证 | 本性能测试未覆盖；由 SDK 自测单独验证 |
| 卸载后 800 ms 回到接口前基线 | 未达到；存在延迟回收 |
| 空闲后匿名内存显著回落 | 已观察到 |

## 14. 测试制品校验

安装测试 HAP：

```text
cfcce67fd1c0017b00b7967a868243dbc9f871f7c573a0cf249add1f8df63ef9
```

`amphion_dingqiao.har`：

```text
8a8e0d5655d9ea498beb9a63612563a669e593214219cb079e6167028a1b9526
```

`amphion_asr.har`：

```text
7beaa3cd253192e5cc449e44bc5971a4dc16a513e729faefec645dcd741787d0
```

`pcm.bin`：

```text
c4e22f496e043fc91c6a655775faf357790017e5e02299f33cd13b985abeb579
```

`manifest.jsonl`：

```text
314a65601306b2e6f63b76de554cc5b72c525b6c984366a32aaca25af7ba0d02
```

## 15. 原始证据

- 十次独立进程的完整 `LIFECYCLE` / `LCITER` 日志：`evidence/20260713/sdk-lifecycle-10-round.log`
- 测试结束后的空闲回收观察：`evidence/20260713/post-idle-memory.log`
- 制品与证据哈希：`evidence/20260713/SHA256SUMS.txt`
