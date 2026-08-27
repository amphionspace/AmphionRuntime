# Android / HarmonyOS ASR 0.3.11 对齐清单

本文约束 Android 非 Demo 能力对齐 HarmonyOS 0.3.11 的范围和发布条件。版本号只表示通过本清单的
正式交付身份，不能用 Demo 页面可见、代码已编译或单一真机识别成功代替 SDK 契约验收。

## 要改变的行为

- Dingqiao Android 适配层开放与 HarmonyOS 同名的 Runtime 日志等级配置，并在
  `prepareRuntime` 初始化 Core Runtime 时生效。
- short/long、连续识别、声纹评分、Speaker VAD、警务增强和生命周期行为按同名公共参数验收。
- 补齐 Android 缺失且被本版本声明支持的公共类型、诊断交付、模型身份和发布证据。
- 若某项 HarmonyOS 能力无法在 Android 离线实现，必须在公开文档和版本说明中明确列为平台差异，
  不得暴露无实现接口、填充假结果或用网络实验服务冒充端侧能力。

## 必须保持不变的行为

- `isFinal=true` 只表示 utterance/endpoint final；`isLast=true` 只表示整个 session 的最后结果。
- 普通连续识别在调用方 `finish(sessionId)` 前不得出现 `isLast=true`；正常结束恰好一次 last，随后
  恰好一次 `onComplete`；`cancel` 不产生 final/complete。
- `onStart` 对外回调前 session 和会话级配置已经发布，允许回调栈内同步 `writeAudio`、`finish`、
  `cancel`。
- `speakerSimilarity` 仅来自当前非空 final 的真实 PCM；无有效声纹 ID、无语音证据或技术上无法
  生成 embedding 时省略，不填假分数。
- AGC 只影响 ASR 输入；VAD、初始起音、声纹和 Speaker VAD 继续使用原始 PCM。
- 日志和诊断只能观察运行状态，不得进入识别控制路径或改变回调顺序。

## 本轮明确不处理

- HarmonyOS 预留但没有商用模型的目标说话人增强；Android 不增加不可用开关。
- ASR 文本精度、声纹 target/non-target 阈值和说话人聚类精度不与生命周期门禁混为同一结论。

## 当前核对结果

| 能力 | Android 当前状态 | 结论 |
| --- | --- | --- |
| short/long 与 stable-prefix | Core 已有同源 native 语义；本分支补会话参数、场景映射和门禁 | 待真机 |
| 声纹校验 | Android/HarmonyOS 构建均使用 `shared/models/asr/dingqiao/eres2net.onnx`，公共字段使用 `speakerSimilarity` | 待组合真机 |
| Speaker VAD | Android 在 decoder 串行路径同步评分，不存在 HarmonyOS 异步 hop 乱序路径 | 待换人边界真机 |
| Police 基础规则 | 车牌、派出所、警务术语公共资产逐文件一致 | 已对齐 |
| Police 人名纠正 | Android/HarmonyOS 构建均使用 `shared/models/asr/police/lac/v1/lac_encoder.onnx`，LAC/CRF/字典/拼音资产逐文件一致，按 `sysGeneralLexicon` 做 PER 门控同音纠正 | Debug/Release 单测与哈希通过，待真机 |
| Runtime 日志 | 本分支补 `setLogLevel`，同时覆盖 license 校验和 Runtime 准备 | 单测通过 |
| 公共 API 兼容 | 补 `getWorkPath`、`SINGLE/CONTINUOUS` 别名、参数默认值和非空授权消息 | 单测与接口对照通过 |
| Diagnostics SDK | 独立 diagnostics AAR；schema v2、匿名会话、WAV/timeline/callback、资源采样、崩溃 journal 与 model/build identity 已补齐 | 单测与 AAR 隔离检查通过 |
| Speaker Diarization | 独立 JNI 使用相同 pyannote powerset mask 与 `eres2net`；Android/HarmonyOS 构建均使用 `shared/models/asr/dingqiao` 中的模型和许可证；10s/2.5s 离线分窗、重叠说话、在线/全局聚类和 finish 双路屏障已接入 | Debug/Release、状态机及 fat AAR 结构通过，待离线真机 |
| 生命周期释放 | 本分支补 finish 后 shutdown/relicense drain 用例与有界释放 | 单测通过，待真机 |
| 版本/交付身份 | Android 正式版本暂保持 0.3.3，必须在最终真机门禁完成后再冻结为 0.3.11 | 正确冻结 |

