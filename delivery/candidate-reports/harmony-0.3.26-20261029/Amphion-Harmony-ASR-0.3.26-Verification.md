# Amphion HarmonyOS ASR 0.3.26 验收状态（未发布候选）

**状态：完整包已组并通过最终 ZIP 验收，带一项记录在案的豁免。** 正式 SDK、Diagnostics
子包、完整 ZIP 与真机验收全部绑定同一冻结提交 `927bda6eb122f5a0ad25dd4ec04b8316237bc026`
（分支 `feat/harmony-sortformer-diarization`，组包时工作区干净，**尚未合入 main**）。

唯一缺口：`speaker-vad-turn`。该模式本轮**首次具备夹具并实际执行**，6 例归属断言全部通过，
但单轮判定仍为 FAIL —— 载体自设的「收尾补救 finish 到非空 final ≤ 1200 ms」预算未达成。按
`DEFAULT_DELIVERY.md`，受检报告必须 PASS，故该模式按豁免登记，包仍为未发布候选
（`published: false`）。

| 产物 | 值 |
|---|---|
| 完整 ZIP | `Amphion-Harmony-ASR-Complete-0.3.26.zip`，1,939,479,824 字节 |
| SHA-256 | `860d731f7228c326f3116903e1b14c3bfb4ea65172351f780c8918a243b2d224` |
| 位置 | `~/.cache/amphion-runtime/delivery-staging/asr/harmony/0.3.26/927bda6e/packages/complete/` |
| Release 子包 | `amphion-harmony-asr-sdk-v0.3.26-20261029.zip`，390,439,622 字节，`14c7901aeb245c6e04072b1cd573db945d5b6bad7682208d8443bcf6498b4a58` |
| Diagnostics 子包 | `Amphion-ASR-Diagnostics-SDK.zip`，773,898,586 字节，`618e20a645adda58e74fbc47781eded6898bf441478226393ff9955d97b6858a` |
| 设备 | HUAWEI VYG-AL30，HarmonyOS 7.0.0.109，arm64-v8a |

交付分支头部此后多出的是「记录本轮验收证据」的提交与一处 Android 构建修复，都不改鸿蒙产品
代码、也不改随包文档，因此本轮四个产物仍可直接交付。该 Android 修复是把
`community_diarization.cpp` 与三个头文件挪进 `asr/android/sdk-dingqiao/src/main/cpp/`：
Sortformer 那个提交把它们从鸿蒙模块删掉了，而 Android 的角色分离 JNI 目标一直按相对路径
编译鸿蒙那棵树里的这份源码，删除后 Android CI 的 CMake 配置失败。Android 仍是 Community
链路，所以源码落到仍在用它的那个模块里。

## 本版改动（相对 0.3.25 `a63e5834`）

| 改动 | 落点 | 说明 |
|---|---|---|
| 角色分离换为 Sortformer-66M-4spk 流式模型（CPU，ORT 1.16.3），Community-1 链路整体移除、不留后备 | `sortformer_diarization.cpp`、`SortformerLocalClient.ets`、`SpeakerDiarizationSession.ets` | 9.92 s 块提交 + 可选块内预览（`diarizationPreviewMs` 默认 5000） |
| 相邻同人句子合并为一项，新增 `DiarizedUtterance.sourceUtteranceIds` | `SpeakerDiarizationTranscriptState.ts`、`DingqiaoModels.ets` | `speakerIndex=-1` 不参与；`speakerTurns` 不变 |
| 热词不再吞掉后续文字：半匹配前缀 1 s 过期 + 首字加分封顶 1.0 | sherpa 补丁 `0036` / `0037`（两端共用） | 公开接口与热词入参格式不变；预置池 1.0 与单字热词行为不变 |
| 机主离场：定不出换人点时退保守前缀而非放行混合句；未经流式确认的句子需过实测下沿 0.45 | `Runtime.ets`、`SpeakerTurnFinalizer.ts` | 回调契约不变，被判非机主仍为空 final + `SPEAKER_VAD_REJECTED` |
| 模型资产清单与构建身份绑定 7 个 Sortformer 资产 | `sortformer_diarization_v1.json`、`harmony_build_identity.py` | MindIR 门禁移除 |

## 通过项

| 项 | 结果 |
|---|---|
| 组包前真机 `customer-ptt` | PASS，12/12 轮，空 final 率 0.000，原生流泄漏 0，内存 PASS（增长 19.36 MiB、峰值 418.1 MiB），CPU 均值 118.8% 单核等效 |
| 组包前真机 `diarization-windows`（丁桥 4 条 ≥ 120 s） | PASS，4/4 轮，角色生命周期 PASS，结束到最终结果 1137~2280 ms |
| 角色分离精度（openbench-der-v1，同机同音频） | 丁桥 4 条 DER **12.10%**（0.3.25 Community 23.10%）；逐条 3.01 / 13.50 / 26.24（退化，原 10.34）/ 6.44% |
| 热词 7 例真机夹具 | 客户原样 53 词、不含该热词录音、单字热词、两字前缀全部正常；构造的七字前缀探针从「11 位数字全丢」改善到「仅丢前 5 位」。主机 500 条回归：CER 1.021% → 1.075%，热词召回 97.25% → 97.09% |
| 机主换人 `speaker-vad-turn` 6 例归属断言 | **PASS，6/6**（修复前 2/6 泄露非机主首句）；单轮判定仍 FAIL，见下 |
| 最终 ZIP 复测（装包内 HAP） | PASS，12/12 轮，空 final 率 0.000，内存 PASS（增长 16.39 MiB、峰值 412.1 MiB），`versionName 0.3.26` / `versionCode 326` |
| 最终 ZIP 校验和 | PASS，`docs/checksums.txt` 全部 50 项一致；包内 identity 与 Diagnostics 子包逐字段一致 |
| 披露检查 | 包内无评测探针、评测脚本、评测语料与内部路径；Release 子包脱敏门禁 PASS（16 文件 / 1 HAR） |
| API 23 编译兼容 | PASS，52 个文件 |
| 包内 `demo-source/` 独立构建 | PASS，34 个构建任务全通过、未改任何一行源码；产出签名 HAP `60af50c5` |
| 独立构建产物装机复测 | PASS，热词 7 例与包内 Diagnostics Demo 逐字相同；`customer-ptt` 12/12，增长 7.29 MiB、峰值 401.6 MiB |
| 主机门禁 | 仓库布局 / 可观测性 / 版本一致性 PASS；交付 270 个测试 PASS；`asr/tools/tests` 634 个测试中 2 失败 1 错误，均为既有问题（见下） |

