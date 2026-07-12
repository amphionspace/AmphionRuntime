import { audio } from '@kit.AudioKit';
import worker, { ErrorEvent, MessageEvents, ThreadWorkerGlobalScope } from '@ohos.worker';

const workerPort: ThreadWorkerGlobalScope = worker.workerPort;
const PCM_BYTES_PER_MS = 32; // 16 kHz * mono * S16LE / 1000
const LATE_CALLBACK_TOLERANCE_MS = 10;

let capturer: audio.AudioCapturer | undefined;
let running: boolean = false;
let stopping: boolean = false;
let callbackCount: number = 0;
let totalBytes: number = 0;
let previousCallbackAtMs: number = 0;
let previousBufferDurationMs: number = 0;
let maxCallbackGapMs: number = 0;
let lateCallbackCount: number = 0;
let callbackGapExcessMs: number = 0;
let maxCallbackWorkMs: number = 0;
let bufferSizeBytes: number = 0;

function resetStats(): void {
  callbackCount = 0;
  totalBytes = 0;
  previousCallbackAtMs = 0;
  previousBufferDurationMs = 0;
  maxCallbackGapMs = 0;
  lateCallbackCount = 0;
  callbackGapExcessMs = 0;
  maxCallbackWorkMs = 0;
  bufferSizeBytes = 0;
}

function onReadData(buffer: ArrayBuffer): void {
  if (!running || buffer.byteLength === 0) return;
  const callbackStartedAt = Date.now();
  if (previousCallbackAtMs > 0) {
    const gapMs = callbackStartedAt - previousCallbackAtMs;
    if (gapMs > maxCallbackGapMs) maxCallbackGapMs = gapMs;
    const excessMs = Math.max(0, gapMs - previousBufferDurationMs);
    if (excessMs > LATE_CALLBACK_TOLERANCE_MS) {
      lateCallbackCount += 1;
      callbackGapExcessMs += excessMs;
    }
  }
  previousCallbackAtMs = callbackStartedAt;
  previousBufferDurationMs = buffer.byteLength / PCM_BYTES_PER_MS;
  callbackCount += 1;
  totalBytes += buffer.byteLength;

  // The audio framework owns/recycles its callback buffer. Copy once, then transfer ownership to
  // the host so this callback returns without waiting for synchronous ASR decode on the host thread.
  const pcm = buffer.slice(0);
  try {
    workerPort.postMessage({ type: 'pcm', pcm: pcm }, [pcm]);
  } catch (e) {
    failAndStop(`PCM 传输失败：${e}`);
    return;
  }
  const workMs = Date.now() - callbackStartedAt;
  if (workMs > maxCallbackWorkMs) maxCallbackWorkMs = workMs;
}

async function startCapture(): Promise<void> {
  if (running || capturer !== undefined) return;
  resetStats();
  try {
    const streamInfo: audio.AudioStreamInfo = {
      samplingRate: audio.AudioSamplingRate.SAMPLE_RATE_16000,
      channels: audio.AudioChannel.CHANNEL_1,
      sampleFormat: audio.AudioSampleFormat.SAMPLE_FORMAT_S16LE,
      encodingType: audio.AudioEncodingType.ENCODING_TYPE_RAW
    };
    const capturerInfo: audio.AudioCapturerInfo = {
      source: audio.SourceType.SOURCE_TYPE_MIC,
      capturerFlags: 0
    };
    const created = await audio.createAudioCapturer({ streamInfo, capturerInfo });
    capturer = created;
    bufferSizeBytes = created.getBufferSizeSync();
    created.on('readData', onReadData);
    running = true;
    await created.start();
    workerPort.postMessage({ type: 'started', bufferSizeBytes: bufferSizeBytes });
  } catch (e) {
    running = false;
    await releaseCapturer();
    workerPort.postMessage({ type: 'error', message: `麦克风启动失败：${e}` });
  }
}

async function stopCapture(errorMessage: string = ''): Promise<void> {
  if (stopping) return;
  stopping = true;
  const current = capturer;
  let overflowCount = -1;
  if (current !== undefined) {
    try {
      // A non-zero value is definitive evidence of framework loss. Some normal-capture paths in
      // Harmony do not increment this counter, so callback gap metrics are recorded as well.
      overflowCount = current.getOverflowCountSync();
    } catch (e) {
      overflowCount = -1;
    }
    try {
      await current.stop();
    } catch (e) {
      // Continue through off/release and return the diagnostics collected so far.
    }
    // Let a readData task that was already queued before stop run while `running` is still true.
    // The stopped ack must stay behind that final PCM message on the same worker port.
    await new Promise<void>((resolve: () => void): void => {
      setTimeout(resolve, 0);
    });
  }
  running = false;
  await releaseCapturer();
  stopping = false;
  if (errorMessage.length > 0) {
    workerPort.postMessage({ type: 'error', message: errorMessage });
    return;
  }
  workerPort.postMessage({
    type: 'stopped',
    overflowCount: overflowCount,
    callbackCount: callbackCount,
    totalBytes: totalBytes,
    maxCallbackGapMs: maxCallbackGapMs,
    lateCallbackCount: lateCallbackCount,
    callbackGapExcessMs: callbackGapExcessMs,
    maxCallbackWorkMs: maxCallbackWorkMs,
    bufferSizeBytes: bufferSizeBytes
  });
}

async function releaseCapturer(): Promise<void> {
  const current = capturer;
  capturer = undefined;
  if (current === undefined) return;
  try {
    current.off('readData');
  } catch (e) {
    // best-effort teardown
  }
  try {
    await current.release();
  } catch (e) {
    // best-effort teardown
  }
}

function failAndStop(message: string): void {
  stopCapture(message);
}

workerPort.onmessage = (event: MessageEvents): void => {
  const type = event.data['type'] as string;
  if (type === 'start') {
    startCapture();
  } else if (type === 'stop') {
    stopCapture();
  }
};

workerPort.onmessageerror = (event: MessageEvents): void => {
  failAndStop(`录音线程消息解析失败：${event.type}`);
};

workerPort.onerror = (event: ErrorEvent): void => {
  failAndStop(`录音线程异常：${event.message}`);
};
