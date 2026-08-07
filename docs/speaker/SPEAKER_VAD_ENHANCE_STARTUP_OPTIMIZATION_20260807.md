# 【真机优化】Speaker VAD Enhance 启动延迟（2026-08-07）

## 结论

Mate 80 上已经确认并修复增强 session 启动变慢的问题。修复前，即使 Conv-TasNet 已经加载，
每次 `startListening()` 仍会同步创建两个 ERes2Net 提取器，热启动需要 682～749 ms；普通 ASR
只有 1～19 ms。

修复包含两层：

- 完成的增强 session 把两个 ERes2Net 提取器归还到模型池，下一个 session 直接复用；池最多保留
  一对，避免 cancel 重叠时无限累积。
- 新增异步 `preloadTargetSpeakerEnhancementModel(voiceprintIds)`，在 `startListening()` 之前准备
  Conv-TasNet、增强选流 ERes2Net 和 Speaker VAD ERes2Net。Demo 在用户开启增强开关时以及上一轮
  正常结束卸载模型后自动后台预热。
- 后台预热不占用 Demo 的全局加载锁。用户在预热完成前点击“开始识别”时会立即开麦并缓存 PCM，
  等增强模型就绪后自动建立 session、按序回灌缓存，点击不会被忽略，也不会丢失首段语音。

真机结果：

| 场景 | 修复前 | 修复后 |
|---|---:|---:|
| 增强模型已热，创建下一 session | 682～749 ms | 2 ms |
| `unloadModel` 后先后台预加载，再创建 session | 无 | 19 ms |
| 不预加载的首次增强 session | 970～1085 ms | 1088 ms |
| `unloadModel` 后直接按需重载 | 1209～1301 ms | 1307 ms |
| `unloadRuntime` 后直接按需重载 | 1213～1296 ms | 1300 ms |

这说明优化没有伪造 `onStart` 或取消真实卸载：未预加载的冷路径仍然真实付出加载成本；只有已经
预热或同一模型生命周期内的启动变快。

## 生命周期与内容保护

- 预加载后的 session：一次 start、一次 last、一次 complete、0 error，`onStart` 内同步写入通过。
- `unloadModel` 和 `unloadRuntime` 后能够重新冷加载，四阶段 reload 模式全部通过。
- 推理中 cancel 后立即恢复 3/3 通过，没有迟到回调或跨 session 污染。
- C1/C2/C3 最终文本仍逐例满足“包含上海、不包含你好”，回调契约全部通过。
- 普通 ASR 不会因为 HAR 内置或新增预加载接口而自动加载 Conv-TasNet；只有显式调用预加载或启用
  `enableTargetSpeakerEnhancement` 才进入该路径。

## 资源代价

为了让下一次点击快速启动，预加载完成后会保留 Conv-TasNet 和增强使用的一对 ERes2Net。调用
`unloadModel()` / `unloadRuntime()` 仍会释放它们。Demo 在增强开关保持开启时会在上一轮卸载后主动
重新预热，因此空闲期会保留增强模型内存，这是用内存换点击延迟的明确取舍。

cancel 后立即恢复的三轮测试峰值约 995 MiB，结束后回落到约 825 MiB；没有持续增长，但比此前
约 933 MiB 的峰值高，仍需保留为中低端设备支持范围的风险。

## 证据

- 修复前红灯：
  [`pre-fix`](../../delivery/harmony-dingqiao/evidence/target-speaker-enhancement/20260807-startup-optimization/pre-fix/report.json)
- 最终签名 HAP（SHA-256 `7b4aa60a5f4512a42027befea6b436674e913445e9fe1ba087f96f4c2be4b1d6`）
  预加载后 19 ms：
  [`preload`](../../delivery/harmony-dingqiao/evidence/target-speaker-enhancement/20260807-startup-optimization/preload/report.json)
- 热复用 2 ms、真实卸载重载：
  [`reload`](../../delivery/harmony-dingqiao/evidence/target-speaker-enhancement/20260807-startup-optimization/reload/report.json)
- cancel 恢复：
  [`cancel`](../../delivery/harmony-dingqiao/evidence/target-speaker-enhancement/20260807-startup-optimization/cancel/report.json)
- C1/C2/C3 内容回归：
  [`content`](../../delivery/harmony-dingqiao/evidence/target-speaker-enhancement/20260807-startup-optimization/content/report.json)
