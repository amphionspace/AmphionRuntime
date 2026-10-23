# ASR 上 NPU 迁移复测：两处归因修正、两道新墙与七个变量的逐一排除（2026-10-23）

## 本文是什么

`NOVA14PRO_PORTING_FEASIBILITY_20261016.md` 第四章结论为「ASR 无法迁移到 NPU」，并给出三条
模型侧待办：去除动态量化、把流式缓存固定为静态形状、按固定 chunk 导出。

本文是对该章的**实机复测**。结论方向（属模型侧工程、SDK 集成层无法解决）成立，但：

- 该章的**三处归因与实测不符**；
- 它给的三条待办，**10-08 那轮（`.cache/asr-encoder-npu/`）就已全部完成**，本文验证了它们确实有效；
- 做完之后 ASR encoder **依然上不了 NPU**，拦路的是该章从未记录的新墙；
- 为定位真正的拦路原因，**逐一隔离了七个结构性变量，全部排除**；`Authentication failed`
  的触发条件至今未知，本地探针已用尽，需华为侧支持。
- 过程中产生过两个被自己推翻的中间结论（第 5.3、第 6 节），一并记录以免重走。

## 环境

| 项 | 值 |
|---|---|
| 设备 | HUAWEI nova 15（PSN-AL00），Kirin 8020，OpenHarmony-6.0.2.130，arm64-v8a |
| NPU | `NPU_ohos.boot.hardware.kirin8020_v2_0`（与说话人编码器同一加速器） |
| 转换器 | MindSpore Lite 2.7.0 `converter_lite`，Linux x86_64，Docker `--platform linux/amd64` 容器 |
| 探测 | Diagnostics Demo 的 `probeMindSporeBackend`（`MindirProbe.ets`） |
| 产物 | `.cache/asr-npu-static-probe/`，另有 10-08 轮产物 `.cache/asr-encoder-npu/` |

**探测口径**：零值输入，只判「加速器是否接受该图」与延迟。`scope` 字段原文为
`zero-filled inputs; latency and backend acceptance only, not accuracy`。
**本文不含任何精度数据**，下文所有 PASS 均不代表识别结果正确。

## 0. 结论速览

| 该章论断 | 复测结果 |
|---|---|
| 第一道墙：动态量化算子不被支持，**无法生成 `.ms`**，不存在上 NPU 的可能 | **已突破**。去量化后的图转换成功，产出 586 MB `.ms` |
| 第二道墙：流式 transducer 的**动态形状**不被 HiAI 接受 | **归因有误**。静态化的 joiner 在本机 NPU 上 PASS |
| 推断：encoder 越过第一道墙亦将撞上第二道 | **不成立**。它撞的是别的墙 |
| `libhiai_ir_infershape.so` 缺失致动态形状无法推导 | **是噪声**。joiner 在同样缺库下构建成功 |
| （未记录） | **新墙一：单模型体量上限 201–268 MB** |
| （未记录） | **新墙二：encoder 压到 156 MB 仍被拒，`Authentication failed`，原因未定位** |
| （未涉及） | decoder 是**独立的算子问题**，与体量和形状均无关 |
| （未记录） | **新墙三：节点数**。3766 节点使 NPU 编译器**进程崩溃**（两次复现），崩溃点在 1536–3766 之间 |
| （未记录） | `Authentication failed` 的**七个**候选变量已逐一排除（含算子种类），触发条件仍未知 |

## 1. 第一道墙已突破

10-08 那轮已完成该章要求的三件事，产物与 provenance 在 `.cache/asr-encoder-npu/`：

| 产物 | 内容 |
|---|---|
| `encoder.dequantized.fp32.onnx` | 去除 ORT 动态量化（`DynamicQuantizeLinear` / `MatMulInteger`），617 MB / 10891 节点 |
| `encoder.upstream.fp32.onnx` | 从源 checkpoint `epoch-4.pt`（2.86 GB）重新导出 |
| `encoder.upstream.npu.fp32.onnx` | 重写设备拒绝算子（`GatherElements`×19、`LessOrEqual`→`Greater+Not`），3766 节点，`residualRefusedOperators: {}`，数值校验 maxAbsDiff 7.9e-4 |
| `upstream-inputshape.txt` | 全静态输入形状：`x:1,77,80` + 116 个 `cached_*` |

