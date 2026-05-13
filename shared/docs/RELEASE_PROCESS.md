## ASR 模型 / SDK 发布与灰度流程

本文档覆盖：

- 模型 SemVer 规则
- SDK SemVer 规则
- 端 + 服务端发版灰度流程
- 紧急回滚 SOP

适用范围：Android / iOS / Linux 服务端 / 模型工具链。

## 1. SemVer 规则

### 1.1 模型 SemVer

模型版本号规则与 [tools/asr-sdk/MODEL_LAYOUT.md](../../tools/asr-sdk/MODEL_LAYOUT.md) 第一节一致：

| 段位 | 含义 | 触发例 |
| --- | --- | --- |
| MAJOR | 网络拓扑 / 词表 / chunk size 变更 | encoder 层数变了；tokens.txt 数量变了；frame stride 变了 |
| MINOR | 训练数据扩充 / 收敛后微调 | 加 100 小时医疗领域数据；冻结骨干微调最后两层 |
| PATCH | 仅修复 | 重新量化；INT8 校准重跑；补充缺失 .onnx |

判断方法：MAJOR 升级一定要走端 SDK 的 `min_sdk_version` / `max_sdk_version` 限制；其它两段 SDK 不需要发版。

### 1.2 SDK SemVer

SDK 版本号语义遵守 [semver.org](https://semver.org/lang/zh-CN/)：

| 段位 | 含义 | 触发例 |
| --- | --- | --- |
| MAJOR | 公开 API 不兼容变更 | 删 / 改 [com.yourco.asr](../../android/SherpaAsrSdk/sdk/src/main/java/com/yourco/asr) 包下的方法签名 |
| MINOR | 公开 API 向下兼容的新增 | 新增 [enableLmRescoring](../../android/SherpaAsrSdk/sdk/src/main/java/com/yourco/asr/AsrConfig.kt) |
| PATCH | 仅修复 / 性能优化 | 修热词 bug、优化 RTF |

强约束：

- SDK MAJOR 升级必须配套 [shared/api-spec/](../api-spec/) schema 升版（manifest_version + 1）
- SDK MINOR / PATCH 不允许动公开 API 签名（可加新方法 / 加默认参数 / 不删旧的）
- 所有公开 API 加 `@Deprecated` 至少跨一个 MINOR 版本才能删

## 2. 模型发版流程

### 2.1 出包

按 [tools/asr-sdk/](../../tools/asr-sdk/) 中的脚本顺序：

1. `01_export_to_onnx.md` 算法同学按文档导出 ONNX
2. `02_quantize_int8.md` INT8 量化
3. `03_verify_onnx.sh` 在 Linux cxx-api 上跑通验证集
4. `MODEL_LAYOUT.md` 中的 manifest.json 生成脚本
5. 算法同学按上游 [scripts/benchmark/](../../scripts/benchmark/) 出 WER / CER 报告（标准 LibriSpeech / 公司内部测试集），未劣化才能发；下游不另跑 WER
6. SDK / 服务端只在 [shared/regression-set/](../regression-set/) 上跑端到端烟测（验证 PCM → 文本流程不挂、热词分支生效）

### 2.2 灰度发布

模型走 manifest 灰度：

1. 把模型文件 + manifest.json 上传到 OSS：`s3://your-bucket/asr/<model_id>/<version>/`
2. 在配置中心新建 manifest 灰度规则（按 city / app version / 用户 hash 分桶）
3. 灰度阶段（建议 7 天）：1% → 5% → 25% → 50% → 100%
4. 每个阶段都看：crash 率不上升 / 上游 WER 报告不劣化 / 用户反馈无突变
5. 任何一项异常 → 触发 [3.2 回滚](#32-紧急回滚-sop)

### 2.3 客户端拉取

客户端启动期 / Wi-Fi 时拉 manifest，按 SHA256 校验，原子替换到本地 `<filesDir>/AsrModels/<model_id>/<version>/`。

服务端：滚动重启拉新 manifest（建议金丝雀 1 个 pod 跑 30 分钟无异常，再全量滚动）。

## 3. SDK 发版流程

### 3.1 标准发版

```
PR -> code review -> CI green ->
打 tag v<MAJOR>.<MINOR>.<PATCH> ->
[ci/android.yml](../../ci/android.yml) 自动产出 AAR + 上传到内部 Maven ->
[ios/build_xcframework.sh](../../ios/SherpaAsrSdk/build_xcframework.sh) 产出 xcframework + 挂 GitHub Releases ->
server [Dockerfile](../../server/asr-service/deploy/Dockerfile) build + push 到内部 Registry ->
邮件通知所有业务方 + 更新 [INTEGRATION.md](../../android/SherpaAsrSdk/docs/INTEGRATION.md) CHANGELOG
```

### 3.2 紧急回滚 SOP

| 触发条件 | 优先级 | 处理 |
| --- | --- | --- |
| 客户端 crash 率 ≥ baseline + 0.5% | P0 | 立即回滚 manifest（指向上个稳定 model_version），24h 内查根因 |
| 端 SDK 严重 bug（数据丢失 / 静默失败） | P0 | 紧急 PATCH 版本 + 强制 App 弹窗升级 |
| 上游 WER / CER 报告整体劣化 ≥ 1% | P1 | 模型回滚 + 算法同学 24h 复盘（劣化阈值由算法同学根据 baseline 决定） |
| 服务端 OOM / RTF > 1 | P0 | k8s 回滚 deployment / 临时 scale up + 限流 |
| 服务端 grpc 报 9001 ≥ 0.1% QPS | P1 | 滚动重启；定位是 model 还是 onnxruntime 问题 |

回滚执行：

- 模型：配置中心改 manifest URL 指向上一版本；端侧下次启动自动切换
- SDK：业务方需要发版才能回滚（PATCH 版本反向修复）
- 服务端：`helm rollback asr-service <revision>`

## 4. 月度联合工程回归

WER / CER 评估由上游 [scripts/benchmark/](../../scripts/benchmark/) 出报告，下游不重复跑。每月最后一个工作日由值班同学触发 [shared/docs/dashboard/runner.py](dashboard/runner.py)：

- 三端 SDK 在 [shared/regression-set/](../regression-set/) 上跑端到端烟测，采集 启动延迟 p50 / p95
- 服务端跑 [bench_concurrent.py](../../server/asr-service/bench/bench_concurrent.py) 输出 RTF / 并发上限 / 内存 / first-partial 延迟
- Bugly / Crashlytics / Sentry 拉上月端 crash 率
- 拼接上游 WER 报告 URL（不重新跑 WER），写入 monthly 报告顶部
- 与上月环比，工程指标劣化 ≥ 0.5% 自动 ticket
- 报告归档到 [shared/docs/dashboard/trends/reports/](dashboard/trends/reports/)

## 5. 兼容性矩阵

| 模型 model_type | min_sdk_version | max_sdk_version | 端 |
| --- | --- | --- | --- |
| zipformer2 | 1.0.0 | 2.0.0 | Android / iOS / Server |
| paraformer | 1.1.0 | 2.0.0 | Android / iOS / Server |
| zipformer2_ctc | 1.1.0 | 2.0.0 | Android / iOS / Server |
| nemo_ctc | 1.1.0 | 2.0.0 | Android / iOS / Server |

矩阵更新规则：每次 SDK MINOR 升级时增加新 model_type 行；MAJOR 升级时把 max_sdk_version 上拉。

## 6. 联系

- 技术决策：voice-tech-leads@your-org.example
- 事故响应：voice-oncall@your-org.example（7×24）
- 通知频道：#voice-asr-release
