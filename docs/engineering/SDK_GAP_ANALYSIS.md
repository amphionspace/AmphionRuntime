# AmphionRuntime SDK 差距分析

2026-10-19 · 对照 [SDK_TARGET_SHAPE.md](SDK_TARGET_SHAPE.md) · 基准提交 `033435e8`

> 本文只核对目标文档九个维度在当前仓库里的实际状态，结论全部附可复核的证据路径。精度、性能和客户验收状态不在本文范围内。

## 结论

差距集中在**契约与分层**，不在功能完成度。功能面已经相当完整——诊断 SDK 随包交付、客户错误码三端一致、升级说明齐备、Demo 展示语义已对齐；缺的是让这些成果可以被机器验证、且不随平台数量线性复制的结构。

| # | 维度 | 状态 | 一句话 |
| --- | --- | --- | --- |
| 1 | 契约即代码 | 未达标 | 5 份手写接口文档，无生成器；内部错误码已在三端间漂移 |
| 2 | 核心逻辑只写一次 | 未达标 | 角色分离在两端各写一遍（2647 / 3622 行），无共享内核 |
| 3 | 生命周期状态机 | 未达标 | 无显式状态机，约束分散在各端 gate 文件与散文契约里 |
| 4 | 不确定性进公共契约 | 部分达标 | 字段三端都实现了，但不在跨端 canonical 契约中 |
| 5 | 可自证 | 部分达标 | 诊断 SDK 已交付；证据清单做过一次没有延续 |
| 6 | 调用方体验 | 部分达标 | 升级说明、平台差异、Demo 语义都到位；上手成本未测量 |
| 7 | 版本与承诺 | 部分达标 | 弃用流程有实例；冻结／演进／实现细节三层未明文划分 |
| 8 | 健康度指标 | 未达标 | 六项指标 0 项达标，2 项从未测量 |
| 9 | CI 结构 | 部分达标 | 鸿蒙有 64 个测试且进 CI，但挂在 "Android SDK CI" 下 |

## 已经达标的部分

先列这些，因为它们决定了后面每条差距的真实代价。

- **客户可见错误码三端一致。** `1002200001`–`1002200035` 在 Android、鸿蒙、iOS 三端代码里完全相同（各 22 个码，iOS 与鸿蒙逐码一致）。Android 多出的 `1002200036` / `1002200037` 已标 `@Deprecated`，差异写进 `delivery/harmony-dingqiao/docs/HARMONY_DIFFERENCES.md`。这是目前做得最干净的一块契约。
- **参数契约已经进 CI。** `shared/api-spec/dingqiao-asr-parameters.json` 由 `asr/tools/dingqiao_parameter_contract.py` 驱动，被 `.github/workflows/android.yml` 和 `asr/tools/tests/test_ios_dingqiao_contract.py` 引用。这是「契约即代码」在仓库里唯一真正落地的一段，可以直接作为扩展模板。
- **跨端黄金向量已有雏形。** `asr/android/sdk-dingqiao/src/test/.../CommunityHarmonyParityTest.kt` 读取抓取自鸿蒙的提交决策（资源文件 `community-harmony-42911432-commits.txt`，5 条），断言 Android 实现复现同样的映射结果。做法完全正确，只是规模还是 5 条。
- **诊断能力已经是交付物。** `Amphion-ASR-Diagnostics-SDK.zip` 出现在交付产物清单里，三端均有 Diagnostics 模块（如 `asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/DiagnosticsModule.ets`）。
- **鸿蒙逻辑有真实测试覆盖。** `asr/tools/tests/` 下 90 个测试中 64 个是 `test_harmony_*.py`，由 `android.yml` 以 `python3 -m unittest discover -s asr/tools/tests -p 'test_harmony_*.py'` 执行。鸿蒙没有 ArkTS 原生单测，但不等于没有门禁。
- **升级说明成体系。** 仓库里有 19 份 `UPGRADE_*.md`，覆盖 0.3.6 至 0.3.24。

## 1. 契约即代码 — 未达标

**目标**：一份机器可读契约，手写接口文档 0 份，三端常量／客户文档／校验／用例全部生成。

**现状**

手写接口文档 5 份（排除 `.cache`）：

| 文档 | 行数 |
| --- | --- |
| `asr/docs/api/语音识别SDK接口-20260622.md`（跨端 canonical） | 905 |
| `asr/android/docs/customer/语音识别SDK接口.md` | 381 |
| `asr/android/docs/customer/语音识别SDK接口-交付批注版.md` | — |
| `delivery/harmony-dingqiao/docs/语音识别SDK接口.md` | 569 |
| `tts/docs/api/语音合成SDK接口.md` | 678 |

