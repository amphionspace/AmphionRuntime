# Amphion HarmonyOS ASR 0.3.22 组包前验收摘要（修订版 dca08e69）

本摘要是组包前证据，不是最终 ZIP 的验收结论。最终 ZIP 的验收报告绑定其自身 SHA-256，另行外置。

本次是 0.3.22 的修订交付，针对现场反馈的两个问题：锁屏后识别变慢约 3 倍、开说话人分离后吐字慢。

## 冻结身份

| 项 | 值 |
|---|---|
| 版本 | 0.3.22，版本日期 2026-10-13 |
| 源码提交 | dca08e69（分支 `delivery/harmony-asr-20261012` 合入 `main`，并合并上游 PR #260）|
| 语种范围 | 中英（ZH_EN） |
| 设备 | Kirin 9020，OpenHarmony-6.1.1.120，arm64-v8a，序列号 7GK0226326015655 |
| 正式 SDK 构建模式 | `debug`（非 diagnostics） |
| Diagnostics 子包构建模式 | `diagnostics`，身份与验收报告逐字段相等 |

## 本版改动

| 改动 | 文件 | 对应问题 |
|---|---|---|
| 新增 `AsrSchedulingConfig.displayMayTurnOff`；`resolveDiarizationQos` 增加第三参数，声明可能熄屏时保持 `inherit` 不降档 | `AsrSchedulingConfig.ts` | 锁屏变慢 |
| `rule1` 在长录音模式下关闭（`recognizerMode='long'` 时），短句模式保持原行为 | `RecognitionConfig.ets` | 吐字慢 |
| 新增 25 秒句长上限，超出且已有文字时主动切句（日志 `source=utterance-length`） | `Runtime.ets` | 吐字慢 |
| 新增 `kind=SESSION_CONFIG` 每会话回显端点规则与 VAD 配置 | `Runtime.ets` | 可观测性 |
| `CALLBACK_RESULT` 在 final 上补记 `speakerIndex`/`utteranceId`/`speakerConfidence`；新增 `CALLBACK_DIARIZATION_UPDATE`；探针移至会话装饰之后 | `SpeechRecognizeSdk.ets` | 可观测性 |
| `SpeakerDiarizationResult` 暴露 `encoderBackend`；`FINISH_TIMEOUT` 的 `degradedMessage` 带上实际后端 | `DingqiaoModels.ets`、`SpeakerDiarizationSession.ets` | 诊断 |
| 压测链路支持 `--diarization-display-may-turn-off` | `run_device_stress.py`、`EntryAbility.ets`、`DeviceStressTest.ets` | 验证用 |

公共接口为**新增**，无删除或语义变更；回调顺序与角色结果格式未变。

### 合入的上游改动

本版合并了上游 PR #260（`perf(diarization): hop windows every 2 s with density-matched VBx Fb`，8 文件 320 增 27 删）。
它把 `SpeakerDiarizationLocalClient` 的 `hopMs` 默认值由 1 s 改为 2 s，并让 native 聚类按窗口起点间距缩放 VBx 的 Fb，
使 1 s 节奏下能分开的说话人不会因证据变稀而被合并。dingqiao 路径本来就显式传 2000，对本交付链路等价。
与本版改动的文件重叠仅 `SpeakerDiarizationLocalClient.ets` 与 `community_diarization.cpp` 两处，且改动区域不相交，合并无冲突。

### 行为变更的影响范围

| 开关 | 变更 | 影响范围 |
|---|---|---|
| `EndpointRules.rule1` | 全局默认仍为 `true`；dingqiao 层在 `recognizerMode='long'` 时置为 `false` | **仅长录音路径**。短句模式（语音指令、搜索听写等）行为与 0.3.22 原版完全一致 |
| `AsrSchedulingConfig.displayMayTurnOff` | 新增，默认 `false` | 不设置则行为与 0.3.22 原版完全一致 |

设备实测确认两种模式各自生效：

| 模式 | `kind=SESSION_CONFIG` 实测 |
|---|---|
| 长录音（会议纪要） | `rule1=false rule3UtteranceSec=-1` |
| 短句（`customer-ptt`） | `rule1=true rule3UtteranceSec=20`（0.3.22 原行为） |

`displayMayTurnOff` 默认关闭是为保留亮屏场景 `background` 的控热收益（实测省 55.9 个 CPU 百分点）。
代价是修正不会自动生效，需调用方显式声明。

## 通过项

