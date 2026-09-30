# 跨窗口特征复用不可行（前提证伪，2026-09-30）

**结论：在当前 Community-1 模型与 10 s 窗 / 1 s 步长几何下，跨窗复用 fbank / encoder / segmentation
的中间结果无法保持逐值一致，因此不能用来消除"每秒重算整窗"的重复计算。该优化方向关闭。**

本轮为只读验证，未修改 SDK 运行代码。目的是在执行增量缓存前先证实或证伪前提——如果复用会改变
每个特征值，那么它必然改变聚类、VBx 与身份，仓库的逐值一致门禁会直接否决它。

## 为什么会重复计算

每 1 秒新增音频都要处理一个 10 秒窗，因此同一段音频被重复参与约 10 次推理。真机实测单窗
native 耗时中位约 575 ms（segmentation 124 + fbank 22 + encoder/pooling 429），而步长只有 1 s，
余量仅约 1.6 倍。

## 证伪依据

### 1. fbank 逐窗去均值（结构性原因）

`asr/harmony/sdk/src/main/cpp/community_fbank.h:59-63` 在 log-mel 之后对每个 mel 维度按**本窗**
998 帧求均值并减掉：

```cpp
for(int m=0;m<80;++m) {
  double mean=0;for(int f=0;f<frames;++f)mean+=features[f*80+m];
  const float value=static_cast<float>(mean/frames);
  for(int f=0;f<frames;++f)features[f*80+m]-=value;
}
```

这是官方 Community-1 管线的必需归一化，意味着**同一段绝对音频在不同窗里的特征值必然不同**。

实测（真实会议音频，窗起点 0 与 16000 采样，即相隔 1 s，`asr/tools` 同款 fbank + 锁定 ONNX）：

| 比较 | 结果 |
| --- | --- |
| 同一绝对音频的 fbank 帧（A[k+100] vs B[k]），898 帧 | **逐帧全部不同**：max = median = **0.2533** |
| 差异分布 | 均匀遍布整窗，**不是**切片边缘效应 |
| 完全相等的帧 | 0 / 898 |

差异恒为同一数值，正是两窗 mel 均值不同所致。

### 2. encoder 输出网格与 1 s 步长非整数对齐

encoder 输出 `[1,2560,125]`，10 s → 125 帧，即 **80 ms/帧**；1 s 步长 = **12.5 帧**，非整数。
按最佳整数偏移比较重叠帧：

| 偏移（输出帧） | 比较帧数 | max abs diff |
| --- | ---: | ---: |
| 13 | 112 | **1.525** |
| 12 | 113 | 2.030 |
| 19 | 106 | 2.851 |

即使只取最佳对齐，残差仍是 1.5 量级，而非 1e-6 级；叠加第 1 条，逐值一致不可能达成。
segmentation 同样受窗口相对网格约束（589 帧 / 10 s ≈ 271.6 采样/帧，1 s = 58.9 帧，非整数）。

### 3. pooling 不是可优化项

主机实测（ORT 1.16.3 CPU，与设备同版本）：

| 阶段 | 耗时 |
| --- | ---: |
| encoder（`[1,998,80]` → `[1,2560,125]`） | **198 ms** |
| pooling（整窗 mask） | 0.43 ms |
| pooling（单 run mask） | 0.41 ms |

`embeddingMs` 几乎全部是 encoder；减少 pooling 调用没有意义。

## 影响

- "每秒重算整窗"是**结构性冗余**，在不改变特征/embedding 取值的前提下无法消除。
- 这也解释了仓库既有对照中"2 s hop 会丢说话人"：证据与该窗的归一化绑定，改变窗口几何即改变
  VBx 分量存活。
- 因此降低单窗成本只能走模型层（量化/更小模型），那需要独立的身份精度评估，且会改变每个特征值，
  必须重新走精度门禁。

## 复现

主机脚本与产物位于 `.cache/speaker-screen-repro-acf477c2/encoder_shift/`（`extract_fbank.cpp`、
`fbankA.f32`、`fbankB.f32`、比较脚本）。原始 PCM、模型与哈希不进入 Git。
