# 【最终评估】端侧目标说话人增强

## 1. 最终结论

当前分支的 `enableTargetSpeakerEnhancement` **在客户最关注的 C1/C2/C3 重叠场景中明确优于
main 上的 Speaker VAD**：默认 Speaker VAD 的严格业务结果为 `0/3`，本分支为 `3/3`，且三例连续
重复 12 个 session 时文本完全一致。

但它**不全面优于** main，也不应替代 main 的默认 Speaker VAD：增强链路在 Mate 80 上约使用
1.9 倍平均 CPU、增加约 341 MiB 峰值 RSS；对目标人缺席的多人/噪声输入存在稳定误放行，对本来
已经能识别的普通语音也可能丢字或截断。

最终产品判断是：

- **作为高端机、目标人预计在场、多人同时讲话时的显式可选能力：有条件通过。**
- **作为普通 ASR / Speaker VAD 的全局默认替代：不通过。**
- **作为“只会输出注册警员”的身份安全能力：不通过。**

## 2. 对照范围与证据有效性

- 设备：Huawei Mate 80，HarmonyOS `6.1.0.135`，12 个逻辑 CPU，约 12 GB 内存。
- 当前分支：`codex/speaker-vad-enhancement-debug@d1ba845`。
- 当前远端 main：`0367ac6`。
- main 真机基线产物：`main@1ca9108`，默认 Speaker VAD 参数为阈值 `0.35`、窗口 `1500 ms`、
  步长 `500 ms`，20 ms 实时写入。
- 截至 `main@0367ac6`，上述阈值、窗口和步长没有变化。其间的 hop 调度修复用于消除调用方分帧差异，
  已有实时 20 ms 路径零漂移证据。因此本报告复用已完成的 main 真机基线，不重复刷机；main 性能
  绝对值仍严格绑定 `1ca9108` 的报告，不伪装成 `0367ac6` 的重新实测。
- 当前分支最终签名 HAP：SHA-256
  `7b4aa60a5f4512a42027befea6b436674e913445e9fe1ba087f96f4c2be4b1d6`，大小
  `359,886,041 bytes`。

`/Users/boxp/Downloads/鸿蒙-声纹-wav和问题描述-0729` 与仓库
`asr/test-fixtures/target-speaker-customer-cases` 的 3 段注册 WAV、C1、C2、C3 已逐文件核对，
六个 SHA-256 全部一致。因此以下效果对照没有换语料。

## 3. 效果：C1/C2/C3 是否优于 main

严格业务门固定为：最终放行文本必须包含“上海”，且不得包含“你好”。

| 用例 | main 默认 Speaker VAD | 本分支增强 | 判断 |
|---|---|---|---|
| C1：目标人与他人轮流讲话 | endpoint 前“你好”已经进入目标 final，失败 | `帮我查收明天的警单。然后准备明天去上海。` | **增强胜出** |
| C2：目标人说话时他人插话 | 含“上海”的混合段因分数不足被整体丢弃，失败 | `我准备明天去北京，我看明去北京的机票。你帮我定一下。准备据上海。` | **增强胜出，但仍有错字** |
| C3：他人近麦、目标人远场 | 目标“上海”片段被尾部干扰拖低并丢弃，失败 | `我准备去上海，你帮我准备一下飞机票多少钱。` | **增强胜出** |

汇总：

- main 默认 `1500/500 ms`：`0/3`。
- main 的 `1000/300 ms` 研究探针：仅 C1 通过，`1/3`；C2/C3 仍不能从重叠语音中恢复目标内容。
- 本分支增强：`3/3`；C1/C2/C3 各重复四次，共 12 个连续 session，文本完全一致。

这不是简单调 Speaker VAD 阈值得到的收益。Speaker VAD 只能决定整段保留或丢弃，无法判断重叠
语音中的每个字属于谁；本分支先用 Conv-TasNet 分出两路，再用 ERes2Net 选择更接近注册声纹的一路，
所以能够恢复 C2/C3 中原本被整体丢弃的目标内容。

## 4. 效果边界：为什么不能说全面优于 main

除 C1/C2/C3 外，当前已有以下反向证据：

- 12 条新增目标人在场音频：2 条明显改善、3 条基本不变、6 条发生丢字/替换/截断，1 条两边均有错
  无法判优；其中 2 条发生严重截断。
- 目标人缺席、其他人单独讲话：12/12 输出为空。
- 目标人缺席、其他人多人重叠或交通噪声：3/12 错误产生正式文本，三个失败样例重复两次后 6/6
  复现。
- 更大的 speaker-disjoint 离线 test 中，60 个 other-only 样例有 8 个产生非空错误文本。该数字不能
  当作线上错误率，但证明风险不是理论猜测。
- 把后置 Speaker VAD 阈值从 0.35 提高到 0.45、0.50、0.60 仍不能消除所有误放行。

