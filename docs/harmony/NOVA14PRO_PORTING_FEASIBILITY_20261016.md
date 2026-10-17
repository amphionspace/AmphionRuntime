# nova 14 Pro 移植可行性实测（2026-10-16）

回答三个问题：SDK 能不能在这台机器上跑、能不能用它的 NPU、ASR 能不能搬过来。
结论全部基于真机实测，**ASR 上 NPU 这一项做了实际迁移尝试**，不是推断。

## 一、结论速览

| 问题 | 结论 | 依据 |
|---|---|---|
| SDK 能否运行 | **能** | 安装、启动、识别、角色分离全部通过，`sdk=PASS`、空 final 率 0.000 |
| 能否使用 NPU | **能，但只限说话人编码器** | 会话内实测 `encoderBackend=npu`，设备 `NPU_ohos.boot.hardware.kirin8020_v2_0` |
| ASR 能否搬上 NPU | **不能**，且与机型无关 | 见第四节，两道墙均已实测复现 |

**ASR 本身在任何机型上都跑在 CPU（ORT/XNNPACK），Mate 80 亦然。** 本文所说"NPU 可用"
指的始终是角色分离链里的说话人编码器那一张图。

## 二、设备与软件环境

| 项 | nova 14 Pro | 对照：Mate 80 |
|---|---|---|
| 型号 | MIA-AL00 | 我方测试机 |
| 系统 | 6.0.0.130 / OpenHarmony-6.0.2.130 | 6.1.0.135 / OpenHarmony-6.1.1.120 |
| **API** | **22** | 24 |
| ABI | arm64-v8a | arm64-v8a |
| NPU | `kirin8020_v2_0` | `kirin9020`（既有记录） |

API 22 比我方日常验证的 API 24 低两级，HAP 仍可安装运行——交付工程声明的
`compatibleSdkVersion` 是 `5.0.0(12)`。

### 两项前置条件（均非阻塞）

1. **签名**：该机 UDID 已在现有 DevEco signing-project profile 的设备白名单内，无需新增申请。
2. **授权**：授权按 `deviceInfo.ODID` 绑定。该机 ODID 不在原签发清单内，首次运行 ASR 返回
   `license-1002200033`；把其 ODID 纳入清单重签后即通过。**正式交付需把目标机器 ODID 纳入
   签发清单**，属既有流程。

## 三、SDK 与 ASR 实测结果

构建身份 `07dc706f`（主线，含聚类上限与预览预算两项改动），diagnostics 构建。

### 3.1 文本正确性

8 条数字用例输出与 Mate 80 **逐字相同**：

```
12345678910。123。12345。2.58万。13800138000。2026/05/15。38。8910。
```

含 0.3.23 修复的两处（连续数字不拆组、日期两侧无空格）。文本链路行为跨机型一致。

### 3.2 客户原始录音（523.7 秒，角色分离开启）

| 指标 | nova 14 Pro |
|---|---|
| 总体 | `PASS`，空 final 率 0.000 |
| final | 58 条，2193 字 |
| 说话人数 | 4 |
| 角色更新 / 结果 | 39 / 5 |
| 降级 | 0 |
| 原生流泄漏 / 意外回调 | 0 / 0 |
| 角色分离 RTF | **0.0767** |
| RSS | 头 622.8 → 尾 651.6 MiB，斜率 0.76 MiB/min，峰值 675.8 MiB |
| 跑完即刻后壳温度 | 38.2 °C |

同一段录音在 Mate 80 上的既有记录是 2199 字、说话人 4、角色更新 39 / 结果 5——**字数差 6、
角色侧计数完全一致**。（utterance 条数口径不同：既有记录计的是 79 条 utterance，本次计的是
58 条 final，二者不是同一计数单位，不构成差异。）

### 3.3 角色分离耗时拆分

| | 次数 | 合计 | 占比 |
|---|---|---|---|
| 窗口推理 | 258 | 25.9 s | 64.4% |
| 提交聚类 | 5 | 2.0 s | 5.0% |
| 预览聚类 | 45 | 12.3 s | 30.5% |

合计 40.2 s / 523.7 s 音频。该会话较短（258 窗口），训练集上限未触发，预览占比也低于
长会话——这组数**不可直接与 Mate 80 的 2 小时基线比较**。

## 四、ASR 上 NPU：实际迁移尝试与失败原因

NPU 路径要求 MindSpore Lite 载入 `.ms` 模型并交由名字含 `kirin` 的 NNRt 加速器执行。
对 ASR 的三张图逐一实做如下。

### 4.1 第一道墙：encoder 连格式转换都过不去

