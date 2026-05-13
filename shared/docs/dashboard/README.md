## 月度跨端联合工程指标 Dashboard

本目录沉淀每月一次的「Android / iOS / Linux 服务端」联合工程指标报告，方便横向对比 + 长期趋势观察。

> 识别正确性（WER / CER）由上游 sherpa-onnx [scripts/benchmark/](../../../scripts/benchmark/) 统一出报告，下游不重复造轮子。月度报告里只通过 URL 链上去做引用，本 dashboard 自身只追踪 端 / 服务端工程指标 三轨。

## 目录结构

```
shared/docs/dashboard/
├── README.md            # 本文件
├── runner.py            # 一键跑齐三端 + 出 dashboard 的脚本
├── trends/              # 历年汇总 CSV + Markdown 报告
│   ├── rtf.csv          # 服务端 RTF / 并发 / 内存 / 错误率
│   ├── crash.csv        # 端 crash 率
│   ├── startup.csv      # 端启动延迟
│   └── reports/
│       ├── 2026-04.md
│       ├── 2026-05.md
│       └── ...
└── templates/
    └── monthly.md.tpl   # 月度报告模板
```

## 出报告流程

每月最后一个工作日由值班同学触发：

```bash
python shared/docs/dashboard/runner.py \
    --month 2026-05 \
    --android-aar artifacts/amphion-runtime-1.1.0.aar \
    --ios-xcframework artifacts/AmphionRuntime-1.1.0.xcframework \
    --server-image your-registry/asr-service:1.1.0 \
    --bench-target localhost:50051 \
    --upstream-wer-report-url 'https://internal.example/asr/wer/2026-05.html' \
    --out shared/docs/dashboard/trends/reports/2026-05.md
```

`runner.py` 会：

1. 调端侧脚本拉启动延迟 p50 / p95
2. 调 server bench 出 RTF / 并发 / 内存 / first-partial 延迟 / 错误率
3. 拉 Sentry / Bugly / Crashlytics 上月 crash 率
4. 把上游 WER 报告 URL 直接渲染成顶部链接（不重新跑 WER）
5. 结果写到 `trends/{rtf,crash,startup}.csv` 末尾 + 渲染本月 markdown 报告

## 关键工程指标

| 指标 | 健康阈值 | 数据源 |
| --- | --- | --- |
| 启动延迟（Engine 初始化） | ≤ 800 ms p95 | 三端 SDK 内置打点 |
| 单流 RTF (CPU) | ≤ 0.35 (mod_beam_search) | server bench |
| 服务端 RTF p99 | ≤ 0.5 | server bench |
| 服务端内存峰值 | ≤ 2048 MiB | server bench |
| 服务端 first-partial 延迟 p95 | ≤ 500 ms | server bench |
| Crash 率 (端) | ≤ baseline + 0.05% | Bugly / Crashlytics / Sentry |
| 服务端 9001 错误率 | ≤ 0.1% QPS | Prometheus asr_error_total |

识别正确性指标（WER / CER / 命中率）请直接看上游 [scripts/benchmark/](../../../scripts/benchmark/) 的 CSV 报告，不在本 dashboard 出现。

## 异常触发

- 任意工程指标连续 2 个月劣化 ≥ 0.5%，自动建 P1 ticket
- 单月劣化 ≥ 1%，触发 P0 + 走 [RELEASE_PROCESS.md 第 3.2 节回滚 SOP](../RELEASE_PROCESS.md#32-紧急回滚-sop)
- 上游 WER 报告劣化阈值（如何回滚）由算法同学根据 baseline 决定，不在本 dashboard 决策

## 历史报告索引

历史报告按月归档在 `trends/reports/<YYYY-MM>.md`；汇总趋势用 [trends/rtf.csv](trends/rtf.csv) 等 CSV，可直接喂给 Grafana / Superset。