## 代价与未覆盖

- **`speaker-vad-turn` 收尾时延**：6 例中 4 例靠收尾补救才检出换人，其中 3 例为 1652~1732 ms，
  超出载体自设的 1200 ms 预算。构成：换人分割推理约 160 ms + 机主前缀重解码约 790 ms +
  前缀 final 补尾刷新约 400 ms + 打分派发约 300 ms。该时延在本次修复前后基本不变
  （修前 1637~1813 ms），不是修复引入，且在随包声明的「结束到最终角色结果 1.1~2.4 s」之内；
  说话过程中临时结果持续刷新。处置待定：按实测放宽预算，或把前缀投机预解码提前。
- **0.45 下沿的注册同源偏乐观**：阈值依据的注册音与测试音同一会话，机主一侧偏高。跨会话注册下
  机主短句是否会被误拒，须用客户真实声纹复测后才能认为该下沿在生产上成立。
- **热词召回代价**：619 个热词实例少命中 1 个（`弗里曼`）。补丁 0037 的首字封顶在真机上只证明了
  「无回退」，未能正面验证 —— 产品层把 `sysGeneralLexicon` 固定为 3.0，该录音在 3.0 不翻转。
- **算力上升**：识别与角色分离并行时，角色分离推理墙钟 RTF 0.256~0.271（0.3.25 为 0.07~0.09），
  整进程 CPU 均值 1.84 核，p95 2.76 核，峰值 RSS 825 MB（0.3.25 为 581 MB）。已写入随包文档。
- **相邻同人合并的真机佐证**沿用 `2d49bec5` 轮次的观测（131 条 utterance 中 9 条为合并项）。
  该链路此后未改动，本轮未重新采集 utterance 明细。
- **AliMeeting** 20 窗 12.74% 为探针实测，产品链路未重跑。
- **2 小时长会**（`2d49bec5` 轮次用包内 Demo 复测）：7381 s 单会话 PASS，RSS 峰值 911 MB、
  HWM 926 MB、斜率 1.13 MB/min（0.3.24：1160 / 1222 MB、约 2.0 MB/min），线程稳定；
  电池 26.0 → 37.0 °C（0.081 °C/min）。ArkTS 堆单调上升未归因。
  见 `docs/speaker/SORTFORMER_2H_SESSION_20261029.md`。
- **功耗**：USB 供电下电流读数不可用，以 CPU 时间为代理。
- `demo-source` 仍随附历史遗留的内部压测与探针工具：`MindirProbe.ets`（公开桩，仅抛「仅诊断 SDK
  可用」）、`HotwordDeviceEval.ets`、`DeviceStressTest.ets`、`LifecycleBench.ets`、
  `ModelLoadBench.ets`、`PowerSampler.ets`。与 0.3.25 及 20261027 四川包同样随附，均为 Demo 侧
  脚手架、不含评测语料与内部路径，建议 0.3.27 清理。
- **三项既有主机测试失败**（与本版无关）：`test_police_enhancement_demo_toggle` 断言的单行
  `amphion_police` 导入已被 main 自身的提交 `9334ebdc` 改为两符号导入而未同步，在 main 上同样失败；
  `test_sherpa_source_isolation` 的幂等用例在本检出上加不加新补丁都失败；`test_speaker_vad_dataset`
  在本解释器下无法导入 `sherpa_onnx`。
- **安卓端**：热词两个补丁两端共用，但安卓的换人切分与收尾短窗补判在
  `fix/android-speaker-turn-split` 分支，等安卓真机验证；安卓角色分离仍为 Community 链路。

## 外置交付材料

| 文件 | 说明 |
|---|---|
| `FINAL-ZIP-ACCEPTANCE.md` | 绑定完整 ZIP 的 SHA-256；按设计记载测试机型号与序列号（随包摘要中这两项被脱敏门禁拒绝） |
| `交付邮件-0.3.26-20261030.md` | 中文交付邮件草稿，未发送 |

两份都在 `delivery/harmony-dingqiao/evidence/acceptance/20261029-927bda6e-0.3.26/`，均不随包。

## 取代关系

本轮取代同版本三轮未交付的构建：`719f34ee`（变更日志含测试机型号，被脱敏门禁拒绝）、
`2a9f9cf3`（组包完成后追加了相邻同人合并改动）、`2d49bec5`（组包完成后追加了热词与机主识别
两组修复）。四轮的 `customer-ptt` / `diarization-windows` 结论一致（PASS，DER 12.10%）。