全仓没有任何代码生成器（按 `codegen` / `generate.*errcode` 搜索无结果）。

**内部错误码已经漂移。** `shared/api-spec/errcodes.yaml` 定义 33 个码，`AsrError.kt` 20 个，`AsrError.swift` 17 个。iOS 与契约一致；Android 有 7 个码在同一数字上表示不同含义：

| 码 | 契约 / iOS | Android `AsrError.kt` |
| --- | --- | --- |
| 1002 | InvalidSampleRate | SDK_NOT_INITIALIZED |
| 1003 | SdkNotInitialized | SESSION_ALREADY_CLOSED |
| 2001 | ModelDirInvalid | LANGUAGE_UNAVAILABLE |
| 2002 | ModelFileMissing | ASSET_INSTALL_FAILED |
| 2003 | ModelLoadFailed | STORAGE_INSUFFICIENT |
| 3001 | SessionAlreadyClosed | DECODE_FAILED |
| 3002 | SampleRateMismatch | POSTPROCESS_FAILED |

`AsrError.swift` 第 3 行注释写「与 Android 完全一致的错误码段」，与上表不符。

**声称存在的门禁不存在。** `errcodes.yaml` 头部写明「CI 中：Android `:sdk:test` 解析本文件校验 `AsrErrorCode` 常量；iOS `Test/AsrErrorCodeTests` 校验 enum」。仓库里搜不到任何 `*ErrorCode*Test*` 文件，也没有任何代码文件引用 `errcodes.yaml`（唯一一处是 `AsrError.swift` 的注释链接）。同目录的 `README.md` 则写明「当前没有由此 YAML 自动生成并在编译期完整校验的链路」——两份文件自相矛盾。

**客户码不在契约内。** 客户实际看到的 `1002200xxx` 码空间完全不在 `shared/api-spec/` 里，只活在 Markdown 和三端各自的常量文件中。被称为 single source of truth 的 `errcodes.yaml` 管的是一个客户看不见的内部码空间。

**差距**

- 需要生成器：0 个 → 至少 1 个
- 需要纳入契约的码空间：客户码 `1002200xxx`（35 个）目前 0 覆盖
- 需要修复的漂移：7 个内部码 + 1 处失实注释 + 1 处自相矛盾的文档声明

**严重度**：内部码目前不直接暴露给客户（客户只见 `1002200xxx`），所以这不是已发生的客户事故；但它证明了「文档声称有门禁、实际没有」这件事在本仓库已经发生过，这正是契约不可执行的典型后果。

## 2. 核心逻辑只写一次 — 未达标

**目标**：判断规则只存在一处，平台层只做类型转换与回调投递。

**现状**

| 实现 | 行数 | 文件数 |
| --- | --- | --- |
| `asr/android/sdk-dingqiao/.../diarization/` | 2647 | 14 |
| `asr/harmony/sdk-dingqiao/.../diarization/` | 3622 | 14 |
| `asr/ios/Sources/AmphionRuntime/Dingqiao/` | 2095 | — |

文件数相同，但模块切分不同，无法逐文件对照 review：

- Android：`DiarizationAlgorithms` + `SpeakerTurnSegmenter` + `DiarizationTranscriptState` + `SpeakerDiarizationLocalClient`
- 鸿蒙：`SpeakerDiarizationGlobalClusterer` + `DiarizationWindowScheduler` + `OnlineSpeakerRegistry` + `SpeakerDiarizationTranscriptState` + `SpeakerDiarizationRuntimeLease`

全仓没有任何跨端共享的判断逻辑层（无共享 native、无共享规则描述）。

**这个结构已经产生过缺陷。** `asr/android/docs/ANDROID_HARMONY_ROLE_PARITY_20260917.md` 记录：Android 用截断把浮点秒转毫秒、鸿蒙用四舍五入，同一尾 token 一端得 15220 ms、一端得 15219 ms，产生负时长尾字并绕过既有的零时长补全。这不是逻辑错误，是同一条规则被实现了两次。

**差距**

- 重复实现份数：2–3 → 目标 1
- 跨端黄金向量：现有 5 条（仅覆盖提交决策映射）→ 需覆盖 2500 ms 补全、600 ms 发射延迟归属、`speakerInferred` 标记、已提交窗口冻结、段落合并
- 新平台接入成本：目前等于重写一遍（iOS 已经是第三次）

