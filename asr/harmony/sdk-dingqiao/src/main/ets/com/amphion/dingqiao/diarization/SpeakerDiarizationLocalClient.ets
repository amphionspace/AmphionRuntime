import { DiarizationPcmSpool } from './DiarizationPcmSpool';
import { NmnetDiarizationInference, NmnetDiarizationDelta } from 'amphion_asr';
import { fileIo as fs } from '@kit.CoreFileKit';
import { SpeakerDiarizationDegradedReason } from '../DingqiaoModels';
import { DiarizationInferenceWindow, DiarizationWindowScheduler } from './DiarizationWindowScheduler';

const SAMPLE_RATE: number = 16000;
const WINDOW_SAMPLES: number = 320000;
// A native call cannot be interrupted; timing out only discards its result and
// every later window. When the system throttles a backgrounded app, a window on
// its single-threaded, low-priority worker can take tens of seconds while still
// progressing, so this bound only has to catch work that has stopped.
const INFERENCE_TIMEOUT_MS: number = 60000;
// History and overlap state require one ordered native lane per session.
const ENCODER_LANES: number = 1;
let nextDiarizationJobId: number = 1;

export interface DiarizationLocalWindowResult {
  jobId: string;
  generation: string;
  windowStartSample: number;
  contentStartInWindowSample: number;
  realEndSample: number;
  commitStartSample: number;
  stableEndSample: number;
  finalWindow: boolean;
  result: NmnetDiarizationDelta;
  /**
   * This window's share of executor capacity: the wall time of its native call
   * divided by the lanes. Summed over a session, it stays below the audio
   * duration while the executor keeps up, as it did with one window per call.
   */
  inferenceWallMs: number;
}

export interface SpeakerDiarizationLocalObserver {
  onWindow(result: DiarizationLocalWindowResult): void;
  onFlushed(delta: NmnetDiarizationDelta): void;
  onDrained(): void;
  onDegraded(reason: SpeakerDiarizationDegradedReason, message: string): void;
}

interface DiarizationLocalJob {
  jobId: string;
  generation: string;
  offsetBytes: number;
  sampleCount: number;
  windowStartSample: number;
  contentStartInWindowSample: number;
  realEndSample: number;
  commitStartSample: number;
  stableEndSample: number;
  finalWindow: boolean;
}

export class SpeakerDiarizationStorageError extends Error {
  constructor(message: string) { super(message); }
}

export interface SpeakerDiarizationLocalClientOptions {
  /** NMNet requires a fixed 20 s window and 2 s cadence. */
  hopMs?: number;
  /** Maximum queued descriptors behind the single native in-flight job. */
  maxPendingJobs?: number;
  /** The engine's ASR QoS request; role workers run one level below it. */
  recognizerQos?: string;
  /**
   * Where the speaker encoder runs: 'cpu' (the default when omitted), 'npu'
   * for an NNRt accelerator, or 'auto' to prefer one and fall back to the CPU.
   */
  encoderBackend?: string;
  /**
   * Explicit placement for the role workers: 'inherit' (default) keeps them on
   * the recognizer-derived policy, 'background' or 'utility' lets the scheduler
   * run the per-window burst at a lower operating point. Results are identical.
   */
  roleQos?: string;
}

/**
 * Incremental on-device executor. PCM stays in the application sandbox and one
 * bounded 20-second window is processed at a time by SDK-bundled models.
 */
export class SpeakerDiarizationLocalClient {
  private static readonly sweptJobRoots: Set<string> = new Set<string>();

  // Job files are removed when a client becomes quiescent, which a killed process never
  // reaches. The first client of a process removes whatever earlier processes left.
  private static sweepStaleJobs(root: string): void {
    if (SpeakerDiarizationLocalClient.sweptJobRoots.has(root)) return;
    SpeakerDiarizationLocalClient.sweptJobRoots.add(root);
    try {
      if (!fs.accessSync(root)) return;
      for (const name of fs.listFileSync(root)) {
        try { fs.rmdirSync(`${root}/${name}`); } catch (_ignored) {}
      }
    } catch (_ignored) {}
  }

