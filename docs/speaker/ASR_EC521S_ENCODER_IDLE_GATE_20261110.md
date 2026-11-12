# EC521S encoder IDLE 门控：证据、修复与待验收状态

记录日期：2026-11-10（Asia/Shanghai）。本文是内部脱敏技术记录，区分历史实验、当前源码修复、主机验证和设备验收。只保存计数、哈希、状态和证据位置；不复制客户音频、识别原文、license、签名密码或密钥。

| 维度 | 当前状态 | 已有证据及边界 |
| --- | --- | --- |
| 接口契约 | **所测接口项通过** | SDK 119/119 单测；新包 checkpoint、IDLE finish、限定热词边界通过；三项 Dq 契约通过。识别失败的短夹具也有双方 last=1、stopped=1、errors=0。此结论仅覆盖所测项，不表示公共热词 API 整体通过。 |
| 识别 | **三次严格文本对照均 FAIL；真实精度未定** | 短夹具 320 为 24/26 字、16000 为 27/26 字；历史共同输入为 1158/1193 个归一化字符、LCS 未匹配 83/118。没有人工真值，不能把任一 control 当正确原文，也不能将未匹配数称为 CER。 |
| 功耗与温升 | **新包 PENDING** | 历史 USB 输入功率下降只能描述旧实验。当前没有新包的 USB、脱线锁屏温升或稳定功耗测量，不能宣称新包已降低 25%。 |

用户可见体验尚未验收：同 PCM 的门控前后输出存在变化，尚无人工标注判断哪方更准确。当前记录不授予发布资格。文档和证据清单不参与 APK 编译。

## 历史六轮：编排完成，识别问题未闭环

历史证据由[脱敏审计摘要](</private/tmp/ec521s-evidence-audit-h0buvzuv/summary.md>)和[完整审计 JSON](</private/tmp/ec521s-evidence-audit-h0buvzuv/summary.json>)提供。六轮均有 DONE、end、stop_tap、录音 completed/errorCode=null 和 SESSION 汇总；两个编排分别结束于 ABAB_DONE、ABAB2_DONE。后续分析中断不能倒推为六轮录音未完成，完成标志也不能替代 SDK 回调或产品验收。

| 轮次 | APK 组 | 测量时长（秒） | USB 输入功率（W） | 进程 CPU（100%=1核） | PCM 时长（秒） | public finals | 去标点字符数 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| gate1 | armD | 480 | 1.238 | 128% | 509.50 | 18 | 1006 |
| ctrlx1 | armC | 480 | 1.718 | 204% | 520.56 | 16 | 1203 |
| gate2 | armD | 480 | 1.297 | 128% | 509.10 | 18 | 1005 |
| ctrlx2 | armC | 480 | 1.727 | 200% | 517.96 | 16 | 1203 |
| gate3 | armD2 | 480 | 1.275 | 133% | 525.40 | 18 | 1191 |
| ctrlx3 | armC | 480 | 1.725 | 203% | 520.36 | 16 | 1203 |

| 对照对 | USB 输入下降 | CPU 下降 | 文本相似度 | control/gate 未匹配字符 | 最长连续 control 未匹配 |
| --- | ---: | ---: | ---: | ---: | ---: |
| ctrlx1 / gate1 | 27.91% | 37.25% | 0.856496 | 257 / 60 | 125 字 |
| ctrlx2 / gate2 | 24.90% | 36.00% | 0.855978 | 258 / 60 | 125 字 |
| ctrlx3 / gate3（D2） | 26.08% | 34.48% | 0.918964 | 103 / 91 | 11 字 |

旧表先用 Unicode `isalnum` 保留字符，再使用 `SequenceMatcher(autojunk=False)`。这些字符数包含替换对应的未匹配字符，不能等同纯删除数或 CER。纯删除分别为 gate1 192 字、gate2 193 字、gate3 22 字。旧 gate1/2 最大纯删除均在 control 去标点字符偏移 `[98,223)`，位于第 3 个 public final，属于前部缺口；没有可靠的字符到音频时间映射，不能给出缺字的精确秒数。

六轮共同前缀 509.10 秒的 PCM 哈希一致，每轮完整 PCM 都是源输入的逐字节前缀，但完整录音时长不同。三个 control 的原始拼接结果一致。缺少样本到测量墙钟的映射，因此不能证明每个 480 秒功率窗口覆盖完全相同的输入样本。

