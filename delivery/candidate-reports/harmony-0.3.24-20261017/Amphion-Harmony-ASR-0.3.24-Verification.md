# Amphion HarmonyOS ASR 0.3.24 验收状态（未发布候选）

**状态：完整包已组并通过最终 ZIP 验收，带一项记录在案的豁免。** 正式 SDK、Diagnostics
子包、完整 ZIP、真机验收与本版三项修复的针对性验证全部绑定同一冻结提交
`776e2badfb8a3a2b4542724ded67a785a1e99411`（分支 `delivery/harmony-0.3.24`，组包时工作区干净）。

唯一缺口：`speaker-vad-turn` 沿用 0.3.20–0.3.23 的豁免（本检出与两个受控数据包中均无目标
说话人夹具）。按 `DEFAULT_DELIVERY.md`，缺该模式证据的包不具备正式发布资格，故仍按仓库既有
口径登记为未发布候选（`published: false`）。本版未改动该模式。

**与 0.3.23 的差别：0.3.23 带着"包内 `demo-source` 原样不可编译"的缺陷发出，本版不带。**
该类缺陷在本轮又出现了一次（这次是 `SdkSelfTest.ets` 导入只存在于 Diagnostics SDK 的
`amphion_police`），在组包流程中被发现并当场修掉，组包门禁也从"查一个已知内部模块"改成
"查每一个裸模块导入"。

| 产物 | 值 |
|---|---|
| 完整 ZIP | `Amphion-Harmony-ASR-Complete-0.3.24.zip`，1,717,640,164 字节 |
| SHA-256 | `d296336576d5596be56ce545c8d4c48f561dfda2e0a50eac6a6f7caed1d0abfd` |
| 位置 | `delivery/harmony-dingqiao/build/complete-sdk-0.3.24-776e2bad/` |

## 本版改动（相对 0.3.23 `9a5cc7b6`）

只改角色分离的**计算成本**与**组包脚本**，**不动识别模型、角色分离算法、阈值、窗口长度、
hop 与提交周期**。识别文本与 0.3.23 逐字一致。

| 改动 | 落点 | 对应问题 |
|---|---|---|
| 训练集上限 512（按时间均匀抽样）、短 run 候选上限 32、复用准入检查已算过的 `Ahc` 拟合 | `asr/harmony/sdk/src/main/cpp/community_cluster.h` | 聚类代价随会议时长失控：二次，说话人未满上限时为立方 |
| 预览自限流由音频时长的 1/10 改为 1/20 | `SpeakerDiarizationSession.ets` | 预览是角色分离里最大的单项（534.1 s / 1183.5 s） |
| 组包时剥掉 `SdkSelfTest.ets` 的 `amphion_police` 用例；组包门禁改为检查每一个裸模块导入 | `pack_complete_asr_delivery.sh`、`test_complete_delivery_package.py` | 交付包里的独立 Demo 源码无法编译 |
| 警务词条跨端对齐 | `PoliceTermsV2.ets`、同音词表 | 双端一致性 |

## 通过项

| 项 | 结果 |
|---|---|
| 组包前真机 `customer-ptt` | PASS，100/100 轮，空 final 率 0.000，原生流泄漏 0，内存 PASS（增长 63.0 MiB、斜率 11.98 MiB/min、峰值 596.1 MiB、HWM 614.3 MiB） |
| 最终 ZIP 复测（装包内 HAP） | PASS，100/100 轮，空 final 率 0.000，原生流泄漏 0，内存 PASS（增长 48.8 MiB、斜率 9.79 MiB/min、峰值 600.6 MiB） |
| 最终 ZIP 校验和 | PASS，`docs/checksums.txt` 全部 49 项逐一核对一致 |
| API 23 编译器兼容 | PASS，52 个公开 HAR TypeScript 文件由独立的 OpenHarmony 6.1 / API 23 `es2abc` 编译通过（与 0.3.23 同一把编译器） |
| 正式 SDK 子包 | PASS：版面、校验和、UTF-8 ZIP、CRC、zh-en 单语种、脱敏 16 文件 + 1 HAR；交付的 `amphion_dingqiao.har` 自报 `BUILD_MODE_NAME='debug'`、`HAR_VERSION='0.3.24'` |
| Diagnostics 子包 | PASS，`SKIP_BUILD` 绑定本提交的已验证 diagnostics 构建身份，含已签名 Demo |
| 独立 Demo 源码构建 | **PASS，且无需改任何一行源码**（见下） |
| 数字串回归 | PASS，8 条用例在包内 HAP 与独立构建的 HAP 上逐字相同，且与 0.3.23 一致 |
| 主机回归 | 204 项角色分离与聚类测试通过 |
| 仓库门禁 | layout / observability / versions 三项 PASS |

## 本版改动的针对性验证

### 成本（真机，同机、同语料 7332 秒、同参数，与 0.3.23 对照）