  private readonly scheduler: DiarizationWindowScheduler;
  private readonly queue: DiarizationLocalJob[] = [];
  private readonly jobDir: string;
  private readonly spool: DiarizationPcmSpool;
  private readonly observer: SpeakerDiarizationLocalObserver;
  private readonly inference: NmnetDiarizationInference;
  private readonly maxPendingJobs: number;
  private flushing: boolean = false;
  private drainedNotified: boolean = false;
  private readonly inferenceLoad: Promise<void>;
  private readonly quiescentCallbacks: Array<() => void> = [];
  private nextJobId: number = 1;
  private activeJob?: DiarizationLocalJob;
  private activeJobStartedMs: number = 0;
  private finishing: boolean = false;
  private stopped: boolean = false;
  private finishWindowQueued: boolean = false;
  private closed: boolean = false;
  private degraded: boolean = false;
  private resourcesClosed: boolean = false;
  private loadSettled: boolean = false;
  private readonly diagnostic?: (event: string, fields: Record<string, Object>) => void;

  constructor(context: Context, workPath: string, observer: SpeakerDiarizationLocalObserver,
    diagnostic?: (event: string, fields: Record<string, Object>) => void,
    options?: SpeakerDiarizationLocalClientOptions, maxSpeakers: number = 0) {
    this.observer = observer;
    this.diagnostic = diagnostic;
    this.maxPendingJobs = options?.maxPendingJobs ?? 2;
    if (!Number.isInteger(this.maxPendingJobs) || this.maxPendingJobs <= 0) {
      throw new Error('maxPendingJobs must be a positive integer');
    }
    if (options?.hopMs !== undefined && options.hopMs !== 2000) throw new Error('NMNet requires a 2 s hop');
    if (options?.encoderBackend === 'npu') throw new Error('NMNet currently supports CPU inference only');
    this.scheduler = new DiarizationWindowScheduler(SAMPLE_RATE, 20_000, 2_000, 18_000);
    let roleQos = options?.roleQos ?? 'inherit';
    if (roleQos === 'inherit') {
      if (options?.recognizerQos === 'user-interactive') roleQos = 'user-initiated';
      else if (options?.recognizerQos === 'user-initiated') roleQos = 'default';
    }
    this.inference = new NmnetDiarizationInference(maxSpeakers, roleQos);
    const localJobId = nextDiarizationJobId;
    nextDiarizationJobId += 1;
    SpeakerDiarizationLocalClient.sweepStaleJobs(`${workPath}/speaker-diarization-jobs`);
    this.jobDir = `${workPath}/speaker-diarization-jobs/job-${Date.now()}-${localJobId}`;
    this.ensureDir(this.jobDir);
    this.spool = new DiarizationPcmSpool(this.jobDir);
    const loadStartedMs = Date.now();
    this.inferenceLoad = this.inference.load(context);
    this.inferenceLoad.then((): void => {
      if (this.diagnostic !== undefined) {
        const fields: Record<string, Object> = {};
        fields['loadMs'] = Date.now() - loadStartedMs;
        this.diagnostic('DIARIZATION_LOCAL_MODEL_READY', fields);
      }
      this.loadSettled = true;
      this.pump();
      this.maybeNotifyDrained();
      this.closeWhenQuiescent();
    }, (error: Object): void => {
      this.loadSettled = true;
      if (!this.closed && !this.degraded) {
        this.fail(SpeakerDiarizationDegradedReason.MODEL_UNAVAILABLE,
          `speaker diarization model load failed: ${error}`);
      }
      this.closeWhenQuiescent();
    });
  }

  append(audio: ArrayBuffer): void {
    if (this.closed || this.finishing || this.degraded) return;
    try {
      this.spool.append(audio);
      // Do not materialize every window that a fast producer makes. Descriptors
      // are pulled only up to the bounded pending capacity in pump().
      this.scheduler.acceptSamples(audio.byteLength / 2, 0);
      this.pump();
    } catch (error) {
      this.fail(SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE,
        `speaker diarization spool failed: ${error}`);
    }
  }

