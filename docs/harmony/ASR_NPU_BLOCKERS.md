# ASR 上 NPU：阻塞点清单（2026-10-27 整理）

本文是 `ASR_NPU_RETEST_20261023.md` 的阻塞点提炼，便于对外沟通与排期。
实验方法、七个变量的逐一隔离过程、两个被推翻的中间结论见那份复测文档，本文不重复。

## 读法前提（重要）

- 所有 `PASS` 只代表**「NPU 加速器愿意接受并编译这个模型」**，探测口径是**零值输入**，
  原文 `scope` 为 `zero-filled inputs; latency and backend acceptance only, not accuracy`。
  **本文与复测文档均不含任何精度数据**，`PASS` 不等于识别结果正确。
- 环境：HUAWEI nova 15（PSN-AL00），Kirin 8020，OpenHarmony-6.0.2.130，arm64-v8a；
  NPU `NPU_ohos.boot.hardware.kirin8020_v2_0`；转换器 MindSpore Lite 2.7.0 `converter_lite`。
- **仅覆盖 nova 15 / Kirin 8020 一款机型。** Mate 80 / Kirin 9020 未用同方法复测。

## 阻塞点总表

| # | 阻塞点 | 性质 | 谁能解 | 当前状态 |
|---|---|---|---|---|
| **B1** | `Authentication failed`：encoder 压到 156 MB、低于已验证通过线，仍被拒 | **硬阻塞** | **华为侧** | 七个结构性变量已全部排除，本地探针用尽 |
| **B2** | 节点数过多导致 NPU 编译器**进程崩溃**，崩溃点在 1536–3766 节点之间，encoder 恰为 3766 | 硬约束 | 模型导出层 + SDK | 未评估拆图可行性 |
| **B3** | 单模型体量上限在 **201–268 MB** 之间 | 硬约束 | 模型导出层 | 已量化到 156 MB，该条已满足 |
| **B4** | decoder 被拒，属独立的算子问题（与体量、形状均无关） | 可推进 | **本地可做** | 唯一线索：`Clip param type invalid` |
| **B5** | 收益未知：**没有任何一组 encoder 的 NPU 延迟数据** | 决策风险 | 依赖 B1 | joiner 上 NPU 反而更慢 |

**B1 是真阻塞。它不解决，B2/B3 都没有意义** —— 因为 encoder 连编译都过不去，拆图和控体量都是在为一个还没证明可行的路径做工程。

---

## B1 `Authentication failed`（硬阻塞，需华为侧）

### 现象

用 `converter_lite` 自带的权重量化把 encoder 从 586 MB 压到 **156 MB**，已低于实测通过线
201 MB，转换本身 `CONVERT RESULT SUCCESS:0`，但设备端构建仍失败。

设备侧日志（取自复测记录）：

```
MS_LITE: nnrt_delegate.cc:100 CheckNPUPrefix# strncmp: 13306020061847651998 failed,
         device_name: NPU_ohos.boot.hardware.kirin8020_v2_0
MS_LITE: nnrt_delegate.cc:580 InitNNCompilation# hiai_foundation is nullptr.
NNRt:    Authentication failed, input model cannot run by npu.
MS_LITE: nnrt_delegate.cc:586 InitNNCompilation# Build NNCompilation failed, ret: 1
MS_LITE: nnrt_delegate.cc:220 CreateFullModelKernel# Init NNCompilation failed
MS_LITE: nnrt_delegate.cc:145 BuildKirinNPUModel# Create full model kernel failed
```

对照：合成模型**因超体量**被拒时的日志**没有** `Authentication failed` 这一行：

```
MS_LITE: nnrt_delegate.cc:145 BuildKirinNPUModel# Create full model kernel failed
```

### 为什么确定不是体量问题

| 判据 | 数据 |
|---|---|
| 体量低于通过线 | 156 MB < 已实测 PASS 的 201 MB |
| 它真的编译了很久才失败 | build **2278–3543 ms**；而超体量是**秒拒** 100–170 ms，差一个数量级 |
| 报错形态不同 | 多出 `Authentication failed` 一行，超限模型没有 |

### 为什么本地定位不下去

