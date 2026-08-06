# Android / HarmonyOS v3.0 SDK 运行稳定性 1000 用例设计

本文档定义 **手机端 SDK 运行稳定性** 验收语料与门禁。  
只关心：不崩溃、可恢复、无资源泄漏、生命周期/队列/流式/播放路径可长期运行。  
**不关心**：发音、拼音、音素、朗读正确性、Android/Harmony 文本读音一致性。

关联产物：

| 产物 | 路径 |
| --- | --- |
| 用例 JSONL（docs 主源） | `docs/android-harmony-v3-parity-1000/android_v3_sdk_stability_1000_cases.jsonl` |
| 汇总 JSON | `docs/android-harmony-v3-parity-1000/android_v3_sdk_stability_1000_summary.json` |
| 生成器 | `docs/android-harmony-v3-parity-1000/generate_v3_sdk_stability_1000_cases.py` |
| Dingqiao 用例副本 | `dingqiao_test_cases/android_v3_sdk_stability_1000_cases.jsonl` |

---

## 1. 目标与非目标

### 目标

在真实 Android / HarmonyOS 手机上证明 SDK 服务层可工业级稳定运行：

1. API 创建 / 查询 / 合成 / 播放 / 停止 / 销毁路径不崩溃、不死锁。
2. 错误路径可预期，且错误后下一次合法请求仍可成功。
3. 重复 create / speak / shutdown 后，Java/native/RSS、fd、线程、TN 子进程可回到基线附近。
4. 队列突发、流式缓冲、播放路由、长文本/TN 载荷下，服务仍能完成并释放资源。
5. Android 与 Harmony 使用 **同一套稳定性门禁**（允许平台采样 API 不同，不允许门禁语义不同）。

### 非目标（明确不做）

- 不测发音、拼音、音素、多音字、姓氏专名读法。
- 不要求 golden 文本读音，不比较 Android/Harmony 读音一致性。
- 不把 `zh-core` / `en-core` / `mixed-zh-en` / TN 读法正确性等旧类别作为稳定性轴。
- 文本只是 **触发服务行为的载荷**；长文本存在的目的是压 TN/管道/热状态，不是验读法。

---

## 2. 稳定性类别与数量

总计 **1000** 条。类别即稳定性维度，不是文本类型维度。

| 类别 | 数量 | 运行稳定性关注点 |
| --- | ---: | --- |
| `smoke-api` | 25 | 冷/热创建、query、speak、stop、shutdown、isBusy 冒烟，确认主路径可跑通。 |
| `engine-create-query` | 75 | 引擎创建、音色查询、延迟加载、多引擎顺序销毁后资源释放。 |
| `workpath-resource-load` | 75 | bundled / external / default workPath 加载与重复 create-destroy 后句柄释放。 |
| `lifecycle-state-machine` | 85 | new / idle / running / queued / destroyed 下 speak、stop、shutdown、isBusy 状态机。 |
| `listener-callback-contract` | 55 | listener 替换、晚注册、回调顺序、终态回调唯一、listener 不泄漏。 |
| `request-queue-scheduler` | 80 | PREEMPT / QUEUE 突发、重入提交、突发中 stop/shutdown、队列排空。 |
| `streaming-config-buffering` | 80 | chunk / firstChunk / pcmQueue 配置路径、冲突优先级、分片连续、队列不死锁。 |
| `playback-channel-audio-route` | 45 | `SYNTHESIZE_AND_PLAY` 路由/声道、非法 channel 可控失败、AudioTrack 释放。 |
| `params-boundary-runtime` | 65 | speed / pitch / volume 边界与 clamp 后仍可完成，且下一次请求仍成功。 |
| `error-validation-recovery` | 75 | 精确错误码 + **每个错误后必须再跑一条合法恢复请求**。 |
| `longtext-tn-stability` | 80 | 长文本与高密度 TN 载荷下不挂死、无 broken pipe、短请求可接续。 |
| `memory-leak-soak` | 110 | 循环 create/speak/shutdown/playback/error，GC 后内存回到基线附近。 |
| `fd-thread-process-leak` | 90 | fd、线程、TN 子进程、stderr watcher、僵尸/孤儿进程清理。 |
| `stress-recovery-regression` | 60 | 已知稳定性回归防护，以及 native/runtime 失败后的恢复。 |