代码、模型、公共 API、文档和交付脚本缺口已经关闭；Debug/Release/Diagnostics 软件门禁及预览
fat AAR 结构验证通过。当前 ADB 未发现设备，剩余项属于真机发布门禁。在全部门禁完成前，不把
Android 制品命名或描述为正式 0.3.11。

## 0.3.4–0.3.11 反向版本审计

| HarmonyOS 版本 | 主要变更 | Android 对齐证据 |
| --- | --- | --- |
| 0.3.4 | 警务术语短 final 定向修复 | Police CSV/FST/gazetteer 逐文件哈希与 HarmonyOS 一致 |
| 0.3.5–0.3.6 | 可配置 endpoint、连续会话恢复、稳定模型回退 | endpoint/fresh-stream 使用共享 Core 状态机；Android manifest 固化源模型 SHA，最终软件门禁通过 |
| 0.3.7–0.3.8 | Speaker VAD 收口、长会话边界、编译期 Diagnostics | 共享 Core 修复已在基线；独立 diagnostics AAR、崩溃恢复与 schema v2 已补齐 |
| 0.3.9 | Runtime 日志等级 | `setLogLevel` 覆盖授权验证和 Runtime 准备，默认 `WARN` |
| 0.3.10 | 无独立公开发布节 | 无额外公共契约需迁移 |
| 0.3.11 | short/long、Speaker VAD 短句、LAC 人名、端侧 Speaker Diarization | 共享 native short/long；LAC 和说话人模型逐文件哈希；公共类型、回调与 finish 屏障已对齐 |

Android 与 HarmonyOS 使用不同 ONNX Runtime 版本和目标格式，ASR ORT 产物不要求
字节相同；它们必须绑定同一源模型身份，并在正式组包时由同一最终提交的
provenance 再校验。这是发布身份门禁，不是用跨平台二进制哈希代替功能对齐。

## 发布门禁

| 能力 | Android 0.3.11 发布要求 |
| --- | --- |
| short/long | 两种模式参数优先级、Rule3 语义和 long stable-prefix 真机门禁通过 |
| 生命周期 | start-write、finish-shutdown、finish-shutdown-relicense、cancel、重入和恢复通过 |
| 声纹/Speaker VAD | 短句逐 final 出分资格、vadBegin 组合、换人边界和恢复通过 |
| Police | Android/Harmony 基础词典与 LAC 资产逐文件哈希一致；人名 matcher 与真机 LAC 推理通过 |
| 日志/诊断 | `setLogLevel` 单测通过；Diagnostics 构建与普通构建隔离，导出失败不影响 ASR |
| Speaker Diarization | 离线、断网可用；配置、增量更新、最终结果、finish/cancel 和降级契约通过 |
| 模型/交付 | AAR、APK、模型 manifest、版本、授权和构建 commit 由同一 provenance 绑定 |

## 真机发布门禁

- 在同一最终提交构建并安装 Debug APK；ADB 断网运行普通 short/long、声纹、Speaker VAD、LAC 人名和
  Speaker Diarization。
- Speaker Diarization 必须看到增量 revision、唯一 last、最终 diarization result、随后唯一 complete；
  cancel 不得产生 last/result/complete，finish timeout 必须明确标记 degraded。
- 执行 `start-write`、`finish-shutdown`、`finish-shutdown-relicense`、纯静音 `vadBegin`、真实语音
  `vadBegin`、短句逐 final 声纹出分和下一 session 恢复。
- 检查普通 Debug/Release AAR 不包含诊断采集开关，diagnostics AAR 导出 schema v2 完整目录并可恢复
  上次进程 active-session journal。