该轮 provenance 的 `scope` 明确写着
`does not prove that the rewritten graph compiles on NNRt, nor anything about accuracy`
—— 即**从未验证能否在 NNRt 上编译**。本文补上该验证。

转换结果：

```
converter_lite --fmk=ONNX \
  --modelFile=encoder.upstream.npu.fp32.onnx \
  --inputShape='<upstream-inputshape.txt 全文>' \
  --outputFile=encoder.npu
→ CONVERT RESULT SUCCESS:0
→ encoder.npu.ms  614,721,200 bytes
```

**该章「模型无法生成 `.ms`，不存在上 NPU 的可能」这句话不再成立。**

## 2. 第二道墙的归因有误：决定性因素不是形状

把 joiner 的 batch 维由 `N` 固定为 1（唯一改动，3 节点、`Add`/`Gemm`/`Tanh`），转换后探测：

```json
{"status":"PASS","requestedBackend":"npu",
 "device":"NPU_ohos.boot.hardware.kirin8020_v2_0",
 "buildMs":282.6,"medianMs":0.819}
```

HiAI 日志与该章记录的失败完全相反：

```
HIAI_DDK_MSG: model.cpp BuildWeightMergedModelBuffer "Build success!"
HIAI_DDK_MSG: model_builder_impl.cpp BuildModel "build model success."
HIAI_DDK_MSG: hiai_foundation_dl_helper.c HIAI_Foundation_IsNpuSupport "support NPU"
```

（该章记录的是 `ModelRuntimeRepo_TryBuild "no runtime support the Model."` / `BuildModel "build model failed."`）

**确认是本机 NPU 在执行**，三重证据：

1. 设备名 `NPU_ohos.boot.hardware.kirin8020_v2_0`；
2. 上列 HiAI 构建成功日志；
3. 后端间构建耗时差异：NPU 282.6 ms vs CPU 42.2 ms（非静默回落）。

但同样固定形状的 decoder 仍被拒：

| 模型 | 体量 | 节点 | 算子 | NPU |
|---|---|---|---|---|
| joiner（静态） | 16 MB | 3 | `Add` `Gemm` `Tanh` | **PASS** median 0.819 ms |
| decoder（静态） | 17 MB | 17 | 含 `Clip` `GreaterOrEqual` `Gather` `Conv` `Squeeze` `Transpose` | **FAIL** |

decoder 转换时 converter 即警告 `Clip param type invalid`（两次）。

**结论：静态形状是必要条件，不是充分条件。** 该章把 decoder/joiner 的构建失败归因于 batch 维动态，
实测证明对 joiner 成立（固定后即通过）、对 decoder 不成立（固定后仍拒），decoder 卡的是算子。

### 2.1 `libhiai_ir_infershape.so` 缺失是噪声

该章把该库缺失记为「动态形状本就无法在设备上推导」的相关现象。实测中 joiner 在同样缺库的情况下
构建成功，**该日志与构建成败无关**。

## 3. 新墙一：单模型体量上限 201–268 MB

为把「体量」与「算子组合」彻底分开，合成一组对照模型：只含 `Gemm`、形状全静态、1 输入 1 输出、
`[1,4096]` 输入配 4096×4096 fp32 权重逐层叠加，唯一变量是体量。

| 产物 | 体量 | NPU | build |
|---|---|---|---|
| `synth-64mb.ms` | 67 MB | **PASS** | 801 ms |
| `synth-128mb.ms` | 134 MB | **PASS** | 1287 ms |
| `synth-192mb.ms` | 201 MB | **PASS** | — |
| `synth-256mb.ms` | 268 MB | **FAIL** | 158 ms |
| `synth-320mb.ms` | 336 MB | **FAIL** | 172 ms |
| `synth-640mb.ms` | 671 MB | **FAIL** | 117 ms |

**阈值落在 201 MB 与 268 MB 之间。** 两个旁证：

- 超限时 build 仅 100–170 ms，是**直接拒绝**；
- 通过时 build 随体量单调上升（801 → 1287 ms），说明确实在编译。

该章未记录这道限制。它意味着任何上 NPU 的 encoder 导出都必须满足 **≤201 MB** 的体量预算，
而 fp32 encoder 为 586 MB，必然超限。

## 4. 新墙二：体量不是 encoder 的全部原因

