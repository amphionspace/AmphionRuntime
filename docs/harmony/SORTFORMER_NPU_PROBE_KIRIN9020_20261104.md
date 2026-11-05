# Sortformer 上 NPU：Kirin 9020 探测结果

- 日期：2026-11-04
- 设备：**HUAWEI Mate 80（VYG-AL30），Kirin 9020**，NPU `NPU_ohos.boot.hardware.kirin9020_v2_0`
- 转换器：MindSpore Lite 2.7.0 `converter_lite`，Linux x86_64，Docker `--platform linux/amd64`
- 探测：Diagnostics Demo 的 `probeMindSporeBackend`（`MindirProbe.ets`）
- 产物：`<scratch>/npu/`

**为什么做这轮**：`ASR_NPU_BLOCKERS.md` 明确声明「仅覆盖 nova 15 / Kirin 8020 一款机型，
Mate 80 / Kirin 9020 未用同方法复测」。手上这台正是未复测的那款。另外
`--diarization-encoder` 自 0.3.26 起标注「Sortformer always runs on the CPU」，
即 Sortformer 从未试过 NPU。

**探测口径**：零值输入，只判「加速器是否接受该图」与延迟。**不含任何精度数据，
PASS 不代表输出正确。**

## 0. 结论

**Sortformer 今天不能上 NPU。** 四个图里两个能上，但它们合计只有 6 MB，
而 encoder 占了绝大部分计算量，被 `Authentication failed` 挡住——与 Kirin 8020 上的
B1 同一个阻塞，**在 9020 上同样复现**。

| 图 | ONNX 体量 / 节点 | 能否转 .ms | NPU | 备注 |
|---|---|---|---|---|
| `pre_encode` | 2.0 MB / 32 | ✅ | **PASS** 中位 3.44 ms | CPU 3.73 ms，NPU 无优势 |
| `speaker_head` | 3.9 MB / 41 | ✅ | **PASS** 中位 2.35 ms | |
| `spkcache_update` | 0.4 MB / 270 | ❌ | — | 算子 **`IsInf`** 不支持 |
| `encoder_layers`（int8） | 66.3 MB / 2855 | ❌ | — | **`DynamicQuantizeLinear`**、**`MatMulInteger`** 不支持 |
| `encoder_layers`（fp32 + 权重量化） | → 84.9 MB | ✅ | **FAIL** | `Authentication failed`，build 1042 ms |
| `encoder_layers`（fp32 原样） | → 276.8 MB | ✅ | **FAIL** | `Authentication failed`，build 188 ms |

## 1. 本轮的新发现

### 1.1 体量被排除得比上一轮更干净

| 模型 | 体量 | NPU | 有 `Authentication failed` |
|---|---|---|---|
| `synth-128mb.ms`（只含 Gemm 的对照件） | **134 MB** | **PASS**（build 882 ms，中位 3.09 ms） | **无** |
| `encoder_wq8.ms`（我们的 encoder） | **84.9 MB** | **FAIL** | **有** |

**对照件比我们的 encoder 大 1.6 倍却能通过。** 上一轮在 8020 上是「156 MB 低于已验证
通过线 201 MB 仍被拒」，本轮更强：**同一台设备上，更大的模型过、更小的我们的模型不过**。
体量不是判别因素，已可彻底排除。

### 1.2 两条此前被当作线索的日志，是无害噪声

旧文档向华为提的问题 2 与问题 3，本轮可以直接回答：

```
MS_LITE: CheckNPUPrefix# strncmp: 10528977252980073605 failed,
         device_name: NPU_ohos.boot.hardware.kirin9020_v2_0
MS_LITE: InitNNCompilation# hiai_foundation is not nullptr,
         current device name prefix is not HIAI_F.
```

**这两行在 PASS 的用例里逐字出现**（`synth-128mb` 通过那次，日志完全相同）。所以：

- **问题 2「`hiai_foundation is nullptr` 是失败的原因还是结果？」** → 两者都不是。9020 上它
  **不是** nullptr（与 8020 相反），且在成功用例里同样出现。与失败无关。
- **问题 3「那个 strncmp 数值在成功构建的用例里是否也出现？」** → **出现，且数值相同。**
  它是设备相关的常量，不是失败标志。

**唯一有判别力的那一行是：**

```
DLSA: Authentication failed, fail to authenticate model.
NNRt: Authentication failed, input model cannot run by npu.
```

`DLSA` 来自 `dllite_service`（日志域 `C02101`），是上一轮记录里**没有**的域。向华为提问时应
直接指向 DLSA 的模型认证条件，不要再纠缠 strncmp 与 hiai_foundation。

### 1.3 节点数崩溃（B2）在 9020 上仍然复现，但不是 Sortformer 的约束

- `nd-n3766.ms`（3766 节点、仅 0.5 MB）：**进程消失**，与 8020 一致。该编译器缺陷未修复。
- 但我们的 encoder 有 **5616 个 ONNX 节点**却没有让进程崩溃，而是走到认证失败。
  说明 `converter_lite` 的算子融合把 `.ms` 的实际节点数压到了崩点以下。
  **B2 不是 Sortformer 的当前约束。**

