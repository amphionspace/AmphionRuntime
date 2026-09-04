import { DiarizationPcmSpool } from './DiarizationPcmSpool';
import { SpeakerDiarizationInference, SpeakerDiarizationWindowResult } from 'amphion_asr';
import { fileIo as fs } from '@kit.CoreFileKit';
import { DingqiaoSpeakerModelAssets } from '../DingqiaoSpeakerModelAssets';
import { SpeakerDiarizationDegradedReason } from '../DingqiaoModels';
import { DiarizationInferenceWindow, DiarizationWindowScheduler } from './DiarizationWindowScheduler';

const SAMPLE_RATE: number = 16000;
const WINDOW_SAMPLES: number = 160000;
const INFERENCE_TIMEOUT_MS: number = 10000;
let nextDiarizationJobId: number = 1;

export interface DiarizationLocalWindowResult {
  jobId: string;
  windowStartSample: number;
  contentStartInWindowSample: number;
  realEndSample: number;
  commitStartSample: number;
  stableEndSample: number;
  finalWindow: boolean;
  result: SpeakerDiarizationWindowResult;
}

export interface SpeakerDiarizationLocalObserver {
  onWindow(result: DiarizationLocalWindowResult): void;
  onDrained(): void;
  onDegraded(reason: SpeakerDiarizationDegradedReason, message: string): void;
}

interface DiarizationLocalJob {
  jobId: string;
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

/**
 * Incremental on-device executor. PCM stays in the application sandbox and one
 * bounded 10-second window is processed at a time by SDK-bundled models.
 */
export class SpeakerDiarizationLocalClient {
  private readonly scheduler: DiarizationWindowScheduler = new DiarizationWindowScheduler(SAMPLE_RATE);
  private readonly queue: DiarizationLocalJob[] = [];
  private readonly jobDir: string;
  private readonly spool: DiarizationPcmSpool;
  private readonly observer: SpeakerDiarizationLocalObserver;
  private readonly inference: SpeakerDiarizationInference = new SpeakerDiarizationInference();
  private readonly inferenceLoad: Promise<void>;
  private readonly quiescentCallbacks: Array<() => void> = [];
  private nextJobId: number = 1;
  private activeJob?: DiarizationLocalJob;
  private finishing: boolean = false;
  private closed: boolean = false;
  private degraded: boolean = false;
  private resourcesClosed: boolean = false;
  private loadSettled: boolean = false;

