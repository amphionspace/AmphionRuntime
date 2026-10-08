# Amphion HarmonyOS ASR 0.3.20 验收状态（未发布）

**状态：完整包已组并通过最终 ZIP 验收，但带一项记录在案的豁免。** 正式 SDK、Diagnostics、完整 ZIP 与真机证据全部绑定同一冻结提交。`speaker-vad-turn` 经交付负责人指示豁免，清单声明理由、随包的验收摘要同步披露、打包时打印警告。按 `DEFAULT_DELIVERY.md`，缺该模式证据的包**不具备正式发布资格**，登记为未发布候选（`published: false`）。

| 产物 | 值 |
|---|---|
| 完整 ZIP | `Amphion-Harmony-ASR-Complete-0.3.20.zip`，1,667,827,806 字节 |
| SHA-256 | `9a7fd99d36c7e0f9b795f239502dcc7185b042f1dcd0845d1aa13451d33deacf` |

## 最终 ZIP 验收

| 项 | 结果 |
|---|---|
| 固定哈希后解包 | PASS，五个目录齐全（`release-sdk`、`diagnostics-sdk`、`diagnostics-demo`、`demo-source`、`docs`）|
| 安装包内 `-signed.hap` | PASS，精确选取 `amphion_asr_demo-diagnostics-signed.hap` |
| 包内 demo 复测 | PASS，`customer-ptt` 1 轮，`--installed-package`，sdk=PASS、memory=PASS、空 final 率 0 |
| 包内源码独立构建 | PASS，依赖 `libs/amphion_dingqiao.har`，只补本地授权与签名，33 个 hvigor 任务 |
| 源码构建产物复测 | PASS，`customer-ptt` 1 轮，sdk=PASS、memory=PASS、空 final 率 0 |

源码独立构建首次失败于资源路径错误：源码包自身不含 `rawfile` 目录，授权文件须放入该目录后方可加载。

## 冻结身份

| 项 | 值 |
|---|---|
| 版本 | 0.3.20，版本日期 2026-10-07 |
| 源码提交 | 见 `harmony.json` 的 `source_commit` |
| 分支 | `delivery/harmony-asr-20261007` |
| 语种范围 | 中英（ZH_EN） |
| 设备 | Mate 80，OpenHarmony-6.1.1.120，API 24，arm64-v8a |
| 暂存目录 | `~/.cache/amphion-runtime/delivery-staging/asr/harmony/0.3.20/9aecc49e` |

## 已通过

| 项 | 结果 |
|---|---|
| API 23 编译兼容 | PASS，52 个公开 HAR TypeScript 文件，使用独立公开 SDK 6.1.0.31 的 `es2abc` |
| 正式 SDK 子包 | PASS，布局、校验和、UTF-8 ZIP、CRC、zh-en SDK-only 校验均通过 |
| Diagnostics 子包 | PASS，由同一提交的 diagnostics 构建身份产出 |
| 真机 `customer-ptt` | PASS，2 轮，sdk=PASS、memory=PASS、空 final 率 0 |
| 真机角色分离发热 | PASS，960 秒会议收尾 3942 ms（门禁 15000 ms）、空 final 率 0、生命周期 1/1；RTF 0.3190、平均 CPU 238.0%、机身温升 6.35 °C、RSS 峰值 738.7 MiB |
| 主机测试 | 交付相关 258 项、角色分离契约 29 项、sherpa 隔离 7 项、Harmony 工具链 3 项全部通过 |

## 未完成与未覆盖

保留原状，不改写为通过。