### 1.4 两个算子级阻塞（本地可解，与 B1 无关）

| 图 | 不支持的算子 | 性质 |
|---|---|---|
| `spkcache_update` | `IsInf` | 单个算子。该图仅 0.4 MB / 270 节点，**留在 CPU 的代价可忽略**，不值得改图 |
| `encoder_layers.int8` | `DynamicQuantizeLinear` × 124、`MatMulInteger` × 124 | ONNX 动态量化方案，MindSpore Lite 的 ONNX 解析器不支持 |

int8 这条**已有绕法且已验证**：用 fp32 图配 `converter_lite` 自带的权重量化
（`quant_type=WEIGHT_QUANT, bit_num=8`），得到 84.9 MB 的 `.ms`，算子干净、转换成功。
所以 int8 算子不是真阻塞，真阻塞仍是 B1。

### 1.5 即便 B1 解决，还有两道独立的工程阻塞

**a) NPU 无延迟优势（至少在能过的两个图上）**

| 图 | NPU 中位 | CPU 中位 |
|---|---|---|
| `pre_encode` | 3.44 ms | 3.73 ms |
| `speaker_head` | 2.35 ms | 未测 |

`pre_encode` 上 NPU 只快 0.29 ms，而 NPU 的 build 开销是 506 ms（CPU 46 ms）。
与上一轮「joiner 上 NPU 反而更慢」的观察一致：**小图上 NPU 没有收益**。
encoder 的 NPU 延迟**仍然没有任何数据**（B5 未解）。

**b) encoder 的输入形状是真动态的**

Sortformer 的 encoder 输入 `feats: [1, ctx_frames, 512]`，而
`ctx_frames = spkcache_len + fifo_len + chunk_len + right_context`，
在一次会话中从首块的 **125** 增长到稳态 **501**（spkcache 188 + fifo 188 + chunk 124 + rc 1）。

NPU 要静态形状。本轮按稳态 501 固定来做探测，这对「接不接受」的判定是有效的，但
**部署时需要另外解决**：补零到 501 会让注意力算到填充区、改变输出；或者前几块走 CPU、
进入稳态后切 NPU，那就要处理两套后端的一致性。**该方案的开销与精度影响均未评估。**

## 2. 可以做和不可以做的

**不要做**（在 B1 解决前都是为未证明可行的路径做工程）：
- 为 `IsInf` 改图（`spkcache_update` 留 CPU 的代价可忽略）
- 拆分 encoder 以绕节点数（B2 已证明不是当前约束）
- 继续压 encoder 体量（体量已彻底排除）

**可以做**：
- 把本轮证据并入对华为的提问。相比上一轮，本轮多了三件可用的材料：
  1. 同设备上「134 MB 过、84.9 MB 的我们不过」的对照，体量已排除
  2. `strncmp` 与 `hiai_foundation` 两条线索被证伪（PASS 用例里同样出现）
  3. 新的日志域 `DLSA`（`dllite_service`）是唯一判别点
- 若要继续本地定位，方向是**按层二分**：逐步减少 Sortformer encoder 的层数并逐个探测，
  找出触发认证失败的最小结构。上一轮在 ASR encoder 上备有 `enc-L1/L2/L4/L8` 变体，
  同样手法可用于 Sortformer，但该工作**本轮未做**。

## 3. 复现

```bash
# 1) 转换（Docker linux/amd64）
#    形状按稳态固定：encoder ctx=501，pre_encode mel=(124+1)*8=1000
converter_lite --fmk=ONNX --modelFile=pre_encode.onnx   --inputShape='mel:1,128,1000' --outputFile=pre_encode
converter_lite --fmk=ONNX --modelFile=speaker_head.onnx --inputShape='enc:1,512,501'  --outputFile=speaker_head
#    encoder 必须用 fp32 + 自带权重量化，int8 图的 ONNX 量化算子不被支持
printf '[common_quant_param]\nquant_type=WEIGHT_QUANT\nbit_num=8\n' > quant8.cfg
converter_lite --fmk=ONNX --modelFile=encoder_layers.onnx --inputShape='feats:1,501,512' \
               --configFile=quant8.cfg --outputFile=encoder_wq8

# 2) 推到沙箱（必须带 -b；只能推到 files 根，建子目录会被拒）
hdc file send -b com.amphion.asr.harmony.demo <x>.ms /data/storage/el2/base/files/<x>.ms

# 3) 探测
hdc shell aa start -a EntryAbility -b com.amphion.asr.harmony.demo \
  --ps mindirProbe true --ps mindirProbeRunId <id> \
  --ps mindirProbeModel /data/storage/el2/base/files/<x>.ms \
  --ps mindirProbeBackend npu --ps mindirProbeIterations 3
hdc shell "hilog -x | grep MINDIR_PROBE"
```

踩过的坑：
- `converter_lite` 只有 Linux x86_64 版，macOS 上必须走 Docker `--platform linux/amd64`
- 沙箱写入要 `hdc file send -b <bundle>`；`hdc shell mkdir` 在沙箱内会 `Permission denied`，
  且推到不存在的子目录会失败，所以直接推 `files` 根
- 探针的 `--ps` 不接受空值
