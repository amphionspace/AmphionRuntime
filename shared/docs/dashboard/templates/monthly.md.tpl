## ASR 月度联合工程指标报告 — {{MONTH}}

> 生成时间：{{GENERATED_AT}}  
> 生成方式：`shared/docs/dashboard/runner.py --month {{MONTH}}`  
> 上月对比：[{{PREV_MONTH}}](./{{PREV_MONTH}}.md)  
> 上游 WER 报告（识别正确性）：{{UPSTREAM_WER_REPORT}}

> 注：识别正确性（WER / CER）由上游 sherpa-onnx `scripts/benchmark/` 统一出报告，本 dashboard 不重复造轮子。本报告只追踪 端 / 服务端工程指标 三轨：启动延迟、服务端 RTF / 并发 / 内存、客户端 crash 率。

## 1. 总览

| 维度 | 本月 | 上月 | 变化 | 健康 |
| --- | --- | --- | --- | --- |
| RTF 单流 | {{RTF_SINGLE}} | {{RTF_SINGLE_PREV}} | {{RTF_SINGLE_DELTA}} | {{RTF_SINGLE_STATUS}} |
| RTF p99 多流 | {{RTF_P95}} | {{RTF_P95_PREV}} | {{RTF_P95_DELTA}} | {{RTF_P95_STATUS}} |
| Android 冷启动 p95 | {{ANDROID_COLD_P95}} ms | - | {{ANDROID_COLD_P95_DELTA}} ms | - |
| iOS 冷启动 p95 | {{IOS_COLD_P95}} ms | - | {{IOS_COLD_P95_DELTA}} ms | - |
| Crash 率 Android | {{CRASH_ANDROID}} | {{CRASH_ANDROID_PREV}} | {{CRASH_ANDROID_DELTA}} | {{CRASH_ANDROID_STATUS}} |
| Crash 率 iOS | {{CRASH_IOS}} | {{CRASH_IOS_PREV}} | {{CRASH_IOS_DELTA}} | {{CRASH_IOS_STATUS}} |
| 服务端错误率 | {{SVR_ERROR_RATE}} | {{SVR_ERROR_RATE_PREV}} | {{SVR_ERROR_RATE_DELTA}} | {{SVR_ERROR_RATE_STATUS}} |

## 2. 端侧启动延迟（p50 / p95）

| 端 | 冷启动 | 热启动 |
| --- | --- | --- |
| Android | {{ANDROID_COLD_P50}} / {{ANDROID_COLD_P95}} ms | {{ANDROID_HOT_P50}} / {{ANDROID_HOT_P95}} ms |
| iOS | {{IOS_COLD_P50}} / {{IOS_COLD_P95}} ms | {{IOS_HOT_P50}} / {{IOS_HOT_P95}} ms |

## 3. 服务端压测

| 指标 | 值 | 阈值 | 健康 |
| --- | --- | --- | --- |
| 本次并发数 | {{SVR_MAX_CONCURRENCY}} | ≥ {{SVR_MAX_CONCURRENCY_TARGET}} | {{SVR_MAX_CONCURRENCY_STATUS}} |
| RTF p50 | {{SVR_RTF_P50}} | ≤ {{SVR_RTF_TARGET}} | {{SVR_RTF_P50_STATUS}} |
| RTF p99 | {{SVR_RTF_P99}} | ≤ {{SVR_RTF_TARGET}} × 1.5 | {{SVR_RTF_P99_STATUS}} |
| 内存峰值 | {{SVR_MEM_PEAK}} MiB | ≤ {{SVR_MEM_TARGET}} MiB | {{SVR_MEM_STATUS}} |
| First partial 延迟 p95 | {{SVR_FIRST_PARTIAL_P95}} ms | ≤ {{SVR_FIRST_PARTIAL_TARGET}} ms | {{SVR_FIRST_PARTIAL_STATUS}} |

## 4. 客户端崩溃 Top 5

| 端 | 异常 | 影响用户 | Owner | 状态 |
| --- | --- | --- | --- | --- |
{{CRASH_TOP_TABLE}}

## 5. 服务端错误码 Top 5

| 错误码 | 名称 | 占比 | Owner | 状态 |
| --- | --- | --- | --- | --- |
{{SVR_ERROR_TOP_TABLE}}

## 6. 风险与跟进

### 6.1 本月 P0 / P1

{{P0_P1_LIST}}

### 6.2 待跟进项

{{FOLLOWUPS}}

### 6.3 下月计划

{{NEXT_MONTH_PLAN}}

## 7. 附录

- 模型版本：{{MODEL_ID}}@{{MODEL_VERSION}}
- 上游 WER 报告：{{UPSTREAM_WER_REPORT}}
- Android SDK：{{ANDROID_SDK_VERSION}}（aar sha256: {{ANDROID_SDK_SHA}}）
- iOS SDK：{{IOS_SDK_VERSION}}（xcframework sha256: {{IOS_SDK_SHA}}）
- Server 镜像：{{SERVER_IMAGE}}（image digest: {{SERVER_IMAGE_DIGEST}}）
