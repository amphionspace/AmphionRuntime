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
| `scheduling.diarizationEncoder` | `auto` | **0.3.26 起不再生效**：角色分离换成 Sortformer-66M-4spk，整条链路在 CPU（ORT 1.16.3 CPU EP）上运行，没有 NPU 路径。字段保留只为让既有配置继续编译；取值仍按原规则校验（`cpu`/`npu`/`auto`），但不改变任何行为，角色结果的 `encoderBackend` 恒为 `cpu` |
| `scheduling.diarizationHopMs` | `2000` | **0.3.26 起不再生效**：Sortformer 链路没有滑动分析窗，每 9.92 s 提交一个块。字段保留只为兼容，取值仍按 250–10000 校验，但不改变任何行为。刷新节奏改由 `diarizationPreviewMs` 控制 |
| `scheduling.diarizationPreviewMs` | `5000` | **0.3.26 新增**。临时角色的刷新周期（毫秒，`0` 或 2500–9920，向下取整到 80 ms）。Sortformer 每 9.92 s 块提交一次最终角色；到达该周期时对块内已到部分做一次不推进 speaker-cache 的预览推理，先给调用方临时角色，块完成后由最终结果覆盖。每次预览约等于一次块推理（实测 328–344 ms 对 389 ms），5000 使角色分离算力约翻倍（RTF 0.045 → 0.075~0.080，与原 Community 链路 0.083 相当），2500 约三倍。`0` 关闭预览，首次角色等待 ≈10 s。预览→最终的标签翻转率实测 1.7%~2.4% 帧·槽位 |
| `scheduling.diarizationQos` | `auto` | 角色分离工作线程（Sortformer 引擎的 role worker）的调度放置：`auto` 在 `diarizationPreviewMs >= 2000`（含 0，即不预览）时解析为 `background`、否则为 `inherit`；`inherit` 不设任何 QoS、直接继承前台策略；`utility`、`background` 显式降低操作点；`default` 显式设为 `QOS_DEFAULT`。角色结果在任何取值下都逐位不变。每块推理是一次约 0.4 s 的 2~4 核脉冲，之后空闲约 9.5 s，`background` 的意义与此前相同：把脉冲压在较低操作点上 |
| 鼎桥 `numThreads` | `4` | ASR 推理线程数，含调用线程，整数 1–8；基础 SDK 原默认 2 不变 |
| `disablePrepack` | `true` | 保留原来偏向低内存、快加载的策略 |

配置在创建引擎时复制，CPU 数组也会复制。修改原对象不影响正在加载或运行的引擎。切换策略需创建新引擎；不支持通过 `StartParams` 在会话中切换。调度参数参与模型复用判定，防止复用具有另一套策略的模型。

## 作用范围和限制

- HarmonyOS API 12 起的 QoS 接口，与工程原有最低版本一致。仅修改鸿蒙 ASR；Android 不使用这些策略。
- ASR 模型内部 ORT 工作线程使用所属 recognizer 的固定策略，线程随模型销毁被等待并回收。没有新增进程级线程池。
- 同步及异步 ASR native 解码调用在作用域内临时设置调用线程，退出时恢复，异常路径也恢复。若无法读取共享线程原有 QoS，则跳过其 QoS 设置；若无法读取原 affinity，则跳过绑核。设置被系统拒绝时保留识别流程并记录诊断。
- 不改变 N-API 队列优先级，不调整 ArkTS 主线程；这些配置不承诺降低队列等待。绑核和忙等选项只作用于 ASR 模型。`numThreads` 沿用基础 SDK 的语义，也用于标点模型构造；声纹和 Speaker VAD 的配置不变。
- 鼎桥 SDK 开启角色分离时，`scheduling.qos` 也作用于角色分离自有的推理和聚类线程，但始终比 ASR 低一级：`user-interactive` 对应角色线程 `QOS_USER_INITIATED`，`user-initiated` 对应 `QOS_DEFAULT`，`default` 不设置。这些线程仍先设为 nice 10；系统接受 QoS 后按该等级的策略调度，拒绝时保持 nice 10。用于系统应用在息屏或后台时，让角色分离与 ASR 一起摆脱后台默认策略，同时转写仍然优先。不调整借用的运行时线程。
- 非空 CPU 集合不表示固定频率或独占 CPU；系统可能拒绝或收窄请求。不要跨机型复制 CPU 编号。
- `AmphionScheduling` hilog 记录设置返回码、QoS 读取结果、affinity 是否与请求一致，以及恢复失败；同一 recognizer 的同类结果只记录一次，避免逐帧日志干扰性能。角色线程每个线程启动时记录一次 `role-qos requested/result/effective`。不包含音频或文本。出现恢复失败的运行不能作为非侵入性验收 PASS。
- 成功角色窗口的 `encoderBackend`、`encoderDevice` 和 `encoderMs` 分别记录运行路径、所选设备名和仅 `Encoder.Run` 的耗时；`embeddingMs` 仍包含编码和全部 pooling。这些字段以及 NNRt 构建成功日志，不证明全图算子已委托 NPU。MindIR 中 FP16 常量存储不代表全图 FP16 计算；边界输入输出要求 FP32，具体委托和计算精度须有独立系统及硬件证据。
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
