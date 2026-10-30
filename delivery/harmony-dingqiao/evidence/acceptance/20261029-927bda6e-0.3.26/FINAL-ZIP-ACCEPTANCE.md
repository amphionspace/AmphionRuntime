# HarmonyOS ASR SDK 0.3.26 最终 ZIP 验收报告

> 本文件放在最终 ZIP 之外，绑定该 ZIP 自身的 SHA-256，不随包交付。
>
> 本文件**按设计记载测试机型号与序列号**：随包摘要里这两项被脱敏门禁拒绝，因此在摘要中写的是
> 「机型与序列号见外置最终报告」。包内文档的脱敏门禁不适用于本文件。

验收结论：**所列功能、生命周期与两处缺陷修复通过；`speaker-vad-turn` 模式带一项记录在案的
豁免**（归属断言 6/6 通过，但该模式自设的收尾时延预算未达成，详见「豁免与未覆盖」）。

## 交付身份

| 项目 | 冻结值 |
|---|---|
| 完整 ZIP | `Amphion-Harmony-ASR-Complete-0.3.26.zip` |
| SHA-256 | `860d731f7228c326f3116903e1b14c3bfb4ea65172351f780c8918a243b2d224` |
| 字节数 | 1939479824 |
| SDK / Demo 版本 | 0.3.26 / 0.3.26（versionCode 326） |
| 源码提交 | `927bda6eb122f5a0ad25dd4ec04b8316237bc026` |
| 交付分支 | `feat/harmony-sortformer-diarization`（组包时工作区干净，尚未合入 main） |
| 能力及架构 | 中英 ZH_EN、ASR + 角色分离 + 机主识别、arm64-v8a，模型内置 |
| 真机 | HUAWEI VYG-AL30，HarmonyOS 7.0.0.109，arm64-v8a，序列号 7GK0226326015655 |
| 签名与授权 | 本地 DevEco 自签证书（`signing-project`，叶证书有效期至 2049-03-16）；Demo 内置试用授权 `DINGQIAO-TDTECH-202610-001`，不绑设备，ASR+TTS，2026-12-22 到期 |

五目录完整交付：Release SDK、Diagnostics SDK、已签名 Diagnostics Demo、独立 Demo 源码、
文档及组包前证据。源码不含私钥或商用授权；本地构建测试仅补入既有授权与签名材料。

## 子包与产物哈希

| 产物 | 字节数 | SHA-256 |
|---|---:|---|
| `release-sdk/amphion-harmony-asr-sdk-v0.3.26-20261029.zip` | 390439622 | `14c7901aeb245c6e04072b1cd573db945d5b6bad7682208d8443bcf6498b4a58` |
| `diagnostics-sdk/Amphion-ASR-Diagnostics-SDK.zip` | 773898586 | `618e20a645adda58e74fbc47781eded6898bf441478226393ff9955d97b6858a` |
| 包内公开 HAR `har/amphion_dingqiao.har` | — | `adc3b77d8bc258df41a99117c46f7939fe006eabdbc5de7102b0482168495a38` |
| 包内已签名 Diagnostics Demo HAP | — | `c520b8d0e668edfdd4c3ca7f31c99007a887719ce953be502ee45c597e909c7a` |
| 独立构建产出的签名 HAP | — | `60af50c5dec6af70a1bdd4c24fe58bc1b13556eed581c192f561ef465aacc1b5` |
| 组包前验收摘要 `docs/ACCEPTANCE-SUMMARY.md` | — | `ef634d129aab80441cd5b04e66ded4419df8c3047988c1efec93081720bf83e7` |

## 已执行验证

| 验证 | 结果 | 证据及实际范围 |
|---|---|---|
| ZIP 完整性与内容校验 | PASS | 固定外层 SHA-256 后解压，包内 `docs/checksums.txt` 全部 50 项逐条一致 |
| 包内身份一致性 | PASS | `docs/build-identity.json` 与 Diagnostics 子包逐字段一致（`created_at` 除外）；两个子包与四份真机报告同绑 `927bda6e` |
| 披露检查 | PASS | 包内无评测探针、评测脚本、评测语料与内部路径；Release 子包脱敏门禁 16 文件 / 1 个 HAR |
| API 23（OpenHarmony 6.1）编译兼容 | PASS | 52 个公开 TypeScript 文件，独立 es2abc |
| 真机 `customer-ptt`（组包前，Diagnostics 构建） | PASS | 12/12 轮，空 final 率 0.000，原生流 0 泄漏，内存 PASS（增长 19.36 MiB、峰值 418.1 MiB），CPU 均值 118.8% 单核等效 |
| 真机 `diarization-windows`（组包前，现场录音 4 条 ≥ 120 s） | PASS | 4/4 轮，角色生命周期 PASS，结束到最终角色结果 1137~2280 ms，推理 RTF 0.256~0.271 |
| 角色分离精度（openbench-der-v1） | 测得 | 4 条全集 DER 12.10%（0.3.25 Community 链路同机同音频 23.10%）；逐条 3.01 / 13.50 / 26.24（退化，原 10.34）/ 6.44% |
| 真机热词 7 例（组包前） | 6/7 正确 | 第 7 例为构造的七字前缀探针，仍丢 5 位数字；其余含贵方原样 53 词在内全部正确 |
| 真机机主换人 6 例（组包前） | 归属 PASS 6/6 | 修复前同夹具 2/6 泄露非机主首句；该模式单轮判定仍 FAIL，见豁免 |
| 最终 ZIP 内 Diagnostics Demo 装机复测 | PASS | 从该 ZIP 解压、明确安装 `-signed.hap`，`--installed-package` 取安装包身份（versionName 0.3.26 / versionCode 326）；`customer-ptt` 12/12 轮，空 final 率 0.000，内存 PASS（增长 16.39 MiB、峰值 412.1 MiB） |
| 最终 ZIP 源码 + 包内正式 HAR 独立构建 | PASS | 仅补入本地授权 rawfile 与签名材料，`ohpm install --all` 后 `assembleHap`：**34 个构建任务全部通过、未改任何一行源码**；产出 `-signed.hap` 如上 |
| 独立构建产物装机复测 | PASS | 明确安装 `-signed.hap`：热词 7 例输出与包内 Diagnostics Demo **逐字相同**（含第 7 例探针的同一残余）；`customer-ptt` 12/12 轮，空 final 率 0.000，内存 PASS（增长 7.29 MiB、峰值 401.6 MiB） |
| 主机回归 | PASS / 既有失败已列明 | 交付 270 项全通过；`asr/tools/tests` 634 项中 2 失败 1 错误，均为既有问题（见下） |