USB 功率按 seg1 的 `ibus_ma × vbus_mv` 样本均值统计；CPU 按整窗进程节拍差分统计。它们不是完整录音的能耗，也不是脱线锁屏一小时的温升结果。线程快照只有中间 60 秒，不能直接与整窗 CPU 相加。

历史 APK 身份：

| APK 组 | SHA-256 | Gate / EnergyProbe |
| --- | --- | --- |
| armC | `6f54e6087e769c2d971b4bec74768838f164ffca680dd4c035d0cc174a2a6f9c` | 无 / 无 |
| armD | `245de663e796af67b1a86804af2733cc0af666c184993763a9ef6168ac5ac219` | 有 / 无 |
| armD2 | `f3e24f14fa7a62bc0cf46387e7f2332e05b39bf1d6be45e40598de007ef47eeb` | 有 / 有 |

armC、armD、armD2 的 ASR sherpa JNI、ONNX Runtime、audio-processing 库、Manifest 和公开签名证书哈希相同。但是 armC 的 diarization JNI、police JNI 与 D/D2 不同，且 armC 不包含 D/D2 中的四个 sortformer 模型；D/D2 的 native 和模型集合则逐项相同。日志不足以证明每轮最终加载的全部模型与配置一致，所以 control 与 gate 的历史对照不能作为只改变 IDLE gate 的单变量实验。这里记录混杂因素，不涉及修改 Sortformer。

历史安装编排可以关联 armC、armD、armD2 候选，但缺少每轮已安装 APK 的逐字节哈希以及嵌入的源码指纹，严格的提交→APK→当时设备安装身份链仍不完整。后续旧包回归已单独核对安装哈希，不补充历史六轮当时缺失的证明。

## 本轮修复范围与不变量

运行时代码基线为 `a8c79ee260f86968076bcf37fc8627695fd6e37c`。只读核对时实际 Git HEAD 是它的后继 `32b363c79d89bd8bfbeb309d97562faee947085b`，后继提交仅更新授权交付历史，没有 runtime 源码改动。本轮源码为该 HEAD 上的未提交修改；最终身份须使用下面五个相关代码文件的完整 SHA-256，不能把主 APK 直接标为干净的 `a8c79ee2` 构建。

| 代码文件 | 修复或验证内容 | SHA-256（16000 补测包源码） |
| --- | --- | --- |
| [SessionImpl.kt](<<LOCAL_PATH>>) | IDLE 按能量边界切片；限制 IDLE 流边界；清理热词替换状态；模式变化先恢复预滚。 | `d503073cbc35d92144ecd2defb0b555d4883b29c652f3780a16dbaefc7c249e4` |
| [IdleEnergyProbe.kt](<<LOCAL_PATH>>) | 固定 20 ms 窗、跨调用累计、processed PCM 能量、独立绝对或相对唤醒。 | `4d5aa1a976280f146f30005fb87bca774f323f93d3760633d65cf139e0790d4c` |
| [EncoderIdleGate.kt](<<LOCAL_PATH>>) | 更正边界与计数注释，说明新流 800 ms 预热和预滚重送口径。 | `57ba27d2dfa6a53aa4a42a21631439c16ff6309ea8a164ccbc12802465b89dee` |
| [IdleEnergyProbeTest.kt](<<LOCAL_PATH>>) | 立即/短起音、不规则分帧、跨调用累计、重新武装等 16 条针对测试。 | `1b9fa87287e24ebb25855cf6243349bfacce1eb54da12412068f468a12799542` |
| [EncoderIdleGateInstrumentedTest.kt](<<LOCAL_PATH>>) | 四项回归及回调摘要；历史 PCM 识别/CPU 诊断与 LCS 脱敏差分。 | `3107e787605db3afb754552746470247eb5d798dc58e1fce4a085f14aa2fdda4` |

