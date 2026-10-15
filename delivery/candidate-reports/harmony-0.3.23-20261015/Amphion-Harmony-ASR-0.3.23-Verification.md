# Amphion HarmonyOS ASR 0.3.23 验收状态（未发布候选）

**状态：完整包已组并通过部分最终 ZIP 验收，带两项记录在案的缺口。** 正式 SDK、Diagnostics
子包、完整 ZIP、真机验收与三项修复的针对性验证全部绑定同一冻结提交
`9a5cc7b69ba1551ded06bd089721cce28ad73e40`（分支 `release/harmony-0.3.23`，组包时工作区干净）。

两项缺口：

1. `speaker-vad-turn` 沿用 0.3.20–0.3.22 的豁免（本检出与两个受控数据包中均无目标说话人夹具）。
   按 `DEFAULT_DELIVERY.md`，缺该模式证据的包**不具备正式发布资格** —— 因此尽管本轮的指示是
   "正式发布"，这里仍按仓库既有口径登记为未发布候选（`published: false`）。
2. **包内 `demo-source` 原样不可编译**：`MindirProbe.ets` 仍从内部模块 `amphion_asr` 取三个
   探针函数，而交付工程并不依赖该模块。删掉那一行（并把三处调用置桩）后独立构建通过、产物
   真机 8/8 通过。打包脚本已在本包冻结之后修好，但该 ZIP 无法在不换源码提交的前提下重切，
   所以本包带着这个缺陷发出，客户文档里给出了那一行的规避方法。

| 产物 | 值 |
|---|---|
| 完整 ZIP | `Amphion-Harmony-ASR-Complete-0.3.23.zip`，1,717,605,729 字节 |
| SHA-256 | `0d5ee9ee28f097d521136fb6693b4272ae7deecfdd255dcb14d5782eb6f9d44a` |
| 位置 | `delivery/harmony-dingqiao/build/complete-sdk-0.3.23-9a5cc7b6/` |

## 本版改动（相对 10-14 的 0.3.22 修订版 `24aae909`）

只改三处，**识别模型、角色分离算法与所有默认调度参数均未改动**。

| 改动 | 落点 | 对应现场问题 |
|---|---|---|
| tagging 前把连续单字数字串折叠成数字；对齐偏移经改写映射回调用方坐标 | `0032-fix-itn-keep-spoken-digit-runs-intact.patch`（`wetext/processor/wetext_processor.cc`） | `一二三四五六七八九十` → `123 4567 80~90`（拆组 + 结尾"十"被当概数） |
| ITN 之后按对齐保留标点模型插入的标点、丢弃其新插入的空格，对不齐则原样采用模型输出 | `asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets` | 日期/金额/小数两侧多余空格（`2 . 58万`、`2026 / 05 / 15`） |
| 登记 SDK 自建 ORT 工作线程 id，检测到 cpuset 迁移后对其重新下发 `cpuIds`，迁移后持续重试 3 秒 | `0033-fix-harmony-reapply-asr-worker-affinity.patch`（`harmony-scheduling.cc`） | 客户 10-15 报告"解锁后 1 分钟仅恢复 1/26" |

改为 0.3.23 而非再发一个 0.3.22：客户已先后收到两个同名 0.3.22 制品（10-13 与 10-14），
而本版又改了识别文本，沿用同号会让现场报告无法对齐。

## 冻结身份

| 项 | 值 |
|---|---|
| 版本 | 0.3.23，版本日期 2026-10-15，`versionCode` 323 |
| 源码提交 | `9a5cc7b69ba1551ded06bd089721cce28ad73e40` |
| 分支 | `release/harmony-0.3.23` |
| 语种范围 | 中英（ZH_EN） |
| 设备 | Mate 80，Kirin 9020，OpenHarmony-6.1.1.120，API 24，arm64-v8a |
| **正式 SDK 构建模式** | **`debug`**（非 diagnostics，门禁已核验） |
| Diagnostics 子包构建模式 | `diagnostics` |

## 已通过

