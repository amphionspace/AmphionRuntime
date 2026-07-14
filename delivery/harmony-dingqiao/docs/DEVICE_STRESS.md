# Harmony ASR 真机压力测试

`delivery/run_device_stress.py` 将 PCM WAV 转为 16 kHz/mono/s16，推送到已连接的 Harmony
设备，并以无 UI 模式驱动鼎桥 demo。每次运行会采集应用的 RSS、VmData、VmSwap、线程数、
回调契约和 native online-stream 存活数。

## 运行

从仓库根目录执行：

```bash
python3 delivery/harmony-dingqiao/delivery/run_device_stress.py \
  --data-dir ~/Downloads/testdata \
  --mode burst \
  --cycles 200 \
  --files 48
```

默认会先构建、签名、安装并执行 UI smoke。确认设备已安装当前 HAP 时可加
`--skip-build-install`。结果写入
`delivery/harmony-dingqiao/build/device-stress/<run-id>/`：

- `report.json`：总体结论、回调计数、空结果率、native 流和内存判定。
- `memory.csv`：按时间采集的 `/proc/<pid>/status`。
- `result.txt`：设备端逐轮契约结果。
- `hilog.txt`：本轮系统和应用日志。
- `payload/corpus.json`：源 WAV 到设备 PCM 的映射。

设备写出结果后会删除本轮 PCM、manifest 和 corpus 映射，避免重复压测持续占用应用存储；
主机侧 artifact 保留完整输入映射用于复核。

## 模式

| 模式 | 覆盖边界 |
| --- | --- |
| `burst` | 快于实时喂入、尾部 flush、长音频、连续会话 |
| `paced` | 20 ms 实时喂入，对照 burst 是否丢 backlog |
| `vad-begin` | 真实语音启用 10 秒 `vadBegin`，验证真实起音事件优先于首段静音超时 |
| `cancel` | 500 ms 后取消，验证无 final/complete 和短会话泄漏 |
| `cancel-full` | 完整音频解码后取消，隔离正常 finish 路径 |
| `max-duration` | 20 秒自动结束、80 个迟到帧、单次 complete、下一轮重启 |
| `reconfigure` | 轮换 VAD 参数，覆盖引擎替换和旧引擎释放 |
| `recreate` | 每轮创建引擎并连续 shutdown 两次 |
| `edge` | 空闲调用、非法 session/帧、串 session、busy、重复 finish |
| `reentrant` | `onComplete` 回调内立即再次 `startListening`，验证完成态可重入 |
| `start-cancel` | `onStart` 回调内立即 `cancel`，验证取消后不再透出 start 后续事件 |
| `numeric-edge` | `maxAudioDuration=NaN` 等非有限数输入，验证不会绕过 20 秒兜底上限 |

默认门槛为 RSS 增长不超过 64 MiB、线程增长不超过 2、正常结束模式空 final
不超过 5%。少于 15 秒的采样只报告 `INCONCLUSIVE`，避免把模型冷启动误判为泄漏。
`rss_slope_mb_per_minute` 和三段 RSS 中位数用于识别缓慢线性增长；斜率至少需要 60 秒观测，
且当前不单独作为硬门槛。

## 2026-07-10 基线

语料盘点：1894 条有效 WAV，约 3.09 小时；其中 1394 条 24 kHz、500 条 44.1 kHz，
时长约 1.10 到 48.88 秒。SDK 输入是 PCM，因此 MP3 不直接进入本工具。

| 用例 | 结果 | RSS 变化 | 线程变化 |
| --- | --- | ---: | ---: |
| 200 轮、48 条分位语料 burst | 200/200 PASS，空 final 2%，流存活 0 | +11.09 MiB | 0 |
| 100 轮、500 ms cancel | 100/100 PASS，流存活 0 | -0.90 MiB | -1.5 |
| 10 轮、完整 20 秒后 cancel | 10/10 PASS，流存活 0 | +8.41 MiB | -2 |
| 15 轮 VAD reconfigure | 15/15 PASS，流存活 0 | +8.02 MiB | -2 |
| 10 轮 engine recreate + 双 shutdown | 10/10 PASS，流存活 0 | +4.42 MiB | -2 |
| 3 轮 max-duration + 迟到帧 | 3/3 PASS，流存活 0 | +4.32 MiB | 0 |
| 扩展 edge 契约 | 8 个预期错误精确匹配，重复 finish 无额外错误 | 采样不足 | 采样不足 |
| 解码中强制停止进程后冷启动 | 中断被检测并保留日志；重启 edge PASS | 不适用 | 不适用 |

