import { DiarizationPcmSpool } from './DiarizationPcmSpool';
import { CommunityDiarizationInference, CommunityDiarizationWindow, CommunityDiarizationCluster } from 'amphion_asr';
import { fileIo as fs } from '@kit.CoreFileKit';
import { SpeakerDiarizationDegradedReason } from '../DingqiaoModels';
import { DiarizationInferenceWindow, DiarizationWindowScheduler } from './DiarizationWindowScheduler';

const SAMPLE_RATE: number = 16000;
const WINDOW_SAMPLES: number = 160000;
const INFERENCE_TIMEOUT_MS: number = 10000;
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
  result: CommunityDiarizationWindow;
}

export interface SpeakerDiarizationLocalObserver {
  onWindow(result: DiarizationLocalWindowResult): void;
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
  /** Community-1 keeps a 10 s native input; this only controls window cadence. */
  hopMs?: number;
  /** Maximum queued descriptors behind the single native in-flight job. */
  maxPendingJobs?: number;
}

/**
 * Incremental on-device executor. PCM stays in the application sandbox and one
 * bounded 10-second window is processed at a time by SDK-bundled models.
 */
export class SpeakerDiarizationLocalClient {
  private readonly scheduler: DiarizationWindowScheduler;
  private readonly queue: DiarizationLocalJob[] = [];
  private readonly jobDir: string;
  private readonly spool: DiarizationPcmSpool;
  private readonly observer: SpeakerDiarizationLocalObserver;
  private readonly inference: CommunityDiarizationInference = new CommunityDiarizationInference();
  private readonly maxPendingJobs: number;
  private pendingClusters: number = 0;
  private readonly inferenceLoad: Promise<void>;
  private readonly quiescentCallbacks: Array<() => void> = [];
  private nextJobId: number = 1;
  private activeJob?: DiarizationLocalJob;
  private activeJobStartedMs: number = 0;
  private finishing: boolean = false;
  private finishWindowQueued: boolean = false;
  private closed: boolean = false;
  private degraded: boolean = false;
  private resourcesClosed: boolean = false;
  private loadSettled: boolean = false;
  private readonly diagnostic?: (event: string, fields: Record<string, Object>) => void;

  constructor(context: Context, workPath: string, observer: SpeakerDiarizationLocalObserver,
    diagnostic?: (event: string, fields: Record<string, Object>) => void,
    options?: SpeakerDiarizationLocalClientOptions) {
    this.observer = observer;
    this.diagnostic = diagnostic;
    const hopMs = options?.hopMs ?? 2_000;
    this.maxPendingJobs = options?.maxPendingJobs ?? 2;
    if (!Number.isInteger(this.maxPendingJobs) || this.maxPendingJobs <= 0) {
      throw new Error('maxPendingJobs must be a positive integer');
    }
    this.scheduler = new DiarizationWindowScheduler(SAMPLE_RATE, 10_000, hopMs, 1_500);
    const localJobId = nextDiarizationJobId;
    nextDiarizationJobId += 1;
    this.jobDir = `${workPath}/speaker-diarization-jobs/job-${Date.now()}-${localJobId}`;
    this.ensureDir(this.jobDir);
    this.spool = new DiarizationPcmSpool(this.jobDir);
    this.inferenceLoad = this.inference.load(context);
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
      // Do not materialize every window that a fast producer makes. Descriptors
      // are pulled only up to the bounded pending capacity in pump().
      this.scheduler.acceptSamples(audio.byteLength / 2, 0);
      this.pump();
    } catch (error) {
      this.fail(SpeakerDiarizationDegradedReason.STORAGE_UNAVAILABLE,
        `speaker diarization spool failed: ${error}`);
    }
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

