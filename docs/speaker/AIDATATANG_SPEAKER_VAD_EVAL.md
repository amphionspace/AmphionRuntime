# Aidatatang 主说话人 VAD 评测

本文沉淀 2026-06-30 使用 `aidatatang_test_spk_balanced_500` 对 Android 主说话人 VAD 状态机做的离线复现实验。实验脚本为 `asr/tools/speaker/06_eval_speaker_vad_aidatatang.py`，机器可读结果在 `asr/tools/speaker/results/aidatatang_speaker_vad_eval/summary.json`，Markdown 结果在 `asr/tools/speaker/results/aidatatang_speaker_vad_eval/summary.md`。

## 1. 要解决的问题

普通 VAD 只知道“有没有人说话”，不知道“是不是目标说话人在说话”。在目标人说完、旁边人立刻接话且中间没有足够静音的场景里，普通 VAD 很容易把两个人的语音合成同一个 utterance，导致下游 ASR final 或 LLM 输入混入非目标人的话。

主说话人 VAD 解决的是这个具体问题：目标人开口后，如果检测到当前 utterance 尾部连续多个声纹窗口低于目标阈值，就主动 endpoint，尽早把目标人的句子收尾，减少目标人离场后的非目标拖尾。

本实验不回答两个问题：

- 不评估 ASR 字错误率或词错误率，因为这里没有跑 ASR 解码。
- 不评估声纹注册泛化能力，因为测试集每个 speaker 只有 1 条 utterance，本实验用同条音频注册目标声纹，target 确认率会偏乐观。

## 2. 数据与实验构造

测试集：`aidatatang_test_spk_balanced_500`，本地路径通过环境变量 `AIDATATANG_SPEAKER_VAD_DIR` 指定。

| 项 | 值 |
| --- | --- |
| 样本数 | 500 |
| 说话人数 | 500 |
| 每个说话人 utterance 数 | 1 |
| 总时长 | 1168.308 秒 |
| 单条时长 p10 / p50 / p90 | 1.440 / 1.944 / 3.762 秒 |
| 音频格式 | 16 kHz mp3，manifest 为 Lhotse 风格 recordings / supervisions |

实验构造：

1. 按 recording id 排序，取第 `i` 条作为 target，第 `i+1` 条作为 other，最后一条接回第一条，组成 500 组 target + other 会话。
2. target 用自身音频提取声纹 embedding 作为注册声纹。
3. 会话音频为 `target_audio + other_audio`，中间不插入静音。这是压力场景，用来模拟目标人刚说完、旁边人马上接话。
4. 无 speaker-VAD 的 baseline 假设普通 VAD 会把两段连续语音合成一个 utterance，因此非目标泄露时长等于 other 段时长。
5. 有 speaker-VAD 时，离线复刻 Android 状态机：先确认目标人，再在连续 `consecutiveBelow=2` 个低分窗口后 endpoint。

运行配置：

| 配置项 | 值 | 含义 |
| --- | --- | --- |
| speaker model | shared/models/asr/dingqiao/eres2net.onnx | Android/HarmonyOS 交付共用的目标声纹 embedding 模型 |
| winSec | 1.0 秒 | 每次取 utterance 尾部 1 秒音频做声纹打分 |
| hopSec | 0.3 秒 | 每 0.3 秒滑动一次打分窗口 |
| consecutiveBelow | 2 | 连续 2 个低于阈值的窗口后触发 endpoint |
| threshold scan | 0.30 / 0.35 / 0.40 / 0.45 / 0.50 | 观察收益和截断风险随阈值变化的取舍 |

## 3. 指标说明