| 项 | 结果 |
|---|---|
| API 23 编译兼容 | PASS，52 个公开 HAR TypeScript 文件，独立 API 23（OpenHarmony 6.1）`es2abc` 探针校验 |
| 正式 SDK 子包 | PASS，布局、校验和、UTF-8 ZIP、CRC、客户交付脱敏 16 文件 1 个 HAR |
| 正式 SDK 构建模式 | PASS，`BUILD_MODE_NAME = 'debug'`，诊断模块未编入正式 SDK |
| 模型资产 | PASS，manifest v2 共 9 个资产；ZH_EN ONNX MD5 与钉定值一致 |
| 自包含 HAR | PASS，警务资产、ASR/声纹模型、native 库、目标说话人模型策略与本地产物一致 |
| 干净客户宿主编译 | PASS，自包含兼容 HAR 在干净宿主工程中安装并编译通过 |
| Diagnostics 子包 | PASS，同一提交的 diagnostics 构建身份，含已签名 Demo HAP |
| 真机安装冒烟 | PASS，debug 与 diagnostics 两轮均 `install bundle successfully`，引擎就绪、进程存活 |
| `customer-ptt` 验收 | PASS，100 轮、24 个语料，`sdk=PASS memory=PASS emptyFinalRate=0.000`，0 失败项 |
| 验收报告与 Diagnostics 包身份 | PASS，`build_identity` 与 `build-identity.json` 逐字段相等（HAP SHA-256 `28e36e7c…`） |

### 内存

`customer-ptt` 100 轮：RSS 增长 35.834 MB（阈值 64.0），观测窗口 430.826 秒，300 个采样（排除 60 个预热采样），
**增速 0.083 MB/s**（报告记为 8.262 MB/min）；线程增长 **0**（阈值 2）；
head 510.789 MB，tail 546.623 MB，peak 587.098 MB，peak HWM 598.277 MB，swap 0；
三分位中位 512.076 / 531.951 / 543.152 MB。

**不可与 0.3.22 原版报告的 14.578 MB 直接比较**：那轮观测窗口仅 41.985 秒（30 个采样），
按增速计为 0.347 MB/s。本版增速为其约 1/4。`rss_growth_mb` 是窗口内绝对增量，窗口长度不同则不可比。

同一构建在连续运行十余小时、反复装卸应用的设备上测得 60.029 MB（增速 0.140 MB/s），重启设备后
降至 45.539 MB（上一修订轮），本轮 35.834 MB。测量须在干净设备状态下进行。

### 问题一的机制验证

同一构建、同一语料、亮屏、运行期间流式抓取 hilog 的 A/B 对照：

| 臂 | `role-qos` 日志行数 | 内容 |
|---|---|---|
| 默认（`displayMayTurnOff=false`） | 3 | `requested=0 result=0 effective=0`（即 `QOS_BACKGROUND`） |
| 开启（`displayMayTurnOff=true`） | **0** | 无 |

默认臂逐字复现客户日志中的该行；开启后 SDK 不再申请降档，调用方的绑核不会再被 background cpuset 覆盖。

### 问题二的修前修后

| 语料 | 指标 | 修前 | 修后 |
|---|---|---|---|
| 客户稀疏语音 120 s | 最大无输出空档 | 105.1 s | 72.5 s |
| 客户稀疏语音 120 s | final 数 | 3 | 5 |
| 去静音连续语音 301 s | 最大 final 间隔 | 77.8 s | 66.7 s |
| 去静音连续语音 301 s | final 数 | 22 | 24 |
| 去静音连续语音 301 s | final 间隔 p90 | 24.8 s | 24.7 s |

25 秒句长上限实测触发（`source=utterance-length`），p90 24.7 s 与该上限吻合。
`rule1` 收窄到长录音模式后，稀疏语音结果与全局关闭时逐项一致（18 回调 / 5 final / 72.5 s）。

## 豁免项

| 模式 | 理由 |
|---|---|
| `speaker-vad-turn` | 延续 0.3.22、0.3.21、0.3.20 的豁免：该模式需要目标说话人 manifest，其客户夹具既不在本检出中，也不在两个已获取的受控数据包中，因此无法产出有效证据。本次未新增该模式的改动。 |

## 未验证项

本节不省略。以下结论不得解读为已解决。

| 项 | 状态 | 说明 |
|---|---|---|
| 问题一的熄屏症状 | **未验证** | 仅验证「不再申请 background QoS」，未验证「因此变快」。熄屏测试在我方环境不可靠，需客户在其场景确认 partial 间隔是否从 1.36 s 回到 0.45 s 量级 |
| 问题一的生效条件 | **需调用方配合** | 默认 `false`，不显式设置则无变化 |
| 问题二的主要症状 | **仍在** | 最大空档由 105 s 降至 72.5 s，使用者仍会看到长时间无输出 |
| 问题二残余的归因 | **待客户确认** | 放大输入、改端点策略、两者组合三种独立干预均停在 72.5–73.2 s 同一地板，据此判断该段录音无可转写语音；该判断未经客户确认 |
| 25 秒句长上限的覆盖 | **有限** | 上限要求当前已有文字；解码器无文字时不生效，这正是残余空档的成因 |
| 问题三 | **未处理** | `onSpeakerDiarizationResult` 超过 15 秒才到（实测 21.6 s）本版未改动 |
| 问题二修前修后的数值 | **沿用上一修订轮** | 该组对照在 `8eb66b32` 上测得；本版相对其仅合入 PR #260，未改动端点与句长逻辑，故未重测 |

