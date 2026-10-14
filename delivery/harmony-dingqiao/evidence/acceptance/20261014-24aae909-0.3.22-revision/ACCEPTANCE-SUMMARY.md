# Amphion HarmonyOS ASR 0.3.22 组包前验收摘要（修订版 24aae909）

本摘要是组包前证据，不是最终 ZIP 的验收结论。最终 ZIP 的验收报告绑定其自身 SHA-256，另行外置。

本次是 0.3.22 的第三轮修订交付。相对 10-13 的 `c23c8f3d` 包，变化是：修正了正式 SDK 的构建模式
缺陷、收紧了角色结果的收尾预算、让调用方的句长上限真正生效、并**撤回了两个被现场复测否证的
问题一归因**。

## 冻结身份

| 项 | 值 |
|---|---|
| 版本 | 0.3.22，版本日期 2026-10-14 |
| 源码提交 | `24aae909`（PR #262 合入 `main`） |
| 语种范围 | 中英（ZH_EN） |
| 设备 | Kirin 9020，OpenHarmony-6.1.1.120，arm64-v8a，序列号 7GK0226326015655 |
| **正式 SDK 构建模式** | **`debug`**（非 diagnostics，见「上一轮缺陷的修正」） |
| Diagnostics 子包构建模式 | `diagnostics`，身份与验收报告逐字段相等 |

## 本版改动

| 改动 | 文件 | 对应问题 |
|---|---|---|
| 收尾截止由「ASR 尾部起算」改为「停录起算」，打捞预留从截止内部切出而非叠加；ASR 尾部未到时延迟打捞 | `SpeakerDiarizationFinishBarrier.ts` | 问题三 |
| 截止 14000 / 预留 3000；新增 `kind=DIARIZATION_FINISH` 逐会话上报收尾时间分解（release 可见） | `SpeechRecognizeSdk.ets` | 问题三 + 可观测性 |
| `EndpointRules.longFormMaxUtteranceSec`；长录音句长上限改为采纳 `endpointMaxUtteranceMs`，夹在 `[5s, 25s]`，有效值回显 | `Types.ets`、`Runtime.ets`、`EndpointRulePolicy.ts`、`RecognitionConfig.ets` | 问题二（感知延迟） |
| 先建 encoder，再按「是否有 encoder 落在 CPU」决定分割线程数（全部上加速器时取 2 线程），并加 `force_spinning_stop` | `community_diarization.cpp` | 问题一（余量） |
| 分割线程上报加 `#ifndef __ANDROID__` 守卫；新增按 Android 条件编译共享翻译单元的测试 | `community_diarization.cpp`、`test_harmony_community_native.py` | 构建正确性 |
| `displayMayTurnOff` / `diarizationQos` 注释改写为实测结论 | `AsrSchedulingConfig.ts` | 归因更正 |

公共接口为**新增**（`longFormMaxUtteranceSec`），无删除或语义变更；回调顺序与角色结果格式未变。

### 一项需要调用方注意的行为变更

`onSpeakerDiarizationResult` 的收尾边界由 `ASR 排空 + 15 s + 3 s` 改为 `max(ASR 排空, 14 s)`。
结果返回更快，但 `degradedReason = FINISH_TIMEOUT` 会比原版更常见 —— 预算整体变紧，原本
「晚一点但完整」的会话现在可能「按时但尾部角色被截断」。该降级原因本就在契约内。

## 通过项

| 项 | 结果 |
|---|---|
| API 23 编译兼容 | PASS，52 个公开 HAR TypeScript 文件，独立 API 23（OpenHarmony 6.1）`es2abc` 探针校验 |
| 正式 SDK 子包 | PASS，布局、校验和、UTF-8 ZIP、CRC、客户交付脱敏 16 文件 1 个 HAR |
| **正式 SDK 构建模式** | PASS，包内自包含 HAR 的 `BUILD_MODE_NAME = 'debug'`，诊断模块未编入正式 SDK |
| 模型资产 | PASS，manifest v2 共 9 个资产；ZH_EN ONNX MD5 与钉定值一致 |
| 自包含 HAR | PASS，警务资产、ASR/声纹模型、native 库、目标说话人模型策略与本地产物一致 |
| 干净客户宿主编译 | PASS |
| Diagnostics 子包 | PASS，同一提交的 diagnostics 构建身份，含已签名 Demo HAP |
| 构建身份 | PASS，两轮构建（debug / diagnostics）均通过 `harmony_build_identity.py --verify` |
| `customer-ptt` 验收 | PASS，100 轮、24 个语料，逐轮 PASS，`sdk=PASS memory=PASS emptyFinalRate=0.000`，0 失败项 |
| 验收报告与 Diagnostics 包身份 | PASS，`build_identity` 与 `build-identity.json` 逐字段相等 |
| 单元测试 | PASS，549 个 harmony 测试（CI 同一条 discover 命令）+ 22 个发布默认值门禁 |