| 指标 | 名词说明 | 解决或暴露的问题 | 计算口径 | 数值解读 |
| --- | --- | --- | --- | --- |
| threshold | 声纹相似度阈值，窗口余弦分数低于该值时视为目标人可能离场 | 控制“更早切断非目标拖尾”和“误切目标人”的取舍 | 对 0.30 到 0.50 做扫描 | 越高越激进，非目标拖尾更少，但目标截断风险更高 |
| target 确认率 | 会话开始后，状态机是否至少一次确认当前 utterance 属于目标人 | 暴露目标人刚开口时是否被错误抑制 | 1 - pre_target_endpoint_rate - target_not_confirmed_rate | 越高越好；本实验因同条注册会偏高 |
| speaker endpoint 率 | speaker-VAD 是否在会话内主动触发 endpoint | 衡量主说话人离场检测是否真正生效 | state == endpoint 的会话数 / 总会话数 | 越高表示越多场景能靠声纹提前收尾 |
| target 截断率 | endpoint 是否早于 target 结束时间超过容忍窗口 | 暴露把目标人自己的话提前截断的风险 | endpoint_sec < target_end_sec - hopSec 的会话数 / 总会话数 | 越低越好，是 speaker-VAD 的主要副作用指标 |
| 非目标泄露时长 | target 结束后，other 仍留在同一个 utterance 里的时长 | 直接对应“目标人离场后旁边人接话被混入 final”的问题 | min(max(endpoint_sec - target_end_sec, 0), other_duration_sec) | 越低越好 |
| 非目标泄露降幅 | 开启 speaker-VAD 后减少了多少非目标泄露 | 衡量该功能相比无 speaker-VAD 的净收益 | 1 - with_speaker_vad_leak / baseline_leak | 越高越好 |
| 平均非目标泄露 无/有 | 无 speaker-VAD 与有 speaker-VAD 的平均非目标泄露秒数 | 用秒级数值解释收益大小，便于估算下游 LLM 被污染的时长 | sum(leak_sec) / n_pairs | 两者差值就是平均每段少混入多少秒非目标语音 |
| endpoint 提前量 p50 / p90 | 相比无 speaker-VAD 等到完整 target + other 结束，提前多少秒收尾 | 衡量下游拿到 final 的时延收益 | target_duration + other_duration - endpoint_sec 的分位数 | 越大表示越早产出目标句 final |
| target 后 endpoint 延迟 p50 / p90 | target 结束后多久触发 speaker endpoint | 衡量目标人离场检测的反应速度 | 对成功 speaker endpoint 且未截断 target 的样本计算 endpoint_sec - target_end_sec | 越低越好，但受 winSec / hopSec / consecutiveBelow 限制 |
| score target p10 / p50 / p90 | 纯 target 窗口的声纹相似度分布 | 判断目标窗口与阈值是否有安全距离 | 对窗口完全落在 target 段内的分数做分位统计 | 应显著高于阈值 |
| score transition p10 / p50 / p90 | 跨 target 与 other 边界窗口的声纹相似度分布 | 暴露边界窗口受混音污染后是否会延迟 endpoint | 对窗口跨越边界的分数做分位统计 | 处于 target 和 other 之间是正常现象 |
| score other p10 / p50 / p90 | 纯 other 窗口的声纹相似度分布 | 判断非目标人是否能被阈值稳定压住 | 对窗口完全落在 other 段内的分数做分位统计 | 应低于阈值，p90 越低越稳 |

## 4. 实测结果

阈值扫描结果如下：

| threshold | target 确认率 | speaker endpoint 率 | target 截断率 | 非目标泄露降幅 | 平均非目标泄露 无/有 | endpoint 提前 p50/p90 | target 后 endpoint 延迟 p50/p90 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0.30 | 99.60% | 85.20% | 0.60% | 52.97% | 2.337s / 1.099s | 0.956s / 3.012s | 0.952s / 1.264s |
| 0.35 | 99.60% | 91.00% | 0.80% | 57.41% | 2.337s / 0.995s | 1.028s / 3.104s | 0.916s / 1.193s |
| 0.40 | 99.00% | 93.20% | 1.00% | 60.74% | 2.337s / 0.917s | 1.100s / 3.105s | 0.880s / 1.132s |
| 0.45 | 99.00% | 94.40% | 1.40% | 63.33% | 2.337s / 0.857s | 1.172s / 3.190s | 0.844s / 1.072s |
| 0.50 | 98.80% | 96.40% | 2.80% | 66.73% | 2.337s / 0.777s | 1.220s / 3.382s | 0.808s / 1.024s |

默认阈值 0.40 的结论：

- 平均非目标泄露从 2.337 秒降到 0.917 秒，减少 1.420 秒，降幅 60.74%。
- 500 组会话中 466 组触发 speaker endpoint，触发率 93.20%。
- target 确认率 99.00%，说明目标开口阶段基本能被确认。
- target 截断率 1.00%，说明存在少量误切目标人的风险。
- endpoint 提前量 p50 为 1.100 秒、p90 为 3.105 秒，说明该能力能让下游更早拿到目标人的 final。
- target 结束后 endpoint 延迟 p50 为 0.880 秒、p90 为 1.132 秒，符合 `winSec=1.0s` 和 `hopSec=0.3s` 下的预期量级。

最终收益数据表格如下，工作点采用默认阈值 0.40：

