# 角色分离端到端推进记录（2026-09-28）

**发布结论：BLOCKED。** 下文保留逐提交证据，不能将早期数值当作最新产物验收。`ad16789a` 已验证客户不同主讲人不再被 KMeans 误合并；`f6aef3d4` 修复销毁后空闲 arena 保留，短录音资源门禁转绿，连续短会话和124秒锚点共137窗公开状态不变。最新运行提交 `196caeec` 另含短 clean run 的 mask 归属修复：固定公开片真机strict DER为33.6679%，171窗在修复前后同张量分叉中的公开结果、临时更新、身份及调用方展示不变。但客户开场短段仍为 UNKNOWN，公开集仍有既有误认和少数说话人低召回，长期内存及本次公开片严格实时趋势仍 INCONCLUSIVE。最新提交没有完整四锚点、16段及最终展示验收；未合入最终 PR，也没有生成正式发布 ZIP。最新记录见[短 mask 归属及公开片验证](DIARIZATION_SHORT_MASK_OWNERSHIP_20260928.md)，前序记录见 [arena 回收](DIARIZATION_ARENA_RELEASE_20260928.md)、[容量修复](DIARIZATION_CAPACITY_FIX_20260928.md)和[短段恢复差分](DIARIZATION_SHORT_RUN_AND_CAPACITY_20260928.md)。

## 代码变化

短 mask 修复只阻止一个短 clean run 借用同时池化 overlap 的整窗 embedding 建档，保留纯净1帧/2帧证据。55项相关测试通过；Android共用native重编译通过，48项未变化的JVM测试复用有效缓存。四实录及一个公开片的既有host回放结果不变；新真机公开片又以自己的171窗张量完成前后分叉。最初与主机向量逐位比较的分析红灯已保留并纠正来源，未降低精度门槛；旧新真机共有的86个绝对PCM窗口全部逐位一致。它不构成DER改善或当前客户短段UNKNOWN已解决的证据。

资源修复见[空闲 arena 销毁回收](DIARIZATION_ARENA_RELEASE_20260928.md)：最早错误状态是模型销毁后 live=0、reserved=255 MiB。仅在没有活跃分配时回收后 reserved=1 MiB；正式候选已去除临时日志。两次连续短会话、124秒锚点、cancel-full及Runtime释放后恢复均通过对应SDK门禁，长时内存结论仍未通过。[首窗 Run 后释放实验](DIARIZATION_MEMORY_OWNERSHIP_20260928.md)保留为已否决的历史分叉，不作为当前生产候选。

从 `origin/main=f5bd3867e9548f7630c4e436cb308d7cd63c2040` 开始。运行代码提交 `f850a7cc6ca6f64612a9f10bb5b99173fc4e4446` 只补齐诊断快照中的独立 `runEmbeddings`，并测试快照不被后续复用的数组改写。没有调整窗口、hop、timeout、模型、建组规则、UNKNOWN 或生命周期。此前快照只有整窗 embedding 与 run 范围，不能精确重放当前 run 聚类，不能拿整窗向量替代。

新增开发工具分别负责不可覆盖的输入 manifest、配对评分及回退否决、分层真机运行、完整窗口快照重放、外部 RTTM 的 embedding 覆盖审计和 Qwen 音频辅助标注。它们不进入 SDK 推理链路。事件存在只证明该阶段被观测，不能自动将分割、embedding 或最终展示判为 PASS。

## 同产物实测

Mate80 `7GK0226326015655`，系统 `OpenHarmony-6.1.1.120`；ZH_EN diagnostics HAP，source fingerprint `c3f09b1fdb7390202afade0bde344437195f93deb976d72f410d6ba83c388cfd`。HAP 和四个 HAR 的完整 SHA-256、输入、report、corpus、完整事件和主机实验索引见 [证据索引](evidence/DIARIZATION_E2E_DIAGNOSTIC_PROGRESS_F850A7CC.json)。这不是 Debug/Release 最终发布的同提交证据包。

| 输入 | SDK 调用契约 | 角色与精度 | 实时与内存 | 决策 |
| --- | --- | --- | --- | --- |
| AISHELL-4 四人切片 180 s | PASS；唯一 last/complete，stream 归零 | 输出 2 人，strict DER 42.7774%；002-F、003-F recall=0，与历史同片评分一致 | 队列样本覆盖超过 60 s，无持续音频延迟增长；RSS 后段仍高于前段，长期结论 INCONCLUSIVE | 保留身份失败，进入同张量定位 |
| 实录四人 123.8 s | PASS；finish 到 complete 1050 ms | 输出 4 人；尚缺人工裁定与调用方最终呈现，不能据人数判精度 PASS | diarization RTF 0.5491；队列检查 PASS；RSS 三段中位数上升，INCONCLUSIVE | 不据接口 PASS 放行 |
| 实录四人 19.58 s（paced） | session PASS；唯一 last/complete，stream 归零 | 输出 4 人；身份和可读性待裁定 | RTF 0.3736；27.5 s 观察窗 RSS 增加 117.471 MiB，现有资源门禁 FAIL | 自动停止余下锚点，未扩展完整集 |

