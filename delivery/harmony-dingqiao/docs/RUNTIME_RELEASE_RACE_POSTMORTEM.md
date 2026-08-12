# Harmony Runtime 释放竞态复盘

## 结论

客户反馈的“长录音单句过长会丢字”包含两个不同现象：

1. 同一 session 连续识别超过一小时没有观察到状态、RSS、线程或 callback 契约的累积漂移；
2. 客户故障现场真正可稳定复现的是 `finish -> shutdown -> setLicense`：音频越长，finish 时待排空的
   native async decode 越多，越容易撞上 Runtime 提前释放，而不是“一小时阈值”本身导致累积。

旧实现会在 native decode worker 的成功回调返回前释放共享 recognizer。迟到回调随后进入
`getResult`，可能造成尾部结果缺失，也可能直接 native 崩溃。

## 可失败断言

复现必须重放完整宿主时序，不能只检查长音频文本或进程是否存活：

```text
start -> burst write complete PCM -> finish -> shutdown
      -> setLicense(valid) -> prepareRuntime
```

每个 session 必须满足：

- `finish` 前 `isLast=0`；
- 结束后恰好一次 `isLast=true`，随后恰好一次 `onComplete`；
- `error=0`、unexpected callback 为 0、native stream 归零；
- Runtime 重建后的下一 session 可以正常开始和结束。

修复前，3 秒客户音频前缀即可稳定复现与现场相同的 native 栈；因此问题不是音频必须超过一小时。

## 根因时序

```text
session.stopAsync
  native decodeAsync -----------------------------------+
                                                        |
engine.shutdown                                         |
  session.close                                         |
setLicense                                              |
  Runtime.release                                       |
    recognizer.close  // 旧实现过早                     |
                                                        |
  decode worker callback -------------------------------+
    getResult(closed recognizer) -> crash / missing tail
```

`engine.shutdown()` 只关闭公开 engine，不等价于 native async callback 已全部返回。旧 Runtime 只有
模型池所有权，没有记录仍在使用这些 native 对象的 session，因此无法判断安全释放点。

## 修复边界

Harmony core 增加 Runtime release gate：

- session 创建时取得 lease；
- 只有公开 callback gate 已关闭、最后一个 in-flight native 调用返回且 stream 已关闭，才释放 lease；
- `unloadModel` / Runtime release 在 lease 清零前延后执行，并在等待期间拒绝新 session；
- 有效 `setLicense` 等待旧 Runtime 完成安全释放，再发布新授权成功回调。

保持不变：识别模型、VAD、endpoint、音频 FIFO、`isFinal/isLast` 语义、cancel 契约和 Android 实现。
Android 的 decoder 由专用线程串行执行，engine close 会等待 decoder 退出后再释放 recognizer，不存在
本次 Harmony native async callback 的同构释放路径。

## 为什么会漏掉

- 既有长稳压覆盖持续识别和资源变化，但没有组合会话结束、引擎释放和重新授权。
- 既有 `finish-shutdown` 只证明 engine shutdown 不吞 terminal callback，没有触发进程级 Runtime 释放。
- “音频越长越容易出现”被误当作时间累积，实际只是扩大了 pending decode 窗口。
- Runtime/Model 的全局所有权与 session 的 native 使用期没有形成显式状态机。

## 永久门禁

- 主机状态机：`test_harmony_runtime_release_gate.py` 锁定多 session 等待、重复 release 合并、Runtime
  release 覆盖 model unload、无 active session 时立即卸载，以及实际源码接线位置。
- Mate 80：`finish-shutdown-relicense` 使用短前缀做最小竞态回归，使用完整客户 WAV 做 backlog
  回归，并至少连续两轮验证 Runtime 重建恢复。
- 发布相邻门禁：保留 `finish-shutdown`、实时 `paced`、回调重入、cancel、start-write/reload 和
  既有生命周期矩阵；精度评测与生命周期判定继续分开。
- 报告必须保留 `report.json`、逐轮 callback trace、hilog、内存采样与输入映射，不提交客户 PCM。

停止条件是同一 commit、同一 ZH_EN HAP、同一 Mate 80 上：最小复现转绿、完整客户音频转绿、
Runtime 重建恢复通过，并且相邻状态机、SDK 单测和 Harmony 构建均通过。达到这些条件后不重复运行
无关长时模式。
