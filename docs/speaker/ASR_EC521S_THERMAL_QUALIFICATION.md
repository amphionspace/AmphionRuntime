# EC521S encoder idle gate 热测载体与短时资格检查

本载体用于先证明锁屏、物理 USB 离线条件下按 1× 真实时间处理精确 PCM 窗口，并收集独立温度证据。`PASS_PROCESSING_ONLY` 与 `PASS_SENSOR_COLLECTION_ONLY` 分别表示处理资格、采样质量通过，均不表示温度、识别精度或交付验收通过。代码落盘和静态检查不能代替统一构建、安装与真机资格检查。

实现入口：

- [独立 instrumentation](../../asr/android/samples/dingqiao-demo/src/androidTest/java/com/amphion/dingqiao/demo/EncoderIdleGateThermalInstrumentedTest.kt)：`EncoderIdleGateThermalInstrumentedTest#pacedPrivatePcmQualification`。
- [有界前台服务](../../asr/android/samples/dingqiao-demo/src/main/java/com/amphion/dingqiao/demo/ThermalQualificationService.kt)：仅维持实际处理生命周期和 PARTIAL_WAKE_LOCK；不改频率、affinity、cpuset 或白名单。服务标签本身不证明厂商休眠策略已豁免。
- [独立设备采样器](../../asr/tools/device/collect_encoder_idle_thermal.sh)：设备端 `sh` 脚本；仅写本轮输出与协作取消标记，不启动应用，不改变设备设置。

## 参数与输出

默认测试套件没有 `thermalPcmPath` 时跳过此类。指定单个类/方法运行，避免夹带其他设备测试。

| instrumentation 参数 | 默认值 / 要求 |
| --- | --- |
| `thermalPcmPath` | 必填；canonical path 必须位于目标应用私有 `filesDir` 内。16 kHz、单声道、PCM16 little-endian；不读取客户原文或生成音频副本。 |
| `thermalStartSample` | 0；从指定样本开始，按帧流式读取。 |
| `thermalSampleCount` | 必填；精确窗口，不循环、不补零、不截短。20 秒为 320000；120 秒为 1920000；3600 秒为 57600000。 |
| `thermalBackend` | `sdk`；可选 `dingqiao`，使用公共 `createEngine/startListening/writeAudio/finish/cancel/shutdown` 录音链路。每轮一个 session，不轮换。 |
| `thermalMode` | `qualification`，最多 300 秒；显式 `measurement` 才允许最多 3600 秒。 |
| `thermalGate` / `thermalThreads` | `on` 或 `off`，默认 on；SDK 线程数 1 或 2，默认 2。鼎桥仅接受 2，拒绝其他线程数，不反射改线程。gate off 仅在测试内通过反射关闭，未增加 SDK 开关。 |
| `thermalExpectedUsb` | 0；物理 `/sys/class/power_supply/usb/online` 必须可读且匹配。1 仅用于插线冒烟，不是拔线证据。 |
| `thermalRequireLocked` | true；实际检查屏幕 `isInteractive=false`，单独记录 `isKeyguardLocked`，不声称验证了安全锁屏。 |
| `thermalRequireSpeech` | true；正常完成还要求非空最终文本；纯静音控制须明确 false，不能据此证明语音识别有效。 |
| `thermalReadyDelaySeconds` | 30；范围 0–120。延迟后最多再等 120 秒，连续 3 次状态符合才开始。 |
| `thermalMaxLagMs` / `thermalMaxFeedLagMs` | 10000 / 1000；分别约束处理/监测间隔和逐帧绝对节拍，避免解冻后突发追赶掩盖卡顿。 |
| `thermalExpectedPcmSha256` | 可选；精确输入窗口的原始字节 SHA-256，非整个文件哈希。 |
| `thermalRunId` | 可选，默认时间戳加 UUID；显式值为 1–96 个字母数字、点、下划线、短横线，首位必须字母或数字。每次全新。 |

`sdk` 保留原基线：关闭角色分离、目标声纹、标点与 ITN，不加热词；启用 VAD 和 endpoint，VAD endpoint 800 ms，RULE3 关闭。`dingqiao` 显式 long、vadEnd 800，无角色分离、声纹校验或 Speaker VAD；使用每轮新的私有 workPath，核验实际引擎没有目标声纹配置。它保留公共默认完整预置热词、beam、标点、ITN、disablePrepack 与 2 线程，不替换或裁剪默认热词。每条报告包含 backend，另记录实际配置、热词数量/哈希、decodingMethod 和 maxActivePaths；不同后端结果不能混成同配置 A/B。

鼎桥公共 `writeAudio` 仅接受 640 字节，因此 `dingqiao` 要求 `thermalSampleCount` 是 320 的整数倍；否则运行前拒绝，不补静音、不截短。SDK 后端仍支持末尾不足一帧。两者均只读取所指定精确窗口一次，不复用旧长测类的循环、分段轮换、补静音或原文报告。

应用输出目录为 `/sdcard/Android/data/com.amphion.dingqiao.demo/files/thermal_qualification/<runId>/`：`report.jsonl`、`READY`、`STARTED`（elapsedRealtime 毫秒）、`DONE`。`ABORT` 存在时协作取消。目录已存在则拒绝覆盖。SDK 正常停止使用 `stop()`，检查唯一 last 后唯一 stopped；鼎桥使用公共 `finish()`，检查同一 session 的唯一 last 后唯一 `onComplete`，共用报告中的 `stops` 计数，且 finish 前不得已有终态。异常使用 SDK `close()` 或鼎桥公共 `cancel()/shutdown()`；鼎桥 `writeAudio` 若正在持锁等待 PCM 背压，测试先关闭所保留的底层 session 解除等待，再调用公共 cancel。仅中断线程不能唤醒 SDK 的 uninterruptible PCM 等待；释放仍遵循公共 shutdown 的 native 工作等待契约。