主稳压 artifact：
`delivery/harmony-dingqiao/build/device-stress/20260710-231528-burst-18e50bec`。
该轮 RSS 三段中位数为 694.57/682.59/694.20 MiB，未呈线性增长。

## 2026-07-11 adversarial 发现

新增三条红灯契约，用于固定当前 Harmony SDK 的高风险边界：

| 用例 | 结果 | 主要症状 | Artifact |
| --- | --- | --- | --- |
| `reentrant` 3 轮 | 3/3 FAIL | `onComplete` 回调内 `isBusy()==true`，立即 `startListening` 触发 `ENGINE_BUSY` | `20260711-112219-reentrant-4ff47443` |
| `numeric-edge` 3 轮 | 3/3 FAIL | `maxAudioDuration=Number.NaN` 后喂入 1168 帧仍无 `onComplete`，会话上限被绕过 | `20260711-112231-numeric-edge-f5bf6f84` |
| `start-cancel` 3 轮 | 3/3 FAIL | `onStart` 内立即 `cancel` 后，每轮仍有 1 个 native stream 存活 | `20260711-112628-start-cancel-dfa83bdb` |

对照结果：单独重跑 `edge` 通过（`20260711-112205-edge-71f55e92`），标准
`max-duration` 通过（`20260711-111857-max-duration-457e0da3`）。因此新增失败集中在
回调重入、取消时序和非有限数参数处理，不是旧 edge/max-duration 路径回归。`start-cancel` 的根因指向
`startListening` 中 `this.session = this.asrEngine.newSession(callback)` 的赋值时序：如果
`newSession` 同步触发 `onSessionStarted`，客户在 `onStart` 中取消时 `tearDownSession()` 还看不到
新 session，无法关闭刚创建的 native stream。

## 2026-07-12 模型加载回归

加载优化后的 `zhen` 配置使用 4 个 ORT worker，不执行 eager silence warmup。独立进程
`createEngineAsync` 10 次结果为 p50 774.5 ms、p95 810.25 ms，pool hit 为 0–1 ms。

同一台设备随后使用 500 条 44.1 kHz 语料中的 24 条分位样本执行 48 轮 burst：

| 结果 | 首轮 | 总耗时 | 空 final | 峰值 RSS |
| --- | ---: | ---: | ---: | ---: |
| 48/48 PASS | 120 ms | 21858 ms | 4.1667% | 571.863 MiB |

artifact：`delivery/harmony-dingqiao/build/device-stress/20260712-101550-burst-edaea120`。
该结果用于防止去掉 eager warmup 后把全部成本转移到第一条真实音频；完整加载身份、历史对照
和复现命令见 [`MODEL_LOAD_PERFORMANCE.md`](./MODEL_LOAD_PERFORMANCE.md)。

## 已修复问题

1. online stream 原先只依赖 N-API finalizer，ArkTS 引用释放后 native 对象要等 GC，短会话呈现
   每轮约 4.6 MiB 的线性增长。现在 stream 具有显式幂等 `close()`，会话、硬重启、预热和
   speaker 临时流均在确定的所有权边界释放；finalizer 仅作兜底。
2. 长 WAV 快灌会连续占用 UIAbility event runner，触发 Harmony 6 秒前台阻塞 watchdog。
   burst 每 50 帧让出 1 ms，仍远快于实时但不再饿死事件循环。
3. Harmony 的 `stop()` 可同步回调，导致连续两次 `finish()` 的第二次被误报
   `FINISH_FAILED`。适配层保留最近正常结束的 session，直到下一次成功 start，使其与 Android
   的异步完成窗口一致。
4. 达到 max duration 后，同 session 的迟到采集帧会被安静丢弃；任意真正的空闲写入仍返回
   `NOT_LISTENING`。

## 剩余边界

- 主稳压采用按采样率和时长分位抽取的 48 条 WAV，不等同于 1894 条逐文件准确率评测。
- 本工具覆盖 ASR 会话和引擎生命周期，不覆盖声纹注册/删除压力；声纹需单独准备 3-8 秒样本
  和预期身份关系。
- 物理 USB 断连、系统主动低内存回收和设备重启需要人工控制，不能由本脚本安全自动触发。
