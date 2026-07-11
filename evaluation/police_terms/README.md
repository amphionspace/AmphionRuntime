# 警务术语（terms）批量评测工装

本批测试集：`test_data/police_terms_20260711/`（1932 条 / 6 说话人 / 4 类）。
端侧走 `PoliceTermsBatchEvalActivity`（`com.amphion.asr.sample`），本目录是主机侧驱动链。

## 数据流

```
build_cases.py            # 4 类 -> cases.tsv + build/metadata.jsonl + build/push/wavs（硬链接）
  └─ push_batch_eval.sh   # build/push/ -> 真机 batch-eval/（清 progress）
       └─ run_batch.sh    # am start 拉起评测（fresh 重置输出）
            └─ pull_eval.sh    # 拉回 police_terms_eval.tsv 到 <round>/
                 └─ analyze_police_terms_eval.py  # 分类别 CER/整句准确率 + failures + confusion_pairs
```

## 一次基线全流程

```bash
cd evaluation/police_terms
python3 build_cases.py                       # 生成用例（默认读 test_data/police_terms_20260711）
./push_batch_eval.sh --archive-old           # 推真机（旧输出先归档到 _archive/）
./run_batch.sh all                           # 跑全部 4 类（fresh）
# 等设备跑完（logcat -s PoliceTermsBatchEval:I 看进度）
./pull_eval.sh round_baseline --analyze      # 拉回 + 分析
```

分类别单跑：`./run_batch.sh appname` / `vocab` / `dialog` / `specialcode`。
断点续跑：`./run_batch.sh all --resume`（不 fresh，跳过 progress 里已完成的）。

## 设备契约（勿改）

- 读：`/sdcard/Android/data/com.amphion.asr.sample/files/batch-eval/`
  - `metadata.jsonl`：`{orig_utt_id, utt_id, text, audio_path}`，按 `orig_utt_id` 前缀过滤
  - `wavs/<utt_id>.wav`（flat；utt_id 全局唯一）
- 写：`.../files/police-terms-eval/police_terms_eval.tsv`（9 列）
- `orig_utt_id = police_terms_20260711_<catkey>`，catkey ∈ {vocab, dialog, appname, specialcode}

## 验收口径（analyze 的 sent_acc，标点无关）

| 类别 | 目标 |
|---|---|
| 行业对话 dialog | ≥98% |
| 行业词汇 vocab | ≥95% |
| 应用名称 appname | ≥90%（补词后） |
| 特殊代码 specialcode | ≥90% |

> 设备 `sent_match` 列标点敏感、偏严，仅参考；甲方口径用 analyze 的 `sent_acc`。
> 音频 24kHz，端侧 `WavIo.readPcm16k` 会重采样到 16k，无需预处理。
