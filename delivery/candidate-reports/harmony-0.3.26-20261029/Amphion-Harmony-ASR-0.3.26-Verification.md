# Amphion HarmonyOS ASR 0.3.26 验收状态（未发布候选）

**状态：完整包已组并通过最终 ZIP 验收，带一项记录在案的豁免。** 正式 SDK、Diagnostics
子包、完整 ZIP 与真机验收全部绑定同一冻结提交 `2d49bec598a577ce9cce64f5d2e5bdd7ec8542e9`
（分支 `feat/harmony-sortformer-diarization`，组包时工作区干净，**尚未合入 main**）。

唯一缺口：`speaker-vad-turn` 沿用 0.3.20–0.3.25 的豁免（本检出无目标说话人夹具）。按
`DEFAULT_DELIVERY.md`，缺该模式证据的包不具备正式发布资格，故登记为未发布候选（`published: false`）。

| 产物 | 值 |
|---|---|
| 完整 ZIP | `Amphion-Harmony-ASR-Complete-0.3.26.zip`，1,939,450,943 字节 |
| SHA-256 | `d9a69c9e1bbfd62a7bab40f5c27fdb5717feb85f8f67a609a04e2ee58a698e72` |
| 位置 | `~/.cache/amphion-runtime/delivery-staging/asr/harmony/0.3.26/2d49bec5/packages/complete/` |
| Release 子包 | `amphion-harmony-asr-sdk-v0.3.26-20261029.zip`，390,431,679 字节，`b3ceee1cb5cee3e5adbb9a11243e89c0e67451cffcc2929198829218090e1339` |
| Diagnostics 子包 | `Amphion-ASR-Diagnostics-SDK.zip`，773,888,466 字节，`8bc78869ffeae3d941368991018eb68a4785c71fcd4f1b82b673816abc5a3ed6` |
| 设备 | HUAWEI VYG-AL30，HarmonyOS 7.0.0.109，arm64-v8a |

## 本版改动（相对 0.3.25 `a63e5834`）

| 改动 | 落点 | 说明 |
|---|---|---|
| 角色分离换为 Sortformer-66M-4spk 流式模型（CPU，ORT 1.16.3），Community-1 链路整体移除、不留后备 | `sortformer_diarization.cpp`、`SortformerLocalClient.ets`、`SpeakerDiarizationSession.ets` | 9.92 s 块提交 + 可选块内预览（`diarizationPreviewMs` 默认 5000） |
| 相邻同人句子合并为一项，新增 `DiarizedUtterance.sourceUtteranceIds` | `SpeakerDiarizationTranscriptState.ts`、`DingqiaoModels.ets` | `speakerIndex=-1` 不参与；`speakerTurns` 不变 |
| 模型资产清单与构建身份绑定 7 个 Sortformer 资产 | `sortformer_diarization_v1.json`、`harmony_build_identity.py` | MindIR 门禁移除 |

## 通过项

| 项 | 结果 |
|---|---|
| 组包前真机 `customer-ptt` | PASS，12/12 轮，空 final 率 0.000，原生流泄漏 0，内存 PASS（增长 13.2 MiB、峰值 419.1 MiB） |
| 组包前真机 `diarization-windows`（丁桥 4 条 ≥ 120 s） | PASS，4/4 轮，角色生命周期 PASS，结束到最终结果 1.1~2.2 s |
| 角色分离精度（openbench-der-v1，同机同音频） | 丁桥 4 条 DER **12.10%**（0.3.25 Community 23.10%）；逐条 3.01 / 13.50 / 26.24（退化，原 10.34）/ 6.44% |
| 相邻同人合并真机佐证 | 回传 131 条 utterance 中 9 条为合并项（`sourceUtteranceIds` > 1） |
| 最终 ZIP 复测（装包内 HAP） | PASS，12/12 轮，空 final 率 0.000，内存 PASS（增长 17.5 MiB、峰值 415.1 MiB），`versionCode 326` |
| 最终 ZIP 校验和 | PASS，`docs/checksums.txt` 全部 50 项一致；包内 identity 与 Diagnostics 子包逐字段一致 |
| 披露检查 | 包内无评测探针、评测脚本、评测语料与内部路径；Release 子包脱敏门禁 PASS（16 文件 / 1 HAR） |
| API 23 编译兼容 | PASS，52 个文件 |

## 代价与未覆盖

- **算力上升**：识别与角色分离并行时，角色分离推理墙钟 RTF 0.25~0.27（0.3.25 为 0.07~0.09），
  整进程 CPU 均值 1.76 核（1.58 核），峰值 RSS 711~804 MB（581 MB）。已写入随包文档。
- **AliMeeting** 20 窗 12.74% 为探针实测，产品链路未重跑。
- **2 小时长会**（组包后用包内 Demo 复测，同身份）：7381 s 单会话 PASS，RSS 峰值 911 MB、HWM 926 MB、斜率 1.13 MB/min（0.3.24：1160 / 1222 MB、约 2.0 MB/min），线程稳定；电池 26.0 → 37.0 °C（0.081 °C/min），整进程 CPU 均值 1.86 核。ArkTS 堆单调上升未归因。见 `docs/speaker/SORTFORMER_2H_SESSION_20261029.md`。
- **功耗**：USB 供电下电流读数不可用，以 CPU 时间为代理。
- `demo-source` 仍随附历史遗留的 `MindirProbe.ets` 公开桩（仅抛「仅诊断 SDK 可用」），与 0.3.25 相同，建议 0.3.27 清理。
- Android 端仍为 Community 链路，双端角色分离不一致，直至 Android 重建。

## 取代关系

本轮取代同版本两轮未交付的构建：`719f34ee`（变更日志含测试机型号，被脱敏门禁拒绝）与
`2a9f9cf3`（组包完成后追加了相邻同人合并改动）。两轮的 `customer-ptt` / `diarization-windows`
结论与本轮一致。
