# ASR 验证与发布门禁

路径均相对仓库根目录；本文件由根 AGENTS.md 按任务引用，所列约束仍须遵守。

仅 SDK 运行行为修改执行相关问题验证；正式发布执行完整矩阵。纯文档、归档和不影响二进制的组包修改使用对应小型检查，不重新跑真机。复用身份一致的已有证据。

## 必须保留的测试门禁

- Harmony HAR 必须用 OpenHarmony 6.1 / API 23 的 `es2abc` 检查实际交付内容，不能只用当前 CLT 编译仓库。客户在 0.3.18 遇到的 `CommunitySpeakerIdentity.ts:102:39 Type expected` 源于 `< unique.length` 的旧编译器解析问题；Node 单测和 API 26 编译均不能发现它。`verify_harmony_api23_compiler.py` 必须先复现旧语法失败及改名后通过，再逐一编译 HAR 内全部非声明 `.ts`，记录编译器、HAR、源文件 SHA-256 和失败信息。缺少编译器、使用无法复现原问题的新编译器、无实现文件或任一文件失败均阻断组包，不得记为 skip/PASS。此检查不等于客户 Windows DevEco 完整工程验收。
- 状态机单测：纯静音达到 `vadBegin` 只超时一次；边界帧中语音优先；ASR text/token 永久解除计时；低噪声、短脉冲和被静音隔开的变幅脉冲不误判；稳态高能非语音最多获得一次确认窗并最终超时；语音型变化信号不受调用方分帧影响；旧活动只能触发 probe，不能直接永久解除计时。同一 PCM 以单个大块或多个小块写入必须得到相同决定，deadline 之后的样本不得回看并改变 deadline 处的结果。
- 标准真机 session：记录调用 `finish` 前的 `isLast` 数量，要求为 0；结束后要求总数为 1。
- `max-duration`：达到上限后恰好一次 last/complete，迟到音频帧不产生额外回调，随后可以启动新 session。
- `cancel`、`start-cancel`、`start-write`、重复 `finish`、回调内重入、非法 session/frame 和 `NaN` 参数必须分别验证，不得合并成单一“edge passed”。`start-write` 必须在 `onStart` 调用栈内同步写入多帧真实 PCM 缓存，不能延迟到回调返回后；还要分别覆盖继续识别和回调内立即 `finish`。
- `vad-begin`：使用真实语音和纯静音分别测试。真实语音不得自动结束；纯静音必须按配置结束。
- 声纹与 `vadBegin` 必须组合测试 1000 ms 入参、实时/突发喂入、直接起音/前置静音；前置静音与源文件自身静音之和必须小于 1000 ms，否则自动结束是正确结果。显式 `finish` 前不得有 `isLast`，足够长的有效语音必须出现带分数的 final。另用纯静音/稳态高能非语音验证有界自动结束。参数上层改大只能作为规避，不能替代此门禁。
- `voiceprint-fallback` 必须使用能在旧版本稳定产生“非空 endpoint final 但分数缺失”的双文件语料，分别覆盖 cold/warm extractor；第一条非空 final 必须带分数，显式 `finish` 前不得有 `isLast`。该模式不得配置短 `maxAudioDuration`，避免把声纹样本选择与自动结束混成一个断言。
- Harmony finish 兼容性发布必须运行 `delivery/harmony-dingqiao/delivery/run_finish_compat_release_gate.py`。
  `callback-api-reentrant` 的 `SPEECH_END -> finish` 必须返回带非空文本的唯一 last；
  `finish-shutdown` 必须在同一 commit、设备和 HAP/HAR 上返回唯一 last 后唯一 complete。
  根汇总 `report.json` 和两个子模式完整 artifact 必须保留。
- Runtime 释放竞态修复必须用 `finish-shutdown-relicense` 重放完整调用序列：整段 PCM 入队后
  `finish -> shutdown -> setLicense -> prepareRuntime`。要求 `finish` 前 `isLast=0`，之后恰好一次
  last/complete、无 error、native stream 归零，并验证 Runtime 重建后的下一 session 可恢复。
- 长稳压：按采样率、时长和音量分层抽样，不只取随机文件；报告 callback 契约、空 final、native stream、RSS 和线程变化。
- 测试报告必须保留 `report.json`、逐轮结果、内存采样、hilog 和输入映射。失败 artifact 不得被后续运行覆盖。
- 发布矩阵完成后必须用 `archive_release_gate_evidence.py` 生成新的、不可覆盖的脱敏证据目录；
  保留 canonical PASS 和非 canonical 失败现场，不提交原始 PCM。发布账本必须通过
  `attach-evidence` 记录根 `report.json` 路径与 SHA-256，并用 `verify-evidence` 校验。
- SDK-only 打包不得把“Git 输入看起来干净”等同于“已构建 HAR 来自当前源码”。打包前必须验证
  `harmony_build_identity.py`；中英裁剪仍要绑定 `amphion_asr`、`amphion_police`、
  `amphion_dingqiao` 和 `sherpa_onnx` 四个 HAR，provenance 必须记录 source fingerprint 和
  component HAR 哈希。

