# Amphion ASR Debug SDK

Debug HAR 与 Release HAR 的模块名和识别接口保持一致。替换四个 HAR 后，现有
`startListening`、`writeAudio`、`finish`、`cancel`、`shutdown` 和回调代码不需要修改。

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

工具会拉取最近一次已导出的诊断、校验 WAV 和 manifest、脱敏 hilog，并生成 ZIP 与
SHA-256。手机端文件不会被删除。

当前实现采用显式导出：`writeAudio` 只写入最长 120 秒的有界内存快照，不同步写磁盘；
崩溃前自动落盘和 `FAILURE_ONLY` 环形缓冲将在后续阶段实现。
