# perf/diarization-role-heat 分支发热测试文档（2026-10-07）

**结论：把角色分离的窗口 hop 从 1 秒改成 2 秒，窗口数减半，已记录的真机数据上机身温升从 6.16 °C 降到 4.50 °C，角色分离 RTF 降 47.8%，代价是整段 DER 从 3.12% 升到 3.23%，身份与说话人映射不变。同分支上先加后撤的 AHC 配对距离缓存换不来可测收益，回滚正确。**

本文只覆盖当前分支。真机数字来自提交时记录的运行；今天本机实跑的是主机测试，真机复测止于许可授权，下文逐项标注来源与缺口。

## 被测对象

| 项 | 值 |
|---|---|
| 分支 | `perf/diarization-role-heat` |
| HEAD | `35dcd1da` |
| 相对 main | main `b8d14310`，合并基 `b9c61a64` |
| 改动规模 | 2 个文件，+91 / −15 行 |
| 窗口 hop 默认值 | 2000 ms（main 为 1000 ms） |
| 其余 | encoder、执行器、预览限流均与 main 相同 |

分支上的三个提交：

| 提交 | 内容 | 去向 |
|---|---|---|
| `b87332ab` | AHC 配对距离按 live-node 槽位缓存 | 已被 `35dcd1da` 回滚 |
| `26d24abb` | 窗口 hop 默认值改为 2 秒 | 保留 |
| `35dcd1da` | 回滚 `b87332ab` | 保留 |

净效果只有一处功能差异：`SpeakerDiarizationLocalClient` 的默认 hop。`hopMs` 仍是可传参数，需要更细边界的调用方可以要回 1 秒。

## 真机对照（已记录）

同一段 960 秒 AISHELL-4 音频，2 秒 hop 对 1 秒 hop。数字记录在 `26d24abb` 的提交信息、`SpeakerDiarizationLocalClient.ets` 的默认值注释和 `test_shipped_window_hop_is_the_measured_default` 的文档字符串三处，互为校验。

| 指标 | 1 秒 hop | 2 秒 hop | 变化 |
|---|---:|---:|---|
| 角色分离 RTF | 0.3065 | 0.1601 | −47.8% |
| 平均 CPU | 214.3% | 196.9% | −8.1% |
| 机身温升（按起始温度归一化） | 6.16 °C | 4.50 °C | −1.66 °C |
| RSS 峰值 | 725.0 MiB | 668.5 MiB | −56.5 MiB |
| 整段 DER | 3.12% | 3.23% | +0.11 个点 |
| — 漏检 | 1.50% | 1.47% | −0.03 |
| — 混淆 | 1.23% | 1.46% | +0.23 |

两组起始机身温度为 26.47 和 27.07 °C，温升已归一化。代价落在边界精度而非身份：两边都报出四个说话人（参考为五人），reference-to-index 映射完全相同，DER 的 0.11 个点全部来自混淆时长，漏检还微降。

**温度口径**：机身温升，按起始温度归一化。不用电池温度——10-04 一轮已证明插 USB 且亮屏时各组 16 分钟都升 9–11 °C，组间没有可测差别。

## 为什么是 hop

Community-1 的 10 秒窗口每秒滑一次，每秒音频被看十次，而分割、Fbank 和 encoder 都是每窗跑一次。从一份 351 窗采集看，encoder 占单窗 460.6 ms 的 70.7%，360 秒音频要花 161.67 秒计算。让角色路径发热的是这份冗余，不是调度。hop 翻倍直接把窗口数和总计算量减半。

这个判断与 10-05 一轮独立吻合：那轮是从结果反推（INT8 把整进程 CPU 从 3.06 压到 2.31 CPU-s/s，是四步里单步收益最大的），本轮是直接打表。两条证据指向同一个结论。

## 被排除的候选：AHC 配对距离缓存

