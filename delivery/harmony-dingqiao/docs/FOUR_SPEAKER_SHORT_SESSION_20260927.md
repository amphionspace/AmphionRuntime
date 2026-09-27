# 19.58 秒四人轮流发言被标为同一人的定位

状态：**身份体验 FAIL，禁止合入或宣称四人分离已修复。** 已修两处无依据的已知身份分配；剩余短句建档和 VBx 身份合并仍阻断验收。

## 输入与边界

- Mate80 鼎桥 Demo 的最新麦克风录音，19.58 秒、16 kHz / PCM16 / mono，979 帧；用户确认四人依次各说一句。
- 原始现场：`run-1790498434519/session-3`；WAV SHA-256 `f13ad95b225a88c64161ff9a01770d07718f547c97445b7b6bb61ae146f739e7`。原音、截图、完整事件和另外两次录音均保存在私有证据目录，未提交仓库。
- 私有证据根：`~/.cache/amphion-runtime/diagnostics/four-speaker-collapse-20260927-165102/`。输入映射为 `input-map.json`，实验约束为 `protocol.json`。
- 固定模型和权重、10 秒逻辑窗口、160000 samples 输入、32000 samples / 2 秒 hop、10 秒预览、120 秒定稿、10 秒单窗口 / 15 秒 finish timeout。实际六个窗口起点为 0 / 2 / 4 / 6 / 8 / 10 秒；本轮不评估定稿周期。
- 改变：单个建档向量也遵守本地声道的约束分配；没有任何已知身份声学支持的帧输出 UNKNOWN。静音声道不能在无效 embedding 时以同分抢占唯一身份。
- 不变：已提交结果冻结、公共编号方式、ASR 原文与 token/ITN 来源关系、public callback 顺序、final / last / complete、session 生命周期、模型和所有上述参数。原生 UNKNOWN 时间区间仍保留；原句有限补全仍必须 `speakerInferred=true, confidence=0`。
- 不处理：不按四人答案强行指定聚类数，不绕过 VBx，不降低建档阈值，不改模型或隐藏未知。不能把本补丁描述成身份精度修复。

## 第一个错误状态及后续放大

| 层 / 时刻 | 固定输入的状态 | 结论 |
|---|---|---|
| 首个窗口 0–10 秒 | channel 1 覆盖第一人 1.145–2.292 秒，共 68 个干净帧；channel 2 覆盖第二人 4.891–7.338 秒，共 145 帧 | 两人已经在分割中分开；第一人不足现有 `0.2 * 589` 建档条件 |
| 首次预览约 10 秒 | 仅 channel 2 的 embedding 可建档；`train.size()==1` 分支却把所有活跃 channel 都写成 0，产生 `[-2,0,0]` | **最早可复现的实现错误**：单一建档被扩散给另一个声道；发生在 UI / SDK 文本对齐之前 |
| 2–12 秒窗口 | channel 1 同时包含第一人尾部和第三人开头，二者被池化成一个 embedding | 本地轨道并非总是真实人物；不能无条件将本地不同轨道作为全局身份真值 |
| 最后六窗口建档 | 10 个训练 embedding，AHC 分成 3 组；第一人没有独立合格训练向量 | 建档筛选已经不足以独立建立四人的身份 |
| VBx 第 4 / 11 次迭代 | 第 4 次把第四人的两个向量分给第三人所在组；第 11 次所有训练向量的最高后验都相同；第 15 次仅一个 prior 大于 `1e-7` | **剩余主要准确性 bottleneck：短会话的建档与全局聚类** |
| 最终时间线重建，首个错误帧 1.14471875 秒 | 已知身份 activation 全为 0，但人数估计为 1；旧实现按排序补入 cluster 0 | 第二处实现错误：把“有人说话”变成“这个已知人说话”；约 2.986875 秒没有已知支持的区间被标成已知 |
| SDK / Demo | 原始 `speakerTurns` 就全为 index 0，SDK 与页面忠实传递；各句尾部有限 UNKNOWN 补全带推断标记 | 标点、ITN、直接角色标签及图例不是本次全一人的根因；补全标记不表示整句是推断出来的 |

这里按事件发生次序定位首次预览错误；音频时间 1.14471875 秒则是最终重建中最早的无支持身份帧，两者不要混用。

## 因果证据与排除项

