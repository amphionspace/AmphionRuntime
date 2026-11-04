---
状态: Sortformer 运行时资产已恢复并逐文件 SHA-256 核对、CPU 端到端真实跑通；理论分析完成，
一个关键算子风险已用合成探针验证排除；NPU 转换所需的预转换 ONNX 源图仍未找到
影响: 后续"从 Mate 60 起多颗麒麟芯片 + 安卓/鸿蒙双端"兼容性工作的起点与方法依据
---

# Sortformer 角色分离模型跨机型 / 跨芯片验证（2026-11-03 立项，11-04 资产恢复）

本文记录四件事：Sortformer 运行时资产如何从邮箱附件里找回并验证、能从已知信息推出什么理论
结论、一个关键风险点已经用合成探针方法验证过的真实结果、以及资产恢复后新做的真实加载验证。
不含任何编造或外推成真实数据的内容——凡标"理论推断"的地方都未经真机验证，不得当作结论使用。

## 一、运行时资产：已从内部邮箱附件恢复，逐文件哈希核对通过（11-04 更新）

厂商交付包 `sortformer-66M-4spk-delivery-v1（1）.zip` 本身仍未找到——本地全盘（含 `.cache`、
`.local-archive`、git 历史、stash）、项目对象存储归档索引均无记录，0.3.26 鸿蒙也从未归档到
COS。但**运行时资产已经用另一条路径恢复**：

1. 用飞书 CLI 搜索邮箱，顺着 `HarmonyOS ASR SDK 0.3.26` 公告邮件找到它的**回复邮件**，附件
   `Amphion-Harmony-ASR-Complete-0.3.26.zip`——这是当时组包产出的完整 SDK 包本身，不是厂商
   原始交付包，但它的鸿蒙 HAR 里已经编译进了 Sortformer 全部运行时资产。
2. 下载（1,939,479,824 字节），整包 SHA-256
   `860d731f7228c326f3116903e1b14c3bfb4ea65172351f780c8918a243b2d224` 与候选验收报告记录的值
   逐位一致。
3. HAR（`demo-source/libs/amphion_dingqiao.har`）实际是 gzip 压缩的 tar，不是普通 zip；解开
   两层后在 `package/src/main/resources/rawfile/amphion-dingqiao/sortformer-66M-4spk/` 下找到
   全部 7 个文件。
4. **逐文件 SHA-256 与 `delivery/harmony-dingqiao/delivery/sortformer_diarization_v1.json` 清
   单核对，全部 OK**：`pre_encode.ort`、`encoder_layers.int8.ort`、`speaker_head.ort`、
   `spkcache_update.ort`、`learnable_sil_emb.npy`、`mel_window_hann400_periodic_false.npy`、
   `mel_filterbank_128x257_slaney.npy`。
5. 已恢复到仓库约定的运行时路径 `shared/models/asr/dingqiao/sortformer-66M-4spk/`（该路径
   `.gitignore` 已预先排除，不会被误提交）。

**这解除了精度/CPU 端真机验证的阻塞**，见第四节的真实加载与端到端结果。

**仍然缺失、尚未解除的一环**：NPU 转换需要的是**转换前的原始 ONNX 源图**（manifest 里
`derivedFrom` 字段指向的 `models/*.onnx`），这批 `.ort` 是已经编译优化过的 ONNX Runtime
Mobile 格式，OMG 转换器吃的是 ONNX，不是 `.ort`——这两者不能互相代替。原始 ONNX 源图大概率
只在厂商原始交付包里，**这部分仍然需要第二节、第七节里说的两条路径之一**。

## 二、已有的间接方法：跨芯片探针方法学已经预演过一次

因为缺 Sortformer 资产，先用已经完整验证过的 **ASR encoder FP32 五段模型**（真实生产模型，
不是替代品）在 nova 14 Pro（MIA-AL00，芯片型号未知，与 nova 15 的 Kirin 8020 不同）上跑了一
遍同样的探针流程，目的是检验"跨芯片验证"这套方法本身是否成立，不是验证 Sortformer。

### 结果（第一轮：冷启动探针，缺真实输入与接力能力）