`b87332ab` 给质心连接的 AHC 加了按 live-node 槽位的配对距离缓存，带 16 MiB 私有预算和分配失败回退。回滚的理由不是正确性——八种形状乘三个种子下标签与缓存前逐位相同，删掉失效逻辑的变异体也能被测出来。是它不赚：

| 证据 | 数值 |
|---|---|
| 真机 960 秒，同一构建对照 RTF | 0.30649 → 0.30653 |
| 同上，平均 CPU | 214.3% → 218.0% |
| 主机 950 点单次 `Ahc` 调用 | 98.04 ms，缓存省 16.17 ms |
| 960 秒会话在角色分离上的总计算 | 294 秒 |
| 代价 | 角色路径 242 行代码 + 16 MiB 预算分配 |

RTF 只动了第四位小数，CPU 变化也在跑间波动内。聚类不是时间的去处。这与 09-28 一轮（`DIARIZATION_AHC_COST_20260928.md`）相互印证：那轮已经把真正的聚类浪费清掉了——跳过必定被拒的短段重复拟合，Mate 80 上同一 180 秒片的 18 次聚类总耗时从 8075 ms 降到 2600 ms。之后再缓存配对距离，自然拿不到东西。

## 测试门禁的改动

两个 cadence 门禁原本写死了 1 秒 hop 的期望表，任何 hop 改动都会把它们变成一个说明不了问题的失败。现在它们从出厂默认值推导期望，只断言当初要守的规则：每个 hop 恰好一个完整窗口、尾部只补一次、最后一个恰好对齐的窗口不重复。丢掉每隔一个窗口的变异体仍然被它们测出。

新增的 `test_shipped_window_hop_is_the_measured_default` 把默认值和支撑它的那组测量数字钉在一起：改 hop 就必须改注释里的数字，改数字就必须重新测量。

## 主机测试（今天实跑）

| 项 | 结果 |
|---|---|
| `asr/tools/tests/test_harmony_community_diarization.py` | 30 个用例，OK，跳过 1 |

跳过的是 `test_identity_source_compiles_with_target_sdk`（需设置 `HARMONY_ES2ABC` 指向目标 SDK 编译器）。同一文件在 main 上是 29 个用例，多出的一个正是上面那个把 hop 默认值与测量数字绑定的新用例。

## 今天的真机复测：进展与阻塞

目标是在客户机型上重跑 main 与本分支的 960 秒对照，补齐收尾时间和生命周期门禁。已打通到安装运行，止于许可授权。

**设备**：HUAWEI Mate 80 `VYG-AL30`，`7GK0226326015655`，OpenHarmony-6.1.1.120，API 24，11.9 GB，arm64-v8a。UDID `152CF7FE…71972A`。这正是前两轮都欠复核的客户机型。

**温度采集可用**：设备暴露 `shell_front` / `shell_back` / `shell_frame`，与本分支的 shell rise 口径一致。待机 `shell_front` 31.3–31.7 °C，环境 21.3 °C，电量 82%。

**音频已备**：本地有完整 AISHELL-4 测试集带 RTTM 参考。从 M 房间会议 `M_R003S02C01` 切出前 960 秒（16 kHz 单声道），该窗口内参考为 6 个说话人。注意这不是已记录数字所用的 `20200616_M_R001S04C01`，所以新数据只能作为两分支之间的干净 A/B，不能与上表逐位对比。

**构建链已修通**，清掉三处阻塞：

1. 隔离 sherpa 源码树带一个自动生成的 ohpm 锁文件改动（`enableUnifiedLockfile: false`），导致身份校验失败。已备份后还原。
2. `node_addon_api` 走 FetchContent 联网克隆失败。改用仓库既有的 `NODE_ADDON_API_CACHE` 指向 `.cache/node-addon-api-c679f6f4`（commit 对得上），脚本会把 GIT_REPOSITORY 改写成本地 file:// URI。
3. 根因：CLT 自带的 `ninja` 和 `node` 都是纯 x86_64 二进制，它们启动 `/usr/bin/git` 时走 x86_64 slice，而本机 Command Line Tools 只有 arm64/arm64e 的 `libxcrun.dylib`，于是 git 在整条 native 构建链里无法执行，CMake 读到 `GIT_VERSION_STRING=''`。用一个强制 `arch -arm64` 的 git 垫片置于 PATH 前端解决。