用 `converter_lite` 自带的权重量化把 encoder 压到阈值以下（配置 `.cache/asr-npu-static-probe/quant8.cfg`）：

```ini
[common_quant_param]
quant_type=WEIGHT_QUANT
bit_num=8
```

586 MB → **156 MB**（26.7%），`CONVERT RESULT SUCCESS:0`。

> 该量化与该章第一道墙不是同一件事。第一道墙卡的是 **ORT 的动态量化算子**
> （`DynamicQuantizeLinear`/`MatMulInteger`），MindSpore Lite 的 ONNX 解析器不认；
> 这里用的是 **converter_lite 自己的权重量化**，走的是另一条路。两者不冲突。

探测结果：

| 模型 | 体量 | 相对 201 MB 通过线 | NPU | build |
|---|---|---|---|---|
| `encoder.npu.ms`（fp32） | 586 MB | 超限 | FAIL | 384 ms |
| `encoder.int8w.ms`（int8 权重） | **156 MB** | **低于通过线** | **FAIL** | **2278 / 3543 ms** |

**两点说明这不是体量问题**：

1. 156 MB 低于已实测通过的 201 MB；
2. build 耗时 2278–3543 ms，与超限秒拒（100–170 ms）相差一个数量级 —— 它真的编译了很久才失败。

**两类失败的报错也不同。** encoder（fp32）：

```
MS_LITE: nnrt_delegate.cc:100 CheckNPUPrefix# strncmp: 13306020061847651998 failed,
         device_name: NPU_ohos.boot.hardware.kirin8020_v2_0
MS_LITE: nnrt_delegate.cc:580 InitNNCompilation# hiai_foundation is nullptr.
NNRt:    Authentication failed, input model cannot run by npu.
MS_LITE: nnrt_delegate.cc:586 InitNNCompilation# Build NNCompilation failed, ret: 1
MS_LITE: nnrt_delegate.cc:220 CreateFullModelKernel# Init NNCompilation failed
MS_LITE: nnrt_delegate.cc:145 BuildKirinNPUModel# Create full model kernel failed
```

合成模型超限（336 MB）：

```
MS_LITE: nnrt_delegate.cc:145 BuildKirinNPUModel# Create full model kernel failed
```
（**无** `Authentication failed` 行）

**encoder 另有第三道墙，本文未定位。** HiAI 侧更细的拒绝原因被 `<private>` 掩码，
设备端取不到；确定 `Authentication failed` 的触发条件需要 HiAI DDK 文档或华为侧支持。

## 5. 变量隔离：七项排除，一项新墙

为定位 `Authentication failed`，逐个隔离 encoder 与所有 PASS 模型之间的差异变量。
合成对照模型一律**只含 `Gemm`、形状全静态**，每组只变一个量。

### 5.1 输入/输出数量 —— 已排除

encoder 有 117 输入 / 117 输出（116 个 `cached_*` 是流式逐层状态缓存），而所有 PASS 的真实模型
只有 1–2 个。合成一组体量极小（17–40 KB）、仅输入输出数量不同的模型：

| 产物 | 输入/输出 | NPU | build | median |
|---|---|---|---|---|
| `io-io4.ms` | 4 / 4 | **PASS** | 602.1 ms | 0.626 ms |
| `io-io16.ms` | 16 / 16 | **PASS** | 266.9 ms | 2.518 ms |
| `io-io32.ms` | 32 / 32 | **PASS** | 254.1 ms | 2.378 ms |
| `io-io64.ms` | 64 / 64 | **PASS** | 351.4 ms | 3.594 ms |
| `io-io117.ms` | **117 / 117** | **PASS** | 740.9 ms | 7.333 ms |

**117 个输入输出完全可接受，该变量排除。**

这同时否掉了一个看似可行的改法：把 116 个 `cached_*` 按 6 类各拼成 1 个张量（117 → 7 输入）
**解决不了问题**。先验证再动手，省下了一轮无用的导出脚本改造。

### 5.2 节点数 —— 新墙，且表现为编译器崩溃

共享同一个 64×64 权重串联 `Gemm`，使节点数变化 29 倍而体量几乎不变：