| 项 | nova 15（Kirin 8020） | nova 14 Pro（未知芯片） |
|---|---|---|
| NNRt 设备枚举 | `NPU_ohos.boot.hardware.kirin8020_v2_0, HIAI_F` | 只有 `HIAI_F` |
| ASR encoder 五段（96~146 MiB/段，与 nova 15 完全相同的 .om 文件） | 全部 PASS | **全部 PASS**（build 388~875 ms） |

两台设备的 NNRt 设备拓扑确实不同，说明这次真的拿到了跨芯片信号，不是同一颗芯片的重复样本。
五段真实模型在拓扑不同的芯片上全部被接受——结构性接受度这一层，换芯片没有直接报废，但第一
轮用的探针程序是更早期的迭代版本，不支持真实输入回灌（`.in`/`.out`）、也不支持五段接力模式
（split-seq）——本地留存的探针源码快照文件名本身就是证据：`om_probe.cpp.before_io`、
`.before_seq`、`.before_split`，这些能力是后来才加的。

### 补齐：直接复用本地已编译的信号 HAP，重装后拿到完整数据

该探针代码的最终版本不在 git 也不在 stash，但本地构建产物目录里留着一份时间点吻合（签名时间
2026-10-30 01:33，与探针能力迭代完成的时间点一致）的已编译 HAP：
`delivery/harmony-dingqiao/samples/dingqiao-demo/entry/build/default/outputs/default/amphion_asr_demo-default-signed.hap`，
bundle 为同一个 `com.amphion.asr.harmony.demo`。直接 `hdc install -r` 装到 nova 14 Pro，无需
重新编译。

装上后重跑同一套流式序列（真实特征、跨拍缓存接力、与 FP32 归档比对），短集与全量集结果：

| 指标 | nova 15（Kirin 8020） | nova 14 Pro（不同芯片拓扑） |
|---|---:|---:|
| 短集 5 clips 编辑数 | 5/216（CER 2.31%） | **5/216（CER 2.31%）——完全一致** |
| 全量 120 clips 编辑数 | 675/8156（CER 8.2761%） | **675/8156（CER 8.2761%）——完全一致** |
| 每步延迟中位 | 111~117 ms | **109.3 ms** |
| 每步延迟 P95 | 128~131 ms | **117.3 ms** |
| build 耗时 | ≈3.4~3.5 s | 2.6 s |
| 超时步数 | 0 | 0（3440 步） |

**结论**：同一张 `.om` 图在拓扑不同的两颗芯片上，精度逐位打平、延迟持平甚至略快，640 ms 预算
内零超时。这是第一个真正意义上的跨芯片正面结论，不再只是"装得进去"，而是"算得一样对、一样
快"。过程记录：第一次尝试全量集时设备 USB 瞬断（`E001005 Device not found`），确认是真实连接
问题、不是模型或兼容性问题后，设备重新连接，原样重跑拿到以上数据，没有改动任何判定口径。

**边界没有变**：这仍然是 ASR encoder 的方法预演，不是 Sortformer 本身；nova 14 Pro 的具体芯片
型号仍未确认；只覆盖了两颗芯片，Mate 60 / Mate 70 Pro / "最新机型" 仍然是全新的、没有任何数据
的组合。

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

## 四、资产恢复后的真实验证（11-04，CPU 端）

### 4.1 四个模块真实加载（不是只核对哈希）

用 onnxruntime 1.31.1 CPU EP 逐个创建 `InferenceSession`，全部成功，并把声明的输入输出形状
和理论分析第 3.2 节的推断做了交叉核对：

| 模块 | 输入 | 输出 |
|---|---|---|
| `pre_encode.ort` | `mel [batch,128,mel_frames]` | `feats [batch,enc_frames,512]` |
| `encoder_layers.int8.ort` | `feats [batch,ctx_frames,512]` | `enc [batch,512,ctx_frames]` |
| `speaker_head.ort` | `enc [batch,512,ctx_frames]` | `probs [batch,out_frames,4]` |
| `spkcache_update.ort` | `chunk [1,124,512]`、`spkcache`/`fifo [1,188,512]` 等 12 个张量 | `spkcache_out`/`fifo_out [1,188,512]` 等 6 个张量 |

**`chunk` 形状 `[1,124,512]`、`spkcache`/`fifo` 形状 `[1,188,512]`，和交付清单记录的
`chunkLen: 124`、`spkcacheLen: 188`、`fifoLen: 188` 完全一致**——第 3.2 节"理论推断"的那部分，
现在有真实模型签名作为实测依据，不再只是从数字推断。