四项设备回归所用测试包 `e46eb6…` 的 instrumentation 源码 SHA-256 是 `d4024cf84d16f321047452d6ae0c4cc8ad3b82fd82890112b78b03e8c50eef3d`。随后只在历史方法内新增差分记录，并加入私有纯 helper；其余四个文件完全一致。历史诊断阶段（instrumentation 源码 `fbbfff0c584f1aff39cc39f14b8d121409c1b49d70c106138fbd63288195b962`）的历史方法之前及 `config()` 之后的全部代码均逐字比对一致，覆盖原四项方法、共享 `decode` 和 `Capture`，见[阶段边界证明](</private/tmp/encoder-gate-historical-final.6ow605/summary.json>)。之后针对已证实的 16000 覆盖缺口，只新增 `silenceReplay` 的分区选择，得到上表源码；其他方法、helper 和全部断言均与历史包逐字一致，见[补测范围证明](</private/tmp/encoder-gate-large-chunk-build.MlEXVt/summary.json>)。

具体行为：

1. 能量探测以固定 20 ms（16 kHz 下 320 samples）音频窗为单位，跨调用保留未满窗的能量。`samplesUntilNextDecision` 约束 Session 在覆盖预滚前作出下一次决定，避免合法的 1 秒调用块先覆盖上一块起音。
2. 能量观察实际送入 ASR 的 processed PCM；VAD 仍观察 raw PCM。达到 `-60 dBFS` **或** 比先前噪声底高 `10 dB` 均可唤醒，移除按调用次数预热。稳态可闻环境声会保守唤醒；能量不是语音分类器，也不能证明所有低能量语音都不会漏掉。
3. 仅在确认静音、成功创建新 stream 后进入 IDLE。RULE3 checkpoint 和 soft reset 保留 native 上下文，不得因 generation 变化直接进入 IDLE。新流已经接受 800 ms 合成静音预热，并非字面上的空 stream。
4. 更新热词成功替换 stream 后，清空 gate，解除 probe 武装，并清零旧流 gap 计数。运行时 speaker 模式等使 `encoderIdleAllowed()` 变为 false 时，`feedAndDecode` 先调用 `resumeEncoderFromIdle("policy-change")`；恢复失败则停止本次喂入。
5. `idleSamples` 是 **IDLE 期间接收的样本数**，包含之后可能通过 pre-roll 重送的样本，不能直接换算为净节省的 encoder 工作量。

## 主机验证与产物身份

旧 probe 的真实红测是 12 条测试中 9 条失败：[日志](</private/tmp/idle-energy-probe-red.XD2XWa/gradle.log>)、[JUnit XML](</private/tmp/idle-energy-probe-red.XD2XWa/IdleEnergyProbeTest.xml>)。随后第一次修复验证遇到并行编辑中的 Session 编译错误，现场保留于[该次构建日志](</private/tmp/idle-energy-probe-green.7mHTpn/gradle.log>)；该目录里的 XML 是旧红测副本，不能计为一次新运行或绿色结果。

最终统一构建使用 Microsoft JDK 17.0.20.1，执行：

```bash
./gradlew --no-daemon :sdk:testDebugUnitTest \
  :samples:dingqiao-demo:assembleDebug \
  :samples:dingqiao-demo:assembleDebugAndroidTest \
  -PdingqiaoDebugUseReleaseSigning=true --console=plain
```

结果：**BUILD SUCCESSFUL，退出码 0；SDK 28 个 suite、119 条测试，0 failures、0 errors、0 skipped；其中 probe 16/16 通过。** [完整日志](</private/tmp/encoder-gate-final-build.QbInur/gradle.log>)、[全部统计与当次源码哈希](</private/tmp/encoder-gate-final-build.QbInur/summary.json>)、[probe 绿色报告](</private/tmp/encoder-gate-final-build.QbInur/junit/TEST-com.amphion.asr.internal.IdleEnergyProbeTest.xml>)均独立保存，全部 28 份 JUnit XML 已归档在同次证据目录。

| 产物阶段 | SHA-256 | 状态 |
| --- | --- | --- |
| 主 APK | `201492970fd0a5278be360859171dfb3c56ce67e4d64006eaacde10c87b74ea2` | 已构建；后续只补测试代码，不重建主包。 |
| 原测试 APK | `efad1d2bffcfb5492b9536b556e2b4c15dab1f7466302e09b63f7c95ba6dea50` | 原设备红测使用的测试包身份，不能混记为后续测试包。 |
| 仅补回调摘要的中间测试 APK | `532535460bd7eda711d2bcb450890ad83175a4ffc9c8bc0cb1784c4a51100129` | 独立归档；未选为最终设备验证包。 |
| 四项设备验证测试 APK | `e46eb6f23f0dcdf4c8b5f7db12b56d31153d8bfa3f297ae624e4a3d580f0b5aa` | 构建和签名验证通过；四项结果为 3 PASS / 1 FAIL，详见下节。 |
| 历史 LCS 诊断测试 APK | `1a618403884a34b82c46b6d1bf3850a376acdde8fb11640c1063eb91404108f1` | 构建和签名验证通过；历史单次 1 test / 1 严格一致性 FAIL，无 skip/crash。 |
| 16000 分区补测测试 APK | `030f9d1ab2afd419b5f6e27c006b1aace2527fec634f693bef485650ce1164c3` | 构建和签名验证通过；独立 16000 分区 1 test / 1 严格一致性 FAIL，无 skip/crash。 |

