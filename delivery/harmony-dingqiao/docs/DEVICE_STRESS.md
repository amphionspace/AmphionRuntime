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
| `cancel` | 500 ms 后取消，验证无 final/complete 和短会话泄漏 |
| `cancel-full` | 完整音频解码后取消，隔离正常 finish 路径 |
| `max-duration` | 20 秒自动结束、80 个迟到帧、单次 complete、下一轮重启 |
| `reconfigure` | 轮换 VAD 参数，覆盖引擎替换和旧引擎释放 |
| `recreate` | 每轮创建引擎并连续 shutdown 两次 |
| `edge` | 空闲调用、非法 session/帧、串 session、busy、重复 finish |

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