collector 的第一个参数是相同 runId。环境变量为 `INTERVAL_SECONDS=10`、`WAIT_START_SECONDS=300`、`MAX_RUN_SECONDS=420`、`EXPECTED_USB=0`、`SHELL_GUARD_M=50000`。默认输出为 `/data/local/tmp/amphion-thermal-qualification/<runId>/`，旧目录保留，不删除、不覆盖。将每轮 app 与 collector 目录、构建哈希/设备信息一起归档。公共 helper 的既有 runtime 准备阶段记录可能另写 `dq_corner/report.jsonl`，它不作为本轮热测权威报告。

## 最小执行顺序

1. 主代理冻结最终统一构建的主 APK、测试 APK、源码身份和私有 PCM 窗口。先核验安装身份与可用授权；禁止检查或输出实际 key/license 内容。
2. 20 秒插线冒烟：`thermalSampleCount=320000`、gate on、threads 2、expected USB 1、require locked false、ready delay 2；collector 使用 `EXPECTED_USB=1 MAX_RUN_SECONDS=90`。选含真实语音的窗，或仅为载体连通性显式关闭 require speech。先确认反射字段、应用读取 USB sysfs 的权限、通知/服务启动及资源释放。
3. 120 秒拔线锁屏资格：同一真实语音/静音混合窗，count 1920000、expected USB 0、require locked true、ready delay 30；collector `MAX_RUN_SECONDS=180`。每次显式记录 backend；由主代理决定 gate on/off 的必要比较，线程 2/1 比较仅适用于 SDK，鼎桥固定 2，每次新 runId。
4. collector 先启动等待 STARTED，随后启动独立 instrumentation。使用已经验证能脱离 USB/ADB 继续运行的驻设备启动方式；标准输入、标准输出与控制进程生命周期不能依赖宿主连接。两端结果、采样时间覆盖和处理进度全部回收后再判定。
5. 仅在资格通过、有效测温路径明确之后设计/启动一小时比较。未经许可不得自行启动长测。

逐帧用 `elapsedRealtimeNanos` 的绝对 deadline，SDK 最后不足一帧也保留精确输入时长。提交返回、SDK 已接受、decoder 已处理分别记录；处理计数包含门控跳过的源样本。每秒检查进度，每 10 秒输出 CPU/墙钟、计数、快照年龄、进度/队列积压上界、barrier 等待、最长 accept 调用、尾部积压、回调和文本哈希。每次只有一个未完成周期探针，另可有一个显式首尾 barrier。鼎桥在公共 last/complete 前会关闭底层 session，因此测试在 finish 前暂停周期探针，继续运行设备/期限监测；收到 complete 后有界 join decoder 线程，确认退出后才读取最终计数（包含 AGC stop flush），避免向已关闭队列发 barrier。`processedSnapshotSource` 区分队列 barrier 与线程 join，`decoderJoinMs` 单独报告。未暴露 native 单次 decode 最大时长；barrier、join 延迟和尾部积压不能改名为 native decode 时长。

`idleSamplesGross` 包含随后回放的 pre-roll，不能直接计算净 encoder 节省。`gateTransitionsCovered` 为 false 时只证明处理行为，不能声称覆盖门控进入/恢复。非空最终文本与相同哈希均不等于识别精度验收；已知严格文本回归仍是独立阻断项。

## 温度数据与失效判据

collector 每轮采样原始 thermal zones、battery dumpsys、USB、原始电池电流/电压/电量、各 CPU policy 频率、应用各线程 CPU ticks/cpuset/允许 CPU 列表。原始 thermalservice 每 60 秒保留一次；dumpsys 有 3 秒等待上限。应用 CPU 百分比以 100% 为一个核心，外部采样器的整机发热不包含在 app CPU 中；A/B 必须保持相同观测设置。

必须读到 `shell_front`、`shell_back`、`shell_frame` 和 battery zone。0、-127000、非数字、缺失或超范围温度使温度采样无效，不能把无效值当低温。USB 不符/不可读、Battery updates stopped、外部供电与要求不符、表面温度保护触发会写 ABORT。50℃仅为停止保护值，**不是客户验收阈值**。

首次/末次采样距边界不得超过 interval+2 秒，中间间隔不得超过 2×interval+2 秒，单次采样不得超出 interval；至少两点。温度或诊断失效保持原始现场，不把 FAIL/INVALID/INCOMPLETE 改写为 PASS。进度 lag、馈入迟到、监测卡顿、SDK 错误、样本数或回调契约不符、超时及资源释放失败均判处理失败。

历史 EC521S 锁屏曾出现全部 shell_* 为 0，当前实现会如实判温度无效。若复现，必须验证独立接触式/红外测温或新鲜 HAL 读数与原测点的对应关系，不能把缓存 SKIN_T 或电池温度无说明地替换为后壳温度。

## 长测设计边界

后续同构建、同后端、同一精确 3600 秒输入以 1× 比较 gate on/off；SDK 可比较 threads 1/2，鼎桥固定 2。须匹配环境、初始表面/电池温度、SOC 与摆放；报告峰值、T60、ΔT、相对环境温差及末 20 分钟斜率。仍持续升温不能称为达到稳定温度。目前没有客户认可的绝对温度/温升阈值，不能仅凭曲线较低签收。

当前 `thermalRequireLocked=true` 要求输入全程屏幕关闭；若目标协议需要“前 10 分钟亮屏、后 50 分钟锁屏”，还需要明确的阶段切换与核验，不能将该参数改 false 就声称完成了锁屏阶段。此文档不授权自动发起一小时测试，也不解决现存识别文本差异或热词 native 崩溃阻断。
