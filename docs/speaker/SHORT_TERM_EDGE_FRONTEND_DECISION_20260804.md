# 短期重叠语音前端：端侧算力与接入决策（2026-08-04）

> 2026-08-05 后续状态：Conv-TasNet 虽通过 Mate 80 小样本资源/内容门，但在 60 个 speaker-disjoint
> other-only test 中产生 8 个非空 false rescue，当前无训练 C2/C3 路线已停止。C1 `1000/300 ms` 也只
> 保留为 prototype；绝对 PCM hop 调度及冻结集重放已完成，分帧门通过但模型层严格门仍失败，未升级
> 为正式默认值。后续 600 ms buffered-tail 又以 `25.21%` 目标截断换取拖尾下降，C1 无训练默认路线
> 同样关闭。

## 1. 问题重述

短期不训练新模型时，需要回答的不是“哪台手机理论上能装下某个 checkpoint”，而是：在现有
Harmony `ZH_EN ASR + ERes2Net + Speaker VAD` 已经常驻的前提下，哪个公开前端还能在目标设备上以
可接受的包体、内存、CPU 和等待时间运行，并且不破坏现有 SDK 生命周期契约。

本报告把判断分为三档：

- **已满足**：同一 Harmony 真机、同一 SDK 交付栈已有资源与业务结果。
- **高概率满足，需真机验证**：主机实验、模型规模和运行时算子都给出正信号，但没有候选 ONNX 在目标
  真机上的 create-session、RTF、RSS 数据。
- **不满足**：即使算法有正信号，现有模型形态、资源、延迟或产品语义中至少一项已经构成硬阻断。

“高概率满足”不等于可以交付。尤其不能把 Apple M5 的 RTF 按一个固定倍率换算成 Harmony ARM CPU；
没有目标真机数据时，本文不作这种伪精确外推。

## 2. 当前真机和交付预算基线

### 2.1 已实测硬件

2026-08-04 通过 HDC 读取当前设备：

- 型号：`HUAWEI Mate 80`，产品号 `VYG-AL30`。
- 系统：`6.1.0.135(SP8C00E120R5P7)`，`arm64-v8a`。
- `/proc/meminfo`：`MemTotal=11,892,832 kB`，即约 11.34 GiB，属于 12 GB 档。
- 压力工具从系统采样得到 `logical_cpus=12`。系统不允许普通 shell 读取 `/proc/cpuinfo`，因此本文不猜测
  大小核型号、频率或 NPU 规格。

### 2.2 现有 0.2.9 的 CPU/RSS

严格短窗口真机报告：
[`20260804-143605-voiceprint-customer-cases-short-window-b6f7e4ce/report.json`](../../delivery/harmony-dingqiao/build/device-stress/20260804-143605-voiceprint-customer-cases-short-window-b6f7e4ce/report.json)

| 指标 | `Speaker VAD 1000/300 ms` 实测 |
| --- | ---: |
| RSS head / tail / peak | 525.65 / 549.71 / **552.41 MiB** |
| 平均 / p95 / 峰值单核等价 CPU | 109.64% / 155.63% / 216.69% |
| 平均 / p95 整机容量 | 9.14% / 12.97% |
| 线程 head / tail | 46 / 45 |
| 设备与 SDK | Mate 80 / 0.2.9 / arm64-v8a |

原 `1500/500 ms` 同类客户样例报告：
[`20260804-142901-voiceprint-customer-cases-e005914a/report.json`](../../delivery/harmony-dingqiao/build/device-stress/20260804-142901-voiceprint-customer-cases-e005914a/report.json)

| 指标 | `Speaker VAD 1500/500 ms` 实测 |
| --- | ---: |
| RSS head / tail / peak | 510.45 / 532.86 / **536.11 MiB** |
| 平均 / p95 / 峰值单核等价 CPU | 111.39% / 161.78% / 182.35% |
| 平均 / p95 整机容量 | 9.28% / 13.48% |

两个运行的时长和内存初态不同，不能把 16.3 MiB 的峰值差直接归因于窗口变化；能成立的结论是：
`1000/300 ms` 没有观察到 CPU 抬升，现有真机资源门通过。业务上它让 C1 通过，但 C2/C3 仍失败。

### 2.3 包体和已有模型