| 项 | 结果 |
|---|---|
| API 23 编译兼容 | PASS，52 个公开 HAR TypeScript 文件，独立 OpenHarmony 6.1 / API 23 `es2abc` 探针 |
| 构建身份一致性 | PASS，`Harmony HAR/HAP build identity matches current source and artifacts` |
| 版本序号 | PASS，`harmony 0.3.23 packaging version is next` |
| **正式 SDK 构建模式** | PASS，核验为 `debug`；该门禁即 10-13 污染包漏掉的那一道 |
| 正式 SDK 子包 | PASS，布局、校验和、UTF-8 ZIP、CRC、zh-en SDK-only、客户交付脱敏 16 文件 1 个 HAR |
| 模型资产 | PASS，manifest v2 共 9 个资产，ZH_EN ONNX MD5 与钉定值一致 |
| 自包含 HAR / 干净宿主编译 | PASS，在干净客户宿主安装并编译通过 |
| Diagnostics 子包 | PASS，以 `SKIP_BUILD=true` + `INCLUDE_SIGNED_DEMO=true` 对同一提交的已验证构建身份组包 |
| 真机 `customer-ptt` 验收 | PASS，100/100 轮逐轮 PASS，空 final 率 0.000，原生流 0 泄漏，内存 PASS（增长 47.1 MiB，斜率 11.31 MiB/min，峰值 613.6 MiB） |
| 验收报告与 Diagnostics SDK 的构建身份一致 | PASS，逐字段比对为 `True`（本轮一度因误用 `--installed-package` 而不一致，改用 `--skip-build-install` 后修正） |

## 三项修复的针对性验证（真机）

### 文本后处理：8 条用例 8/8

| 念出的内容 | 0.3.22 | 0.3.23 |
|---|---|---|
| 一二三四五六七八九十 | `123 4567 80 ~ 90。` | `12345678910。` |
| 八九十 | `80 ~ 90。` | `8910。` |
| 两点五八万 | `2 . 58万。` | `2.58万。` |
| 二零二六年五月十五日 | `2026 / 05 / 15。` | `2026/05/15。` |
| 三十八 | `38。` | `38。`（未回归） |
| 八十 | `80。` | `80。`（未回归） |
| 一二三 / 一二三四五 | `123。` / `12345。` | 同（未回归） |
| 幺三八零零一三八零零零 | `13800138000。` | 同（未回归） |

安装最终 ZIP 内取出的 demo HAP 后复测，同样 8/8。

### 多人会议无回归（523.7 秒，客户原始录音）

| 指标 | 修复前 | 修复后 |
|---|---|---|
| utterance 数 | 79 | 79 |
| 有 `speakerTextSpans` | 79/79 | 79/79 |
| 有说话人标签 | 20/79 | 20/79 |
| 角色更新 / 结果 | 39 / 5 | 39 / 5 |
| 说话人编号集合 | [-1,0,1,2,3] | 同 |

该录音里那段报数由 `234 52456464560` 变为 `23452456464560`。

### 绑核恢复（`cpuIds=[0,1,2,3]`，第 60 秒熄屏 → 第 400 秒解锁）

| | 亮屏起始 | 解锁后 |
|---|---|---|
| 0.3.22 | 9~11 个线程持有配置掩码 | **1 个** |
| 0.3.23 | 11~12 个 | **9~10 个（恢复）** |

hilog 中 `affinity-reapplied workers=N` 仅在调度域迁移后出现。

## 最终 ZIP 验收（部分）

| 项 | 结果 |
|---|---|
| 固定哈希后复核 | PASS，SHA-256 与记录一致 |
| 正式 SDK HAR 构建模式 | PASS，包内 `BuildProfile` 为 `BUILD_MODE_NAME='debug'`，版本 0.3.23 |
| 包内 `-signed.hap` | PASS，精确取出 `amphion_asr_demo-diagnostics-signed.hap`（432,036,538 字节） |
| 包内 demo 安装复测 | PASS，8 条 ITN 用例 8/8 |
| 包内源码独立构建 | **FAIL 原样 / PASS 去掉一行后**：原样 `CompileArkTS` 报 `10505001 Cannot find module 'amphion_asr'`（`MindirProbe.ets:4`）；删该 import 并置桩三处调用后 `BUILD SUCCESSFUL`，33 个 hvigor 任务，依赖 `libs/amphion_dingqiao.har`，只补本地授权与签名 |
| 源码构建产物复测 | PASS，签名 HAP `d26b30c1…`，8 条 ITN 用例 8/8，`sdk=PASS`、空 final 率 0.000 |

## 未完成与未覆盖

保留原状，不改写为通过。