HiAI 侧更细的拒绝原因在设备日志里被 `<private>` 掩码，取不到。为逼近原因，
把 encoder 与所有已 PASS 模型之间的差异变量**逐个隔离，七项全部排除**（详见 B 区「已排除变量」）。

剩余可能性 —— 图拓扑复杂度、特定算子组合模式、HiAI 内部的模型规模启发式 ——
**不是本地能构造出的探针所能覆盖的**。

### 需要华为侧回答的问题

1. `NNRt: Authentication failed, input model cannot run by npu.` 的**抛出条件**是什么？
   有哪些模型属性会触发它？
2. 紧随其前的 `InitNNCompilation# hiai_foundation is nullptr.` 是该失败的**原因**还是**结果**？
   同一设备上其它模型（joiner、117 输入输出的合成模型）可正常构建，说明 hiai_foundation 本身可用。
3. `CheckNPUPrefix# strncmp: 13306020061847651998 failed` 中那个数值是什么语义？
   它在成功构建的用例里是否也出现？
4. 能否提供取消 `<private>` 掩码、拿到 HiAI 侧细化拒绝原因的方法（DDK 调试开关 / 特定日志域）？
5. 单模型是否存在**官方的体量与节点数上限**？若有，具体数值是多少（见 B2、B3 的实测值）。

---

## B2 节点数 → NPU 编译器进程崩溃

### 现象

共享同一个 64×64 权重串联 `Gemm`，使节点数变化 29 倍而**体量几乎不变**，唯一变量是节点数：

| 产物 | 节点数 | 体量 | NPU | build |
|---|---|---|---|---|
| `nd-n128.ms` | 128 | 19 KB | **PASS** | 314.2 ms |
| `nd-n512.ms` | 512 | 30 KB | **PASS** | 607.4 ms |
| `nd-n1536.ms` | 1536 | 61 KB | **PASS** | 2079.6 ms |
| `nd-n3766.ms` | **3766**（与 encoder 相同） | 131 KB | **进程崩溃** | — |

3766 节点那次，设备日志只剩一行开始标记，之后进程消失，连结果行都写不出来：

```
MINDIR_PROBE|BEGIN|runId=z3766|backend=npu|bytes=513100
（无 RESULT、无 END）
```

**两次独立运行均复现**（第二次在第 3 次轮询时进程已消失）。

### 判据

- 体量仅 **131 KB**，与内存容量无关 —— 是 **NPU 编译器在处理深链图时自身崩溃**，不是 OOM。
- build 耗时与节点数近似成正比（128→1536 节点，314→2080 ms），证实编译开销由**节点数**驱动而非体量。
- **崩溃点落在 1536 与 3766 节点之间**，encoder 恰为 3766 节点。

### 影响

即便 B1 解决，encoder 仍可能需要**拆成多个子图分段上 NPU**，并核算跨段数据搬运开销。
该可行性与开销**均未评估**。

---

## B3 单模型体量上限 201–268 MB

### 现象

为把「体量」与「算子组合」彻底分开，合成一组只含 `Gemm`、形状全静态、1 输入 1 输出的对照模型
（`[1,4096]` 输入配 4096×4096 fp32 权重逐层叠加），**唯一变量是体量**：

| 产物 | 体量 | NPU | build |
|---|---|---|---|
| `synth-64mb.ms` | 67 MB | **PASS** | 801 ms |
| `synth-128mb.ms` | 134 MB | **PASS** | 1287 ms |
| `synth-192mb.ms` | 201 MB | **PASS** | — |
| `synth-256mb.ms` | 268 MB | **FAIL** | 158 ms |
| `synth-320mb.ms` | 336 MB | **FAIL** | 172 ms |
| `synth-640mb.ms` | 671 MB | **FAIL** | 117 ms |

**阈值落在 201 MB 与 268 MB 之间。** 两个旁证：

- 超限时 build 仅 100–170 ms —— 是**直接拒绝**，没有进入编译；
- 通过时 build 随体量单调上升（801 → 1287 ms）—— 说明确实在编译。

### 状态

该条**已满足**：权重量化后的 encoder 为 156 MB（现场复核：`encoder.int8w.ms` 156.2 MB）。
但满足之后撞上 B1，所以这条不再是当前阻塞 —— 它是未来任何 encoder 导出都必须守住的**预算线**。

---

## B4 decoder 被拒：独立的算子问题（本地可推进）