### 内存

`customer-ptt` 100 轮：RSS 增长 35.820 MB（阈值 64.0），观测窗口 429.531 秒，**增速 0.083 MB/s**；
线程增长 1（阈值 2）；head 505.324 MB，tail 541.145 MB，peak 586.547 MB。

与前两轮同口径对比：0.106 MB/s（`8eb66b32`）、0.083 MB/s（`dca08e69`）、0.083 MB/s（本轮）。
**不可与 0.3.22 原版报告的 14.578 MB 直接比较**：那轮观测窗口仅 41.985 秒，按增速计为 0.347 MB/s。

### 问题三的三臂真机验证

在 `dca08e69` 上完成，本轮未改动该逻辑，故不重测。

| 臂 | 配置 | 结果 |
|---|---|---|
| 健康基线 | 24 分钟、亮屏、默认 | 停录→角色结果 **2.785 s**，零欠账，`timedOut=false` |
| 强制积压 | hop 250 + CPU encoder | **14001 ms**（旧锚点等价 18646 ms），`customer_stop_latency` PASS `max_ms=14104` |
| 慢 ASR 尾部 | 再叠单线程 ASR + 全速喂入 | `stopToSalvageMs = stopToAsrTailMs = 15120`，延迟打捞成立，推理保住多出的 4.1 s |

截止设 15000 时实测客户可见值 15099 ms 仍越界（回调链本身约 99 ms），故内部截止取 14000。

## 豁免项

| 模式 | 理由 |
|---|---|
| `speaker-vad-turn` | 延续 0.3.22、0.3.21、0.3.20 的豁免：该模式需要目标说话人 manifest，其客户夹具既不在本检出中，也不在两个已获取的受控数据包中，因此无法产出有效证据。本次未新增该模式的改动。 |

## 未验证项

本节不省略。以下结论不得解读为已解决。

| 项 | 状态 | 说明 |
|---|---|---|
| **问题一（锁屏变慢）** | **未解决** | 根因是进程级 cpuset（熄屏时系统将整个进程移入仅含 4 个小核的调度域）。SDK 侧无独立解法：缺口 0.20×，而角色分离链**全部**开销仅 0.180× |
| 问题一原修正 `displayMayTurnOff` | **已证无效** | 客户 10-14 复测两场，开关生效（`role-qos` 全程 0）但实时率仍 0.80× |
| 问题一的 QoS 路径 | **已证无效** | 我方实测：熄屏下持 `QOS_USER_INTERACTIVE`（最高档）与持 `QOS_BACKGROUND`（最低档）的线程 `Cpus_allowed_list` 相同，均为 `0,1,2,3`，进程全部 54 个线程亦然 |
| 问题一的干净基线 | **待客户复测** | 客户测的 1013 包正式 SDK 误用 diagnostics 模式（我方缺陷），0.80× 中该开销占比未知 |
| 问题一的 cpuset 迁移可行性 | **待客户确认** | 需系统权限写 `/dev/cpuset/*/tasks`，且每次屏幕状态切换后重新下发。我方设备 hdc shell 读该路径即被拒，无法代为验证 |
| 问题二的主要症状 | **仍在** | 最大无输出空档由 105 s 降至 72.5 s，使用者仍会看到长时间无输出 |
| 问题二残余的归因 | **待客户确认** | 放大输入、改端点策略、两者组合三种独立干预均停在 72.5–73.2 s 同一地板 |
| 问题三的现场效果 | **未验证** | 三臂为我方构造场景；客户现场的 21.6 s 未用本版复测 |
| 分割换 MS Lite CPU 运行时 | **未验证** | 10-08 探针显示 35.2 vs 97 ms/窗，但非受控对比，且未在小核域验证 |
| 放宽 hop 以降成本 | **被挡住** | `CommunityHopSamples` 取相邻窗口起点的**最小**间距，中途改 hop 会使 Fb 按密集证据缩放而后半段实际稀疏，正是 #260 要修的失败模式 |
| 熄屏场景的生命周期门禁 | **测不了** | 熄屏下 ArkTS UI 线程冻结，demo 的压测状态上报走 UI 层，`completes=0`。demo/harness 限制，非 SDK 问题 |