短录音 RSS 在首个 10 s 推理窗口附近由约 442 MiB 跳至 550 MiB，完成后的采样趋稳。124 s 的首次窗口也有类似台阶。它与首次推理驻留相关，但目前没有内部分配证据能区分工作区、模型驻留与泄漏；不能把台阶直接称为持续泄漏，也不能放宽门槛当作已解决。后续最小实验应固定输入，以已加载状态与首次加载状态对照分配归属，并保留冷启动成本，不能把它从发布报告中隐藏。

## 最早偏离定位

当前 AISHELL-4 完整日志共 86 个窗口；有界 `events.ndjson` 只剩后 40 个窗口。复现必须使用 `events.full.ndjson`，脚本会拒绝缺失 prefix、向量、窗口所有权或顺序的输入。

1. 主机直接调用生产 C++ 聚类，`hard`、`frameHard`、`trainingIndices`、`trainingRunIndices`、`ahc` 与真机逐项一致。
2. 最终 commit 的 117 个训练向量先形成 42 个 AHC 组，VBx 最后保留 2 个。两位缺失参考人物均有有限 run embedding，并进入独立 AHC 组。因此“从未进入训练”不是这两人的直接原因。
3. 参考区间覆盖审计中，002-F/003-F 分别只有 5/4 个干净、纯度至少 90% 的有效 run；各自仅一次连续发言，滑窗重复覆盖不能充当独立重现。排除时间重叠样本后，两人的跨次同人 margin 均没有证据，不能宣称 embedding 已通过。
4. 固定同一分割和完整向量，只把训练输入换成现有整窗路径，仍输出 2 人、两位参考人物 recall=0。回退 run 拆分不能解决本片，且不是生产候选。
5. 未修改上游 VBx 使用同一训练向量、AHC、导出 PLDA 和官方 Fa=0.07/Fb=0.8，同样保留 2 组；prior 最大绝对差 `1.11e-16`、objective 最大差 `5.12e-11`，AHC 标签完全一致。**VBx 数值移植错误假设被证伪**。这不是官方完整管线成绩，也没有证明输入特征链路与官方等价。

6. 补跑同一 PCM 的未修改 Community-1 完整离线管线（模型 revision `3533c8cf8e369892e6b79ff1bf80f7b0286a54ee`，不传 oracle 人数，仅上限 4）：输出 4 人，使用当前评分器 strict DER `25.1006%`，两位女性 recall 分别 `0.515451/0.873504`。共享的 86 个窗口共 151,962 个分割值完全相同，258 对整窗 embedding 最低 cosine `0.999999919`。共同窗口上的推理移植没有表现出导致本例塌缩的偏离。
7. **首个已证明影响身份的差异是送入聚类的窗口采样密度。** 官方 10 s 窗口 / 1 s hop 共 171 窗，SDK 为 10 s / 2 s 共 86 窗。将已存官方张量分别按 1 s、2 s 送入同一生产 C++ 整窗聚类（不再推理），训练向量由 215 降为 107，AHC 均 36 组，但 VBx 从 4 个输出塌缩为 2 个；两位少数说话人 recall 从 `0.515451/0.873504` 变为 0。两路均未触发 KMeans。这个单变量分叉证明“采样步长只是性能参数、不改变身份”在该输入上不成立。

两路主机全历史重建 DER 分别 `24.3169%/39.2506%`，不同于上游完整管线 `25.1006%` 和 SDK 冻结输出 `42.7774%`：它们的 reconstruction、run 训练和提交冻结并不相同，不能把这些差值都归给 hop。下一候选必须先决定如何对齐输入协议，再在实录金丝雀中验证；不直接把生产 hop 改为 1 s 并宣称完成。它接近翻倍的编码工作量可能令现有 RTF 余量不足，需独立测量并保留状态所有权；此时才按证据决定是否进入增量推理迁移。不能用复制样本、强制四组或未经校准的 Fa/Fb 补偿隐藏这个分布变化。

整窗/run 分叉指标只用于主机全历史诊断，不替代 SDK 冻结提交指标。一次误用 suffix 重建对全片 reference 评分的结果已明确作废；旧短录音单组诊断、错误模式运行和截断日志分析都在证据索引中标记 non-canonical，不算当前回归证据。

## 协议和测试数据索引

固定六段历史结果用同一评分器重算，加权 strict DER 为 `0.2940783172807604`；历史设备报告缺少当前完整 build binding，只作为趋势基线。官方完整数据数字不能与该子集直接相减。缓存三场 AISHELL-4 完整会议分别有 5、6、6 位 reference speaker，超过 SDK 当前最多 4 人；必须单列能力范围差异。公开集采用相对回归，不新增官方数值硬门槛。

[输入索引](../../delivery/harmony-dingqiao/delivery/diarization_evaluation_inputs.json) 固定 24 条输入：6 条公开、16 条实录（其中 3 个锚点）、客户主讲人锚点和 600 s AMI。每条保留 WAV SHA、归一化、原文件偏移和标注性质；冻结后的 manifest 另含 PCM、RTTM、评分器哈希和评分协议。客户会议只验收四位主要发言人，背景不占名额。MOSS 与 Qwen 均为辅助标注，不能代替人工身份真值。

