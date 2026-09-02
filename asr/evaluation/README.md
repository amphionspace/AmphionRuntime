# ASR 评测

本目录集中管理只服务于 ASR 的离线评测工装、输入协议和人工复核模板。模型、大型语料、真机输出与包含个人路径的临时报告不进入 Git；统一通过仓库资产清单同步。

| 目录 | 用途 |
| --- | --- |
| `plate_number/` | 车牌号码识别结果分析与真机结果拉取 |
| `police_station/` | 派出所名称识别结果分析与真机结果拉取 |
| `police_terms/` | 警务术语批量评测、对比和人工复核 |
| `voiceprint_traffic/` | 声纹真实流量评测协议与 manifest 校验 |

各工装从仓库根目录调用，输入数据必须通过参数显式指定。例如：

```bash
python3 asr/evaluation/police_terms/build_cases.py \
  --src /path/to/police_terms_20260711
```
