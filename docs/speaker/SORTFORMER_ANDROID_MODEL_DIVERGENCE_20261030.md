# 安卓侧 Sortformer 模型与厂商交付的差异（2026-10-30）

安卓的角色分离换成 Sortformer 之后，**随包的模型文件与厂商交付不是逐字节相同**。本文记录差了
什么、为什么差、怎么复现，以及需要反馈给模型提供方的内容。鸿蒙不受影响：它继续用厂商原样的
`.ort` 与 ORT 1.16.3。

## 一句话

安卓链的 onnxruntime 比交付包所要求的 1.16.3 新很多，加载 `spkcache_update` 时在
`/TopK_3` 上按 ONNX 规范拒绝；我们把那个 K 从「运行时由 `Gather(Shape(...), [1])` 算出」改为
「显式的 `int64[1] = [188]` 常量」，输出逐字节不变。

## 两处差异

| 项 | 鸿蒙（厂商原样） | 安卓 |
|---|---|---|
| 格式 | `.ort`（ORT 1.16.3 转换） | `.onnx`（厂商源图） |
| `spkcache_update` | 原图 | `/TopK_3` 的 K 改为常量，删 3 个悬空节点 |
| 编码器文件 | `encoder_layers.int8.ort`，源自 `models/int8/encoder_layers.int8.ort1163.onnx` | `models/int8/encoder_layers.int8.onnx` |
| onnxruntime | 1.16.3 | sherpa 预构建 1.24.3 |

**编码器那一行要特别注意**：交付包 README 第 0 节说明，`encoder_layers.int8.onnx` 带 8 个无用的
`ai.onnx.ml:5` 声明，**ORT 1.16.3 加载不了**，所以厂商另做了去掉声明的 `ort1163` 变体供鸿蒙用。
安卓的运行时能直接吃原始那份。两端编码器**权重相同、文件不同**。

## 为什么会这样

交付包整体是围绕 ORT 1.16.3 与鸿蒙做的适配，README 第 0 节标题就写着「运行时兼容性 ——
ORT 1.16.3（鸿蒙）」。安卓的 onnxruntime 跟着 sherpa 的预构建走（`ONNXRT_VERSION=1.24.3`，
来自 `csukuangfj/onnxruntime-libs`），与识别链路共用同一个 `libonnxruntime.so`，不能为角色分离
单独降版——同一进程里两份 ORT 会撞符号。

`/TopK_3` 的报错原文：

```
Node (/TopK_3) Op (TopK) [ShapeInferenceError] K input must be a one-dimensional tensor of size 1.
```

**这张图本身是合规的**：`onnx.shape_inference` 给出 `/Gather_output_0` 的 rank=1、dims=[1]，
正是规范要求的形状。1.16.3 接受，更新的运行时在自身图变换后重新校验时拒绝。换成版本无关的
原始 `.onnx` 报同一个错，所以**与 `.ort` 这层格式无关**。

## 改了什么

`spkcache_update` 共 270 个节点，动了 3 个：

| | 厂商原图 | 改后 |
|---|---|---|
| `/TopK_3` 的 K | `/Gather_output_0`（Shape → Gather → K） | initializer `int64[1] = [188]` |
| 节点数 | 270 | 267（删 `/Shape`、`/Gather`、`/Constant_80`） |
| initializer 数 | 0 | 1 |

K 的值之所以能写死：`/TopK_3` 的数据输入 `/Where_13_output_0` 形状静态为 `[1, 188]`，沿 axis=1
取 TopK，所以 K 恒为 188 —— 即交付清单 `streaming.spkcacheLen`。权重、算子类型与其余 267 个
节点一律未动，另外三张图未碰。

脚本：`asr/tools/models/patch_sortformer_spkcache_topk.py`。它会断言目标节点存在、该轴形状静态、
被删节点无其他消费者，任一条不满足就报错退出——厂商换版时它会直接失败，而不是悄悄改错地方。

| 文件 | sha256 |
|---|---|
| 厂商 `spkcache_update.onnx` | `0c7aa030999f999152b2e3af839a24ded2a58ead57f81639af8faf29301b5b4a` |
| 改后（安卓用） | `0c94925a541276407c03d10290f8dcac00b3dbc4cf1f2cb788cc1ccf002a609d` |

## 等价性怎么验的

同一组固定种子的随机输入，喂进改前改后两张图（ORT 1.19.2，扩展优化开启），六个输出
**逐字节完全一致**：`spkcache_out`、`spkcache_preds_out`、`sc_len_out`、`fifo_out`、
`f_len_out`、`compressed_out`。

端到端的印证更有力：四条丁桥现场录音在同一套 openbench-der-v1 口径下，安卓与鸿蒙
**全集 DER 都是 12.10%**，逐条最大差 0.06pp（3.01/13.56/26.24/6.41 对
3.01/13.50/26.24/6.44）。两端共用同一份 C++ 实现与同一套权重，数值路径没有分叉。

## 连带发现的一个安装器缺陷（已修）

资产就绪判定原来只校验「大小不小于下限」。改图后新旧 `spkcache_update` 只差 151 字节、
**旧的反而更大**，于是旧的厂商图一直被当作已就绪、从未被替换，设备上跑的始终是旧图，
排查了很久才发现。现已改为按精确大小比对，不一致即删除重装，装完再核一次；
`DingqiaoSortformerAssetsTest` 钉住这个行为。任何体积相近的模型换版都会踩这个坑。

## 需要反馈给模型提供方

1. **把 `/TopK_3` 的 K 在导出时就写成常量**，或显式整形为 `[1]`。这样两端都不必打补丁。
   根因在导出脚本，不在模型质量。
2. **明确声明支持的 onnxruntime 版本范围**。目前交付包只验证了 1.16.3，而我们两个平台的运行时
   版本由各自的识别链路决定，不可能统一到 1.16.3。
3. 如能提供一份对新版运行时也能加载的 `.ort`，安卓即可回到与鸿蒙相同的格式。

## 风险与限制

- 我们现在维护一份与厂商交付不一致的模型文件。厂商换版时必须重跑补丁脚本并重做等价性比对，
  脚本的断言会在结构变化时报错。
- 安卓不享受 `.ort` 的加载期优化，启动时要多做一次图优化。实测代价见
  `docs/speaker/SORTFORMER_ANDROID_DEVICE_20261030.md`。
- 两端编码器文件不同（权重相同）这一点，在任何"两端二进制一致"的表述里都必须排除。