四项设备验证包只执行 `:samples:dingqiao-demo:assembleDebugAndroidTest`（使用相同 release-signing 开关），12 秒完成、退出码 0。[该测试 APK](</private/tmp/encoder-gate-final-test-build.LodCvW/dingqiao-demo-debug-androidTest.apk>)、[构建日志](</private/tmp/encoder-gate-final-test-build.LodCvW/gradle.log>)及[身份清单](</private/tmp/encoder-gate-final-test-build.LodCvW/summary.json>)独立归档。

历史差分诊断在原四项验证期间完成，仍只执行相同 test-only task，13 秒、退出码 0；[历史诊断测试 APK](</private/tmp/encoder-gate-historical-final.6ow605/dingqiao-demo-debug-androidTest.apk>)、[构建日志](</private/tmp/encoder-gate-historical-final.6ow605/gradle.log>)及[五源码快照/身份清单](</private/tmp/encoder-gate-historical-final.6ow605/summary.json>)独立保存。纯 LCS helper 的实际 Kotlin 代码已通过 8 个边界例及 961 组短字符串穷举对照，见[定向检查输出](</private/tmp/encoder-gate-text-diff-ika49gxo/checks.log>)；这不计入 SDK 119 条，也不替代设备识别检查。

16000 分区补测包仍只运行相同 test-only task，12 秒、退出码 0；[补测测试 APK](</private/tmp/encoder-gate-large-chunk-build.MlEXVt/dingqiao-demo-debug-androidTest.apk>)、[构建日志](</private/tmp/encoder-gate-large-chunk-build.MlEXVt/gradle.log>)和[五源码/范围证明](</private/tmp/encoder-gate-large-chunk-build.MlEXVt/summary.json>)分别归档。

三次 test-only 构建前后主 APK 都是 `201492…`，四个已有修复/单测源码哈希与统一构建一致，未重建主包、未重跑 SDK 单测。三份测试 APK 均通过签名验证，公开证书相同。原四项及三项 Dq 结果绑定 `e46eb6…`，历史结果绑定 `1a618…`，16000 补测绑定 `030f9d…`，不能互换。

[中间测试构建日志](</private/tmp/encoder-gate-callback-build.5rDDia/gradle.log>)和[中间产物身份](</private/tmp/encoder-gate-callback-build.5rDDia/summary.json>)保留。随后历史入口构建的 Gradle 日志虽已输出 `BUILD SUCCESSFUL`，harness 任务在收到暂停指示后被 SIGTERM；[该次日志](</private/tmp/encoder-gate-historical-build.c6KNgO/gradle.log>)及[取消状态和产物身份](</private/tmp/encoder-gate-historical-build.c6KNgO/summary.json>)单独保留，不作为最终设备验证包。热词夹具修正后才产生用于原四项和三项 Dq 的 `e46eb6…` 测试包。

原主 APK 与原测试 APK 的 `apksigner verify --print-certs` 均成功，公开证书 SHA-256 都为 `8d9de5c78e1f31358608f828e61c6240c6f88073591bd0b7d0dfb687ca946698`。[Demo 构建配置](<<LOCAL_PATH>>)在启用 `dingqiaoDebugUseReleaseSigning` 时为 debug 使用 release 签名。没有本地 base/test 证书不一致的证据，未修改签名配置；设备已装 test 的更新冲突必须与设备安装证书单独核对。

## 设备验证：六项边界/契约通过，三次严格文本对照失败

