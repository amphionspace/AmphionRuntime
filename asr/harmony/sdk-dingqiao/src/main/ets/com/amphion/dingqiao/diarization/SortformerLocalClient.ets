import { SortformerDiarizationInference, SortformerDiarizationEvent,
  SortformerDiarizationFeedResult } from 'amphion_asr';
import { SpeakerDiarizationDegradedReason } from '../DingqiaoModels';

const SAMPLE_RATE: number = 16000;
// Native work cannot be interrupted; a timeout only discards the session's
// later results. A chunk pass costs ~0.4 s on the CPU; this catches a stall.
const INFERENCE_TIMEOUT_MS: number = 60000;
// Audio is handed to the engine in batches of at least this much so a 20 ms
// producer does not cross NAPI fifty times a second; the engine itself only
// acts at chunk and preview boundaries, so batching changes no result.
const FEED_MIN_SAMPLES: number = SAMPLE_RATE / 2;
// Backlog the engine may fall behind the microphone before the session is
// declared stalled rather than quietly growing without bound.
const MAX_PENDING_SAMPLES: number = SAMPLE_RATE * 600;

/** One engine report, with frame indexes converted to session milliseconds. */
export interface SortformerLocalEvent {
  /** 'final' or 'preview'. */
  kind: string;
  beginTime: number;
  endTime: number;
  inferenceMs: number;
  /** Per slot (4), [beginTime, endTime) speech runs in milliseconds. */
  runs: number[][][];
}

export interface SortformerLocalFeedResult {
  jobId: string;
  /** Audio the engine has consumed through, in samples. */
  audioEndSample: number;
  /** Last mel frame the front end has produced, as a session time in ms. */
  melEndTime: number;
  events: SortformerLocalEvent[];
  /** Wall time of the native call. */
  inferenceWallMs: number;
  flushed: boolean;
}

export interface SortformerLocalObserver {
  onFeedResult(result: SortformerLocalFeedResult): void;
  onDrained(): void;
  onDegraded(reason: SpeakerDiarizationDegradedReason, message: string): void;
}

export interface SortformerLocalClientOptions {
  /** The engine's ASR QoS request; the role worker runs one level below it. */
  recognizerQos?: string;
  /** 'inherit' (default), 'background', 'utility' or 'default' for the role worker. */
  roleQos?: string;
  /** Provisional role refresh period in ms; 0 disables previews. */
  previewMs?: number;
  /** Encoder intra-op threads. */
  threads?: number;
}

/**
 * Incremental on-device executor for the Sortformer chain. PCM is queued in
 * memory and handed to one native engine in order; one call is in flight at a
 * time, so the speaker cache advances strictly in audio order.
 */
export class SortformerLocalClient {
  private readonly observer: SortformerLocalObserver;
  private readonly inference: SortformerDiarizationInference;
  private readonly inferenceLoad: Promise<void>;
  private readonly diagnostic?: (event: string, fields: Record<string, Object>) => void;
  private readonly pending: Int16Array[] = [];
  private pendingSamples: number = 0;
  private fedSamples: number = 0;
  private readonly quiescentCallbacks: Array<() => void> = [];
  private nextJobId: number = 1;
  private activeJobId: string = '';
  private activeJobStartedMs: number = 0;
  private finishing: boolean = false;
  private flushQueued: boolean = false;
  private flushed: boolean = false;
  private stopped: boolean = false;
  private closed: boolean = false;
  private degraded: boolean = false;
  private resourcesClosed: boolean = false;
  private loadSettled: boolean = false;