## 3. 生命周期状态机 — 未达标

**目标**：命名状态 + 明确迁移 + 恒真不变量，写在共享内核里，用 property test 守护。

**现状**

全仓没有显式状态机。生命周期约束以两种形式存在：

1. **散文契约**：`docs/engineering/ASR_CONTRACTS.md` 的「生命周期」一节，9 条中文约束，全文 54 行。
2. **各端自行实现的 gate 文件**，切分不同：

| 端 | gate 文件 |
| --- | --- |
| 鸿蒙 | `SessionStartGate.ts`、`FinishShutdownGate.ts`、`LatestRequestGate.ts`、`RejectedFinalLifecycle.ts`、`RuntimePreparationState.ts` |
| Android | `RejectedFinalLifecycle.kt`、`RuntimeLifecycleBridge.kt` |

两端只有 `RejectedFinalLifecycle` 一个同名。

公共接口文档里 `isLast` 字段至今挂着 `// TODO待明确字句结束、讲话结束如何标识`（`asr/docs/api/语音识别SDK接口-20260622.md:521`），而内部契约早已把它定义得很精确。**最核心的生命周期承诺没有写在调用方会读的地方。**

无 property test。

**差距**

- 显式状态机：0 → 1
- 散文不变量转成可执行断言：9 条 → 0 条已转换
- 公共文档与内部契约的 `isLast` 定义对齐：未做

## 4. 不确定性进公共契约 — 部分达标

**目标**：UNKNOWN、推断标记、置信度、重叠是公共 API 的带版本类型字段。

**现状**

字段本身三端都实现了，语义规则也写得极细（2500 ms 补全边界、600 ms 发射延迟归属、`speakerInferred` 标记、`confidence` 置 0、已提交窗口冻结）。**问题只在它们住在哪里**：

| 文档 | `speakerTurns` 出现次数 |
| --- | --- |
| `asr/docs/api/语音识别SDK接口-20260622.md`（跨端 canonical） | **0** |
| `asr/android/docs/customer/语音识别SDK接口.md` | 2 |
| `delivery/harmony-dingqiao/docs/语音识别SDK接口.md` | 3 |

语义的权威定义在 `docs/engineering/ASR_CONTRACTS.md` 和 `delivery/harmony-dingqiao/docs/UNKNOWN_SPEAKER_BACKFILL.md` 等工程文档里——调用方读不到。

**差距**

- 跨端 canonical 契约需补齐角色与不确定性字段：当前 0 覆盖
- 这些字段需要版本化承诺：当前无
- 官方展示语义：已在两端 Demo 对齐（见 `ANDROID_HARMONY_ROLE_PARITY_20260917.md`），但未成文为契约的一部分

## 5. 可自证 — 部分达标

**目标**：诊断可导出、不泄露内容；四个交付状态机器可判。

**现状**

诊断面**已达标**：独立诊断 SDK 随包交付，三端均有 Diagnostics 模块，并有 `test_harmony_diagnostics_core.py` / `test_harmony_diagnostic_journal.py` 覆盖。

证据清单**形态正确但没有延续**。`delivery/harmony-dingqiao/evidence/DELIVERY_0.3.13.json` 的结构正是目标形态：

```json
{ "status": "PASS", "source_commit": "0aa5622e…", "complete_verified_files": 48,
  "artifacts": [ { "sha256": "54f9eaf9…", "size_bytes": 300164238, "artifact": "…v0.3.13-20260908.zip" } ] }
```

但全仓只有这一份 `DELIVERY_*.json`。当前版本已到 0.3.24，而 `evidence/acceptance/20261017-776e2bad-0.3.24/` 目录里只有一个文件：一封交付邮件 Markdown。

**差距**

- 带结构化清单的版本：1 / 12（0.3.13 之后的版本都没有）
- 四个交付状态（构建完成／验收通过／已发布／归档完成）仍靠人判断
- 零网络请求：是 `AGENTS.md` 的产品底线，但无自动化检查（按 INTERNET 权限／网络断言搜索无门禁）

证据目录已按 `<日期>-<提交>-<版本>` 命名，说明「证据绑定提交」的习惯已经有了，缺的只是把它结构化并自动产出。

## 6. 调用方体验 — 部分达标

**目标**：十行拿到第一条结果、跨端零平台分支、错误自带修复路径、Demo 即参考实现。

