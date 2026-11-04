---
状态: 立项，角色分离模型本身的跨机型验证被阻塞；理论分析完成，一个关键算子风险已用合成探针验证排除
影响: 后续"从 Mate 60 起多颗麒麟芯片 + 安卓/鸿蒙双端"兼容性工作的起点与方法依据
---

# Sortformer 角色分离模型跨机型 / 跨芯片验证（2026-11-03 立项）

本文记录三件事：Sortformer 本身为什么今天还验证不了、能从已知信息推出什么结论、以及一个
关键风险点已经用合成探针方法验证过的真实结果。不含任何编造或外推成真实数据的内容——凡标
"理论推断"的地方都未经真机验证，不得当作结论使用。

## 一、硬阻塞：Sortformer 运行时资产不可达

厂商交付包 `sortformer-66M-4spk-delivery-v1（1）.zip` 不在任何本机可达位置：本地全盘（含
`.cache`、`.local-archive`、git 历史、stash）、项目对象存储归档索引
（`delivery/published-artifact-archives.json`）均无记录；0.3.26 鸿蒙从未归档到 COS，因为它
本来就还是未发布候选。**这不是没找到，是这批资产本来就"不进 Git"，只能靠外部交付包或已组
包机器恢复。** 解除方式二选一：

1. 找到当初收到交付包的渠道重新索取；
2. 找到跑过 `pack_dingqiao_customer_delivery.sh` / 鸿蒙 0.3.26 组包的那台机器，模型文件应该
   解压在那台机器本地的 `shared/models/asr/dingqiao/sortformer-66M-4spk/`。

在此之前，Sortformer 真实权重相关的任何真机验证（精度、延迟、工作集占用）都做不了，与机型
无关——不只是新机型测不了，现有的 nova 15 / nova 14 Pro 也一样测不了。

## 二、已有的间接方法：跨芯片探针方法学已经预演过一次

因为缺 Sortformer 资产，先用已经完整验证过的 **ASR encoder FP32 五段模型**（真实生产模型，
不是替代品）在 nova 14 Pro（MIA-AL00，芯片型号未知，与 nova 15 的 Kirin 8020 不同）上跑了一
遍同样的探针流程，目的是检验"跨芯片验证"这套方法本身是否成立，不是验证 Sortformer。

### 结果

| 项 | nova 15（Kirin 8020） | nova 14 Pro（未知芯片） |
|---|---|---|
| NNRt 设备枚举 | `NPU_ohos.boot.hardware.kirin8020_v2_0, HIAI_F` | 只有 `HIAI_F` |
| ASR encoder 五段（96~146 MiB/段，与 nova 15 完全相同的 .om 文件） | 全部 PASS | **全部 PASS**（build 388~875 ms） |

两台设备的 NNRt 设备拓扑确实不同，说明这次真的拿到了跨芯片信号，不是同一颗芯片的重复样本。
五段真实模型在拓扑不同的芯片上全部被接受——**结构性接受度这一层，换芯片没有直接报废**，这
是一个真实的正面信号，但只到"装不装得进去"这一层。

### 发现的限制：延迟/精度这一层测不了，是工具版本问题，不是芯片问题

nova 14 Pro 上装的探针程序是更早期的迭代版本，不支持真实输入回灌（`.in`/`.out`）、也不支持
五段接力模式（split-seq）——本地留存的探针源码快照文件名本身就是证据：
`om_probe.cpp.before_io`、`.before_seq`、`.before_split`，这些能力是后来才加的。该探针代码的
最终版本既不在 git 也不在 stash，本机也没有现成安装包可以直接搬过去重装；要补齐，需要重新
走一遍 DevEco 构建安装，是一项独立可排期的工程任务，不依赖任何外部输入。

## 三、Sortformer 的理论分析（全部基于仓库内真实证据，推断部分已标注）

### 3.1 体积：大概率不需要像 ASR encoder 那样拆段（较强依据）

`delivery/harmony-dingqiao/delivery/sortformer_diarization_v1.json` 记录的交付清单真实字节数
（不需要本地有权重文件即可读取）：

| 子图 | 体积 |
|---|---:|
| `pre_encode.ort` | 2.11 MB |
| `encoder_layers.int8.ort` | 69.97 MB |
| `speaker_head.ort` | 4.11 MB |
| `spkcache_update.ort` | 0.54 MB |
| 四张图合计 | ≈76.7 MB |

Sortformer 本来就拆成了四个独立子图，最大的 encoder 只有 70 MB。对照这次在 Kirin 8020 上实
测的单模型工作集上限 **162~168 MiB**，每张图都有一倍以上余量。**理论推断**：大概率不需要再
做"按层拆段"。但这个上限只在 Kirin 8020 上测过，换芯片后会不会是另一个数字，没有验证。