四项定向测试的[设备结果与安装哈希](</private/tmp/ec521s-old-gate-verification-spikmhrq/new-four-gate-tests/result.json>)确认 3 PASS / 1 FAIL；三项 Dq 的[设备结果](</private/tmp/ec521s-old-gate-verification-spikmhrq/new-three-contract-tests/result.json>)和[公开回调轨迹](</private/tmp/ec521s-old-gate-verification-spikmhrq/new-three-contract-tests/dq-report-new.jsonl>)确认 3 PASS。两组都使用主 APK `201492…` 和测试 APK `e46eb6…`。

| 项目 / 方法 | 当前状态 | 结果及范围 |
| --- | --- | --- |
| `continuousCheckpointKeepsEncoderActive` | PASS | 新包 `idleEntries=0`；旧包同目标用例为 4，命中预期断言失败。 |
| `silenceReplayPreservesTextAcrossCallerChunks`：320 samples | **FAIL** | control/gate 文本长度 24/26，exact 断言失败；双方 last=1、stopped=1、errors=0。时间戳断言位于 exact 之后，不能据此称该断言已执行。 |
| 同方法：16000 samples | **FAIL（独立补测）** | `030f9d…` 仅跑该分区一次，control/gate 为 27/26 字，exact 失败。双方 finals=2、last=1、stopped=1、errors=0；后续时间戳断言仍未执行。 |
| `finishWhileIdlePublishesOneTerminalResult` | PASS | IDLE finish 不虚构文本，唯一 last 后唯一 stopped；门控边界验证通过。 |
| `hotwordsReplacementDoesNotInheritIdleAudio` | PASS（限定夹具） | 初始热词选择 beam decoder；换流边界及终态通过。默认 greedy 的独立崩溃仍未修复。 |
| `historicalReplayKeepsRecognition`：共同 509.10 秒输入 | **FAIL** | `1a618…` 单次 control→gate：归一化 1158/1193 字、LCS 1075；双方唯一 last→stopped、errors=0。CPU 工作量下降不替代严格文本一致性。 |
| 三项 Dq 公共契约 | **3 PASS** | `a06_cancel_noFinalNoComplete` 无 final/complete；`a10c_finishIdempotent_singleComplete` 唯一 last→complete；`a11_vadBegin_initialSilenceAutoFinish` 静音自动结束顺序正确。 |
| 新包 USB / 温升 | PENDING | 尚未执行新测量，不从主机单测或单次 CPU 诊断推算功耗收益。 |

旧包检查已有[设备原始汇总](</private/tmp/ec521s-old-gate-verification-spikmhrq/old-results.md>)：`continuousCheckpointKeepsEncoderActive` 命中预期断言失败，`idleEntries=4`（预期 0），这是有效设备红测。旧主 APK 为 `f3e24f14…`，测试载体为 `efad1d2b…`，均由设备端哈希绑定。

### 短夹具的严格差异与 PCM 范围

[短样本脱敏记录](</private/tmp/ec521s-old-gate-verification-spikmhrq/new-four-gate-tests/report-1794263378129.jsonl>)和[门控/endpoint 日志](</private/tmp/ec521s-old-gate-verification-spikmhrq/new-four-gate-tests/metrics-filtered.log>)支持对 320 分区的逐段反推：首段 IDLE 输入 24000 samples、回放 16000，省略 `[43520,51520)`（2.72–3.22 秒）；中间 320 samples 全部回放；末段 25280、回放 16000，省略 `[266560,275840)`（16.66–17.24 秒）。两段省略都在人工前后零音频内，未省略实际 fixture PCM。净省略 17280 samples=1.08 秒；`idleSamples=49600` 是含回放的 3.1 秒 IDLE 输入，不能当作净节省，更不能直接当 CPU/功耗下降。

主 APK 的 sherpa JNI SHA-256 为 `c906b3687c5238481cbd61255708183fa564b25e9572afbd9db08d9bbaccbac8`，已核对与[实际匹配的 derived JNI](<<LOCAL_PATH>>)逐字节相同。该模型以 640 ms 推进，1 秒预滚不保证 native 状态等价；日志中 control 额外的 Rule1 硬换流是首部两字差异的候选机制，不能由此证明识别质量高低。该次 Rule1 的精确 publicSamples 未被记录，不把推导时刻当实测。严格一致性仍为 FAIL；不能通过替换对照基线或放宽断言把该次 FAIL 改为 PASS。

