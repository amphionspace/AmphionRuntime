# C1 buffered-tail Linux 收尾任务

## 目的

这是本分支无训练路线的最后一次算法实验。它只回答冻结的 `buffered_tail_commit` 能否在同一
AISHELL-2 target→other 全量矩阵上同时消除目标截断、非目标文本和 anchor 失败；不修改阈值、窗口、
holdback、ERes2Net、ASR 或 SDK 默认行为。

C2/C3 的无训练盲分离路线已经因 target-absent 开放集门失败而关闭，本任务不得重新运行 Conv-TasNet、
RE-SepFormer、阈值/margin 搜索、真机扩身份或稳压。

## 被测版本和唯一输入

- 分支：`docs/voiceprint-evaluation-plan`
- 最低提交：`05df421`（包含 `94e8e8c` 的 buffered-tail 工具和真机补验）
- baseline：Linux 服务器已有的
  `asr/tools/speaker/results/voiceprint_pilot_20260728_aishell2_enroll3_paired/`
- absolute 对照：
  `asr/tools/speaker/results/voiceprint_pilot_20260805_c1_turn_transition_absolute_full/`
- ERes2Net：
  `asr/harmony/sdk-dingqiao/src/main/resources/rawfile/amphion-dingqiao/eres2net.onnx`
- ZH_EN ASR：
  `asr/harmony/sdk/src/main/resources/rawfile/amphion-models/zh-en/v1/`
- 固定参数：`threshold=0.35`、`win=1.0s`、`hop=0.3s`、连续低分窗 `2`、tail holdback
  `600 ms`、`seed=73`、30 dev / 60 test speaker、`absolute_samples`。

脚本会按仓库冻结哈希校验 ERes2Net 和全部 ASR artifact。新的 `summary.json` 还必须与 absolute 对照的
baseline summary/trials、speaker model 和 ASR artifact 哈希逐项相同；不满足时本轮无效，先修复输入，
不得继续解释业务指标。

## Linux 执行

耗时风险与上一轮 3060 行 absolute replay 同量级。有效停止条件只有：输入/模型哈希不匹配、依赖缺失、
进程异常或 artifact 审计失败。业务严格门 FAIL 是完整实验结果，必须保存并停止，不得改参数重跑。

```bash
git switch docs/voiceprint-evaluation-plan
git pull --ff-only origin docs/voiceprint-evaluation-plan

python3 -m unittest \
  asr.tools.speaker.test_c1_turn_transition_synthetic -v

export C1_BASELINE_DIR="asr/tools/speaker/results/voiceprint_pilot_20260728_aishell2_enroll3_paired"
export C1_ABSOLUTE_DIR="asr/tools/speaker/results/voiceprint_pilot_20260805_c1_turn_transition_absolute_full"
export C1_BUFFERED_RESULT_DIR="asr/tools/speaker/results/voiceprint_pilot_20260805_c1_turn_transition_buffered_tail_full"

python3 asr/tools/speaker/15_eval_c1_turn_transition_synthetic.py \
  --baseline-dir "$C1_BASELINE_DIR" \
  --speaker-model asr/harmony/sdk-dingqiao/src/main/resources/rawfile/amphion-dingqiao/eres2net.onnx \
  --asr-model-dir asr/harmony/sdk/src/main/resources/rawfile/amphion-models/zh-en/v1 \
  --output-dir "$C1_BUFFERED_RESULT_DIR" \
  --seed 73 \
  --dev-speakers 30 \
  --test-speakers 60 \
  --speaker-threads 2 \
  --asr-threads 2 \
  --progress-every 5 \
  --score-schedule absolute_samples \
  --publication-policy buffered_tail_commit
```

输出目录必须在执行前不存在。失败 artifact 不得删除、覆盖或改名后重跑。

## 结果审计

运行后必须同时保留：

- `summary.json`
- `trials.jsonl`
- `report.md`
- `environment.txt`

检查以下后置条件：

1. `configuration.score_schedule == "absolute_samples"`。
2. `configuration.publication_policy == "buffered_tail_commit"`。
3. `configuration.tail_holdback_sec == 0.6`、`seed == 73`。
4. `trial_counts.total_rows == 3060`、dev/test speaker 为 `30/60`、test other speaker 为 `60`。
5. `artifacts` 中 baseline、ERes2Net 和 ASR 哈希与 absolute 对照完全相同。
6. `trials.jsonl` 有 3060 个唯一试验键，所有数值有限；不得出现缺行、重复或 `NaN/Inf`。
7. 记录四个文件的 SHA256；ignored artifact 保留在服务器，只把结论、指标和哈希写回 Git。

## 一次性决策

- `decision.status == PASS`：缓冲候选通过离线业务门。本分支仍不直接实现 SDK；把它记录为后续独立
  SDK 状态机/真机实施候选，然后关闭本调研分支。
- `decision.status == FAIL`：保留 `decision.failures` 和最差桶，关闭 C1 无训练正式默认路线；不得扩大
  holdback、改阈值或复用 test 调参。连同已经关闭的 C2/C3 无训练路线，本分支直接收尾。
- `INCONCLUSIVE` 只允许用于输入、依赖、哈希或 artifact 完整性问题；修复同一阻断后重跑一次，不能
  把业务 FAIL 改记为 INCONCLUSIVE。

Linux 回填提交应只修改结论文档，不提交语料、模型、完整 trials 或任何私有路径。