### 现象

把 batch 维固定后，joiner 通过而 decoder 仍被拒 —— 两者体量、形状条件相同：

| 模型 | 体量 | 节点 | 算子 | NPU |
|---|---|---|---|---|
| joiner（静态） | 16 MB | 3 | `Add` `Gemm` `Tanh` | **PASS** median 0.819 ms |
| decoder（静态） | 17 MB | 17 | 含 `Clip` `GreaterOrEqual` `Gather` `Conv` `Squeeze` `Transpose` | **FAIL** |

唯一线索是转换阶段的警告，出现两次：

```
Clip param type invalid
```

### 已知与未知

- 原先推测是 `Clip` / `GreaterOrEqual` / `Gather` 所致，但 **`Gather` 单算子实测 PASS**，已排除。
- `Clip`、`GreaterOrEqual` **未单独验证**（它们不在 encoder 的算子差集内，上一轮没覆盖）。
- 下一步明确可做：给 `Clip`、`GreaterOrEqual` 做「`Gemm` → 算子 → `Gemm`」三明治对照
  （单算子最小用例不可靠，原因见下文方法论教训）。

### 为什么它对整体很关键

流式 transducer **每解码一步都要跑一次 decoder**。decoder 上不了 NPU，整条链路就必须
在 CPU 与 NPU 之间来回搬数据，encoder 单点加速的收益会被搬运开销吃掉多少，目前没有数据。

---

## B5 收益未知（决策风险）

这一条不是技术阻塞，但影响是否值得继续投入：

| 事实 | 数据 |
|---|---|
| **没有任何一组 encoder 的 NPU 延迟数据** | encoder 至今未在 NPU 上构建成功过一次 |
| joiner 上 NPU **反而更慢** | median **0.819 ms**（NPU）vs **0.648 ms**（CPU）。3 节点的 `Gemm` 图本不该上 NPU |
| decoder 上不了 NPU | 见 B4，会引入跨后端搬运 |

也就是说：现在不只是「做不到」，而是**连「做到了能快多少」都不知道**。
真实收益只可能来自 encoder，而那恰好是卡在 B1 的那一环。

---

## 已排除的变量（避免重走）

下列七项**均已实测排除**，不是 `Authentication failed` 的触发条件：

| 变量 | 排除依据 |
|---|---|
| 动态量化算子（`DynamicQuantizeLinear`/`MatMulInteger`） | 去量化后转换成功，产出 `.ms`（现场复核 `encoder.npu.ms` 586.2 MB） |
| 动态形状 | 静态化的 joiner 在 NPU 上 PASS |
| 已知拒绝算子（`GatherElements`×19、`LessOrEqual`×1） | 10-08 轮已重写，`residualRefusedOperators: {}` |
| 模型体量 | 压到 156 MB（低于 201 MB 通过线）仍 FAIL |
| 输入/输出数量 | 117 输入 / 117 输出的合成模型 **PASS**（build 740.9 ms） |
| **算子种类** | encoder 用到的 **26 种算子全部可被接受**（见下） |
| `libhiai_ir_infershape.so` 缺失 | joiner 在同样缺库下构建成功，与成败无关 |

### 关于「输入输出数量」的一个连带结论

117 输入输出完全可接受，这同时**否掉了一个看似可行的改法**：把 116 个 `cached_*`
按 6 类各拼成 1 个张量（117 → 7 输入）**解决不了问题**。先验证再动手，省下一轮无用的导出改造。

---

## 两条必须记住的方法论教训

### 1. 单算子最小用例在「加速器是否接受」上不是可靠探针

给 encoder 的 26 种算子逐个做单算子最小用例，初看是 **7 个算子被拒**，包括
`Sigmoid`、`Softmax`、`Transpose`、`Concat`。

但所有 FAIL 的 build 都是 **17–35 ms**（秒拒），所有 PASS 的都是 **157–184 ms**，两组泾渭分明 ——
这更像图的**形式**被拒，而非算子不被支持。于是做了三明治对照（`Gemm` → 算子 → `Gemm`）：