### 4.2 四模块真实串联跑通一整条链路

用随机但形状正确的输入，按真实数据流顺序跑：`pre_encode → encoder_layers → speaker_head →
spkcache_update`，全部输出 `finite=True`，且 `spkcache_update` 返回的 `f_len_out=[124]`
正确反映了"这一块 124 帧被吸收进 FIFO"——这是内部状态记账逻辑在真实生效，不是空跑或占位输出。

**边界**：这次用的是随机输入，不是真实音频，所以不构成精度/DER 验证；要做精度验证，需要接上
真实 mel 特征提取和参考标注（manifest 的 `validation` 字段记录了厂商自己的基线：主机金标
逐阶段 max|Δ| mel 2.3e-5、speaker_head 1.9e-5，端到端 0.016；设备 `VYG-AL30 dq5 UEM DER
12.10%`，与仓库其它文档的 DER 数字一致）。

### 4.3 对第二节跨芯片探针方法学的意义

有了真实权重，第二节验证过的跨芯片探针方法（OMG 转换、`.om/HIAI_F` 真机 build、split-seq 流
式接力）**原则上可以直接套用到 Sortformer 上**——但要注意第一节末尾的限制：探针链路从
ONNX 开始，这批 `.ort` 文件不能直接喂给 OMG，需要先解决 ONNX 源图缺失的问题，或者先评估
"`.ort` → 可转换的 ONNX" 这条路径是否可行（有信息损失风险，未验证）。

## 五、合成探针实验：验证了动态 K 这个真实风险点（已执行，真实结果）

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

## 六、安卓 vs 鸿蒙：不是同一个验证面

"兼容对应的安卓和鸿蒙系统"这句话涵盖两个完全不同的验证面：

- **鸿蒙路径**：NNRt → `HIAI_F`，本文第二、四节用的就是这条链路，换机型主要是换芯片，瓶颈
  模式（工作集上限、cube 利用率、算子接受度）大概率还在，但具体数字要重测。
- **安卓路径**：现在安卓的 Sortformer 完全跑在 CPU（sherpa 预编译 ORT 1.24.3），代码里没有
  任何 NNAPI 或厂商 NPU 代理调用——这条线上 NPU 加速**还没有开始做**，不是"换机型重测"，是
  "从零立项"。工作量和鸿蒙这条线不是一个量级，需要单独排期。

## 七、下一步（按能否现在开始排序）

| 优先级 | 动作 | 是否需要等外部输入 |
|---|---|---|
| ~~1~~ | ~~重装 nova 14 Pro 上的探针，把 ASR encoder 的跨芯片数据补完整~~ | **已完成（见第二节补齐部分）**：直接复用本地已编译 HAP，精度与延迟均与 nova 15 打平 |
| ~~2~~ | ~~找到 Sortformer 运行时资产~~ | **已完成（见第一节）**：从内部邮箱附件恢复，7 个文件逐一 SHA-256 核对通过 |
| 3 | 在 nova 15 / nova 14 Pro（方法已验证可跨芯片复用）上跑 Sortformer 真机基线（CPU 路径） | 不需要，现在可排期——资产已就绪 |
| 4 | 找到 Sortformer 的预转换 ONNX 源图（NPU 转换专用，`.ort` 不能代替），解除 NPU 这一条路径的阻塞 | 需要用户提供厂商原始交付包，或确认是否有已转换过 OMG 的产物 |
| 5 | 借到 Mate 60（Kirin 9000s），走一遍同样的探针流程 | 需要先借到设备 |
| 6 | 确认"最新机型"具体型号，排入设备矩阵 | 需要用户明确型号 |
| 7 | 安卓 NPU 兼容性单独立项。另外注意：**Mate 60 / Mate 70 Pro 本身不是安卓设备矩阵的合适代表**——Mate 70 Pro 已确认是 HarmonyOS NEXT，无 AOSP 兼容层；Mate 60 即便早期固件带兼容层，也不等同受支持的 Android 运行环境。安卓侧若要验证，应使用真正运行 Android 的设备，与这两款机型分开排期 | 需要用户确认范围 |

## 八、关联文档

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
