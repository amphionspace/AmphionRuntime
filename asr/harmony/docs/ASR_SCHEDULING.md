# 鸿蒙 ASR 可选调度配置

这些调度选项用于比较息屏前后的 ASR 性能，默认保留原有 QoS、affinity 和忙等策略。设置请求不保证系统提供更多 CPU 资源，也不授予后台运行或录音权限。绑核属于实验能力，必须针对客户机型验证。

## 鼎桥 SDK

```typescript
import { AsrSchedulingConfig, CreateEngineParams, SpeechRecognizeSdk } from 'amphion_dingqiao';

const params = new CreateEngineParams();
params.language = 'zh-CN';
params.online = 1;
const scheduling = new AsrSchedulingConfig();
scheduling.qos = 'user-initiated';
// 仅在确认客户设备允许使用的 CPU 编号后填写；空数组不绑核。
scheduling.cpuIds = [];
// 显式提供 scheduling 即接管全部字段，不再套用下表的 mode 缺省。
scheduling.allowSpinning = true;
params.scheduling = scheduling;
params.numThreads = 4;
// 可选引擎级覆盖：true 跳过 prepack，false 启用；省略时由 short/long 模式选择。
// params.extraParams['disablePrepack'] = true;
const engine = SpeechRecognizeSdk.createEngine(params);
```

基础 SDK 使用 `AsrConfig.scheduling` 和已有的 `AsrConfig.numThreads`、`disablePrepack`。`AsrConfig.builder().scheduling(...)` 同样可用；`AsrSchedulingConfig` 从两个 SDK 的入口导出。

| 配置 | 默认值 | 含义 |
|---|---|---|
| `scheduling.qos` | `default` | 保持系统策略；可选 `user-initiated`、`user-interactive` |
| `scheduling.cpuIds` | `[]` | 不修改 affinity；非空为允许执行的零起始 CPU 编号集合，不自动推断大核 |
| `scheduling.allowSpinning` | 省略 `scheduling` 时按 mode：`short：true；long：false`；显式 `scheduling` 原样采用 | 保留或让出 ORT 的忙等；设为 false 减少空转，可能增加唤醒延迟 |
| 鼎桥 `numThreads` | `4` | ASR 推理线程数，含调用线程，整数 1–8；基础 SDK 原默认 2 不变 |
| 鼎桥 `disablePrepack` | `short：true；long：false` | 按最终解析的 mode 选择；short 跳过 prepack，long 启用；显式引擎级 `true`/`false` 优先 |
| Core `AsrConfig.disablePrepack` | `true` | Core 默认保持跳过 prepack；可显式设为 `false` |

引擎参数在创建时复制，CPU 数组也会复制。修改原对象不影响正在加载或运行的引擎。切换显式引擎策略需创建新引擎；这些引擎参数不通过 `StartParams` 修改。调度参数参与模型复用判定，防止复用具有另一套策略的模型。

未设置引擎级 `disablePrepack` 时，鼎桥 SDK 根据最终解析的 `recognizerMode` 选择缺省值，包括会话级 mode 覆盖和未显式指定 mode 时的 continuous→long 规则；角色分离开关不参与选择。`prepareRuntime()` 仍预加载 `short`、`disablePrepack=true` 的默认模型，Core 默认值也仍为 `true`。short→long 使用既有模式重建路径；`StartParams.extraParams['disablePrepack']` 不覆盖显式引擎参数，也不覆盖上述缺省选择。

默认 `true` 预热池与 `false` 长模式专用 recognizer 仍可能并存；自定义线程、调度和端点配置也会影响模型复用。显式 `true` 保留跳过 prepack 的策略，不保证整个进程的初始化时延或内存完全恢复旧模式；须对对应配置分别测量，不能仅凭启用 prepack 的既有结果推断缺省路径成本。

## 作用范围和限制