| 指标 | 0.3.23 | 0.3.24 |
|---|---|---|
| 角色分离总计算 | 1183.5 s | **924.4 s（−21.9%）** |
| RTF | 0.1614 | **0.1261** |
| 窗口推理 | 450.7 s | 453.0 s（持平，本就不该变） |
| 提交聚类 | 198.7 s | 202.2 s（持平，该项消的是随时长的增长） |
| 预览聚类 | 534.1 s | **269.3 s（−49.6%）** |
| 提交聚类增长指数 | 约 2.0 | **0.85** |

会话质量两轮一致：785 条 final、30800 字、说话人 4、`degraded=0`。

主机侧另加了一条回归：会话由 300 个窗口增到 570 个时，修前耗时比为 5.99（允许 3.0）而失败，
修后通过。

### 说话人归属未移动

该会话 65 次提交全部经两版聚类器重放并送入真实的 `CommunitySpeakerIdentity`；对照工具本身
以设备记录的 `clusterToFrozenId` 校验，**65/65 次提交一致**。上限以下真实数据逐位相同；上限
以上内部标签最多差 9.61%，经注册表吸收后公开说话人不一致 **5.90 s / 7332 s（0.08%）**，其中
真正"一个具名说话人变成另一个"仅 **0.61 s（0.0083%）**，无任何槽位丢失原有标签。

### 独立 Demo 源码：本轮发现并修掉的缺陷

本轮第一次组出的 0.3.24 包，其 `demo-source` **原样不可编译**：`SdkSelfTest.ets` 从
`amphion_police` 导入 `PoliceEnhancePipeline`，而该模块只随 Diagnostics SDK 发出，交付的
Demo 工程只带 `libs/amphion_dingqiao.har`，`CompileArkTS` 报 `10505001 Cannot find module
'amphion_police'`。这与 0.3.23 的 `MindirProbe.ets` 是同一类缺陷。

修法是两层：组包时剥掉这段词条回归用例；更重要的是把组包门禁从"查 `from 'amphion_asr'` 这一个
已知内部模块"改成"把每一个裸模块导入对照工程声明的依赖检查一遍"——`amphion_police` 当初正是
从前者的缝里漏过去的。`test_complete_delivery_package.py` 对产出的 ZIP 独立断言同一不变式，
该断言在旧组包脚本下失败、在新脚本下通过。

修完后的包内 `demo-source`：`ohpm install --all` 后 **34 个 hvigor 任务全部执行、BUILD
SUCCESSFUL，未改任何一行源码**；只补本地授权与签名材料后产出的签名 HAP 装机复测，8 条数字
用例与包内 HAP 逐字相同（`12345678910。123。12345。2.58万。13800138000。2026/05/15。38。
8910。`，9 条 final、59 字、0 错误）。

另需说明一个环境前提（不是包的缺陷）：命令行工具链下 `@ohos/hvigor-ohos-plugin` 需对工程可见，
DevEco Studio 会自动装好，离线 CLT 不会。

## 豁免项

| 模式 | 原因 |
|---|---|
| `speaker-vad-turn` | 沿用 0.3.20–0.3.23 的豁免：该模式需要目标说话人夹具，本检出与两个受控数据包中均不存在。本版未改动该模式。 |

## 未解决 / 未验证（请勿理解为已修复）

- **长会议进程内存**：2 小时会话峰值约 1.1 GB。已定位增长在 ArkTS 堆（103 分钟 +243 MB，占 RSS
  增量 84%），已排除 native 分配器扩张、证据缓冲堆积与诊断事件拷贝三种成因；对象级归因未完成，
  本版未修。三轮 100 轮 `customer-ptt` 均在通用预算内，不代表长会议已解决。
- **SDK 无遇热或按积压降级的机制**（按要求未实现）：降级只在存储不可用、推理不可用与收尾超时
  三种情况触发。
- **锁屏变慢未解决**（与 0.3.23 相同）：干净包锁屏期 0.856×/0.866×，缺口 0.134×。
- **以"十"结尾的数字串 `textNormalization.spans` 为空**（与 0.3.23 相同，文本正确）。
- **本版验证未覆盖两种场景**：所用音频为单一录音循环，说话人数很早达到上限，因此"长静音后换人"
  与短 run 候选上限的等价性均未被触发。前者是唯一可能让公开说话人编号错位的机制。
- **Android AAR 未在本轮重建**：`community_cluster.h` 由 Android 经 JNI 共用，两端行为暂不一致。
- **CI 缺口未补**（与 0.3.23 相同）：`itn.yml` 只跑 Python 侧 `InverseNormalizer`，设备文本路径
  CI 结构上看不到；那 8 条设备用例仍应纳入交付前回归。
- 本批语种范围为中英（ZH_EN），不含粤英模型；不包含 TTS 模型；目标说话人增强仅保留接口，不包含
  所需模型，不能启用。

## 环境备忘

`build_install_smoke.sh` 在本机返回 1：装包后的"引擎就绪"探测 30 秒超时。构建、构建身份文件与
其后每一轮 100 轮验收都正常通过。本轮有两条串起来的流水线因这个非零返回被 `set -e` 静默截断，
值得把探测时间放宽或加一次重试。
