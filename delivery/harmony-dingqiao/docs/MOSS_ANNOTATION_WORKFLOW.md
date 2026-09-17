# MOSS 辅助标注与复核流程

2026-09-17。真实录音没有标注时，默认先用 MOSS-Transcribe-Diarize 生成文字、说话人编号和时间区间，形成可复核的辅助标注。已有标注但诊断依赖某个争议区间时，也使用此流程交叉检查。

MOSS 是研发标注工具，不接入端侧 SDK；它的输出不能自动成为人工真值。只有结果视频而没有原始录音时，无法标注客户原会话，须明确使用了替代语料。

## 1. 固定输入和标注状态

- 优先使用 SDK 实际收到的完整 PCM，保存原录音到 PCM 的对应关系、采样率、声道、时长、裁剪起点，以及文件和裸 PCM 各自的 SHA-256。核对截断、重采样和声道选择，不能只比较文件名。
- 辅助标注必须对应实际评测输入。同一裁剪偏移只应用一次；生成时间先按片段相对时间保存，需要原录音坐标时另列偏移。
- 第一次输入仅提供音频和默认任务提示，不提供期望人数、SDK 输出、参考转写或角色答案。用户确认的实际人数可用于生成后的核对，不用于强制模型输出指定人数。
- 每次运行使用新的私有证据目录，保存失败和截断输出。不重复采样直到出现期望答案；需要重跑时先记录唯一变化、要证伪的假设和停止条件。

标注状态按区间记录：

| 状态 | 含义 | 可用于什么结论 |
|---|---|---|
| MOSS 辅助标注 | 模型独立生成，未经听审 | 定位候选问题、组织后续复核 |
| 交叉支持 | 原标注与 MOSS 在该区间身份一致 | 支持局部假设；不保证边界和重叠完全正确 |
| 已听审裁定 | 明确记录复核人、区间和裁定依据 | 对应范围内的正式参考；不得冒称整段均已听审 |
| 待裁定 | 身份、边界、重叠、特殊发声或截断存在争议 | 保留并报告，不能强行判定 SDK 正误 |

不要给未裁定部分补一个假分数。若评估仅覆盖已裁定范围，必须同时列出未评估时长及原因，不能静默排除难例后宣称整段通过。

## 2. 当前可用环境

用户指定主机：`amphion-42`。以下路径于 2026-09-17 核实；执行前检查是否仍存在，路径失效时先查找，不自动改服务或安装新环境。

| 项目 | 路径或版本 |
|---|---|
| 工具仓库 | `~/workspace/audiollm-go` |
| Python 环境 | `~/workspace/audiollm-go-speaker-clustering/.local-test-runs/moss-diarization/venv/bin/python` |
| 模型目录 | `~/workspace/audiollm-go-speaker-clustering/.local-test-runs/moss-diarization/model` |
| 模型锁 | 仓库内 `docs/evaluations/community-diarization/acceptance/moss/model-lock.json` |
| 模型 | `OpenMOSS-Team/MOSS-Transcribe-Diarize`，revision `704aa4a9c304e8520be88901e0d1960158ef5b15` |
| 官方 helper revision | `61bc29cd4120be7b5d3b761b64cd5dff57263642` |
| 带参考的评测入口 | 仓库内 `test/delivery/tools/speaker_clustering/evaluate_moss.py` |
| 无参考的官方 CLI | `python -m moss_transcribe_diarize.app.cli` |

复用已安装环境，检查可用显存，串行运行。显存不足时保留失败并调整执行安排，不为辅助标注擅自停止其他服务。录音仅送到已获授权的研发机器，原音、转写、向量和完整日志保存在私有目录。

## 3. 无标注录音的生成入口

在 amphion-42 上执行，先将 `moss_input` 改为已准备的实际输入绝对路径：

```bash
cd "$HOME/workspace/audiollm-go"
moss_python="$HOME/workspace/audiollm-go-speaker-clustering/.local-test-runs/moss-diarization/venv/bin/python"
moss_model="$HOME/workspace/audiollm-go-speaker-clustering/.local-test-runs/moss-diarization/model"
moss_input=/absolute/path/to/input.wav
moss_run=$(mktemp -d "$PWD/.local-test-runs/moss-annotation-XXXXXXXX")
HF_HUB_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
  "$moss_python" -m moss_transcribe_diarize.app.cli "$moss_input" \
  --backend hf --model "$moss_model" --device cuda:0 --dtype bf16 \
  --decoding greedy --max-new-tokens 5120 --out-dir "$moss_run" \
  > "$moss_run/summary.json" 2> "$moss_run/stderr.log"
```

