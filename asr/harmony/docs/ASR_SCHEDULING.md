# 鸿蒙 ASR 可选调度配置

这些选项用于比较息屏前后的 ASR 性能，默认保持现有行为。设置请求不保证系统提供更多 CPU 资源，也不授予后台运行或录音权限。绑核属于实验能力，必须针对客户机型验证。

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
scheduling.allowSpinning = true;
params.scheduling = scheduling;
params.numThreads = 4;
// 已有选项：false 启用权重预打包，以加载时间和内存换取推理吞吐。
params.extraParams['disablePrepack'] = true;
const engine = SpeechRecognizeSdk.createEngine(params);
```

基础 SDK 使用 `AsrConfig.scheduling` 和已有的 `AsrConfig.numThreads`、`disablePrepack`。`AsrConfig.builder().scheduling(...)` 同样可用；`AsrSchedulingConfig` 从两个 SDK 的入口导出。

| 配置 | 默认值 | 含义 |
|---|---|---|
| `scheduling.qos` | `default` | 保持系统策略；可选 `user-initiated`、`user-interactive` |
| `scheduling.cpuIds` | `[]` | 不修改 affinity；非空为允许执行的零起始 CPU 编号集合，不自动推断大核 |
| `scheduling.allowSpinning` | `true` | 保留 ORT 的忙等；设为 false 减少空转，可能增加唤醒延迟 |
| 鼎桥 `numThreads` | `4` | ASR 推理线程数，含调用线程，整数 1–8；基础 SDK 原默认 2 不变 |
| `disablePrepack` | `true` | 保留原来偏向低内存、快加载的策略 |

配置在创建引擎时复制，CPU 数组也会复制。修改原对象不影响正在加载或运行的引擎。切换策略需创建新引擎；不支持通过 `StartParams` 在会话中切换。调度参数参与模型复用判定，防止复用具有另一套策略的模型。

## 作用范围和限制

- HarmonyOS API 12 起的 QoS 接口，与工程原有最低版本一致。仅修改鸿蒙 ASR；Android 不使用这些策略。
- ASR 模型内部 ORT 工作线程使用所属 recognizer 的固定策略，线程随模型销毁被等待并回收。没有新增进程级线程池。
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

其他对照参数：`--asr-cpu-ids <已验证的CPU集合>`、`--asr-num-threads 1..8`、`--asr-disable-spinning`、`--asr-enable-prepack`。没有指定时保持原默认值。测试载体沿用现有后台录音条件，SDK 自身不负责这一能力。

验收须逐 session 检查显式 finish 前没有 last、结束后唯一 last/complete、cancel 后无新增 final/complete、卸载后恢复。比较屏幕状态时，还需区分 PCM 到达间隔、调度等待、推理耗时和回调延迟，不能只用最终识别文本判断性能。USB 供电、调试连接、温度和客户后台运行条件也需保持一致。

本分支提供可选能力；客户设备的息屏收益和完整发布门禁需另有对应构建的实测证据，不能仅凭单测或编译通过宣称已修复息屏性能。

参考：[鸿蒙 N-API QoS 调度说明](https://developer.huawei.com/consumer/cn/doc/harmonyos-guides-V5/use-napi-about-extension-V5)、[ONNX Runtime 线程配置](https://onnxruntime.ai/docs/performance/tune-performance/threading.html)。当前依赖 ORT 1.16.3，仅使用其已有的 spinning 开关，不使用较新版本的 spin duration/backoff 参数。