| 产物 | 节点数 | 体量 | NPU | build |
|---|---|---|---|---|
| `nd-n128.ms` | 128 | 19 KB | **PASS** | 314.2 ms |
| `nd-n512.ms` | 512 | 30 KB | **PASS** | 607.4 ms |
| `nd-n1536.ms` | 1536 | 61 KB | **PASS** | 2079.6 ms |
| `nd-n3766.ms` | **3766**（与 encoder 相同） | 131 KB | **进程崩溃** | — |

3766 节点那次，日志只有 `MINDIR_PROBE|BEGIN|runId=z3766|backend=npu|bytes=513100`，
之后进程消失，连 `RESULT` 都写不出。**两次独立运行均复现**（第二次在第 3 次轮询检查时进程已消失）。

体量仅 131 KB，与内存容量无关：**是 NPU 编译器在处理深链图时自身崩溃**。

build 耗时与节点数近似成正比（128→1536 节点，314→2080 ms），证实编译开销由节点数而非体量驱动。
**崩溃点落在 1536 与 3766 节点之间。**

### 5.3 算子种类 —— 已排除（含一个被自己推翻的中间结论）

encoder 用 26 种算子。取其与已 PASS 模型（joiner 的 `Add`/`Gemm`/`Tanh`、frontend 的 13 种、
合成模型的 `Gemm`）的差集，得 15 种未验证算子，为每种构造**单算子最小用例**（小体量、全静态）：

| 算子 | encoder 中次数 | 单算子图 NPU | build |
|---|---|---|---|
| `MatMul` | 420 | PASS | 157.5 ms |
| `Slice` | 381 | PASS | 184.0 ms |
| `Reshape` | 278 | PASS | 157.1 ms |
| `Transpose` | 250 | ~~FAIL~~ | 35.4 ms |
| `Concat` | 120 | ~~FAIL~~ | 18.5 ms |
| `Where` | 57 | ~~FAIL~~ | 25.8 ms |
| `Expand` | 43 | PASS | 181.7 ms |
| `Pow` | 40 | PASS | 173.4 ms |
| `Sigmoid` | 38 | ~~FAIL~~ | 34.6 ms |
| `ReduceMean` | 20 | PASS | 172.5 ms |
| `Gather` | 19 | PASS | 170.7 ms |
| `Softmax` | 19 | ~~FAIL~~ | 31.3 ms |
| `ReduceSum` | 6 | PASS | 164.1 ms |
| `Greater` | 1 | ~~FAIL~~ | 33.2 ms |
| `Not` | 1 | ~~FAIL~~ | 17.6 ms |

初看是「7 个算子被拒」。但 `Sigmoid`/`Softmax`/`Transpose`/`Concat` 属最基础算子，HiAI 不支持它们
在现实中几乎不可能，且全部 FAIL 的 build 都是 17–35 ms（秒拒）而 PASS 的是 157–184 ms，
两组泾渭分明 —— 这更像是图的**形式**被拒，不是算子不被支持。

**对照实验**：把每个被拒算子嵌入「`Gemm` → 算子 → `Gemm`」三明治（另加纯 Gemm 对照）：

| 用例 | 单算子图 | 三明治 | build（三明治） |
|---|---|---|---|
| `Transpose`（配 `Reshape` 转 3D） | FAIL | **PASS** | 168.6 ms |
| `Concat` | FAIL | **PASS** | 349.3 ms |
| `Where`（bool 条件为常量） | FAIL | **PASS** | 174.2 ms |
| `Sigmoid` | FAIL | **PASS** | 172.4 ms |
| `Softmax` | FAIL | **PASS** | 173.1 ms |
| `Greater` + `Cast` | FAIL | **PASS** | 180.6 ms |
| `Not` + `Cast` | FAIL | **PASS** | 177.3 ms |
| `Control`（纯 `Gemm`，基准） | — | **PASS** | 224.9 ms |

**全部 PASS。「7 个算子被拒」的中间结论作废。**

被拒的是**单算子图这一形式** —— 只含一个 `Sigmoid` 的图被 NPU 秒拒，同一个 `Sigmoid` 夹在两个
`Gemm` 之间则正常编译。推测 NPU/委托层对过于简单的图有「不值得上加速器」的启发式判断。

**结论：encoder 用到的 26 种算子，没有一种是 HiAI 不支持的。算子种类这个变量排除。**

