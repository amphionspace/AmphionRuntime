## 跨端烟测样本

本目录是「Android / iOS / Linux 服务端」三端共用的 ASR 烟测 WAV 集，定位是 端侧 / 服务端工程链路自检（启动是否正常、是否能跑通完整 PCM → 文本流程、热词分支是否生效），不做 WER 计算。

WER / CER 由上游统一出报告，参见 [scripts/benchmark/](../../scripts/benchmark/) （LibriSpeech + MFA + jiwer 标准流程）。SDK / 服务端发版前需要看上游对应模型的 WER 报告无劣化，再走 [shared/docs/RELEASE_PROCESS.md](../docs/RELEASE_PROCESS.md) 的灰度。

## 用途

1. 三端 SDK 的端到端烟测（在 emulator / simulator 上跑通完整一遍）
2. 服务端 [bench_concurrent.py](../../server/asr-service/bench/bench_concurrent.py) 提供的 PCM 源
3. 现网 bad-case 沉淀池：把出现过的怪音频按本目录约定塞进来，避免下次再裸奔

## 目录约定

```
shared/regression-set/
├── README.md                # 本文件
├── manifest.jsonl           # 数据清单：每行一个 JSON，描述一条样本
├── short/                   # 短句（< 5s）
├── long/                    # 长句（5–30s）
└── hotwords/                # 带热词样本（含业务领域词）
```

WAV 文件不入 git（避免仓库膨胀）。请把 WAV 放在公司内网对象存储 / NAS，CI 里用 `aws s3 sync` 或 rsync 拉到 `shared/regression-set/`，路径与 [manifest.jsonl](manifest.jsonl) 中保持一致。

本目录默认 .gitignore 掉所有 .wav 文件（见 [.gitignore](.gitignore)），但 `manifest.jsonl` / `*.md` 必须入库。

## manifest.jsonl 协议

每行一个 JSON，字段如下（注意：本协议不再持有 ground truth，因 WER 由上游统一计算）：

```json
{
  "id": "short-0001",
  "wav": "short/0001.wav",
  "lang": "zh",
  "duration_sec": 3.2,
  "category": "short",
  "hotwords": [],
  "tags": ["daily", "general"]
}
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| id | string | 是 | 样本唯一 id；规则：`<category>-<seq>` |
| wav | string | 是 | 相对本目录的 WAV 路径 |
| lang | string | 是 | zh / en / mixed |
| duration_sec | number | 是 | 音频时长，秒 |
| category | string | 是 | short / long / hotwords |
| hotwords | array | 否 | 仅 hotwords category 必填；本句应该用到的领域词 |
| tags | array | 否 | 自由标签，便于切片统计 |

## 数据采集要求

- 采样率：16 kHz mono 16-bit PCM WAV
- 信噪比：> 20 dB（避免数据本身导致烟测抖动）
- hotwords 类别：每条 WAV 至少出现 1 个公司业务领域词；hotwords 字段填入实际命中的词列表

## 维护规则

- 新增样本：append 到对应 category 目录 + 在 manifest.jsonl 末尾追加新行
- 不要删除已存在的 id：避免历史报告对不上；如果某条样本要废弃请打 `tags: ["deprecated"]` 并保留
- 增删 hotwords 类别样本时同步更新 `tools/asr-sdk/hotwords/` 下的词典
- 此目录不再承担识别正确性评估职责。WER / CER 评估请走上游 [scripts/benchmark/](../../scripts/benchmark/)，下游不重复造轮子