| 项 | 状态 | 原因 |
|---|---|---|
| 真机 `speaker-vad-turn` | WAIVED（结构性，非产品缺陷） | 该模式需要客户目标说话人夹具，本检出与两个已拉取的受控数据包中均不存在。本版未改动该模式。清单与随包验收摘要均声明该豁免 |
| 包内 `demo-source` 原样编译 | 缺陷，已定位、已修打包脚本、本包未重切 | 见下一节 |
| **锁屏变慢** | **未解决，但基线已更正** | 干净包锁屏期实测 0.856× / 0.866×，真实缺口 **0.134×**（角色分离链 0.091×、ASR 主链路自身 0.043×；关掉角色分离也只到 0.957×）。客户 10-14 的 0.80× 系在 10-13 那个 diagnostics 污染包上测得，污染值实测 ≥0.22× 实时率。SDK 侧无独立解法 |
| 锁屏期仅点亮屏幕 | 无效，必须解锁 | 仅点亮时进程仍在受限调度组，排空 0.618×；滑动解锁后 1.550× |
| 停录即拆会话会丢文本 | 已量化，未改 | 积压 133 秒时停止、30 秒后拆会话，最终文本少 15% |
| 以"十"结尾数字串的 `textNormalization.spans` | 已知残留 | 文本正确，区间失败关闭为空数组。折叠后上游语法逐位记录，而"十"一个汉字产出两个字符，必然出现宽度为 0 的区间被既有校验拒绝；UTF-8 字符中间无法切分。523 秒会议实测 79/79 区间完好，该模式未出现 |
| 吐字慢（0.3.22 问题二） | 主要症状仍在 | 最大无输出空档 105 → 72.5 秒，残余归因（该段无可转写语音）待客户确认。本版未改动 |
| 角色结果迟到（0.3.22 问题三） | 现场效果未验证 | 机制已在 0.3.22 修订版改好并三臂真机验证，客户现场那次 21.6 秒尚未用新包复测 |
| 绑核的可移植性 | 已记录，非缺陷 | 同为 Mate 80，`cpuIds=[4..11]` 在 6.1.2.329 上 `affinity-exact result=1`、在 6.1.0.135 上为 `0`。交付文档已写明须逐机型实测并给出兜底值 `[4,5,6,7]` |
| Android 端一致性 | NOT_RUN | 补丁 0032 / 0033 位于 Android 经 JNI 共用的 `sherpa-onnx/csrc`，**Android AAR 未在本轮重建**，两端行为暂不一致 |
| 长稳内存分阶段证据 | INCONCLUSIVE | 100 轮 `customer-ptt` 的通用 RSS 预算通过，未采集与角色分离阶段对齐的证据 |
| 断网网络观测 | NOT_RUN | — |
| 粤英语种 / TTS 模型 / 目标说话人增强 | 不在本批范围 | 本批为 ZH_EN；不含 TTS 模型；目标说话人增强仅保留接口，不含所需模型，不能启用 |

## 包内 `demo-source` 不可编译（本轮发现的交付缺陷）

**现象**：从最终 ZIP 解出 `demo-source/`，`ohpm install --all` 后 `assembleHap` 失败：

```
10505001 ArkTS Compiler Error
Cannot find module 'amphion_asr' or its corresponding type declarations.
At File: .../entry/src/main/ets/util/MindirProbe.ets:4:82
```

**成因**：`pack_complete_asr_delivery.sh` 只对 `DeviceStressTest.ets` 与 `ModelLoadBench.ets`
两个文件剥离内部模块 import。`MindirProbe.ets` 是 2026-10-08 的提交 `c0dec403` 新增的
（**0.3.20 交付是 10-07，正好在这之前**，所以上次这道检查过得去），它带进来第三个
`from 'amphion_asr'` 的 import，没人剥。

**本轮的处置**：

1. 打包脚本已修（本包冻结之后）：同样对 `MindirProbe.ets` 剥 import 并把
   `probeOrtBackend` / `probeMindSporeChainPaced` / `probeMindSporeBackend` 三处调用置桩；
   并新增一道**兜底门禁**——组包时扫描交付源码里所有 `.ets`，只要还有 `from 'amphion_asr'`
   就让组包失败。这样下一个文件再带内部依赖进来，会在组包时暴露，而不是等客户编译时暴露。
2. **本包没有重切**：`pack_complete_asr_delivery.sh` 把 `SOURCE_COMMIT` 钉在 `HEAD`，并要求
   正式 SDK 的 `BUILD_PROVENANCE.json` 与 Diagnostics 的 `build-identity.json` 都等于同一个
   提交。改打包脚本就要换提交，换提交就要重建两个子包、重跑 100 轮验收。为一行 import 做这些，
   代价与收益不成比例。