> 记此弯路以免重走：若把那个中间结论直接交付，模型侧会收到一份「去掉 `Transpose`/`Concat`/
> `Softmax`」的待办 —— 而这对 Zipformer 根本改不动，是个死任务。单算子最小用例在这类
> 「加速器是否接受」的判定上**不是可靠的探针**，必须放进有代表性的图里测。

### 5.4 已排除变量汇总

| 变量 | 是否为 `Authentication failed` 的触发条件 | 依据 |
|---|---|---|
| 动态量化算子 | **否** | 去量化后转换成功（第 1 节） |
| 动态形状 | **否** | 静态化 joiner PASS（第 2 节） |
| 已知拒绝算子（`GatherElements`/`LessOrEqual`） | **否** | 10-08 已重写，`residualRefusedOperators: {}` |
| 模型体量 | **否** | encoder 压到 156 MB（低于 201 MB 通过线）仍 FAIL（第 4 节） |
| 输入/输出数量 | **否** | 117/117 合成模型 PASS（5.1） |
| **算子种类** | **否** | encoder 的 26 种算子全部可被接受（5.3） |
| `libhiai_ir_infershape.so` 缺失 | **否** | joiner 同样缺库仍 PASS（2.1） |
| 节点数 | **是一道独立的墙**，但**不解释** `Authentication failed` | 3766 节点合成模型是**进程崩溃**，无错误返回；encoder 是 `status FAIL` + 明确的 `Authentication failed`（两种不同失败） |

**七个结构性变量全部排除。** 已无法用合成模型继续逼近 —— 剩余可能性（图拓扑复杂度、
特定算子组合模式、HiAI 内部的模型规模启发式）不是本地能构造出的探针所能覆盖的。
**定位 `Authentication failed` 需要华为侧说明其抛出条件。**

另有一条本轮确立的方法论教训：**单算子最小用例在「加速器是否接受」的判定上不是可靠探针**
（5.3），任何此类结论都须在有代表性的图中复核。

## 6. 一处需要更正的早前判断

本轮中途我曾判断「int8 模型的 CPU 探测把应用打挂、系统随后卸载了应用，导致实验无法继续」，
并据此展开了一整段关于设备 UDID 与签名白名单的排查。**该判断是错的**：

- 应用**从未被卸载**。事后 `bm dump -n com.amphion.asr.harmony.demo` 正常返回完整信息。
- 当时触发该判断的是一次 `hdc file send -b` 返回 `[Fail][E005101] Invalid bundle name`，
  以及紧随其后一次返回空的 `bm dump -a | grep amphion`。两者均为瞬时现象，重试即恢复。
- 正确做法是重试确认，而非据单次失败下结论并转向排查签名。第 5 节的实验在重试后全部正常完成。

**仍然成立的部分**：本机设备 UDID `E2CB35C30EDE8451255DED4A65144DDB411D14EFBE09FC3B6E9D7F0EFC77F3CA`
确实不在任何现有 profile 的 device-ids 中（8 个 profile 全查，格式已核对为 64 位十六进制、
`device-id-type: udid`）。这只影响**全新安装**；`install -r` 替换已装应用不校验 UDID，故不影响本轮实验。
若将来应用真被卸载，需在 AGC 后台把该 UDID 加入 debug profile（证书与私钥无需更换）。

**另一条确实成立的事实**：int8 权重量化的 encoder 在 **CPU 后端**加载会打挂应用
（`MINDIR_PROBE|BEGIN|runId=eq8cpu` 之后无 `RESULT`/`END`）。权重量化在 CPU 推理需反量化回浮点，
内存翻倍。该产物不能作为 CPU 回退方案。

## 7. 复测后的待办（取代该章 4.4）

该章 4.4 的三条已全部完成且有效，不再是待办。实际待办为三条（第 4/5/6 项）：