| 项 | 状态 | 原因 |
|---|---|---|
| 真机 `speaker-vad-turn` | FAIL（结构性，非产品缺陷） | 不传清单、并关闭内容门禁时：`sdk=PASS`、`memory=PASS`、各轮 `status=PASS`，但全部 final 为空，实时性门禁以 `no trigger-to-final metrics observed` 失败。不传清单时源文件只按路径排序，没有语音被归到已建档说话人，目标说话人 VAD 将其全部抑制。该模式需要客户目标说话人夹具，两个已拉取的 bundle 里都没有 |
| 完整 ZIP | NOT_BUILT | 依赖上一项 |
| 最终 ZIP 验收、包内源码独立构建 | NOT_RUN | 依赖完整 ZIP |
| 粤英语种 | 不在本批范围 | 受控输入中无粤英模型。HAR 仍声明该能力但无法启用；恢复范围须作为独立交付范围评审 |
| 长会议发热 | INCONCLUSIVE | 16 分钟内机身温度单调上升，结束时仍在上升；更长会议未验证 |
| 息屏 | NOT_RUN | 本机型未复测 |
| 长稳内存 | INCONCLUSIVE | 通用 RSS 增长对角色分离只作参考，未采集分阶段对齐证据 |
| 断网网络观测 | NOT_RUN | — |
| 客户 Windows DevEco 6.1 工程 | NOT_RUN | — |

## 本轮打通的构建阻塞

这台主机此前无法完成交付组包，依次解决：

1. 隔离 sherpa 源码树带一个自动生成的 ohpm 锁文件改动，身份校验失败；备份后还原。
2. `node_addon_api` 走 FetchContent 联网克隆失败；改用仓库既有的 `NODE_ADDON_API_CACHE` 指向本地缓存，脚本会把 GIT_REPOSITORY 改写为本地 `file://`。
3. CLT 自带的 `ninja` 与 `node` 为纯 x86_64，其子进程启动 `/usr/bin/git` 走 x86_64 slice，而本机 Command Line Tools 只有 arm64 的 `libxcrun.dylib`，CMake 读到空的 `GIT_VERSION_STRING`；用强制 `arch -arm64` 的 git 垫片置于 PATH 前端解决。
4. `.secure/signing/` 三套开发证书均过期；改用 DevEco 托管的有效材料（绑定 demo 包名、含本机 UDID、有效至 2027-09-30）。
5. 许可设备白名单不含本机 ODID；按 `TROUBLESHOOTING.md` 正规路径取得 ODID、加入签发清单、用本地私钥重签 demo 许可。
6. `sdk-dingqiao` 的 81 MB 角色分离模型资产未进 `.gitignore`，被当作未跟踪改动，使"干净工作区"门禁无法通过；按 `sdk` 与 `android` 的同样写法补上。
7. 两份 sherpa `libsherpa-onnx-c-api.so` 不一致（SDK 模块为已不再钉住代次的旧产物）；按 `DELIVERY.md` 步骤重建 native 并分发，两份现已一致。

## 受控测试数据

`aishell3-500`（500 个 WAV，按说话人目录组织，带 punc+hotwords 转写）与 `dingqiao-meeting-20260918`（五段客户授权会议录音、MOSS 与人工裁定）已于 2026-10-07 从 OBS 拉取并校验通过。两者都不含目标说话人夹具清单。

`team-secure-state-v5` 未拉取：它的权威设备白名单与本机一处临时改动冲突（为给本机 ODID 开白名单，已还原为权威的 128 字节版本），现在直接 fetch 即可。**该 bundle 是签名材料与设备白名单的权威来源**；本轮使用的签名配置与本地重签的 demo 许可都不是权威来源，正式发布前应以它替换。

## 关于 `speaker-vad-turn` 的豁免

交付负责人已指示本批跳过该模式。实现方式应为**显式记录的豁免**而非移除门禁：清单声明 `waived_modes` 及理由，验收摘要同步披露，门禁其余部分不变，包内自带豁免证据。该改动涉及交付门禁，需负责人批准后执行。

## 下一步

1. 按上一节执行豁免，或取得客户目标说话人夹具后运行 `speaker-vad-turn`（2 轮，diagnostics 构建），与 `customer-ptt` 报告一并写入 `acceptance-manifest.json`。
2. 运行 `pack_complete_asr_delivery.sh` 组完整 ZIP 并固定其 SHA-256。
3. 从该 ZIP 解包安装包内 `-signed.hap`，用包内源码与正式 HAR 独立构建，在同一机型复测并记录输入、产物哈希与安装结果。
4. 按 `ASR_DELIVERY_WORKFLOW.md` 第 4、5 节登记状态、起草交付说明并归档。