因此本分支的优势是**特定重叠场景下恢复目标内容**，不是普通语音普遍提准，也不是目标缺席安全保证。
C1/C2/C3 只有三条固定客户样例，足以证明“这个症状被改善”，不足以计算正式 CER、FAR 或 FRR。

## 5. 性能评估

本节所有“代价”都相对关闭目标说话人增强的 baseline 计算，不用增强链路的绝对值代替增量：

- 端到端 CPU、RSS：baseline 是 `main@1ca9108` 默认 Speaker VAD，同一 Mate 80、同一三段注册音频、
  同一 C1/C2/C3、同一 20 ms 实时写入。
- 首个临时文本：baseline 是同一 A/B HAP、同一 PCM 的普通 ASR 配对运行。
- 点击启动：baseline 是同设备的普通 ASR 路径；本轮修改没有改变该路径，但最终增强 HAP 没有再重复
  跑一轮普通 ASR，因此启动增量是路径对照，不写成同产物配对值。旧 main 的 Speaker VAD 载体没有
  记录同口径 `startCallbackMs` / `firstNonEmptyPartialMs`，这两项也不冒充 main Speaker VAD 配对数据。
- 最新 main 的默认 Speaker VAD 参数没有变化；baseline 对应的 commit、HAP 和输入哈希仍在报告中保留。

### 5.1 C1/C2/C3 实时运行资源

两组均为同一 Mate 80、同一三段注册音频、同一 C1/C2/C3、20 ms 实时写入。

| 指标 | baseline：main Speaker VAD | 本分支增强 | 性能代价 |
|---|---:|---:|---:|
| RSS head | 510.45 MiB | 755.01 MiB | **+244.55 MiB / +47.9%** |
| RSS tail | 532.86 MiB | 777.11 MiB | **+244.24 MiB / +45.8%** |
| peak RSS | 536.11 MiB | 877.41 MiB | **+341.30 MiB / +63.7%** |
| 平均单核等价 CPU | 111.39% | 209.49% | **+98.10 个百分点 / +88.1%** |
| P95 单核等价 CPU | 161.78% | 362.81% | **+201.03 个百分点 / +124.3%** |
| 平均整机 CPU 容量 | 9.28% | 17.46% | **+8.18 个百分点 / +88.1%** |
| P95 整机 CPU 容量 | 13.48% | 30.23% | **+16.75 个百分点 / +124.3%** |
| 线程 head → tail | 47 → 45 | 49 → 47 | 均无增长 |

本分支三例 77.5 秒运行中 RSS 头尾增加 22.1 MiB，仍在 64 MiB 门内；但 RSS 斜率为正，单次短跑
不能证明长期没有泄漏。此前 12 session、约 328 秒稳压的三段中位数约为 773/781/773 MiB，未见逐轮
累积。两组证据合起来支持“当前没有已证实的持续泄漏”，不支持“内存长期绝对稳定”的过度承诺。

### 5.2 实时处理余量

- baseline 没有 Conv-TasNet 分离块；本分支为每个 2 秒块新增一次分离和两路 ERes2Net 选流。
- 当前最终 C1/C2/C3：22 个新增增强块，P95 `1622 ms`，最慢 `1625 ms`。
- 每个 2 秒块按 `1750 ms` 步长进入队列，因此当前最慢块余量约 `125 ms`，最大排队 2 块。
- 扩展 12 条目标人在场样例的独立冷进程最慢块达到 `1727 ms`，只剩 `23 ms` 余量。
- 约 2 倍实时写入仍能正确完成；一次性突发会产生 7 块积压，但不会丢结果。

结论是 Mate 80 的 ARM CPU **能实时跑，但余量有限**。当前没有 8 GB、中端设备、后台 CPU 争用或
温控降频证据，不能直接扩大支持机型。

### 5.3 启动和首个临时文本

最新启动优化后：

| 场景 | baseline：普通 ASR | 本分支增强 | 点击路径代价 |
|---|---:|---:|---:|
| 首次启动，增强已异步预加载 | 19 ms | 19 ms | **0 ms** |
| 同一模型生命周期内热启动 | 1 ms | 2 ms | **+1 ms** |
| 首次启动且未执行预加载 | 19 ms | 1088 ms | **+1069 ms** |

另测得增强模型 `unloadModel` 后直接重载为 1307 ms、`unloadRuntime` 后直接重载为 1300 ms；没有同一
门禁下的 baseline 重载数据，因此这两项只作为增强绝对冷路径记录，不虚构相对增量。

Demo 在增强开关开启时异步预加载；如果用户在预加载完成前点击“开始识别”，会立即开麦并缓存 PCM，
模型就绪后自动回灌，不丢开头。代价是增强模型和一对 ERes2Net 在空闲期保留到 `unloadModel()` 或
`unloadRuntime()`。

