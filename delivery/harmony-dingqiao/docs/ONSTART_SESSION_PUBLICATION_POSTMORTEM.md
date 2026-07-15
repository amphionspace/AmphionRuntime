# `onStart` 会话发布竞态复盘

## 结论

这次客户首次使用 ASR 收到 `1002200010 startListening not succeeded`，不是模型冷加载失败，
也不是调用方误用。SDK 在 session 尚不可用时就发送了成功回调，违反了 `onStart` 的公共契约。

我们不仅需要修正赋值顺序，还需要修正验收方法：成功回调必须按“回调内可立即调用哪些 API”
定义并测试，不能只检查回调是否出现、进程是否存活或回调返回后能否继续工作。

## 故障时间线

旧实现的同步调用链如下：

```text
startListening
  busy = true
  asrEngine.newSession(...)
    AsrSession constructor
      onSessionStarted()
        listener.onStart()
          customer flushes buffered PCM
            writeAudio() sees session === undefined
            -> 1002200010 NOT_LISTENING
  session = createdSession  // 已经太晚
```

首次冷加载期间，宿主会继续采集麦克风并缓存 PCM。加载越久，收到 `onStart` 时待冲刷的帧越多，
所以问题更容易在第一次使用时暴露。冷加载扩大了竞态的可见度，但没有造成竞态。

## 为什么会漏过

### 1. 把成功回调当成“通知”，没有写成状态后置条件

旧测试只断言出现一次 `onStart`，没有断言回调进入时 session 已经发布、会话级配置已经完成。
因此测试可以通过，调用方却仍无法使用 SDK。

### 2. 测试载体的喂入时序比真实宿主更宽松

普通 `burst` / `paced` 模式先等待 `onStart` 返回，再开始 `writeAudio`。真实宿主在模型加载期间
已经缓存音频，会在 `onStart` 调用栈内立即冲刷。测试没有进入客户实际命中的窄窗口。

### 3. 用 `start-cancel` 代表了整个回调重入能力

`cancel()` 已有 `startingSession && session === undefined` 的特殊补偿，所以 `start-cancel` 能通过；
`writeAudio()` 和 `finish()` 没有该分支。一个 API 的特殊兼容掩盖了 session 尚未发布这一根因，
不能据此推断其他 API 在 `onStart` 内也可用。

### 4. 首次使用测试关注了耗时，没有组合缓存回放

冷启动门禁记录了 createEngine/model-ready 耗时，但没有同时模拟“加载期间持续采集、成功回调内回放”。
性能测试和生命周期测试被拆开后，缺少了两者交叉产生的真实用户时序。

### 5. 验收结论依赖汇总指标，缺少回调入口处断言

进程未崩溃、最终出现 complete、聚合错误率正常，都不能证明 `onStart` 当下可用。该缺陷必须用
按 sessionId 排序的轨迹和回调内同步调用捕获。

## 根因修复

Harmony core 的同步 started 信号在 `newSession()` 返回前只被暂存。鼎桥适配层完成以下步骤后，
才向宿主发送一次 `onStart`：

1. 保存 created session；
2. 完成目标说话人和 Speaker VAD 的会话级配置；
3. 确认 session 没有在启动过程中被取消或销毁。

没有采用吞掉 `NOT_LISTENING`、调用方延时、补写静音或单独给 `writeAudio` 增加特殊分支。这些做法
只能隐藏症状，仍会让 `finish`、后续新 API 或配置回调遇到同一半初始化状态。

## 永久门禁

| 门禁 | 必须证明的契约 |
| --- | --- |
| `start-write` | 在 `onStart` 调用栈内写入 32/88 个真实 PCM 帧，不得出现 `NOT_LISTENING` |
| `start-write` + continue | 冲刷缓存后继续写入并正常结束，恰好一次 last 和 complete |
| `start-write` + finish | 冲刷缓存后在回调内立即 `finish`，不得出现 `FINISH_FAILED` |
| `start-write-reload` | 每轮卸载模型并重新 createEngine，重新冷加载后的 `onStart` 仍满足同一可用性契约 |
| `start-cancel` | 回调内立即取消，不得遗留 final、complete 或 native stream |
| cold start | 隔离构建和重新安装后首轮执行上述门禁，不能只测 warm session |
| cross-platform | 同时核对 Android/Harmony 的成功回调发布顺序和公共语义 |

以后新增成功回调或 session 公共方法时，要建立“回调 x 可重入 API”矩阵。某个 API 的通过不能代替
其他 API；具有特殊兼容分支的 API 尤其不能作为 session ready 的证明。

## 验证记录

- 修复前最小复现：5/5 FAIL，每轮均出现 `start > error-1002200010`；
- 最终 0.2.4 HAP：隔离构建、签名、安装通过；
- USB `start-write`：100/100 PASS，32/88 帧 x continue/finish 四种组合各 25 轮；
- USB `start-write-reload`：20/20 PASS；每轮显式卸载模型并重新 createEngine，20 次冷加载
  `engineReadyMs=681..828`，错误 0，native stream 0；
- 首轮冷加载 `engineReadyMs=804`，错误 0，native stream 0；
- `start-cancel`、`reentrant`、`edge`、`user-sequence` 相邻门禁全部通过；
- Android 已在发布 session 状态后异步发送 `onStart`，单测通过，无需修改。

详细 artifact 和资源数据见 [`DEVICE_STRESS.md`](./DEVICE_STRESS.md) 的
“2026-07-15 `onStart` 同步写入竞态”章节。

## 发布检查

发布负责人不能只验证 Demo 操作或识别文本。必须确认：

1. 当前 PR HEAD 的构建和单测通过；
2. 当前 USB 设备使用本次构建的 HAP/HAR，而不是旧安装包；
3. 首轮冷启动和后续 warm session 都执行回调内缓存冲刷；
4. 按 sessionId 保存 callback trace、错误码、native stream 和内存 artifact；
5. HDC 掉线等基础设施失败标为 `INCONCLUSIVE`，恢复后原参数完整重跑，不得记作 PASS。