## 本版问题的来源记录

0.3.22 原版的验收摘要已写明 `diarizationQos` 默认 `'auto'`「因 hop ≥ 2000 解析为 `background`」，
当时将其视为压低发热的预期行为。问题一本质上是该默认值变更的未预见后果：`background` QoS 在亮屏下
对 1500 ms 窗口预算只剩 5% 余量（SDK 注释已记录），熄屏移除大核集群后余量被击穿。

问题二的长句部分同理：`recognizerMode='long'` 设计上禁用 `rule3`（「lossless long-form path」），
但未为长录音提供替代的句长上限，而全局生效的 `rule1` 又使 `rule3` 的句长计数永远无法累积到 20 秒。
两条规则互相抵消，长段朗读因而只能等自然停顿。本版把两者的开关统一到同一判据，并由 25 秒上限接替兜底。

### 组包顺序缺陷（本轮修正）

`8e9b4678`（10-12）与 `c23c8f3d`（10-13）两个修订包的**正式 SDK 误用了 diagnostics 构建的 HAR**
（`BUILD_MODE_NAME = 'diagnostics'`），诊断模块（含事件落盘）被编入正式 SDK。
成因是组包时先执行了 diagnostics 构建，而 `assemble_selfcontained_dingqiao_har.sh` 只重打已构建的 HAR，
于是正式包捡到了带诊断探针的那一套。0.3.21（10-09）与 0.3.22（10-10）两个包为 `debug`，未受影响。

本轮按 `debug 构建 → 正式包 → diagnostics 构建 → diagnostics 包 → 验收 → 完整包` 的顺序执行，
并在上表「正式 SDK 构建模式」一项中显式核验。两个缺陷包已在构建目录中改名为 `.diagnostics-mode-defect` 留证。

## 构建与测试环境说明

本机命令行环境下，若干官方发布脚本需要四项注入才能跑通，均为环境问题，不影响产物内容：

| 注入 | 原因 |
|---|---|
| PATH 前置一个直接 `exec` 真实 git 的 wrapper | hvigor 的 node 是 x86_64（Rosetta），其子进程中 `/usr/bin/git` 这个 Xcode CLT shim 会因 `libxcrun.dylib` 只有 arm64 切片而退出码 1，cmake 据此认定 git 不存在（`GIT_VERSION_STRING=''`）并中止 FetchContent。直接 symlink 无效：git 会按 argv[0] 推算 exec-path，转而从 PATH 找 `git-upload-pack`，再次落到 shim |
| `NODE_ADDON_API_CACHE` 指向本地 node-addon-api 克隆 | 构建环境无外网，`FetchContent` 的 GitHub 地址不可达；脚本据此把 `GIT_REPOSITORY` 改写为本地 `file://` URI |
| sherpa 模块 `srcPath` 改写为代际真实路径 | hvigor 不接受 `third_party/.derived/sherpa-onnx` 这个代际符号链接 |
| `signingConfigs` | 提交态为空（签名材料从不入库），否则产出 unsigned HAP 且身份输入缺失 |

流程注意事项：

- **hilog 必须在运行期间流式抓取。** `capture_hilog` 仅在结束后执行一次 `hilog -x`，而设备 hilog 是跨天滚动缓冲，
  会话启动期日志（`role-qos`、`kind=LOAD`、`kind=SESSION_CONFIG`）全部抓不到。`hilog -r` 在该环境下清不掉。
- **打包顺序必须是：构建 → 还原派生树 → 写身份 → 打包。** 构建会弄脏派生 sherpa 树，而打包要求树干净且身份匹配。
  `pack_diagnostics_sdk.sh` 的 `SKIP_BUILD=true` 与 `BUILD_IDENTITY_PATH` 两个钩子正是为此。
- **组包前验收必须用 `--skip-build-install`，不能用 `--installed-package`。** 后者记录的是安装包指纹
  （bundle name / fingerprint / versionCode），而完整包组装要求报告的 `build_identity` 与 Diagnostics 包的
  `build-identity.json` 逐字段相等。`--installed-package` 适用于最终 ZIP 的验收，不适用于组包前证据。
- **设备重启后首次跑测前须先 `aa start` 一次应用**，否则 harness 推送载荷会报 `Invalid bundle name`。
- **内存指标须在干净设备状态下测量**，且只能按增速比较，不能直接比较不同窗口的绝对增量。