用 MindSpore Lite 2.7.0 的 `converter_lite`（Linux x86_64，容器内执行）转换
`encoder.int8.onnx`：

```
UNSUPPORTED OP LIST:
  FMKTYPE: ONNX, OP TYPE: DynamicQuantizeLinear
  FMKTYPE: ONNX, OP TYPE: MatMulInteger
Convert failed. Ret: Common error code.
```

我方 ASR encoder 采用 ONNX Runtime 的动态量化方案，其 `DynamicQuantizeLinear` 与
`MatMulInteger` 不被 MindSpore Lite 的 ONNX 解析器支持。**模型无法生成 `.ms`，不存在上 NPU
的可能。**

### 4.2 第二道墙：decoder / joiner 能转，但 NPU 拒绝构建

两者为 fp32，转换通过（`CONVERT RESULT SUCCESS:0`，产物 17.5 MB / 16.4 MB）。推入设备后以
`npu` 后端探测：

```
{"status":"FAIL","requestedBackend":"npu",
 "device":"NPU_ohos.boot.hardware.kirin8020_v2_0","stage":"build","code":-1}
```

设备侧日志给出直接原因：

```
HIAI_DDK: ModelRuntimeRepo_TryBuild "no runtime support the Model."
HIAI_DDK: BuildModel "build model failed."
NNRt_HiAIAdapter: HiaiExecutorImpl::model build fail!
NNRt: [NNCompiler] Build failed, fail to prepare model when normally building
MS_LITE: BuildKirinNPUModel# Create full model kernel failed
```

**NPU 已找到且可寻址**——同一台机器、同一次会话中说话人编码器 `buildMs 460.8 / status PASS`。
失败发生在 HiAI 运行时判定"没有运行时支持该模型"。

另记录一条相关现象：该机加载 `libhiai_ir_infershape.so` 失败（`No such file or directory`），
即设备侧缺少 HiAI 的 IR 形状推导库，动态形状本就无法在设备上推导。

### 4.3 结构差异（实测）

| | ASR encoder | decoder | joiner | 说话人编码器 |
|---|---|---|---|---|
| 输入 | **117** | 1 | 2 | 1 |
| 输出 | **117** | 1 | 1 | 1 |
| 含动态维的输入 | **117 / 117** | 1 / 1 | 2 / 2 | **0 / 1** |
| 形状 | 全动态 | `[N,2]` | `[N,512]` ×2 | 固定 `[1,998,80]` |
| 节点数 | 12235 | 17 | 3 | 卷积为主 |

ASR encoder 的 116 个 `cached_*` 输入是流式 transducer 的状态缓存，输出维度由 `Slice` / `Add`
在运行时算出（如 `Slicenew_cached_key_0_dim_0`）。仅 3 个节点的 joiner 也因 batch 维为动态而
被拒绝构建——**决定性因素是形状是否静态，不是模型大小**。

源码对此早有判据，本次实测与之一致：

> The speaker encoder is the one Community stage with a fixed-shape, convolution-only graph
> (fbank [1,998,80] -> [1,2560,125]), so it is the one stage that can leave the CPU.

### 4.4 结论

**ASR 无法迁移到 NPU，与 nova 14 Pro 无关**，Mate 80 上原因完全相同。两道墙：

1. encoder 的动态量化算子不被 MindSpore Lite 转换器支持；
2. 流式 transducer 的动态形状不被 HiAI 运行时接受（decoder / joiner 已实测确认，encoder 即便
   越过第一道墙亦将撞上第二道）。

要真正把 ASR 放上 NPU，需要的是**改模型导出方式**：去除动态量化、把流式缓存固定为静态形状、
按固定 chunk 导出并重新验证精度。这属于模型侧工程，SDK 集成层无法解决。

## 五、本次未覆盖

- **长时稳定性**：最长会话 523.7 秒。内存斜率 0.76 MiB/min 取自该段，不足以外推长会议。
- **锁屏 / 后台行为**：未测。Mate 80 上锁屏会把全部线程压入 `0-3`，该机调度域结构未知。
- **绑核生效性**：未测 `affinity-exact`。该参数跨机型、跨系统版本不可移植，部署前需逐机实测。
- **CPU 拓扑**：`/proc/cpuinfo` 与 `/sys/devices/system/cpu/` 对 shell 用户均为 Permission denied，
  未取得核数与分组。
- **温升曲线**：仅记录跑完即刻的 38.2 °C，无全程曲线。
- 本次性能数据取自 523.7 秒会话，训练集上限与预览限流在该长度下均未充分触发。