- HarmonyOS API 12 起的 QoS 接口，与工程原有最低版本一致。仅修改鸿蒙 ASR；Android 不使用这些策略。
- ASR 模型内部 ORT 工作线程使用所属 recognizer 的固定策略，线程随模型销毁被等待并回收。没有新增进程级线程池。
- 角色（Community）分离的 segmentation 与 encoder session 在请求非空时也通过 ORT 的自定义线程工厂创建 intra-op worker，由 worker 自身设置 QoS：`pthread_create` 不继承 QoS，只设置驱动线程无法覆盖真正执行 encoder 的线程。mask 仍由创建线程继承，worker 不另发 affinity 请求，已存在的 worker 也不被后续作用域重绑。正因为 XNNPACK 的 pthreadpool 在 EP 内部创建、既不经过该工厂也不受 `allow_spinning` 控制，鸿蒙的 encoder 不注册 XNNPACK：锁定的 signed per-channel INT8 图会被 ORT 1.16.3 的 XNNPACK 全部认领，一旦认领，真正执行卷积的线程就不在任何调度请求的覆盖范围内。该图在 CPU EP 上与此前 U8/S8 图逐位相同、且对线程数逐位不变，因此这一选择不改变输出。Android 仍使用 FP32 encoder 及其 XNNPACK 计算池。请求为空时不接管线程创建。
- 同步及异步 ASR native 解码调用在作用域内临时设置调用线程，退出时恢复，异常路径也恢复。若无法读取共享线程原有 QoS，则跳过其 QoS 设置；若无法读取原 affinity，则跳过绑核。设置被系统拒绝时保留识别流程并记录诊断。
- 不改变 N-API 队列优先级，不调整 ArkTS 主线程；这些配置不承诺降低队列等待。QoS、绑核和忙等选项只作用于 ASR 模型。`numThreads` 沿用基础 SDK 的语义，也用于标点模型构造；声纹和 Speaker VAD 的配置不变。
- 非空 CPU 集合不表示固定频率或独占 CPU；系统可能拒绝或收窄请求。不要跨机型复制 CPU 编号。
- `AmphionScheduling` hilog 记录设置返回码、QoS 读取结果、affinity 是否与请求一致，以及恢复失败；同一 recognizer 的同类结果只记录一次，避免逐帧日志干扰性能。不包含音频或文本。出现恢复失败的运行不能作为非侵入性验收 PASS。
- `allowSpinning=false` 和启用 prepack 都只是可测的取舍，没有预设息屏性能收益。不开启保活、网络请求、自动权限申请或系统省电设置修改。

## 对照验证

同一源码和 HAP、同一 PCM/分帧/实时节奏，依次对照默认、仅 QoS、仅绑核、两者组合；线程数、忙等、prepack 每次单独改变。不要同时修改多个变量后归因。

现有真机脚本增加以下参数，参数会写入根 `report.json`：

```bash
python3 delivery/harmony-dingqiao/delivery/run_device_stress.py \
  --data-dir "$HOME/.cache/amphion-runtime/test-data/v1/aishell3_test_hotwords_500" \
  --mode paced --files 1 --cycles 1 --skip-build-install \
  --asr-qos user-initiated
```

忙等缺省与 `disablePrepack` 同理：测试载体显式传入 `scheduling`，因此 `--asr-disable-spinning` 等参数验证的是显式路径，不验证省略 `scheduling` 时的 mode 缺省。验证缺省路径必须实际省略该对象。

其他对照参数：`--asr-cpu-ids <已验证的CPU集合>`、`--asr-num-threads 1..8`、`--asr-disable-spinning`、`--asr-enable-prepack`。未指定时沿用测试载体原有配置；其中载体默认显式传 `disablePrepack=true`，`--asr-enable-prepack` 则显式传 `false`，均不验证 SDK 未设置该键的模式缺省路径。验证缺省路径时必须实际省略该键。测试载体沿用现有后台录音条件，SDK 自身不负责这一能力。

验收须逐 session 检查显式 finish 前没有 last、结束后唯一 last/complete、cancel 后无新增 final/complete、卸载后恢复。比较屏幕状态时，还需区分 PCM 到达间隔、调度等待、推理耗时和回调延迟，不能只用最终识别文本判断性能。USB 供电、调试连接、温度和客户后台运行条件也需保持一致。

本分支提供可选能力；客户设备的息屏收益和完整发布门禁需另有对应构建的实测证据，不能仅凭单测或编译通过宣称已修复息屏性能。

参考：[鸿蒙 N-API QoS 调度说明](https://developer.huawei.com/consumer/cn/doc/harmonyos-guides-V5/use-napi-about-extension-V5)、[ONNX Runtime 线程配置](https://onnxruntime.ai/docs/performance/tune-performance/threading.html)。当前依赖 ORT 1.16.3，仅使用其已有的 spinning 开关，不使用较新版本的 spin duration/backoff 参数。