  async cluster(segments: Float32Array, embeddings: Float32Array,
    maxSpeakers: number): Promise<CommunityDiarizationCluster> {
    if (this.closed) throw new Error('speaker diarization client is closed');
    this.pendingClusters += 1;
    try {
      await this.inferenceLoad;
      if (this.closed) throw new Error('speaker diarization client is closed');
      return await this.inference.cluster(segments, embeddings, maxSpeakers);
    } finally {
      this.pendingClusters -= 1;
      this.closeWhenQuiescent();
    }
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
    if (this.closed || this.degraded || this.activeJob !== undefined) return;
    this.fillQueue();
    const job = this.queue.shift();
    if (job === undefined) {
      this.maybeNotifyDrained();
      return;
    }
    this.activeJob = job;
    this.activeJobStartedMs = Date.now();
    void this.execute(job);
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

  private async execute(job: DiarizationLocalJob): Promise<void> {
    let timeout: number = -1;
    let inferenceTimedOut: boolean = false;
    let inferencePromise: Promise<CommunityDiarizationWindow> | undefined;
    try {
      const samples = this.readWindow(job);
      const timeoutPromise = new Promise<CommunityDiarizationWindow>((_resolve,
        reject: (reason?: Object) => void): void => {
        timeout = setTimeout((): void => {
          inferenceTimedOut = true;
          reject(new Error('speaker diarization inference timed out'));
        }, INFERENCE_TIMEOUT_MS);
      });
      inferencePromise = this.inferenceLoad.then(
        (): Promise<CommunityDiarizationWindow> => this.inference.process(samples));
      const result = await Promise.race([inferencePromise, timeoutPromise]);
      if (timeout >= 0) clearTimeout(timeout);
      timeout = -1;
      if (this.closed || this.degraded || this.activeJob?.jobId !== job.jobId ||
        this.activeJob?.generation !== job.generation) {
        await this.settleInference(inferencePromise);
        return;
      }
      this.recordWindowSamples(job, samples, result);
      this.observer.onWindow({
        jobId: job.jobId,
        generation: job.generation,
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

  private async settleInference(promise: Promise<Object>): Promise<void> {
    try { await promise; } catch (_ignored) {}
  }

  private recordWindowSamples(job: DiarizationLocalJob, samples: Float32Array,
    result: CommunityDiarizationWindow): void {
    if (this.diagnostic === undefined) return;
    try {
      for (let channel = 0; channel < 3; channel++) {
        const active: number[] = [];
        const clean: number[] = [];
        let cleanCount: number = 0;
        for (let frame = 0; frame < 589; frame++) {
          const count = result.segments[frame * 3] + result.segments[frame * 3 + 1] +
            result.segments[frame * 3 + 2];
          active.push(result.segments[frame * 3 + channel]);
          clean.push(count === 1 ? active[frame] : 0);
          cleanCount += clean[frame];
        }
        const mask = cleanCount > 2 ? clean : active;
        const ranges: number[][] = [];
        for (let frame = 0; frame < 589; frame++) {
          if (mask[frame] === 0) continue;
          const begin = frame * 270;
          const end = Math.min(job.sampleCount, begin + 991);
          if (begin >= end) continue;
          const previous = ranges[ranges.length - 1];
          if (previous !== undefined && previous[1] >= begin) previous[1] = end;
          else ranges.push([begin, end]);
        }
        let energy: number = 0;
        let count: number = 0;
        for (const range of ranges) {
          for (let sample = range[0]; sample < range[1]; sample++) {
            energy += samples[sample] * samples[sample]; count += 1;
          }
        }
        const valid = result.embeddings.slice(channel * 256, (channel + 1) * 256)
          .every((value: number): boolean => Number.isFinite(value));
        const fields: Record<string, Object> = {};
        fields['jobId'] = job.jobId;
        fields['evidenceKey'] = `${job.jobId}:${channel}`;
        fields['localChannel'] = channel;
        fields['realPcmRange'] = [job.windowStartSample, job.realEndSample];
        fields['featurePcmRange'] = [job.windowStartSample, job.windowStartSample + WINDOW_SAMPLES];
        fields['rightZeroPadSamples'] = WINDOW_SAMPLES - job.sampleCount;
        fields['featureSampleRate'] = SAMPLE_RATE;
        fields['featureFrames'] = 998;
        fields['selectedSegmentationMask'] = mask;
        fields['maskReason'] = cleanCount > 2 ? 'CLEAN_FRAMES' : 'FULL_ACTIVITY_TOO_FEW_CLEAN_FRAMES';
        fields['cleanFrames'] = cleanCount;
        fields['maskReceptivePcmRanges'] = ranges.map(range =>
          [range[0] + job.windowStartSample, range[1] + job.windowStartSample]);
        fields['maskReceptivePcmRms'] = count > 0 ? Math.sqrt(energy / count) : 0;
        fields['levelFilter'] = 'NONE';
        fields['embeddingSelection'] = 'FULL_WINDOW_FEATURES_WITH_MASKED_STATISTICS';
        fields['clusteringEligibility'] = !valid ? 'INVALID_EMBEDDING' :
          cleanCount >= 0.2 * 589 ? 'ELIGIBLE' : 'INSUFFICIENT_CLEAN_ACTIVITY';
        this.diagnostic('DIARIZATION_COMMUNITY_SAMPLES', fields);
      }
    } catch (_ignored) {
      // Diagnostic bookkeeping cannot alter sampling or publication.
    }
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
    if (this.finishing && this.activeJob === undefined && this.queue.length === 0) {
      this.observer.onDrained();
    }
  }

  private closeWhenQuiescent(): void {
    if (!this.closed || !this.loadSettled || this.activeJob !== undefined ||
      this.pendingClusters > 0 || this.resourcesClosed) return;
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