### 3.2 张量形状：比 ASR encoder 更不容易踩 cube 利用率的坑（中等依据，方向性推断）

ASR encoder 跑不动的真因是流式步长太细——每步只处理 `T=8` 帧，16×16 的计算块只填了 1/32（
见 `docs/harmony/ASR_NPU_BLOCKERS.md`）。Sortformer 的流式参数不是这个量级：`chunkLen: 124`、
`spkcacheLen: 188`、`fifoLen: 188`（同一份 manifest），主干每次处理的时间维度在 124~188 这个
量级，比 ASR encoder 的 `T=8` 大一到两个数量级。按"形状越方、cube 填得越满"这条已验证规律，
**理论推断**：Sortformer 落入"填不满 cube"陷阱的概率比 ASR encoder 小。未经实测。

### 3.3 算子：已知一个真实风险点，已用合成探针验证排除（强依据，见第四节）

`spkcache_update.onnx` 里有一个 `Shape→Gather→TopK` 的动态 K 模式（`/TopK_3` 的 K 由
`Gather(Shape(/Where_13_output_0), [1])` 算出，完整记录见
`asr/tools/models/patch_sortformer_spkcache_topk.py`）。这个模式已经在不同 ONNX Runtime 版本
间炸过一次——1.16.3（鸿蒙用）能读，1.24.3（安卓 sherpa 预构建）报
`ShapeInferenceError`，靠把 K 换成编译期常量解决。`TopK` 这个算子此前给 ASR encoder 做的 26
种算子逐一排除测试里从未出现过，是真正没测过的新变量。**第四节已经把这个风险点用合成探针
测过，结果是正面的。**

### 3.4 跨芯片先例：有，但不是同一类架构（中等依据）

`docs/speaker/DIARIZATION_NPU_THERMAL_MATRIX_20261008.md`（Mate 80，**Kirin 9020**）记录过：
旧的 Community/wespeaker 角色 encoder（卷积密集型）成功跑上 NPU（在线 MindSpore Lite 路径，
`NPU_ohos.boot.hardware.kirin9020_v2_0`），识别文本逐字节相同，角色标签一致率 99.2%~100%，
16/30/60 分钟各降温 2~2.8°C。这证明"角色分离类模型上 Kirin 9020 NPU"有先例，且走在线路径也
没有撞上 ASR encoder 那个 `Authentication failed`。但 wespeaker 是卷积密集型（已验证的 NPU
甜点），Sortformer 是 attention + 动态形状密集型，架构上离 wespeaker 更远、离 ASR encoder（
已知难伺候）更近。**理论推断**：这条先例只能说明芯片和运行时支持这类工作，不能说明 Sortformer
这张具体的图也会被同样接受。

### 3.5 不同麒麟芯片设备拓扑已知不一致（实测事实）

| 设备 | 芯片 | NNRt 设备枚举 | 状态 |
|---|---|---|---|
| nova 15（PSN-AL00） | Kirin 8020 | `NPU_ohos.boot.hardware.kirin8020_v2_0, HIAI_F` | 已测（ASR encoder） |
| nova 14 Pro（MIA-AL00） | 未知，与 8020 不同 | 只有 `HIAI_F` | 已测（ASR encoder，探针版本旧，延迟/精度测不了） |
| Mate 80（VYG-AL30） | Kirin 9020 | `NPU_ohos.boot.hardware.kirin9020_v2_0` | 已测（旧 wespeaker 模型，10-08） |
| Mate 70 Pro（PLR-AL00） | 推测同代 | 未测 NPU | 仓库有一次非 NPU 的真机记录（SDK lifecycle），项目借到过这台机型 |
| Mate 60 | Kirin 9000s | 无任何记录 | 全新，需要先借到设备 |
| "最新机型" | 待确认具体型号 | 无任何记录 | 需要用户明确是哪款 |

三种不同枚举形态，说明换芯片不是换个数字那么简单，连设备拓扑都可能不同。**理论分析能排优
先级、圈风险点，不能替代每颗芯片的实测。**

## 四、合成探针实验：验证了动态 K 这个真实风险点（已执行，真实结果）

方法沿用 ASR encoder 调研时已验证过的方式（`docs/harmony/ASR_NPU_BLOCKERS.md` B2/B3 体量阶梯
与算子三明治对照）：不需要真实权重，只要真实形状和真实算子类型，配合随机权重，照样能测出
"编译器收不收、建不建得起来、算得对不对"。

