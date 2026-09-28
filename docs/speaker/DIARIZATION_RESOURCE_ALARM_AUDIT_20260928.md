# 角色分离资源报警线审计（2026-09-28）

修正默认 64 MiB 对角色分离的硬否决，并取消“整段 RSS 下降即可证明内存稳定”的自动放行。
两者都把不同生命周期阶段的进程 RSS 当成了同阶段资源证据。新结论为 `INCONCLUSIVE`，
保留原始统计和报警；没有把增长改写为正常，也没有宣称角色分离整体交付完成。

## 修改边界

- 改变：采集脚本和端到端评估器统一解释角色分离默认 RSS 报警；显式及模式隐式开启均适用。
- 保持：普通 ASR 的默认预算、显式 RSS 预算、线程增长、队列、stream 回收、回调及收尾契约。
  显式 `--max-rss-growth-mb 64` 仍然是硬预算。旧报告中的非默认预算继续执行。
- 不处理：SDK 推理、模型、窗口、timeout、身份精度和长会议资源定标；不改历史报告与交付结论。

此规则落实 [2026-09-15 已有解释](../../delivery/harmony-dingqiao/docs/MEETING_SPEAKER_FIX_20260915.md)：
通用 64 MiB 未按会议角色分离定标，不能单独判定泄漏或否决修复。旧报告未记录 64 MiB
是否显式传入，按通用报警解释；若历史验收另有硬预算，必须在绑定原证据的评审中保留该判断。
新报告记录 `rss_growth_limit_enforced`，消除后续歧义。

## 失败现场复算

复用 [PR #235 同产物证据](DIARIZATION_PR235_MERGE_ACCEPTANCE_20260928.md)，仅在主机读取
两份原报告与 CSV。SDK 运行提交为 `6578c787f26d181253861f8c5e203208ae8a65a0`，
Mate80 `7GK0226326015655` / `OpenHarmony-6.1.1.120`，HAP SHA-256 为
`c4583f3031dc39a743783770d2edcdae6d54a23263c27b309ea3c1e9a17e3317`。

| 原始用例 | 不变的测量结果 | 资源判断 |
| --- | --- | --- |
| paced，4×19.58 s | 70 点，87.733 s；RSS +85.650 MiB；线程 −0.5 | 原通用 FAIL 保留；角色分离 INCONCLUSIVE |
| voiceprint-fallback，cold/warm，角色分离开启 | 23 点，27.973 s；RSS +68.113 MiB；线程 −10 | 原通用 FAIL 保留；角色分离 INCONCLUSIVE |

paced 的 head 窗口混入第二轮推理前低位，tail 窗口多数采样仍在第四轮运行阶段；
tail 中位数 570.371 MiB，最后实际采样却为 420.340 MiB。+85.650 MiB 不是同阶段结束残留。
voiceprint-fallback 的首轮冷驻留与次轮 warm 阶段不同；结束只 shutdown，进程级声纹模型池
仍可驻留。该短观察不能完成全部字节归属。白盒来源与回收修复沿用
[内存归属](DIARIZATION_MEMORY_OWNERSHIP_20260928.md)和
[arena 回收](DIARIZATION_ARENA_RELEASE_20260928.md)，不冒充当前 HAP 的逐分配计数。

[复算索引](evidence/DIARIZATION_RESOURCE_ALARM_AUDIT_20260928.json)绑定输入报告、CSV 和三个
评估模块的 SHA-256。逐字段重新计算与原报告相同；两份采样在普通 ASR 策略或显式 64 MiB
预算下仍 FAIL，原回调轨迹仍 PASS。旧报告没有覆盖写入。

## 相邻报警线审计

范围为 `device_stress_metrics.py`、`run_device_stress.py`、`diarization_evaluation.py`
及其调用方；没有将“未发现过时依据”写成这些预算已完成产品定标。

| 规则 | 处理与依据 |
| --- | --- |
| 默认 RSS 增长 64 MiB | 仅角色分离改为诊断报警；普通 ASR 保留 |
| >60 s、末段 RSS 不高于首段且斜率 ≤0 自动 PASS | 删除自动放行；释放阶段下降同样可能掩盖运行增长，须同阶段评审 |
| 6 个样本 / 15 s 最小观测，60 s 才算斜率 | 保留统计前提；纠正文档，达到时长不代表预热结束或无泄漏 |
| 默认线程增长 ≤2 | 保留硬门禁；本次两个失败现场均未触发它 |
| stream 归零、唯一 last/complete、cancel 无结束回调 | 保留硬门禁；与模型驻留不能互相替代 |
| finish→complete ≤15 s | 保留：[9 月 23 日客户窗口](../../delivery/harmony-dingqiao/docs/SEPT23_FEEDBACK_TRIAGE.md)仍有效 |
| 角色队列 pending≤2，音频延迟≤10 s 且无上升才可自动通过 | 保留；10 s 来源于既有输入窗口，持续增长仍须定位 |
| 目标说话人增强处理 <1750 ms、队列≤2 | 保留；该路径每 1.75 s 到达下一块，与角色分离窗口不同 |
| 正常结束模式空 final≤5% | 保留；没有过时证据，不替代逐 session 生命周期检查 |
| 调用方自定预算（包括警务语料评估的 1024 MiB / 32 线程） | 保留显式配置；不能据此推导角色分离的预算 |

## 验证与放行边界

修改前两条最小回归均红灯：通用报警被继承为 FAIL；整段 RSS 下降被判为 PASS。
修改后 118 项主机测试通过，覆盖共享指标、设备采集、端到端评估、警务调用方、finish 门禁
及证据归档。新增断言保护普通 ASR、隐式角色模式、显式同值预算、线程失败、证据不足、
重复评估不改原数据，以及哈希绑定评审不能覆盖硬失败。

本次不改变 SDK/HAP/HAR，基于 `origin/main` 的 `7f41e794675b92baae2a0c0e74a8c2a56744ef0c`。
无需重复构建或真机长跑。资源 `INCONCLUSIVE` 仍阻止端到端交付放行；同阶段评审通过后，
仍须满足身份精度、实录体验、实时、生命周期和离线等全部既有门禁。

复现主机测试：

```bash
python3 -m unittest \
  tools.delivery.test_device_stress_metrics \
  delivery.harmony-dingqiao.delivery.test_run_device_stress \
  delivery.harmony-dingqiao.delivery.test_diarization_evaluation \
  delivery.harmony-dingqiao.delivery.test_evaluate_police_corpus \
  delivery.harmony-dingqiao.delivery.test_run_finish_compat_release_gate \
  delivery.harmony-dingqiao.delivery.test_archive_release_gate_evidence -v
```