  /**
   * Windows owed to inference: spooled but unpulled, queued, and the one in flight.
   *
   * A finish cannot publish roles until this reaches zero, so its value at stop
   * separates "inference fell behind the audio" from "clustering was slow".
   */
  pendingWindowCount(): number {
    if (this.closed || this.degraded || this.stopped) return 0;
    return this.scheduler.availableCount() + this.queue.length +
      (this.activeJob !== undefined ? 1 : 0);
  }

  finish(): void {
    if (this.closed || this.finishing) return;
    this.finishing = true;
    // Normal windows are drained before the final padded window is issued.
    // finish() is called lazily by fillQueue(), after all normal descriptors
    // have been pulled, so a bounded queue cannot skip an owned interval.
    this.pump();
    this.maybeNotifyDrained();
  }

  cancel(onQuiescent?: () => void): void {
    if (onQuiescent !== undefined) this.quiescentCallbacks.push(onQuiescent);
    if (!this.closed) {
      this.closed = true;
      this.queue.splice(0, this.queue.length);
      this.closeSpool();
    }
    this.closeWhenQuiescent();
  }

  cleanup(onQuiescent?: () => void): void { this.cancel(onQuiescent); }

  /** Finish timeout: keep completed evidence, start no more windows, drop the in-flight one. */
  stopInference(): void {
    if (this.closed) return;
    this.stopped = true;
    this.queue.splice(0, this.queue.length);
  }

  private submit(window: DiarizationInferenceWindow | undefined): void {
    if (window === undefined) return;
    const jobId = `w${this.nextJobId.toString().padStart(8, '0')}`;
    this.nextJobId += 1;
    const realSamples = Math.max(0, window.realEndSample - window.startSample);
    const sampleCount = Math.min(WINDOW_SAMPLES, realSamples);
    const contentStartInWindowSample = 0;
    const offsetSample = window.startSample;
    this.queue.push({
      jobId,
      generation: jobId,
      offsetBytes: offsetSample * 2,
      sampleCount,
      windowStartSample: window.startSample,
      contentStartInWindowSample,
      realEndSample: window.realEndSample,
      commitStartSample: window.commitStartSample,
      stableEndSample: window.stableEndSample,
      finalWindow: window.finalWindow,
    });
  }

  private pump(): void {
    if (this.closed || this.degraded || this.stopped || this.activeJob !== undefined) return;
    this.fillQueue();
    const job = this.queue.shift();
    if (job === undefined) {
      this.maybeNotifyDrained();
      return;
    }
    // Consecutive queued windows share one native call; results keep this order.
    const batch: DiarizationLocalJob[] = [job];
    while (batch.length < ENCODER_LANES) {
      const next = this.queue.shift();
      if (next === undefined) break;
      batch.push(next);
    }
    this.activeJob = job;
    this.activeJobStartedMs = Date.now();
    void this.execute(batch);
  }

  private fillQueue(): void {
    if (this.closed || this.degraded || this.finishWindowQueued) return;
    const capacity = Math.max(0, this.maxPendingJobs - this.queue.length);
    if (capacity > 0) {
      const windows = this.scheduler.takeAvailable(capacity);
      for (let index = 0; index < windows.length; index++) this.submit(windows[index]);
    }
    if (this.finishing && !this.scheduler.hasAvailable() && this.queue.length < this.maxPendingJobs) {
      try {
        const tail = this.scheduler.finish();
        this.finishWindowQueued = true;
        this.submit(tail);
      } catch (error) {
        this.fail(SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE,
          `speaker diarization finish spool failed: ${error}`);
      }
    }
  }