状态分布（设计目标）：

- `PASS`：合法路径必须完成且无意外错误。
- `EXPECTED_ERROR`：非法输入/非法状态必须报精确错误，且随后恢复请求成功。

---

## 3. 可执行契约（比“有 1000 条”更重要）

每条 JSONL 用例必须是 **runner 可精确执行的操作契约**，不能只是标签。

### 3.1 必填字段

| 字段 | 要求 |
| --- | --- |
| `id` | 全局唯一。 |
| `category` | 上表 14 类之一。 |
| `operation` | runner 必须有对应 handler；无 handler 的 operation 不得入库。 |
| `expected_status` | `PASS` 或 `EXPECTED_ERROR`。 |
| `text` | 服务载荷；长度必须匹配该类别的稳定性意图。 |
| `params` | 真实会传给 SDK 的参数；不得写 SDK 不支持却标 `PASS` 的组合。 |
| `setup` | 执行前置/循环/采样控制；runner 必须读取并执行。 |
| `assertions` | 该 operation 的硬断言；runner 必须逐条判定。 |
| `leak_checks` | 需要采样时非空；空表示本条不做泄漏判定。 |
| `metrics` | 至少记录时延、回调、资源快照字段。 |

`EXPECTED_ERROR` 额外必填：`expectedErrorName`、`expectedErrorCode`。

### 3.2 operation 保真规则

| 用例声明 | runner 必须真正做的事 |
| --- | --- |
| `loopCount=N` | 循环 N 次，不得只 speak 一次。 |
| `requestBurstSize=N` | 提交 N 个请求并等待调度结束。 |
| `preState=running/queued/...` | 先把引擎推到该状态，再执行目标动作。 |
| `runValidRequestAfterError=true` | 错误后必须再发一条合法短请求并成功。 |
| `gcAfterLoop=true` | 循环结束后强制 GC/settle，再采 after 快照。 |
| `inspectProcFd/Thread/Child=true` | 必须采样对应资源，不能只记 heap。 |
| `targetTextLength=L` | `text` 实际长度必须接近 L；禁止把长文本压成 1 字却保留该字段。 |

**禁止**：为了“跑通”而静默改写 PASS 语义（例如强制 `modelLoadOnCreate=true`、把含汉字的 `en-US` 改成 `zh-en`）。  
不支持的组合应标 `EXPECTED_ERROR`；支持的组合按真实参数执行。

### 3.3 文本载荷策略（稳定性专用）

| 层级 | 用途 | 文本要求 |
| --- | --- | --- |
| A. API / 生命周期 / 错误恢复 | 快路径、状态机、错误码 | 可用短文本；错误类按契约使用空串/超长串/非法参数。 |
| B. 流式 / 队列 / 播放 | 缓冲、突发、AudioTrack | 中等长度，足以产生多 chunk 与真实播放。 |
| C. 长文本 / TN / soak | 管道、TN 子进程、热节流、泄漏趋势 | **必须保留真实长度**（如 800–9500）；不得为加速全部改成单字。 |

说明：缩短 PASS 文本可以加快冒烟，但会削弱 C 层稳定性证据；工业级放行必须以 C 层未阉割语料为准。

---

## 4. 工业级通过门禁

以下门禁用于 Android 与 Harmony 真机。任一门禁失败，不得宣称“工业级稳定”。

### 4.1 功能稳定性

1. 全量 1000 条：`FAIL == 0`。
2. `EXPECTED_ERROR` 必须命中期望错误（允许通过 callback 或 throw），且恢复请求成功。
3. 无进程崩溃、无 ANR/卡死、无不可恢复 native abort。
4. 每条请求终态可观察：`onComplete` / 期望错误 / 明确终态断言之一成立。
5. 队列类结束后 `queue_depth == 0`；streaming 类 chunk 序号连续、无 pcm 队列死锁。

### 4.2 资源泄漏（单条 + 趋势）

**单条（有 `leak_checks` 时）**，case 结束后相对 before（强制 GC/settle 后）：