**已达标**

- Demo 展示语义三端一致（`ANDROID_HARMONY_ROLE_PARITY_20260917.md`：Android 已改为按 `sourceUtteranceId` 展示完整原句，与鸿蒙一致）
- 平台差异有专门文档 `HARMONY_DIFFERENCES.md`，逐条写明
- 19 份升级说明，回答「调用方必须改什么」
- 参数契约保证跨端参数名一致，`platform_extensions` 明确隔离

**差距**

- 「十行拿到第一条结果」从未测量过
- 错误返回是否带参数名／当前值／合法范围，未统一核查
- 默认值能否直接跑通，无对应用例

## 7. 版本与承诺 — 部分达标

**已达标**：弃用流程有真实实例——`LICENSE_APP_MISMATCH` / `LICENSE_CERT_MISMATCH` 标 `@Deprecated` 并给出替代码，差异写进 `HARMONY_DIFFERENCES.md`。

**差距**

- 冻结／演进／实现细节三层边界未明文划分，调用方无法判断什么可以依赖
- 契约版本号未随包交付（当前靠 SDK 版本号间接表达）
- 精度「同评测集不得回退」无自动门禁

## 8. 健康度指标 — 0 / 6 达标

| 指标 | 目标 | 现状 |
| --- | --- | --- |
| 手写接口文档份数 | 0 | **5** |
| 三端行为逻辑重复实现份数 | 1 | **2–3** |
| 跨端一致性用例通过率 | 100% | 无统一用例集（仅 5 条黄金向量 + 若干单向 parity 检查） |
| 契约承诺中有对应用例的比例 | 100% | 参数契约有；错误码、生命周期、角色语义无 |
| 新工程师拿到第一条结果的代码行数 | ≤ 10 | **未测量** |
| 新平台接入所需的行为逻辑量 | 0 | 等于重写一遍 |

## 9. CI 结构 — 部分达标

5 个 workflow：`android.yml`、`ios.yml`、`dashboard.yml`、`itn.yml`、`repository-layout.yml`。

**没有 `harmony.yml`。** 鸿蒙的 64 个 Python 测试挂在名为 "Android SDK CI" 的 workflow 下执行。覆盖是真实的，但对任何新人来说，主交付平台的门禁藏在另一个平台的 workflow 里，是一个会持续产生误解的结构。

三端测试用三套框架写（Kotlin JUnit 16 个文件 / Python 解析 ArkTS 64 个文件 / Swift 1 个文件），没有任何一套用例是三端用同样输入都要通过的。

## 差距与演进步骤的对应

目标文档把演进排成 ①–⑥。按本次核对，各步的起点状态：

| 步骤 | 起点 | 已有的抓手 |
| --- | --- | --- |
| ① 跨端一致性用例 | 5 条黄金向量 | `CommunityHarmonyParityTest` + `community-harmony-42911432-commits.txt` 的抓取／回放做法可直接扩展 |
| ② 契约机器可读 | 参数契约已落地，错误码／结果字段／生命周期未动 | `dingqiao_parameter_contract.py` 是现成模板 |
| ③ 判断逻辑下沉 | 未开始 | 需要 ① 先到位 |
| ④ 状态机显式化 | 未开始；9 条散文不变量已写清 | `ASR_CONTRACTS.md` 可直接作为状态机规格的输入 |
| ⑤ 不确定性进公共契约 | 字段已实现，契约未覆盖 | 两份交付文档里的写法可直接上收 |
| ⑥ 证据清单自动化 | 做过一次（0.3.13） | `DELIVERY_0.3.13.json` 的 schema 可直接复用 |

六步里有四步已经有现成的抓手，不需要从零设计。

## 三条可以立刻做、且不影响任何交付的事

1. **修 7 个内部错误码漂移，删掉 `AsrError.swift` 那句失实注释，让 `errcodes.yaml` 的头部声明与 `README.md` 一致。** 纯内部改动，不碰客户码。
2. **把 `errcodes.yaml` 头部声称存在的那个校验测试真的写出来。** 一个测试，补上一条已经承诺了的门禁。
3. **把 `CommunityHarmonyParityTest` 的抓取／回放做法扩到 `UNKNOWN_SPEAKER_BACKFILL.md` 的 2500 ms 补全和 600 ms 归属规则上。** 这是 ① 的第一批用例，也是整个序列的起点。

三件事都不改架构、不动交付、不需要真机。
