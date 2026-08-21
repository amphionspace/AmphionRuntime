# Amphion ASR Debug SDK

Debug HAR 与 Release HAR 的模块名和识别接口保持一致。替换四个 HAR 后，现有
`startListening`、`writeAudio`、`finish`、`cancel`、`shutdown` 和回调代码不需要修改。

预配置 Debug HAR 和随包应用默认开启结构化诊断，但不包含音频和识别文本。客户只替换
Debug HAR 即可记录非敏感结构化事件，原有识别业务代码不需要修改。测试人员明确同意后，
再通过下方配置开启音频或识别文本；随包应用也可使用启动参数
`--ps diagnosticsAudio true --ps diagnosticsText true`，复现后点击“导出诊断包”。

在 `prepareRuntime` 前显式开启诊断：

```ts
const options = DiagnosticOptions.customerSupport();
options.captureAudio = true;
options.includeRecognitionText = true;
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
SHA-256。手机端文件不会被删除。

当前实现采用显式导出：`writeAudio` 只写入最长 120 秒的有界内存快照，不同步写磁盘；
崩溃前自动落盘和 `FAILURE_ONLY` 环形缓冲将在后续阶段实现。