这个入口不需要参考标签。保留 `raw_transcript.txt`、`segments.json`、字幕文件和 `summary.json`。默认提示词不覆盖，`--render` 不启用。此 CLI 会选择可用 attention backend；应记录实际 backend，不能自动套用另一轮固定 SDPA 的证据。

5120 是本次三分钟片段使用的上限，不是任意长音频都足够。检查生成 token 数、解析段数、时间合法性、尾部实际语音是否覆盖，达到上限或缺尾则标为 INCONCLUSIVE。需要提高上限或拆分时，保留原失败、预先固定新方案；跨片段的 S01 不保证是同一个人，必须另做身份对齐，不能直接拼接编号。

另存 `run.json`：输入及模型文件哈希、模型锁、工具提交及源码哈希、依赖版本、提示词、生成配置、实际 attention backend、开始结束时间、生成 token 数和完整性检查。本 CLI 的输出不能替代这些绑定信息；本次固定 SDPA 复核使用的是下述评测入口。

有可信参考时，可复用 `evaluate_moss.py` 的完整模型锁检查与评分。输入 JSONL 需要 `name`、`recording_id`、`duration_seconds`、`audio_filepath`、`pcm_sha256` 和 `reference`；`reference` 为 `[startSeconds, endSeconds, speakerId]` 列表。该脚本在模型生成后才评分，不能给无参考录音伪造 `reference=[]`，再把空参考分数当精度。

## 4. 生成后的复核

1. 核对原始输出和解析结果：编号集合、段数、时间区间与截断。生成末尾小幅越界时保留原始值，裁剪后的评分另行记录，不改原输出。
2. 若有原 TextGrid/RTTM，核对人物、区间、偏移、转换精度和特殊标记。起点与时长分别舍入导致的亚毫秒差，不等同真实换人边界错误。
3. 固定整段身份对应关系，再逐区间比较。SDK 的 S4、MOSS 的 S04、参考的第四个人不能按数字直接对应。
4. 根因分析回溯建档/查询实际 PCM：取样区间、重叠、窗口、`evidenceKey`、档案创建时间及样本贡献。评估器为了计算 DER 得出的一一映射，只是计分映射，不证明某档案真实属于谁。
5. 重点复核用户投诉处、SDK/MOSS 分歧处、短插话、重叠及新身份首次出现处。把原音小片段、双方标签和文字并排留存；需要确定性裁定时听审并记录。尚未听审必须明说。
6. 指标注明参考来源、collar、是否含重叠、评分范围及未知处理。MOSS 与原标注的 DER 不是“标注错误率”；模型人数一致也不能单独证明标注正确。

无人工参考时，可以报告“与 MOSS 的一致性”和具体分歧，不能把它命名为正式准确率。辅助标注和诊断结论发生修正时，新增更正记录，保留旧报告与哈希。

## 5. 本次复核留下的教训

三段固定 180 秒 AISHELL-4 录音，MOSS 自然分出 2/3/4 人，与原标注一致；250 ms collar、含重叠的 DER 分别为 2.84%、8.62%、15.08%。最后一段仍漏检约 21 秒，不能直接用 MOSS 替换全部原标注。

四人片段中，MOSS 支持原标注在 121–123 秒的主要人物仍为前面的同一个人。SDK S4 的初始建档样本也主要来自此人；将计分映射的 S4 当成另一真实人物，再据相似度推断模型能力不足，是错误的归因方式，应撤回该推断。另有约 0.99 秒换人边界分歧和约 1.164 秒纯 `<$>` 标记未进入 RTTM，均保留为待裁定。

私有证据目录：`~/.cache/amphion-runtime/diagnostics/customer-video-diarization-20260917-d3w2c6q2/moss-annotation-audit-8cqlfeo8/`；远端：`~/workspace/audiollm-go/.local-test-runs/harmony-annotation-audit-20260917-8cqlfeo8/`。证据清单为 `evidence-manifest.json`，结论为 `标注复核与归因更正.md`。原音和完整转写不入库。

后续优化见 [角色分离优化计划](SPEAKER_DIARIZATION_OPTIMIZATION_PLAN_20260917.md)。