数据复用 [原对象存储报告](DIARIZATION_PUBLIC_DATASET_REPORT_20260927.md) 的私有归档，未重新下载大文件。16 段音频按归档 manifest 哈希取出到索引指定的 `diagnostics/e2e-delivery-20260927/recordings/audio/`；客户原音按哈希复制到 `customer-meeting.wav`。公开 WAV/RTTM 复用 `benchmark/aishell4-current` 与 `benchmark/alimeeting-test/selected-clips`。原始录音和含文本的诊断不提交 Git。

## 复现入口和放行边界

从仓库根目录执行；输出目录必须全新，失败结果不能覆盖：

```bash
python3 delivery/harmony-dingqiao/delivery/diarization_evaluation.py freeze \
  --spec delivery/harmony-dingqiao/delivery/diarization_evaluation_inputs.json \
  --data-root "$HOME/.cache/amphion-runtime" --output /new/run/evaluation-manifest.json
python3 delivery/harmony-dingqiao/delivery/diarization_evaluation.py run \
  --manifest /new/run/evaluation-manifest.json --tier anchor --output /new/run/anchors
python3 delivery/harmony-dingqiao/delivery/diarization_evaluation.py evaluate \
  --manifest /new/run/evaluation-manifest.json --captures /new/run/captures.json \
  --output /new/run/assessment.json
python3 delivery/harmony-dingqiao/delivery/diarization_evaluation.py compare \
  --baseline /baseline/assessment.json --candidate /new/run/assessment.json \
  --output /new/run/comparison.json
```

`captures.json` 结构可参照证据索引指向的本地 `current-captures.json`：根 `binding` 包含完整运行提交、设备、系统、source fingerprint 和五个 artifact 的 path/SHA；各 case 绑定输入 SHA、binding SHA、report、corpus、完整 events，可附 caller 和逐区间 review。review 必须绑定输入、binding 和所有 capture 哈希，并逐门禁保存 status/evidence。缺失、祖先或不同产物证据不得变为 PASS。

`evaluate/compare` 返回 0=PASS、1=FAIL、2=INCONCLUSIVE。`run` 成功采集仍返回 2，采集不等于验收；失败预检不拉取设备旧日志。`recordings` 要求同 manifest、同 HAR/HAP 的四锚点全绿；`long` 还要求完整实录全绿。对比报告区分既有失败、新回归和基线未验证的新观察失败，不把同一个旧红灯称为回归。

Qwen 入口为 `annotate_qwen_audio.py --audio <wav> --output-dir <new-dir> --api-key-env <variable>`，按[官方 HTTP API](https://help.aliyun.com/en/model-studio/fun-asr-flash-recorded-speech-recognition-http-api) 使用模型标识 `qwen-audio-3.1-asr-flash`。请求只含音频和 diarization 开关，逐词保存换人与 UNKNOWN；原始响应、输入 SHA、参数、服务 request ID 和未锁定的模型 alias 均留存，不在日志输出 key。当前 Mac 的 `~/.zshrc`/已加载环境未找到对应变量，amphion-42 也没有该文件；尚未调用服务，等待用户指出变量所在位置。

当前尚未实施增量推理迁移：已测 124/180 s 无持续队列积压，但尚不能证明长会议稳定。先解决当前身份/资源红灯，再按原矩阵扩展；若长时结果证实持续积压或重复编码污染，再按 session/generation 状态所有权、绝对 frame 坐标和 flush 契约设计迁移。

## 本轮验证

45 项相关用例通过（评估门禁、评分器、矩阵/生命周期分析、快照重放/Qwen 解析和 Harmony 公共角色契约）。覆盖输入与 reference 哈希变化、不可覆盖输出、人数塌缩否决、已有失败归因、错误产物 review、缺失前序窗口、同 PCM 重叠向量不算独立证据、逐词换人及 UNKNOWN、失败预检不采旧日志、未通过锚点不扩展长跑等。ZH_EN diagnostics 构建及五个产物 build identity 校验通过；真机范围和红灯如上。未执行最终 Release、Android 全矩阵或完整客户验收，不能将本次测试数量视为整体放行。

后续优化记录：[同窗口 embedding 复用与瓶颈](DIARIZATION_EMBEDDING_REUSE_20260928.md)。运行提交 `83fa0e41` 在三个固定输入上保持窗口张量、原句、临时和冻结结果完全一致，降低重复编码成本；身份塌缩和资源红灯仍阻断整体交付。

后续已完成单窗口共享 encoder 候选 `7b5b7fb0`，三输入 150 个窗口及公开结果逐项等价，124 秒/180 秒 embedding 耗时再降约 44%/51%。当前 run 路径的 1 秒/2 秒采样状态差分与资源未决项见 [共享 encoder 与采样协议差分](DIARIZATION_SHARED_ENCODER_20260928.md)。整体交付仍阻断，不能以性能改善覆盖既有身份红灯。