- 0.2.9 客户样例实验 HAP：`339,029,913 bytes`（约 323.3 MiB），记录在上述 `142901` report。
- 当前本地 debug HAP：`338,845,631 bytes`（约 323.1 MiB）。它是 demo 容器，不应当冒充客户 release
  包体，但能说明再增加 80～280 MB FP32 模型不是小变化。
- 基础 `amphion_asr.har`：约 218.9 MB；`amphion_dingqiao.har`：约 36.8 MB。
- Harmony 模型资源：`ZH_EN + punctuation + VAD` 约 262 MiB；内置 ERes2Net 约 38 MiB。
- `libonnxruntime.so` 约 12 MiB，已有包无需为新 ONNX 再带第二份 ORT。

这些数值是构建产物或 report 实测；HAP/HAR 之间存在依赖和重复打包关系，不能简单相加得到最终客户
安装占用。

## 3. Harmony ONNX Runtime 能力边界

### 3.1 当前是完整 CPU ORT，不是 minimal ORT

仓库 [`asr/tools/04_build_harmony_so.sh`](../../asr/tools/04_build_harmony_so.sh) 固定使用 OHOS
ONNX Runtime 1.16.3 预编译库。当前 `libonnxruntime.so`：

- 能直接加载内置 `eres2net.onnx` 和 Silero VAD ONNX；官方说明 basic minimal build 只能加载 ORT
  format，不能加载 ONNX。因此现有库不是 basic minimal build。
- 二进制含完整图优化、CPU Execution Provider、ONNX schema 和诸如 `ConvTranspose`、`Gemm`、
  `LayerNormalization`、`ReduceMean`、`Range`、`Tile` 等注册信息。