热词修复出现在**公开 Release HAR 路径**上这一条，由「独立构建产物装机复测」提供：该 HAP 只
依赖包内 `amphion_dingqiao.har`，其 7 例输出与 Diagnostics 构建逐字相同，因此修复不是只存在于
诊断构建里。

## 豁免与未覆盖

- **`speaker-vad-turn` 豁免（本轮理由已更换）**：该模式自 0.3.20 起因「无客户目标说话人夹具」
  被豁免。本轮夹具首次具备并实际执行，**归属断言 6/6 通过**，但模式单轮判定仍为 FAIL：载体
  自设的「收尾补救 finish → 非空 final ≤ 1200 ms」预算未达成，6 例中 4 例靠收尾补判检出换人，
  其中 3 例为 1652~1732 ms。构成为换人分割推理约 160 ms、机主前缀重解码约 790 ms、前缀 final
  补尾刷新约 400 ms 与打分派发约 300 ms。该时延在本版修复前后基本不变（修前 1637~1813 ms），
  不是本次修复引入，且落在随包声明的「结束到最终角色结果 1.1~2.4 s」之内；说话过程中临时
  结果持续刷新，不存在等待期无文字。因受检报告要求 PASS，本包按记录在案的豁免交付，豁免理由
  在 `docs/acceptance-manifest.json` 与 `docs/ACCEPTANCE-SUMMARY.md` 中均已披露。
- **0.45 句级下沿的注册同源偏乐观**：阈值依据的注册音与测试音同一会话，机主一侧偏高。跨会话
  注册下机主短句是否会被误拒未验证，需客户真实声纹复测。
- **111223-816 一条 DER 退化**：10.34% → 26.24%（约 4 秒混淆）。
- **热词召回代价**：主机 500 条回归中 619 个热词实例少命中 1 个；七字前缀探针仍丢 5 位数字。
  首字封顶一处真机上只证明了「无回退」，产品层把预置池权重固定为 3.0，该录音在 3.0 不翻转。
- **长会话**：2 小时单会话实测通过（峰值 RSS 911 MB、内核水位 926 MB、斜率 1.13 MB/min），
  由同一角色分离运行时的早前一轮构建测得，本提交未重跑。ArkTS 堆单调上升未归因。
- **功耗**：USB 供电下电流读数为净充电电流，绝对功耗无法测量，以 CPU 时间为代理。
- **AliMeeting** 20 窗 12.74% 为探针实测，产品链路未重跑。
- **短于 120 秒的会话**只有终结一次角色结果，`diarization-windows` 夹具因此判 FAIL，属夹具前置
  条件而非产品缺陷，0.3.25 同。
- **Android 端未在本轮重建**：两个热词补丁位于两端共用的 C++ 源码但 Android AAR 未重编；
  Android 的机主换人修复在独立分支上待真机验证。
- **源码版移除了内部探针**，其 `liveStreams=0` 不作为资源回收的实测证据。
- **三项既有主机测试失败**（与本版无关）：`test_police_enhancement_demo_toggle` 断言的单行
  `amphion_police` 导入已被 main 自身的提交 `9334ebdc` 改为两符号导入而未同步，在 main 上同样
  失败；`test_sherpa_source_isolation` 的幂等用例在本检出上加不加新补丁都失败；
  `test_speaker_vad_dataset` 在本解释器下无法导入 `sherpa_onnx`。

## 发布资格

本包为**未发布候选**（`published: false`）：`speaker-vad-turn` 的受检报告判定为 FAIL 按豁免
处理，按 `DEFAULT_DELIVERY.md` 不具备正式发布资格；交付分支亦尚未合入 main。按用户明确授权
可带披露豁免交付与归档。状态记录见 `delivery/candidate-reports/harmony-0.3.26-20261029/`。