[16000 单次设备结果](</private/tmp/ec521s-old-gate-verification-spikmhrq/new-large-caller-chunk/result.json>)及[脱敏记录](</private/tmp/ec521s-old-gate-verification-spikmhrq/new-large-caller-chunk/report-1794265332238.jsonl>)确认严格失败。补测的 control/gate 为 27/26 字，离线 LCS 匹配 26，control `[18,19)` 为单字未匹配；gate 的原始文本哈希与 320 gate、无人工前后静音的 checkpoint 结果相同，26 个时间戳也与 320 gate 完全相同。这说明本夹具的 gate 输出跨两种分区稳定；control 自身却为 24/27 字，因此任一对照都不能替代人工真值。上述诊断不改变三次严格失败，短夹具 CPU 数值不用于功耗推断。

[最终跨分区脱敏对齐](</private/tmp/ec521s-old-gate-verification-spikmhrq/short-chunks-alignment.json>)补齐了早期证据边界：原 320 的 JUnit compact comparison 省略了部分公共字符，当时不能从显示片段确认完整差分；随后利用 16000 的完整差分在内存中重建，并与两侧以及 320 的原始文本 SHA-256 闭合，才确认精确归一化长度 24/26、LCS=24，gate 仅在 `[0,2)` 多两字。control 从 320 到 16000 在后者 `[0,2)`、`[18,19)` 共新增三字。本次短样本补充分析使用 Unicode `isalnum`，LCS 计数与 `SequenceMatcher(autojunk=False)` 一致；没有重新运行 320 或保存原文。已保存时间戳的离线检查均有序且在声明范围内，仍不表示原用例中被 exact 阻断的范围断言已经执行。未记录逐 final 文本边界，不能从 callbackTrace 推断文字属于哪一条 final。

为补齐 320 失败后未执行的 16000 分区，仅给 `silenceReplayPreservesTextAcrossCallerChunks` 增加可选参数 `encoderIdleCallerChunk`。缺省依次为 320、16000；显式值必须为 `320` 或 `16000`，其余值通过 `require` 拒绝。补测明确选择同一方法并传 `-e encoderIdleCallerChunk 16000`，不重跑 320 或已通过用例。原 exact、时间戳和 IDLE 断言均保留，若 exact 再次失败只可对已保存时间戳独立诊断，不能声称后续断言已经运行。

### 独立未修复问题：默认 greedy 模式动态新增热词崩溃

旧热词用例发生 native `SIGSEGV/SEGV_MAPERR`，fault address `0x58`，未到达门控边界断言，不能算作预期红测通过。[保留的崩溃栈](</private/tmp/ec521s-old-gate-verification-spikmhrq/old-hotwords/crash-filtered.log>)显示 `SessionImpl.updateHotwords` → `OnlineRecognizer.createStream` 的 native 路径。[公开 updateHotwords 注释](<<LOCAL_PATH>>)未声明必须在创建 engine 时预先配置热词；而 [EngineImpl 的 decoder 选择](<<LOCAL_PATH>>)根据初始热词是否为空固定为 `greedy_search` 或 `modified_beam_search`。native 静态审查支持空 BPE 指针路径，但尚未对该 APK 作符号化，不能把候选机制表述为已完整定位或已修复。

本轮只把热词测试夹具改为创建时 `config().hotwords(listOf("初始"), 1.5f).build()`，保留 `session.updateHotwords(listOf("测试"), 1.5f)` 和原有边界断言，以便验证支持热词的 decoder 下的门控换流状态。没有修改 native、默认 decoder 或公共 API。旧包已升级，不回切重跑；因此热词换流只有代码证据及新包验证，缺少旧包目标断言复现，不称为完整红绿闭环。该路径的新包用例通过也不表示热词 API 整体通过或 greedy 崩溃已修复。

回调摘要只记录 `finals`（含 last）、`lasts`、`stopped`、`errors` 数量及有序 `callbackTrace`；不保存文本或错误对象内容。热词用例保留停止前的边界记录，避免终态写入掩盖旧包的边界失败。

### 历史共同输入的单次诊断：严格一致性失败