- 上游当前 Harmony 构建脚本明确使用 `onnxruntime_MINIMAL_BUILD=OFF`、
  `onnxruntime_REDUCED_OPS_BUILD=OFF`、`onnxruntime_DISABLE_CONTRIB_OPS=OFF`。一手来源：
  [csukuangfj/onnxruntime-libs Harmony 构建工作流](https://github.com/csukuangfj/onnxruntime-libs/blob/master/.github/workflows/harmony-os-shared.yaml)。

严格边界：1.16.3 release 的历史工作流没有保存在对应 tag 中，因此“release 二进制与今天脚本每个 flag
逐项相同”不是已证明事实。候选进入 HAP 前仍必须用**实际交付的** `libonnxruntime.so` 在设备上创建
session；仅凭字符串扫描不能证明某个图一定可运行。微软官方也把 reduced-op/minimal build 定义为显式
构建选项，见 [Custom build](https://onnxruntime.ai/docs/build/custom.html) 和
[Reduced operator config](https://onnxruntime.ai/docs/reference/operators/reduced-operator-config-file.html)。

### 3.2 当前没有 NPU/GPU 加速

当前 Harmony 构建缓存和上游构建路径均关闭 NNAPI、XNNPACK、ACL/ArmNN、GPU 等 EP，实际使用 CPU
Execution Provider。因此本文的“端侧可跑”全部指 ARM CPU；Mate 80 即使有 NPU，也不会自动参与。
将模型改成 FP16 同样不会自动得到加速：当前 OHOS ORT 构建路径明确关闭/剔除了 CPU FP16/BF16
MLAS 路径。

### 3.3 候选图的主要风险

| 候选 | 预计主要 ONNX 算子 | 当前 ORT 风险 | 动态形状风险 |
| --- | --- | --- | --- |
| RE-SepFormer 固定 4 秒 | Conv/ConvTranspose、MatMul/Gemm、Softmax、LayerNormalization/Reduce、Reshape/Slice/Gather/Pad | 已在 macOS ORT 1.16.3 通过；设备库含关键 schema，但尚未在设备 create-session | 固定 `1×32000` 已把主要动态时间轴冻结；低于原始动态导出 |
| SpeechBrain SepFormer | 上述算子，但 Transformer 更大、层数更多 | 无本项目 ONNX 导出和设备证据 | 原始 PyTorch 接口接受变长；直接动态导出风险高 |
| Asteroid Conv-TasNet | Conv、dilated/depthwise Conv、ConvTranspose、PReLU、ReduceMean、Sqrt/Div、Reshape/Pad/Slice | 固定 2 秒图已在实际交付 ARM ORT 1.16.3 完成 create-session 和推理 | 固定 `1×32000` 已冻结时间轴 |
| WeSep BSRNN+ECAPA | STFT/ISTFT、complex 拆分、双向 LSTM、GroupNorm、Mel frontend、动态 subband slicing | 组合图复杂，官方路径是 TorchScript/LibTorch，不是 ONNX | 最高；输入长度、STFT 帧数和循环切带都随时间变化 |

WeSep 官方实现可直接看到 `torch.stft/istft`、双向 LSTM、动态 padding 和分带逻辑：
[wesep/models/bsrnn.py](https://github.com/wenet-e2e/wesep/blob/master/wesep/models/bsrnn.py)。

## 4. 候选端侧算力分级

### 4.1 决策矩阵

| 候选 | 已知资源/效果 | 当前 Mate 80（12 GB/12 logical CPUs） | 8 GB 高端机 | 中端/≤6 GB | 短期结论 |
| --- | --- | --- | --- | --- | --- |
| 现有 Speaker VAD `1000/300` | 真机 peak 552 MiB；平均约 1.10 核；absolute 与 buffered-tail 严格门均 FAIL | **算力满足，业务门未满足** | 未测，但没有新增模型 | 未测 | **仅研究证据；无训练路线关闭** |
| WeSep BSRNN+ECAPA | 27.63M 推理参数；checkpoint 282.6 MB；M5 RTF 0.302～0.322；进程 peak RSS 1.94 GB；C1～C3 PASS | 内存物理上装得下，但 Harmony runtime/ONNX/延迟均不满足 | 不建议 | 不满足 | **不满足短期交付** |
| SpeechBrain SepFormer 16 kHz | 官方 PyTorch/GPU 路径；mask network 约 113 MB；无本项目 ONNX/RTF/RSS；非 target-conditioned | 可能装得下，但没有可交付证据 | 不建议 | 不满足 | **不满足；不继续投入** |
| RE-SepFormer 固定 4 秒 ONNX + ERes2Net 选流 | ONNX 83.58 MB；M5 ORT 4 线程中位 RTF 0.0276；独立进程 peak RSS 429.65 MB；C1～C3 PASS | 资源可能可跑，但同为无 target identity 的盲分离 | 内存可能可跑，但无证据 | 不建议 | **开放集根因相同，不再作为回退** |
| Conv-TasNet 固定 2 秒 ONNX + ERes2Net 逐块选流 | ONNX 20.15 MB；Mate 80 中位 RTF 0.144～0.162、最差 p95 RTF 0.295；进程 peak RSS 519.4 MiB；桌面完整分块 C1～C3 PASS | **ARM CPU 资源门满足，开放集业务门失败** | 不再扩展 | 不再扩展 | **无训练路线停止；仅保留研究证据** |

分级里的“物理上装得下”不代表产品可用。现有基线 peak RSS 约 552 MiB；如果把 RE-SepFormer 主机
独立进程的 430 MiB 粗略视为上界线索，总进程很可能进入约 0.8～1.0 GiB 档。共享 ORT、allocator 和
平台差异使它不能直接相加，但足以说明该方案应先限定 Mate 80 这类 12 GB 高端设备，不应直接宣称覆盖
8 GB 或中端机。

### 4.2 Conv-TasNet 已通过的门和仍未通过的门

Asteroid 官方模型卡给出 16 kHz、512 filters、`8 blocks × 3 repeats`；官方实现每个 block 含 1×1
卷积、512 通道 depthwise dilated convolution、residual/skip 1×1 卷积和 global layer norm。它的权重小，
但中间特征和逐帧卷积仍可能吃 CPU，必须以端上 RTF/RSS 而不是文件大小做决定。一手来源：

- [官方模型卡](https://huggingface.co/JorisCos/ConvTasNet_Libri2Mix_sepclean_16k)
- [Asteroid ConvTasNet 实现](https://github.com/asteroid-team/asteroid/blob/master/asteroid/models/conv_tasnet.py)
- [Asteroid TDConvNet 实现](https://github.com/asteroid-team/asteroid/blob/master/asteroid/masknn/convolutional.py)

本轮已完成此前缺失的内容门和导出门：整段模型以及“2 秒块 + 0.5 秒交叠 + 每块 ERes2Net 选流 +
交叉淡化”都使 C1～C3 逐条满足“含上海、无你好”。C3 分块文本首字从“我”退化为“不”，因此这是
严格回归门 PASS，不是准确率无损。固定 `1×32000` ONNX 为 `20,147,162 bytes`，SHA-256
`f5b040d383007319c67bd2e1862cc6b6b2ac9bef5101581f30c0c00200b3b7ab`。与 Harmony 相同的桌面 ORT
1.16.3 在关闭 arena/memory pattern 后成功加载、推理，4 线程中位 RTF `0.0583`，进程最大 RSS
`267 MB`。随后 Mate 80 真机已用实际交付 ORT 1.16.3 完成三条资源门：中位 RTF
`0.144～0.162`、最差 p95 RTF `0.295`、进程 peak RSS `519.4 MiB`，并保持三轮 ASR 生命周期。
这证明当前设备的 ARM CPU 原始计算门通过；完整端侧选流/拼接/重识别仍未完成。

仍有一个资产一致性风险：本机已下载 checkpoint
`~/.cache/torch/asteroid/models--JorisCos--ConvTasNet_Libri2Mix_sepclean_16k/blobs/8d97f012f7b2f22bb79cb0d0983a7ba27a52c1796ee3f63cbf25b4d28630adce`
大小为 `20,394,640 bytes`，其序列化 `model_args.sample_rate` 实际为 `8000`，而模型卡写 `16000`。
直接以 16 kHz 客户输入运行已通过三条内容门，但在确认这是上游历史序列化字段错误还是权重实际按
8 kHz 构造前，不能把它作为已澄清的 16 kHz 生产资产。模型卡当前 metadata 为 CC BY-SA 4.0，历史正文
还出现过 3.0/4.0 不一致；闭源客户交付必须先确认 checkpoint 与派生 ONNX 的许可义务。

### 4.3 RE-SepFormer 和标准 SepFormer 不是同一个端侧结论

本项目已经跑通的是较小的 **RE-SepFormer 8 kHz、固定 4 秒 ONNX**，不是 16 kHz 标准 SepFormer。
官方 RE-SepFormer 模型卡明确要求 8 kHz、单通道，且不保证跨数据集表现：
[speechbrain/resepformer-wsj02mix](https://huggingface.co/speechbrain/resepformer-wsj02mix)。

标准 16 kHz SepFormer 官方模型是 WHAMR! noisy/reverb 英语域，官方用法仍是 PyTorch，甚至专列 GPU
推理入口，并没有 ONNX/端侧保证：
[speechbrain/sepformer-whamr16k](https://huggingface.co/speechbrain/sepformer-whamr16k)。
因此标准 SepFormer 不能借用 RE-SepFormer 的 83.6 MB、RTF 0.0276 和 430 MB RSS 数据。

## 5. 短期最小接入形态

### 5.1 C1 现有能力边界

对明确属于“目标人说完、其他人才接话”的场景，`1000/300 ms` 只保留为 prototype 和已知 C1 单例证据，
不能作为立即交付或全局默认策略。它复用当前 ERes2Net，不新增模型、runtime 或内存边界，且 hop 调度
已满足分帧无关；但独立 target→other absolute replay 仍出现目标截断、非目标文本和 anchor 误判。

600 ms 缓冲提交/尾部回退已完成冻结重放：非目标文本降到 `1/960`，但目标截断升到 `242/960`，
短/中/长目标桶均失败。因此该候选也不进入 SDK；C2/C3 是同时重叠，更不应被宣传为这一策略可以解决。

### 5.2 高端机应急：固定块分离作为 opt-in 增强模式

若业务必须短期处理 C2/C3，最小改动不是把 PyTorch 或 LibTorch 搬进 HAR，而是：

1. 保留当前录音 PCM；只在显式开启“重叠增强”时进入新路径。
2. 使用一个固定 2～4 秒、batch=1 的 ONNX，两路输出；禁止动态时间维和 Python runtime。
3. 复用已有 `libonnxruntime.so`，在独立 worker 中运行，不占用 ASR 的 4 个 ORT worker；初始先给 separator
   2 个 intra-op threads，再按真机数据调，而不是一开始抢满 12 核。
4. 使用当前 enrollment ERes2Net 对每块两路重新评分，不能在首块后固定流序号；低置信块静音并用交叠
   淡化抑制边界跳变。C3 已观察到流序号换位，后续若引入 hysteresis 必须以该用例证明不会跟错流。
5. 分离结果重新送入现有 ZH_EN ASR；生命周期对外仍由原 session 状态机驱动，separator 失败时返回原始
   ASR 结果或明确的增强失败，不能伪造 `final/isLast/onComplete`。

在候选选择上，先做 Conv-TasNet，不再先做 RE-SepFormer：前者现在已经通过同一 C1～C3 内容门和
ORT 1.16.3 桌面兼容门，同时把模型从 83.6 MB 降到 20.1 MB、look-ahead 从 4 秒降到 2 秒。若许可审查
否决 CC BY-SA checkpoint，再回退到 Apache-2.0 的 RE-SepFormer 高端机 PoC。

### 5.3 不采用的短期形态

- 不集成 WeSep/PyTorch/LibTorch：它会引入新的大 runtime、约 283 MB checkpoint 和已实测 1.94 GB
  主机峰值，同时仍是双向离线模型。
- 不集成标准 SepFormer：没有比已跑通 RE-SepFormer 更短的证据链，且更大。
- 不依赖 NPU：当前 ORT 没有对应 EP；接 NPU 是独立平台项目，不是“换一个模型文件”。
- 不把盲分离包装成真正 TSE：RE-SepFormer/Conv-TasNet 都没有 enrollment conditioning；它们只是在两路
  输出后用 ERes2Net 选流，target absent、三人、跨块换序仍是已知失败域。

## 6. 下一轮完整链路真机实验与停止条件

### A. Conv-TasNet worker 按需救援门（优先）

原始 ARM CPU 资源门已经通过。下一轮只回答“独立 worker 内的逐块分离、ERes2Net 选流、拼接和重识别
能否在 C1～C3 完整波形上成立”。测试载体仍只构建和安装一个 `ZH_EN` 诊断 HAP，不改 SDK 默认行为。

必须记录：

- worker 往返、冷/热 session 创建时间；2 秒块 p50/p95 RTF；separator 与重识别时 CPU；
- 基线、加载后、连续 30 轮后的 RSS/HWM/线程；
- C1/C2/C3 严格“含上海、无你好”；
- target-only、target-absent 和 other-only 不得被错误救援；C3 的一字退化必须如实保留；
- hilog 不得出现 `THREAD_BLOCK_3S/6S`；
- `finish` 前 `isLast=0`，正常结束恰好一次 last/complete，下一 session 可恢复。

停止条件：任一出现 p95 RTF `>=0.35`、相对 0.2.9 基线增量 peak RSS `>=250 MiB`、worker 卡顿/退出、
三例任一业务失败、target-absent 误救援或生命周期错误，则不再对该模型做参数搜索，转 B 或只保留
C1 策略。这是本次高端机应急门，不是全产品长期预算。

### B. RE-SepFormer 许可回退门（已被开放集根因否决）

该回退原本只处理 Conv-TasNet 许可问题。2026-08-05 开放集归因确认 target-absent 错误来自当前
ERes2Net 工作点接受原始非目标语音，而 RE-SepFormer 同样是无 enrollment identity 的盲分离，不能
规避根因。因此不再把它放入临时 HAP；历史资源上限只保留为已执行实验记录。

## 7. 最终短期建议

1. **今天没有新的默认策略可交付：**C1 `1000/300 ms` 已满足算力和分帧门，但 absolute 与
   buffered-tail replay 均未通过业务门；C1 无训练正式默认路线关闭。
2. **C2/C3 无训练路径停止：**60 个 other-only test 已出现 8 个非空 false rescue；不再运行
   Conv-TasNet 阈值搜索、稳压或真机扩身份，保留原始 ASR/fallback。
3. **RE-SepFormer 不作为许可回退：**它同样没有 target identity，无法修复已定位的开放集根因。
4. **公开大模型只保留 reference：**Conv-TasNet、WeSep、RE-SepFormer 和标准 SepFormer 只证明内容
   可恢复；下一交付候选必须是 enrollment-conditioned、小型 causal TSE。

对应的主机效果、哈希、RTF 和逐例文本见
[`VOICEPRINT_OVERLAP_FRONTEND_EXPERIMENT_20260804.md`](VOICEPRINT_OVERLAP_FRONTEND_EXPERIMENT_20260804.md)。
真机原始计算、RSS、生命周期和主线程失败根因见
[`CONVTASNET_HARMONY_DEVICE_PILOT_20260804.md`](CONVTASNET_HARMONY_DEVICE_PILOT_20260804.md)。
