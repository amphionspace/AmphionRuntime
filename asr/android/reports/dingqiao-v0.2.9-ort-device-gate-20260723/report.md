# 鼎桥 Android ASR SDK 真机门禁报告

- 日期：2026-07-23
- 分支：`feat/android-runtime-api-alignment`
- SDK 被测提交：`7016f135496136490271768e79a64dd1ebc69fd4`
- 设备：vivo V2505A，Android 16 / API 36
- 测试语言：`ZH_EN`
- 结论：**BLOCKED（不是 PASS）**

## 阻断项

`voiceprint-fallback` 要求使用旧版本可稳定复现“非空 endpoint final 但分数缺失”的固定双文件语料。本机、仓库、下载目录、已有压缩包和 vivo 设备均未找到以下文件，因此没有用随机音频替代：

1. `情指行-勤指.wav`
2. `帮我核查身份证号码为三七零五零311九九111二三零九八三。.wav`

拿到这两个文件后只需补跑 `DqVoiceprintTest.v04c_fixedFallbackCorpusFirstEndpointHasScore`。在该用例通过前，完整发布门禁不能标记为 PASS。

## 已通过门禁

| 门禁 | 结果 | 证据摘要 |
| --- | --- | --- |
| Android SDK 单测 | PASS | debug/release，`sdk` 与 `sdk-dingqiao` 全部通过 |
| Harmony 相邻状态机单测 | PASS | 32/32 |
| 生命周期与数值边界 | PASS | `DqSdkCornerCaseTest` 25/25 |
| burst / paced / drain | PASS | 4 个文件 realtime、fast、fast-long-drain 文本完全一致 |
| 音频语料 | PASS | 24/24 OK，无 ERROR、TIMEOUT、EMPTY |
| finish flush | PASS | 4 个分层文件 realtime/fast-short/fast-long 完全一致 |
| `vadBegin` 真语音 | PASS | 显式 `finish` 前无 `isLast` |
| `vadBegin` 纯静音 | PASS | 配置时间到达后恰好一次 last/complete |
| 声纹主流程 | PASS | `DqVoiceprintTest` 除固定 fallback 语料外 12/12 |
| License | PASS | 12/12 |
| 内置声纹模型 | PASS | 公共 `preloadVoiceprintModel()` 安装并可用 |
| ORT 快速加载 | PASS | cold 1892 ms、warm 39 ms、model reload 1283 ms、runtime reload 1299 ms |
| 用户操作序列 | PASS | 300 cycles；300 cancel + 600 正常 session |
| 长稳压 | PASS | 单组 209 秒；RSS 有回落，线程稳定，无单调泄漏证据 |

## 生命周期断言

- 普通 session 在显式 `finish` 前 `isLast` 数量为 0。
- 正常结束恰好一次 `isLast`，随后恰好一次 `onComplete`。
- cancel 后不产生 final/complete。
- `onStart` 回调栈内同步 write、finish、cancel 均可用。
- `shutdown -> unloadModel -> createEngine` 后的首次回调内同步回放可用。
- 旧 session 的迟到 write/finish/cancel 不终止或污染替换 session。
- `maxAudioDuration`、重复 finish、非法 session/frame、NaN/Infinity、回调内重入均分别通过。

## 资源观察

24 文件、209 秒语料测试中，RSS 从约 475 MiB 上升到峰值约 589 MiB，随后回落到约 492 MiB，结束约 493–504 MiB；线程主要保持 49–50，结束为 47。该结果排除了本轮测试中的持续单调增长，但不等价于覆盖系统 OOM、低存储、USB 断连或驱动异常。

300 轮用户操作序列运行 205.822 秒。RSS 在约 502–587 MiB 间波动并多次回落，线程主要为 49–50。

## 已知测试环境问题

vivo 会冻结后台 instrumentation。测试 APK 增加了仅 debug 生效的前台保活 Activity；它不调用 SDK，不创建或卸载引擎。第一次声纹组合运行曾因测试夹具重复 `setLicense` 导致仍被复用的 engine 失效，并在 native `OnlineRecognizer_createStream` 触发 SIGSEGV。测试夹具已改为每个进程只准备一次 runtime，相关顺序用例随后通过；失败 tombstone 作为回归证据保留。

导出 JSONL 时误改了 debug app 数据目录权限，Android 16 的 `run-as` 随即拒绝访问。设备已卸载并重装同一测试 APK，随后 ORT 公共生命周期冒烟测试再次通过。卸载仅删除了测试 Demo 的临时数据；已拉取 TSV 和 tombstone 均保留。完整 JSONL 原文件未能导出，本报告记录其测试统计。

## 证据文件

- `evidence/dingqiao_audio_eval.tsv`
- `evidence/finish_flush_regression.tsv`
- `evidence/corpus_memory.tsv`
- `evidence/user_sequence_memory.tsv`
- `evidence/logcat.txt`
- `evidence/tombstone_29.txt`