| 场景问题 | 指标 | 无 speaker-VAD | speaker-VAD 0.40 | 收益或代价 | 结论 |
| --- | --- | --- | --- | --- | --- |
| 目标人说完后旁边人马上接话，被混入同一个 utterance | 平均非目标泄露时长 | 2.337s | 0.917s | 减少 1.420s，降幅 60.74% | 核心收益成立 |
| 500 组连续会话里，非目标语音累计污染 final 或下游输入 | 非目标泄露总时长 | 1168.308s | 458.660s | 减少 709.648s，约 11.83 分钟 | 大幅减少非目标拖尾 |
| 下游必须等 target + other 全部结束才拿到 final | endpoint 提前量 p50 / p90 | 0.000s / 0.000s | 1.100s / 3.105s | p50 提前 1.100s，p90 提前 3.105s | 目标句 final 更早到达 |
| 主说话人离场后，是否能由声纹主动切开连续语音 | speaker endpoint 率 | 0.00% | 93.20% | 提升 93.20 个百分点 | 大多数连续接话场景可触发 |
| 目标人开口阶段是否能被状态机确认 | target 确认率 | 不适用 | 99.00% | 作为保护指标观察 | 本实验同源注册下确认空间充足 |
| speaker-VAD 可能提前截断目标人自己的话 | target 截断率 | 0.00% | 1.00% | 增加 1.00 个百分点 | 主要副作用，可用阈值控制 |
| 目标人结束后多久主动 endpoint | target 后 endpoint 延迟 p50 / p90 | 不适用 | 0.880s / 1.132s | 反应时延约 1 秒 | 与 1.0s 窗长、0.3s 步长配置匹配 |

声纹分数分布如下：

| 窗口区域 | n | p10 | p50 | p90 | mean |
| --- | --- | --- | --- | --- | --- |
| target | 2480 | 0.595 | 0.769 | 0.888 | 0.749 |
| transition | 1666 | 0.100 | 0.362 | 0.750 | 0.396 |
| other | 2219 | 0.017 | 0.145 | 0.335 | 0.164 |

分数分布说明：

- target 窗口 p10 为 0.595，明显高于默认阈值 0.40，说明在本数据集同源注册条件下目标确认空间充足。
- other 窗口 p90 为 0.335，低于默认阈值 0.40，说明大多数非目标人尾窗能被压住。
- transition 窗口 p50 为 0.362，接近默认阈值 0.40，说明边界窗口容易受 target 与 other 混合影响。连续低分机制能避免单个边界窗口抖动就立刻 endpoint。

## 5. 结论与推荐

默认 `threshold=0.40` 是本次实验里较均衡的工作点：非目标泄露降幅达到 60.74%，speaker endpoint 率 93.20%，target 截断率控制在 1.00%。这支持当前主说话人 VAD 对以下场景有效：

- 目标人说完后，旁边人马上接话。
- 环境中存在连续多人语音，普通 VAD 难以靠静音切开。
- 下游只希望尽早拿到目标人的完整一句话，不希望 other 的语音拖进同一个 final 或同一次 LLM 输入。

如果业务更怕误切目标人，可以用 `threshold=0.35`：非目标泄露降幅 57.41%，target 截断率 0.80%。如果业务更怕非目标拖尾，可以用 `threshold=0.45`：非目标泄露降幅 63.33%，但 target 截断率升到 1.40%。

不建议仅凭本实验把阈值推到 0.50：虽然非目标泄露降幅最高，为 66.73%，但 target 截断率升到 2.80%，且本实验 target 注册条件偏乐观，真实跨设备或远场注册下风险可能更高。

## 6. 复现实验

```bash
export AIDATATANG_SPEAKER_VAD_DIR=<aidatatang_test_spk_balanced_500目录>
python3 asr/tools/speaker/06_eval_speaker_vad_aidatatang.py \
  --dataset-dir "$AIDATATANG_SPEAKER_VAD_DIR" \
  --speaker-model shared/models/asr/dingqiao/eres2net.onnx \
  --out-dir asr/tools/speaker/results/aidatatang_speaker_vad_eval \
  --thresholds 0.30 0.35 0.40 0.45 0.50 \
  --win-sec 1.0 \
  --hop-sec 0.3 \
  --consecutive-below 2
```

输出：

- `asr/tools/speaker/results/aidatatang_speaker_vad_eval/summary.json`
- `asr/tools/speaker/results/aidatatang_speaker_vad_eval/summary.md`

## 7. 已知限制

- 每个 speaker 只有 1 条 utterance，target 用自身音频注册，目标确认率和 target 分数分布会偏乐观。
- 本实验是离线状态机复刻，不是真机 Android callback 时延，也不包含 JNI、AudioRecord、ASR decode 和后处理耗时。
- 合成会话无静音拼接，是刻意放大“目标人离场后 other 立刻接话”的压力场景；真实场景中如果中间有足够静音，普通 VAD 本身也可能切开。
- 本实验只证明 speaker-VAD endpoint 对非目标拖尾有效，不替代目标说话人 final 门控的 FAR / FRR / CER / WER 评测。