1. `native-regression-both-red.log`：两个独立断言在修复前失败，分别捕获单建档扩散和零 activation 帧被命名；不依赖文字或期望人数。
2. `online-baseline-parity.json`：生产 Session、身份历史、预览和 finish 使用原始完整到达顺序回放，最终 `utterances / speakerTurns / speakerCount / isSessionFinal` 与手机逐字段相同。`online-final.json` 使用相同输入与时序，仅替换本次 native 实现，冻结和文字守恒断言通过。
3. `official-cluster-audit.json`：同一批训练 embedding、同一锁定 PLDA 和官方 VBx；AHC、最终 hard labels 一致，PLDA 最大差 `3.27e-14`，后验最大差 `3.53e-25`。官方也只保留一人，排除了 native PLDA/VBx 移植计算错误，**不因此宣称分割模型能力不足**。
4. `segmentation-parity.json`：同 PCM 的六个窗口，CPU ONNX 与手机分割差异为 0 帧。`embedding-parity.json`：CPU 与 XNNPACK embedding 最大差 `1.431e-6`；替换后 `cpu-native-baseline.json` 的人数和 hard labels 不变，排除了手机执行后端导致此次塌缩。
5. MOSS 只收到原音，不收到人数、SDK 标签或答案；辅助输出四段约 1.11–2.32 / 4.88–7.34 / 9.98–12.24 / 14.61–16.81 秒，与用户“四人轮流一句”的描述一致，无重叠。保存 `moss-annotation/`、`moss-run.json`、模型及工具哈希；辅助标注不是精确边界人工真值，不用它计算正式 DER。
6. 基线 pending 最大 0、native in-flight 最大 1、音频延迟最大 700 ms，finish 到 complete 740 ms；无超时。本次不是积压或等待 120 秒未满，finish 已处理尾段。

## 修复与现有验收

修改生产文件：`asr/harmony/sdk/src/main/cpp/community_cluster.h`，Harmony 与 Android 共用。回归文件：`asr/tools/tests/test_harmony_community_native.py`。

- 单建档只跳过 AHC / VBx，继续走现有 constrained assignment；其他活跃声道不直接继承该身份。
- 静音声道的排序分数始终低于活跃声道，避免 zero/NaN embedding 产生同分抢占。
- 重建只选有正 activation 的已知身份；人数证据超出已有身份支持时，用匿名轨道保留语音和 overlap，不删除语音，不强行分配身份。

| 样例 / 检查 | 结果 | 适用范围 |
|---|---|---|
| 原生 8 项回归 | PASS | 单建档、已知/未知交替、已知声学支持、overlap、cap、时间轴、资源边界 |
| SDK 52 项回归 | PASS | 预览/定稿冻结、公共编号、标点/ITN 对齐、文本 span 与推断标记 |
| 此次 19.58 秒在线回放 | **身份 FAIL** | 旧最终 ID 为 `[1,1,1,1]`；修复后为 `[1,1,1,UNKNOWN]`，前三人的误认仍存在 |
| 之前 102.38 秒四人原录音 | PASS，无最终结果变化 | 同到达顺序回放；文字、ID、spans、UNKNOWN、overlap、speakerTurns 全部相同，见 `adjacent-four-comparison.json` |
| 之前 47.82 秒单人原录音 | PASS，native 无变化 | 旧日志缺少 processed clock，拒绝伪造在线回放；只比较同输入 native labels / turns，见 `adjacent-single-native-comparison.json` |

生产修复提交 `4d4727f1`，签名中英诊断包通过 Harmony 构建、构建身份、授权、签名链和模型哈希校验。Mate80 使用这份原 PCM、同一会议模式做了一次最小复验：

| 检查 | 真机结果 |
|---|---|
| 输入和中间模型结果 | WAV / PCM 哈希相同；全部 6 个窗口起点、有效结尾、分割、embedding 与原现场逐值相同 |
| 公开结果与在线回放 | 逐字段相同，包括 speakerTurns、文本 spans、推断与最终状态 |
| 页面 | `[说话人 1, 说话人 1, 说话人 1, 不确定]`；**四人身份体验 FAIL** |
| 无支持已知身份 | 原先错误命名的 2.986875 秒声学区间保留为 UNKNOWN；原句有限补全仍可能有推断，不隐藏原始 turns |
| 单窗口推理 | 平均 541.02 ms，最大 611.78 ms |
| 队列 / 音频延迟 | pending 最大 0，in-flight 最大 1，完成窗口最大音频延迟 480 ms |
| finish / 生命周期 | finish 到 complete 752 ms；finish 前 last=0，之后恰好 1 次 last 再 1 次 complete，无 error、无非 last 空 final |

证据：`device-fixed/build-identity.json`、`device-fixed/metrics.json`、`device-fixed/public-result.json`、`device-fixed/ordered-events.json`、完整诊断 ZIP 内的输入映射 / hilog / `resource-samples.csv`，以及 `screen-final.png`、`layout-final-tail.json`。短音频文件回放不能证明长时 RSS 平台或整体实时能力。原失败现场、中间失败测试日志和拒绝不完整在线回放的日志均保留，不用后续 PASS 覆盖。

## 未解决范围与合入阻断

四人正常轮流说短句仍未达到身份准确性要求。修复后的 UNKNOWN 增多是撤回无证据归属，不能作为四人分离成功的证据。不能通过缩到 60 秒、延长 timeout、改变 hop、强制四类、提前截断 VBx 迭代或修改文案结案。

后续需要针对独立短句身份的证据获取、建档和跨窗口聚类设计可验证的修复；必须同时保护单人不重复建档以及多人短句可区分。现有固定筛选排除了第一人的独立短句，现有固定 VBx 又合并其余三组；仅修 SDK 对齐/调度无法恢复缺失的身份。当前补丁保持候选状态，身份体验红灯期间不运行重复发布矩阵、不合入。