## SDK 真实调用方验收

- 产品验收对象是 SDK 公共 API 和回调契约；demo/HAP 只是 USB 真机上的测试载体。UI 不崩溃、按钮可点击或识别文本正确，都不能替代 SDK 生命周期断言。
- 真实用户操作必须翻译成调用方时序：快速开始/取消/重启、`onStart` 内冲刷录音缓存、`finish` 后立即尝试下一 session、回调内重入、旧 session 迟到 `writeAudio/finish/cancel`、重复结束、运行中 shutdown 和失败后的下一轮恢复。
- 成功回调必须写成可观察的状态后置条件，并建立“回调 x 公共 API”重入矩阵。不得用一个带特殊补偿分支的 API（例如启动期 `cancel`）证明其他 API 也可用；首次使用还必须组合冷加载期间缓存、回调内同步回放和继续/立即结束两条路径。具体教训见 `delivery/harmony-dingqiao/docs/ONSTART_SESSION_PUBLICATION_POSTMORTEM.md`。
- 每条压力用例必须按 `sessionId` 保存有序回调轨迹，分别统计 start、final、`isLast`、complete 和 error。聚合总数相等不能证明没有串 session。
- cancel 生效后不得再新增 final/complete；取消前已经正常产生的非 last endpoint final 必须保留并计入快照，但取消前不得已有 `isLast` 或 complete。正常 session 必须只有一次 `isLast`，随后一次 complete；旧 session 的迟到调用不得终止或污染当前 session。
- 现实操作压力与精度评测分开。生命周期用例只检查状态、归属、顺序、错误码、资源回收和可恢复性，不用文本正确率决定 PASS；声纹只检查“应有分数/应省略分数”的接口契约，不比较相似度精度。
- `user-sequence`、`reentrant`、`start-cancel`、`start-write`、`start-write-reload`、`edge` 和实时 `paced` 是发布前必跑门禁。`start-write-reload` 必须在每轮结束后执行 `shutdown -> unloadModel -> createEngine`，验证首次冷加载和业务空闲卸载后的重新冷加载具有相同的 `onStart` 可用性。至少一组运行超过 60 秒，以区分模型逐步驻留与持续内存泄漏。
- 不得声称“覆盖所有边界”。报告必须列出已覆盖的调用序列、轮数、设备/系统版本、未覆盖的外部故障，以及任何仅为 `INCONCLUSIVE` 的资源指标。

## 推荐验证命令

从仓库根目录执行；以下是按需选用的命令，不是要求每个任务顺次全跑。

```bash
python3 -m unittest \
  asr.tools.tests.test_harmony_initial_silence_tracker \
  asr.tools.tests.test_harmony_rejected_final_lifecycle \
  delivery.harmony-dingqiao.delivery.test_run_device_stress -v

python3 delivery/harmony-dingqiao/delivery/run_finish_compat_release_gate.py \
  --data-dir "$HOME/.cache/amphion-runtime/test-data/v1/aishell3_test_hotwords_500"

(cd asr/android && ./gradlew --no-daemon :sdk:testDebugUnitTest :sdk-dingqiao:testDebugUnitTest --console=plain)
(cd asr/android && ./gradlew --no-daemon :sdk:testReleaseUnitTest :sdk-dingqiao:testReleaseUnitTest --rerun-tasks --console=plain)

python3 delivery/harmony-dingqiao/delivery/run_device_stress.py \
  --data-dir "$HOME/.cache/amphion-runtime/test-data/v1/aishell3_test_hotwords_500" \
  --mode vad-begin --cycles 100 --files 0

python3 delivery/harmony-dingqiao/delivery/run_device_stress.py \
  --data-dir "$HOME/.cache/amphion-runtime/test-data/v1/aishell3_test_hotwords_500" \
  --mode voiceprint-vad-begin --cycles 100 --files 0

python3 delivery/harmony-dingqiao/delivery/run_device_stress.py \
  --data-dir "$HOME/.cache/amphion-runtime/test-data/v1/aishell3_test_hotwords_500" \
  --mode user-sequence --cycles 300 --files 3
```

完整发布或约定完整回归的运行逻辑合入使用以下矩阵，次数和语料数量可按耗时调整；问题定位只运行相关子集。完整矩阵至少覆盖 `burst`、`paced`、`vad-begin`、`vad-begin-silence`、`voiceprint`、`voiceprint-fallback`、`voiceprint-vad-begin`、`voiceprint-vad-begin-idle`、`cancel`、`cancel-full`、`max-duration`、`edge`、`reentrant`、`start-cancel`、`start-write`、`start-write-reload`、`user-sequence` 和 `numeric-edge`。任何模式失败都应先解释并修复，不能通过放宽全局空结果率掩盖生命周期错误。