[历史设备结果及安装身份](</private/tmp/ec521s-old-gate-verification-spikmhrq/historical-common-replay/result.json>)和[完整脱敏记录](</private/tmp/ec521s-old-gate-verification-spikmhrq/historical-common-replay/report-1794264838973.jsonl>)确认 1 test / 1 exact FAIL，无 skip/crash；运行于 2026-11-10 10:42:40（UTC+08:00）结束，driver 整次墙钟 289.253 秒。下表 CPU/elapsed 只统计各次输入至 stopped 的区间，不包含模型创建和 LCS 对齐。

| 指标 | control | gate |
| --- | ---: | ---: |
| 归一化字符数 | 1158 | 1193 |
| LCS 匹配字符数 | 1075 | 1075 |
| 未匹配字符数 | 83 | 118 |
| 最长连续未匹配 | 8 | 9 |
| finals（含 last） | 21 | 20 |
| last / stopped / errors | 1 / 1 / 0 | 1 / 1 / 0 |
| 进程累计 CPU（ms） | 318163 | 211213 |
| 输入至 stopped 墙钟（ms） | 168142 | 113672 |

累计 CPU 时间下降约 **33.6%**、该区间墙钟下降约 **32.4%**。这是同主 APK、同一 engine、同 PCM、固定 control→gate 顺序的单次工作量诊断，有顺序、缓存和进程噪声限制；不是 USB 功耗或温升结果。gate 的 `idleEntries/resumes=22/22`，`idleSamples=3677120`（229.82 秒）仍包含随后回放的样本，不能视为净省略或净节省。

新差分采用 LCS + `Character.isLetterOrDigit` code points，旧表采用 `SequenceMatcher(autojunk=False)` + Unicode `isalnum`；不能直接比较相似度或最长差异便宣称旧 125 字已经逐字恢复。双方仍有未匹配字符，且无人工真值，真实精度未定，当前不满足可发布验收。 历史 flattened token 数量为 1206/1239，与归一化字符数不同，不能把 LCS 字符区间直接用作时间戳索引。

历史诊断方法为 `historicalReplayKeepsRecognition`，参数 `encoderIdleReplayPath` 指向 app 私有的 16 kHz、单声道、little-endian PCM16 文件，不增加前后静音。设置 RULE3=-1、VAD endpoint=800 ms、chunk=320；同一 engine 内先 control、后 gate。共同输入为 8,145,600 samples、16,291,200 bytes、509.10 秒，SHA-256 `02f020ed70554a81deea6b37d77509b7e748b6677e29444ebf981d81d2bb64ac`。缺参时 Assume 跳过，因此原四项设备选择必须明确列出四个方法，不得把新增入口的 skipped 当成 PASS。

历史差分只在内存中保留 Unicode letter/digit **code point**（`Character.isLetterOrDigit`），不折叠大小写，再用动态规划求最长公共子序列（LCS）；相同长度分支固定先推进 control。日志只输出归一化字符数、匹配及双方未匹配计数、最长未匹配段、0 基半开未匹配区间 `[start,end)`，不输出对应字符。`equal` 表示归一化相等，`rawEqual` 表示完整原文精确相等；最终用例仍要求 raw exact 相等，不以归一化相等替换。该差分以 control 为参照，仍不是 CER 或人工准确率。

CPU 指标从输入前计到 `capture.awaitStopped()` 之后，使用 `android.os.Process.getElapsedCpuTime()` 和 `SystemClock.elapsedRealtime()`，覆盖全进程（含 ORT 线程）并排除 engine 模型创建。结果用于同输入下工作量诊断；固定顺序、单次重放和进程噪声仍有限制，不是新的 USB、稳定功耗或温升基准。历史用例比较完整文本时只让断言暴露布尔差异，避免 JUnit 失败信息泄露客户原文。

[设备最终汇总](</private/tmp/ec521s-old-gate-verification-spikmhrq/new-results.md>)确认新包共 9 次选定执行：6 PASS、3 次严格文本 FAIL，均无 skip、crash 或 timeout；这不包含旧热词夹具的崩溃。[最终安装身份复核](</private/tmp/ec521s-old-gate-verification-spikmhrq/final-installed-identity.json>)于 2026-11-10 10:59:27（UTC+08:00）再次确认主 APK `201492…`、测试 APK `030f9d…`；7 个预期旧/新门控报告目录全部保留，所有验证后台任务均已收集。

原始失败现场和审计目录保留，不清理、不覆盖。[仓库脱敏证据清单](<<LOCAL_PATH>>)只保存身份、状态和证据位置，不归档客户载荷或凭证。