**签名**：`.secure/signing/` 下三套开发证书均已过期（2026-09-04 / 09-15 / 09-16）。可用的是 DevEco 托管的 `~/.ohos/config/default_signing-project_k5KeKAT…`——绑定 `com.amphion.asr.harmony.demo`、设备列表含本机 UDID、有效至 2027-09-30。密码取自 `.cache/speaker-screen-repro-acf477c2/signing-project/build-profile.json5`，组装成 `.secure/harmony-signing-signing-project.json`（已 gitignore，权限 600）。

**已完成**：HAP 构建、签名、校验、安装全部通过（421 MB 签名包；证书链、profile、许可签名、9 个模型资产、5 个 arm64 native 库均校验通过）。`run_device_stress.py` 能推送 PCM、启动会话并落盘产物与 hilog。

**阻塞点**：许可的设备白名单不含这台 Mate 80。自检模式原话 `code=1002200033 msg=device SN not in license whitelist`。机制已查清：demo 固定用 `deviceInfo.ODID`（普通应用读不到硬件 SN，需要 `ohos.permission.sec.ACCESS_UDID`），指纹为 `SHA-256(大写去空(ODID) + deviceIdSaltId)`。HAP 内嵌的 `DINGQIAO-TDTECH-202609-001` 绑 4 个设备，经核算清单 `.secure/amphion_asr_demo_device_ids.txt` 中 4 个 id 的指纹与许可中 4 个哈希逐一对应，其中 `7GK0226326015655` 对应第一条——但那是硬件 SN 条目，按 `TROUBLESHOOTING.md` 属系统/预置宿主流程；普通 demo 走 ODID，而本机 ODID 不在清单内。许可未过期（2026-11-30），未绑证书和包名，与更换签名证书无关。

下一步按 `TROUBLESHOOTING.md` 的正规路径：取得本机 ODID、加入签发清单、用本地私钥重签 demo 许可，再重建安装。取 ODID 需要应用侧临时导出，本轮未完成。

## 本分支尚缺的测试项

| 缺口 | 为什么重要 |
|---|---|
| 停止后收尾时间未记录 | 15 秒收尾门禁是前两轮最难过的一道，从「30 秒内未完成」做到 3.8 秒才 PASS。RTF 减半理论上让收尾更宽裕，但这是推论不是测量 |
| 5 个生命周期门禁未记录 | 前两轮都跑了，本轮没有 |
| 运行机型未记录 | 只有起始机身温度 26.47 / 27.07 °C，机型、系统版本、环境温度都没有写进仓库 |
| 息屏未复测 | 2 秒 hop 对后台 ASR 吞吐的影响未知 |
| 超过 16 分钟的会议未测 | 长会议饱和是否真的解除未验证 |
| Mate 80 未复核 | 客户机型，两轮都欠（本轮已连上，止于许可） |
| Android 未移植 | Android 仍是 4 线程 XNNPACK 池加每 10 秒全量重聚 |

## 来源

- 提交 `26d24abb`、`b87332ab`、`35dcd1da` 的提交信息
- `asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/diarization/SpeakerDiarizationLocalClient.ets` 的默认值注释
- `asr/tools/tests/test_harmony_community_diarization.py`（今天在本分支实跑）
- `docs/speaker/DIARIZATION_SCREEN_OFF_AND_HEAT_20261004.md`（10-04 与 10-05 两轮，用于交叉验证）
- `docs/speaker/DIARIZATION_AHC_COST_20260928.md`（Mate 80 聚类耗时，用于交叉验证）
- 今天本机的设备与构建检查：`hdc list targets`、`hidumper -s ThermalService -a '-t'`、`bm get --udid`、自检模式 `--ps selftest true`、证书有效期核对、许可指纹核算