| # | 待办 | 状态 | 归属 |
|---|---|---|---|
| 1 | ~~输入/输出数量对照~~ | **已完成，变量排除**（5.1） | — |
| 2 | ~~把 116 个 `cached_*` 合并为 6 个张量~~ | **已否决**。117 输入本身不是问题，该改法无用 | — |
| 3 | ~~逐类排查算子~~ | **已完成，变量排除**（5.3）。26 种算子全部被支持 | — |
| 4 | **定位 `Authentication failed` 的触发条件** | **本轮主要未解项**。七个结构性变量已全部排除，本地探针已用尽；**需华为侧说明其抛出条件**（HiAI 细节日志被 `<private>` 掩码） | 外部（阻塞） |
| 5 | decoder 为何被拒 | 未定位。原以为是 `Clip`/`GreaterOrEqual`/`Gather`，但 `Gather` 实测 PASS（5.3）；`Clip`、`GreaterOrEqual` 未单独验证（不在 encoder 差集内）。converter 转换时报 `Clip param type invalid` 两次，是现有唯一线索 | 本地可做 |
| 6 | 节点数约束：崩溃点在 1536–3766 之间，encoder 恰为 3766 节点 | 未评估。即便第 4 项解决，也可能需要拆图分段执行并核算跨段搬运开销 | 模型导出层 + SDK |

**新增硬约束（两条）**：体量预算 **≤201 MB**（第 3 节）；节点数须低于 1536–3766 之间的崩溃点（5.2）。
即便其余问题全部解决，导出仍须同时满足这两条。

**收益尚未可知**：流式 transducer 每解码一步都要跑 decoder，若 decoder 上不了 NPU，整链路仍需
跨后端搬运数据。且 joiner 上 NPU 后 median 0.819 ms **反而慢于** CPU 的 0.648 ms（3 节点 Gemm
本不该上 NPU）。真实收益只可能来自 encoder，而 encoder 至今未能在 NPU 上构建成功，
**没有任何一组 encoder 的 NPU 延迟数据**。

## 8. 顺带记录的两条事实

- **int8 权重量化的模型不能当 CPU 回退方案**：在 CPU 后端加载即打挂应用（反量化内存翻倍）。
  这也是第 6 节阻塞的起因。后续不应对超大量化模型做 CPU 后端探测。
- **joiner 上 NPU 无收益**：median 0.819 ms vs CPU 0.648 ms。

## 9. 未覆盖

- 任何精度数据。全部探测为零值输入。
- `Authentication failed` 的确切触发条件。
- 把 encoder 拆成多个 ≤201 MB 子图分段上 NPU 的可行性与跨段搬运开销。
- 其他机型。本轮仅 nova 15 / Kirin 8020；该章在 Mate 80 / Kirin 9020 上的结论未用本轮方法复测，
  其第 4 章的归因错误是否同样适用于该机型，未经验证。
- `Authentication failed` 的抛出条件。七个结构性变量排除后，本地已无可用探针。
- decoder 的 `Clip` / `GreaterOrEqual` 未做单算子或三明治验证。
- 按层截取 encoder 子图做二分定位的尝试失败（ONNX `Extractor` 产出的图引用了未包含的中间张量，
  223 节点中 182 个无生产者，无法拓扑排序）。该失败属方法问题，与 NPU 无关，后改用合成模型完成同一目的。

## 10. 产物清单

`.cache/asr-npu-static-probe/`：

| 文件 | 说明 |
|---|---|
| `joiner.static.onnx` / `.ms` | batch 固定为 1 的 joiner，**NPU PASS** |
| `decoder.static.onnx` / `.ms` | batch 固定为 1 的 decoder，NPU FAIL（算子） |
| `enc-frontend.ms` | encoder 前端 59 节点，**NPU PASS** |
| `encoder.npu.ms` | 静态 fp32 encoder 586 MB，NPU FAIL（超限） |
| `encoder.int8w.ms` | 权重量化 encoder 156 MB，NPU FAIL（`Authentication failed`） |
| `synth-{64,128,192,256,320,640}mb.{onnx,ms}` | 体量阶梯对照 |
| `io-io{4,16,32,64,117}.{onnx,ms}` | 输入输出数量阶梯，全部 **NPU PASS** |
| `nd-n{128,512,1536,3766}.{onnx,ms}` | 节点数阶梯；前三者 PASS，3766 使编译器崩溃 |
| `ops/op-*.{onnx,ms}` | 15 个单算子最小用例（5.3），**其 FAIL 结论已被三明治对照推翻** |
| `sand/sd-*.{onnx,ms}` | 8 个「Gemm → 算子 → Gemm」三明治对照，全部 PASS（5.3） |
| `quant8.cfg` | 权重量化配置 |
| `shapes*.txt` | 各组静态输入形状 |

相关：`.cache/asr-encoder-npu/`（10-08 轮的去量化/静态化/算子重写产物与 provenance）。