  constructor(context: Context, observer: SortformerLocalObserver,
    diagnostic?: (event: string, fields: Record<string, Object>) => void,
    options?: SortformerLocalClientOptions) {
    this.observer = observer;
    this.diagnostic = diagnostic;
    this.inference = new SortformerDiarizationInference(options?.threads ?? 2,
      options?.recognizerQos ?? 'default', options?.roleQos ?? 'inherit', options?.previewMs ?? 5000);
    this.inferenceLoad = this.inference.load(context);
    this.inferenceLoad.then((): void => {
      this.loadSettled = true;
      this.closeWhenQuiescent();
      this.pump();
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
    if (this.closed || this.finishing || this.degraded || this.stopped) return;
    const samples = new Int16Array(audio.slice(0, audio.byteLength - audio.byteLength % 2));
    if (samples.length === 0) return;
    this.pending.push(samples);
    this.pendingSamples += samples.length;
    if (this.pendingSamples > MAX_PENDING_SAMPLES) {
      this.fail(SpeakerDiarizationDegradedReason.INFERENCE_TIMEOUT,
        `speaker diarization fell ${Math.round(this.pendingSamples / SAMPLE_RATE)} s behind the audio`);
      return;
    }
    this.pump();
  }

  /** Audio not yet handed to the engine plus the call in flight, in whole seconds. */
  pendingWindowCount(): number {
    if (this.closed || this.degraded || this.stopped) return 0;
    return Math.ceil(this.pendingSamples / SAMPLE_RATE) + (this.activeJobId.length > 0 ? 1 : 0);
  }

  finish(): void {
    if (this.closed || this.finishing) return;
    this.finishing = true;
    this.pump();
    this.maybeNotifyDrained();
  }

  cancel(onQuiescent?: () => void): void {
    if (onQuiescent !== undefined) this.quiescentCallbacks.push(onQuiescent);
    if (!this.closed) {
      this.closed = true;
      this.pending.splice(0, this.pending.length);
      this.pendingSamples = 0;
    }
    this.closeWhenQuiescent();
  }

  cleanup(onQuiescent?: () => void): void { this.cancel(onQuiescent); }

  /** Finish timeout: keep delivered results, start no more calls, drop the in-flight one. */
  stopInference(): void {
    if (this.closed) return;
    this.stopped = true;
    this.pending.splice(0, this.pending.length);
    this.pendingSamples = 0;
  }

  private pump(): void {
    if (this.closed || this.degraded || this.stopped || !this.loadSettled || this.activeJobId.length > 0) return;
    const flush = this.finishing && !this.flushQueued;
    if (!flush && this.pendingSamples < FEED_MIN_SAMPLES) return;
    if (this.flushed) { this.maybeNotifyDrained(); return; }
    const samples = new Float32Array(this.pendingSamples);
    let offset = 0;
    for (const part of this.pending) {
      for (let index = 0; index < part.length; index++) samples[offset + index] = part[index] / 32768.0;
      offset += part.length;
    }
    this.pending.splice(0, this.pending.length);
    this.pendingSamples = 0;
    if (flush) this.flushQueued = true;
    const jobId = `f${this.nextJobId.toString().padStart(8, '0')}`;
    this.nextJobId += 1;
    this.activeJobId = jobId;
    this.activeJobStartedMs = Date.now();
    void this.execute(jobId, samples, flush);
  }

  private async execute(jobId: string, samples: Float32Array, flush: boolean): Promise<void> {
    let timeout: number = -1;
    let timedOut: boolean = false;
    let call: Promise<SortformerDiarizationFeedResult> | undefined;
    try {
      const timeoutPromise = new Promise<SortformerDiarizationFeedResult>((_resolve,
        reject: (reason?: Object) => void): void => {
        timeout = setTimeout((): void => {
          timedOut = true;
          reject(new Error('speaker diarization inference timed out'));
        }, INFERENCE_TIMEOUT_MS);
      });
      call = this.inference.feed(samples, flush);
      const result = await Promise.race([call, timeoutPromise]);
      if (timeout >= 0) clearTimeout(timeout);
      timeout = -1;
      const wallMs = Date.now() - this.activeJobStartedMs;
      if (this.closed || this.degraded || this.stopped || this.activeJobId !== jobId) {
        await this.settle(call);
        return;
      }
      this.fedSamples += samples.length;
      if (flush) this.flushed = true;
      this.deliver(jobId, result, wallMs, flush);
    } catch (error) {
      if (!this.closed && !this.degraded && !this.stopped && this.activeJobId === jobId) {
        const message = `${error}`;
        const lower = message.toLowerCase();
        const reason = timedOut || lower.indexOf('timeout') >= 0 ?
          SpeakerDiarizationDegradedReason.INFERENCE_TIMEOUT :
          (lower.indexOf('load') >= 0 || lower.indexOf('model') >= 0 || lower.indexOf('asset') >= 0 ?
            SpeakerDiarizationDegradedReason.MODEL_UNAVAILABLE :
            SpeakerDiarizationDegradedReason.INFERENCE_UNAVAILABLE);
        this.fail(reason, `speaker diarization local inference failed: ${message}`);
      }
      if (call !== undefined) await this.settle(call);
    } finally {
      if (timeout >= 0) clearTimeout(timeout);
      if (this.activeJobId === jobId) this.activeJobId = '';
      if (this.closed) this.closeWhenQuiescent();
      else {
        this.pump();
        this.maybeNotifyDrained();
      }
    }
  }

  private deliver(jobId: string, result: SortformerDiarizationFeedResult, wallMs: number, flush: boolean): void {
    const events: SortformerLocalEvent[] = [];
    for (const event of result.events) {
      events.push({
        kind: event.kind,
        beginTime: event.beginFrame * 10,
        endTime: (event.beginFrame + event.frames) * 10,
        inferenceMs: event.inferenceMs,
        runs: event.runs.map((slot: number[][]): number[][] =>
          slot.map((run: number[]): number[] => [run[0] * 10, run[1] * 10])),
      });
    }
    if (this.diagnostic !== undefined) {
      try {
        // Same shape the queue analyzers already read: how far the engine runs
        // behind the microphone and whether a call was in flight when it reported.
        const fields: Record<string, Object> = {};
        fields['jobId'] = jobId;
        fields['pendingJobs'] = Math.ceil(this.pendingSamples / SAMPLE_RATE);
        fields['nativeCallsInFlight'] = 1;
        fields['audioEndSample'] = this.fedSamples + this.pendingSamples;
        fields['completedThroughSample'] = result.samples;
        fields['audioDelayMs'] = Math.max(0, (this.fedSamples + this.pendingSamples - result.samples) / 16);
        fields['elapsedMs'] = wallMs;
        fields['melFrames'] = result.melFrames;
        fields['events'] = events.length;
        fields['flush'] = flush;
        this.diagnostic('DIARIZATION_QUEUE', fields);
      } catch (_ignored) {}
    }
    this.observer.onFeedResult({
      jobId,
      audioEndSample: result.samples,
      melEndTime: result.melFrames * 10,
      events,
      inferenceWallMs: wallMs,
      flushed: flush,
    });
  }

  private async settle(promise: Promise<Object>): Promise<void> {
    try { await promise; } catch (_ignored) {}
  }

  private fail(reason: SpeakerDiarizationDegradedReason, message: string): void {
    if (this.degraded || this.closed) return;
    this.degraded = true;
    if (this.diagnostic !== undefined) {
      try {
        const fields: Record<string, Object> = {};
        fields['reason'] = reason;
        fields['message'] = message;
        fields['pendingSamples'] = this.pendingSamples;
        fields['finishing'] = this.finishing;
        if (this.activeJobId.length > 0) {
          fields['jobId'] = this.activeJobId;
          fields['elapsedMs'] = Date.now() - this.activeJobStartedMs;
        }
        this.diagnostic('DIARIZATION_LOCAL_FAILURE', fields);
      } catch (_ignored) {}
    }
    this.pending.splice(0, this.pending.length);
    this.pendingSamples = 0;
    this.observer.onDegraded(reason, message);
    this.maybeNotifyDrained();
  }

  private maybeNotifyDrained(): void {
    if (this.finishing && this.activeJobId.length === 0 && (this.flushed || this.degraded || this.stopped)) {
      this.observer.onDrained();
    }
  }

  private closeWhenQuiescent(): void {
    if (!this.closed || !this.loadSettled || this.activeJobId.length > 0 || this.resourcesClosed) return;
    this.resourcesClosed = true;
    this.inference.close();
    const callbacks = this.quiescentCallbacks.splice(0, this.quiescentCallbacks.length);
    for (let index = 0; index < callbacks.length; index++) callbacks[index]();
  }
}