| 指标 | 建议门禁 |
| --- | --- |
| fd | 净增长 ≤ 2（抖动上限可机型标定，默认告警 >2、失败 >8） |
| thread | 净增长 ≤ 2（含 stderr watcher；失败 >8） |
| TN child process | 回到基线；不得残留业务 TN 子进程 |
| zombie / orphan TN | == 0 |
| Java heap | 净增长低于机型预算（默认失败阈值 96MB，仅作上限；soak 应用更严趋势） |
| native heap | 净增长低于机型预算（默认失败阈值 32MB） |
| RSS | 必须采样；soak/全量趋势优先于单条绝对值 |

**趋势（工业级必做）**：

1. 每 50 条采样一次 fd / thread / TN / heap / RSS。
2. 全量结束后相对全局 baseline：fd、thread、TN 净增长应为 0（允许小抖动）。
3. `memory-leak-soak` 与 `fd-thread-process-leak` 类别单独出趋势图/表；只看单条 before/after 不足。

### 4.3 长时与环境矩阵（放行建议）

1000 条顺序跑通是必要但不充分条件。工业级放行建议至少再满足：

1. 中端机连续跑完完整语料（含 C 层长文本），中途无重启进程。
2. 额外 soak：同进程重复 create/speak/shutdown ≥ 2 小时，或等价循环量。
3. 至少覆盖：音频焦点丢失 / 来电或打断、锁屏或后台、播放与纯合成各一档。
4. Android 与 Harmony 使用同一 JSONL 语义与同一门禁；平台差异只体现在采样实现。

### 4.4 性能观察（稳定性附属，不作读音验收）

记录但不以“好听/读对”判分：

- `firstPacketMs`、`synthesisMs`、`audioDurationMs`、`rtf`
- `callbackCount`、`terminalCallbackCount`、`chunkCount`

用途：发现卡死、超时、RTF 恶化、热节流导致的稳定性退化。

---

## 5. Runner 实现要求

Android（如 `AarStability1000DeviceTest`）与 Harmony（如 `DingqiaoHarmonyStabilityRunner`）必须：

1. 按 `operation` 分发到真实 handler，禁止把绝大多数 operation 塌缩成单次 `speak`。
2. 执行 `setup` / `params` 中的 loop、burst、preState、recovery、GC、资源检查。
3. 对 `assertions` 与 `leak_checks` 逐项判定并写入结果 JSONL。
4. 结果至少包含：`status`、`errors`、`before`/`after` 资源快照、关键时延与回调计数。
5. 不支持的 operation 应直接 `FAIL` 并报 `unsupported_operation`，不得记 `PASS`。

当前已知风险（文档约束，修复前不得宣称工业级）：

- 大量 operation 若未实现 handler，1000 pass 会虚高。
- 若把长文本压成单字，`longtext-tn-stability` 失去稳定性意义。
- 若 runner 静默改写 language / modelLoadOnCreate，测到的不是真实 API 契约。

---

## 6. 明确排除项

- 不含旧文本正确性类别：`zh-core`、`en-core`、`mixed-zh-en`、`tn-numeric-date-money-unit`、`frontend-rules-technical`、`polyphone-surname-proper`、`symbols-unicode-failsoft`。
- 不含发音正确性、golden 拼音/音素字段。
- 不含“读音一致性”断言；Android/Harmony 对齐仅针对 **运行稳定性门禁**，不对齐读法。

---

## 7. 维护规则

1. 改类别数量或 operation 语义时，先改本设计文档，再改生成器，再重新生成 JSONL/summary。
2. 生成器校验必须保证：总数 1000、类别计数匹配、id 唯一、无发音/golden 字段、无不可执行的重复空壳。
3. Dingqiao / androidTest assets 副本必须与 docs 语料的 **稳定性语义** 一致；允许平台路径不同，不允许把门禁或长文本意图改没。
4. 任何“为加速而缩短 C 层文本 / 跳过 loop / 跳过 leak”的改动，只能用于调试切片，不得作为放行证据。

---

## 8. 一句话验收标准

**在 Android 与 Harmony 真机上，完整执行可保真的 1000 条运行稳定性用例：零 FAIL、错误可恢复、资源可回到基线，且长文本/循环/突发类操作被真实执行——这才算工业级运行稳定；发音对不对不在本套范围内。**
