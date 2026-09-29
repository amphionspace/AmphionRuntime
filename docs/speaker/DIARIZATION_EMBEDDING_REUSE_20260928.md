# 同窗口 embedding 复用与瓶颈记录

这是端到端交付的局部性能修复，**不是身份精度修复或发布放行**。前置诊断和采样密度根因见 [端到端推进记录](DIARIZATION_E2E_PROGRESS_20260928.md)。运行候选提交 `83fa0e41`；Android 既有编译断裂另由 `5a54b20f` 修复。最终长会议、完整实录、人工身份裁定和客户展示门禁仍未完成。

## 要改变与必须保持的行为

目标是去掉同一窗口内、相同 mask 的重复 encoder 调用。保持 PCM、fbank、10 秒窗口/2 秒 hop、分割、run 范围、每个向量和非训练 sentinel、AHC/VBx、临时身份、已提交身份、公共文本与生命周期不变。不跨窗口、stream 或 session 缓存，不修改 Fa/Fb，不把不同 mask 的向量视为同一人物。

固定的 masked WeSpeaker 模型 SHA-256 为 `bc3912904210f19c7a249a2fca8cfc587b82b4142b73231570839e9dd9041375`。ONNX 图在共享特征后按 mask channel 分别池化，最后逐行投影，三个 mask 不互相改变对应向量。生产代码只在 clean run 已覆盖该 channel 的全部选中帧时复用该窗口已算出的向量；只要还有另一段活动，包括不足训练长度的短尾段，就继续使用独立 run 推理。overlap 的 NaN 和短段的零向量行为保持原样。

## 旧版瓶颈证据

证据来自 `f850a7cc` 的同一 Mate80、同一输入。取完整窗口日志，未再跑旧版：

| 输入 | 窗口数 | embedding 占推理耗时 | run 编码调用 | 可复用调用 | 占全部 encoder 调用 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 四人短录音 19.58 s | 6 | 88.25% | 9 | 9 | 60.00% |
| 四人实录 123.8 s | 58 | 86.84% | 81 | 37 | 26.62% |
| AISHELL-4 四人切片 180 s | 86 | 87.01% | 117 | 29 | 14.29% |

全部 75 个可复用 run 的旧版完整向量逐值相同，最大绝对差为 0。调用比例只是工作量诊断，实际性能必须看真机计时。

## 验证与未关闭问题

最小测试在旧代码稳定失败于“相同 mask 仍执行 encoder”，修复后通过。测试还覆盖不同窗口 PCM、单帧间隙、多个独立 run、长段加短插话、纯短段及 overlap，逐项检查向量/范围和不确定性标记。48 项 Community/native/公共身份契约检查通过；Android SDK 61 项和适配层 129 项单测通过，Android arm64 native 构建通过。Harmony 只构建了一个 ZH_EN diagnostics 测试 HAP，签名、模型与 build identity 校验通过。

短录音候选与旧版的 6 个窗口分割、整窗向量、run 向量、run 范围均完全一致；聚类 commit/preview、公共角色 payload 和四条 ASR 原句/时间戳也一致。embedding 累计耗时由 6433.824 ms 降至 2472.900 ms（-61.56%），角色推理 RTF 由 0.373627 降至 0.178012。唯一 last/complete 和 native stream 归零通过。

124 秒实录的 58 个窗口也逐项一致，包括 23 条 ASR 原句、12 次临时聚类和两次冻结提交。embedding 耗时由 58128.642 ms 降至 41920.684 ms（-27.88%），角色推理 RTF 由 0.549069 降至 0.418476。finish 到 complete 为 1066 ms，未出现提前 last、额外 complete 或存活 stream。队列超过 60 秒观察的最大音频延迟 1540 ms；SDK 资源阈值 PASS，但 RSS 三段中位数继续上升，严格长期内存结论仍为 INCONCLUSIVE。没有将载体 PASS 当作长期内存或客户身份体验通过。

AISHELL-4 四人切片的 86 个窗口、25 条 ASR 原句、16 次临时聚类及两次冻结提交也逐项相同。embedding 耗时由 84058.072 ms 降至 73359.433 ms（-12.73%），角色推理 RTF 由 0.549875 降至 0.488958；strict DER 保持 42.7774%，仍只输出两人。UNKNOWN/overlap、少数人漏识和已有身份编号均未被性能优化改写。这证明本次局部变换在三个固定输入上的等价性，不证明原结果本身已经正确。

短录音 RSS 仍触发原门禁：旧版增长 117.471 MiB，候选增长 123.168 MiB，两者均为约 26 秒观察窗并跨过首次推理驻留。该差异不足以归因于新泄漏，也不能作为内存通过依据；红灯保持。124/180 秒配对测量用于进一步判断资源与身份，不启动完整 16 段或发布长矩阵来掩盖它。

Android native 构建错误在起始 `origin/main=f5bd3867` 已存在：JNI 调用缺少 native 新增的两组 run 参数。独立修复显式传入空的可选 run evidence，保留 Android 现有整窗聚类路径；未伪造 run 向量。红灯和修复后构建日志均保留。Android Kotlin/JNI 尚未贯通 run 级证据，平台身份能力一致性仍是开放项，不能把编译恢复称为角色分离交付。

本地证据根目录：`~/.cache/amphion-runtime/diagnostics/embedding-reuse-20260928/`。包含 `experiment.json`、红/绿日志、旧版 HAP/HAR 副本、`baseline-bottleneck.json`、输入索引、逐轮 report/corpus/内存/hilog、完整事件、向量与公共结果差分以及新旧 build binding。原始音频与含文本的诊断不进入 Git。

## 后续路径已有的证据

剩余独立 run 在相同 fbank 上重复执行整窗 encoder。利用当前模型三个 mask 槽位合并推理，124 秒实录的剩余 run 调用只能从 44 次降到 35 次，180 秒片段从 88 次降到 64 次，收益有限。

在主机保留同一 ONNX 权重，将图按 `/resnet/pool/Reshape_output_0` 切成 encoder 和 pooling 两部分：一次 encoder 输出 `[1, 2560, 125]`，占 1,280,000 字节；同一特征上分别执行四种 mask pooling，与四次完整模型的输出逐值相同，最大绝对差 0。一次合成特征实验计时为完整四次 1551 ms、encoder 一次 380 ms、pooling 四次 4.4 ms。它只证明图分解方向可行，不能当作真实语音、Mate80 性能或已完成的生产改造。

下一步应先用真实窗口验证该边界，再在单次 `Process` 内共享 encoder 特征；特征必须在该调用结束时释放，不跨窗口、generation 或 session。模型权重与三通道 mask 语义不变，分解后的 ONNX、原始模型哈希、导出脚本和精度差分必须重新绑定。之后才测量官方 1 秒采样协议所需的实时余量，并保护四段实录锚点；不以直接改 hop 或强制增加聚类数替代优化。

三段配对的正式索引在 [83fa0e41 证据摘要](evidence/DIARIZATION_EMBEDDING_REUSE_83FA0E41.json)。`paired-gate-comparison.json` 没有新增语义回归，仍保留旧有短录音内存 FAIL。新旧 HAP/HAR 均另存了实际字节，后续构建不会破坏本轮对照。公开集第一次尝试因独立 Android 提交改变 HEAD 而被预检拒绝，未播放音频；实际测量在冻结的 `83fa0e41` 源码上下文完成，随后恢复原分支。预检失败日志保留，不当作算法失败或有效采集。