首个非空临时文本采用原始音频快速通道，不等待首个 2 秒增强块。相同 HAP、相同 PCM 的配对结果：

| 语料 | baseline：普通 ASR | 本分支增强 | 首个临时文本代价 |
|---|---:|---:|---:|
| C1 | 2136 ms | 2375 ms | **+239 ms / +11.2%** |
| C2 | 2010 ms | 2139 ms | **+129 ms / +6.4%** |
| C3 | 2079 ms | 2164 ms | **+85 ms / +4.1%** |
| C1/C2/C3 中位数 | 2079 ms | 2164 ms | **+85 ms / +4.1%** |
| C1/C2/C3 平均值 | 2075 ms | 2226 ms | **+151 ms / +7.3%** |
| 扩展 12 条平均值 | 3130 ms | 3429 ms | **+299 ms / +9.6%** |

扩展 12 条的配对增量中位数为 `+194 ms`，最差为 `+838 ms`。

所以“启动模型慢”的问题已基本移出点击路径，但不能承诺首个临时文本与普通 ASR 零差异。

### 5.4 包体和最坏瞬时内存

- Conv-TasNet ORT：`20,500,600 bytes`，约 19.55 MiB。
- baseline HAP：`339,029,913 bytes`；当前最终 HAP：`359,886,041 bytes`，增加
  **20,856,128 bytes / 19.89 MiB / +6.15%**。
- 上述是两个完整 HAP 的总差额；Conv-TasNet 资产本身为 19.55 MiB、占差额的大部分，但不能把其余
  分支改动产生的体积全部归给模型。
- 常规 C1/C2/C3 峰值相对 baseline 增加 **341 MiB / +63.7%**。
- 推理中 cancel 后立即恢复的当前最坏实测峰值为 **995 MiB**；相对常规 baseline 峰值高
  **459 MiB / +85.7%**。这不是同模式配对值，只用于设备最坏内存预算。

cancel 不等待已经进入原生推理的旧任务退出，新旧 session 的中间张量会短时重叠，因此峰值高于常规
运行。这不是当前证据中的持续泄漏，但是真实的瞬时内存预算。

## 6. SDK 工程成熟度

当前分支已通过：

- C1/C2/C3 内容门和连续 session；
- `onStart` 内同步写入、立即 finish/cancel；
- partial 回调内重入；
- 推理中 cancel 后立即恢复；
- `unloadModel`、`unloadRuntime` 后真实重载；
- 正常 session 在 `finish` 前无 `isLast`，结束后恰好一次 last、一次 complete；
- cancel 无 final/complete，结束后 native stream 归零；
- 正式 ORT 资产随 HAR/HAP 和客户包校验；
- 最终签名 HAP 的构建、安装和启动烟测。

因此主要剩余风险不在 SDK 生命周期，而在模型适用范围、目标缺席安全性和中低端设备资源余量。

## 7. 最终使用建议

对外保持一个显式开关，不改变 main Speaker VAD 的默认路径：

- **建议开启：**业务已知目标警员在场，并且多人同时讲话、目标内容价值高。
- **建议关闭：**安静或单人环境、目标人可能缺席、三人以上重叠、交通噪声很强、设备资源紧张。
- 临时文本用于降低等待感，身份判断和最终业务记录以增强 final 为准；但 final 也不能作为身份安全证明。
- 当前支持结论只覆盖 Mate 80 这一档高端设备。其他机型必须先做同样的实时块、RSS 和温控压力门禁。

综合评级：**C1/C2/C3 效果通过；Mate 80 实时性能有条件通过；通用效果和目标缺席安全不通过；
整体作为可选增强功能有条件通过。**

## 8. 证据索引

- main 默认 Speaker VAD：
  [`main-default`](../../delivery/harmony-dingqiao/evidence/target-speaker-enhancement/20260807-final-evaluation/main-default/report.json)
- main `1000/300 ms` 研究探针：
  [`main-short-window`](../../delivery/harmony-dingqiao/evidence/target-speaker-enhancement/20260807-final-evaluation/main-short-window/report.json)
- 当前分支 C1/C2/C3、CPU、RSS、实时块：
  [`content`](../../delivery/harmony-dingqiao/evidence/target-speaker-enhancement/20260807-startup-optimization/content/report.json)
- 当前分支最终预加载启动：
  [`preload`](../../delivery/harmony-dingqiao/evidence/target-speaker-enhancement/20260807-startup-optimization/preload/report.json)
- 当前分支 cancel 峰值：
  [`cancel`](../../delivery/harmony-dingqiao/evidence/target-speaker-enhancement/20260807-startup-optimization/cancel/report.json)
- 扩展语料与失败分析：
  [`SPEAKER_VAD_ENHANCE_DEVICE_EVAL_20260807.md`](SPEAKER_VAD_ENHANCE_DEVICE_EVAL_20260807.md)