  constructor(context: Context, workPath: string, observer: SpeakerDiarizationLocalObserver) {
    this.observer = observer;
    const localJobId = nextDiarizationJobId;
    nextDiarizationJobId += 1;
    this.jobDir = `${workPath}/speaker-diarization-jobs/job-${Date.now()}-${localJobId}`;
    this.ensureDir(this.jobDir);
    this.spool = new DiarizationPcmSpool(this.jobDir);
    this.inferenceLoad = this.inference.load(context, DingqiaoSpeakerModelAssets.bundledPath());
    this.inferenceLoad.then((): void => {
      this.loadSettled = true;
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
      const windows = this.scheduler.acceptSamples(audio.byteLength / 2);
      for (let index = 0; index < windows.length; index++) this.submit(windows[index]);
      this.pump();
    } catch (error) {
      this.fail(SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE,
        `speaker diarization spool failed: ${error}`);
    }
  }

  finish(): void {
    if (this.closed || this.finishing) return;
    this.finishing = true;
    if (!this.degraded) {
      try { this.submit(this.scheduler.finish()); } catch (error) {
        this.fail(SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE,
          `speaker diarization finish spool failed: ${error}`);
      }
    }
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


  private submit(window: DiarizationInferenceWindow): void {
    const jobId = `w${this.nextJobId.toString().padStart(8, '0')}`;
    this.nextJobId += 1;
    const realSamples = Math.max(0, window.realEndSample - window.startSample);
    const sampleCount = Math.min(WINDOW_SAMPLES, realSamples);
    const contentStartInWindowSample = WINDOW_SAMPLES - sampleCount;
    const offsetSample = Math.max(0, window.realEndSample - sampleCount);
    this.queue.push({
      jobId,
      offsetBytes: offsetSample * 2,
      sampleCount,
      windowStartSample: Math.max(0, window.realEndSample - WINDOW_SAMPLES),
      contentStartInWindowSample,
      realEndSample: window.realEndSample,
      commitStartSample: window.commitStartSample,
      stableEndSample: window.stableEndSample,
      finalWindow: window.finalWindow,
    });
  }

  private pump(): void {
    if (this.closed || this.degraded || this.activeJob !== undefined) return;
    const job = this.queue.shift();
    if (job === undefined) {
      this.maybeNotifyDrained();
      return;
    }
    this.activeJob = job;
    void this.execute(job);
  }

  private async execute(job: DiarizationLocalJob): Promise<void> {
    let timeout: number = -1;
    let inferencePromise: Promise<SpeakerDiarizationWindowResult> | undefined;
    try {
      const samples = this.readWindow(job);
      const timeoutPromise = new Promise<SpeakerDiarizationWindowResult>((_resolve,
        reject: (reason?: Object) => void): void => {
        timeout = setTimeout((): void => {
          reject(new Error('speaker diarization inference timed out'));
        }, INFERENCE_TIMEOUT_MS);
      });
      inferencePromise = this.inferenceLoad.then(
        (): Promise<SpeakerDiarizationWindowResult> => this.inference.process(samples));
      const result = await Promise.race([inferencePromise, timeoutPromise]);
      if (timeout >= 0) clearTimeout(timeout);
      timeout = -1;
      if (this.closed || this.degraded || this.activeJob?.jobId !== job.jobId) {
        await this.settleInference(inferencePromise);
        return;
      }
      this.observer.onWindow({
        jobId: job.jobId,
        windowStartSample: job.windowStartSample,
        contentStartInWindowSample: job.contentStartInWindowSample,
        realEndSample: job.realEndSample,
        commitStartSample: job.commitStartSample,
        stableEndSample: job.stableEndSample,
        finalWindow: job.finalWindow,
        result,
      });
    } catch (error) {
      if (!this.closed && !this.degraded && this.activeJob?.jobId === job.jobId) {
        const message = `${error}`;
        const reason = error instanceof SpeakerDiarizationStorageError ?
          SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE :
          (message.toLowerCase().indexOf('timeout') >= 0 ?
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
        const retainedOffset = this.queue.length > 0 ? this.queue[0].offsetBytes :
          Math.max(0, this.spool.endOffset() - WINDOW_SAMPLES * 2);
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

  private async settleInference(promise: Promise<Object>): Promise<void> {
    try { await promise; } catch (_ignored) {}
  }

  private readWindow(job: DiarizationLocalJob): Float32Array {
    let data: ArrayBuffer;
    try { data = this.spool.read(job.offsetBytes, job.sampleCount * 2); }
    catch (error) { throw new SpeakerDiarizationStorageError(`diarization PCM read failed: ${error}`); }
    const pcm = new Int16Array(data);
    const result = new Float32Array(WINDOW_SAMPLES);
    const offset = WINDOW_SAMPLES - pcm.length;
    for (let index = 0; index < pcm.length; index++) result[offset + index] = pcm[index] / 32768.0;
    return result;
  }

  private fail(reason: SpeakerDiarizationDegradedReason, message: string): void {
    if (this.degraded || this.closed) return;
    this.degraded = true;
    this.queue.splice(0, this.queue.length);
    this.observer.onDegraded(reason, message);
    this.maybeNotifyDrained();
  }

  private maybeNotifyDrained(): void {
    if (this.finishing && this.activeJob === undefined && this.queue.length === 0) {
      this.observer.onDrained();
    }
  }

  private closeWhenQuiescent(): void {
    if (!this.closed || !this.loadSettled || this.activeJob !== undefined || this.resourcesClosed) return;
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
