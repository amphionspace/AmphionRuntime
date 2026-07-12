import worker, { ErrorEvent, MessageEvents } from '@ohos.worker';

export type PcmListener = (samples: Int16Array) => void;
export type RecorderErrorListener = (message: string) => void;

const CAPTURE_WORKER_URL = 'dingqiao_demo/ets/workers/AudioCaptureWorker.ets';

/** Diagnostics returned after the worker has completely stopped and emitted every queued PCM block. */
export class AudioRecorderStats {
  overflowCount: number = -1;
  callbackCount: number = 0;
  totalBytes: number = 0;
  maxCallbackGapMs: number = 0;
  lateCallbackCount: number = 0;
  callbackGapExcessMs: number = 0;
  maxCallbackWorkMs: number = 0;
  bufferSizeBytes: number = 0;
}

/**
 * 16 kHz / mono / S16LE microphone capture.
 *
 * AudioCapturer deliberately lives in a ThreadWorker. The SDK's writeAudio path may synchronously
 * decode for longer than Harmony's small capture ring can absorb. Keeping readData on the UI/SDK
 * thread would therefore make the audio service discard whole time spans before the SDK ever sees
 * them. The worker callback only copies/transfers the framework buffer and immediately returns.
 */
export class AudioRecorder {
  private readonly onPcm: PcmListener;
  private readonly onError: RecorderErrorListener;
  private workerInstance?: worker.ThreadWorker;
  private running: boolean = false;
  private starting: boolean = false;
  private stopping: boolean = false;
  private startPromise?: Promise<void>;
  private resolveStart?: () => void;
  private stopPromise?: Promise<AudioRecorderStats>;
  private resolveStop?: (stats: AudioRecorderStats) => void;
  private lastStats: AudioRecorderStats = new AudioRecorderStats();

  constructor(onPcm: PcmListener, onError: RecorderErrorListener) {
    this.onPcm = onPcm;
    this.onError = onError;
  }

  async start(): Promise<void> {
    if (this.running) return;
    const alreadyStarting = this.startPromise;
    if (alreadyStarting !== undefined) {
      await alreadyStarting;
      return;
    }

    this.lastStats = new AudioRecorderStats();
    this.starting = true;
    const pending = new Promise<void>((resolve: () => void): void => {
      this.resolveStart = resolve;
    });
    this.startPromise = pending;

    try {
      const instance = new worker.ThreadWorker(CAPTURE_WORKER_URL, { name: 'SDK PCM capture worker' });
      this.workerInstance = instance;
      instance.onmessage = (event: MessageEvents): void => this.handleWorkerMessage(instance, event);
      instance.onmessageerror = (event: MessageEvents): void => {
        this.failWorker(instance, `录音线程消息解析失败：${event.type}`);
      };
      instance.onerror = (event: ErrorEvent): void => {
        this.failWorker(instance, `录音线程异常：${event.message}`);
      };
      instance.onexit = (code: number): void => {
        if (this.workerInstance === instance) {
          this.failWorker(instance, `录音线程意外退出：${code}`);
        }
      };
      instance.postMessage({ type: 'start' });
    } catch (e) {
      this.failWorker(this.workerInstance, `录音线程启动失败：${e}`);
    }

    await pending;
    if (this.startPromise === pending) this.startPromise = undefined;
  }

  async stop(): Promise<AudioRecorderStats> {
    const inFlightStop = this.stopPromise;
    if (inFlightStop !== undefined) return await inFlightStop;

    const inFlightStart = this.startPromise;
    if (inFlightStart !== undefined) await inFlightStart;
    // Two callers can both enter stop while start is pending. The first resumed caller owns the
    // stop transaction; every later continuation must join it instead of replacing its resolver.
    const stopAfterStart = this.stopPromise;
    if (stopAfterStart !== undefined) return await stopAfterStart;

    const instance = this.workerInstance;
    if (instance === undefined || !this.running) {
      if (instance !== undefined) this.terminateWorker(instance);
      this.starting = false;
      this.stopping = false;
      return this.lastStats;
    }

    this.stopping = true;
    const pending = new Promise<AudioRecorderStats>((resolve: (stats: AudioRecorderStats) => void): void => {
      this.resolveStop = resolve;
    });
    this.stopPromise = pending;
    try {
      instance.postMessage({ type: 'stop' });
    } catch (e) {
      this.failWorker(instance, `录音线程停止失败：${e}`);
    }
    const stats = await pending;
    if (this.stopPromise === pending) this.stopPromise = undefined;
    return stats;
  }

  isRecording(): boolean {
    return this.running || this.starting;
  }

  private handleWorkerMessage(instance: worker.ThreadWorker, event: MessageEvents): void {
    if (this.workerInstance !== instance) return;
    const type = event.data['type'] as string;
    if (type === 'pcm') {
      // Keep accepting PCM while stop is in flight. The worker sends stopped only after AudioCapturer
      // has stopped, and the message port preserves all earlier PCM messages ahead of that ack.
      if (this.running || this.starting) {
        const pcm = event.data['pcm'] as ArrayBuffer;
        if (pcm.byteLength > 0) this.onPcm(new Int16Array(pcm));
      }
      return;
    }
    if (type === 'started') {
      this.lastStats.bufferSizeBytes = Number(event.data['bufferSizeBytes']);
      this.starting = false;
      this.running = true;
      this.settleStart();
      return;
    }
    if (type === 'stopped') {
      const stats = this.readStats(event);
      this.lastStats = stats;
      this.running = false;
      this.starting = false;
      this.stopping = false;
      this.settleStart();
      const resolve = this.resolveStop;
      this.resolveStop = undefined;
      this.terminateWorker(instance);
      if (resolve !== undefined) resolve(stats);
      return;
    }
    if (type === 'error') {
      this.failWorker(instance, `${event.data['message']}`);
    }
  }

  private readStats(event: MessageEvents): AudioRecorderStats {
    const stats = new AudioRecorderStats();
    stats.overflowCount = Number(event.data['overflowCount']);
    stats.callbackCount = Number(event.data['callbackCount']);
    stats.totalBytes = Number(event.data['totalBytes']);
    stats.maxCallbackGapMs = Number(event.data['maxCallbackGapMs']);
    stats.lateCallbackCount = Number(event.data['lateCallbackCount']);
    stats.callbackGapExcessMs = Number(event.data['callbackGapExcessMs']);
    stats.maxCallbackWorkMs = Number(event.data['maxCallbackWorkMs']);
    stats.bufferSizeBytes = Number(event.data['bufferSizeBytes']);
    return stats;
  }

  private failWorker(instance: worker.ThreadWorker | undefined, message: string): void {
    if (instance !== undefined && this.workerInstance !== instance) return;
    this.running = false;
    this.starting = false;
    this.stopping = false;
    this.settleStart();
    const resolve = this.resolveStop;
    this.resolveStop = undefined;
    if (instance !== undefined) this.terminateWorker(instance);
    if (resolve !== undefined) resolve(this.lastStats);
    this.onError(message);
  }

  private settleStart(): void {
    const resolve = this.resolveStart;
    this.resolveStart = undefined;
    if (resolve !== undefined) resolve();
  }

  private terminateWorker(instance: worker.ThreadWorker): void {
    if (this.workerInstance !== instance) return;
    this.workerInstance = undefined;
    try {
      instance.terminate();
    } catch (e) {
      // The worker may already have terminated after a fatal error.
    }
  }
}
