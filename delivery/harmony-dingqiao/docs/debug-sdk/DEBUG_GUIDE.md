# Amphion ASR Debug SDK

Debug HAR 与 Release HAR 的模块名和识别接口保持一致。替换四个 HAR 后，现有
`startListening`、`writeAudio`、`finish`、`cancel`、`shutdown` 和回调代码不需要修改。

预配置 Debug HAR 和随包应用默认使用 `CUSTOMER_SUPPORT`：结构化诊断、实际送入公共
`writeAudio` 的 PCM 和识别文本全部开启。客户只替换 Debug HAR 即可完成一次完整复现，
原有识别业务代码不需要修改。该默认值只存在于专用 Debug 交付；Release HAR 中诊断硬关闭。
如现场不允许携带音频或识别文本，可分别传入
`--ps diagnosticsAudio false --ps diagnosticsText false`，复现后点击“导出诊断包”。
自动化真机验证可同时传入 `--ps selftest true --ps diagnosticsExport true`，自测完成后
`DiagnosticSmoke` hilog 会输出 `EXPORT_SUCCESS` 和沙箱路径。传入
`--ps diagnosticsEnabled false` 可验证 Debug 构建的关闭路径。

三种模式：

- `BASIC`：生命周期、参数摘要、回调、资源和 native 状态；即使误设开关也不采音频/文本。
- `CUSTOMER_SUPPORT`：`BASIC` 全部内容，并按独立开关采集公共 `writeAudio` PCM 和识别文本。
- `FAILURE_ONLY`：平时使用内存滚动窗口；遇到 error、空 final、提前 `isLast` 或初始静音
  超时后自动持久化，正常完成的 session 不长期保留。

若宿主需要显式配置，在 `prepareRuntime` 前调用：

```ts
const options = DiagnosticOptions.customerSupport();
options.captureAudio = true;
options.includeRecognitionText = true;
SpeechRecognizeSdk.configureDiagnostics(options);
```

长期现场观察可改用：

```ts
const options = DiagnosticOptions.failureOnly();
options.captureAudio = true;              // 需得到音频采集授权
options.includeRecognitionText = false;
options.failureRingAudioSec = 20;          // 异常前滚动音频
SpeechRecognizeSdk.configureDiagnostics(options);
```

复现结束后导出应用沙箱目录：

```ts
SpeechRecognizeSdk.exportDiagnostics({
  onSuccess: (path: string): void => console.info(`diagnostics=${path}`),
  onError: (code: number, message: string): void => console.error(`${code}: ${message}`)
});
```

电脑连接手机后执行：

```bash
python3 tools/collect_asr_diagnostics.py \
  --device auto --last 1 --note "识别约20秒后提前结束"
```

工具默认使用随包 Demo 的 bundle，并通过 `bm dump` 自动识别 HAP module。用于客户应用时增加
`--bundle com.customer.app`；应用包含多个 HAP module 时同时指定 `--module entry`。

工具会拉取最近一次已导出的诊断、校验 WAV 和 manifest、脱敏 hilog，并生成 ZIP 与
SHA-256。默认只保留异常 session；若没有异常，则只保留最新 session，防止把无关会话带出
应用沙箱。确需全量分析时显式增加 `--include-all-sessions`。手机端文件不会被删除。

交付包自带经过构建流程生成的 `build-identity.json`，收集工具会把 HAP、四个 HAR、native、
模型和源码指纹写入每个 run。也可以通过 `--build-identity <path>` 覆盖。

敏感业务可使用单独密码文件加密输出（密码文件不会进入诊断包）：

```bash
python3 tools/collect_asr_diagnostics.py --device auto --last 1 \
  --encrypt-password-file /secure/channel/asr-debug.password
```

输出为 `.zip.enc`，采用 OpenSSL AES-256-CBC、PBKDF2-SHA256 和 200000 次迭代；密码应通过
与文件不同的渠道传递。

每个诊断目录包含 `manifest.json`、`summary.json`、构建/模型/有效配置身份、事件与回调
NDJSON、脱敏后的 `hilog.txt`、`resource-samples.csv`、`native-state.json`，以及每个 session 的 timeline、result 和
可选 `sdk-input.wav/json`。`summary.json` 会直接标出 finish、提前 `isLast`、空 final、自动结束
原因、PCM 时长/截断、错误、回调延迟和下一轮可用性。

`events.ndjson` schema v2 的每条事件都携带 `runId`、`engineId`、匿名 `sessionId`、
`sessionGeneration`、`streamGeneration`、`wallTimeMs`、单 run 单调递增的
`monotonicTimeNs` 与执行线程类别。Runtime 的模型加载、endpoint、decode、stream reset/restart、
结果抑制、声纹资格/分数和 release 状态会自动映射到同一业务 session。

`writeAudio` 只更新有界内存，不同步写磁盘。Debug 版通过 5 秒低频后台 journal 保存活跃
session；若进程异常退出，下次 `SpeechRecognizeSdk.init` 会恢复为可导出的 run，并写入
`crash-recovery.json`。硬杀进程最多可能丢失最后约 5 秒，不能替代系统 crash dump。

默认单 session 滚动保留最近 5 分钟音频，可配置但最高 10 分钟；超过窗口后持续采集并丢弃
最旧 PCM，元数据会记录滚动丢弃字节数。诊断总目录最多 200 MB，最多保留最近 3 个 run，
超限时从最旧 run 开始清理。以上参数可通过 `DiagnosticOptions` 调整。
