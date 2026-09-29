# 同窗口共享 encoder 与采样协议差分

本轮完成一项有配对证据的计算优化，**角色分离整体仍阻断交付**。候选运行提交 `7b5b7fb0`，基线 `83fa0e41`；设备均为 Mate80 `7GK0226326015655`、`OpenHarmony-6.1.1.120`。两边 HAP 和四个 HAR 的实际字节均已归档，完整哈希、输入、评估器与结果索引见 [证据摘要](evidence/DIARIZATION_SHARED_ENCODER_7B5B7FB0.json)。前一轮见 [相同 mask 复用记录](DIARIZATION_EMBEDDING_REUSE_20260928.md)。

## 代码改变与不变量

剩余瓶颈是同一 Fbank 输入上，为不同 clean run 重复执行 WeSpeaker encoder。将原始锁定 ONNX 在 `/resnet/pool/Reshape_output_0` 分解为 encoder 与 pooling，权重不变。每次 native `Process` 编码一次，得到 `[1, 2560, 125]`、1,280,000 字节的特征；整窗与独立 run 的 mask 分别池化。特征属于该次同步调用，结束即释放，不跨窗口、generation 或 session 缓存。encoder 沿用 XNNPACK 四线程，pooling 为单线程 CPU，不引入第二个计算线程池。

保持 PCM、Fbank、分割、10 秒窗口/2 秒 hop、run 准入、短段零向量、overlap NaN、AHC/VBx、身份冻结、SDK 原句与回调语义不变。本补丁不改模型、人数、Fa/Fb、timeout、队列策略，也不填补 UNKNOWN。

最小用例在旧实现失败于不连续 run 重复编码，修复后通过；同时检查不同窗口 PCM、单帧间隙、长段加短尾、纯短段及 overlap。59 项 native/身份/build identity 检查、190 项 Android 单测、Android arm64 native 编译通过。仅构建安装一个 ZH_EN diagnostics HAP，签名、授权、build identity 通过。

`export_community_embedding_split.py` 使用 `onnx==1.19.1` 从原模型导出，逐一校验源和两个输出哈希。14 个真实窗口、32 组 mask 的主机完整图/拆分图输出逐值相同。Harmony/Android 资产同步、JNI 和内部 native 类型、build identity 均更新；HAP 内新资产哈希通过，旧 26 MB 图不再重复打包。内部 byte-array loader 变为五项资产，公共 SDK API 和 resource-manager loader 不变。准备方式见 [Community 模型说明](../../delivery/harmony-dingqiao/docs/COMMUNITY_MODELS.md)。

## 同输入 Mate80 配对结果

| 输入 | 窗口 | embedding 累计耗时：基线 → 候选 | 角色 RTF：基线 → 候选 | 最大音频延迟：基线 → 候选 |
| --- | ---: | --- | --- | --- |
| 四人实录 19.58 s | 6 | 2472.90 → 2488.28 ms | 0.1780 → 0.1745 | 660 → 640 ms |
| 四人实录 123.8 s | 58 | 41920.68 → 23484.72 ms（-43.98%） | 0.4185 → 0.2660 | 1540 → 940 ms |
| AISHELL-4 四人切片 180 s | 86 | 73359.43 → 36158.53 ms（-50.71%） | 0.4890 → 0.2848 | 1920 → 820 ms |

150 个窗口的坐标、分割、整窗/分段向量与 run 范围全部逐值一致。52 条 ASR 原句及时间戳、29 次 preview、5 次 commit/公共角色结果逐项一致；排除项仅为 job ID 和聚类计时。短录音在上一版已达到每窗一次编码，本次基本持平，符合预期。

三轮 native stream 均归零、生命周期通过，pending 最大值均为 0。124 秒与公开切片的 finish→complete 分别为 1194 / 1143 ms；前者基线 1066 ms，不能声称所有尾部延迟均改善。短 paced 载体的该字段为 -1，不能当作有效耗时。

公开切片 SDK strict DER 仍为 **42.7774%**，仍只输出两人，两位少数说话人召回为 0。本次证明输出等价和算力收益，未修复这些既有误认/漏识。SDK 文本等价也不等于真实调用方呈现已经验收。

## 保留的资源红灯和不确定性

- 短录音 RSS 门禁依旧 FAIL：基线增长 123.168 MiB，候选 121.486 MiB，观察不足 60 秒并跨首次模型驻留，不能归因为持续泄漏，也不能放行。
- 124 秒实录 RSS 三段中位数为 613.822 / 628.965 / 642.090 MiB；公开切片为 621.414 / 637.422 / 642.090 MiB。原载体阈值 PASS，但严格长期趋势均为 INCONCLUSIVE，未放宽阈值。
- 124 秒实录严格实时证据 PASS。公开切片队列头尾延迟中位数为 600 / 610 ms，虽最大延迟和 RTF 大幅下降且 pending 为 0，现有严格实时判定仍为 INCONCLUSIVE（基线 PASS）。保留这个变化，不将性能均值替代趋势结论。

配对器没有发现新增身份语义回归；整体仍 FAIL，包含既有短 RSS 红灯和未完成的门禁。未执行完整 16 段及发布长矩阵，未合入或发布。

## 为下一步身份修复补充的状态差分

复用同一 180 秒 PCM、官方已保存的分割，使用当前生产 Fbank、拆分图和 run 提取逻辑，仅将同一批 1 秒窗口张量按 1 秒/2 秒取样。走相同 C++ 聚类和 PLDA，不传 oracle 人数；4 只是 SDK 能力上限。以下是**主机全历史诊断**，没有 SDK 临时身份、冻结与调用方展示，不能充当真机身份验收。

| 当前 run 路径 | 窗口 | 训练 run | AHC 组 | 输出人数 | strict DER | 002-F / 003-F recall |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1 秒采样 | 171 | 233 | 46 | 4 | 33.7753% | 22.2909% / 84.6154% |
| 2 秒采样 | 86 | 117 | 42 | 2 | 42.8311% | 0 / 0 |

两路均未触发 KMeans 或短段训练补充。密度造成身份分量丢失的结论在当前 run 路径再次成立；它不是“模型完全不可分”的证据，也不代表改 hop 就完成交付。

另在同一批密集分割和整窗向量上，关闭可选 run 证据作一次诊断对照：整窗路径 DER 为 24.3169%，UNKNOWN 由 32.12 秒降至 0，但错误身份归属从 **2.07 秒增至 15.09 秒**。整窗路径漏检 20.43 秒，当前 run 路径 59.34 秒，表明还有短段/匿名证据覆盖问题。不能直接撤掉 run 和 overlap 保护来追 DER；该对照不作为生产候选。

下一步先在 SDK preview/commit 冻结路径验证官方 1 秒采样协议，再以四段实录锚点否决错误换号、短插话消失和不诚实归属。同时沿未准入 run → 匿名轨迹 → frame assignment 定位剩余覆盖损失，保留真实 UNKNOWN/overlap。只有在同输入证据证明窗口重复编码仍不足实时后，才进入跨窗口增量 encoder 设计。

本地证据目录为 `~/.cache/amphion-runtime/diagnostics/shared-encoder-20260928/`，保留新旧构建绑定、逐轮报告、hilog/回调、RSS、完整窗口快照、导出记录、主机分叉输入及评估。原始 PCM、实录文本和模型二进制未提交 Git。完整四锚点、16 段、长会议、真实展示、人工身份裁定、离线网络观测及最终生命周期发布门禁仍未全部完成。Qwen 辅助标注尚未获得可确认的匹配凭据，未发起 API 调用；这不影响本轮同输入状态差分。