## 上一轮缺陷的修正

`8e9b4678`（10-12）与 `c23c8f3d`（10-13）两个修订包的**正式 SDK 误用了 diagnostics 构建的 HAR**
（`BUILD_MODE_NAME = 'diagnostics'`），诊断模块（含事件落盘）被编入正式 SDK。成因是组包时先执行
diagnostics 构建，而 `assemble_selfcontained_dingqiao_har.sh` 只重打已构建的 HAR。0.3.21（10-09）
与 0.3.22（10-10）两个包为 `debug`，未受影响。

**这个缺陷直接影响了现场结论**：客户测出的 0.80× 实时率是在被污染的 1013 包上测的，其中有多少
来自诊断模块的落盘开销目前未知。本轮按正确顺序执行并在上表显式核验，客户需用本包复测才能得到
干净基线。

## 归因更正记录

问题一的归因两次出错，均已撤回：

1. **第一次（10-12）**：认为根因是 SDK 自己申请 `QOS_BACKGROUND`，据此交付 `displayMayTurnOff`。
   客户开启后复测，症状未变。
2. **第二次（同一前提）**：该归因依赖「background QoS 隐含 background cpuset」这一论断，
   我方实测否证 —— QoS 决定既定核集合内的调度权重，核集合本身由系统指派，QoS 与
   `sched_setaffinity` 都无法扩大它，root 亦然。

客户按第一版归因做过配置并浪费了一轮测试，这个过程本身是第二版归因的证据，故两版都在
`docs/speaker/SCREEN_LOCK_AND_PARTIAL_LAG_20261012.md` 中保留。

## 构建与测试环境说明

本机命令行环境下，若干官方发布脚本需要四项注入才能跑通，均为环境问题，不影响产物内容：

| 注入 | 原因 |
|---|---|
| PATH 前置一个直接 `exec` 真实 git 的 wrapper | hvigor 的 node 是 x86_64（Rosetta），其子进程中 `/usr/bin/git` 这个 Xcode CLT shim 会因 `libxcrun.dylib` 只有 arm64 切片而退出码 1，cmake 据此认定 git 不存在并中止 FetchContent |
| `NODE_ADDON_API_CACHE` 指向本地 node-addon-api 克隆 | 构建环境无外网 |
| sherpa 模块 `srcPath` 改写为代际真实路径 | hvigor 不接受代际符号链接 |
| `signingConfigs` | 提交态为空（签名材料从不入库） |

流程注意事项：

- **本轮两次构建的「engine readiness」检查均超时**（300 s / 600 s）。已单独确认应用可正常启动并
  取得授权（`AmphionRuntime Harmony init done, version=0.3.22, license=LICENSED`），且两次身份均通过
  `harmony_build_identity.py --verify`。该超时是冒烟脚本等待 UI 状态上报的那一步，与产物无关。
- **组包前验收必须用 `--skip-build-install`，不能用 `--installed-package`。** 后者记录的是安装包
  指纹，而完整包组装要求报告的 `build_identity` 与 Diagnostics 包的 `build-identity.json` 逐字段相等。
- **打包顺序必须是 `debug 构建 → 正式包 → diagnostics 构建 → diagnostics 包`。** 顺序颠倒会让正式包
  捡到 diagnostics 构建的 HAR，这正是上一轮的缺陷。
- **hilog 必须在运行期间流式抓取**；设备 hilog 是跨天滚动缓冲，事后导出抓不到会话启动期。
- **内存指标须在干净设备状态下测量**，且只能按增速比较。