  private async execute(batch: DiarizationLocalJob[]): Promise<void> {
    const job = batch[0];
    let timeout: number = -1;
    let inferenceTimedOut: boolean = false;
    let inferencePromise: Promise<NmnetDiarizationDelta[]> | undefined;
    try {
      const samples: Float32Array[] = batch.map((item: DiarizationLocalJob): Float32Array => this.readWindow(item));
      const timeoutPromise = new Promise<NmnetDiarizationDelta[]>((_resolve,
        reject: (reason?: Object) => void): void => {
        timeout = setTimeout((): void => {
          inferenceTimedOut = true;
          reject(new Error('speaker diarization inference timed out'));
        }, INFERENCE_TIMEOUT_MS);
      });
      inferencePromise = this.inferenceLoad.then(
        (): Promise<NmnetDiarizationDelta[]> => this.inference.process(samples[0], job.sampleCount, job.windowStartSample / 32000)
          .then((delta: NmnetDiarizationDelta): NmnetDiarizationDelta[] => [delta]));
      const results = await Promise.race([inferencePromise, timeoutPromise]);
      if (timeout >= 0) clearTimeout(timeout);
      timeout = -1;
      const wallShareMs = (Date.now() - this.activeJobStartedMs) / ENCODER_LANES;
      for (let index = 0; index < batch.length; index++) {
        // Publication can stop or degrade this client; never deliver past that.
        if (this.closed || this.degraded || this.stopped || this.activeJob?.jobId !== job.jobId ||
          this.activeJob?.generation !== job.generation) {
          await this.settleInference(inferencePromise);
          return;
        }
        this.deliver(batch[index], samples[index], results[index], wallShareMs);
      }
    } catch (error) {
      if (!this.closed && !this.degraded && !this.stopped && this.activeJob?.jobId === job.jobId) {
        const message = `${error}`;
        const reason = error instanceof SpeakerDiarizationStorageError ?
          SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE :
          (inferenceTimedOut || message.toLowerCase().indexOf('timeout') >= 0 ?
            SpeakerDiarizationDegradedReason.INFERENCE_TIMEOUT :
            (message.toLowerCase().indexOf('load') >= 0 || message.toLowerCase().indexOf('model') >= 0 ?
              SpeakerDiarizationDegradedReason.MODEL_UNAVAILABLE :
              SpeakerDiarizationDegradedReason.INFERENCE_UNAVAILABLE));
        this.fail(reason, `speaker diarization local inference failed: ${message}`);
      }
      if (inferencePromise !== undefined) await this.settleInference(inferencePromise);
    } finally {
      if (timeout >= 0) clearTimeout(timeout);
      if (this.activeJob?.jobId === job.jobId) this.activeJob = undefined;
      if (!this.closed) {
        // Keep the executor's isolated timeout harness independent of the full scheduler.
        const scheduledStart = this.scheduler?.nextWindowStartSample();
        const retainedOffset = this.queue.length > 0 ? this.queue[0].offsetBytes :
          (scheduledStart === undefined ?
            Math.max(0, this.spool.endOffset() - WINDOW_SAMPLES * 2) : scheduledStart * 2);
        try { this.spool.discardBefore(retainedOffset); }
        catch (error) { this.fail(SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE, `${error}`); }
      }
      if (this.closed) this.closeWhenQuiescent();
      else {
        this.pump();
        this.maybeNotifyDrained();
      }
    }
  }

  private deliver(job: DiarizationLocalJob, samples: Float32Array, result: NmnetDiarizationDelta,
    wallShareMs: number): void {
    if (this.diagnostic !== undefined) {
      const fields: Record<string, Object> = {};
      fields['jobId'] = job.jobId;
      fields['windowStartSample'] = job.windowStartSample;
      fields['realEndSample'] = job.realEndSample;
      fields['wallMs'] = wallShareMs;
      fields['segmentationMs'] = result.segmentationMs;
      fields['embeddingMs'] = result.embeddingMs;
      fields['embeddingFeaturesMs'] = result.embeddingFeaturesMs ?? -1;
      fields['embeddingEncoderMs'] = result.embeddingEncoderMs ?? -1;
      fields['pendingWindows'] = this.pendingWindowCount();
      fields['historyChunks'] = result.historyChunks;
      fields['historyCompressed'] = result.historyCompressed;
      this.diagnostic('DIARIZATION_LOCAL_WINDOW', fields);
    }
    this.observer.onWindow({
      jobId: job.jobId,
      generation: job.generation,
      windowStartSample: job.windowStartSample,
      contentStartInWindowSample: job.contentStartInWindowSample,
      realEndSample: job.realEndSample,
      commitStartSample: job.commitStartSample,
      stableEndSample: result.rolesCommittedThroughSample,
      finalWindow: job.finalWindow,
      result,
      inferenceWallMs: wallShareMs,
    });
  }