### 实验设计

复刻 `spkcache_update.onnx` 里真实的 `Shape→Gather→TopK` 模式，输入形状 `[1, 188]`（即真实
的 `spkcacheLen`），K 取 188（与真实图一致——`patch_sortformer_spkcache_topk.py` 的分析已指出
真实场景里 K 在编译期就等于 188，这不是简化，是忠实复现）。做两个变体对照：

1. `topk_dynk`：K 由 `Shape(scores) → Gather(idx=1)` 动态算出（真实图的原始写法）
2. `topk_constk`：K 直接是常量 188（Android 侧已经用的改法）

OMG 转换、推到 nova 15 真机（Kirin 8020，`.om/HIAI_F`）运行，并用随机数种子固定输入，和宿主
`numpy` 的全排序结果逐值比对。

### 结果

| 变体 | OMG 转换 | 设备 build | 设备运行 | 数值正确性 |
|---|---|---:|---|---|
| `topk_dynk`（动态 K） | 通过 | 34.2 ms | PASS | 与宿主逐值一致 |
| `topk_constk`（常量 K） | 通过 | 5.2 ms | PASS | 与宿主逐值一致 |

### 结论

**动态 K 的 `Shape→Gather→TopK` 模式，在 `.om/HIAI_F` 这条离线路径上，Kirin 8020 能正确接受
并算对，不需要像安卓那样预先做常量折叠。** 这排除了第 3.3 节标注的那个真实风险点——至少在
这一颗芯片、这一个孤立算子模式上是这样。

**边界**：这只是一个孤立算子的合成验证，不是完整 Sortformer 图的验证——真实图里这个模式和
其他算子的组合方式、上下游张量形状是否逐一一致，没有测；也只测了 Kirin 8020 一颗芯片。不能
据此断言"Sortformer 整图能上 NPU"，只能说"这一个已知风险点不再是已知阻塞"。

## 五、安卓 vs 鸿蒙：不是同一个验证面

"兼容对应的安卓和鸿蒙系统"这句话涵盖两个完全不同的验证面：

- **鸿蒙路径**：NNRt → `HIAI_F`，本文第二、四节用的就是这条链路，换机型主要是换芯片，瓶颈
  模式（工作集上限、cube 利用率、算子接受度）大概率还在，但具体数字要重测。
- **安卓路径**：现在安卓的 Sortformer 完全跑在 CPU（sherpa 预编译 ORT 1.24.3），代码里没有
  任何 NNAPI 或厂商 NPU 代理调用——这条线上 NPU 加速**还没有开始做**，不是"换机型重测"，是
  "从零立项"。工作量和鸿蒙这条线不是一个量级，需要单独排期。

## 六、下一步（按能否现在开始排序）

| 优先级 | 动作 | 是否需要等外部输入 |
|---|---|---|
| 1 | 重装 nova 14 Pro 上的探针（补齐 split-seq + 真实输入支持），把 ASR encoder 的跨芯片数据补完整 | 不需要，现在可排期 |
| 2 | 找到 Sortformer 交付包或已组包机器 | 需要用户提供渠道/机器信息 |
| 3 | 拿到资产后，先在 nova 15（已验证方法最完整）上跑 Sortformer 真机基线 | 依赖 2 |
| 4 | 借到 Mate 60（Kirin 9000s），走一遍同样的探针流程 | 需要先借到设备 |
| 5 | 确认"最新机型"具体型号，排入设备矩阵 | 需要用户明确型号 |
| 6 | 安卓 NPU 兼容性单独立项，与鸿蒙这条线分开排期 | 需要用户确认是否纳入本轮范围 |

## 七、关联文档

- `docs/harmony/ASR_NPU_BLOCKERS.md`、`docs/harmony/ASR_NPU_RETEST_20261023.md` —— ASR encoder
  的阻塞点清单与方法学来源
- `docs/speaker/DIARIZATION_NPU_THERMAL_MATRIX_20261008.md` —— Kirin 9020 上旧 wespeaker 角色
  encoder 的真机先例
- `docs/speaker/SORTFORMER_ANDROID_MODEL_DIVERGENCE_20261030.md` —— 动态 K 风险点的最初发现
  （安卓 ORT 版本差异）
- `delivery/harmony-dingqiao/delivery/sortformer_diarization_v1.json` —— 本文第 3.1 节体积数据
  的来源
- 飞书：《ASR Encoder 上麒麟 NPU：端到端验证与归因结论》
  https://ccnuebbmik1f.feishu.cn/docx/IuFBdPOLloazXbxbbzRcwBrKnah