| 用例 | 单算子图 | 三明治 | build（三明治） |
|---|---|---|---|
| `Transpose` | FAIL | **PASS** | 168.6 ms |
| `Concat` | FAIL | **PASS** | 349.3 ms |
| `Where` | FAIL | **PASS** | 174.2 ms |
| `Sigmoid` | FAIL | **PASS** | 172.4 ms |
| `Softmax` | FAIL | **PASS** | 173.1 ms |
| `Greater` + `Cast` | FAIL | **PASS** | 180.6 ms |
| `Not` + `Cast` | FAIL | **PASS** | 177.3 ms |
| 纯 `Gemm`（基准） | — | **PASS** | 224.9 ms |

**全部 PASS，「7 个算子被拒」的结论作废。** 被拒的是**单算子图这一形式** ——
推测 NPU/委托层对过于简单的图有「不值得上加速器」的启发式判断。

**若把那个中间结论直接交付，模型侧会收到一份「去掉 `Transpose`/`Concat`/`Softmax`」的待办 ——
这对 Zipformer 根本改不动，是个死任务。**

### 2. int8 权重量化的模型不能作为 CPU 回退方案

权重量化的 encoder 在 **CPU 后端**加载会**打挂应用**（`MINDIR_PROBE|BEGIN|runId=eq8cpu`
之后既无 `RESULT` 也无 `END`）。原因是权重量化在 CPU 推理需反量化回浮点，内存翻倍。
后续不应对超大量化模型做 CPU 后端探测。

---

## 下一步建议

| 优先级 | 动作 | 依赖 |
|---|---|---|
| 1 | 把 B1 的五个问题提给华为侧 | 无，**建议立即发起** |
| 2 | 给 decoder 的 `Clip` / `GreaterOrEqual` 做三明治对照（B4） | 本地可做，约半天 |
| 3 | 评估 encoder 拆成 ≤201 MB、<1536 节点子图的可行性与跨段搬运开销（B2/B3） | 建议等 B1 有回音后再投入 |
| 4 | 在 Mate 80 / Kirin 9020 上用同方法复测 | 另一台设备 |

第 3 项特意排在 B1 之后：**在 encoder 连编译都过不去的情况下做拆图工程，可能是在为一条还没证明可行的路径投入。**

---

## 可现场复核的产物

`.cache/asr-npu-static-probe/`（体量为 2026-10-27 现场复核值）：

| 文件 | 体量 | NPU 结论 |
|---|---|---|
| `encoder.npu.ms` | 586.2 MB | FAIL（超 B3 体量线） |
| `encoder.int8w.ms` | 156.2 MB | **FAIL（B1 `Authentication failed`）** |
| `joiner.static.ms` | 15.7 MB | PASS，median 0.819 ms |
| `decoder.static.ms` | 16.6 MB | FAIL（B4 算子） |
| `enc-frontend.ms` | — | PASS（encoder 前端 59 节点） |
| `nd-n{128,512,1536,3766}.ms` | 19/30/61/131 KB | 前三 PASS，3766 使编译器崩溃 |
| `io-io{4,16,32,64,117}.ms` | 17–40 KB | 全部 PASS |
| `synth-{64,128,192,256,320,640}mb.ms` | 67–671 MB | 体量阶梯，阈值 201–268 MB |
| `ops/op-*.ms` | — | 15 个单算子用例，**其 FAIL 结论已被三明治推翻** |
| `sand/sd-*.ms` | — | 8 个三明治对照，全部 PASS |

`.cache/asr-encoder-npu/`（10-08 轮产物，provenance 现场复核）：

| 文件 | provenance 记录 |
|---|---|
| `encoder.dequantized.fp32.onnx` | 617,234,820 B；去除 `matmul_integer`×344、`dynamic_quantize_linear`×312 |
| `encoder.npu-ops.fp32.onnx` | 617,918,865 B；`refusedOperators: {GatherElements: 19}` |
| `encoder.upstream.npu.fp32.onnx` | 614,978,834 B；`refusedOperators: {GatherElements: 19, LessOrEqual: 1}` 已重写 |

## 未覆盖

- **任何精度数据。** 全部探测为零值输入。
- `Authentication failed` 的确切触发条件（B1）。
- encoder 拆子图分段上 NPU 的可行性与跨段搬运开销（B2）。
- decoder 的 `Clip` / `GreaterOrEqual` 单独验证（B4）。
- 其他机型（仅 nova 15 / Kirin 8020）。