  private async settleInference(promise: Promise<Object>): Promise<void> {
    try { await promise; } catch (_ignored) {}
  }

  private readWindow(job: DiarizationLocalJob): Float32Array {
    let data: ArrayBuffer;
    try { data = this.spool.read(job.offsetBytes, job.sampleCount * 2); }
    catch (error) { throw new SpeakerDiarizationStorageError(`diarization PCM read failed: ${error}`); }
    const pcm = new Int16Array(data);
    const result = new Float32Array(WINDOW_SAMPLES);
    for (let index = 0; index < pcm.length; index++) result[index] = pcm[index] / 32768.0;
    return result;
  }

  private fail(reason: SpeakerDiarizationDegradedReason, message: string): void {
    if (this.degraded || this.closed) return;
    this.degraded = true;
    if (this.diagnostic !== undefined) {
      try {
        const fields: Record<string, Object> = {};
        fields['reason'] = reason;
        fields['message'] = message;
        fields['pendingJobs'] = this.queue.length;
        fields['finishing'] = this.finishing;
        if (this.activeJob !== undefined) {
          fields['jobId'] = this.activeJob.jobId;
          fields['realPcmRange'] = [this.activeJob.windowStartSample, this.activeJob.realEndSample];
          fields['startedMs'] = this.activeJobStartedMs;
          fields['elapsedMs'] = Date.now() - this.activeJobStartedMs;
        }
        this.diagnostic('DIARIZATION_LOCAL_FAILURE', fields);
      } catch (_ignored) {}
    }
    this.queue.splice(0, this.queue.length);
    this.observer.onDegraded(reason, message);
    this.maybeNotifyDrained();
  }

  private maybeNotifyDrained(): void {
    if (!this.finishing || this.closed || this.drainedNotified || this.flushing ||
      this.activeJob !== undefined || this.queue.length > 0 || !this.loadSettled) return;
    if (this.degraded || this.stopped) {
      this.drainedNotified = true;
      this.observer.onDrained();
      return;
    }
    if (!this.finishWindowQueued) return;
    this.flushing = true;
    void this.flushNative();
  }

  private async flushNative(): Promise<void> {
    try {
      const delta = await this.inference.finish();
      if (!this.closed && !this.stopped && !this.degraded) this.observer.onFlushed(delta);
    } catch (error) {
      if (!this.closed && !this.stopped) this.fail(SpeakerDiarizationDegradedReason.INFERENCE_UNAVAILABLE, `${error}`);
    } finally {
      this.flushing = false;
      if (!this.closed && !this.drainedNotified) {
        this.drainedNotified = true;
        this.observer.onDrained();
      }
      this.closeWhenQuiescent();
    }
  }

  private closeWhenQuiescent(): void {
    if (!this.closed || !this.loadSettled || this.activeJob !== undefined ||
      this.flushing || this.resourcesClosed) return;
    this.resourcesClosed = true;
    this.inference.close();
    this.removeJobFiles();
    const callbacks = this.quiescentCallbacks.splice(0, this.quiescentCallbacks.length);
    for (let index = 0; index < callbacks.length; index++) callbacks[index]();
  }

  private closeSpool(): void { this.spool.close(); }

  private removeJobFiles(): void {
    try {
      this.spool.remove();
      fs.rmdirSync(this.jobDir);
    } catch (_ignored) {}
  }

  private ensureDir(path: string): void {
    if (fs.accessSync(path)) return;
    const index = path.lastIndexOf('/');
    if (index > 0) this.ensureDir(path.substring(0, index));
    if (!fs.accessSync(path)) fs.mkdirSync(path);
  }
}