3. 客户侧规避写进了交付文档：删掉 `MindirProbe.ets` 第 4 行那个 import，并把该文件里三处
   `probe*` 调用改成抛错即可；该文件只是诊断探针，正式 SDK 本来也没有这三个函数。

**验证**：按上述规避改完后，独立构建 `BUILD SUCCESSFUL`（33 个 hvigor 任务），产出的签名 HAP
（`d26b30c1637bb9f4153975348acae1967c40afc6e10494f3aaaf47fe18d64740`）装机后 8 条 ITN 用例
全部达标，`sdk=PASS`、空 final 率 0.000。**除这一行 import 外，包内源码是完整可用的。**

## 独立构建环境上的两个坑（方法记录）

1. **CLT 自带的 node 是 v24.14.1，它不再支持 `NODE_PATH`。** hvigor 正是靠 `NODE_PATH`
   指向 `~/.hvigor/project_caches/<id>/workspace/node_modules` 来解析自己的插件，于是每次
   调用都死在 `Cannot find module '@ohos/hvigor-ohos-plugin'`。在 CLT 的 `hvigor/` 根下补出
   `node_modules/@ohos/{hvigor,hvigor-ohos-plugin}` 两个符号链接即可。这与交付包无关，是本机
   工具链供给问题，但任何人复现这一步都会先撞上它。
2. **`deviceInfo.ODID` 在卸载 demo 后会重新生成**，本地签发的授权随即失配，`setLicense`
   返回 `1002200033`。`hdc install` 覆盖安装保留 ODID，卸载不保留。该结论用已验证通过的
   Diagnostics HAP 反向验证过：重装之后它同样报 `1002200033`。

## CI 盲区（本轮暴露，建议修）

`.github/workflows/itn.yml` 只跑 Python 侧的 `InverseNormalizer`。本轮修的两处文本缺陷都在
**C++ ITN + 设备端标点**这条链路上，CI 结构上看不到：

- 数字折叠在 `wetext_processor.cc`，Python 入口不经过；
- 空格缺陷由设备端 ct-transformer 标点模型引入，主机侧完全不存在。

建议把本记录里那 8 条真机用例提升为交付前的固定回归项（设备侧），否则同类缺陷仍会漏到现场。

## 签名与授权来源

仓库内 `.secure/signing/asr-demo` 的叶子证书与 profile 均已于 **2026-09-15 过期**，无法签名。
本轮使用 DevEco 托管的 signing-project 材料（`~/.ohos/config/` 下 5 套有效材料之一，
有效至 2027-09-30、绑定 demo 包名、设备列表含本机 UDID），
经 `.cache/speaker-screen-repro-acf477c2/local-signing.json` 指向。

## 本轮打通的组包阻塞

1. Xcode 27 许可未接受导致 HAP 构建失败；切到 `/Library/Developer/CommandLineTools`。
2. `node-addon-api` 走 FetchContent 联网克隆失败（`GIT_VERSION_STRING` 为空）；
   改为预打补丁的本地缓存目录 + 在 `include(FetchContent)` 之前注入 `FETCHCONTENT_SOURCE_DIR_*`。
3. `third_party/.derived/sherpa-onnx` 是符号链接，hvigor 的 `exitIfNotExists` 不跟随符号链接，
   就地组包报 `Path not found`；就地打包前须换成真实目录副本。
   另 `asr/harmony/.hvigor/cache/project-config.json` 会残留旧的绝对树路径。
4. 验收报告与 Diagnostics 构建身份不一致：起因是用了 `--installed-package`；
   正确做法是 `--skip-build-install`。
5. Diagnostics ZIP 缺 `demo/*.hap`：需 `INCLUDE_SIGNED_DEMO=true`，
   并同时 `SKIP_BUILD=true`，否则就地的 hvigor 运行会清掉已签名 HAP。
6. 每次 `git commit --amend` 之后构建身份即过期（本轮撞了 3 次）；**先定稿提交再构建**。
7. 交付文档里出现机型代号被脱敏门禁拦下（第 10 / 112 行），已移除。

## 下一步

1. 取得客户目标说话人夹具后运行 `speaker-vad-turn`，方可把本记录从候选改为正式发布。
2. 下一个版本组包时确认 `MindirProbe.ets` 的剥离与新增的兜底门禁生效（本轮已做过脱机 dry-run）。
3. 包实际发出后，再用 `tools/delivery/asr_release_tracker.py record` 登记台账
   （本轮未登记，因为包尚未发出）。
4. 重建 Android AAR，消除两端行为差异。
5. 把 8 条 ITN 真机用例固化为交付前回归项。
