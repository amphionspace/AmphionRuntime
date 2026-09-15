# 会议角色身份稳定性专项：已复现，尚未修复

## 结论

**身份稳定性 FAIL；SDK 生命周期 PASS。** 在已连接的鸿蒙真机上，使用 COS 中一场真实会议的前 180 秒、原始第 0 通道实时输入：4 位参考说话人中，2 位被分配多个已命名编号，排除标注边界前后 250 ms 和真实重叠区后仍发生 3 次变号。整段最终 speaker turns 中，UNKNOWN 占 96.97 秒。

这不是仅有 UI 显示不一致：SDK 公共 `onSpeakerDiarizationResult` 已输出错误身份。宿主机使用同一 PCM、模型和当前生产会话代码保存内部状态，其主说话人时间线与 USB 结果在 18,000 个 10 ms 帧上完全一致。

分支：`test/meeting-speaker-stability`，基线 `e65395cfbcf24a699026cc8bffd16c415e19ef09`。本次只增加评估统计、相关测试和问题证据，未修改 SDK 算法，也未推送或合入。

## 输入与构建身份

| 项目 | 固定值 |
| --- | --- |
| 音频 | COS `cuhk-anfeiweng-1373259071/fengtingyan/dingqiao/20200623_S_R001S01C01.flac` |
| 原文件 SHA-256 | `7bd547327820c60b156afa3c483e81860925f69ca8f29e42df35cd29255eb073` |
| 片段 | 原文件 0–180 秒，8 通道中的第 0 通道，16 kHz PCM16；不重采样、不拼接 |
| 输入 WAV SHA-256 | `657727254cf6015a8b9cd2c87568677dedd6d2836cec56ddd50337014f6c95c2` |
| 身份标注 | [AISHELL 发布的对应 RTTM](https://huggingface.co/datasets/AISHELL/AISHELL-4/blob/main/train_S/TextGrid/20200623_S_R001S01C01.rttm)，并保存对应 TextGrid；4 人 |
| RTTM SHA-256 | `4abf1920a2580982cba117112677e882c0cecff74c72226096d563f0b7956ef7` |
| 设备 | PSN-AL00，OpenHarmony-6.0.2.130 |
| SDK / 测试载体 | SDK `0.3.13`；USB carrier `0.3.14` / versionCode `314` |
| 调用参数 | `diarization-windows`，1 session，20 ms 实时喂入，`maxSpeakers=4`，`recognizerMode=long`，`vadEnd=1500`，`maxAudioDuration=28800000`，未配置 `vadBegin` |
| 实际 HAP 构建提交 | `67e33c8cff3338e8d09a48a9d4c804e9d5899ae2` |
| HAP SHA-256 | `79fc6bbd0df21a8851a1645814022e3b6c0506de325acc0d184ac3919c81b3b6` |

先查 OBS 项目语料、可用数据目录及清单，未找到所需会议录音，再按用户指示查 COS；本条录音来自 COS，标注来自公开数据源。

复用现有 diagnostics HAP 前，逐字段比较构建身份：当前源码指纹、模型、native 库、HAP 和四个 HAR 哈希均相同，唯一差异是 Git 提交号。随后明确重新安装该 HAP，并以 `--installed-package` 测试、保留构建等价证明。**没有把旧 HAP 伪记为在当前提交重新构建。** 本次不是最终发布门禁。

## 公共结果中的变号证据

以下时间为排除标注边界和真实重叠之后，第一个符合评估条件的 10 ms 帧中心；不是回调墙钟时间。

| 参考说话人 | 上一次身份证据时间 | 首次不同身份时间 | SDK 编号变化 |
| --- | ---: | ---: | --- |
| `006-M` | 102.325 s | 103.685 s | `0 → 3` |
| `001-M` | 110.995 s | 111.005 s | `3 → 1` |
| `006-M` | 104.365 s | 128.935 s | `3 → 1` |

其中 `001-M` 的标注连续发言为 104.6174–116.4551 秒，SDK 在 **111.000 秒**直接切换编号，构成同一人一句发言内部变号的明确证据。

各参考人在单人、远离边界区域内的归属秒数如下。UNKNOWN 和漏检分别统计，不能用 UNKNOWN 没有变号来判定身份稳定。

| 参考人 | 有效 SDK 编号及秒数 | UNKNOWN | 漏检 |
| --- | --- | ---: | ---: |
| `001-M` | `3`: 4.53；`1`: 20.11 | 8.80 | 0 |
| `003-M` | 无 | 17.01 | 0.60 |
| `004-M` | `2`: 6.36 | 14.73 | 0 |
| `006-M` | `0`: 9.84；`3`: 0.69；`1`: 3.34 | 40.47 | 0.20 |

250 ms 边界宽限、排除真实重叠后的 DER 为 **71.34%**；这是说话人分离错误率，包含无身份覆盖、身份混淆等，不是 ASR 字错率。UNKNOWN 的 96.97 秒使用完整输出语音段口径，不能与上表不同评估范围的 UNKNOWN 秒数直接相加比较。

## 白盒定位

保存 73 个推理窗口的 segmentation mask、实际声纹取样范围、embedding 和生产会话状态后，只重放缓存状态，不再回放真机音频。

1. `w00000045`（窗口结束 112.5 秒）的本地通道 `1`，segmentation 将 102.5309375–108.4878125 秒连续判为同一通道。参考标注表明其中包含 `006-M`、`001-M` 的轮流发言及短暂重叠。这是该变号证据中最早可见的身份混合状态。
2. `collectSingleSpeakerSamples` 信任该 mask，并只取前 2.5 秒：**102.5309375–105.0309375 秒**。这份声纹输入含两人的语音，不能代表纯粹的 `001-M`。
3. 首个 0–127.2 秒公开窗口形成 **34 个内部簇**。混合簇与此前三个已注册簇的相似度分别为 `0.218470 / 0.593657 / 0.055800`，均低于 `0.72`，因此获得第四个身份，公开编号为 `3`。
4. `w00000046`（窗口结束 115 秒）取样后移为 **105.0309375–107.5309375 秒**，为 `001-M` 单人语音，归入公开编号 `1` 的簇。两个窗口的稳定输出边界恰好在 111 秒相接，直接解释公共结果的 `3 → 1`。
5. 后一公开窗口内部仍形成 **18 个簇**。公开 `speakerCount=4` 不能证明内部恰好分出了正确的四个人。

上述宿主机状态是 **non-canonical 诊断证据**；真机公共结果才是行为验收证据。已定位“分割混入身份 → 短前缀声纹输入混合 → 独立簇 → 输出变号”的具体链路，但没有验证参数或算法修复，也未证明这一个链路解释全部 UNKNOWN 和所有变号。

Harmony 与 Android 当前实现都有 2.5 秒取样上限及 `0.72` 阈值。已有本地候选分支 `fix/diarization-speaker-consistency` 包含取样扩展和阈值校准，但不在当前 main，本次没有套用其修复，也不能将其旧样本结果视为本会议通过。

## 生命周期、附属问题与范围

| 检查 | 结果 |
| --- | --- |
| start / final / last / complete / error | `1 / 14 / 1 / 1 / 0` |
| finish 前 last | `0` |
| 终态顺序 | 唯一 last → 终结 diarization result → 唯一 complete |
| 分人输出窗口 | 0–127.2 秒、127.2–180 秒；后一窗口为 session final |
| native stream 回收 | `0`，PASS |
| 声纹分离推理累计 | 40.233 秒，RTF 0.2235 |
| finish 到 complete | 1.613 秒 |
| 本轮资源检查 | PASS；RSS 增量 27.809 MiB，峰值 686.434 MiB；首尾线程数均为 68 |

附属问题：大量语音无可用身份，`003-M` 的单人内部区域完全未获得编号；这是业务可用性失败，不能被生命周期 PASS 掩盖。`degraded=false` 表示本轮未走运行时降级路径，**不能作为身份精度合格的判断**；本次不改变该标记语义。

仅完成一条真实会议的 3 分钟、一次实时 USB 测试，以及一次内部推理对照。没有覆盖 Android 真机、长时间身份漂移、多个会议或麦克风通道、客户原始录音/版本、断网网络观测及完整发布矩阵。短期资源 PASS 不证明长期无泄漏。

## 保存与复核

- [综合评估及哈希](evidence/meeting-speaker-stability-20260915/assessment.json)：本专项综合结论 FAIL；原 `report.json` 的 PASS 仅是原测试载体的生命周期/资源门禁。
- [白盒摘要](evidence/meeting-speaker-stability-20260915/whitebox-summary.json)：窗口取样、簇相似度、宿主机与真机对齐范围。
- 原始证据目录：`~/.cache/amphion-runtime/diagnostics/meeting-speaker-stability-20260915/`。
- 真机原报告：`usb/20260915-114437-diarization-windows-6ad41fbb/report.json`，SHA-256 `ccac2ffc3e001448ac314f20eb7fc993ef9550855b8768ffdb72c19c8b906d7b`。同目录保存 `result.txt`、`memory.csv`、`hilog.txt`、`payload/corpus.json` 和输入 PCM；根目录保存 `evidence-manifest.json`。
- 原始录音、文本、embedding 和密钥均不加入 Git。失败现场不覆盖。
- 评估器新增逐参考人的原始 SDK 编号分布和变号时间；两个针对性测试通过，分别验证“同一人返回后变号”以及“任意稳定编号、UNKNOWN、重叠不误报”。没有 SDK 二进制修改，因此不追加构建或无关门禁。

复核现有结果：

```bash
python3 delivery/harmony-dingqiao/delivery/evaluate_speaker_diarization_report.py \
  --report "$HOME/.cache/amphion-runtime/diagnostics/meeting-speaker-stability-20260915/usb/20260915-114437-diarization-windows-6ad41fbb/report.json" \
  --reference-rttm "$HOME/.cache/amphion-runtime/diagnostics/meeting-speaker-stability-20260915/20200623_S_R001S01C01.rttm" \
  --duration-seconds 180

python3 -m unittest \
  delivery.harmony-dingqiao.delivery.test_evaluate_speaker_diarization_report -v
```
